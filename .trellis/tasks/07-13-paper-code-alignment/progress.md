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
- **Superseded by AC41 (historical):** this verification used the then-current
  `max(1, outer-3)` Smartian inner limit. AC41 replaced that obsolete
  three-second reserve with the current bounded six-second
  startup/report-normalization allowance while preserving the exact outer
  deadline.
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

## 2026-07-27 — Post-audit reproducibility and release hardening

- Moved Stage 2 category qualification onto normalized scene weights.
  `R_hat` and `n_eff` are invariant to a common KDE-density scale, reliable
  zero-recall primary evidence opens search without certifying a candidate, and
  missing or under-evidenced primary data cannot prove a complement stronger.
- Replaced the seeded 300-target bandwidth approximation with exact
  full-sample leave-one-out Gaussian-grid fitting over all 2,934 emitted
  profiles. Duplicate profile vectors are grouped algebraically without
  changing the objective. The selected bandwidth remains `0.08`; the artifact
  records method `full_leave_one_out_gaussian_grid_v1`, sample size `2934`, and
  a replayable fit digest.
- Implemented action-conditioned per-cell DACE retrieval with BM25+dense RRF,
  explicit dense-unavailable/fallback provenance, and complete typed primary
  and candidate evidence rows in the CEGO payload.
- Packaged the default `toolcards` data in the wheel and made a fresh Docker
  build compile pinned Smartian sources into the image. The native ARM64 outer
  image uses the ARM64 `.NET` runtime, carries the x86-64 runtime libraries
  required by official Linux `solc`, pins an ARM-compatible GPTScan Z3/Falcon
  pair, and contains no macOS host path.
- Kept each fuzz campaign's original outer deadline, reserved six seconds for
  Smartian lifecycle/report handling, and added `EXECUTED_PARTIAL` aggregation
  so valid current-run findings survive sibling failure or timeout.
- Allowed ordinary decimal duration prose while continuing to reject
  statistical field names and rate-like values. Updated effective paper prose
  for conditional shared compilation, dataset-level runtime proxies, and
  user-budget fuzz campaigns.
- A clean isolated sdist-to-wheel build produced an 87-entry wheel containing
  the default Performance KB, profile artifact, and vector index with no stale
  certification modules, bytecode cache, or host-path dependency. A full native
  ARM64 Docker build and `docker build --check .` completed without warnings.
- Live image verification passed for native `.NET 8.0.29`, official Linux
  `solc`, Smartian, Falcon `0.2.28`, Z3 `4.13.0.0`, all 2,934 profiles, and the
  full-sample bandwidth metadata. A real `pragma solidity ^0.4.26` Smartian run
  used a 15-second outer budget, fuzzed for 9 seconds, completed 18,425
  executions, and emitted one valid mishandled-exception finding with no parser
  errors or failures.
- Final verification passed: complete suite `501 passed`; compileall; CLI help;
  Performance-KB JSON validation and unchanged-file diff; `git diff --check`;
  clean sdist/wheel build; fresh Docker build and live analyzer smoke; and
  `latexmk` for the 12-page paper.
- Checkpoint 24 and AC37–AC43 are complete. Per the requested exclusions,
  `toolcards/performance_db.json` and the optional RuleChecker-bypass behavior
  were not changed. No secret, commit, stage, or push was introduced.

## 2026-07-28 — Local-private benchmark runtime snapshot

- Added an ignored `toolcards/.private/` runtime snapshot so the source
  checkout continues to use local-private evaluation slices while tracked
  release knowledge remains public-only.
- Recovered the private Performance extension from a private recovery source
  and merged it with the current public KB. The local snapshot validates and
  leaves the tracked `toolcards/performance_db.json` byte-unchanged.
- Rebuilt the local profile artifact with `solc_compact_ast_v3` over the public
  and private corpora using a full-sample leave-one-out bandwidth fit.
- Added fail-closed runtime selection. The private pair must pass both
  production loaders, exactly extend current public rows/datasets, and have
  identical Performance/profile delta identities. Missing, stale, or
  mismatched halves fail before Stage 1; explicit `kb_root` bypasses the static
  private snapshot.
- Removed private source identities and paths from public profile metadata. The
  public profile samples and fitted statistics remain unchanged.
