#!/usr/bin/env python3
"""Publish a versioned source archive to Crow; no GitHub credential in test jobs."""
import base64
import gzip
import hashlib
import subprocess

sha=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
archive=subprocess.check_output(['git','archive','--format=tar',sha])
bundle=gzip.compress(archive,mtime=0)
name='arya_test_source_'+sha[:12]
result=subprocess.run(['crow','--disable-update-check','repo','secret','add',
    'Keryxion/hermes-converse','--name',name,'--value',base64.b64encode(bundle).decode(),
    '--event','push','--event','manual'],capture_output=True,text=True)
if result.returncode:
    raise SystemExit('Crow source-bundle publication failed (output withheld)')
print('Suite revision:',sha)
print('Crow source secret:',name)
print('Archive SHA256:',hashlib.sha256(bundle).hexdigest())
