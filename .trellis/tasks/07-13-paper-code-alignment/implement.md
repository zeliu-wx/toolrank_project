# Implementation Plan: Paper-aligned `screc_v2`

## Success Definition

The task is complete only when the implementation satisfies AC1–AC36 in
`prd.md`, all new regression tests pass, the complete tracked test suite passes,
and legacy Stage 1 certification semantics are absent from the default
pipeline. Preserve every existing Performance-DB metric/count edit; only the
approved additive runtime unit/basis metadata and independently sourced runtime
observations may change its prior diff.

Completion is recorded by the acceptance-criteria table and progress log. The
unchecked boxes in historical Checkpoints 0–7 were not backfilled when those
phases completed; they are not outstanding work.

## Working Rules

- Make changes in the order below because each checkpoint establishes the typed contract required by the next layer.
- Add or update a failing regression test before changing the corresponding behavior.
- Treat the checkpoints as one ordered cross-layer migration, not independently releasable commits. Focused tests must pass before advancing, and the complete runtime must pass at the final cutover.
- Do not add a `screc_v1` converter, dual-version consumer, or compatibility facade to make an intermediate checkpoint look releasable.
- Touch only files needed for AC1–AC36. Do not reformat or retune unrelated code or data.
- Do not commit, reset, or discard any pre-existing worktree change.
- Use historical tests from `c875f03^` only as reference material. Do not restore certification-era expectations.

## Checkpoint 0 — Protect the worktree and establish the test surface

### Changes

- [ ] Record the initial branch, `git status --short`, and `git diff -- toolcards/performance_db.json` before editing.
- [ ] Remove the repository-level `tests/` ignore rule from `.gitignore`; retain ignores for caches and generated output.
- [ ] Create a small tracked test package with reusable in-memory profile, performance-KB, action-matrix, and finding fixtures.
- [ ] Confirm tests never write to the repository's real `toolcards/` files and never call an LLM, network service, compiler download, Docker daemon, or external analyzer.

### Verification gate

```bash
git status --short
git check-ignore -v tests/test_stage1_selection.py || true
python -m pytest --collect-only -q
```

Expected: new test sources are not ignored and collection is offline and deterministic.

### Rollback point

Only `.gitignore` and new test fixtures exist at this point. Revert those task-owned lines/files if collection cannot be made deterministic; do not touch user-owned files.

## Checkpoint 1 — Replace Stage 1 certification with direct primary selection

### Tests first

- [ ] Add unit tests for `phi(1, 1) == 1`, average ranks for metric ties, and missing Recall/Precision exclusion from the relevant benchmark comparison.
- [ ] Add scoring tests that assert `S_t`, every `s_t,D`, normalized `w_D`, and `support_mass` exactly.
- [ ] Add boundary tests for support mass below, equal to, and above `tau=0.2`.
- [ ] Add selection tests for score, developer-preferred raw metric, known/lower runtime, and lexical final tie-break order.
- [ ] Add tests for `NO_SCENE_EVIDENCE`, `NO_FEASIBLE_TOOL`, and `NO_PRIMARY_WITH_SUFFICIENT_SUPPORT`.
- [ ] Add a metamorphic test that changes only category `detected/total` counts and asserts identical scene neighbors, scores, support mass, and `t^star`.

### Contract and implementation

- [ ] Reshape `toolrank/schemas_v2.py` around `Stage1Status`, `BenchmarkToolScore`, `NominalToolScore`, `ScorePanel`, `PrimarySelection`, and `Stage1EvidencePacket(schema_version="screc_v2")` from `design.md`.
- [ ] Make `toolrank/scene_scoring.py` consume overall Recall/Precision only; remove category-count, confidence-interval, `effective_total`, and `local_strong` inputs from nominal scoring.
- [ ] Implement comparable-metric participation, average ranks, `phi`, support mass, `S_t`, and the complete deterministic tie order in one Stage 1 selection module.
- [ ] Preserve normalized relevance weights for every scene benchmark and retain raw kernel density separately for later Stage 2 use.
- [ ] Remove `filter_scene_pool_to_count_bearing()` from the Stage 1 engine path in `toolrank/engine.py`.
- [ ] Replace `certify_primary()` usage with direct selection and explicit early Stage 1 results.
- [ ] Delete `toolrank/certification.py` only after repository search proves it has no remaining consumer; remove task-created orphan imports at the same time.
- [ ] Keep `toolrank/recall_ci.py` helpers only if Stage 2 diagnostics still use them. Do not delete unrelated statistical utilities merely because certification is removed.

### Verification gate

```bash
python -m pytest -q tests/test_stage1_scoring.py tests/test_stage1_selection.py tests/test_stage1_count_independence.py
python -m compileall -q toolrank
rg -n "filter_scene_pool_to_count_bearing|certify_primary|local_strong|certified_primary" toolrank
```

