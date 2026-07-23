# Progress Log

## 2026-07-13 — Implementation baseline

- Branch: `github-release`
- Pre-existing worktree entries:
  - `M toolcards/performance_db.json`
  - `?? .agents/`
  - `?? .codex/`
  - `?? .trellis/`
  - `?? AGENTS.md`
- Baseline binary diff SHA-256 for `toolcards/performance_db.json`:
  `6be708deec7995ead026868a844363b9458a8835e3351a8aaf84d9a8143058a1`
- Baseline diff size for `toolcards/performance_db.json`: 438 insertions, 281 deletions.
- Constraint: implementation must preserve that diff exactly.

## 2026-07-13 — Implementation complete

- Replaced Stage 1 certification with direct paper-ranked `t*` selection and
  support threshold `tau=0.2`.
- Moved category counts to Stage 2 and fixed complement eligibility at
  `R_hat > 0` plus `n_eff >= 15`; primary ownership is immutable.
- Replaced replacement/gap outcomes with additive owner sets and a checked
  primary-only repair fallback.
- Added max-runtime accounting, explicit `NO_EXECUTABLE_PLAN`, per-tool run
  statuses, and provenance/conflict-preserving additive fusion.
- Added the typed top-level pipeline statuses and updated CLI/JSON/README.
- Added executable scheduling rules to
  `.trellis/spec/backend/lakes-scheduling-contract.md`.
- Verification: `48 passed` with warnings treated as errors; compileall,
  `git diff --check`, CLI help/smoke, and all 34 package-module imports passed.
- No repository linter or type-checker is configured/installed; no passing
  claim is made for either.
- Final performance-DB diff SHA-256 remains
  `6be708deec7995ead026868a844363b9458a8835e3351a8aaf84d9a8143058a1`
  with 438 insertions and 281 deletions, exactly matching the baseline.

## 2026-07-14 — Fresh execution only

- Removed every historical and pre-existing report reuse path from the
  production runner, including ancestor `smartbugsout` discovery, environment,
  API, CLI, copy, and pre-execution fast-path support.
- Selected tool result directories are cleared before batch execution; each
  analyzer invocation recreates its own output directory and only reads a
  report after a successful current invocation.
- Applied the same selected-tool cleanup to the native SmartBugs fallback.
- Added five focused regressions covering ancestor reports, stale invocation
  output, removed directory-target contracts, native fallback cleanup, and
  fresh report normalization/fusion.
- Independent Trellis check result: no findings.
- Verification: focused `5 passed`; complete suite `53 passed`; compileall,
  runner/CLI help, removed-hook search, and `git diff --check` passed.
- Performance-DB diff SHA-256 remains
  `6be708deec7995ead026868a844363b9458a8835e3351a8aaf84d9a8143058a1`.

## 2026-07-14 — Performance-KB runtime ownership

This entry records the intermediate AC13 implementation. Its linked/global-max
fallback and coverage result were superseded by the reliability work below.

- Removed ToolCard metrics from scheduling runtime resolution. Tool IDs and
  display names now serve only as unambiguous aliases for Performance-KB rows.
- Added positive finite runtime parsing for `time_sec`,
  `execution_time_avg`, and `execution_time_avg_average_s`; cumulative seconds
  and timeout counts are excluded.
- Added an interim same-source deduplication and scene-weighted P90 estimator;
  its weak/global fallback behavior was removed by the final work below.
- Added strict runtime/provenance invariants and DACE source/unit metadata.
- Recorded the current estimator honestly as a dataset-level nearest-bucket
  proxy; the KB does not yet contain true per-solc/LOC/complexity runtime cells.
- The then-current packaged baseline was 14 tools with a numeric estimate and 6
  unknown; the final support gate below deliberately makes weak estimates
  unknown again.
- Independent Trellis recheck: no findings after closing alias-collision,
  typed-invariant, finite-gate, and cross-layer-test issues.
- Verification: focused `61 passed`; complete suite `80 passed`; compileall,
  CLI/runner help, real CLI smoke, and `git diff --check` passed.
- Performance-DB diff SHA-256 remains
  `6be708deec7995ead026868a844363b9458a8835e3351a8aaf84d9a8143058a1`.

## 2026-07-14 — Runtime reliability, primary-controlled supplementation, and fresh execution boundary

- Removed linked/global historical runtime fallback. Only compiler/LOC-
  compatible rows retaining at least `0.2` original scene support enter the
  weighted P90; weak or incompatible runtime remains unknown.
