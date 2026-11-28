"""The admin socket (hermes-converse specs/admin.md) and the `controls` frame (specs/client.md section 12).

The suite's client plays the device; nothing here imports or mocks the server.
"""
import asyncio
import time
import uuid
import aiohttp
import pytest
import pytest_asyncio
from yarl import URL

pytestmark = pytest.mark.live

FIELDS = ('device_name', 'attached', 'muted', 'volume', 'address')


def unused_name():
    return 'arya-test-' + uuid.uuid4().hex


def admin_url(url):
    return URL(url).with_path('/v1/audio/admin')


def entry(frame):
    """A `devices` entry or a `device` frame, checked against section 2; unknown fields are ignored."""
    d = {k: frame[k] for k in FIELDS}
    assert isinstance(d['device_name'], str) and d['device_name']
    assert type(d['attached']) is bool
    assert d['muted'] is None or type(d['muted']) is bool
    assert d['volume'] is None or (type(d['volume']) in (int, float) and 0 <= d['volume'] <= 1)
    assert d['address'] is None or isinstance(d['address'], str)
    if not d['attached']:
        assert d['muted'] is None and d['volume'] is None, 'mute or volume listed for a device that is not attached'
    return d


class Admin:
    """One admin connection. Results can arrive in any order and between `device` frames, so
    every frame is kept and `wait` searches them."""

    def __init__(self, ws):
        self.ws, self.frames = ws, []

    async def wait(self, kind, *, after=0, timeout=10, **fields):
        seen = after
        async with asyncio.timeout(timeout):
            while True:
                for f in self.frames[seen:]:
                    if f['type'] == kind and all(f.get(k) == v for k, v in fields.items()):
                        return f
                seen = len(self.frames)
                f = await self.ws.receive_json()
                assert isinstance(f, dict) and isinstance(f.get('type'), str), 'invalid admin frame'
                for d in f['devices'] if f['type'] == 'devices' else [f] if f['type'] == 'device' else []:
                    entry(d)
                self.frames.append(f)

    async def send(self, **frame):
        request_id = uuid.uuid4().hex
        await self.ws.send_json({**frame, 'request_id': request_id})
        return request_id

    async def request(self, **frame):
        return await self.wait('result', request_id=await self.send(**frame))

    def attached(self):
        """The names attached now, from the list and every change received since."""
        state = {}
        for f in self.frames:
            for d in f['devices'] if f['type'] == 'devices' else [f] if f['type'] == 'device' else []:
                state[d['device_name']] = d['attached']
            if f['type'] == 'device_removed':
                state.pop(f['device_name'], None)
        return {name for name, on in state.items() if on}


@pytest_asyncio.fixture
async def admin(live_config):
    url, key = live_config
    async with aiohttp.ClientSession() as http:
        async with http.ws_connect(admin_url(url), headers={'Authorization': 'Bearer ' + key},
                                   max_msg_size=8*1024*1024) as ws:
            a = Admin(ws)
            assert await a.wait('devices') is a.frames[0], 'the first admin frame is not devices'
            yield a


async def device(client, admin, **start):
    """Attach a test device and wait until the admin connection has been told.

    The device does not report `controls` by itself: these tests send each report by hand."""
    c = await client(select=False, auto_controls=False, **start)
    name = c.ready['device_name']
    first = await admin.wait('device', device_name=name)
    assert first['attached'] and first['muted'] is None and first['volume'] is None  # it has not said
    return c, name


@pytest.mark.parametrize('headers', [{}, {'Authorization': 'Bearer arya-test-invalid-key'}])
async def test_missing_or_wrong_key_refused_before_upgrade(live_config, headers):
    async with aiohttp.ClientSession() as http:
        with pytest.raises(aiohttp.WSServerHandshakeError) as e:
            await http.ws_connect(admin_url(live_config[0]), headers=headers)
        assert e.value.status == 401


async def test_controls_reports_reach_admin_and_clear_on_detach(client, admin):
    c, name = await device(client, admin)
    await c.send(type='controls', muted=False)  # a device with no volume to set
    assert entry(await admin.wait('device', device_name=name, muted=False))['volume'] is None
    await c.send(type='controls', muted=False, volume=0.4)
    await admin.wait('device', device_name=name, muted=False, volume=0.4)
    await c.send(type='controls', muted=True, volume=0.4)
    await admin.wait('device', device_name=name, muted=True, volume=0.4)
    await c.ws.close()
    gone = await admin.wait('device', device_name=name, attached=False)
    assert gone['muted'] is None and gone['volume'] is None


async def test_set_sends_one_controls_frame_and_answers_with_the_report(client, admin):
    c, name = await device(client, admin)
    await c.send(type='controls', muted=False, volume=0.4)
    await admin.wait('device', device_name=name, muted=False, volume=0.4)

    async def set_(answer, **fields):
        offset, mark = len(c.events), len(admin.frames)
        request_id = await admin.send(type='set', device_name=name, **fields)
        assert await c.wait('controls', after=offset) == {'type': 'controls', **fields}  # only the fields given
        if answer:
            await c.send(type='controls', **answer)
        result = await admin.wait('result', request_id=request_id)
        assert set(result) == {'type', 'request_id', 'device'}
        return entry(result['device']), mark

    # The device applies it and reports; the change is also a `device` frame.
    got, mark = await set_(dict(muted=True, volume=0.4), muted=True)
    assert (got['attached'], got['muted'], got['volume']) == (True, True, 0.4)
    await admin.wait('device', after=mark, device_name=name, muted=True, volume=0.4)
    # The device decides: it stays muted and takes another volume than the one asked for.
    got, mark = await set_(dict(muted=True, volume=0.35), muted=False, volume=0.9)
    assert (got['muted'], got['volume']) == (True, 0.35)
    await admin.wait('device', after=mark, device_name=name, muted=True, volume=0.35)
    # A device that does not answer is shown unchanged after 2 s.
    began = time.monotonic()
    got, mark = await set_(None, volume=0.1)
    assert 1.5 <= time.monotonic() - began <= 6, 'an unanswered set is answered after 2 s'
    assert (got['muted'], got['volume']) == (True, 0.35)
    assert sum(e['type'] == 'controls' for e in c.events) == 3, 'more than one controls frame for a set'


