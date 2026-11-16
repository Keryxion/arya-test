import os
import json
import hashlib
from pathlib import Path
import pytest
import pytest_asyncio
from arya_test.client import Client


@pytest.fixture
def live_config():
    url, key = os.environ.get('ARYA_URL'), os.environ.get('ARYA_API_KEY')
    if not url or not key:
        pytest.fail('Live checks require ARYA_URL and ARYA_API_KEY; never silently skip')
    return url, key


@pytest_asyncio.fixture
async def client(live_config, request):
    clients = []
    async def create(browser=False, select=True, **start):
        c = Client(*live_config, **start)
        clients.append(c)
        return await c.connect(browser=browser, select=select)
    yield create
    failures = []
    for c in clients:
        await c.close()
        if c.failure:
            failures.append(str(c.failure))
    destination=Path('reports/traces')
    destination.mkdir(parents=True, exist_ok=True)
    name=hashlib.sha256(request.node.nodeid.encode()).hexdigest()[:16]
    (destination/(name+'.json')).write_text(json.dumps({'test':request.node.nodeid,
        'connections':[{'events':c.events,'offending_frame':c.offending_frame,'failure':str(c.failure) if c.failure else None,
        'audio_bytes':{tid:len(t.pcm) for tid,t in c.turns.items()}} for c in clients]}, indent=2))
    assert not failures, '; '.join(failures)
