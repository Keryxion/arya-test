# Penny live baseline — 2026-11-16

Target: `wss://penny.z13.org/v1/audio/converse`. Every user-turn connection
selected `free` with `set_model` and received its acknowledgement.

The full live run collected 99 cases: **87 passed, 12 failed** in 283.51 seconds.
There were no skipped or expected-failure tests. Five of these cases were local
harness/contract checks; the rest exercised Penny. The subsequent stricter
assistant-closing-cursor assertion adds one local negative-control case.

Penny's deployed plugin was `7e725ee4ba817adfe62050e396588c0049aaf313` when
inspected. The contract snapshot is from
`a66827433415b702b520c8876c2bcec6cba22231`. This was not a deployment test of
the triggering hermes-converse commit.

## Observed failures

- **Nine Opus cases:** accepted Opus sample rates and real Opus flows close with
  `4404` before `ready`. Negative packet tests cannot reach packet validation.
  `ctypes.util.find_library('opus')` on Penny returned `None`.
- **Cancel:** after cancellation, a user transcript arrives without its required
  `message_id`. The validator rejects it; this prevents validating the remaining
  cancellation/recovery assertions in that case.
- **Barge-in:** the counting reply completes, but the streamed interruption
  produces no `interrupted` within 40 seconds and no continuation transcript.
- **Countdown extension:** the initial countdown is created. An unsolicited
  home-channel announcement follows; the extension utterance produces no user
  transcript before the deadline. The test cannot establish whether the
  countdown tool itself would extend it correctly.

Real PCM speech, explicit and automatic endpointing, transcript opt-in,
conversation recall over multiple turns and reconnects, reconnect during a run,
countdown creation/replay/cancellation, idle speech, command handling, wake
validation, and model selection passed checks in this run.

The source bundle extraction and local harness checks also passed in Crow on
hermes-converse pipeline 83. The live CI jobs stop at configuration compilation
until the explicitly requested Penny API-key transfer to Crow is approved.

See README's coverage table and remaining conditional scenarios. These results
are not evidence of complete client-spec conformance. Keep failures visible;
do not mark them skipped merely to make the check green.

A targeted rerun with the stricter closing-cursor validator failed after 22.57
seconds: the unsolicited home-channel announcement sent assistant text and
`turn_done` without the required empty-text transcript carrying `message_id`.
This is additional contract evidence, not the earlier harness correlation bug.
All six local negative-control/contract checks passed after that change.