- A representative Solidity recommendation exposed the additional private
  scene identities, emitted the private-snapshot warning, and reached a checked
  plan. The public-only comparison exposed no private scene.
- Verification passed: AC44/release/pipeline focus `18 passed`; full suite
  `510 passed`; compileall; JSON/profile validation; `git diff --check`;
  Git-ignore, wheel, and Docker exclusions. No linter or type checker is
  configured. No private artifact is tracked, staged, committed, or pushed.
- Checkpoint 25 and AC44 are complete.

## 2026-07-28 — Local-private hand-curated RAG snapshot

- Recovered the hand-curated passages and matching embeddings from a private
  recovery source. The ignored runtime PassageStore and vector index exactly
  retain their public prefixes and append the bound private rows.
- Marked every private-only passage with `linked_evaluation_ids=[]` and no
  performance-observation links. The private passages remain qualitative:
  retrieval and CEGO may cite them, but they cannot acquire `w_D`,
  independently qualify a complement, or bypass Stage 2 statistics, runtime,
  applicability, or RuleChecker.
- Extended static snapshot resolution from a Performance/profile pair to one
  four-artifact boundary. Performance KB, profiles, PassageStore, and vector
  index now activate together only after production-schema, exact public
  prefix, dataset-delta, passage order/count, embedding dimension/provider/
  model, embedding-prefix, and PassageStore-digest validation.
- Normal source-checkout recommendation now defaults to the private
  PassageStore/index when the complete snapshot is active. Explicit individual
  passage/index paths retain their override semantics, while explicit
  `kb_root` continues to bypass the complete static private snapshot.
- The original private source remains ignored recovery provenance rather than
  a runtime activation artifact. The complete local snapshot validates, and
  every private passage is BM25-retrievable without an embedding credential.
- Independent Trellis review found no production defect and added regressions
  for a provenance-only recovery source plus forbidden performance-observation
  links. Verification passed: AC45 focus `35 passed`; complete
  suite `528 passed`; compileall, CLI help, `git diff --check`, public file
  hash/diff checks, and Git/wheel/Docker exclusions. No linter or type checker
  is configured.
- Checkpoint 26 and AC45 are complete. No private artifact was tracked, staged,
  committed, pushed, or added to the public PassageStore/vector index.

## 2026-07-30 — CEGO voting design expansion removed

- The user confirmed that multi-sample CEGO voting was never part of the
  intended design. The prior R17/AC31 majority-vote requirement, its code, and
  its manuscript sentence were unauthorized design expansion and are
  superseded by the single-proposal contract.
- Each `run_cego` invocation now makes one temperature-zero structured request,
  validates one `CegoProposal`, and passes it directly to the unchanged
  assembler. CEGO owns no sample count, ballot, vote threshold, abstention, or
  cross-response citation aggregation.
- Request and schema failures raise `CegoError`. A RuleChecker rejection starts
  one fresh single-request repair round with the rejection reasons; bounded
  exhaustion still returns the checked primary-only fallback.
- `CegoProposalSample` and ballot/sample terminology were removed from the
  schema boundary. The compact prompt still carries the complete Stage 1
  lineage once and legal candidate matrix rows by reference.
- Verification passed: focused review `71 passed`; complete suite `528 passed`;
  compileall and `git diff --check`. The paper file is outside this code change
  and remains untouched; any paper/code reconciliation requires explicit user
  authorization.

## 2026-08-03 — Auditable Stage 2 Top-5 boundary

- Applied one shared five-candidate ceiling only after complement count,
  stronger-than-primary, feasibility, evidence, runtime, and budget gates.
  Legal candidates are ordered by descending `R_hat`, descending `n_eff`, then
  tool ID. Overflow remains visible as typed `NOT_SHORTLISTED` evidence.
- Promoted the ceiling from a builder convention to a schema/Checker invariant. The
  ownership panel now rejects oversized, mislabelled, overlapping, underfilled,
  or incorrectly ranked partitions, and the complete matrix verifies every
  row's ownership status against its panel partition. RuleChecker rebuilds the
  canonical panel and rejects any semantically altered partition.
- Added regressions for seven qualified candidates, an under-evidenced high-rate
  candidate, deterministic tie ordering, CEGO prompt exclusion, proposal
  sanitization, forged-certificate rejection, and forged-schema rejection.
