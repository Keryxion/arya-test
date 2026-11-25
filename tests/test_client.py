"""Local negative controls: prove the harness rejects corrupt wire behavior."""
import asyncio
import time
import pytest
from arya_test.client import Client
from arya_test.audio import Opus


def test_validator_rejects_wrong_order_and_missing_ids():
    c=Client('ws://invalid','unused')
    with pytest.raises(AssertionError):
        c._validate({'type':'speaking'},0)
    c._validate({'type':'speaking','turn_id':'a'},0)
    with pytest.raises(AssertionError,match='interleaved'):
        c._validate({'type':'speaking','turn_id':'b'},0)


def test_validator_rejects_liveness_after_done():
    c=Client('ws://invalid','unused')
    c._validate({'type':'turn_done','turn_id':'a','next_action':'listen'},0)
    assert c.turns['a'].action=='listen'
    with pytest.raises(AssertionError,match='terminal'):
        c._validate({'type':'thinking','turn_id':'a','tool_calls':0,'reasoning_tokens':None},0)


@pytest.mark.parametrize('value', ['invalid','Listen','',None,7])
def test_unknown_next_action_is_rejected_and_treated_as_absent(value):
    """Section 4: the server sends no other value; a client treats one as absent."""
    c=Client('ws://invalid','unused')
    with pytest.raises(AssertionError,match='invalid next_action'):
        c._validate({'type':'turn_done','turn_id':'a','next_action':value},0)
    assert c.turns['a'].action is None


@pytest.mark.parametrize('value', ['standby','invalid'])
def test_an_interrupted_turn_carries_no_next_action(value):
    c=Client('ws://invalid','unused')
    c._validate({'type':'interrupted','turn_id':'a'},0)
    with pytest.raises(AssertionError):
        c._validate({'type':'turn_done','turn_id':'a','next_action':value},0)


def test_validator_rejects_unsolicited_transcripts():
    c=Client('ws://invalid','unused')
    with pytest.raises(AssertionError,match='unsolicited'):
        c._validate({'type':'transcript','turn_id':'a','role':'user','text':'hello'},0)


def test_codec_accepts_20ms_and_rejects_corruption():
    enc,dec=Opus(16000,True),Opus(16000)
    try:
        assert len(dec.decode(enc.encode(bytes(640))))==640
        with pytest.raises(AssertionError):
            dec.decode(b'')
    finally:
        enc.close()
        dec.close()


def test_validator_rejects_reply_without_closing_cursor():
    c=Client('ws://invalid','unused',transcripts=True)
    c.events.append({'type':'transcript','role':'assistant','turn_id':'a','text':'Hello'})
    with pytest.raises(AssertionError,match='closing transcript'):
        c._validate({'type':'turn_done','turn_id':'a','next_action':'standby'},0)


def emit(c, **frame):
    c._validate(frame, 0)
    c.events.append(frame)


@pytest.mark.parametrize('action', [None, 'listen', 'standby', 'mute'])
def test_completion_actions(action):
    c=Client('ws://invalid','unused')
    frame=dict(type='turn_done',turn_id='a')
    if action is not None: frame['next_action']=action
    emit(c,**frame)


@pytest.mark.parametrize('terminal', ['interrupted', 'error'])
def test_terminal_failure_cannot_change_interaction(terminal):
    c=Client('ws://invalid','unused')
    emit(c,type=terminal,turn_id='a',**({'error':'failed'} if terminal=='error' else {}))
    with pytest.raises(AssertionError,match='carries action'):
        emit(c,type='turn_done',turn_id='a',next_action='listen')
    emit(c,type='turn_done',turn_id='a')


@pytest.mark.parametrize('kind', ['thinking','transcript','state','speaking'])
def test_no_turn_frames_after_interruption(kind):
    c=Client('ws://invalid','unused',transcripts=True)
    emit(c,type='interrupted',turn_id='old')
    with pytest.raises(AssertionError):
        emit(c,type=kind,turn_id='old')
    with pytest.raises(AssertionError,match='before interrupted'):
        emit(c,type='state',turn_id='new',state='thinking')
    emit(c,type='turn_done',turn_id='old')
    emit(c,type='thinking',turn_id='new',tool_calls=0,reasoning_tokens=None)


