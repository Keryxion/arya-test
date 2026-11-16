"""Async headless Arya: reads continuously, models speaker drain, validates frames."""
import asyncio
import contextlib
import json
import time
import uuid
from dataclasses import dataclass, field

import aiohttp

from .audio import Opus, speech


@dataclass
class Turn:
    pcm: bytearray = field(default_factory=bytearray)
    speaking: bool = False
    done: dict | None = None
    interrupted: bool = False
    tool_calls: int = 0
    reasoning: int | None = None
    first_audio: float | None = None
    speaker_until: float = 0
    decoder: Opus | None = None
    drained: asyncio.Event = field(default_factory=asyncio.Event)


class Client:
    def __init__(self, url, key, device=None, **start):
        self.url, self.key = url, key
        self.start = dict(type='start', assistant_name='Arya', device_name=device or f'arya-test-{uuid.uuid4().hex}',
                          input_rate=16000, output_rate=24000)
        self.start.update(start)
        self.events, self.turns = [], {}
        self.active_audio = None
        self.changed = asyncio.Event()
        self.failure = None
        self.offending_frame = None
        self.closed = False
        self.http = self.ws = self.reader = None
        self.encoder = None
        self.ambient = None
        self.tasks = []
        self.ready = None

    async def connect(self, browser=False, select=True):
        self.http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20))
        try:
            protocols = ['hermes-voice-v1', 'hermes-key.' + self.key] if browser else []
            self.ws = await self.http.ws_connect(self.url, protocols=protocols, max_msg_size=8*1024*1024)
            assert self.ws.protocol == ('hermes-voice-v1' if browser else None), 'wrong/secret subprotocol echoed'
            self.reader = asyncio.create_task(self._read())
            await self.send({**self.start, **({} if browser else {'key': self.key})})
            self.ready = await self.wait('ready')
            self._validate_ready()
            if self.start.get('audio_format') == 'opus':
                self.encoder = Opus(self.ready['input']['sample_rate'], encode=True)
            if select:
                await self.select_free()
            return self
        except BaseException:
            await self.close()
            raise

    def _validate_ready(self):
        r = self.ready
        for k in ['session_id', 'recipient_id']:
            assert isinstance(r.get(k), str) and r[k], f'ready.{k} missing'
        for k in ['assistant_name', 'device_name']:
            assert r.get(k) == self.start[k], f'ready.{k} mismatch'
        assert r.get('transcripts') is (self.start.get('transcripts') is True)
        fmt = self.start.get('audio_format', 'pcm16')
        for direction, requested in [('input', 'input_rate'), ('output', 'output_rate')]:
            assert r[direction]['sample_rate'] == self.start[requested]
            assert r[direction]['format'] == fmt
        assert r['input']['block_ms'] == (20 if fmt == 'opus' else 30)
        if fmt == 'opus':
            assert r['output']['block_ms'] == 20
        assert type(r['server_recv_unix_ms']) is int and type(r['server_send_unix_ms']) is int
        assert 0 < r['server_recv_unix_ms'] <= r['server_send_unix_ms']
        if self.start.get('models') is not True:
            assert 'model_catalog' not in r, 'unsolicited model inventory'
        if 'after' in self.start:
            assert type(r.get('new_session')) is bool

    async def select_free(self):
        rid = uuid.uuid4().hex
        await self.send(type='set_model', request_id=rid, model='free')
        e = await self.wait('model_changed', request_id=rid)
        assert e['model'] == 'free' and e['uses_default'] is False and e['applies_to'] == 'next_turn'

    async def send(self, data=None, **kwargs):
        await self.ws.send_json(data if data is not None else kwargs)

    async def _read(self):
        try:
            async for msg in self.ws:
                now = time.monotonic()
                if msg.type == aiohttp.WSMsgType.BINARY:
                    assert self.active_audio is not None, 'binary before speaking or after completion'
                    t = self.turns[self.active_audio]
                    pcm = t.decoder.decode(msg.data) if t.decoder else msg.data
                    assert pcm and len(pcm) % 2 == 0, 'invalid PCM16 reply'
                    t.pcm.extend(pcm)
                    t.first_audio = t.first_audio or now
                    rate = self.start['output_rate']
                    # 1.5s allowed lead plus 0.75s scheduling/transit tolerance.
                    assert len(t.pcm)/(rate*2) <= now-t.first_audio+2.25, 'server audio exceeds playback lead'
                    t.speaker_until = max(now, t.speaker_until) + len(pcm)/(rate*2)
                elif msg.type == aiohttp.WSMsgType.TEXT:
                    assert self.key not in msg.data, 'server echoed API credential'
                    e = json.loads(msg.data)
                    assert isinstance(e, dict) and isinstance(e.get('type'), str), 'invalid JSON frame'
                    self.offending_frame = e
                    self._validate(e, now)
                    self.offending_frame = None
                    self.events.append(e)
                    if e['type'] == 'speaking':
                        await self.send(type='state', turn_id=e['turn_id'], state='speaking')
                    if e['type'] == 'turn_done':
                        self.tasks.append(asyncio.create_task(self._drain(e['turn_id'])))
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    raise AssertionError('WebSocket transport failure')
                self.changed.set()
        except Exception as exc:
            self.failure = exc
        finally:
            self.closed = True
            self.changed.set()

    def _validate(self, e, now):
        kind = e['type']
        if kind == 'transcript':
            assert self.start.get('transcripts') is True, 'unsolicited transcript'
            assert e.get('role') in ('user', 'assistant') and isinstance(e.get('text'), str)
            assert isinstance(e.get('turn_id'), str) and e['turn_id']
            if e.get('replay'):
                assert e.get('message_id'), 'replay missing cursor'
                return
        if kind in {'thinking', 'speaking', 'state', 'transcript', 'interrupted', 'turn_done'} or (kind == 'error' and 'turn_id' in e):
            tid = e.get('turn_id')
            assert isinstance(tid, str) and tid, f'{kind} missing turn_id'
            t = self.turns.setdefault(tid, Turn())
            if kind == 'thinking':
                assert not t.done and not t.interrupted, 'liveness after terminal frame'
                count, reason = e.get('tool_calls'), e.get('reasoning_tokens')
                assert type(count) is int and count >= t.tool_calls
                assert reason is None or (type(reason) is int and reason >= (t.reasoning or 0))
                if not any(x.get('turn_id') == tid and x['type'] == 'thinking' for x in self.events):
                    assert count == 0 and reason is None, 'initial counters not reset'
                assert not {'tools', 'arguments', 'results', 'reasoning'} & e.keys()
                t.tool_calls, t.reasoning = count, reason
            elif kind == 'state':
                assert e.get('state') in ('thinking', 'speaking', 'listening')
            elif kind == 'speaking':
                assert not t.done and not t.interrupted
                assert self.active_audio in (None, tid), 'interleaved untagged audio'
                if not t.speaking and self.start.get('audio_format') == 'opus':
                    t.decoder = Opus(self.start['output_rate'])
                t.speaking = True
                self.active_audio = tid
            elif kind == 'transcript':
                if e['role'] == 'user':
                    assert e.get('message_id'), 'user transcript missing message_id'
                    assert any(x['type'] == 'thinking' and x.get('turn_id') == tid for x in self.events), 'user transcript before thinking'
                elif e.get('message_id'):
                    assert e['text'] == '' and not t.interrupted, 'invalid assistant closing transcript'
                else:
                    assert e['text'], 'empty transcript without cursor'
            elif kind == 'interrupted':
                t.interrupted, t.speaker_until = True, now
                if self.active_audio == tid:
                    self.active_audio = None
            elif kind == 'turn_done':
                assert e.get('next_action') in ('listen', 'standby')
                if t.interrupted:
                    assert e['next_action'] == 'listen'
                t.done = e
                if self.active_audio == tid:
                    self.active_audio = None
        if kind == 'error':
            assert isinstance(e.get('error'), str) and e['error'], 'missing spoken-safe error'
            assert 'Traceback (most recent call last)' not in e['error'], 'internal traceback exposed'
        if kind == 'countdown':
            assert isinstance(e.get('countdown_id'), str) and e['countdown_id']
            assert type(e.get('deadline_unix_ms')) in (int, float)
            assert type(e.get('ring_seconds')) in (int, float) and e['ring_seconds'] > 0
            assert e.get('sound') in ('alarm-1', 'alarm-2', 'alarm-3', 'alarm-4')
        if kind == 'tone':
            assert e.get('tone') in ('confirm', 'error', 'approval') and 'turn_id' not in e
        if kind == 'approval_request':
            assert e.get('approval_id') and e.get('turn_id')
            assert isinstance(e.get('summary'), str) and isinstance(e.get('command'), str)
            assert e.get('choices') and set(e['choices']) <= {'once', 'session', 'always', 'deny'}
        if kind == 'approval_resolved':
            assert e.get('approval_id') and e.get('outcome') in ('approved', 'denied', 'expired', 'cancelled')

    async def wait(self, kind, *, after=0, timeout=25, **fields):
        async with asyncio.timeout(timeout):
            while True:
                self.changed.clear()
                if self.failure:
                    raise self.failure
                for e in self.events[after:]:
                    if e['type'] == kind and all(e.get(k) == v for k, v in fields.items()):
                        return e
                assert not self.closed, f'socket closed ({self.ws.close_code}) waiting for {kind}'
                await self.changed.wait()

    async def quiet_for(self, seconds, forbidden):
        offset = len(self.events)
        await asyncio.sleep(seconds)
        if self.failure:
            raise self.failure
        assert not self.closed, 'unexpected close'
        assert not any(e['type'] in forbidden for e in self.events[offset:]), f'unexpected {forbidden}'

    async def pcm(self, data):
        rate = self.start['input_rate']
        block = rate // 50 if self.encoder else rate * 30 // 1000
        size, seconds = block * 2, block/rate
        clock = asyncio.get_running_loop().time()
        for pos in range(0, len(data), size):
            frame = data[pos:pos+size].ljust(size, b'\0')
            await self.ws.send_bytes(self.encoder.encode(frame) if self.encoder else frame)
            clock += seconds
            await asyncio.sleep(max(0, clock-asyncio.get_running_loop().time()))

    async def utterance(self, text, commit=True):
        pcm = await speech(text, self.start['input_rate'])
        await self.stop_ambient()
        offset = len(self.events)
        await self.pcm(pcm)
        if self.encoder:  # flush codec lookahead without resetting its stream state
            await self.pcm(bytes(self.start['input_rate']//50*2*3))
        if commit:
            await self.send(commit=True)
        else:
            await self.pcm(bytes(self.start['input_rate']*2*5))
        self.ambient = asyncio.create_task(self._ambient())
        return offset

    async def _ambient(self):
        # Test microphone fixture: room silence between synthesized utterances.
        while not self.closed:
            await self.pcm(bytes(self.start['input_rate'] * 2 // 5))

    async def stop_ambient(self):
        if self.ambient:
            self.ambient.cancel()
            with contextlib.suppress(asyncio.CancelledError, ConnectionError):
                await self.ambient
            self.ambient = None

    async def _drain(self, tid):
        t = self.turns[tid]
        try:
            await asyncio.sleep(max(0, t.speaker_until-time.monotonic()))
            if not self.closed:
                await self.send(type='state', turn_id=tid,
                                state='listening' if t.done['next_action']=='listen' else 'standby')
        finally:
            t.drained.set()

    async def finish(self, offset=0, audio=True, user=False):
        fields = {}
        if user:
            transcript = await self.wait('transcript', after=offset, role='user', timeout=60)
            fields['turn_id'] = transcript['turn_id']
        done = await self.wait('turn_done', after=offset, timeout=160, **fields)
        tid = done['turn_id']
        t = self.turns[tid]
        errors = [e for e in self.events[offset:] if e['type'] == 'error' and e.get('turn_id') == tid]
        assert not errors, 'live turn returned an error'
        if audio:
            assert len(t.pcm) > 0 and any(t.pcm), 'no audible reply PCM'
        await asyncio.wait_for(t.drained.wait(), 160)
        if done['next_action'] == 'standby':
            await self.stop_ambient()
        return done

    async def close(self):
        await self.stop_ambient()
        if self.ws and not self.ws.closed:
            with contextlib.suppress(Exception):
                await self.send(stop=True)
            await self.ws.close()
        if self.reader:
            await self.reader
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        if self.encoder:
            self.encoder.close()
        for t in self.turns.values():
            if t.decoder:
                t.decoder.close()
        if self.http:
            await self.http.close()
