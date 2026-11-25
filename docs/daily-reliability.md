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
- Server #204 remains merged as `65fce55e72ec`. Current main is `50f6c0bfef22`.
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
