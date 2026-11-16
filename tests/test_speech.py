"""Real microphone → STT → selected free model → TTS tests on the live server."""
import asyncio
import pytest

pytestmark = [pytest.mark.live, pytest.mark.speech]


def assistant_text(c, offset=0):
    return ''.join(e['text'] for e in c.events[offset:] if e['type']=='transcript' and e.get('role')=='assistant')


@pytest.mark.parametrize('fmt', ['pcm16','opus'])
async def test_say_idle_output_and_drain(client, fmt):
    c = await client(audio_format=fmt)
    await c.send(type='say',text='  Arya contract check.  ')
    done = await c.finish()
    assert done['next_action']=='standby'
    assert not any(e['type']=='transcript' for e in c.events)
    assert not any(e['type'] in ('wake_grant','wake_deny') for e in c.events)
    offset=len(c.events)
    await c.send(type='say',text='Second reply after playback drained.')
    again=await c.finish(offset)
    assert again['turn_id']!=done['turn_id']


@pytest.mark.parametrize('fmt', ['pcm16','opus'])
async def test_real_voice_turn_commit_and_followup(client, fmt):
    c=await client(audio_format=fmt,transcripts=True)
    offset=await c.utterance('Arya, what is two plus two? Answer briefly. Do not use any tools.')
    done=await c.finish(offset)
    assert done['next_action']=='listen'
    messages=[e for e in c.events[offset:] if e['type']=='transcript']
    assert any(e['role']=='user' and e['text'] for e in messages)
    assert any(e['role']=='assistant' and e.get('message_id') and e['text']=='' for e in messages)
    assert any(word in assistant_text(c,offset).lower() for word in ('four','4')), 'free model reply did not answer input'
    offset=await c.utterance('What was the arithmetic question I just asked you? Answer briefly without tools.')
    other=await c.finish(offset)
    assert other['turn_id']!=done['turn_id']
    assert any(word in assistant_text(c,offset).lower() for word in ('two','2','plus')), 'history reply: '+assistant_text(c,offset)


async def test_automatic_endpoint_and_transcripts_off(client):
    c=await client()
    offset=await c.utterance('Arya, say hello briefly without tools.',commit=False)
    await c.finish(offset)
    assert not any(e['type']=='transcript' for e in c.events)


async def test_cancel_preserves_socket_and_next_turn(client):
    c=await client(transcripts=True)
    offset=await c.utterance('Arya, count slowly from one to thirty, without using tools.')
    thinking=await c.wait('thinking',after=offset)
    tid=thinking['turn_id']
    await c.send(type='cancel',turn_id=tid)
    await c.wait('interrupted',turn_id=tid)
    done=await c.wait('turn_done',turn_id=tid)
    assert done['next_action']=='listen'
    await c.send(type='state',turn_id=tid,state='listening')
    offset=await c.utterance('Arya, say hello. Do not use tools.')
    next_done=await c.finish(offset)
    assert next_done['turn_id']!=tid and not c.closed


async def test_stale_cancel_does_not_cancel_current_turn(client):
    c=await client()
    await c.send(type='say',text='One two three four five six seven eight nine ten.')
    thinking=await c.wait('thinking')
    await c.send(type='cancel',turn_id='not-the-current-turn')
    await c.finish()
    assert not any(e['type']=='interrupted' and e.get('turn_id')==thinking['turn_id'] for e in c.events)


async def test_model_change_during_turn_keeps_audio(client):
    c=await client()
    await c.send(type='say',text='This reply should finish even when the model selection changes during playback.')
    turn=await c.wait('speaking')
    await c.select_free()
    done=await c.finish()
    assert done['turn_id']==turn['turn_id']
    assert not any(e['type']=='interrupted' for e in c.events)


async def test_history_reconnect_cursor_and_stop(client):
    c=await client(transcripts=True)
    offset=await c.utterance('Arya, remember the secret word is pineapple. Repeat the word briefly without tools.')
    await c.finish(offset)
    user=next(e for e in c.events if e['type']=='transcript' and e.get('role')=='user')
    closing=next(e for e in reversed(c.events) if e['type']=='transcript' and e.get('role')=='assistant' and e.get('message_id'))
    await c.send(stop=True)
    await asyncio.wait_for(c.reader,10)
    b=await client(device=c.start['device_name'],transcripts=True,after=user['message_id'])
    assert b.ready['new_session'] is False
    replay=await b.wait('transcript',replay=True,message_id=closing['message_id'])
    assert replay['role']=='assistant' and replay['text']
    assert not any(e.get('message_id')==user['message_id'] for e in b.events)
    assert not any(e['type']=='speaking' for e in b.events), 'history replay was spoken'
    offset=await b.utterance('What secret word did I ask you to remember? No tools, answer briefly.')
    await b.finish(offset)
    assert 'pineapple' in assistant_text(b,offset).lower(), 'history lost on stop/reconnect'


async def test_unknown_cursor_starts_fresh_view(client):
    c=await client(transcripts=True,after='arya-test-unknown-cursor')
    assert c.ready['new_session'] is True
    assert not any(e.get('replay') for e in c.events)


async def test_barge_in_captures_continuation(client):
    c=await client(transcripts=True)
    offset=await c.utterance('Arya, count from one to fifty, without tools.')
    first=await c.wait('speaking',after=offset,timeout=120)
    second_offset=await c.utterance('Actually, what is three plus three? Answer briefly, without tools.')
    await c.wait('interrupted',turn_id=first['turn_id'],timeout=40)
    old=await c.wait('turn_done',turn_id=first['turn_id'],timeout=40)
    assert old['next_action']=='listen'
    await c.send(type='state',turn_id=first['turn_id'],state='listening')
    # Select the new turn specifically; never mistake the old completion for success.
    async with asyncio.timeout(160):
        while True:
            users=[e for e in c.events[second_offset:] if e['type']=='transcript' and e.get('role')=='user' and e.get('turn_id')!=first['turn_id']]
            if users:
                break
            if c.failure:
                raise c.failure
            c.changed.clear()
            await c.changed.wait()
    tid=users[0]['turn_id']
    await c.wait('turn_done',turn_id=tid,timeout=160)
    assert any(word in assistant_text(c,second_offset).lower() for word in ('six','6'))


async def test_countdown_create_replay_and_cancel(client):
    c=await client(transcripts=True)
    try:
        offset=await c.utterance('Arya, set a countdown timer for three minutes called contract check. Use the countdown tool.')
        await c.finish(offset)
        alarm=await c.wait('countdown',after=offset,timeout=10)
        await c.close()
        b=await client(device=c.start['device_name'],transcripts=True)
        await b.wait('countdown',countdown_id=alarm['countdown_id'])
        c=b
        offset=await c.utterance('Arya, cancel my contract check countdown timer. Use the countdown tool.')
        await c.finish(offset)
        await c.wait('countdown_cancel',after=offset,countdown_id=alarm['countdown_id'],timeout=10)
    finally:
        # Test-owned countdown only; ended removes it even if the model did not cancel.
        for e in c.events:
            if e['type']=='countdown' and not c.closed:
                await c.send(type='countdown',countdown_id=e['countdown_id'],ended=True)
