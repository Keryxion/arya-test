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

## 2026-11-25

Reviewed original session beginning/end again: original intent is useful reports
without pin-secret/build maintenance. Historical `do it` applied to #204 only;
no merge or deployment authorized this run.

Verified current state (14:00–14:10 UTC):
- Entry checkout clean, branch `improve/live-report-diagnostics`, `cf70a84`.
  GitHub suite main now `e0d540fa9043`; yesterday's diagnostics/bundled-wake
  changes merged via #13, with report date added in #15. No duplication.
- Server #204 remains merged as `65fce55e72ec`. Main at the independent audit was `5145dec4741b` (merged tone PR #223);
  `50f6c0bfef22` was #179's base, not current main.
- Latest Penny deployment 8056791920 targets PR #179 head `77627de12828`.
  GitHub deployment status is failure and links Crow 230; this alone does not
  mean deployment failed. Latest report explicitly ran suite `e0d540fa9043`:
  **112 passed, 103 failed**, all failures `missing current_model`.
  [Report](https://github.com/Keryxion/hermes-converse/pull/179#issuecomment-7161897318),
  [Crow 230](https://crow.tail707a6.ts.net/repos/8/pipeline/230).
- Exact target revision's specs/client.md section 11 uses `set_model` /
  `model_changed`; current main section 11 requires `ready.current_model` and
  model/reasoning commands. The live suite's current_model requirement matches
  main. Classify latest mass failure as deployment/suite contract mismatch,
  not 103 independent product failures or model timing. No weakening assertions.
- PR #179 is CONFLICTING. PR #219 is also CONFLICTING despite successful pytest;
  #178 remains DRAFT (mergeable). Existing #224 owns failed/cancelled/silent turn
  endings. Suite #16 (tone contract update for merged server #223) is mergeable;
  #4 still owns DND coverage. No merge/deploy or duplicate implementation.

Concrete progress:
- No other active Paseo agent found. No configured profiles; discovered Codex
  provider and delegated a read-only deployment/failure audit to
  `6c26528e-e38d-4b71-beb5-eafe8b666f28`; no shared-file edits delegated.
- Opened [suite PR #17](https://github.com/Keryxion/arya-test/pull/17), commit
  `05fc344`, branch `fix/report-comment-pagination` from current origin/main.
  Searches all comment pages so an existing report beyond comment 100 is updated
  rather than duplicated; also paginates associated PRs. No build gate changes.
- New mocked GitHub regression proves page-two report is PATCHed with fresh
  results, no POST. Local harness checks: **88 passed**. Initial sandbox run
  had 3 loopback-bind permission failures; identical run with loopback permitted
  passes. This was local infrastructure, not a test/product defect.

Next priorities:
1. Align PR #179 with current main before an authorized deployment, then run
   targeted current_model/setup checks against the exact serving revision.
   Keep the 103 blocked tests distinct from individually exercised failures.
2. Review #17 and existing suite #16. No full-suite green claim from this run.
3. Resolve/review existing reconnect #219 and draft barge-in #178 independently.
   Once a compatible revision serves Penny, recapture new/reset close codes and
   barge-in traces. Yesterday's reset 1006 remains unresolved; latest setup
   failures do not prove either regression or recovery.
4. Wake download coverage remains a documented bundled-model skip. Provision a
   test-owned supported phrase scenario before claiming download validation.
   Provider rate limiting/model variability remain separate historical concerns;
   do not infer them from today's missing-current_model failures.

Independent audit reviewed before closing:
- Paseo worker confirmed by SSH that Penny checkout is clean at `77627de12828`.
  System `hermes-gateway.service` and `hermes-home.service` are active/running.
  Crow 230 alpha log confirms deployment from `831e789` to `77627de` succeeded;
  the overall failure is the live application's mismatch with current suite.
- Worker independently agrees: restore a main-based revision only with deployment
  authorization, and rebase #179; preserve current assertions. #224 now also
  conflicts with main. No extra live load or server modifications performed.
- This run coordinated through the [Paseo skill](/Users/dturner/.agents/skills/paseo/SKILL.md).

Additional completed audit evidence:
- [Crow 226](https://crow.tail707a6.ts.net/repos/8/pipeline/226), server
  `831e789c263f`, suite `e0d540fa9043`: **210 passed, 3 failed, 2 skipped**.
  Reset returned 1006 instead of 4410; barge-in waited 40 seconds for
  `interrupted`; the model-driven wake switch waited 120 seconds for
  `set_wake_word`. This last failure is distinct from the bundled download
  coverage skips; it remains unclassified without model/tool trace evidence.
- [Crow 223](https://crow.tail707a6.ts.net/repos/8/pipeline/223), server
  `5acc77a9f6b9`, suite `1bdcc7e88d70`: **211 passed, 2 failed, 2 skipped**.
  Barge-in and the model-driven wake switch failed. These runs supply newer
  evidence than yesterday's local reproductions; Crow 230 masks their status.
- Audit compared #179 with main: diverged, main has 15 unique commits and
  deployed branch two. This confirms outdated alpha deployment rather than an
  intentional removal of current_model from main's contract.

## 2026-11-26

Reviewed original Claude session beginning/end and verified current state rather
than treating its merge permission or handoff as current authorization.

Observed (14:00 UTC run):
- Entry clean on `fix/report-comment-pagination`, `eed8b18`; existing suite #17
  remains open/CLEAN, no checks. Suite main is now `fbca170c36fa` (#18 controls/admin
  and #16 tone changes merged); server main `0742087f112a`. New work branches
  from current origin/main; previous PR work untouched.
- Latest Penny deployment 8086454204 targets draft #161 `8caf88899e47`.
  [Crow 260](https://crow.tail707a6.ts.net/repos/8/pipeline/260) alpha log explicitly
  says Penny runs that revision; system gateway/home services are active.
  Overall deployment failure comes from live suite, not failed deployment.
- Latest [report on #161](https://github.com/Keryxion/hermes-converse/pull/161#issuecomment-7193638153)
  is **220 passed, 9 failed, 2 skipped**, suite `fbca170c36fa`, finished 13:38 UTC.
  Crow 261/262 success are other targets, not Penny live success.
- Prior [Crow 258](https://crow.tail707a6.ts.net/repos/8/pipeline/258), server
  `f9a32b127d84`, suite `e0d540fa9043`: 212 passed, 1 failed (barge-in), 2 skipped.
  Yesterday's mass current_model mismatch no longer dominates current results.

Classification and evidence:
- Three Crow260 failures are ClientConnectorDNSError, temporary name resolution
  failure for penny.z13.org. Infrastructure; no application connection occurred.
  Do not retry-mask them or infer a server protocol defect.
- Four speech failures await the *user* transcript (countdown initial speech and
  both detached-turn tests), before exercising their advertised core assertions.
  Cause unresolved: do not label these countdown-tool/model timing without traces.
- Barge-in again waits 40s for interrupted. Existing #178/#234 own related echo
  gating work; no duplicate fix or claim of recovery.
- History replay got `Pineapple.` vs live `pineapple`; deployed section 4 describes
  replay as the whole reply said aloud. Preserve exact assertion while investigating
  the server's speech/replay text paths; #218 is related formatting work.
- Wake download checks remain explicit bundled-default coverage skips; the model
  switch test passes this latest run. Skips are not download validation.
- New/reset passed Crow260 but targeted local run reproduced **1006 vs 4410 on
  both**. Deployed spec section 2 still requires 4410. Historical intermittent
  protocol failure remains actionable; passing CI is insufficient to close it.

Actions and verification:
- No competing Paseo work at entry. No configured profiles; discovered Codex and
  delegated independent read-only spec/PR audit to
  `9378a75b-4943-451c-bb54-2ee732522f92` via Paseo skill. No server writes delegated.
- Branch `improve/timeout-context`: timeout messages now include allowlisted
  role/state/replay filters so reports distinguish user vs assistant transcript
  waits. Never include text, IDs, arbitrary filter values, or frame contents.
  No retries, deadline changes, or build-gate changes.
- Local regression suite: **97 passed**. Initial restricted run: 94 passed,
  3 HTTP loopback bind denials; identical run with loopback access passed.
- Targeted live run: **1 passed, 2 failed**, 39.35s: history replay passed this
  time; both new/reset reproduced abnormal close. JUnit
  `reports/manager-2026-11-26.xml`, traces under reports/traces (ignored artifacts).
  This is not a full-suite green result and does not erase Crow260 failures.

Next priorities:
1. Investigate new/reset close handshake using exact Penny revision and correlated
   server logs; preserve 4410. Do not conflate it with audio-fencing #219.
2. Resolve barge-in through existing #178/#234 ownership, with captured microphone
   and server decision evidence; review before any authorized deployment.
3. Investigate runner DNS failures and pre-user-transcript speech stalls separately.
   Retain CI traces durably through an approved storage mechanism; logs currently
   lack enough evidence to assign the latter to STT/provider/server.
4. Review timeout diagnostic PR and existing pagination #17; neither merge nor
   deployment authorized/performed. Retest replay mismatch with #218 context.

Independent audit reviewed:
- Worker verified actual Penny checkout path
  `/home/hermes/.hermes/plugins/hermes-converse` at `8caf88899e47`, matching Crow.
- Main requires and attempts 4410; no reviewed PR owns a dedicated abnormal-close
  fix. #219 concerns paced audio fencing, not new/reset close handshakes.
- #178 (`b2c51329`) is draft and mergeable, owning fuller echo rejection;
  #234 (`f9a32b12`) is clean and provides only the 1.5-second warm-up mitigation.
- #218 (`f5777acb`) conflicts and owns related display-text normalization work.
  It is not a proven fix for the observed capitalization/punctuation mismatch.
  Spec supports consistent reply content but does not explicitly demand bytewise
  assistant identity; preserve failure pending deterministic regression and spec
  interpretation, rather than prematurely declaring product or harness defect.
- Opened [suite PR #19](https://github.com/Keryxion/arya-test/pull/19).
  Coordination used the [Paseo skill](/Users/dturner/.agents/skills/paseo/SKILL.md).

## 2026-11-27

Reviewed original Claude session beginning/end. Its original intent remains useful
reports without pin/secret maintenance; historical #204 merge approval does not
authorize merges or deployment today. Entry clean on `improve/timeout-context`
`f708489`; existing work preserved. Suite main remains `fbca170c36fa`, server main
`0742087f112a`. Suite #17 pagination and #19 timeout context remain open/MERGEABLE,
no checks. #4 owns DND; server #178/#234 own echo/barge-in work. No duplicates.

Current evidence:
- Latest **completed** report at inspection is [Crow 264](https://crow.tail707a6.ts.net/repos/8/pipeline/264),
  server `d45d72db126f`, suite `fbca170c36fa`: **225 passed, 4 failed, 2 skipped**,
  finished Nov 26 19:06 UTC. [Updated PR report](https://github.com/Keryxion/hermes-converse/pull/161#issuecomment-7193638153)
  posted successfully. Failures: new and reset 1006 vs 4410, barge-in waiting 40s
  for interrupted, model-driven wake switch waiting 120s for set_wake_word.
- Latest Penny deployment 8111499206 / [Crow 267](https://crow.tail707a6.ts.net/repos/8/pipeline/267)
  already running on entry, targets `ced8d9b6162d`. Alpha log explicitly confirms
  Penny moved from d45d72d to ced8d9b; worker confirmed clean SSH checkout.
  Partial log shows all protocol checks pass; speech suite still running at last
  inspection. This is not a full result or proof intermittent close issue fixed.
  Did not add live load, start pipelines, merge, or deploy.
- Prior DNS/pre-user-transcript stalls and replay mismatch did not recur in 264;
  their cause remains unresolved. Current four failures are not DNS evidence.
  Wake switch timing remains unclassified without tool/trace evidence; distinct
  from two bundled-model download coverage skips. Do not call it a download timeout.

Actions/validation:
- No competing Paseo agents or configured profiles. Discovered providers/models,
  delegated read-only handshake audit to `ba65db72-9f55-4a93-85a5-28027a971e10`
  using [Paseo skill](/Users/dturner/.agents/skills/paseo/SKILL.md).
- Inspected worker results and independently read deployed route.py: command tasks
  enter wake_tasks at 757–759; new/reset awaits ws.close(4410) at 834–835; cleanup
  cancels wake_tasks around 1015–1024. Worker inspected runtime aiohttp 3.14.3:
  cancellation during close records abnormal closure and closes transport.
  **Plausible product race, not proven root cause**. Journal access restricted;
  no correlated log proof. No dedicated open PR owns it; #219 is audio fencing,
  #220 is spec-only lifetime proposal, #235 is lazy session creation.
- Opened [suite #20](https://github.com/Keryxion/arya-test/pull/20) from current
  main, branch `improve/report-coverage-gaps`, code commit `aef45ed`: show each
  skipped test/reason under Coverage not exercised in PR report. Existing report
  only showed count, obscuring download coverage gaps. No retries, timeout or
  exit-code changes. **96 local harness/report/wake-validator tests passed**,
  including skip visibility without changing successful status; diff check clean.

Next priorities/blockers:
1. Read completed Crow267 report before new live load; retain exact server/suite
   revisions. One pass cannot close an intermittent failure.
2. Reproduce close cleanup race deterministically in server tests: pause handshake
   while pump exits, verify new/reset deliver 4410; then give server-initiated
   close explicit ownership through completion before cancelling commands.
   Server implementation remains follow-up; preserve live contract assertions.
3. Review #20, #19, #17; no merge/deployment authorization received.
4. Barge-in: use existing #178/#234, capture decision/audio evidence. Wake switch:
   obtain tool/turn evidence before assigning model variability or server fault.
   Durable CI traces still unavailable; journal access is restricted.
5. Bundled skips remain coverage gaps; provision supported test-owned nonbundled
   scenario before claiming authenticated download validation. No physical detector
   loading claim. Avoid model-heavy reruns during active deployment suites.
