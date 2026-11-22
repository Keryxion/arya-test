#!/bin/sh
set -eu
: "${ARYA_API_KEY:?Set the Penny API key through Crow secrets}"
export ARYA_URL="${ARYA_URL:-wss://penny.z13.org/v1/audio/converse}"
python -m pip install --disable-pip-version-check -q .
status=0
python -m pytest --junitxml=reports/junit.xml || status=$?
echo; cat reports/summary.md
# The report is a courtesy: failing to post it never changes the result.
python ci/post-report.py || echo "Report not posted (exit $?)"
exit "$status"