Expected: Stage 1 tests pass; the Stage 1 engine has no count filter or certification call. Any surviving statistical term is demonstrably Stage 2-only.

### Rollback point

The checkpoint boundary is the Stage 1 packet returned by the engine. If it fails, revert only the new Stage 1 models/scoring/engine wiring and their tests.

## Checkpoint 2 — Build Stage 2 category evidence on the immutable primary

### Tests first

- [ ] Add exact category-statistic tests for `R_hat` and `n_eff` using raw kernel density, distinct from normalized `w_D`.
- [ ] Add complement-eligibility tests for `n_eff` below, equal to, and above `15`.
- [ ] Add tests proving low or missing primary category evidence sets `under_evidenced` but never removes or changes `t^star`.
- [ ] Add tests for hard owner-ineligible evidence, no positive support, infeasible tools, missing runtime, and over-budget complements.
- [ ] Add tests proving no required categories produces a primary-only plan after runtime validation.
- [ ] Add primary-runtime tests: unknown or over budget returns `NO_EXECUTABLE_PLAN`, retains the analytical primary, and does not invoke CEGO or execution.

### Contract and implementation

- [ ] Introduce `Stage2EvidenceContext` and build it only after `Stage1Status.PRIMARY_SELECTED`.
- [ ] Refactor `toolrank/assignment_evidence.py`, `toolrank/evidence_packet.py`, `toolrank/category_candidates.py`, `toolrank/ownership_evidence.py`, and category-coverage helpers so category counts are owned exclusively by Stage 2.
- [ ] Name normalized relevance and raw density fields explicitly at model boundaries; use only raw density in `R_hat`/`n_eff` and only normalized relevance in displayed/cited evidence weight.
- [ ] Preserve retained CI and peer-gap values as diagnostics only. Remove any code path where they gate primary ownership or reorder the Stage 1 primary.
- [ ] Implement one complement-eligibility predicate containing feasibility, `R_hat > 0`, `n_eff >= 15`, evidence, scope, known runtime, and parallel-budget checks.
- [ ] Initialize every developer-required category owner list with `t^star`; append at most one accepted complement.

### Verification gate

```bash
python -m pytest -q tests/test_stage2_evidence.py tests/test_stage2_eligibility.py tests/test_stage2_runtime.py
python -m compileall -q toolrank
rg -n "detected|total|n_eff|R_hat" toolrank/scene_scoring.py toolrank/engine.py
```

Expected: count terms are absent from nominal Stage 1 scoring; any engine occurrence is confined to constructing the post-selection Stage 2 context.

### Rollback point

The checkpoint boundary is `Stage2EvidenceContext` plus its eligibility result. Revert only this context and its direct evidence consumers if ownership tests fail.

## Checkpoint 3 — Align DACE-RAG, CEGO, and RuleChecker with additive owners

### Tests first

- [ ] Add an action-contract test proving the decision certificate references an action ID that exists in the generated matrix.
- [ ] Add deterministic assembly tests for primary-only and primary-plus-complement owner lists.
- [ ] Add RuleChecker tests that reject a changed primary, ownerless category, unqualified complement, illegal action, and runtime violation.
- [ ] Add repair-loop tests showing invalid CEGO output is repaired when possible and exhausted retries fall back to a RuleChecker-valid primary-only plan.
- [ ] Add contract tests proving `RUN_ROBUST_SINGLE`, `STOP_WITH_GAPS`, certification, and singleton Stage 1 candidate fields are not accepted or emitted by `screc_v2`.

### Contract and implementation

- [ ] Replace replacement-oriented category assignments with `CategoryAssignment.owner_tools`, `complement_tool`, and `PRIMARY_ONLY | COMPLEMENT_ADDED` status in `toolrank/schemas_v2.py`.
- [ ] Centralize legal action-ID creation and lookup. Make `toolrank/dace_rag.py`, `toolrank/cego.py`, and `toolrank/checker.py` share that helper.
- [ ] Limit the default action types to `RUN_PRIMARY` and `PLAN_COMPOSITION`.
- [ ] Change CEGO output and prompt language from owner replacement to complement proposal; retain evidence citations and caveats.
- [ ] Refactor deterministic certificate assembly so every required category starts with `t^star` and invalid proposals leave it unchanged.
- [ ] Make RuleChecker validate the immutable primary, additive owners, complement eligibility, action identity, scope, and max-runtime rule from typed packet fields.
- [ ] Replace synthetic `STOP_WITH_GAPS` repair exhaustion with a deterministic primary-only certificate that is checked before use.
- [ ] Ensure `NO_EXECUTABLE_PLAN` is a typed Stage 2 terminal result and never an action-matrix row.

### Verification gate

