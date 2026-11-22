# arya-test

Independent, headless client-contract checks for the **live Penny server**, using
**model `free`**. This private repository owns the tests; hermes-converse's Crow
workflow unpacks a pinned source revision and reports the result after each successful Penny deployment.

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
Missing credentials, models, services, or undocumented codec errors fail the check.
A valid `4503 audio_unavailable` explicitly declines optional Opus; the setup
check passes only for that exact error/close pair or negotiated Opus. Opus-only
packet/playback cases then report explicit skips, while PCM fallback is checked.
A `4404` Opus setup error remains a failure. The local harness
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

The hermes-converse check runs on `deployment` events targeting `penny` and
waits for the `alpha` deployment workflow to succeed. A failed deployment does
not run the suite. The cloned contract comes from the deployment commit.
Standalone manual runs test whatever revision Penny is serving.

## Coverage

| Contract | Executed checks |
| --- | --- |
| §1 authentication | Both auth paths, secret subprotocol not echoed, missing/bad keys, invalid first JSON/binary frames |
| §2 start and reconnect | Required/forbidden names, PCM and Opus rate matrix, invalid codec/rates, ready identities/timestamps, malformed Opus, 4503 refusal/PCM fallback, name/rate validation, attachment replacement, reconnect identity |
| §3 controls/commands | Exact-true stop/commit, empty commit, cancellation during capture and current/stale cancellation, command catalog, invalid/unknown commands, title/new, say/empty say |
| §4 lifecycle/transcripts | Real speech and synthetic outbound speech, turn IDs, optional listen/standby/mute actions, ordered interruption/audio, text before audio, pacing, carried reconnect counters/text snapshot, opt-in transcripts, closing cursor, history/replay identity, barge-in |
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

`.crow.yaml` allows standalone manual runs of this repository's tests.
`ci/run.sh` is the check entry point. The hermes-converse workflow unpacks a versioned source archive from a masked
Crow secret and verifies its SHA256. `scripts/publish-crow-bundle.py` publishes
that archive from a committed suite revision. This avoids handing a public
repository a broad GitHub credential for a private checkout. Each version has its
own secret name so older commits continue to test the revision they pin. The `arya_penny_api_key` secret is needed on each Crow repository,
limited to `deployment` on hermes-converse and `manual` on arya-test.
Source-bundle secrets on hermes-converse allow only `deployment`.

Useful operator commands:

```sh
crow --disable-update-check lint .crow.yaml
crow --disable-update-check pipeline create Keryxion/arya-test --branch main
```

## Contract update #173

The snapshot and assertions target hermes-converse `76e1f3c` (merged #173).
Normal completions may omit `next_action`; errors/interruption must omit it.
The headless client preserves its activation across absent actions, honors
explicit listen/standby, and stops upstream audio immediately for mute.
User transcripts require stored IDs and thinking before them. `say` has no
transcripts; persisted server replies require closing cursors. Reconnect text
snapshots are display-only, without cursors; resumed state precedes thinking,
and counters carry over. Text must precede reply audio when transcripts are on.

Penny's revision is recorded with live results. A server that has not deployed
this contract is still checked against it, with deployment lag stated separately
from harness failures. See `docs/contract-173-validation.md` for measured results.

## Wake-word contract update #132

The snapshot targets hermes-converse
`c28f7997bbce51d149bdf62e4c0624a3f80ad1f8` ([server PR #132](https://github.com/Keryxion/hermes-converse/pull/132)).
The harness validates `ready.wake_word` when present and every `set_wake_word`
frame, including phrase, engine names, model URLs and full SHA256 descriptors.
The configured live target must advertise downloadable models. The suite rejects
missing/incorrect HTTP credentials, verifies the advertised manifest/ONNX bytes,
and fetches the manifest-relative TFLite file with the same key. The contract
hash covers the manifest; it does not advertise a separate TFLite hash.

Live result checks send all four documented error values and confirm the socket
remains usable. A speech test asks the real `free` model to change the test-owned
device's phrase to a different one, validates the resulting `set_wake_word`, and reports `load_failed`
on that socket. It fails if the model does not invoke the tool. There is no
undocumented tool-invocation or configuration endpoint in this harness.

These checks verify server wire behavior and downloads. The headless harness has
no wake detector and never reports successful model loading. Physical clients
must separately verify continued detection during downloads, atomic model/phrase
switches, rollback, the 30-second response deadline, cache reuse, and persistence
across restart. Local HTTP corruption/authentication tests are negative controls
for the harness, not evidence for physical client behavior. The exact spec
snapshot comparison and all earlier contract tests remain in place.

Measured results and remaining failures: [wake-word validation](docs/wake-word-132-validation.md).

## Default wake phrase update #196

The snapshot targets hermes-converse
`9db7a097e78145cb9421e4f86a4d316578ef145a` ([server PR #196](https://github.com/Keryxion/hermes-converse/pull/196)).
Devices ship a bundled `Hey Arya` model, which is the phrase before any switch;
the spec's switching examples use `Hey Sakura`. The live switch test therefore
asks for `Hey Sakura` unless that is already configured. No wire format changed.
