"""All assertions come from hermes-converse specs/client.md, never server imports/mocks."""
import asyncio
import uuid
import aiohttp
import pytest

pytestmark = pytest.mark.live


def start(key):
    return dict(type='start', key=key, assistant_name='Arya', device_name='arya-test-'+uuid.uuid4().hex)


async def rejected(config, frame, code, error, binary=False):
    url, key = config
    async with aiohttp.ClientSession() as http:
        async with http.ws_connect(url) as ws:
            if binary:
                await ws.send_bytes(frame)
            else:
                await ws.send_json(frame(key) if callable(frame) else frame)
            async with asyncio.timeout(20):
                response = await ws.receive_json()
                assert response == {'type': 'error', 'error': error}
                await ws.receive()
                assert ws.close_code == code


@pytest.mark.parametrize('frame', [None, [], {}, {'type':'commit'}, 'not start'])
async def test_first_frame_must_be_start(live_config, frame):
    await rejected(live_config, frame, 4400, 'bad_start')


async def test_binary_first_frame(live_config):
    await rejected(live_config, b'\0\0', 4400, 'bad_start', binary=True)


@pytest.mark.parametrize('key', ['', 'arya-test-invalid-key', None])
async def test_bad_or_missing_key(live_config, key):
    f = start(key)
    if key is None:
        del f['key']
    await rejected(live_config, f, 4401, 'unauthorized')


async def test_invalid_browser_key_rejected_before_upgrade(live_config):
    async with aiohttp.ClientSession() as http:
        with pytest.raises(aiohttp.WSServerHandshakeError) as e:
            await http.ws_connect(live_config[0], protocols=['hermes-voice-v1','hermes-key.invalid-arya-test'])
        assert e.value.status == 401


@pytest.mark.parametrize('field', ['assistant_name','device_name'])
async def test_required_names(live_config, field):
    def frame(key):
        f = start(key)
        del f[field]
        return f
    await rejected(live_config, frame, 4400, 'bad_start')


@pytest.mark.parametrize('field', ['profile','name','conversation','conversation_id'])
async def test_forbidden_start_fields(live_config, field):
    await rejected(live_config, lambda key: {**start(key), field:'arya-test'}, 4400, 'bad_start')


@pytest.mark.parametrize('options', [dict(audio_format='wav'), dict(audio_format='opus',input_rate=11025),
                                    dict(audio_format='opus',output_rate=44100)])
async def test_invalid_audio_configuration(live_config, options):
    await rejected(live_config, lambda key: {**start(key), **options}, 4400, 'bad_start')


@pytest.mark.parametrize('browser', [False, True])
async def test_auth_and_ready(client, browser):
    c = await client(browser=browser)
    assert c.ready['input']['sample_rate'] == 16000
    assert c.ready['output']['sample_rate'] == 24000


@pytest.mark.parametrize('rate', [8000,12000,16000,24000,48000])
@pytest.mark.parametrize('fmt', ['pcm16','opus'])
async def test_rates(client, rate, fmt):
    # set explicit rates without overriding Client's keyword defaults
    c = await client(audio_format=fmt, input_rate=rate, output_rate=rate)
    assert c.ready['input']['sample_rate'] == rate


async def test_malformed_opus_closes(client):
    c = await client(audio_format='opus')
    await c.ws.send_bytes(b'')
    await asyncio.wait_for(c.reader, 10)
    assert c.ws.close_code == 4400


async def test_attachment_replaced_and_recipient_stable(client):
    a = await client()
    b = await client(device=a.start['device_name'])
    await asyncio.wait_for(a.reader, 10)
    assert a.ws.close_code == 4409
    assert a.ready['recipient_id'] == b.ready['recipient_id']
    assert a.ready['session_id'] != b.ready['session_id']


async def test_closing_the_socket_keeps_the_conversation(client):
    a = await client()
    await a.ws.close()
    await asyncio.wait_for(a.reader, 10)
    b = await client(device=a.start['device_name'])
    assert b.ready['recipient_id'] == a.ready['recipient_id']