```bash
python -m pytest -q tests/test_action_contract.py tests/test_cego_assembly.py tests/test_rule_checker.py tests/test_repair_fallback.py tests/test_screc_v2_contract.py
python -m compileall -q toolrank
rg -n "RUN_ROBUST_SINGLE|STOP_WITH_GAPS|CertificationVerdict|certified_primary|candidate_set" toolrank
```

Expected: no legacy term remains in executable code or the `screc_v2` schema; the fallback certificate passes the real RuleChecker.

### Rollback point

The checkpoint boundary is a verified decision certificate. If prompt and deterministic assembly changes diverge, revert this checkpoint together; do not keep a new prompt with an old checker contract.

## Checkpoint 4 — Execute and fuse additive category owner sets

### Tests first

- [ ] Add composition tests for ordered tool union and `category_owners: dict[str, list[str]]`.
- [ ] Add execution-adapter tests proving the primary runs normally and complement category filters do not suppress primary results.
- [ ] Add runtime tests proving parallel estimates use `max`, not sum.
- [ ] Add fusion tests for same category/same non-empty location merge, complete source provenance, equal values, conflicting severity, conflicting explanation, and distinct locationless findings.
- [ ] Add tests proving findings from tools outside a category's verified owner set are excluded and categories without an explicit owner list default to primary-only.

### Contract and implementation

- [ ] Change `CompositionPlan` in `toolrank/schemas.py` from singular `category_assignments` to additive `category_owners`.
- [ ] Update `toolrank/engine.py`, `toolrank/execution.py`, and `toolrank/runner.py` to consume the verified owner lists and execute the ordered unique tool set.
- [ ] Update every runtime estimator in `toolrank/dace_rag.py`, `toolrank/cego.py`, `toolrank/checker.py`, and execution preparation to use maximum selected runtime.
- [ ] Introduce `FusedFinding` and update `FusedReport` in `toolrank/schemas.py` with source tools, variants, raw findings, and inconsistent-field markers.
- [ ] Rewrite `toolrank/fusion.py` as additive, provenance-preserving fusion; never remove primary findings merely because a complement exists.
- [ ] Keep parser and runner normalization unchanged except for the minimum adapter changes required by the new plan/result types.

### Verification gate

```bash
python -m pytest -q tests/test_composition.py tests/test_execution.py tests/test_fusion.py tests/test_parallel_runtime.py
python -m compileall -q toolrank
rg -n "category_assignments|sum\(.*runtime|runtime.*sum" toolrank
```

Expected: no executable singular owner map remains, and all parallel budget checks are max-based.

### Rollback point

The checkpoint boundary is `CompositionPlan` → execution → `FusedReport`. Revert all three together if the new additive contract cannot traverse the full path.

## Checkpoint 5 — Finish top-level result, CLI, and release documentation

### Tests first

- [ ] Add `PipelineResult` tests for `PRIMARY_NOT_SELECTED`, `NO_EXECUTABLE_PLAN`, `PLAN_READY`, `EXECUTED`, and `EXECUTION_FAILED` with correct optional later-stage fields.
- [ ] Add CLI summary and JSON snapshot tests for an early Stage 1 terminal, an unexecutable primary, a primary-only plan, and an additive composition.
- [ ] Add a representative offline CLI smoke test with fixture inputs and mocked external execution.

### Contract and implementation

- [ ] Give `PipelineResult` one typed overall status and optional Stage 2/3 fields; remove synthetic placeholder matrices, certificates, checker verdicts, and reports from early terminals.
- [ ] Update `toolrank/cli.py` to print overall status, Stage 1 status, primary, selected action, checker status, and selected tools only when present.
- [ ] Update JSON serialization to emit `screc_v2` names and nullable later-stage objects without a `screc_v1` compatibility facade.
- [ ] Add a concise `screc_v2` migration/release note to `README.md` covering direct Stage 1 selection, Stage 2-only `n_eff >= 15`, additive owner/fusion semantics, removed legacy fields/actions, and new terminal statuses.
- [ ] Remove imports, helpers, and comments made orphaned by this task. Leave unrelated pre-existing dead code untouched and report it separately if noticed.

### Verification gate

```bash
python -m pytest -q tests/test_pipeline_status.py tests/test_cli.py tests/test_cli_smoke.py
python -m toolrank.cli --help
python -m compileall -q toolrank
```

Expected: CLI and JSON expose only the documented v2 contract and handle absent later stages without fabricated objects.

### Rollback point

CLI/result changes form one boundary. Revert them together if any supported invocation cannot render a valid typed result.

## Checkpoint 6 — Full regression and alignment audit

### Automated verification

```bash
python -m pytest -q
python -m compileall -q toolrank tests
python -m toolrank.cli --help
git diff --check
```