- Added explicit seconds/unit basis, replayable candidate provenance, and five
  independently sourced paper observations. SMARTIAN's campaign cap remains
  unschedulable and MANDO-HGT remains unknown.
- Made primary category evidence the sole supplementation gate. Missing or
  `n_eff < 15` evidence opens `SEARCH_REQUIRED / under_evidenced`; with
  `n_eff >= 15`, non-positive `R_hat` or a credible peer gap opens
  `SEARCH_REQUIRED / confirmed_weak`; otherwise the category is
  `PRIMARY_SUFFICIENT` and no complement slate exists.
- Kept `t^star` immutable. Failed complement search produces a checked
  primary-only plan rather than removing the primary.
- Unified scheduling around `max(per-file runtime) * Solidity file count`, one
  worker per selected tool by default, and one outer hard deadline for normal
  and native execution. Fresh measured per-tool runtime is output data only.
- Added fresh-only staging and structural report validation. Selected stale
  output is removed or quarantined; double cleanup failure returns `74` and
  prevents execution, harvesting, and fusion.
- Isolated GPTScan credentials to its private wrapper boundary. Generic
  adapters, plans, OS argv, persisted reports, and logs receive no API key.
- Independent Trellis audit closed every reported defect and returned
  `no code findings`.
- Verification: complete suite `168 passed`; warnings-as-errors suite
  `168 passed`; compileall, CLI/runner help, and `git diff --check` passed.
- Performance-DB diff is 562 insertions and 281 deletions. The 124 additional
  lines are limited to two runtime-criteria fields and five independent runtime
  observations. SHA-256:
  `6b61c63e15824e24e48ae7c85c26110b324c595ce3f4c15baec13d0a2fbcfb02`.

## 2026-07-17 — Canonical Gower profile follow-up

- Added one canonical implementation for compiler bucket, effective LOC, and
  the five AST-derived Gower dimensions. Runtime target analysis now projects
  that result into `ContractFeatures`; `scene_pool` consumes the explicit
  `gower_solc_bucket` instead of reconstructing it from the exact execution
  compiler version.
- Added parity regressions for OR/range pragmas, comments, quoted fake pragmas,
  all five dimensions, schema defaults, and the retained AST-failure fallback.
- Verification: focused `37 passed`; complete suite `251 passed`; compileall
  and `git diff --check` passed. No lint or type-check is configured.
- Independent Trellis check found no core-code defect, but AC27 remains open at
  the release boundary: the local builder is ignored/untracked, and the
  packaged `contract_profiles.json` still declares `source_scanner_v1` while
  runtime targets now use the AST extractor. Cross-engine distances must not
  be shipped silently; publish a reproducible builder and regenerate or reject
  the legacy artifact before marking AC27 complete.

## 2026-07-17 — Canonical AST benchmark-profile rebuild complete

- Replaced the one-shot profiling compiler choice with
  `solc_compact_ast_v3`: constrained sources try intersecting canonical buckets
  oldest-first, no-pragma sources try newest-first, and the compiler that
  actually emits the complete AST owns the persisted Gower bucket. Profiling
  copies may rewrite pragmas; original constraints and execution selection are
  unchanged.
- Unified single-file runtime profiling with the offline builder's safe import
  closure and exact Blockscan-wrapper normalization. Target AST failure now
  retains source diagnostics but cannot create a synthetic zero-complexity
  scene.
- Added the installable `lakes-profile-builder`, tracked relative-path manifest,
  atomic output, duplicate-corpus rejection, bounded skip ledger, compiler
  provenance, and strict engine/count/path/range/digest/bandwidth validation.
- Rebuilt seven unique scene corpora: `3133` attempted, `2934` emitted, and
  `199` explicitly skipped. Dataset emitted counts are `139`, `343`, `22`,
  `212`, `107`, `106`, and `2005`. Compatible fallback recovered `74` samples:
  `42` broad-constraint samples under a later bucket and `32` no-pragma samples
  under an older bucket.
- Recomputed ranges from the emitted profiles: `loc [2,2953]`,
  `avg_cyc [0,13]`, `max_cyc [0,78]`, `sum_cyc [0,651]`,
  `max_nest [0,20]`, and `coupling [0,27]`. The seeded fit selected
  `h=0.08`; an independent full `2934`-sample leave-one-out grid evaluation
  also selected `0.08`.
- A second full build with the same timestamp was byte-identical. Artifact
  SHA-256 is
  `e145f5e923df525c5d1f37e663ae8cbe00b960482d11fe083da58da270e8593a`;
  profile digest is
  `929a8688608014933480f68a04cae84f2073d5dbbce9828fe81f3200d4805d58`.