def test_user_transcript_needs_persisted_id_and_thinking():
    c=Client('ws://invalid','unused',transcripts=True)
    frame=dict(type='transcript',turn_id='a',role='user',text='hello')
    with pytest.raises(AssertionError,match='message_id'):
        emit(c,**frame)
    frame['message_id']='m1'
    with pytest.raises(AssertionError,match='before thinking'):
        emit(c,**frame)
    emit(c,type='thinking',turn_id='a',tool_calls=0,reasoning_tokens=None)
    emit(c,**frame)


def test_cancel_before_persistence_needs_no_transcript():
    c=Client('ws://invalid','unused',transcripts=True)
    emit(c,type='thinking',turn_id='a',tool_calls=0,reasoning_tokens=None)
    emit(c,type='interrupted',turn_id='a')
    emit(c,type='turn_done',turn_id='a')


def test_say_does_not_emit_transcripts():
    c=Client('ws://invalid','unused',transcripts=True)
    c.transient_turns.add(None)
    emit(c,type='thinking',turn_id='a',tool_calls=0,reasoning_tokens=None)
    with pytest.raises(AssertionError,match='say emitted'):
        emit(c,type='transcript',turn_id='a',role='assistant',text='hello')


def test_reconnect_snapshot_and_carried_counters():
    c=Client('ws://invalid','unused',transcripts=True,
             resume=dict(turn_id='a',tool_calls=3,reasoning_tokens=100))
    emit(c,type='transcript',turn_id='a',role='assistant',text='Hello',replay=True)
    assert c.snapshot_turn=='a'
    with pytest.raises(AssertionError,match='before state'):
        emit(c,type='thinking',turn_id='a',tool_calls=3,reasoning_tokens=100)
    emit(c,type='state',turn_id='a',state='thinking')
    with pytest.raises(AssertionError,match='counter reset'):
        emit(c,type='thinking',turn_id='a',tool_calls=0,reasoning_tokens=None)
    emit(c,type='thinking',turn_id='a',tool_calls=3,reasoning_tokens=100)
    emit(c,type='transcript',turn_id='a',role='assistant',text=' world')
    emit(c,type='transcript',turn_id='a',role='assistant',text='',message_id='m1')
    emit(c,type='turn_done',turn_id='a')


def test_resume_without_reply_text_is_inferred_from_state():
    """Reconnecting during a turn: the running-text snapshot appears only when
    the turn already has reply text, and the thinking counters carry on from
    where they were rather than restarting at zero."""
    c=Client('ws://invalid','unused',transcripts=True)
    emit(c,type='transcript',turn_id='turn-41',role='user',text='hello',message_id='m-123',replay=True)
    emit(c,type='state',turn_id='turn-41',state='thinking')
    assert c.snapshot_turn is None and c.turns['turn-41'].resumed
    emit(c,type='thinking',turn_id='turn-41',tool_calls=3,reasoning_tokens=2400)
    emit(c,type='transcript',turn_id='turn-41',role='assistant',text='Two things tomorrow.')
    emit(c,type='transcript',turn_id='turn-41',role='assistant',text='',message_id='m-124')
    emit(c,type='turn_done',turn_id='turn-41')


def test_a_turn_seen_from_its_start_must_reset_its_counters():
    c=Client('ws://invalid','unused')
    with pytest.raises(AssertionError,match='initial counters not reset'):
        emit(c,type='thinking',turn_id='a',tool_calls=3,reasoning_tokens=None)


def test_mid_turn_state_is_not_a_resume():
    """An approval's state frames belong to a turn seen from its start, so they
    are not the resume signal."""
    c=Client('ws://invalid','unused')
    emit(c,type='thinking',turn_id='a',tool_calls=0,reasoning_tokens=None)
    for state in ('speaking','listening','thinking'):
        emit(c,type='state',turn_id='a',state=state)
    assert not c.turns['a'].resumed


def test_cursorless_replay_only_for_running_assistant():
    c=Client('ws://invalid','unused',transcripts=True)
    with pytest.raises(AssertionError,match='user replay'):
        emit(c,type='transcript',turn_id='a',role='user',text='hello',replay=True)


