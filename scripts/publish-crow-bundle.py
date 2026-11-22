#!/usr/bin/env python3
"""Publish this revision's source archive to Crow; no GitHub credential in test jobs."""
import base64
import gzip
import subprocess
import tempfile

sha=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
archive=subprocess.check_output(['git','archive','--format=tar',sha])
bundle=gzip.compress(archive,mtime=0)
name='arya_test_source'
# The archive is too long for a command-line argument, so crow reads it from a file.
with tempfile.NamedTemporaryFile() as value:
    value.write(base64.b64encode(bundle))
    value.flush()
    # One secret that always holds the latest suite: replace it, or create it the first time.
    for verb in ('update','add'):
        result=subprocess.run(['crow','--disable-update-check','repo','secret',verb,'--repository',
            'Keryxion/hermes-converse','--name',name,'--value','@'+value.name,
            '--event','deployment'],capture_output=True,text=True)
        if not result.returncode:
            break
    else:
        raise SystemExit('Crow source-bundle publication failed (output withheld)')
print('Suite revision:',sha)
print('Crow source secret:',name)