async def test_a_device_reports_mute_after_ready_and_applies_a_set(client, admin):
    """Section 12 from the device's side: report after `ready`, apply, answer, and land in standby."""
    c = await client(select=False)
    name = c.ready['device_name']
    reported = await admin.wait('device', device_name=name, muted=False)
    assert reported['volume'] is None, 'the jig has no volume to report'
    # A device mutes as its own control does; it reports once, then stays muted.
    offset = len(c.events)
    result = await admin.request(type='set', device_name=name, muted=True, volume=0.5)
    got = entry(result['device'])
    assert (got['muted'], got['volume']) == (True, None)
    assert c.events[offset]['type'] == 'controls' and c.muted and not c.activation
    result = await admin.request(type='set', device_name=name, muted=False)
    assert entry(result['device'])['muted'] is False and not c.muted
    # A value that is not a Boolean or not a number from 0 to 1 never gets this far: the server refuses it.
    await c.quiet_for(.3, {'speaking', 'thinking', 'turn_done'})


async def test_set_not_attached_and_unknown_device(client, admin):
    c, name = await device(client, admin)
    await c.ws.close()
    await admin.wait('device', device_name=name, attached=False)
    for target, error in [(name, 'not_attached'), (unused_name(), 'unknown_device')]:
        result = await admin.request(type='set', device_name=target, muted=True)
        assert result == {'type': 'result', 'request_id': result['request_id'], 'error': error}


async def test_bad_requests(client, admin):
    # An attached device, so that `bad_request` is the only answer the spec allows.
    c, name = await device(client, admin)
    await admin.ws.send_str('not json')
    offset = len(c.events)
    await admin.ws.send_json({'type': 'set', 'device_name': name, 'muted': True})  # no request_id: ignored
    await admin.ws.send_json({'type': 'set', 'device_name': name, 'muted': True, 'request_id': 7})
    sent = []
    for frame in [dict(type='arya-test-unknown'), dict(type='set', device_name=name),
                  dict(type='set', muted=True), dict(type='set', device_name=name, muted='yes'),
                  dict(type='set', device_name=name, volume=1.01), dict(type='set', device_name=name, volume=-0.1),
                  dict(type='set', device_name=name, volume='0.4'), dict(type='set', device_name=name, volume=True),
                  dict(type='announce', target=name), dict(type='announce', message='   ', target=name),
                  dict(type='announce', message=7, target=name)]:
        result = await admin.request(**frame)
        assert result == {'type': 'result', 'request_id': result['request_id'], 'error': 'bad_request'}, frame
        sent.append(result['request_id'])
    assert [f['request_id'] for f in admin.frames if f['type'] == 'result'] == sent, 'a frame with no request_id was answered'
    await asyncio.sleep(.5)
    # A server that ran either `set` would have sent the device a `controls` frame at once.
    assert not any(e['type'] in ('controls', 'speaking', 'thinking', 'turn_done') for e in c.events[offset:]), \
        'a set with no string request_id reached the device'


def announcement(c, done):
    """Section 9: an announcement is prepared speech, with no transcript, wake event or user turn."""
    assert [e['turn_id'] for e in c.events if e['type'] == 'turn_done'] == [done['turn_id']]
    assert c.turns[done['turn_id']].speaking
    assert not any(e['type'] in ('transcript', 'wake_grant', 'wake_deny') for e in c.events)


@pytest.mark.speech
async def test_announce_speaks_on_the_named_device_only(client, admin):
    (kitchen, name), (den, other) = [await device(client, admin, transcripts=True) for _ in range(2)]
    unknown = unused_name()
    kitchen.expect_announcement()
    result = await admin.request(type='announce', message='  Arya contract check announcement.  ', target=[name, unknown])
    assert result == {'type': 'result', 'request_id': result['request_id'], 'announced': [name], 'skipped': [unknown]}
    announcement(kitchen, await kitchen.finish())
    await den.quiet_for(.5, {'thinking', 'speaking', 'transcript', 'turn_done'})
    assert not den.turns, 'an announcement played on a device that was not named'
    # One name, not in an array, is a target too.
    den.expect_announcement()
    result = await admin.request(type='announce', message='Arya contract check announcement.', target=other)
    assert (result['announced'], result['skipped']) == ([other], [])
    announcement(den, await den.finish())
    assert len(kitchen.turns) == 1


@pytest.mark.speech
async def test_announce_without_target_reaches_every_attached_device(client, admin):
    devices = [await device(client, admin, transcripts=True) for _ in range(2)]
    # This suite runs against servers with real devices in real rooms. An announcement with no
    # target speaks on all of them, so it is sent only when every attached device is a test one.
    others = sorted(n for n in admin.attached() if not n.startswith('arya-test-'))
    if others:
        pytest.skip(f'{len(others)} attached device(s) are not the suite\'s; an announcement with no target would speak on them')
    for c, _ in devices:
        c.expect_announcement()
    result = await admin.request(type='announce', message='Arya contract check announcement.')
    assert {name for _, name in devices} <= set(result['announced']) and result['skipped'] == []
    for c, _ in devices:
        announcement(c, await c.finish())
