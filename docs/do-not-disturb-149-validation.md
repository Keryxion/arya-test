# Do Not Disturb contract #149 validation — 2026-11-19

Contract: hermes-converse `71cb7d40ff800bbe609ff0223b0f715f5fc5b763`
([PR #149](https://github.com/Keryxion/hermes-converse/pull/149), built on merged #173).
The checked-in client spec is byte-identical to that commit (SHA256
`211b9701d91572f602d04562185e301ded2a158d2e854ca872a18bcb2a2b5e76`) and
`specs/revision` records it. This suite is based on the current pin `39cb79e`, not
on suite `main`: `main` also carries the wake-word checks for hermes-converse #132,
which is unmerged and absent from #149's spec. No deployment was performed.

## Live environment

Target: `wss://penny.z13.org/v1/audio/converse`, model `free`. Penny's plugin
checkout (`~/.hermes/plugins/hermes-converse`, detached) was at `71cb7d4`, moved at
08:33:24 by Crow pipeline 151's alpha deploy; the gateway restarted at 08:33:26
and was rechecked at the same commit after the final run. Credentials were read
over the existing `penny` SSH alias into process memory and never printed or saved.

## Run 1: pinned suite `39cb79e` (Crow pipeline 151)

**4 failed, 158 passed, 9 skipped** of 171, in 466.87 s. The 9 skips are the
documented optional-Opus `4503 audio_unavailable` refusal; PCM fallback passed.
The 28 failures #189 recorded against `180db89` are down to these four:

| Test | Cause |
|---|---|
| `test_checked_contract_matches_triggering_commit` | Expected: #149 adds section 12 and two frame-table rows. |
| `test_title_command_keeps_socket` | Pre-existing. `{"type":"command","name":"title",...,"error":"bad_command"}`; also fails on Sakura (no #149 code), on Penny `b570add` (#177, no #149 code, pipelines 130/132), and in the #173 and #132 reports. |
| `test_barge_in_captures_continuation` | Pre-existing and intermittent. Turn 1 runs to its closing cursor and `turn_done` and is never `interrupted`; the barge-in speech produces no new turn. Same frames on Sakura, which has no #149 code. Passed on a focused Penny rerun. Do Not Disturb was off throughout. |
| `test_disconnect_does_not_cancel_active_turn` | Not attributable to #149 on the evidence, but not reproduced on a server without #149 (below). |

Disconnect, reconnect connection on Penny (DND off):
`ready`, `do_not_disturb {on:false}`, cursorless assistant `replay` snapshot,
`state thinking`, `thinking`, `model_changed`, `state speaking`, `speaking`, then
binary audio with no live assistant text. Section 4 says audio after a reconnect
starts with the first text prepared after it; this audio was for text already in
the snapshot. #149's only change on this path is the `do_not_disturb` frame sent
before the catch-up, which is correctly placed. Sakura finished the turn before
reattach on four attempts (cursor replay, nothing live), so it never reached
this branch, and Penny without #149 is not available for comparison. The test
also failed on Penny `b570add` under an older suite, on a different assertion.

## Run 2: this suite (final)

Local harness and contract checks: **49 passed** with no credentials, including
negative controls for a non-Boolean `on`, a `turn_id` on the frame, a frame
other than `do_not_disturb` after `ready`, a replay before it, a close before
it, and a missing frame. Spec comparison against #149's file passed.
Strict Crow lint: `.crow.yaml` and hermes-converse `.crow/arya-test.yaml` valid.

Live negative control: Sakura (no #149 code) fails `test_auth_and_ready` with
`no do_not_disturb frame within 10 s after ready`.

Full live run on Penny `71cb7d4` with `ARYA_SPEC_FILE` set to #149's spec:
**4 failed, 176 passed, 9 skipped** of 189, in 374.44 s. All eight new live Do
Not Disturb cases and the spec comparison passed. Failures:
`test_new_command_reconnect`, `test_title_command_keeps_socket`,
`test_barge_in_captures_continuation`, `test_disconnect_does_not_cancel_active_turn`.
An earlier full run on the same server (before the timeout message change) had
the same result except `test_reset_command_alias` instead of barge-in
(175 passed of 188).

`new`/`reset` close with `1006` after a valid `command` reply instead of `4410`.
This is pre-existing (#173 and #132 reports) and intermittent: in a bounded A/B
on Penny, three runs of both tests failed 2 of 6 with the pinned suite and 2 of
6 with this suite. The do_not_disturb wait precedes the command and does not
touch close handling.

No failure in either run is attributable to #149.

## What the live checks show

- `do_not_disturb` is the first frame after `ready` on every harness connection
  that reached `ready` (PCM, Opus, browser auth, history replay, running-turn
  resume), with a Boolean `on` and no `turn_id`; a new device starts off. The few
  raw-socket rejection/Opus-setup probes do not check it.
- The device's toggle is not echoed within 1 s, and persists across a reconnect
  and to a different `assistant_name` on the same device; turning off also persists.
- `on` values `"true"`, `1`, `"on"`, `[true]`, `{}`, and a missing `on` leave it
  off; `"false"`, `0`, `null`, `""`, `[]`, and a missing `on` leave it on. No error.
- While on (turning it on ends the grace), `say` and the person's own voice turn
  are answered with audible reply audio, and the setting is unchanged afterwards.
- The real `free` model turns it on and off by voice: a `do_not_disturb` frame
  arrives on the socket with the new value and no `turn_id`, the reply is spoken,
  and the next `ready` reports the new value.
- After each run, no device in Penny's `devices.db` had Do Not Disturb on, in the
  `settings` JSON or the legacy column. Every test turns its device off.

## Not checked

The harness has no trigger for server-started output (section 9), so it does not
check that reminders, other messages, their approvals, or `play_tone` are held
after the grace; that nothing is held within it; that turning it on ends it; that
a held reply is never spoken later; or that a still-ringing countdown turn is
silent. It does not restart Penny, so persistence across a server restart is
unchecked. Device-side display, the toggle's availability window, and showing
the last value while disconnected are client UI behavior. That `on` is not
echoed is checked over 1 s, not indefinitely.
