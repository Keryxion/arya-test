"""Real microphone → STT → the selected chat model → TTS tests on the live server."""
import asyncio
import pytest

pytestmark = [pytest.mark.live, pytest.mark.speech]


def assistant_text(c, offset=0, turn_id=None):
    return ''.join(e['text'] for e in c.events[offset:] if e['type']=='transcript' and e.get('role')=='assistant' and (turn_id is None or e.get('turn_id')==turn_id))


@pytest.mark.parametrize('fmt', ['pcm16','opus'])
async def test_say_idle_output_and_drain(client, fmt):
    c = await client(audio_format=fmt,transcripts=True)
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
    done=await c.finish(offset,user=c.start.get("transcripts") is True)
    # Section 4 makes next_action optional, and standby is correct when the
    # person has said they are done. Only a failed or interrupted turn_done
    # must carry none.
    assert done.get('next_action') in (None,'standby'), done
    messages=[e for e in c.events[offset:] if e['type']=='transcript']
    assert any(e['role']=='user' and e['text'] for e in messages)
    assert any(e['role']=='assistant' and e.get('message_id') and e['text']=='' for e in messages)
    assert any(word in assistant_text(c,offset).lower() for word in ('four','4')), 'model reply did not answer input'
    offset=await c.utterance('What was the arithmetic question I just asked you? Answer briefly without tools.')
    other=await c.finish(offset,user=c.start.get("transcripts") is True)
    assert other['turn_id']!=done['turn_id']
    assert any(word in assistant_text(c,offset).lower() for word in ('two','2','plus')), 'history reply: '+assistant_text(c,offset)


async def test_automatic_endpoint_and_transcripts_off(client):
    c=await client()
    offset=await c.utterance('Arya, say hello briefly without tools.',commit=False)
    await c.finish(offset,user=c.start.get("transcripts") is True)
    assert not any(e['type']=='transcript' for e in c.events)


async def test_cancel_preserves_socket_and_next_turn(client):
    c=await client(transcripts=True)
    offset=await c.utterance('Arya, count slowly from one to thirty, without using tools.')
    thinking=await c.wait('thinking',after=offset)
    tid=thinking['turn_id']
    await c.send(type='cancel',turn_id=tid)
    await c.wait('interrupted',turn_id=tid)
    done=await c.wait('turn_done',turn_id=tid)
    assert 'next_action' not in done
    await c.send(type='state',turn_id=tid,state='listening')
    offset=await c.utterance('Arya, say hello. Do not use tools.')
    next_done=await c.finish(offset,user=c.start.get("transcripts") is True)
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
    await c.select_model()
    done=await c.finish()
    assert done['turn_id']==turn['turn_id']
    assert not any(e['type']=='interrupted' for e in c.events)


async def test_history_reconnect_cursor_after_close(client):
    c=await client(transcripts=True)
    offset=await c.utterance('Arya, remember the secret word is pineapple. Repeat the word briefly without tools.')
    await c.finish(offset,user=c.start.get("transcripts") is True)
    user=next(e for e in c.events if e['type']=='transcript' and e.get('role')=='user')
    closing=next(e for e in reversed(c.events) if e['type']=='transcript' and e.get('role')=='assistant' and e.get('message_id'))
    await c.stop_ambient()
    await c.ws.close()
    await asyncio.wait_for(c.reader,10)
    b=await client(device=c.start['device_name'],transcripts=True,after=user['message_id'])
    assert b.ready['new_session'] is False
    replay=await b.wait('transcript',replay=True,message_id=closing['message_id'])
    assert replay['role']=='assistant' and replay['text']
    assert replay['turn_id']==closing['turn_id']
    assert replay['text']==assistant_text(c,turn_id=closing['turn_id'])
    assert not any(e.get('message_id')==user['message_id'] for e in b.events)
    assert not any(e['type']=='speaking' for e in b.events), 'history replay was spoken'
    offset=await b.utterance('What secret word did I ask you to remember? No tools, answer briefly.')
    await b.finish(offset,user=True)
    assert 'pineapple' in assistant_text(b,offset).lower(), 'history lost on close/reconnect'


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
    assert 'next_action' not in old
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


async def test_heard_is_recorded_and_the_turn_carries_on(client):
    """Section 4: `heard` is neither `cancel` nor barge-in, and no frame answers it."""
    c=await client(transcripts=True)
    offset=await c.utterance('Arya, count from one to thirty, without tools.')
    await c.wait('speaking',after=offset,timeout=120)
    heard=len(c.events)
    await c.send(type='heard',wake_word='Hey Arya')
    await c.send(type='heard',wake_word='cancel')
    await c.quiet_for(1.5,{'interrupted','error'})
    assert not any(e['type'] in ('interrupted','error') for e in c.events[heard:])
    await c.finish(offset,user=True)


async def test_countdown_create_replay_and_cancel(client):
    c=await client(transcripts=True)
    try:
        offset=await c.utterance('Arya, set a countdown timer for three minutes called contract check. Use the countdown tool.')
        await c.finish(offset,user=c.start.get("transcripts") is True)
        alarm=await c.wait('countdown',after=offset,timeout=10)
        await c.close()
        b=await client(device=c.start['device_name'],transcripts=True)
        await b.wait('countdown',countdown_id=alarm['countdown_id'])
        c=b
        offset=await c.utterance('Arya, cancel my contract check countdown timer. Use the countdown tool.')
        await c.finish(offset,user=c.start.get("transcripts") is True)
        await c.wait('countdown_cancel',after=offset,countdown_id=alarm['countdown_id'],timeout=10)
        # A countdown that ends is reported once with `ended`; the client does that on a cancel.
        await c.quiet_for(.3,set())
        assert alarm['countdown_id'] not in c.countdowns
    finally:
        await c.close()