- Refreshed the migration audit. Representative primaries are
  `Fibonacci: Mythril -> Smartian`, `BNB: Mythril -> Mythril`, and
  `empirical: Vandal -> Vandal`; changed weights are retained rather than
  normalized back to the legacy result.
- Independent Trellis check found no remaining AC27-AC29 code or artifact
  blocker. Verification passed: focused `79 passed`, complete `293 passed`,
  compileall, strict load of all `2934` profiles, JSON validation, CLI/runner/
  builder help, byte-level replay, full-LOO reconciliation, and
  `git diff --check`. No standalone linter or type checker is configured.
- `toolcards/performance_db.json` remains untouched by this rebuild: file SHA
  `c28acc107dfd04b5a86bcecb55ba44f3fca2955e790c034bc32ee51c8004d74d`;
  diff SHA
  `6b61c63e15824e24e48ae7c85c26110b324c595ce3f4c15baec13d0a2fbcfb02`.

## 2026-07-19 — CEGO majority, shared compilation, and dynamic KB complete

- CEGO now obtains exactly three sequential structured samples at temperature
  zero per proposal round. A complement requires a fixed two-vote category
  majority; failures abstain without lowering the threshold, primary-only
  omissions vote explicitly, and only winner-vote citations enter the one
  aggregate sent through RuleChecker. Every repair starts a fresh three-call
  round.
- Stage 3 now builds a digest-verified standard-JSON bundle only when Smartian
  or Vandal consumes Solidity artifacts. Smartian receives ABI plus creation
  bytecode and Vandal receives runtime bytecode from that same one-time
  compilation. Source-only tools remain source-mode, bytecode/runtime inputs
  compile zero times, and runner/native execution report consistent actual
  consumption. Required-bundle failure stops before every analyzer worker.
- Added the production `lakes kb` / `lakes-kb-update` PDF ingestion path:
  MinerU conversion, strict LLM dataset/capability extraction, normalization,
  block/table provenance checks, safe rejects, stable observation links,
  exact current-lineage projection, immutable generation validation, vector
  binding, atomic pointer publication, rollback/recovery, and current-generation
  dry runs. Unprofiled datasets remain explicitly Stage 1-ineligible.
- Independent Trellis checking found and fixed provenance inconsistency,
  overly broad excerpt matching, table-cell bypass, stale-baseline dry runs,
  post-merge accepted-count drift, embedding-key argv exposure, missing
  manifest-count validation, installed-wheel ToolCard assumptions, and two
  documentation drifts.
- Verification: AC31-AC33 targeted `88 passed`; complete suite `380 passed`;
  compileall for `toolrank`, `tests`, and `docker/runners`; CLI, runner,
  KB-update, and nested KB help; and `git diff --check` all passed. No repository
  linter or type checker is configured.
- Packaged knowledge remained unchanged during this work:
  `performance_db.json` SHA
  `c28acc107dfd04b5a86bcecb55ba44f3fca2955e790c034bc32ee51c8004d74d`,
  diff SHA
  `6b61c63e15824e24e48ae7c85c26110b324c595ce3f4c15baec13d0a2fbcfb02`,
  and `passage_store.json` SHA
  `9c1564ea7f351396166c2256fa6ce438f78fe13c2016775c36f01efb78cb7103`.
- Real MinerU models, external LLM/embedding endpoints, installed solc binaries,
  Smartian/Vandal, and Docker analyzers remain environment-gated smoke tests.

## 2026-07-20 — Real Docker and analyzer smoke

- Used `/tmp/lakes-e2e-smoke-kv49M1/Smoke.sol`, a minimal exact-Solidity-0.5.16
  contract, so the installed host compiler and Smartian/Vandal/Slither
  ToolCard ranges overlap without relying on modern opcodes.
- Real shared compilation completed in about four seconds with compiler
  `0.5.16`. One validated bundle carried ABI plus creation bytecode to Smartian
  and runtime bytecode to Vandal under bundle ID
  `4d8becb71ff227a22abcd16be6e668a39b55af772762eb4eac5c2248740965d2`.
- Vandal executed through SmartBugs/Docker and succeeded in about 3.8 seconds
  with a fresh valid empty report. Slither executed through SmartBugs/Docker
  and succeeded in about 7.8 seconds; compilation was truthfully
  `NOT_APPLICABLE`, consumption was `SOURCE_ONLY`, and its two informational
  ignored findings correctly did not enter fusion.
