import os
import json
import hashlib
import subprocess
import time
from pathlib import Path
import pytest
import pytest_asyncio
from arya_test.client import Client, AudioUnavailable, MODEL


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


def pytest_terminal_summary(terminalreporter, exitstatus):
    """Write reports/summary.md: the report ci/run.sh prints and posts."""
    stats=terminalreporter.stats
    reports={k:[r for r in stats.get(k,[]) if getattr(r,'when','call') in ('call','setup')] for k in ('passed','failed','error','skipped','xfailed','xpassed')}
    reports['failed'] += list(stats.get('error', []))
    reports.pop('error')
    counts=', '.join(f'{len(v)} {k}' for k,v in reports.items() if v) or 'no tests ran'
    reason=lambda r: (getattr(getattr(r.longrepr,'reprcrash',None),'message','') or str(r.longrepr)).strip().splitlines()[0][:200]
    revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=Path(__file__).resolve().parents[1],
        capture_output=True, text=True, check=False).stdout.strip() or 'unknown'
    # The report comment is edited in place, so GitHub's date on it is the first run's.
    lines=[f"## {'❌' if exitstatus or reports['failed'] else '✅'} Arya live suite: {counts}",'',
        time.strftime('Run finished %Y-%m-%d %H:%M UTC.', time.gmtime()),'',
        f"Target `{os.environ.get('ARYA_URL','unset')}`, model `{MODEL or 'server default'}`, server commit `{os.environ.get('CI_COMMIT_SHA','unknown')[:12]}`.",
        f"Suite commit `{revision[:12]}`; pytest exit status `{int(exitstatus)}`."]
    if exitstatus and not reports['failed']:
        lines += ['', 'Run incomplete or unsuccessful; see the full log for collection errors, interruption, or no tests collected.']
    # One line per distinct reason: an unreachable server fails every test the same way.
    by_reason={}
    for r in reports['failed']:
        by_reason.setdefault(reason(r),[]).append(r.nodeid)
    if by_reason:
        lines+=['','### Failed','']
    for why,ids in sorted(by_reason.items(),key=lambda x:-len(x[1])):
        names=', '.join(f'`{i}`' for i in ids)
        lines.append(f'- **{len(ids)}×** {why}: {names}' if len(ids)>1 else f'- {names}: {why}')
    if reports['xpassed']:
        lines+=['','### Passing despite an xfail mark (remove the mark)','']+[f'- `{r.nodeid}`' for r in reports['xpassed']]
    if reports['skipped']:
        lines += ['', '### Coverage not exercised', '']
        for r in reports['skipped']:
            # Pytest skip longrepr is (path, line, reason), not a crash repr.
            detail = r.longrepr[2] if isinstance(r.longrepr, tuple) and len(r.longrepr) == 3 else reason(r)
            lines.append(f'- `{r.nodeid}`: {str(detail).removeprefix("Skipped: ")[:200]}')
    if os.environ.get('CI_PIPELINE_URL'):
        lines+=['',f"[Full log]({os.environ['CI_PIPELINE_URL']})"]
    Path('reports').mkdir(exist_ok=True)
    Path('reports/summary.md').write_text('\n'.join(lines)+'\n')