@pytest.mark.parametrize('value', [False, 'true', 1])
async def test_catalog_requires_boolean_true(client, value):
    c = await client(models=value)
    assert 'model_catalog' not in c.ready


async def test_model_catalog(client):
    c = await client(models=True)
    cat = c.ready['model_catalog']
    assert set(cat) <= {'model','provider','providers'}
    assert isinstance(cat['providers'], list)
    # Section 11 names no model, so the catalog's shape is the whole contract:
    # which models a server runs is its own configuration.
    for p in cat['providers']:
        assert set(p) == {'slug','name','models'}
        assert all(isinstance(m, str) and m for m in p['models'])


async def test_model_command_reset(client):
    c = await client()
    result = await c.setting_command('model', ['reset'])
    assert 'error' not in result and not result['current_model']['pending']
    for field in ('model', 'provider'):
        assert result['current_model'][field] == c.ready['current_model'][field]
    assert result['current_model'] == await c.current_model()
    await c.select_model()


@pytest.mark.parametrize('name', ['model', 'reasoning'])
async def test_malformed_setting_command_returns_current_model(client, name):
    c = await client(select=False)
    result = await c.setting_command(name, [42])
    assert result['error'] == 'bad_command' and 'reply' not in result
    assert result['current_model'] == await c.current_model()


@pytest.mark.parametrize('frame', [dict(claim_id='',wake_word='Hey Arya'),dict(claim_id='x',wake_word=''),
                                   dict(claim_id=1,wake_word='Hey Arya'), dict(wake_word='Hey Arya')])
async def test_bad_wake_keeps_socket(client, frame):
    c = await client()
    await c.send(type='wake', **frame)
    await c.wait('error',error='bad_wake')
    await c.select_model()


async def test_wake_correlated_within_one_second(client):
    c = await client()
    await c.send(type='wake',claim_id='wake-1',wake_word='Hey Arya',confidence=.9,volume=.1)
    await c.wait('wake_grant',claim_id='wake-1',wake_word='Hey Arya',timeout=1)
    await c.quiet_for(.2, {'thinking','transcript','speaking'})
    assert sum(e.get('claim_id')=='wake-1' for e in c.events)==1


async def test_wake_exact_phrases_are_independent(client):
    a, b = await client(), await client()
    await asyncio.gather(a.send(type='wake',claim_id='a',wake_word='Hey Arya'),
                         b.send(type='wake',claim_id='b',wake_word='Arya'))
    await asyncio.gather(a.wait('wake_grant',claim_id='a',wake_word='Hey Arya',timeout=1),
                         b.wait('wake_grant',claim_id='b',wake_word='Arya',timeout=1))


async def test_commands_catalog(client):
    c = await client()
    await c.send(type='commands')
    e = await c.wait('commands')
    assert isinstance(e['commands'],list) and e['commands']
    assert any(x['name']=='new' for x in e['commands'])
    for command in e['commands']:
        for k in ('name','description','args_hint'):
            assert isinstance(command[k],str)
        for k in ('aliases','subcommands'):
            assert isinstance(command[k],list)


@pytest.mark.parametrize('frame', [dict(name='/new'),dict(name='A'),dict(name='x'*41),dict(name='title',args=3)])
async def test_bad_command(client, frame):
    c = await client()
    await c.send(type='command',**frame)
    e = await c.wait('command', name=frame['name'])
    assert e.get('error')=='bad_command' and 'reply' not in e
    await c.select_model()


async def test_unknown_command(client):
    c = await client()
    await c.send(type='command',name='arya_test_nonexistent_command')
    assert (await c.wait('command', name='arya_test_nonexistent_command'))['error']=='unknown_command'


async def test_new_command_reconnect(client):
    c = await client(transcripts=True)
    await c.send(type='command',name='new')
    e = await c.wait('command',name='new')
    assert isinstance(e.get('reply'),str) and 'error' not in e
    await asyncio.wait_for(c.reader,10)
    assert c.ws.close_code==4410
    n = await client(device=c.start['device_name'],transcripts=True,after='unknown-cursor')
    assert n.ready['new_session'] is True
    assert n.ready['recipient_id']==c.ready['recipient_id']