async def test_disconnect_does_not_cancel_active_turn(client):
    c=await client(transcripts=True)
    offset=await c.utterance('Arya, explain why the sky is blue in two sentences. Do not use tools.')
    user=await c.wait('transcript',after=offset,role='user')
    tid=user['turn_id']
    await c.wait('transcript',after=offset,role='assistant',turn_id=tid,timeout=120)
    await c.stop_ambient()
    await c.ws.close()  # No cancel first: the running turn must finish on the server.
    await c.reader
    b=await client(device=c.start['device_name'],transcripts=True,after=user['message_id'],
                   resume=dict(turn_id=tid,tool_calls=c.turns[tid].tool_calls,reasoning_tokens=c.turns[tid].reasoning))
    assert b.ready['new_session'] is False
    async with asyncio.timeout(160):
        while True:
            b.changed.clear()
            if b.failure: raise b.failure
            reply=[e for e in b.events if e['type']=='transcript' and e.get('role')=='assistant' and e.get('message_id')]
            if reply: break
            await b.changed.wait()
    # Finished work replays silently; still-running work resumes under its turn ID.
    if reply[-1].get('replay'):
        assert reply[-1]['text'] and reply[-1]['turn_id']==tid
    else:
        assert reply[-1]['turn_id']==tid
        await b.wait('turn_done',turn_id=tid,timeout=160)


async def test_turn_finishes_after_close_and_is_replayed_unspoken(client):
    c=await client(transcripts=True)
    offset=await c.utterance('Arya, explain why the sky is blue in two sentences. Do not use tools.')
    user=await c.wait('transcript',after=offset,role='user')
    tid=user['turn_id']
    assert not c.turns[tid].done, 'turn finished before the socket closed'
    await c.stop_ambient()
    await c.ws.close()  # No cancel and no stop frame.
    await c.reader
    await asyncio.sleep(30)  # Nothing is connected while the reply finishes.
    b=await client(device=c.start['device_name'],transcripts=True,after=user['message_id'])
    assert b.ready['new_session'] is False
    replay=await b.wait('transcript',replay=True,role='assistant',turn_id=tid,timeout=10)
    assert replay.get('message_id') and replay['text'], 'turn was still running 30 seconds after the socket closed, or its reply was lost'
    await b.quiet_for(2,{'speaking','thinking'})
    assert not b.turns.get(tid) or not b.turns[tid].pcm, 'reply finished while disconnected was spoken later'


async def test_countdown_extension_preserves_id(client):
    c=await client(transcripts=True)
    try:
        offset=await c.utterance('Arya, set a countdown timer for three minutes called tea test. Use the countdown tool.')
        await c.finish(offset,user=True)
        alarm=await c.wait('countdown',after=offset,timeout=10)
        offset=await c.utterance('Arya, extend my existing tea test countdown timer by five minutes. Do not create a second timer.')
        await c.finish(offset,user=True)
        extended=await c.wait('countdown',after=offset,countdown_id=alarm['countdown_id'],timeout=10)
        assert extended['deadline_unix_ms']>alarm['deadline_unix_ms']
    finally:
        await c.close()  # it is still counting: a device sends no `ended` for that


async def test_cancel_capture_before_submission_has_no_transcript(client):
    from arya_test.audio import speech
    c=await client(transcripts=True)
    await c.send(type='endpointing',on=False)
    await c.pcm(await speech('Arya, remember this request should be discarded.'))
    await c.send(type='cancel')
    await c.quiet_for(1,{'thinking','transcript','interrupted','turn_done'})
    await c.send(type='endpointing',on=True)
    await c.send(type='endpointing',commit=True)
    await c.quiet_for(.5,{'thinking','transcript','interrupted','turn_done'})


@pytest.mark.parametrize('value', [1,'true'])
async def test_commit_requires_exact_true(client,value):
    from arya_test.audio import speech
    c=await client(transcripts=True)
    await c.send(type='endpointing',on=False)
    await c.pcm(await speech('Arya, what is two plus two? No tools, answer briefly.'))
    await c.send(type='endpointing',commit=value)
    await c.quiet_for(.5,{'thinking','transcript','speaking'})
    await c.send(type='endpointing',on=True,commit=True)
    await c.finish(user=True)


async def test_typed_commit_alone_ends_the_utterance(client):
    from arya_test.audio import speech
    c=await client(transcripts=True)
    await c.send(type='endpointing',on=False)
    await c.pcm(await speech('Arya, what is two plus two? No tools, answer briefly.'))
    # Endpointing is off, so two seconds of silence must not end the utterance.
    await c.pcm(bytes(c.start['input_rate']*2*2))
    assert not any(e['type'] in ('thinking','transcript','speaking') for e in c.events)
    offset=len(c.events)
    await c.send(type='endpointing',commit=True)
    done=await c.finish(offset,user=True)
    user=next(e for e in c.events[offset:] if e['type']=='transcript' and e['role']=='user')
    assert user['text'] and user['turn_id']==done['turn_id']


async def test_endpointing_on_applies_when_commit_is_not_true(client):
    from arya_test.audio import speech
    c=await client(transcripts=True)
    await c.send(type='endpointing',on=False,commit='true')
    await c.pcm(await speech('Arya, what is two plus two? No tools, answer briefly.'))
    await c.pcm(bytes(c.start['input_rate']*2*2))
    assert not any(e['type'] in ('thinking','transcript','speaking') for e in c.events), 'on:false ignored beside a non-true commit'
    await c.send(type='endpointing',on=True,commit=True)
    await c.finish(user=True)