- Smartian itself consumed the shared ABI/bytecode and completed a direct
  five-second fuzz run with 13,525 executions, zero deployment failures, and a
  valid empty report. The normal runner exposed a real timeout race instead:
  its outer deadline equals Smartian's internal fuzz limit, and the second
  process-group `SIGKILL` raised macOS `PermissionError`. The run was therefore
  recorded `FAIL` instead of typed `TIMEOUT`. The same failed invocation also
  incorrectly recorded shared-artifact `consumed=true`.
- The current code mounted read-only into the LAKES image completed the public
  Stage 1/2 path: `PRIMARY_SELECTED=slither`, `PLAN_READY`, `run_primary`, and
  Checker `ACCEPT`. Full Docker-in-Docker Stage 3 is not runnable on this Apple
  Silicon host because an amd64 analyzer nested inside the emulated amd64 LAKES
  container fails OCI startup; the current host runner plus Docker analyzer
  containers is functional.
- Host-only public recommendation failed closed at `NO_SCENE_EVIDENCE` because
  the active Python environment lacks `py-solc-x`/its canonical profiling
  compiler. MinerU and LLM/embedding configuration are also absent. Dynamic-KB
  dry-run returned a clear MinerU error with exit code 1 and created no pointer
  or partial generation.
- Focused Stage 3 regression tests passed (`31 passed`). The complete suite was
  `379 passed, 1 failed`; the failure is a brittle CLI-help assertion whose
  expected MinerU command is wrapped by Typer/Rich terminal width. No production
  or packaged-KB files were modified by the smoke run, and no processes or
  containers were left running.

## 2026-07-20 — Real-smoke defects fixed and reverified

- Made process-group deadline cleanup resilient to the macOS leader-exit race:
  TERM/KILL `PermissionError` cannot escape, direct-child fallback is bounded,
  and reap/pipe-drain operations each have a `0.2s` limit. A hard timeout now
  returns typed `124/TIMEOUT` without a lingering worker or Smartian process.
- Smartian retains the scheduler-owned outer deadline but runs its integer
  fuzzer with `max(1, outer-3)` seconds. The three-second reserve rounds up the
  measured 2.2-second shutdown/report-normalization cost; small budgets remain
  explicit best-effort typed-timeout cases rather than receiving hidden grace.
- Shared-artifact `consumed` is now based on an exact routed Solidity invocation
  that returned zero and produced a valid current-run report. Failure-only,
  timeout-only, cleanup-failure, and `NOT_RUN` histories remain false. Mixed
  histories retain true only after a real shared-source success, including when
  a later cleanup returns `74`; top-level and per-tool values remain identical.
- Normalized whitespace in the MinerU CLI-help assertion so Rich terminal width
  cannot create a false failure while the exact command and secret-option
  exclusions remain tested.
- Real combined rerun succeeded: Smartian and Vandal were both `SUCCESS`, both
  consumed the same bundle, and both produced valid empty reports. Smartian's
  17-second inner fuzz run executed 59,564 tests. The two-second combined hard
  boundary returned exit `124`; both tools were `TIMEOUT/124/consumed=false`,
  with no process or container left behind.
- Independent Trellis verification fixed one additional manual-execution `74`
  manifest-preservation gap. Final gates passed: focused `41`, broader `153`,
  complete `396`, and warnings-as-errors `396`; compileall, CLI/runner/KB help,
  and `git diff --check` passed. All protected KB/profile hashes remained
  unchanged. No commit, stage, or push was performed.

## 2026-07-20 — Candidate-specific complement strength gate

- Added one typed `complement_strength_against_primary` result shared by the
  primary-category diagnostic, ownership/CEGO candidate surface, and
  RuleChecker. A positive count-qualified primary now requires the candidate's
  Newcombe Recall-gap lower bound to be strictly above zero; missing,
  non-positive, or `n_eff < 15` primary evidence remains an explicitly
  unreliable baseline rather than a fabricated comparison.
- Preserved feasibility, runtime, applicable-evidence, RAG hard-block, budget,
  and `n_eff >= 15` gates. Strength belongs to each candidate, so an infeasible
  strong peer cannot qualify a weaker feasible tool.
- Replayed the real arithmetic target. Slither remained the Stage 1 primary;
  Smartcheck was rejected as weaker, Osiris/Oyente/Mythril remained unavailable
  under execution constraints, and Conkas remained under-evidenced. The final
  certificate was `run_primary`, selected only Slither, and RuleChecker returned
  `ACCEPT` without an LLM fallback warning.