async def test_quiet_uses_received_audio_not_wall_clock(client):
    c = await client(quiet_interval=1)
    await c.quiet_for(2.2,{'quiet','thinking'})
    offset = len(c.events)
    await c.pcm(bytes(16000*2*2))
    e = await c.wait('quiet',after=offset,timeout=5)
    assert e['quiet_seconds']>=1


async def test_empty_commit_and_say_are_ignored(client):
    c = await client()
    await c.send(type='endpointing', commit=True)
    for text in ['', '   ', None, 7]:
        await c.send(type='say',text=text)
    await c.quiet_for(1,{'thinking','speaking','turn_done'})


@pytest.mark.parametrize('signal', [dict(confidence=-1),dict(confidence=2),dict(volume='bad'),dict(heard_at=-1)])
async def test_invalid_wake_signals_treated_as_missing(client, signal):
    c=await client()
    await c.send(type='wake',claim_id='invalid-signal',wake_word='Hey Arya',**signal)
    await c.wait('wake_grant',claim_id='invalid-signal',wake_word='Hey Arya',timeout=1)


async def test_title_command_keeps_socket(client):
    c=await client()
    await c.send(type='command',name='title',args=[c.start['device_name']])
    e=await c.wait('command',name='title')
    assert isinstance(e.get('reply'),str) and 'error' not in e
    await c.select_model()


async def test_transcripts_boolean_opt_in(client):
    c=await client(transcripts='true')
    assert c.ready['transcripts'] is False


@pytest.mark.parametrize('rank', ['confidence','volume','volume_over_confidence','heard_at','arrival'])
async def test_wake_ranking_when_enabled_and_grants_when_disabled(client, rank):
    a,b=await client(),await client()
    # Equal composite scores use detection time and arrival; a louder claimant can beat higher confidence.
    sa=dict(confidence=.5,volume=.2,heard_at=1000)
    sb=dict(sa)
    if rank=='confidence': sb['confidence']=.9
    if rank=='volume': sb['volume']=.8
    if rank=='volume_over_confidence':
        sa.update(confidence=.99,volume=.05)
        sb.update(confidence=.8,volume=.2)
    if rank=='heard_at': sb['heard_at']=500
    await a.send(type='wake',claim_id='rank-a',wake_word='Hey Arya',**sa)
    await b.send(type='wake',claim_id='rank-b',wake_word='Hey Arya',**sb)
    async def decision(c,claim):
        async with asyncio.timeout(1):
            while True:
                c.changed.clear()
                if c.failure: raise c.failure
                frames=[e for e in c.events if e.get('claim_id')==claim and e['type'] in ('wake_grant','wake_deny')]
                if frames: return frames[0]['type']
                await c.changed.wait()
    da,db=await asyncio.gather(decision(a,'rank-a'),decision(b,'rank-b'))
    # The contract permits arbitration to be disabled. All grants are valid then.
    if (da,db)!=('wake_grant','wake_grant'):
        assert (da,db)==(('wake_grant','wake_deny') if rank=='arrival' else ('wake_deny','wake_grant'))
    for c,claim in [(a,'rank-a'),(b,'rank-b')]:
        await c.quiet_for(.2,{'thinking','transcript','interrupted'})
        assert sum(e.get('claim_id')==claim for e in c.events)==1


async def test_opus_non_twenty_ms_rejected(client):
    import ctypes as C
    c=await client(audio_format='opus')
    enc=c.encoder
    output=C.create_string_buffer(4000)
    n=enc.lib.opus_encode(enc.ptr,bytes(320),160,output,4000)  # 10ms at 16kHz
    assert n>0
    await c.ws.send_bytes(output.raw[:n])
    await asyncio.wait_for(c.reader,10)
    assert c.ws.close_code==4400