@pytest.mark.parametrize('requested,expected', [('24000',16000),(16000.0,16000),(True,16000),(7999,8000),(96000,48000)])
def test_ready_uses_negotiated_pcm_rate(requested,expected):
    c=Client('ws://invalid','unused',input_rate=requested)
    c.ready=dict(session_id='s',recipient_id='r',assistant_name='Arya',device_name=c.start['device_name'],
                 current_model=dict(model=None, provider=None, reasoning_level=None, reasoning_override=None,
                                    reasoning_support='unknown', reasoning_levels=[], pending=False),
                 transcripts=False,input=dict(sample_rate=expected,format='pcm16',block_ms=30),
                 output=dict(sample_rate=24000,format='pcm16'),server_recv_unix_ms=1,server_send_unix_ms=2)
    c._validate_ready()
    assert c.start['input_rate']==expected


def test_audio_is_rejected_after_interruption():
    c=Client('ws://invalid','unused')
    emit(c,type='speaking',turn_id='a')
    emit(c,type='interrupted',turn_id='a')
    with pytest.raises(AssertionError,match='audio between interruption'):
        c._audio(b'\1\0',0)
    emit(c,type='turn_done',turn_id='a')
    with pytest.raises(AssertionError,match='binary before speaking'):
        c._audio(b'\1\0',0)


def test_resumed_reply_needs_thinking_before_live_text():
    c=Client('ws://invalid','unused',transcripts=True)
    emit(c,type='transcript',turn_id='a',role='assistant',text='Hello',replay=True)
    emit(c,type='state',turn_id='a',state='speaking')
    with pytest.raises(AssertionError,match='before state and thinking'):
        emit(c,type='transcript',turn_id='a',role='assistant',text='world')


@pytest.mark.parametrize('action,activation,expected', [(None,True,True),(None,False,False),('standby',True,False),('listen',False,True)])
async def test_playback_drain_preserves_or_changes_activation(action,activation,expected):
    c=Client('ws://invalid','unused')
    sent=[]
    async def send(**frame): sent.append(frame)
    c.send=send
    c.activation=activation
    frame=dict(type='turn_done',turn_id='a')
    if action: frame['next_action']=action
    emit(c,**frame)
    await c._drain('a')
    assert c.activation is expected
    assert sent[-1]['state']==('listening' if expected else 'standby')


def test_reply_text_precedes_first_audio():
    c=Client('ws://invalid','unused',transcripts=True)
    emit(c,type='speaking',turn_id='a')
    with pytest.raises(AssertionError,match='before live transcript'):
        c._audio(b'\1\0',1)
    emit(c,type='transcript',role='assistant',turn_id='a',text='Hello')
    c._audio(b'\1\0',1)


def test_resumed_text_also_needs_a_closing_cursor():
    c=Client('ws://invalid','unused',transcripts=True)
    emit(c,type='transcript',role='assistant',turn_id='a',text='Hello',replay=True)
    emit(c,type='state',turn_id='a',state='thinking')
    emit(c,type='thinking',turn_id='a',tool_calls=2,reasoning_tokens=None)
    with pytest.raises(AssertionError,match='closing transcript'):
        emit(c,type='turn_done',turn_id='a')


async def test_pending_approval_suspends_the_absolute_turn_limit(monkeypatch):
    """Section 4 Approvals: while one is pending the client applies no turn
    limit of its own except inactivity, which thinking frames keep fresh; the
    server ends the wait, up to its 300 s default."""
    monkeypatch.setattr(Client,'APPROVAL_INACTIVITY',.3)
    c=Client('ws://invalid','unused')
    emit(c,type='thinking',turn_id='a',tool_calls=0,reasoning_tokens=None)
    emit(c,type='approval_request',turn_id='a',approval_id='ap-1',summary='Okay?',command='nc',choices=['once','deny'])
    async def waits():
        for _ in range(6):  # thinking keeps the wait fresh well past the limit
            await asyncio.sleep(.1)
            c.last_frame=time.monotonic()
            c.changed.set()
        emit(c,type='approval_resolved',approval_id='ap-1',outcome='approved')
        emit(c,type='turn_done',turn_id='a')
        c.changed.set()
    task=asyncio.create_task(waits())
    started=time.monotonic()
    assert (await c.wait('turn_done',timeout=.1))['turn_id']=='a'
    assert time.monotonic()-started>.3, 'the wait ended at the absolute limit'
    await task
    assert not c.pending_approvals


