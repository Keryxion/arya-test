"""Section 12 Do Not Disturb, from what a headless client can observe on the live server.

Every connection (``Client.connect``) already requires ``do_not_disturb`` as the first
frame after ``ready``. Server-started output (section 9 reminders and messages) cannot be
triggered from this harness, so holding it after the grace is not checked here.
"""
import pytest

pytestmark = pytest.mark.live


async def toggle(c, on):
    """The person's own device toggle, followed by a round trip so the server has read it."""
    offset = len(c.events)
    await c.send(type='do_not_disturb', on=on)
    await c.barrier()
    return offset


async def reconnect(client, c, **start):
    await c.close()
    return await client(device=c.start['device_name'], **start)


async def ensure_off(client, device):
    """Never leave a test-owned device in Do Not Disturb."""
    c = await client(device=device, select=False)
    if c.do_not_disturb is not False:
        await toggle(c, False)
    await c.close()


@pytest.mark.parametrize('options', [dict(), dict(browser=True), dict(transcripts=True, after='arya-test-unknown-cursor')])
async def test_ready_is_followed_by_do_not_disturb(client, options):
    c = await client(**options)
    first = c.events[next(i for i, e in enumerate(c.events) if e['type'] == 'ready') + 1]
    # A new device starts with the setting off (server spec: off by default).
    assert first == {'type': 'do_not_disturb', 'on': False}


async def test_device_toggle_not_echoed_and_kept_for_the_device(client):
    c = await client()
    device = c.start['device_name']
    try:
        offset = await toggle(c, True)
        await c.quiet_for(1, {'do_not_disturb', 'error'})
        assert not any(e['type'] == 'do_not_disturb' for e in c.events[offset:]), 'device toggle echoed'
        b = await reconnect(client, c)
        assert b.do_not_disturb is True, 'device toggle did not survive reconnect'
        # The setting belongs to the device, whichever assistant it talks to.
        other = await reconnect(client, b, assistant_name='Arya Second')
        assert other.do_not_disturb is True, 'setting not shared across assistants'
        offset = await toggle(other, False)
        await other.quiet_for(1, {'do_not_disturb', 'error'})
        assert not any(e['type'] == 'do_not_disturb' for e in other.events[offset:]), 'device toggle echoed'
        d = await reconnect(client, other)
        assert d.do_not_disturb is False, 'turning off did not survive reconnect'
    finally:
        await ensure_off(client, device)


async def test_non_boolean_on_is_ignored(client):
    c = await client()
    device = c.start['device_name']
    try:
        for value in ['true', 1, 'on', [True], {'on': True}]:
            await c.send(type='do_not_disturb', on=value)
        await c.send(type='do_not_disturb')
        await c.barrier()
        await c.quiet_for(.5, {'do_not_disturb', 'error'})
        b = await reconnect(client, c)
        assert b.do_not_disturb is False, 'non-Boolean on turned Do Not Disturb on'
        await toggle(b, True)
        for value in ['false', 0, None, '', []]:
            await b.send(type='do_not_disturb', on=value)
        await b.send(type='do_not_disturb')
        await b.barrier()
        await b.quiet_for(.5, {'do_not_disturb', 'error'})
        d = await reconnect(client, b)
        assert d.do_not_disturb is True, 'non-Boolean on turned Do Not Disturb off'
    finally:
        await ensure_off(client, device)


@pytest.mark.speech
async def test_say_answered_aloud_while_on(client):
    c = await client(transcripts=True)
    try:
        offset = await toggle(c, True)  # Turning it on ends the grace.
        await c.send(type='say', text='Arya contract check during Do Not Disturb.')
        await c.finish(offset)  # Requires audible reply PCM.
        assert not any(e['type'] == 'do_not_disturb' for e in c.events[offset:]), 'unexpected do_not_disturb frame'
    finally:
        await ensure_off(client, c.start['device_name'])


@pytest.mark.speech
async def test_own_turn_answered_aloud_while_on(client):
    c = await client(transcripts=True)
    try:
        await toggle(c, True)
        offset = await c.utterance('Arya, what is two plus two? Answer briefly. Do not use any tools.')
        done = await c.finish(offset, user=True)
        reply = ''.join(e['text'] for e in c.events[offset:] if e['type'] == 'transcript'
                        and e.get('role') == 'assistant' and e.get('turn_id') == done['turn_id'])
        assert any(w in reply.lower() for w in ('four', '4')), 'free model reply did not answer input: ' + reply
        b = await reconnect(client, c)
        assert b.do_not_disturb is True, 'own turn changed the setting'
    finally:
        await ensure_off(client, c.start['device_name'])


@pytest.mark.speech
async def test_assistant_change_is_sent_and_reply_spoken(client):
    c = await client(transcripts=True)
    device = c.start['device_name']
    try:
        offset = await c.utterance('Arya, turn on Do Not Disturb on this device. Use the do not disturb tool.')
        await c.finish(offset, user=True)  # The person's turn is spoken even though it turned the setting on.
        frame = await c.wait('do_not_disturb', after=offset, timeout=10)
        assert frame['on'] is True, 'assistant did not turn Do Not Disturb on'
        b = await reconnect(client, c, transcripts=True)
        assert b.do_not_disturb is True
        offset = await b.utterance('Arya, turn off Do Not Disturb on this device. Use the do not disturb tool.')
        await b.finish(offset, user=True)
        frame = await b.wait('do_not_disturb', after=offset, timeout=10)
        assert frame['on'] is False, 'assistant did not turn Do Not Disturb off'
        d = await reconnect(client, b)
        assert d.do_not_disturb is False
    finally:
        await ensure_off(client, device)
