# arya-test

Independent, headless client-contract checks for the **live Penny server**, using
**model `free`**. This private repository owns the tests; hermes-converse's Crow
workflow unpacks a pinned source revision and reports the result on each push.

The client uses only the documented WebSocket protocol. It imports no server
modules and mocks no server component. It sends synthesized microphone speech
through real VAD, STT, model execution, and TTS, receives continuously, validates
PCM16/20 ms mono Opus, and reports speaker drain at playback speed. Between
utterances the synthetic microphone supplies room silence throughout an activation.
Each connection selects `free` using `set_model` and waits for `model_changed`
before running a user turn. Test devices have unique `arya-test-*` names.

## Run

Python 3.11+, `espeak-ng`, `ffmpeg`, and `libopus0` are required.

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install .
export ARYA_URL=wss://penny.z13.org/v1/audio/converse
# Set ARYA_API_KEY through your secret manager, without committing it.
python -m pytest --junitxml=reports/junit.xml
```

On an operator machine with existing SSH access to Penny:

```sh
python3 scripts/local-live.py --junitxml=reports/junit.xml
```

This reads the API key over SSH into process memory, never printing or saving it.
No live test silently skips for missing credentials, codecs, models, or services.
Tests fail when a documented feature cannot be exercised. The local harness
negative controls run without credentials: `python -m pytest tests/test_client.py`.

## Contract and reports

`specs/client.md` is the contract snapshot; `specs/revision` records its upstream
commit. Crow sets `ARYA_SPEC_FILE` to the triggering hermes-converse checkout's
spec. A changed contract fails the check until its assertions and snapshot are
reviewed together. Assertions follow the specification even when Penny disagrees.

JUnit is written to `reports/junit.xml`. Sanitized per-test frame traces and audio
byte counts are written to `reports/traces/`; no API key, start-auth frame, raw
audio, or provider configuration is recorded. Traces contain only test-owned
conversation output. Crow logs include test failures and the triggering commit.

This is a live-deployment regression check. A commit triggers the check but is
**not automatically deployed to Penny**. The result does not claim Penny runs
that commit. Initial inspection found Penny at `7e725ee4ba817adfe62050e396588c0049aaf313`
and the contract at `a66827433415b702b520c8876c2bcec6cba22231`.

## Coverage

| Contract | Executed checks |
| --- | --- |
| §1 authentication | Both auth paths, secret subprotocol not echoed, missing/bad keys, invalid first JSON/binary frames |
| §2 start and reconnect | Required/forbidden names, PCM and Opus rate matrix, invalid codec/rates, ready identities/timestamps, malformed Opus, attachment replacement, reconnect identity |
| §3 controls/commands | Stop, commit/empty commit, current/stale cancellation, command catalog, invalid/unknown commands, title/new, say/empty say |
| §4 lifecycle/transcripts | Real speech and synthetic outbound speech, turn IDs, state, ordered audio, pacing, liveness counters, opt-in transcripts, assistant closing cursor, history and replay, no replay speech, barge-in |
| §5 silence | No wall-clock quiet, quiet from received samples |
| §6–7 flow and IDs | Real automatic endpointing and forced endpointing, repeated turns, turn correlation |
| §8 wake | Correlated one-second decisions, exact phrase separation, invalid requests/signals; streaming without a wake claim |
| §9 outbound audio | Idle `say`, no synthetic user/wake event, standby, subsequent output after drain |
| §10 countdowns | Real model-created countdown, fields/sounds, replay on reconnect, model cancellation/extension, test-owned cleanup |
| §11 model | Catalog opt-in, display-only fields, free availability/selection, invalid IDs/choices, reset, selection during playback |

Frame validation also checks approval requests/resolutions and tones whenever
emitted. The suite does **not yet force** approval expiry/reconnect, provider
failure/stall, deletion of a conversation from Hermes, scheduled outbound work,
countdown snooze/multiple ringing. Ranked wake tie-breaks are checked when
Penny enables selection; disabled selection is checked for grants instead. These
remain coverage gaps, not passing evidence for those requirements. Model/STT
semantic assertions can fail because the live model or transcription failed;
the trace distinguishes that from a protocol failure. No retry converts a failure
to a pass.

## Crow

`.crow.yaml` runs this repository's tests on pushes and manual runs.
`ci/run.sh` is the check entry point. The hermes-converse workflow unpacks a versioned source archive from a masked
Crow secret and verifies its SHA256. `scripts/publish-crow-bundle.py` publishes
that archive from a committed suite revision. This avoids handing a public
repository a broad GitHub credential for a private checkout. Each version has its
own secret name so older commits continue to test the revision they pin. The `arya_penny_api_key` secret is needed on each Crow repository,
limited to `push` and `manual` events. Fork pull requests do not receive it.

Useful operator commands:

```sh
crow --disable-update-check lint .crow.yaml
crow --disable-update-check pipeline create Keryxion/arya-test --branch main
crow --disable-update-check pipeline create Keryxion/hermes-converse --branch main
```
