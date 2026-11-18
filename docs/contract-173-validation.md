# Contract #173 validation — 2026-11-18

Contract: hermes-converse `76e1f3cd4b72ffcb3b88947bf3c6f983b4c509b8`.
The checked-in client spec is byte-identical to that commit and `specs/revision`
records `76e1f3c`. The pinned source archive is published separately for the
hermes-converse deployment workflow; this update does not deploy Penny.

## Local controls

39 local harness/contract checks passed. These prove absent actions are accepted,
listen/standby/mute are recognized, absent actions preserve activation at drain,
failed/interrupted turns cannot carry an action, and audio/turn frames cannot
cross an interruption boundary. They also check persisted user IDs, transcript
ordering, no `say` transcripts, closing assistant cursors, reconnect text
snapshots/state/counters, negotiated PCM rates, first text before reply audio,
and the exact optional-Opus 4503 refusal versus invalid errors or missing PCM.

## Live environment

Target: `wss://penny.z13.org/v1/audio/converse`, selecting `free` on every
connection that reaches `ready`. The deployed plugin was
`180db893708507c82dccf5f48a6deb1a43d18c60`, titled
`Merge branch 'main' into spec-do-not-disturb`. It predates contract #173.
Failures on this deployment do not establish whether merged #173 is defective.
Missing credentials/dependencies are never silently skipped. The only explicit
codec skip is a documented `4503 audio_unavailable` for optional Opus; 4404
still fails and a separate case requires PCM fallback.

## Remaining scope

The suite validates server frames and exercises the acceptance cases through
live requests; it is not an exhaustive simulator of every hardware UI or audio
capture state. Approval expiry/reconnect, scheduled outbound producers, all
countdown ringing/snooze races, and exact resume-audio identity remain gaps.
The running-turn reconnect test validates snapshots/state/carried counters when
the turn is still live, or silent replay if it completed before reattachment.
A deterministic local control covers the live-resume branch even when a fast
model finishes before reconnect. Countdown/model semantic outcomes remain
separate from malformed wire frames when interpreting live failures.

## Measured results

The final full live run collected 170 cases: **142 passed, 28 failed**, no skips
or teardown errors, in 237.04 seconds. The spec byte comparison passed.
The final local rerun passed all **39** checks; this includes one additional
turn-specific replay-comparison regression control added after full collection.
A focused live rerun of the refined history comparison failed on the same
live/replay turn-ID mismatch, before text comparison.

The failures against the older deployment are:

| Cases | Observation |
| --- | --- |
| 10 Opus cases | Valid Opus setup returns `4404 conversation_unavailable`, not the documented `4503 audio_unavailable`. Packet/playback cases cannot reach their next assertions. |
| 4 PCM rate cases | Numeric strings, floats or booleans are coerced instead of using the documented defaults. |
| 2 quiet cases | String and boolean intervals produce quiet frames instead of disabling them. |
| 3 stop cases | Truthy values other than JSON `true` close the socket. |
| 2 commit cases | Truthy values other than JSON `true` submit captured audio while endpointing is disabled. |
| 1 say case | Transient `say` emits assistant transcripts. |
| 1 targeted cancel case | The user transcript lacks its required message ID. |
| 1 capture cancel case | Cancellation before request submission emits turn/transcript frames rather than remaining silent. |
| 1 history case | The same assistant message has different live and replay turn IDs. |
| 1 running reconnect case | Live output resumes before the required state and thinking frames. |
| 2 existing command cases | `title` returns `bad_command`; `reset` closes abnormally with 1006 rather than 4410. These require server investigation; they are not attributed to a harness failure or proved fixed by #173. |

These are results for `180db89`, not a failure report against deployed `76e1f3c`.
No assertion was relaxed to fit Penny. An earlier development run found a
whitespace expectation bug in the normalized-name test; it was corrected and
its targeted live rerun passed. That test also passed in the final full run.
The final suite accepts omitted actions and passes the contract comparison;
it no longer produces the stale mandatory-`next_action` failures.
