#!/usr/bin/env python3
"""Post reports/summary.md as one comment on the deployed pull request, replacing the last one."""
import json
import os
import sys
import urllib.request
from pathlib import Path

MARK = '<!-- arya-test report -->'
token, repo, sha = (os.environ.get(k) for k in ('GITHUB_TOKEN', 'CI_REPO', 'CI_COMMIT_SHA'))
if not (token and repo and sha):
    sys.exit('needs GITHUB_TOKEN, CI_REPO and CI_COMMIT_SHA; nothing posted')


def api(url, method='GET', body=None):
    request = urllib.request.Request(url if url.startswith('https://') else 'https://api.github.com' + url,
        method=method, data=body and json.dumps(body).encode(),
        headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json'})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def pages(path):
    page = 1
    while True:
        items = api(f'{path}?per_page=100&page={page}')
        yield from items
        if len(items) < 100:
            return
        page += 1


body = MARK + '\n' + Path('reports/summary.md').read_text()
for pull in pages(f'/repos/{repo}/commits/{sha}/pulls'):
    if pull['state'] != 'open':
        continue
    comments = pages(f"/repos/{repo}/issues/{pull['number']}/comments")
    old = next((c for c in comments if MARK in c['body']), None)
    if old:
        api(old['url'], 'PATCH', {'body': body})
    else:
        api(f"/repos/{repo}/issues/{pull['number']}/comments", 'POST', {'body': body})
    print('Report posted to', pull['html_url'])
