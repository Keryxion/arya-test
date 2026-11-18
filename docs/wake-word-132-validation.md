# Wake-word contract #132 validation

2026-11-18, target `wss://sakura.z13.org/v1/audio/converse`, model `free`.
Upstream contract: `c28f7997bbce51d149bdf62e4c0624a3f80ad1f8`.
Snapshot SHA256: `7deffebdc701ccf5a69c76d003252f9a7c44435810aae6413f1ddbc9f04f1efb`.
Penny was not deployed or targeted. Credentials came from the existing Sakura SSH
alias into process memory, without printing or saving them.

## Corrected checks

Final focused run: **62 passed in 32.27 seconds**. This includes all six live
wake checks, 17 new harness controls, 38 existing harness controls, and the exact
snapshot comparison. Local report: `reports/wake-final.xml`.

The real-model test selects a phrase different from the advertised current one.
It received `set_wake_word` for `Hey Arya`, authenticated and hash-verified its
models, sent `wake_word_set` with `load_failed` on the same socket, and received
a model reply confirming failure. Reconnecting the same unique test device
confirmed the old `Hey Sakura` phrase remained configured. No successful loading
or physical detector behavior was simulated or claimed; no successful switch
was reported, so no test-owned persisted phrase override needed restoration.

## Initial full run: failed

The initial full run had **188 passed, 6 failed in 407.05 seconds**;
`reports/full-sakura.xml`. This was before correcting the speech trigger:
asking for the already-active `Hey Sakura` let the model decline to call the
tool. That new test also hit the existing audio-pacing guard. Correcting the
trigger and strengthening failure-confirmation/reconnect assertions produced
the focused result above. This does not turn the initial full run green.

| Failed test | Evidence and comparison with unchanged suite main (`39cb79e`) |
|---|---|
| `test_new_command_reconnect` | Close code `1006`, expected `4410`; reproduced on unchanged main. |
| `test_title_command_keeps_socket` | `command` returned `bad_command` instead of a string reply; reproduced on unchanged main. |
| `test_reset_command_alias` | Close code `1006`, expected `4410`; reproduced on unchanged main. |
| `test_say_idle_output_and_drain[pcm16]` | Second reply exceeded audio-pacing guard; reproduced on unchanged main on attempt six of a bounded six-attempt probe (five earlier attempts passed). |
| `test_countdown_extension_preserves_id` | Same audio-pacing guard; two isolated unchanged-main runs passed. This particular case remains intermittent/unresolved; it is not claimed baseline-reproduced. |
| `test_live_set_wake_word_reports_failure_on_same_socket` | Invalid initial same-phrase trigger described above; final corrected and strengthened check passed. |

Baseline command checks: three failed, one passed (including PCM say).
Additional isolated baseline countdown: one passed. Baseline paired PCM say and
countdown: two passed. Bounded baseline PCM probe: five passed, sixth failed.
Reports are `/tmp/arya132-baseline-results.xml`,
`/tmp/arya132-baseline-countdown.xml`, `/tmp/arya132-baseline-playback.xml`, and
`/tmp/arya132-baseline-pacing-{1..6}.xml` on the validation host.

The pacing assertion requires received PCM duration to be no greater than
elapsed time since first audio plus **2.25 seconds** (1.5 seconds lead plus
0.75 seconds scheduling/transit tolerance). In the initial full-run failures:

- PCM say: 131,072 bytes at 24 kHz PCM16 = **2.730667 seconds** on the failing
  second turn; `reports/traces/fe2e985494d4b8cf.json`.
- Countdown extension: 196,608 bytes = **4.096 seconds**;
  `reports/traces/530201ca1e19f074.json`.

The original trace format does not store monotonic first-audio/packet timestamps,
so the exact elapsed value and numeric excess cannot be recovered from these
traces. No such value is inferred or fabricated. `_audio` and `finish` have
identical ASTs to unchanged main; no pacing threshold, scheduling code, prior
assertion, or snapshot comparison was relaxed. The baseline pacing reproduction
establishes the guard can fail independently of this update; it does not diagnose
the deployment's intermittent timing or prove every full-run failure pre-existed.
