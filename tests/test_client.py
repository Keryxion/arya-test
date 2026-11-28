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
    c._validate({'type':'thinking','turn_id':'a','tool_calls':0,'reasoning_tokens':None},0)
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


def test_an_announcement_opened_by_speaking_emits_no_transcripts():
    c=Client('ws://invalid','unused',transcripts=True)
    c.expect_announcement()
    emit(c,type='speaking',turn_id='a')
    c._audio(b'\1\0',time.monotonic())  # audio with no reply text before it is allowed
    with pytest.raises(AssertionError,match='say emitted'):
        emit(c,type='transcript',turn_id='a',role='assistant',text='hello')


@pytest.mark.parametrize('frame', [dict(), dict(muted='yes'), dict(muted=1), dict(volume=1.01), dict(volume=True), dict(muted=True,volume=None)])
def test_validator_rejects_malformed_controls(frame):
    c=Client('ws://invalid','unused')
    for good in (dict(muted=True), dict(volume=0), dict(muted=False,volume=0.4)):
        c._validate({'type':'controls',**good},0)
    with pytest.raises(AssertionError,match='controls'):
        c._validate({'type':'controls',**frame},0)


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


def test_resume_without_reply_text_carries_its_counters():
    """Reconnecting during a turn: the running-text snapshot appears only when
    the turn already has reply text, and the thinking counters carry on from
    where they were rather than restarting at zero."""
    c=Client('ws://invalid','unused',transcripts=True,
             resume=dict(turn_id='turn-41',tool_calls=3,reasoning_tokens=2400))
    emit(c,type='transcript',turn_id='turn-41',role='user',text='hello',message_id='m-123',replay=True)
    emit(c,type='state',turn_id='turn-41',state='thinking')
    assert c.snapshot_turn is None and c.turns['turn-41'].resumed
    emit(c,type='thinking',turn_id='turn-41',tool_calls=3,reasoning_tokens=2400)
    emit(c,type='transcript',turn_id='turn-41',role='assistant',text='Two things tomorrow.')
    emit(c,type='transcript',turn_id='turn-41',role='assistant',text='',message_id='m-124')
    emit(c,type='turn_done',turn_id='turn-41')


def test_a_turn_opened_by_state_must_still_reset_its_counters():
    """The server opens every turn with `state` then `thinking`: that is a
    turn starting, not a resume, and its counters open at zero."""
    c=Client('ws://invalid','unused')
    emit(c,type='state',turn_id='a',state='thinking')
    assert not c.turns['a'].resumed
    with pytest.raises(AssertionError,match='initial counters not reset'):
        emit(c,type='thinking',turn_id='a',tool_calls=3,reasoning_tokens=2400)


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
    emit(c,type='thinking',turn_id='a',tool_calls=0,reasoning_tokens=None)
    emit(c,**frame)
    await c._drain('a')
    assert c.activation is expected
    assert sent[-1]['state']==('listening' if expected else 'standby')


def test_reply_text_precedes_first_audio():
    c=Client('ws://invalid','unused',transcripts=True)
    emit(c,type='speaking',turn_id='a')
    c._audio(b'\1\0',1)
    with pytest.raises(AssertionError,match='before live transcript'):
        emit(c,type='transcript',role='assistant',turn_id='a',text='Hello')


def test_a_tone_is_reply_audio_with_no_text():
    """Section 4: a reply that is only a confirm or error tone has audio and no
    `transcript` frame."""
    c=Client('ws://invalid','unused',transcripts=True)
    emit(c,type='speaking',turn_id='a')
    c._audio(b'\1\0',1)
    emit(c,type='turn_done',turn_id='a')


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
    assert c.ws.frames==[{'type':'state','state':'listening'},{'type':'endpointing','commit':True}]


async def test_close_sends_no_frame():
    c=Client('ws://invalid','unused')
    c.ws=RecordingSocket()
    await c.close()
    assert c.ws.closed and c.ws.frames==[]


