import os
import json
import hashlib
from pathlib import Path
import pytest
import pytest_asyncio
from arya_test.client import Client, AudioUnavailable


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
        try:
            return await c.connect(browser=browser, select=select)
        except AudioUnavailable as exc:
            pytest.skip(str(exc))
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
    if getattr(request.node, 'rep_call', None) is None or request.node.rep_call.passed:
        assert not failures, '; '.join(failures)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    setattr(item, 'rep_' + call.when, outcome.get_result())


def pytest_terminal_summary(terminalreporter):
    """Write reports/summary.md: the report ci/run.sh prints and posts."""
    stats=terminalreporter.stats
    reports={k:[r for r in stats.get(k,[]) if getattr(r,'when','call') in ('call','setup')] for k in ('passed','failed','error','skipped','xfailed','xpassed')}
    reports['failed']+=reports.pop('error')
    counts=', '.join(f'{len(v)} {k}' for k,v in reports.items() if v) or 'no tests ran'
    reason=lambda r: (getattr(getattr(r.longrepr,'reprcrash',None),'message','') or str(r.longrepr)).strip().splitlines()[0][:200]
    lines=[f"## {'❌' if reports['failed'] else '✅'} Arya live suite: {counts}",'',
        f"Target `{os.environ.get('ARYA_URL','unset')}`, model `free`, server commit `{os.environ.get('CI_COMMIT_SHA','unknown')[:12]}`."]
    root=Path(__file__).parents[1]
    spec=os.environ.get('ARYA_SPEC_FILE')
    if spec and Path(spec).read_bytes()!=(root/'specs/client.md').read_bytes():
        lines+=['',f"⚠️ The deployed `specs/client.md` differs from the suite's snapshot (`{(root/'specs/revision').read_text().strip()[:12]}`): "
            'failures may be the suite lagging the contract, not the server breaking it.']
    for title,key in (('Failed','failed'),('Unexpectedly passing (drop the xfail)','xpassed')):
        if reports[key]:
            lines+=['',f'### {title}','']+[f'- `{r.nodeid}`: {reason(r)}' if key=='failed' else f'- `{r.nodeid}`' for r in reports[key]]
    if os.environ.get('CI_PIPELINE_URL'):
        lines+=['',f"[Full log]({os.environ['CI_PIPELINE_URL']})"]
    Path('reports').mkdir(exist_ok=True)
    Path('reports/summary.md').write_text('\n'.join(lines)+'\n')