- Verification passed: Stage 1 isolation `38 passed`; focused Stage 2/CEGO/
  Checker/report coverage `119 passed`; complete suite `535 passed` with the
  pre-existing release-wheel regression still failing because its discovered
  system `setuptools 58.0.4` emits `UNKNOWN-0.0.0.whl` instead of a `lakes-*`
  wheel. `compileall`, `git diff --check`, legacy-symbol scans, and protected
  knowledge-file diff checks passed. No knowledge data, paper source, commit,
  stage, or push was changed.

## 2026-08-12 — Core release integration audit

- Rechecked the public runtime contracts end to end: one structured CEGO
  request per round without voting; normalized `w_D` recall evidence and the
  strict stronger-than-primary gate; canonical Top-5 ownership partitions and
  Checker rebuild; partial-execution preservation; exact-tag Securify reuse
  without `--sudo`; and category reports that retain exact raw findings.
- Closed the remaining GPTScan provider gap. Its no-override path now uses
  endpoint-aware credential precedence, so official DeepSeek hosts prefer
  `DEEPSEEK_API_KEY` while custom hosts cannot receive provider-specific keys.
  Vendored official-DeepSeek calls disable thinking, structured callers request
  JSON output, and custom compatible hosts receive neither provider field.
- Added regressions for official-host key precedence, exact GPTScan request
  options, custom-host compatibility, and structured-caller wiring. Updated
  public configuration prose and the DeepSeek audit note to match the runtime.
- Verification passed: release-focused matrix `165 passed`; complete suite
  `573 passed`; compileall; CLI help; and `git diff --check`. Compileall still
  reports the existing invalid-escape `SyntaxWarning`s in vendored GPTScan
  `query_template.py` and `rich_utils.py`; they are outside this integration
  change. No commit, stage, or push was introduced.

## 2026-08-12 — Public release candidate quality gate

- Made the clean wheel self-contained by packaging the exact public ToolCard,
  Performance-KB, profile, passage, and vector-index assets. A fresh install
  can now recommend outside the source checkout without an explicit knowledge
  directory.
- Kept the complete local-private snapshot outside Git and Docker. Public
  profile metadata and tracked prose no longer disclose private source
  identities, and private runtime artifacts must be complete, regular,
  non-symlink files before atomic activation.
- Made the container build reproduce Smartian from pinned source and
  dependencies without a host path or local build output. Native ARM builder,
  runtime usage, short fuzz, and GPTScan dependency/import probes passed.
- Added read-only GitHub Actions checks for Python 3.10 and 3.13, wheel content,
  dependency consistency, the complete test suite, and source compilation.
- Independent Trellis review replaced one private-derived retrieval fixture
  with synthetic evidence and added fail-closed symlink regressions. Final
  verification passed: `577 passed`; clean build/wheel/sdist/install and
  outside-checkout offline recommendation; `compileall`; four CLI help probes;
  `git diff --check`; `docker build --check .`; public-profile validation; and
  candidate privacy scans. All ignored private artifact digests remained
  byte-identical and the production private resolver remained active locally.
- The current candidate tree is publishable. The existing remote branch
  history still contains superseded private metadata labels from an earlier
  public commit; removing those historical blobs requires separately approved
  history rewriting and a force push.

## 2026-08-17 — Canonical fresh-clone Stage 3 output

- Confirmed that the prior `securify2_direct.json` was an ad hoc diagnostic,
  not a product output. Both public entry points now consume one canonical
  output-layout helper for `LAKES_out/<contract>/`.
- Fixed the actual interruption hazard: a new execution invalidates the prior
  four top-level artifacts before starting any analyzer, with the old fused
  report removed first. Final JSON is atomically replaced and the fused report
  is published last.
- The child runner now uses the active Python interpreter. GitHub checkout
  instructions use an editable install, and the Docker bind mount writes
  directly to the checkout's `LAKES_out/` directory.
- Added an isolated tracked-only CLI execution regression plus exception,
  cleanup-failure, path, and interpreter coverage. A real Securify execution
  produced the exact four canonical top-level files, one raw
  `securify2/result.json`, status `SUCCESS`, and nine fused findings.
- Verification passed: complete suite `583 passed`; tracked-only editable
  install and execution from outside the checkout; `compileall`;
  `git diff --check`; protected knowledge-file diff checks; and
  `docker build --check .` with no warnings.
