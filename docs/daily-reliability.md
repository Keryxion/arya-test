# Arya reliability manager

## 2026-11-24

Intent: useful live reports and actionable failures, without spec snapshot/pin
maintenance or hiding real regressions. Reviewed the beginning and final handoff
of Claude session `47ed16ec-f1e0-4e86-b0af-22dbb07ca799`. Its historical merge
permission is not permission to merge or deploy this run.

Observed state:
- arya-test local and GitHub main: `416d071e5de9`; clean at entry. Only open
  suite PR at entry: #4 (DND), dependent on server #149. Do not duplicate it.
- hermes-converse GitHub main: `2638b77f1af8`. #204 merged as `65fce55`.
  Penny SSH checkout remains `ada7dfb438e5`, clean. Latest GitHub deployment
  Penny ID 8000436638; overall failure is the live check, not proof deployment
  failed. Crow 209 log ran the suite and posted its report successfully.
- Latest Crow history: hermes-converse 210 success, 209 failure; 210 is another
  deployment target, not evidence that Penny's live suite passed. Latest suite
  report is still [186 passed, 7 failed](https://github.com/Keryxion/hermes-converse/pull/204#issuecomment-7100507959),
  [Crow 209](https://crow.tail707a6.ts.net/repos/8/pipeline/209).
- Existing open #219 (`f88ca1e`) handles paced old PCM/stale speaking after
  reconnect; #178 handles barge-in echo gating. Both report mergeable clean.
  Do not duplicate these fixes or describe them as deployed.
- Open spec-only #220 proposes independent socket/session lifetimes and turn
  replay; implementation is explicitly not claimed. Current deployed spec still
  requires 4410 for new/reset. Keep current assertions until contract changes.
- Sibling local hermes-converse checkout is a different revision and has an
  existing modified .gitignore; left untouched. Used deployed GitHub spec instead.

Evidence and classification:
- Wake failures in Crow 209 are at test_wake.py:16 waiting for set_wake_word,
  before verify_models or HTTP download. Current micro wake trace advertises
  `Hey Arya`, models `{}`. Deployed spec section 8 explicitly permits bundled
  phrase without download; server marks that phrase handled. This is a harness
  false failure, not evidence of a model download timeout or infrastructure fault.
- Crow barge-in timed out awaiting interrupted. A fresh targeted run passed.
  Treat as intermittent live behavior, cause unproven; do not call fixed or
  automatically classify as model timing. Existing #178 is relevant.
- Crow new reconnect got 1006 rather than required 4410. Fresh targeted run
  passed. Intermittent close behavior remains unresolved; no xfail/retry masking.
- Crow countdown failures waited for countdown after completed model output;
  PCM semantic failure did not answer input. Model/tool variability is plausible,
  but current run did not retest them. Historical handoff's rerun passes are not
  current proof. Keep distinct from transport/protocol failures.

Actions:
- Paseo inventory found no competing active worker. No profiles configured;
  provider discovery selected codex/gpt-6.1-sol, auto-review, for independent wake
  audit (`b8069b53-072e-44e1-98c8-95dfcc7f3e8b`). Reviewed its Crow, deployed spec,
  server and live evidence before accepting changes.
- Branch `improve/live-report-diagnostics`: show every failed test in grouped
  reports, include suite revision and pytest exit status, include teardown errors,
  prevent incomplete/collection-error runs reporting green. No exit-code masking.
- Correct bundled default wake path to explicit download-coverage skip, with
  README explanation; preserve authentication/hash checks whenever models offered.
- Local regression checks: 68 passed with DYLD_LIBRARY_PATH=/opt/homebrew/lib
  and loopback permission. Initial sandbox run had missing library discovery and
  denied loopback binds; environment issues, resolved without code changes.

Next priorities:
1. Review this run's PR; no merge or deployment authorized/performed.
2. Review #219 and #178 independently, then request deployment authorization if
   desired; rerun reconnect/barge-in against the exact deployed revision.
3. Provision a supported, test-owned nonbundled wake phrase/download scenario so
   skips become real live authentication/hash coverage; do not change global wake
   configuration or claim physical detector loading is tested.
4. Capture repeated failing close-code/barge-in traces and correlate server logs;
   do not weaken 4410 or interruption requirements to make builds green.
5. Improve timeout context and durable CI trace access; currently CI traces stay
   in the container. Report posting pagination (>100 comments) also remains a gap.

Completed live validation (not a full-suite green claim):
- Manager targeted run: 3 passed, 1 failed, 156.36s; new, barge-in and
  disconnect-during-turn passed. Finished-detached replay timed out. Its trace
  (`reports/traces/84171a655e993606.json`) shows same turn resumed thinking after
  reconnect and then assistant text: "litellm rate-limited every one of 5
  attempts". Provider availability blocked completion; this is not proof of
  a replay regression. JUnit: reports/manager-2026-11-24.xml.
- Additional new/reset run: 1 passed, 1 failed, 32.46s. New passed again;
  reset reproduced 1006 instead of 4410. Current actionable protocol failure;
  trace reports/traces/ and JUnit reports/manager-commands-2026-11-24.xml.
- Wake baseline: both formats failed waiting for set_wake_word, 62.93s; both
  ready frames showed bundled Hey Arya and no offered models. Corrected run:
  5 passed, 1 skipped, 1 failed (micro initial-ready timeout, before wake branch),
  42.68s. Narrow follow-up: both download checks explicitly skipped, 2.52s.
  Keep initial-ready timeout as separate unresolved transient, not erased by rerun.
- Trace/JUnit paths are ignored local artifacts; this record retains the important
  evidence across cleanup. No automated retry changes a failed result into a pass.

Updated priority: investigate reset's abnormal close first; record initial-ready
latency separately, and check provider rate limits before replay/model retests.
Avoid load-heavy full-suite runs while free is rate limited. Bundled-default skips
remove two false failures without claiming download coverage or changing build gates.