async def test_an_absolute_limit_applies_when_no_approval_is_pending():
    c=Client('ws://invalid','unused')
    with pytest.raises(TimeoutError,match='waiting for turn_done'):
        await c.wait('turn_done',timeout=.05)


async def test_a_silent_approval_wait_still_ends(monkeypatch):
    monkeypatch.setattr(Client,'APPROVAL_INACTIVITY',.05)
    c=Client('ws://invalid','unused')
    emit(c,type='thinking',turn_id='a',tool_calls=0,reasoning_tokens=None)
    emit(c,type='approval_request',turn_id='a',approval_id='ap-1',summary='Okay?',command='nc',choices=['once'])
    with pytest.raises(TimeoutError,match='approval pending'):
        await c.wait('turn_done',timeout=.05)


def test_an_ending_clears_an_unresolved_approval():
    c=Client('ws://invalid','unused')
    emit(c,type='thinking',turn_id='a',tool_calls=0,reasoning_tokens=None)
    emit(c,type='approval_request',turn_id='a',approval_id='ap-1',summary='Okay?',command='nc',choices=['once'])
    emit(c,type='turn_done',turn_id='a')
    assert not c.pending_approvals


@pytest.mark.parametrize('code,error,fmt,expected', [
    (4503,'audio_unavailable','opus','unavailable'),
    (4404,'conversation_unavailable','opus','failure'),
    (4404,'audio_unavailable','opus','failure'),
    (4503,'audio_unavailable','pcm16','failure'),
])
async def test_only_documented_optional_codec_refusal_is_unavailable(code,error,fmt,expected):
    from types import SimpleNamespace
    from arya_test.client import AudioUnavailable
    c=Client('ws://invalid','unused',audio_format=fmt)
    c.closed=True
    c.ws=SimpleNamespace(close_code=code)
    c.events=[dict(type='error',error=error)]
    with pytest.raises(AudioUnavailable if expected=='unavailable' else AssertionError):
        await c.wait('ready')


def test_replay_comparison_excludes_unrelated_outbound_turns():
    from tests.test_speech import assistant_text
    c=Client('ws://invalid','unused',transcripts=True)
    c.events=[dict(type='transcript',role='assistant',turn_id='answer',text='Four.'),
              dict(type='transcript',role='assistant',turn_id='notice',text='Unrelated notice.')]
    assert assistant_text(c,turn_id='answer')=='Four.'


class RecordingSocket:
    closed=False
    def __init__(self): self.frames=[]
    async def send_json(self, frame): self.frames.append(frame)
    async def send_bytes(self, data): pass
    async def close(self): self.closed=True


async def test_commit_is_a_typed_endpointing_frame(monkeypatch):
    async def silence(text, rate): return bytes(rate//50*2)
    monkeypatch.setattr('arya_test.client.speech', silence)
    c=Client('ws://invalid','unused')
    c.ws=RecordingSocket()
    await c.utterance('hello')
    c.closed=True
    await c.stop_ambient()
    assert c.ws.frames==[{'type':'endpointing','commit':True}]


async def test_close_sends_no_frame():
    c=Client('ws://invalid','unused')
    c.ws=RecordingSocket()
    await c.close()
    assert c.ws.closed and c.ws.frames==[]


@pytest.mark.parametrize('broken', [
    {'reasoning_support': 'supported'}, {'reasoning_level': False},
    {'pending': 1}, {'reasoning_levels': 'low'}, {'reasoning_support': 'maybe'},
])
def test_reasoning_validator_rejects_malformed_state(broken):
    state = dict(model='free', provider=None, reasoning_support='unknown', reasoning_levels=[],
                 reasoning_override=None, reasoning_level=None, pending=False)
    Client._validate_current_model(state)
    with pytest.raises(AssertionError):
        Client._validate_current_model({**state, **broken})


def test_unknown_reasoning_may_list_unconfirmed_levels():
    Client._validate_current_model(dict(model='agent', provider='litellm', reasoning_support='unknown',
                                        reasoning_levels=['low', 'high'], reasoning_override=None,
                                        reasoning_level=None, pending=False))