- Implementation verification passed: focused `72`, complete `406`, compileall,
  and `git diff --check`. Independent Trellis review found no production defect;
  it corrected the real-regression fixture to Conkas `n_eff=1.944` and added an
  explicit accepted Slither-only selected-plan assertion. Its focused `53` and
  complete `406` tests, compileall, and diff check also passed. No commit,
  stage, or push was performed.

## 2026-07-20 — Auditable final report

- Added a provenance-labelled post-Checker combination explanation and retained
  the existing normalized fusion view. Valid LLM prose is one qualitative
  paragraph; unavailable, malformed, or semantically unsafe prose becomes an
  explicit deterministic fallback without affecting the checked plan.
- Added category -> checked owner -> tool status/findings output. Requested
  owner categories remain present with empty finding arrays, while additional
  accepted primary categories follow in stable order.
- Preserved each accepted generic/SmartBugs/SARIF finding as a deep-copied JSON
  object before normalization. An explicit parser-projection marker prevents an
  analyzer's own `raw` field from being mistaken for internal structure.
- Independent review fixed projection-marker collisions, explanation schema and
  status-consistency gaps, then tightened explanation semantics without
  rejecting ordinary `total runtime` language. Final verification passed:
  focused `17`, complete `430`, compileall, and `git diff --check`.
- A fresh API + Docker run on `testContract.sol` selected only Slither,
  RuleChecker returned `ACCEPT`, execution succeeded, and the explanation was
  generated by `deepseek-ai/DeepSeek-V3.2`. `arithmetic` persisted with zero
  findings; observed `access_control` and `unchecked_low_level_calls` contained
  three findings. A full multiset comparison confirmed that all three final
  category findings equal their accepted original Slither JSON objects.
- A subsequent official-DeepSeek rerun verified model availability and forced
  `deepseek-v4-flash` through both the environment and CLI. One safe run rejected
  non-conforming prose and labelled its fallback; the next full run accepted a
  qualitative V4 Flash paragraph with `source=LLM` and
  `model=deepseek-v4-flash`. Stage 1/2/3, the three accepted raw findings, empty
  arithmetic category, and the no-secret output scan all passed unchanged.
- No commit, stage, or push was performed.

## 2026-07-20 — Solidity 0.4.x diagnostic smoke

- A 12-line `pragma solidity 0.4.26` bank contract compiled successfully, emitted
  the canonical `0.4.x` AST/Gower profile, and entered Stage 1 normally.
- Default ranking selected Smartian (`S_t=0.842105`, support `0.252726`), but its
  only runtime evidence is an incompatible, unschedulable campaign cap. Every
  recall/precision preference combination selected Smartian or VulHunter with
  unknown runtime, so the public pipeline correctly failed closed at
  `NO_EXECUTABLE_PLAN` and produced no Stage 3 report.
- A diagnostic forced-Slither run through SmartBugs 2.1.1 and Docker succeeded
  and found both `reentrancy-eth` and `unchecked-lowlevel`, proving the general
  0.4.26 source/adapter/report path works independently of primary selection.
- A forced Smartian run through host Python exercised a non-production mode,
  not the packaged Docker path: `/work/...` is intentionally container-local.
  Supplying a host-valid DLL path progressed to shared compilation but the
  20-second run timed out safely with `consumed=false`. Direct inspection of
  `lakes:latest` confirmed that the image contains the Smartian runner,
  `Smartian.dll`, and `.NET 8`; production Docker execution requires no
  Smartian path from the macOS host.
- Native-output comparison confirmed the intended report boundary. Slither's
  native object remains auditable in `result.tar`/SARIF; SmartBugs converts it,
  LAKES adds `raw_name`/canonical `category`, and that complete enriched
  current-run `result.json` element is the exact object preserved through
  fusion and the final category view.
- `~/.solcx/solc-v0.4.25` is a broken local symlink; compiler discovery ignores
  it, while the installed 0.4.26 binary works. No production code or packaged
  knowledge was changed. Independent read-only review passed 191 tests,
  compileall, and `git diff --check`.

## 2026-07-21 — Cross-paper runtime evidence and derived summaries

- Added 10 independently identified paper-level runtime observations with
  exact source URLs/locators, reported and normalized units/bases, denominator
  metadata, formulas, and explicit limitations. Rejected, copied, component,
  campaign-cap, plot-only, and incompatible-basis evidence remains in the
  research audits rather than the packaged arithmetic constituents.