- [ ] Run all repository-configured lint, type-check, or build commands discovered during implementation. Do not invent a passing claim for a tool the repository does not configure.
- [ ] Run one offline representative pipeline fixture through Stage 1, Stage 2, RuleChecker, plan construction, and additive fusion.

### Contract audit

```bash
rg -n "screc_v1|CertificationVerdict|certification|certified_primary|RUN_ROBUST_SINGLE|STOP_WITH_GAPS|local_strong" toolrank tests README.md
rg -n "category_assignments|owner_tool" toolrank tests
rg -n "detected|total|n_eff|R_hat" toolrank/scene_scoring.py
```

- [ ] Classify every remaining search match. Only historical release prose or clearly Stage 2 statistical evidence may remain; executable legacy behavior must not.
- [ ] Trace one fixture across Stage 1 packet → Stage 2 context → action matrix → certificate → RuleChecker → composition → fusion and assert the same `t^star`, action ID, owner lists, weights, and provenance at every boundary.
- [ ] Compare the final implementation against every PRD acceptance criterion and record evidence in the task progress log.

### Worktree preservation audit

```bash
git status --short
git diff -- toolcards/performance_db.json
git diff --stat
```

- [x] Compare the final Performance-DB diff with the Checkpoint 0 snapshot;
  preserve it plus only the AC14–AC15 approved additive rows/metadata.
- [x] Review every changed line for direct traceability to AC1–AC19.
- [x] Do not stage, commit, or push without a separate user instruction.

## Checkpoint 8 — Performance-KB runtime ownership (AC13)

- [x] Add failing tests for KB-only runtime ownership, field precedence,
  aliases, duplicate rows, weighted P90, unit conversion, unknown preservation,
  and Performance-KB provenance.
- [x] Resolve runtime after ScenePool construction from
  `PerformanceKnowledgeBase`; remove ToolCard metrics from that path.
- [x] Populate one minute-valued runtime and typed source/method provenance in
  each `ToolCostEntry`; update DACE-RAG runtime cards to cite the selected
  Performance-KB source.
- [x] Record the packaged pre-hardening coverage baseline; Checkpoint 9 then
  replaces weak/global fallback estimates with fail-closed unknowns.

```bash
python -m pytest -q tests/test_runtime_evidence.py tests/test_pipeline_status.py tests/test_stage1_selection.py tests/test_stage2_runtime.py
python -m pytest -q
python -m compileall -q toolrank tests
git diff --check
git diff -- toolcards/performance_db.json | shasum -a 256
```

## Checkpoint 9 — Runtime evidence reliability and replayability (AC14–AC15)

- [x] Add `criteria.runtime_unit = "seconds"` and
  `criteria.runtime_basis_default = "per_contract"` without changing any
  existing Performance-DB metric or category-count value.
- [x] Add tests first for compiler mismatch, LOC match metadata, support mass
  just below/equal/above `0.2`, weak single-row evidence, and removal of the
  executable global-max fallback.
- [x] Replace source-ID-only provenance with replayable typed candidate rows,
  original weights, target buckets, quantile, support mass, and threshold.
- [x] Preserve available success/timeout/failure/sample counts and surface them
  in DACE limitations/risk without inventing absent timeout caps or hardware.
- [x] Add typed `per_contract | per_kloc | campaign_cap` basis tests: convert
  per-KLoC values with target LOC and reject campaign caps as completion times.
- [x] Add distinct, source-grounded paper runtime observations for GPTScan,
  HoneyBadger, SAILFISH, and VulHunter. Keep SMARTIAN's campaign cap
  non-schedulable and MANDO-HGT numeric runtime unknown. Do not reuse the
  `smartbugsdb` source identity for these values, and do not fabricate missing
  profile/solc fields merely to pass the support gate.
- [x] Add tests proving runtime cards and explicit per-tool runtime/provenance
  reach the CEGO payload for the primary and every legal candidate.

## Checkpoint 10 — Primary-controlled supplementation (AC16)

- [x] Add boundary tests for primary missing rate, zero rate, positive rate,
  `n_eff` below/equal/above 15, credible peer gap, and sufficient primary.
- [x] Introduce one typed per-category primary decision and use it to gate
  ownership-panel candidate construction, DACE actions, CEGO input, assembly,
  and RuleChecker legality.
- [x] Prove a primary-sufficient category cannot receive a manually proposed
  complement, while a search-required category still falls back to primary-only
  when no candidate qualifies.
- [x] Repeat the Stage 1 count-independence metamorphic test.

## Checkpoint 11 — Execution-aware runtime and measured results (AC17–AC18)

- [x] Add shared schedule tests proving full parallelism uses `max`, an explicit
  insufficient job cap makes a composition illegal, and multi-file targets
  multiply the one-file estimate.
- [x] Resolve the default tool timeout from `B`; test an explicit shorter
  timeout rejecting a selected tool before execution.
