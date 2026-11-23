"""Async headless Arya: reads continuously, models speaker drain, validates frames."""
import asyncio
import contextlib
import json
import time
import uuid
import unicodedata
from dataclasses import dataclass, field

import aiohttp

from .audio import Opus, speech
from .wake import validate_wake_word


class AudioUnavailable(Exception):
    """The server explicitly declined optional audio with the documented 4503."""


@dataclass
class Turn:
    pcm: bytearray = field(default_factory=bytearray)
    speaking: bool = False
    done: dict | None = None
    interrupted: bool = False
    failed: bool = False
    resumed: bool = False
    saw_thinking: bool = False
    resume_state: bool = False
    tool_calls: int = 0
    reasoning: int | None = None
    first_audio: float | None = None
    speaker_until: float = 0
    decoder: Opus | None = None
    drained: asyncio.Event = field(default_factory=asyncio.Event)


class Client:
    def __init__(self, url, key, device=None, resume=None, **start):
        self.url, self.key = url, key
        self.start = dict(type='start', assistant_name='Arya', device_name=device or f'arya-test-{uuid.uuid4().hex}',
                          input_rate=16000, output_rate=24000)
        self.start.update(start)
        self.events, self.turns = [], {}
        self.pending_interruption = None
        self.resume = resume
        self.snapshot_turn = None
        self.activation = False
        self.muted = False
        self.transient_turns = set()
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

    @staticmethod
    def _validate_current_model(state):
        assert isinstance(state, dict), 'missing current_model'
        for key in ('model', 'provider', 'reasoning_override', 'reasoning_level'):
            assert key in state and (state[key] is None or isinstance(state[key], str)), key
        assert type(state.get('pending')) is bool, 'missing reasoning pending state'
        assert state.get('reasoning_support') in ('supported', 'unknown', 'unsupported')
        levels = state.get('reasoning_levels')
        assert isinstance(levels, list) and all(isinstance(v, str) and v for v in levels)
        # unknown may list the levels the gateway accepts; only supported must confirm some.
        assert levels or state['reasoning_support'] != 'supported', 'supported reasoning without levels'

    def _validate_ready(self):
        r = self.ready
        for k in ['session_id', 'recipient_id']:
            assert isinstance(r.get(k), str) and r[k], f'ready.{k} missing'
        for k in ['assistant_name', 'device_name']:
            expected = unicodedata.normalize('NFC', ' '.join(self.start[k].split()))
            assert r.get(k) == expected, f'ready.{k} mismatch'
        assert r.get('transcripts') is (self.start.get('transcripts') is True)
        if 'wake_word_format' in self.start:
            assert 'wake_word' in r, 'ready.wake_word missing for a wake-word device'
            validate_wake_word(r['wake_word'], self.start['wake_word_format'])
        else:
            assert 'wake_word' not in r, 'ready.wake_word sent to a device without wake_word_format'
        self._validate_current_model(r.get('current_model'))
        fmt = self.start.get('audio_format', 'pcm16')
        for direction, requested in [('input', 'input_rate'), ('output', 'output_rate')]:
            rate = self.start[requested]
            if fmt == 'pcm16':
                rate = max(8000, min(48000, rate)) if type(rate) is int else (16000 if direction == 'input' else 24000)
            assert r[direction]['sample_rate'] == rate, f'{direction} rate mismatch'
            self.start[requested] = rate
            assert r[direction]['format'] == fmt
        assert r['input']['block_ms'] == (20 if fmt == 'opus' else 30)
        if fmt == 'opus':
            assert r['output']['block_ms'] == 20
        assert type(r['server_recv_unix_ms']) is int and type(r['server_send_unix_ms']) is int
        assert 0 < r['server_recv_unix_ms'] <= r['server_send_unix_ms']
        if self.start.get('models') is not True:
            assert 'model_catalog' not in r, 'unsolicited model inventory'
        if isinstance(self.start.get('after'), str):
            assert type(r.get('new_session')) is bool

    async def setting_command(self, name, args):
        offset = len(self.events)
        await self.send(type='command', name=name, args=args)
        return await self.wait('command', after=offset, name=name, args=args)

    async def current_model(self):
        offset = len(self.events)
        await self.send(type='current_model')
        return (await self.wait('current_model', after=offset))['current_model']

    async def select_free(self):
        catalog = self.ready.get('model_catalog', {})
        provider = next((p['slug'] for p in catalog.get('providers', []) if 'free' in p['models']), None)
        args = ['free', '--provider', provider, '--session'] if provider else ['free', '--session']
        result = await self.setting_command('model', args)
        state = result['current_model']
        assert 'error' not in result and state['model'] == 'free' and not state['pending'], result
        assert provider is None or state['provider'] == provider, state

    async def send(self, data=None, **kwargs):
        frame = data if data is not None else kwargs
        if frame.get('type') == 'say' and isinstance(frame.get('text'), str) and frame['text'].strip():
            self.transient_turns.add(None)  # bind to the next thinking frame
        await self.ws.send_json(frame)

    async def _read(self):
        try:
            async for msg in self.ws:
                now = time.monotonic()
                if msg.type == aiohttp.WSMsgType.BINARY:
                    self._audio(msg.data, now)
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
                    if e['type'] == 'turn_done' and e.get('next_action') == 'mute':
                        self.muted, self.activation = True, False
                        await self.stop_ambient()
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

    def _audio(self, packet, now):
        assert self.pending_interruption is None, 'audio between interruption and completion'
        assert self.active_audio is not None, 'binary before speaking or after completion'
        t = self.turns[self.active_audio]
        if self.start.get('transcripts') is True and self.active_audio not in self.transient_turns:
            events = [e for e in self.events if e.get('turn_id') == self.active_audio]
            approval_question = any(e['type']=='approval_request' for e in events)
            assert approval_question or any(e['type']=='transcript' and e.get('role')=='assistant' and e.get('text') and not e.get('replay') for e in events), 'reply audio before live transcript text'
        pcm = t.decoder.decode(packet) if t.decoder else packet
        assert pcm and len(pcm) % 2 == 0, 'invalid PCM16 reply'
        t.pcm.extend(pcm)
        t.first_audio = t.first_audio or now
        rate = self.start['output_rate']
        # 1.5s allowed lead plus 0.75s scheduling/transit tolerance.
        assert len(t.pcm)/(rate*2) <= now-t.first_audio+2.25, 'server audio exceeds playback lead'
        t.speaker_until = max(now, t.speaker_until) + len(pcm)/(rate*2)

    def _validate(self, e, now):
        kind = e['type']
        if kind == 'current_model' or (kind == 'command' and e.get('name') in ('model', 'reasoning')):
            self._validate_current_model(e.get('current_model'))
            if kind == 'command':
                assert isinstance(e.get('reply'), str) != isinstance(e.get('error'), str), e
        if kind == 'set_wake_word':
            assert 'wake_word_format' in self.start, 'set_wake_word sent to a device without wake_word_format'
            validate_wake_word(e, self.start['wake_word_format'])
        tid = e.get('turn_id')
        if self.pending_interruption is not None and tid is not None:
            assert tid == self.pending_interruption and kind == 'turn_done', 'new/old turn frame before interrupted turn completes'
        if tid in self.turns and self.turns[tid].interrupted:
            assert kind == 'turn_done', 'frame after interruption'
        if kind == 'transcript':
            assert self.start.get('transcripts') is True, 'unsolicited transcript'
            assert e.get('role') in ('user', 'assistant') and isinstance(e.get('text'), str)
            assert isinstance(e.get('turn_id'), str) and e['turn_id']
            if e.get('replay'):
                assert not any(x['type'] in ('thinking', 'speaking', 'state') for x in self.events), 'replay after live output'
                if not e.get('message_id'):
                    assert e['role'] == 'assistant', 'user replay missing cursor'
                    assert self.snapshot_turn is None, 'multiple running-text snapshots'
                    assert not any(x['type'] in ('thinking', 'speaking', 'state') for x in self.events), 'snapshot after live output'
                    self.snapshot_turn = tid
                    self.turns.setdefault(tid, Turn()).resumed = True
                else:
                    assert self.snapshot_turn is None, 'history after running-text snapshot'
                return
        if kind in {'thinking', 'speaking', 'state', 'transcript', 'interrupted', 'turn_done'} or (kind == 'error' and 'turn_id' in e):
            tid = e.get('turn_id')
            assert isinstance(tid, str) and tid, f'{kind} missing turn_id'
            t = self.turns.setdefault(tid, Turn())
            if self.resume and tid == self.resume['turn_id']:
                t.resumed = True
            if t.resumed and not t.saw_thinking and kind not in ('state', 'thinking'):
                raise AssertionError('resumed live frame before state and thinking')
            if kind == 'thinking':
                if None in self.transient_turns:
                    self.transient_turns.remove(None)
                    self.transient_turns.add(tid)
                assert not t.done and not t.interrupted, 'liveness after terminal frame'
                count, reason = e.get('tool_calls'), e.get('reasoning_tokens')
                assert type(count) is int and count >= t.tool_calls
                assert reason is None or (type(reason) is int and reason >= (t.reasoning or 0))
                if not t.saw_thinking:
                    if t.resumed:
                        assert t.resume_state, 'resumed thinking before state'
                        baseline = self.resume if self.resume and tid == self.resume['turn_id'] else {}
                        assert count >= baseline.get('tool_calls', 0), 'resumed tool counter reset'
                        previous = baseline.get('reasoning_tokens')
                        assert previous is None or (reason is not None and reason >= previous), 'resumed reasoning counter reset'
                    else:
                        assert count == 0 and reason is None, 'initial counters not reset'
                t.saw_thinking = True
                assert not {'tools', 'arguments', 'results', 'reasoning'} & e.keys()
                t.tool_calls, t.reasoning = count, reason
            elif kind == 'state':
                t.resume_state = True
                assert e.get('state') in ('thinking', 'speaking', 'listening')
            elif kind == 'speaking':
                assert not t.done and not t.interrupted
                assert self.active_audio in (None, tid), 'interleaved untagged audio'
                if not t.speaking and self.start.get('audio_format') == 'opus':
                    t.decoder = Opus(self.start['output_rate'])
                t.speaking = True
                self.active_audio = tid
            elif kind == 'transcript':
                assert tid not in self.transient_turns, 'say emitted transcript'
                assert not t.failed and not t.done, 'transcript after terminal frame'
                if e['role'] == 'user':
                    assert e.get('message_id'), 'user transcript missing message_id'
                    assert any(x['type'] == 'thinking' and x.get('turn_id') == tid for x in self.events), 'user transcript before thinking'
                elif e.get('message_id'):
                    assert e['text'] == '' and not t.interrupted, 'invalid assistant closing transcript'
                else:
                    assert e['text'], 'empty transcript without cursor'
            elif kind == 'interrupted':
                t.interrupted, t.speaker_until = True, now
                self.pending_interruption = tid
                if self.active_audio == tid:
                    self.active_audio = None
            elif kind == 'error':
                t.failed = True
            elif kind == 'turn_done':
                if 'next_action' in e:
                    assert e['next_action'] in ('listen', 'standby', 'mute'), 'invalid next_action'
                if t.interrupted or t.failed:
                    assert 'next_action' not in e, 'terminal failure/interruption carries action'
                if self.pending_interruption == tid:
                    self.pending_interruption = None
                turn_events = [x for x in self.events if x.get('turn_id') == tid]
                pieces = [x for x in turn_events if x['type'] == 'transcript' and x.get('role') == 'assistant' and not x.get('replay')]
                if (pieces or self.snapshot_turn == tid) and not t.interrupted and not any(x['type']=='error' for x in turn_events):
                    assert pieces and pieces[-1].get('message_id') and pieces[-1]['text']=='', 'assistant reply missing closing transcript cursor'
                    assert sum(bool(x.get('message_id')) for x in pieces)==1, 'duplicate assistant closing cursor'
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
                if self.closed and kind == 'ready':
                    errors = [e for e in self.events if e['type'] == 'error']
                    if errors and errors[-1].get('error') == 'audio_unavailable':
                        assert self.start.get('audio_format') == 'opus', 'mandatory PCM16 unavailable'
                        assert self.ws.close_code == 4503, 'audio_unavailable must close 4503'
                        raise AudioUnavailable('4503 audio_unavailable: optional codec unavailable')
                assert not self.closed, f'socket closed ({self.ws.close_code}) waiting for {kind}; errors: {[e.get("error") for e in self.events if e["type"] == "error"]}'
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
        assert not self.muted, 'cannot stream microphone while muted'
        self.activation = True
        pcm = await speech(text, self.start['input_rate'])
        await self.stop_ambient()
        offset = len(self.events)
        await self.pcm(pcm)
        if self.encoder:  # flush codec lookahead without resetting its stream state
            await self.pcm(bytes(self.start['input_rate']//50*2*3))
        if commit:
            await self.send(type='endpointing', commit=True)
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
                action = t.done.get('next_action')
                if action in ('standby', 'mute'):
                    self.activation = False
                    await self.stop_ambient()
                elif action == 'listen' and not self.muted:
                    self.activation = True
                await self.send(type='state', turn_id=tid,
                                state='listening' if self.activation and not self.muted else 'standby')
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
        if done.get('next_action') in ('standby', 'mute'):
            await self.stop_ambient()
        return done

    async def close(self):
        await self.stop_ambient()
        if self.ws and not self.ws.closed:
            # Closing the socket ends the session. No cancel: teardown is not a request to stop the assistant.
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
