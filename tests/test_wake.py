"""Live server wire checks. These do not test physical wake detectors."""
import pytest
from arya_test.wake import verify_models

pytestmark = pytest.mark.live


async def test_ready_wake_models_authenticated_and_hash_verified(client):
    c = await client()
    word = c.ready.get('wake_word')
    assert word is not None, 'configured live target must advertise wake_word'
    if not word['models']:
        # An uncached configured phrase can arrive after ready.
        word = await c.wait('set_wake_word', timeout=30)
    assert word['models'], 'live target offered no models to verify'
    assert await verify_models(c.http, c.url, c.key, word)
    # Headless client has no detector. Report unavailability, never pretend it loaded.
    await c.send(type='wake_word_set', phrase=word['phrase'], status='error', error='model_unavailable')
    await c.select_free()


@pytest.mark.parametrize('error', ['model_unavailable', 'download_failed', 'hash_mismatch', 'load_failed'])
async def test_wake_result_frame_keeps_connection_usable(client, error):
    c = await client()
    phrase = c.ready.get('wake_word', {}).get('phrase', 'Hey Sakura')
    await c.send(type='wake_word_set', phrase=phrase, status='error', error=error)
    await c.select_free()


@pytest.mark.speech
async def test_live_set_wake_word_reports_failure_on_same_socket(client):
    c = await client(transcripts=True)
    offset = await c.utterance('Use the set wake word tool now to change this device wake word to Hey Sakura. Do not just describe how.')
    command = await c.wait('set_wake_word', after=offset, timeout=120)
    assert command['phrase'] == 'Hey Sakura'
    await verify_models(c.http, c.url, c.key, command)
    # This exercises a real server command/result round trip. No physical loading claimed.
    await c.send(type='wake_word_set', phrase=command['phrase'], status='error', error='load_failed')
    await c.finish(offset)
    await c.select_free()