- [x] Pass the resolved timeout to both runner paths and remove the native
  fallback's hard-coded value.
- [x] Measure per-tool elapsed runtime in fresh execution, aggregate it across
  sequential contracts, and persist it in `ToolExecutionStatus`/fused output.
- [x] Rename misleading parallel-runtime result fields to plan-runtime fields
  across schemas, engine, composition, CLI/JSON, README, and tests.

## Checkpoint 12 — Rank trace consistency and final audit (AC19)

- [x] Extract one Stage 1 comparator shared by visible ranking and primary
  selection; add a runtime-tie regression asserting rank 1 equals `t^star`.
- [x] Run focused runtime/Stage 1/Stage 2/execution tests, then the complete
  suite, compileall, CLI/runner help, representative smoke, and diff check.
- [x] Audit all Performance-DB changes: the old user metric/count diff must be
  unchanged; classify every additional hunk as approved runtime metadata or a
  source-grounded runtime observation.

## Checkpoint 13 — Runtime reliability follow-up (AC20–AC26)

- [x] Add failing regressions for a real KDE weight sum just above one by
  roundoff, long/short category alias fusion, ordinary analyzer failure,
  wrapper semantic failure/skip, failure-only batch aggregation, root-level
  stale reports/statuses, Slither 0.8 SmartBugs dispatch, multi-file imports,
  bytecode/runtime discovery, and excluded pragma upper bounds.
- [x] Clamp only tolerance-sized floating-point boundary drift before schema
  construction.
- [x] Centralize long-form canonical category normalization and use it at
  runner input, enrichment, parsing, and fusion boundaries.
- [x] Make report promotion and execution status depend on semantic outcome;
  remove `None` detail values and false-success wrapper paths.
- [x] Clear every current-run-consumable selected artifact before execution and
  prevent manifest fallback from reading a previous run.
- [x] Delete the Slither `get_src` path and route all Slither runs through
  SmartBugs.
- [x] Preserve source-project import context and dispatch accepted bytecode and
  runtime inputs without silent omission.
- [x] Replace literal-max pragma handling with constraint intersection shared
  by profiling, feasibility, and compiler selection.

Verified 2026-07-16: `247 passed`; `compileall`, CLI help, runner help, and
`git diff --check` passed. Production `get_src` matches are absent. A real
container analyzer smoke remains environment-dependent on a running Docker
daemon; fake SmartBugs/adapter integration paths are regression-covered.

```bash
python -m pytest -q tests/test_stage1_scoring.py tests/test_fusion_v2.py \
  tests/test_runner_fresh_execution.py tests/test_report_promotion.py \
  tests/test_execution_plan_v2.py
python -m pytest -q
python -m compileall -q toolrank tests
python -m toolrank.cli --help
python -m toolrank.runner --help
git diff --check
```

## Checkpoint 14 — Canonical Gower profile parity (AC27)

- [x] Add regressions that send the same source through runtime target analysis
  and the offline builder and compare compiler bucket, effective LOC, and all
  five complexity dimensions.
- [x] Cover comment-only lines, quoted pragma-like text, and an OR pragma so
  the two consumers cannot drift independently.
- [x] Make one shared profile function own the Gower tuple. Keep target-only
  classification, exact compiler constraints, import roots, and execution
  counts outside that shared tuple.
- [x] Preserve source facts for diagnostics after AST failure while preventing
  zero-complexity values from entering Gower; preserve unrelated user edits.
- [x] Run focused profile tests, the full suite, compileall, and diff hygiene.

```bash
python -m pytest -q tests/test_contract_profile.py tests/test_gower_profile_parity.py
python -m pytest -q
python -m compileall -q toolrank tests
git diff --check
```

## Checkpoint 15 — Full AST benchmark-profile rebuild (AC28–AC29)

- [x] Move the benchmark-profile builder into tracked/installable code and add
  a tracked manifest whose paths are relative to a caller-provided corpus root.
- [x] Define one versioned canonical AST engine, fixed compiler patches, and
  deterministic compatible-bucket fallback. Prove profiling substitution does
  not change exact feasibility/execution constraints and label the actual AST
  emitter.
- [x] Discover stable sample units with safe import closure, reject undeclared
  duplicate roots/corpus digests, and make the duplicate SmartBugs aliases
  contribute only one scene corpus.
- [x] Record per-dataset attempted/succeeded/skipped counts, bounded failure
  classes, source/manifest digests, canonical compiler versions, bandwidth
  seed/grid, and artifact schema/engine metadata.
- [x] Compute ranges and bandwidth solely from emitted samples and write the
  complete artifact atomically. Do not mutate `performance_db.json`.
- [x] Make the runtime loader reject legacy/mixed/malformed artifacts and make
  target AST failure produce no scene evidence rather than a zero-complexity
  cross-engine comparison.