- Added six replayable descriptive summaries: GPTScan `21.845 s/KLoC` from
  `n=2`; HoneyBadger `78.57 s/contract` from `n=4`; SAILFISH
  `23.6766667 s/contract` from `n=3`; VulHunter `4.4 s/contract` as an
  `n=1` identity summary; and truthful `null, n=0` summaries for SMARTIAN and
  MANDO-HGT.
- Schema validation now enforces unique observation/summary identities,
  independent paper identities, exact homogeneous constituent membership,
  canonical formula terms, declared precision, replayed arithmetic, and
  truthful identity/null shapes. Only `per_contract` and `per_kloc` values can
  become summary constituents.
- Runtime assessments, DACE cards, and the CEGO payload expose the summaries as
  explicitly non-schedulable descriptive evidence. The scheduler still reads
  only raw Performance-KB runtime fields, so the summaries cannot create
  `expected_runtime_minutes`, alter weighted-P90 provenance, satisfy the
  compiler/LOC/support gate, affect budgets, or set execution timeouts.
- Independent review allowed an empty exclusions list for an all-admissible
  future corpus, added alias/raw-field/timeout non-interference regressions,
  synchronized the backend scheduling spec, and restored the source spelling
  `João F. Ferreira` in the packaged provenance.
- Final verification passed: focused AC35 `18` tests; adjacent runtime/DACE/
  CEGO `94` tests; complete suite `448 passed`; `compileall`, strict
  Performance-KB load/arithmetic replay, JSON validation, and
  `git diff --check`. The historical Checkpoint 22 command names
  `tests/test_dace_rag.py` and `tests/test_cego.py` were stale; the active
  `test_dace_rag_v2.py`, `test_cego_assembly.py`, and `test_cego_majority.py`
  suites were used.
- The ignored handoff credential was injected only as an ephemeral environment
  variable for two live DeepSeek checks. `deepseek-v4-flash` passed both the
  structured-JSON API probe and the real post-Checker combination-explanation
  path, including the LAKES semantic guard. The credential was not printed,
  persisted, staged, or copied into code. No commit, stage, or push was
  performed.

## 2026-07-21 — Budget-driven fuzz campaign implementation and verification

- Added a typed, user-controlled fuzz campaign allocation selected only by
  `ToolCard.d8_mode=fuzz`. Historical completion runtime and provenance remain
  absent for fuzz tools, while raw and literature assessments stay descriptive.
- Added one Stage 2/3 planning-runtime projection and routed primary,
  complement, RuleChecker, certificate, composition, DACE, and CEGO consumers
  through it. Stage 1 still reads only historical completion runtime.
- Preserved full per-tool parallel allocation, sequential input multiplication,
  explicit-short-timeout checks for static tools, and the existing runner-owned
  outer timeout path. ConFuzzius/sFuzz command construction and existing
  Smartian reserve/tiny-timeout behavior are covered by regressions.
- Independent review bound the policy to the typed fuzz family, rejected
  historical runtime on fuzz rows and campaigns on non-fuzz rows, checked both
  campaign seconds and timeout source against the schedule, and prevented zero,
  unresolved, or inconsistent default budgets from creating an allocation.
- DACE now emits separate Performance-KB history and user-budget campaign cards
  with truthful sources. CEGO names the planning source and semantics. Exact
  fractional outer deadlines now reach the normal runner and native fallback
  without `ceil` extending a tiny campaign; integer inner analyzer limits remain
  bounded by that unchanged outer deadline.
- The complete `expected_runtime_minutes` audit found only six consumer classes:
  construction in `evidence_packet`, validation in `schemas_v2`, the intentional
  Stage 1 tie-break in `scene_scoring`, the non-fuzz branch of the shared
  `plan_runtime` projection, and history-only presentation in DACE and CEGO.
  Every Stage 2/3 executability caller uses the shared projection.
- Final verification passed: AC36 `18 passed`; AC36 plus adjacent runtime/
  Stage 2/DACE/CEGO/runner/Smartian/native suites `89 passed`; complete suite
  `466 passed`; compileall for `toolrank`, `tests`, and `docker/runners`; CLI and
  runner help; Performance-KB JSON validation; and `git diff --check`. No linter
  or type checker is configured. A pre-existing Rich-help regression was made
  deterministic by removing table-border characters before its wrapped-text
  assertion.
- AC36 and Checkpoint 23 are complete. No Performance-KB observation,
  literature arithmetic, paper source, secret, commit, stage, or push was
  changed.