async def test_reset_command_alias(client):
    c=await client()
    await c.send(type='command',name='reset')
    e=await c.wait('command',name='reset')
    assert isinstance(e.get('reply'),str)
    await asyncio.wait_for(c.reader,10)
    assert c.ws.close_code==4410


async def test_opus_setup_or_explicit_unavailability(live_config):
    url,key=live_config
    async with aiohttp.ClientSession() as http:
        async with http.ws_connect(url) as ws:
            await ws.send_json({**start(key),'audio_format':'opus'})
            async with asyncio.timeout(25):
                frame=await ws.receive_json()
                if frame['type']=='ready':
                    assert frame['input']['format']==frame['output']['format']=='opus'
                else:
                    assert frame=={'type':'error','error':'audio_unavailable'}
                    await ws.receive()
                    assert ws.close_code==4503
    # Both negotiated Opus and a documented refusal must leave PCM available.
    from arya_test.client import Client
    c=Client(url,key)
    try:
        await c.connect()
    finally:
        await c.close()


@pytest.mark.parametrize('value', ['', '   ', 7, None, 'x'*99, 'bad\nname'])
async def test_invalid_name_values(live_config,value):
    await rejected(live_config,lambda key:{**start(key),'device_name':value},4400,'bad_start')


async def test_names_normalized(client):
    c=await client(device='  arya-test   e\u0301  ' + uuid.uuid4().hex)
    assert '  ' not in c.ready['device_name']
    assert 'é' in c.ready['device_name']


@pytest.mark.parametrize('field', ['input_rate','output_rate'])
@pytest.mark.parametrize('value', ['24000',16000.5,True,None,7999,96000])
async def test_pcm_rate_validation(client,field,value):
    c=await client(**{field:value})
    expected=max(8000,min(48000,value)) if type(value) is int else (16000 if field=='input_rate' else 24000)
    assert c.ready['input' if field=='input_rate' else 'output']['sample_rate']==expected


@pytest.mark.parametrize('value', ['1',True,None,-1,0])
async def test_invalid_quiet_interval_disabled(client,value):
    c=await client(quiet_interval=value)
    await c.pcm(bytes(16000*2*2))
    await c.quiet_for(.1,{'quiet'})
    assert not any(e['type']=='quiet' for e in c.events)


@pytest.mark.parametrize('value', [7,None,False])
async def test_nonstring_after_is_absent(client,value):
    c=await client(transcripts=True,after=value)
    assert 'new_session' not in c.ready


async def test_malformed_and_unknown_controls_ignored(client):
    c=await client()
    for raw in ['not-json','[]','null','"text"']:
        await c.ws.send_str(raw)
    for frame in [dict(type='unknown'),dict(type='endpointing',on='false'),
                  dict(type='countdown',countdown_id='unknown',ended=True),
                  dict(type='approval_response',approval_id='unknown',choice='once'),
                  dict(type='client_diagnostics',request_id='unrequested')]:
        await c.send(frame)
    await c.quiet_for(.2,{'error','thinking','turn_done'})
    await c.select_model()


async def test_cancel_without_turn_sends_no_terminal_frames(client):
    c=await client(transcripts=True)
    await c.send(type='cancel')
    await c.quiet_for(.3,{'interrupted','turn_done','transcript'})


async def test_reasoning_snapshot_without_catalog(client):
    c = await client(models=False, select=False)
    assert 'model_catalog' not in c.ready
    assert c.ready['current_model'] == await c.current_model()


async def test_reasoning_read_write_and_reset(client):
    c = await client(select=False)
    initial = c.ready['current_model']
    if initial['reasoning_levels']:
        level = initial['reasoning_levels'][-1]
        result = await c.setting_command('reasoning', [level])
        state = result['current_model']
        assert 'error' not in result and state['reasoning_override'] == level and not state['pending']
        assert state == await c.current_model()
    reset = await c.setting_command('reasoning', ['reset'])
    state = reset['current_model']
    assert 'error' not in reset and state['reasoning_override'] is None and not state['pending']
    assert state == await c.current_model()