- [x] Regenerate `toolcards/contract_profiles.json` from all required corpora
  and produce a deterministic migration audit of dataset membership, counts,
  ranges, bandwidth, representative weights, and resulting `t^star` changes.
- [x] Run focused builder/loader/parity tests, the full suite, compileall, CLI
  help, diff hygiene, and an independent Trellis check.

```bash
python3 -m pytest -q tests/test_gower_profile_parity.py \
  tests/test_profile_builder.py tests/test_scene_kde.py
python3 -m pytest -q
python3 -m compileall -q toolrank tests
python3 -m toolrank.cli --help
git diff --check
```

## Checkpoint 16 — Weighted Stage 1 evidence lineage (AC30)

- [x] Add schema and projection tests for aggregate `S_t`, per-benchmark
  `s_t,D`, normalized `w_D`, raw evaluation metrics, stable source/dataset IDs,
  and zero/one/many passage-to-evaluation links.
- [x] Add CEGO payload tests proving the primary and every legal candidate
  receive the typed Stage 1 projection and their evidence-lineage details.
- [x] Add null/unlinked tests proving qualitative passages do not receive a
  fabricated benchmark weight and cannot independently qualify a complement.
- [x] Add RuleChecker conflict tests for applicable weighted positive evidence,
  applicable weighted negative evidence, symmetric applicability filtering,
  hard `owner_ineligible` rejection, and model-supplied weight tampering.
- [x] Implement the typed contract in `schemas_v2.py`, project it once in
  `dace_rag.py`, serialize it in `cego.py`, and consume the same matrix values
  in `checker.py`; avoid parallel prompt-only reconstruction.
- [x] Trace one fixture through Stage 1 packet -> Stage 2 context -> evidence
  matrix -> CEGO JSON -> RuleChecker and assert exact weight/provenance
  preservation plus unchanged `t^star`.
- [x] Run focused tests, the complete tracked suite, compileall, CLI help, and
  `git diff --check` without modifying `toolcards/performance_db.json`.

## Checkpoint 17 — CEGO three-sample majority voting (AC31)

- [x] Add failing tests for exactly three calls per logical attempt, an exact
  2/3 complement ballot, a 2/3 primary-only ballot, tool/citation disagreement,
  one malformed sample, all samples unusable, and deterministic ballot ordering.
- [x] Add a repair-loop regression proving every repair is a fresh three-call
  vote with identical prior checker reasons and only the aggregate reaches the
  real RuleChecker.
- [x] Centralize the odd vote count and canonical ballot representation in
  `toolrank/cego.py`; retain temperature zero at the OpenAI-compatible boundary.
- [x] Union citations only across samples that voted for the winning tool,
  sort/de-duplicate them, and never pre-filter invalid refs. Feed that aggregate
  into the existing `assemble_decision`, then preserve the current checked
  primary-only behavior for transport failure and repair exhaustion.

```bash
python3 -m pytest -q tests/test_cego_majority.py tests/test_repair_fallback.py
python3 -m compileall -q toolrank tests
```

## Checkpoint 18 — Shared Stage 3 compilation bundle (AC32)

- [x] Add failing unit tests for one compiler invocation with Smartian and
  Vandal, source-only no-op, exact compiler/constraint selection, safe project
  standard JSON, component minimization, digest/settings validation, ambiguous
  contract output, missing bytecode, malformed output, timeout, and pre-worker
  failure.
- [x] Add runner/native parity tests showing both paths receive the same bundle
  ID; bytecode/runtime inputs compile zero times; every project source
  entrypoint routes through projections from the one project bundle.
- [x] Introduce the typed compilation bundle/manifest and one run-scoped
  builder. Use one optimizer-disabled standard-JSON invocation requesting only
  consumer-owned components, and make the bundle digest independent of its
  temporary directory.
- [x] Add a single adapter consumption registry. Change Vandal and Smartian to
  consume shared runtime/ABI instead of private `solc` invocations; record
  `SOURCE_ONLY` explicitly for upstream source-only adapters.
- [x] Thread compilation provenance and per-tool consumption into execution
  results/status manifests without putting compiler artifacts under report scan
  roots. Fail closed before analyzer dispatch on bundle errors.

```bash
python3 -m pytest -q tests/test_shared_compilation.py \
  tests/test_runner_shared_compilation.py tests/test_native_shared_compilation.py
python3 -m compileall -q toolrank tests docker/runners
python3 -m toolrank.runner --help
```

## Checkpoint 19 — Dynamic KB extraction and transactional commit (AC33)

- [x] Add failing offline tests for MinerU command construction/output
  discovery, two-channel LLM schema, tool/category/relation/tag normalization,
  numeric/count/unit gates, excerpt/locator provenance, deterministic IDs,
  same-paper/tool/category observation links, runtime Stage 1 projection, and
  explicit unlinked evidence.
