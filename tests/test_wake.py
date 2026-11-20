"""Live server wire checks. These do not test physical wake detectors."""
import pytest
from arya_test.wake import verify_models
from tests.test_speech import assistant_text

pytestmark = pytest.mark.live


@pytest.mark.parametrize('wake_word_format', ['micro_wake_word', 'open_wake_word'])
async def test_ready_wake_models_authenticated_and_hash_verified(client, wake_word_format):
    c = await client(wake_word_format=wake_word_format)
    word = c.ready.get('wake_word')
    assert word is not None, 'configured live target must advertise wake_word'
    if not word['models']:
        # An uncached configured phrase can arrive after ready.
        word = await c.wait('set_wake_word', timeout=30)
    assert set(word['models']) == {wake_word_format}, 'live target offered no model in the device format'
    assert await verify_models(c.http, c.url, c.key, word)
    # Headless client has no detector. Report unavailability, never pretend it loaded.
    await c.send(type='wake_word_set', phrase=word['phrase'], status='error', error='model_unavailable')
    await c.select_free()


async def test_a_device_without_a_format_gets_no_wake_word(client):
    c = await client()  # Client.connect asserts ready has no wake_word
    await c.select_free()


@pytest.mark.parametrize('error', ['model_unavailable', 'download_failed', 'hash_mismatch', 'load_failed'])
async def test_wake_result_frame_keeps_connection_usable(client, error):
    c = await client(wake_word_format='micro_wake_word')
    phrase = c.ready.get('wake_word', {}).get('phrase', 'Hey Sakura')
    await c.send(type='wake_word_set', phrase=phrase, status='error', error=error)
    await c.select_free()


@pytest.mark.speech
async def test_live_set_wake_word_reports_failure_on_same_socket(client):
    c = await client(transcripts=True, wake_word_format='micro_wake_word')
    previous = c.ready['wake_word']['phrase']
    target = 'Hey Arya' if previous != 'Hey Arya' else 'Hey Sakura'
    offset = await c.utterance(f'Change my wake word to {target}. Call the set wake word tool to do it. Give a very brief reply after the tool finishes.')
    command = await c.wait('set_wake_word', after=offset, timeout=120)
    assert command['phrase'] == target
    await verify_models(c.http, c.url, c.key, command)
    # This exercises a real server command/result round trip. No physical loading claimed.
    await c.send(type='wake_word_set', phrase=command['phrase'], status='error', error='load_failed')
    done = await c.finish(offset)
    reply = assistant_text(c, offset, turn_id=done['turn_id']).lower()
    assert any(word in reply for word in ('fail', 'unable', 'could not', "couldn't", 'cannot', 'not changed')), 'model did not report the failed switch'
    await c.select_free()
    device = c.start['device_name']
    await c.close()
    reconnected = await client(device=device, wake_word_format='micro_wake_word')
    assert reconnected.ready['wake_word']['phrase'] == previous, 'failed switch was persisted'
