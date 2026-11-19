"""Negative controls for the harness, not evidence of physical client behavior."""
import copy
import pytest
from arya_test.client import Client
from arya_test.wake import validate_wake_word, model_url

WORD = {'phrase': 'Hey Sakura', 'models': {'open_wake_word': {
    'url': '/v1/audio/wake/hey_sakura/hey_sakura.onnx', 'sha256': 'a'*64}}}


@pytest.mark.parametrize('word', [None, {}, {'phrase': '', 'models': {}},
    {'phrase': 'Hey Sakura', 'models': []}, {'phrase': 'Hey Sakura', 'models': {'unknown': {}}}])
def test_reject_malformed_word(word):
    with pytest.raises(AssertionError):
        validate_wake_word(word)


@pytest.mark.parametrize('field,value', [('sha256', 'a'*63), ('sha256', 'not-a-hash'), ('sha256', None), ('url', '')])
def test_reject_bad_download_descriptor(field, value):
    word = copy.deepcopy(WORD)
    word['models']['open_wake_word'][field] = value
    with pytest.raises(AssertionError):
        validate_wake_word(word)


def test_reject_a_model_in_another_format():
    validate_wake_word(WORD, 'open_wake_word')
    with pytest.raises(AssertionError):
        validate_wake_word(WORD, 'micro_wake_word')


def test_reject_set_wake_word_without_a_format():
    with pytest.raises(AssertionError):
        Client('ws://invalid', 'unused')._validate(dict(type='set_wake_word', **WORD), 0)


def test_live_frame_uses_same_validation_as_ready():
    c = Client('ws://invalid', 'unused', wake_word_format='open_wake_word')
    c._validate(dict(type='set_wake_word', **WORD), 0)
    with pytest.raises(AssertionError):
        c._validate(dict(type='set_wake_word', phrase='Hey Sakura'), 0)
    validate_wake_word({'phrase': 'Hey Sakura', 'models': {}})  # bundled model allowed


@pytest.mark.parametrize('reference', ['https://other.invalid/model', '//other.invalid/model', 'http://example.invalid/model'])
def test_refuse_to_send_key_outside_origin(reference):
    with pytest.raises(AssertionError, match='origin'):
        model_url('wss://example.invalid/v1/audio/converse', reference)


def test_manifest_relative_model_url():
    assert model_url('https://example.invalid/v1/audio/wake/a/manifest.json', 'a.tflite') == 'https://example.invalid/v1/audio/wake/a/a.tflite'


@pytest.mark.parametrize('fault', [None, 'public', 'corrupt'])
async def test_download_verifier_rejects_public_and_corrupted_models(fault):
    import hashlib
    import aiohttp
    from aiohttp import web
    from arya_test.wake import verify_models
    data = b'local harness fixture, not an ONNX detector'
    async def download(request):
        if fault != 'public' and request.headers.get('Authorization') != 'Bearer test-only':
            return web.Response(status=401)
        return web.Response(body=data if fault != 'corrupt' else b'corrupt')
    app = web.Application()
    app.router.add_get('/model', download)
    runner = web.AppRunner(app)
    await runner.setup()
    try:
        site = web.TCPSite(runner, '127.0.0.1', 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        word = {'phrase': 'Hey Sakura', 'models': {'open_wake_word': {
            'url': '/model', 'sha256': hashlib.sha256(data).hexdigest()}}}
        async with aiohttp.ClientSession() as http:
            if fault:
                with pytest.raises(AssertionError, match='authentication' if fault == 'public' else 'hash mismatch'):
                    await verify_models(http, f'http://127.0.0.1:{port}', 'test-only', word)
            else:
                assert await verify_models(http, f'http://127.0.0.1:{port}', 'test-only', word) == {'open_wake_word': len(data)}
    finally:
        await runner.cleanup()