- [x] Add duplicate-dataset tests proving a new paper updates the dataset view
  without duplicating scene mass and retains per-observation paper provenance.
- [x] Add generation tests for extraction, mapping, index-build, manifest,
  pointer-flip, post-flip verification, and recovery failures; readers must
  never mix stores and the visible pointer must retain its original hash on any
  pre-commit failure.
- [x] Implement an injectable update service plus `lakes-kb-update` CLI using
  MinerU and the existing OpenAI-compatible client in production. Keep all
  intermediate Markdown/extraction data in a private work directory.
- [x] Build the complete merged Performance KB, PassageStore, retrieval index,
  manifest, and reject log in an immutable generation, validate through
  production loaders, then publish one atomic pointer with journaled rollback.
  Make engine readers resolve the generation once. Do not alter packaged KB
  data during implementation/tests.
- [x] Document external MinerU/LLM/embedding requirements and a dry-run or
  explicit-output workflow; run CLI help without invoking any external service.

```bash
python3 -m pytest -q tests/test_kb_update_extract.py \
  tests/test_kb_update_validation.py tests/test_kb_update_transaction.py
python3 -m compileall -q toolrank tests
python3 -m toolrank.kb_update --help
git diff --check
```

## Checkpoint 20 — Complement must be stronger than a qualified primary

- [ ] Add a shared candidate-versus-primary strength predicate using the same
  Newcombe Recall-gap definition as the primary category diagnostic.
- [ ] Reject a feasible, count-qualified, budget-valid candidate when its
  credible Recall gap over a count-qualified positive primary is not positive.
- [ ] Preserve complement search for missing, non-positive, or under-evidenced
  primary rows, where a positive count-qualified candidate is
  evidence-stronger without fabricating a primary rate.
- [ ] Make the ownership panel, CEGO candidate payload, deterministic assembly,
  and RuleChecker consume the same strength result.
- [ ] Add the real arithmetic regression: infeasible Osiris may expose a
  diagnostic gap, but weaker Smartcheck must not become an owner; Conkas remains
  under-evidenced and the checked result is Slither-only.

```bash
python3 -m pytest -q tests/test_stage2_evidence.py \
  tests/test_stage2_eligibility.py tests/test_rule_checker.py
python3 -m compileall -q toolrank tests
git diff --check
```

## Checkpoint 21 — User-facing final report with verbatim tool findings

- [x] Add typed schemas for a provenance-labelled combination explanation and
  category -> tool results while retaining the existing normalized fused view.
- [x] Add parser regressions with nested/sentinel fields proving every accepted
  SmartBugs/generic/SARIF finding object survives byte-semantically unchanged in
  `Finding.raw`; normalized projections must not be written into that object.
- [x] Build category results from the verified composition and accepted
  findings. Include zero-finding required categories and observed primary
  categories, preserve checked owner order, and exclude ignored findings.
- [x] Add one post-Checker structured explanation call that can justify only the
  fixed tool combination. Record `LLM` source/model on success and an explicit
  deterministic fallback on missing client, request failure, or invalid output;
  neither path may change the certificate or execution plan.
- [x] Persist both views in `fused_report.json`, update CLI JSON round-trip tests,
  and add a fresh end-to-end fixture asserting category/tool raw JSON, plan-
  explanation provenance, and existing de-duplication/conflict behavior.
- [x] Re-run the real Slither-only arithmetic target and verify the final report
  contains the original `controlled-delegatecall` object (including its string
  confidence and tool-specific fields), an empty arithmetic findings list, and
  a truthful combination explanation source.

```bash
python3 -m pytest -q tests/test_report_parser.py tests/test_fusion_v2.py \
  tests/test_final_report.py tests/test_pipeline_status.py tests/test_cli.py
python3 -m pytest -q
python3 -m compileall -q toolrank tests
git diff --check
```

## Checkpoint 22 — Cross-paper runtime evidence and derived summaries (AC35)

- [x] Add typed `RuntimeLiteratureObservation` and
  `RuntimeLiteratureSummary` schemas plus validators for unique paper identity,
  homogeneous bases, finite positive values, exact constituent membership,
  exact `n`, replayable arithmetic mean, and truthful null/identity summaries.
- [x] Add the independently verified observations from
  `research/runtime_papers_gptscan_sailfish.json`,
  `research/runtime_papers_honeybadger_vulhunter.json`, and
  `research/runtime_papers_smartian_mando.json` to
  `toolcards/performance_db.json`. Preserve existing rows and unrelated user
  changes; do not place derived means in recognized raw runtime metric fields.
- [x] Persist the six tool summaries with the exact values and evidence counts
  in R21. Retain rejected/inadmissible works in the research audit rather than
  padding Performance-KB arithmetic constituents.
