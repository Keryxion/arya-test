"""Wire validation and authenticated downloads; no detector or device emulation."""
import hashlib
import re
from urllib.parse import urljoin, urlsplit


def validate_wake_word(word, wake_word_format=None):
    assert isinstance(word, dict), 'wake_word must be an object'
    assert isinstance(word.get('phrase'), str) and word['phrase'].strip(), 'missing wake phrase'
    models = word.get('models')
    assert isinstance(models, dict), 'wake models must be an object'
    assert set(models) <= {'micro_wake_word', 'open_wake_word'}, 'unknown wake engine'
    if wake_word_format is not None:
        assert set(models) <= {wake_word_format}, 'wake model offered in a format the device does not run'
    for model in models.values():
        assert isinstance(model, dict), 'wake model must be an object'
        assert isinstance(model.get('url'), str) and model['url'], 'missing model URL'
        assert isinstance(model.get('sha256'), str) and re.fullmatch('[0-9a-f]{64}', model['sha256']), 'invalid model sha256'


def model_url(server, reference):
    # Never forward the API key to another host, even for a malformed advertisement.
    server = server.replace('wss://', 'https://', 1).replace('ws://', 'http://', 1)
    url = urljoin(server, reference)
    origin, target = urlsplit(server), urlsplit(url)
    assert (origin.scheme, origin.netloc) == (target.scheme, target.netloc), 'model URL leaves server origin'
    assert not target.username and not target.password, 'model URL contains credentials'
    return url


async def verify_models(http, server, key, word):
    validate_wake_word(word)
    sizes = {}
    for engine, model in word['models'].items():
        url = model_url(server, model['url'])
        # Both absent and incorrect credentials must be rejected before serving bytes.
        for headers in ({}, {'Authorization': 'Bearer arya-test-invalid-key'}):
            async with http.get(url, headers=headers, allow_redirects=False) as response:
                assert response.status == 401, 'wake model endpoint did not require authentication'
        async with http.get(url, headers={'Authorization': 'Bearer '+key}, allow_redirects=False) as response:
            assert response.status == 200, 'authenticated wake model download failed'
            data = await response.read()
        assert data and hashlib.sha256(data).hexdigest() == model['sha256'], 'wake model hash mismatch'
        sizes[engine] = len(data)
        if engine == 'micro_wake_word':
            import json
            manifest = json.loads(data)
            reference = manifest.get('model')
            assert isinstance(reference, str) and reference.endswith('.tflite'), 'manifest missing TFLite model'
            weights = model_url(url, reference)
            async with http.get(weights, allow_redirects=False) as response:
                assert response.status == 401, 'TFLite endpoint did not require authentication'
            async with http.get(weights, headers={'Authorization': 'Bearer '+key}, allow_redirects=False) as response:
                assert response.status == 200, 'authenticated TFLite download failed'
                assert await response.read(), 'empty TFLite model'
            # The contract hashes the manifest, not its referenced TFLite bytes.
    return sizes
