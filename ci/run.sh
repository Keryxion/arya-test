#!/bin/sh
set -eu
: "${ARYA_API_KEY:?Set the Penny API key through Crow secrets}"
export ARYA_URL="${ARYA_URL:-wss://penny.z13.org/v1/audio/converse}"
printf 'Live target: %s; model: free; triggering commit: %s\n' "$ARYA_URL" "${CI_COMMIT_SHA:-local}"
printf 'Hermes deployment checks run after the alpha deploy succeeds; standalone manual runs test the current live server.\n'
python -m pip install --disable-pip-version-check -q .
mkdir -p reports
exec python -m pytest --junitxml=reports/junit.xml