- [x] Attach a matching descriptive summary, when present, to each tool's
  runtime-evidence assessment and DACE/CEGO runtime card. Label it
  non-schedulable and keep `expected_runtime_minutes` unknown unless the
  existing compiler/LOC/support-qualified resolver independently succeeds.
- [x] Add focused tests for all four numeric summaries, both null summaries,
  per-KLoC/per-contract separation, copied paper IDs, mismatched formula/mean,
  component/campaign exclusions, JSON round-trip, and proof that the summary
  cannot affect Stage 1 ties, Stage 2 budgets, or runtime provenance.
- [x] Validate the packaged KB and run the runtime, DACE, CEGO, and full test
  suites. Record the exact evidence counts and the unavoidable Smartian/
  MANDO-HGT gaps in `progress.md`.

```bash
python3 -m pytest -q tests/test_runtime_literature.py \
  tests/test_runtime_reliability.py tests/test_runtime_evidence.py \
  tests/test_dace_rag.py tests/test_cego.py
python3 -m pytest -q
python3 -m compileall -q toolrank tests
python3 -m json.tool toolcards/performance_db.json >/dev/null
git diff --check
```

## Checkpoint 23 — Budget-driven fuzz campaigns (AC36)

- [x] Add a typed `FuzzCampaignBudget` contract and attach it only when the
  ToolCard declares `d8_mode=fuzz`. Keep historical
  `expected_runtime_minutes`/`RuntimeEstimateProvenance` absent for fuzz tools
  while retaining their descriptive `RuntimeEvidenceAssessment`.
- [x] Add one shared planning-runtime projection. Migrate Stage 2 primary and
  complement executability, plan constraints/runtime, RuleChecker, certificate,
  and composition consumers to it; leave the Stage 1 historical runtime
  tie-break unchanged.
- [x] Make an explicit timeout the fuzz campaign duration rather than a
  historical-runtime rejection. Preserve `max` across concurrently selected
  tools and multiplication across sequential execution inputs.
- [x] Expose both the null historical completion estimate and the typed campaign
  allocation in DACE/CEGO without allowing model-supplied values to enter the
  checker or execution plan.
- [x] Add regressions for all three packaged fuzz tools, a future renamed fuzz
  ToolCard, missing/qualified/campaign-cap historical evidence, default and
  explicit allocations, primary and complement eligibility, mixed and
  multi-fuzzer plans, multi-input over-budget behavior, and Stage 1
  non-interference.
- [x] Add/extend runner tests proving ConFuzzius and sFuzz receive the resolved
  SmartBugs `--timeout`, Smartian receives the same outer allocation and keeps
  its report reserve, and tiny budgets are never silently extended.
- [x] Run focused runtime/Stage 1/Stage 2/DACE/CEGO/runner suites, then the full
  tracked suite, compileall, CLI help, JSON validation, and diff hygiene. Do not
  modify Performance-KB observations, literature arithmetic, or paper LaTeX.

```bash
.venv/bin/python -m pytest -q tests/test_fuzz_budget_runtime.py \
  tests/test_runtime_evidence.py tests/test_stage2_runtime.py \
  tests/test_parallel_runtime.py tests/test_dace_rag_v2.py \
  tests/test_cego_assembly.py tests/test_runner_fresh_execution.py \
  tests/test_runner_outer_timeout.py tests/test_execution_schedule.py \
  tests/test_native_fresh_execution.py
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q toolrank tests docker/runners
.venv/bin/python -m toolrank.cli --help
.venv/bin/python -m json.tool toolcards/performance_db.json >/dev/null
git diff --check
```

## Expected File Scope

Primary implementation files:

- `.gitignore`
- `toolrank/schemas_v2.py`
- `toolrank/scene_scoring.py`
- `toolrank/engine.py`
- `toolrank/assignment_evidence.py`
- `toolrank/evidence_packet.py`
- `toolrank/category_candidates.py`
- `toolrank/ownership_evidence.py`
- `toolrank/dace_rag.py`
- `toolrank/cego.py`
- `toolrank/checker.py`
- `toolrank/schemas.py`
- `toolrank/profile_builder.py`
- `toolrank/scene_kde.py`
- `toolrank/scene_pool.py`
- `toolcards/contract_profile_manifest.json`
- `toolcards/contract_profiles.json`
- `Dockerfile`
- `toolrank/execution.py`
- `toolrank/runner.py`
- `toolrank/fusion.py`
- `toolrank/cli.py`
- `toolcards/performance_db.json`
- `README.md`
- focused files under `tests/`

Conditional files may be changed only if a failing boundary test proves they
consume the migrated contract. `toolcards/performance_db.json` may contain only
the approved runtime unit/basis metadata and independently sourced runtime
observations on top of the preserved user diff. Unrelated knowledge bases,
parsers, analyzer adapters, and paper sources remain excluded.