@pytest.mark.parametrize('broken', [
    {'reasoning_level': False},
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


@pytest.mark.parametrize('providers,refused,outcome', [
    ([], True, None),                                                  # nothing advertised, refused: default stands
    ([dict(slug='p',name='P',models=['other'])], True, None),         # not offered: never asked
    ([dict(slug='p',name='P',models=['free'])], False, 'selected'),
    ([dict(slug='p',name='P',models=['free'])], True, 'fail'),        # offered, then refused
    ([dict(slug='p',name='P',models=['free'])], 'reply', None),       # refused in reply text (section 11)
])
def test_select_model_only_tolerates_a_model_nobody_offered(providers, refused, outcome):
    c=Client('ws://invalid','unused')
    c.ready=dict(model_catalog=dict(providers=providers))
    state=dict(model='default' if refused else 'free',provider='p',pending=False)
    async def command(name, args):
        return dict(current_model=state, **({'error':'refused'} if refused is True else {'reply':'No such model.'} if refused else {}))
    c.setting_command=command
    if outcome=='fail':
        with pytest.raises(AssertionError):
            asyncio.run(c.select_model('free'))
    else:
        assert asyncio.run(c.select_model('free')) == (state if outcome else None)


class Wire:
    """A client with its socket replaced by a list of what it sent."""
    def __new__(cls, **kw):
        c=Client('ws://invalid','unused',**kw)
        c.sent=[]
        async def send(data=None, **frame): c.sent.append(data if data is not None else frame)
        c.send=send
        return c


async def act(c, **frame):
    c._validate(frame, 0)
    c.events.append(frame)
    await c._act(frame)


async def test_a_server_controls_mute_is_applied_and_answered():
    c=Wire()
    c.activation=True
    await act(c,type='controls',muted=True)
    assert c.muted and not c.activation
    assert c.sent==[{'type':'endpointing','commit':True},{'type':'state','state':'standby'},{'type':'controls','muted':True}]
    c.sent.clear()
    await act(c,type='controls',muted=False)   # unmuting lands in standby
    assert not c.muted and not c.activation
    assert c.sent==[{'type':'state','state':'standby'},{'type':'controls','muted':False}]


async def test_a_controls_frame_is_answered_even_when_nothing_changes_and_volume_is_ignored():
    c=Wire()
    await act(c,type='controls',volume=0.7)
    await act(c,type='controls',muted=False)
    assert c.sent==[{'type':'controls','muted':False}]*2


async def test_an_idle_mute_commits_nothing():
    c=Wire()
    await act(c,type='controls',muted=True)
    assert not any(f['type']=='endpointing' for f in c.sent)


async def test_mute_next_action_is_applied_on_receipt_and_reported():
    c=Wire()
    c.activation=True
    await act(c,type='thinking',turn_id='a',tool_calls=0,reasoning_tokens=None)
    await act(c,type='turn_done',turn_id='a',next_action='mute')
    assert c.muted and c.sent[-1]=={'type':'controls','muted':True}
    assert {'type':'endpointing','commit':True} in c.sent
    await asyncio.gather(*c.tasks)


async def test_client_diagnostics_is_answered_with_the_request_id():
    c=Wire()
    await act(c,type='client_diagnostics',request_id='diag-1')
    (answer,)=c.sent
    assert answer['type']=='client_diagnostics' and answer['request_id']=='diag-1'
    assert answer['version'] and answer['build'] and isinstance(answer['diagnostics'],dict)
    assert 'error' not in answer and len(str(answer).encode())<32*1024
    with pytest.raises(AssertionError,match='request_id'):
        await act(c,type='client_diagnostics')


async def test_quiet_returns_to_standby_at_the_threshold_only_while_listening():
    c=Wire()
    c.activation=True
    await act(c,type='quiet',quiet_seconds=4.0)
    assert c.activation and not c.sent
    await act(c,type='quiet',quiet_seconds=5.0)
    assert not c.activation and c.sent==[{'type':'state','state':'standby'}]
    c.sent.clear()
    await act(c,type='quiet',quiet_seconds=6.0)
    assert not c.sent


def test_the_default_start_asks_for_quiet_frames():
    assert Client('ws://invalid','unused').start['quiet_interval']==1


async def test_next_action_of_a_turn_never_seen_to_start_is_ignored():
    c=Wire()
    c.activation=True
    await act(c,type='turn_done',turn_id='ghost',next_action='standby')
    assert c.turns['ghost'].action is None
    await c._drain('ghost')
    assert c.activation, 'a standby for a turn the device never saw start changed the activation'


async def test_a_second_turn_done_replaces_the_pending_ending():
    c=Wire()
    c.activation=True
    await act(c,type='thinking',turn_id='a',tool_calls=0,reasoning_tokens=None)
    await act(c,type='speaking',turn_id='a')
    c.turns['a'].speaker_until=time.monotonic()+.3   # still playing
    await act(c,type='turn_done',turn_id='a',next_action='standby')
    await act(c,type='interrupted',turn_id='a')
    await act(c,type='turn_done',turn_id='a')
    await asyncio.gather(*c.tasks,return_exceptions=True)
    assert c.activation, 'the dropped standby was applied'
    states=[f for f in c.sent if f['type']=='state' and f.get('turn_id')=='a' and f['state']!='speaking']
    assert states==[{'type':'state','turn_id':'a','state':'listening'}]


async def test_an_ending_already_applied_ignores_later_frames_of_the_turn():
    c=Wire()
    await act(c,type='thinking',turn_id='a',tool_calls=0,reasoning_tokens=None)
    await act(c,type='turn_done',turn_id='a')
    await asyncio.gather(*c.tasks)
    sent=len(c.sent)
    await act(c,type='interrupted',turn_id='a')
    await act(c,type='turn_done',turn_id='a')
    assert len(c.sent)==sent and len(c.tasks)==1


@pytest.mark.parametrize('own,expected',[(False,True),(True,False)])
async def test_an_interruption_by_the_persons_speech_listens_but_our_own_cancel_does_not(own,expected):
    c=Wire()
    await act(c,type='thinking',turn_id='a',tool_calls=0,reasoning_tokens=None)
    if own:
        c.turns['a'].ours=True
    await act(c,type='interrupted',turn_id='a')
    await act(c,type='turn_done',turn_id='a')
    await asyncio.gather(*c.tasks)
    assert c.activation is expected


async def test_sending_cancel_or_new_marks_the_interruption_as_ours():
    c=Client('ws://invalid','unused')
    class Socket:
        async def send_json(self, frame): pass
    c.ws=Socket()
    emit(c,type='thinking',turn_id='a',tool_calls=0,reasoning_tokens=None)
    emit(c,type='thinking',turn_id='b',tool_calls=0,reasoning_tokens=None)
    await c.send(type='cancel',turn_id='b')
    assert c.turns['b'].ours and not c.turns['a'].ours
    await c.send(type='command',name='new')
    assert c.turns['a'].ours


async def test_a_server_state_applies_after_playback_drains_and_not_for_a_finished_turn():
    c=Wire()
    await act(c,type='thinking',turn_id='a',tool_calls=0,reasoning_tokens=None)
    c.turns['a'].speaker_until=time.monotonic()+.2
    await act(c,type='state',turn_id='a',state='listening')
    assert not c.sent
    await asyncio.sleep(.35)
    assert c.sent==[{'type':'state','turn_id':'a','state':'listening'}]


async def test_cancelling_a_countdown_it_holds_ends_it():
    c=Wire()
    await act(c,type='countdown',countdown_id='c1',deadline_unix_ms=1,ring_seconds=900,sound='alarm-1')
    await act(c,type='countdown_cancel',countdown_id='unknown')
    assert not c.sent
    await act(c,type='countdown_cancel',countdown_id='c1')
    assert c.sent==[{'type':'countdown','countdown_id':'c1','ended':True}]


async def test_late_frames_of_applied_turn_do_not_poison_the_next_turn():
    c=Wire()
    await act(c,type='thinking',turn_id='old',tool_calls=0,reasoning_tokens=None)
    await act(c,type='turn_done',turn_id='old')
    await asyncio.gather(*c.tasks)
    sent=list(c.sent)
    await act(c,type='interrupted',turn_id='old')
    assert c.pending_interruption is None
    await act(c,type='speaking',turn_id='old')
    assert c.sent==sent
    await act(c,type='thinking',turn_id='new',tool_calls=0,reasoning_tokens=None)
    await act(c,type='speaking',turn_id='new')
    c._audio(bytes(960),time.monotonic())
    assert c.active_audio=='new'
