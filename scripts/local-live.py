#!/usr/bin/env python3
"""Run locally using Penny's existing API key over authenticated SSH; never print it."""
import os
import subprocess
import sys

result = subprocess.run(['ssh','-o','BatchMode=yes','penny',
    '''python3 -c 'from pathlib import Path; import shlex; lines=(Path.home()/".hermes/.env").read_text().splitlines(); print(next(shlex.split(x.split("=",1)[1])[0] for x in lines if x.startswith("API_SERVER_KEY=")))' '''
], check=True, capture_output=True, text=True)
env = dict(os.environ, ARYA_URL='wss://penny.z13.org/v1/audio/converse', ARYA_API_KEY=result.stdout.strip())
raise SystemExit(subprocess.call([sys.executable,'-m','pytest',*sys.argv[1:]], env=env))
