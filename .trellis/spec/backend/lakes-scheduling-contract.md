# LAKES Scheduling Contract

## Scenario: Change the recommendation, orchestration, or fusion pipeline

### 1. Scope / Trigger

Use this contract whenever code changes target profiling, the Stage 1 score
domain, historical runtime evidence, Stage 2 category evidence,
action/certificate schemas, adapter dispatch, execution status, report
promotion, CEGO proposal generation, shared compiler artifacts, dynamic knowledge-base
publication, local-private knowledge selection, release-container architecture,
chat-provider configuration, Securify image lifecycle, CLI results, finding
fusion, or the persisted final-report presentation. These
layers share one breaking
`screc_v2` boundary; migrating only one consumer creates a runnable but
semantically inconsistent pipeline.

### 2. Signatures

```python
analyze_target(path) -> ContractFeatures
source_profile_facts(sources) -> {"solc": str, "loc": int}
profile_sources(sources) -> {"solc", "loc", "avg_cyc", "max_cyc", "sum_cyc", "max_nest", "coupling", ...}
profile_file(path, *, dataset_root=None) -> canonical Gower profile
build_artifact(*, corpus_root, manifest_path, generated_at=None) -> dict
load_profiles(path) -> ProfileKB
resolve_static_toolcard_snapshot(toolcards_dir) -> StaticToolcardSnapshot
classify_target_input(path) -> Literal["sol", "bytecode", "runtime"] | None
source_entrypoints(source_files, project_root) -> list[Path]
PerformanceKnowledgeBase.model_validate(payload) -> PerformanceKnowledgeBase
build_tool_table(cards, features, budget, kb, scene_pool) -> list[ToolTableEntry]
compute_scene_scores(scene_pool, kb, feasible_tool_ids, w_recall, w_precision) -> ScorePanel
select_primary(scene_pool, score_panel, tool_table, tau=0.2) -> PrimarySelection
build_stage2_context(stage1, kb, required_categories) -> Stage2EvidenceContext
decide_primary_categories(context_rows, primary_tool, required_categories) -> list[PrimaryCategoryDecision]
complement_strength_against_primary(*, candidate_rate, candidate_n_eff, primary_rate, primary_n_eff) -> ComplementStrengthResult
build_action_evidence_matrix(context, budget, *, retriever=None) -> ActionByEvidenceMatrix
run_cego(client, model, context, matrix, prev_verdict=None, *, w_recall=None, w_precision=None) -> Step2DecisionCertificate
assemble_decision(raw, context, matrix, budget) -> Step2DecisionCertificate
check_decision(certificate, context, matrix) -> CheckerVerdict
composition_from_certificate(certificate) -> CompositionPlan
planning_runtime_minutes(tool_table_entry) -> float | None
plan_runtime_minutes(tools, tool_table, schedule) -> float | None
generate_combination_explanation(*, client, model, certificate, checker_verdict, matrix, checker_enabled) -> CombinationExplanation
_enrich_report_with_categories(report, tool, mapping) -> dict
fuse_reports(findings_by_tool, composition, *, tool_statuses=None, findings_source="synthesized", combination_explanation=None) -> FusedReport
compact_fused_report_payload(fused_report) -> dict
build_compilation_bundle(target_path, selected_tools, *, selected_tool_solc_ranges=None, compiler_timeout_seconds=120.0, ...) -> Stage3CompilationBundle
validate_compilation_bundle(bundle, target_path, selected_tools) -> Stage3CompilationBundle
run_targets(target_path, results_root, selected_tools, *, write_lakes_output=True, ...) -> int
_native_smartbugs_execute(plan) -> ExecutionResult
execute_plan(plan, *, runner_env=None) -> ExecutionResult
run_process_with_deadline(command, *, timeout_seconds, ...) -> DeadlineProcessResult
_smartian_fuzz_timeout_seconds(outer_timeout_seconds) -> int
promote_valid_report_tree(staged_root, final_dir, *, quarantine_root) -> bool
aggregate_tool_status_history(history) -> ToolExecutionStatus
MinerUConverter.convert(pdf, work_dir) -> DocumentArtifact
OpenAIKnowledgeExtractor.extract(document) -> RawKnowledgeExtraction
KbUpdateService.update(*, pdf, kb_root, dry_run=False, work_dir=None) -> KbUpdateResult
load_current_generation(kb_root) -> LoadedKnowledgeGeneration
publish_generation(*, kb_root, performance_kb, passage_store, vector_index, rejects, created_at, run_id, old_pointer_bytes, ...) -> PublishResult
recover_kb_root(kb_root) -> RecoveryResult
resolve_api_key_from_env(base_url) -> str
_resolve_gptscan_api_base(explicit="") -> str
_resolve_gptscan_api_key(explicit="", api_base="") -> str
_resolve_gptscan_model() -> str
_inspect_docker_image(image) -> Literal["exists", "missing", "error"]
_run_securify2_build_process(command, *, cwd, env, display_command=None, redactions=()) -> int
```

`StaticToolcardSnapshot` owns
`performance_db_path`, `contract_profiles_path`, `passage_store_path`,
`vector_index_path`, and `private_active`. Consumers must use these resolved
paths together instead of reconstructing a static knowledge path independently.

Production dynamic-KB commands are:

```text
lakes kb ingest PDF --kb-root ROOT --toolcards-dir TOOLCARDS [--dry-run]
lakes-kb-update ingest PDF --kb-root ROOT --toolcards-dir TOOLCARDS [--dry-run]
lakes-kb-update validate --kb-root ROOT
lakes-kb-update recover --kb-root ROOT
```

The canonical release build is:

```text
docker build [--build-arg LAKES_IMAGE_PLATFORM=linux/amd64|linux/arm64] -t IMAGE .
```

Executable action IDs come only from `toolrank.action_contract.action_id_for`.
Parallel runtime comes only from `toolrank.plan_runtime`.
Stage 1 evaluation IDs come only from
`toolrank.schemas_v2.stage1_evaluation_id(tool, benchmark_id)`.

### 3. Contracts

- `Stage1EvidencePacket.schema_version == "screc_v2"` owns `t*`, `S_t`,
  `s_t,D`, normalized `w_D`, support mass, and terminal Stage 1 reasons.
- Every `BenchmarkToolScore.evaluation_id` is the canonical
  `stage1_evaluation_id(tool, benchmark_id)` and retains its Performance-KB
  `source_id` and dataset identity. `Stage1EvidenceLineage` is the matrix-owned
  projection of those rows: it preserves each tool's `S_t`, every unflattened
  `w_D`/`s_t,D`/Recall/Precision/rank row, and reverse passage links. CEGO may
  serialize this projection but must not reconstruct or replace it.
- `Passage.linked_evaluation_ids` has three distinct states. `None` permits only
  an exact `source_id` match for the same owner tool; `[]` explicitly declares
  no quantitative link; a non-empty list is an authoritative zero-or-more-row
  link and every ID must exist for that tool. Fuzzy source matching is
  forbidden. An unlinked qualitative passage has no benchmark relevance
  weight and cannot independently qualify a complement.
- Every evidence card ID is unique within an action matrix. A card stores only
  linked evaluation IDs plus the exact single-row `w_D` convenience value; a
  multi-row link is never flattened into one scalar. The Stage 1 rows in the
  matrix remain authoritative after JSON round-trip.
- RuleChecker resolves cited cards back to the matrix, filters positive and
  negative evidence with the same applicability predicate, deduplicates linked
  evaluation rows, and compares `sum(applicable positive w_D) >
  sum(applicable negative w_D)`. Applicable `owner_ineligible` remains a hard
  rejection even without a quantitative link. Extra weight-like fields from
  an LLM response are ignored because the model never owns evidence weights.
- Each logical CEGO proposal round owns exactly one structured request at
  `temperature=0.0`. The validated `CegoProposal` is passed directly to
  `assemble_decision`; CEGO has no application-level sampling, voting,
  abstention, or proposal aggregation. `OpenAICompatError` and schema-invalid
  output become `CegoError`. The caller may start one fresh proposal round only
  after RuleChecker rejects the preceding certificate and supplies its reasons.
  Bounded repair exhaustion still returns the checked primary-only plan.
- DACE owns one retrieval cell for every
  `(required_category, primary_or_feasible_tool, PLAN_COMPOSITION)` key.
  `PassageRetrievalDiagnostic` records the query, lexical/dense hit counts,
  returned passage IDs, fusion method, and bounded reason codes. When a bound
  dense index and embedding credential are available, retrieval combines BM25
  and dense ranks with reciprocal-rank fusion. A missing index/credential or a
  failed dense query retains deterministic BM25 results and exposes the exact
  fallback reason; it must not silently become an empty evidence result.
- `ActionByEvidenceMatrix.relevant_matrix_rows` contains exactly one typed row
  for the primary and every feasible candidate in every required category.
  Each row retains the matrix-owned Stage 1 score/benchmark lineage, category
  evidence, all four evidence slots, applicability, target/compiler
  constraints, and runtime provenance. CEGO serializes the complete Stage 1
  lineage once at the prompt top level. For each legal eligible candidate it
  includes one compact typed row without the nested Stage 1 copy, plus
  `stage1_tool_ref` and canonical linked evaluation IDs that resolve against
  that top-level object. It never dumps the full matrix or duplicates Stage 1
  lineage inside candidate rows.
- `profile_sources` is the single owner of the Gower compiler bucket,
  effective LOC, and five structural dimensions. Runtime target analysis and
  the offline benchmark-profile builder consume that same result; neither may
  reconstruct LOC or the categorical compiler feature independently.
- AST profiling uses the canonical patches declared by
  `CANONICAL_PROFILING_COMPILERS`. For constrained sources, try only
  major/minor buckets that intersect every source-unit pragma, from oldest to
  newest. For sources without a pragma, try the documented order from `0.8.x`
  down to `0.4.x`. The first compiler that emits a complete AST decides both
  `solc` and `profiling_compiler`; do not label a fallback profile with the
  initially preferred bucket.
- Profiling may rewrite pragmas only in an in-memory copy. Original source,
  `solidity_version_constraints`, and `primary_solidity_version` remain the
  feasibility/execution contract. A single-file runtime target and the offline
  builder must pass the same safe in-root import closure to `profile_sources`.
  The exact `blockscan_export_wrapper_v1` banner may be position-preservingly
  masked on both paths; ordinary Solidity containing similar words is not
  normalized.
- `ContractFeatures.gower_solc_bucket` is the explicit Stage 1 categorical
  feature. `primary_solidity_version` remains the exact representative used by
  feasibility/execution and must not be repurposed as the Gower bucket.
- A packaged profile artifact's `_meta.engine` must identify the same extractor
  used for the runtime target. A legacy or mixed-engine artifact is not
  comparable and must never be consumed silently. `solc_compact_ast_v3`
  artifacts record the manifest, deterministic compiler-selection orders,
  unique dataset identities, exact attempted/succeeded/skipped ledgers,
  source/profile digests, compiler usage, ranges, and bandwidth fit metadata.
  The loader recomputes internal counts, ranges, sample/source digests, and the
  bandwidth linkage; it never refits or repairs a stale artifact. The builder,
  manifest, migration audit, and parity tests must be present in a clean
  checkout.
- `_ranges` is derived only from emitted samples. Published `_bandwidth` is
  selected from the declared grid by leave-one-out likelihood over every
  normalized emitted profile and is bound to the profile digest, ranges, seed,
  full sample size, and method. Duplicate physical or
  content-identical corpora cannot contribute scene mass twice; exclusions are
  explicit manifest rows. Target AST failure retains source facts for
  diagnostics but yields no Gower scene instead of synthetic zero complexity.
- A source checkout may activate a local-private static snapshot only when all
  four runtime artifacts exist:
  `toolcards/.private/performance_db.json`,
  `toolcards/.private/contract_profiles.json`,
  `toolcards/.private/passage_store.json`, and
  `toolcards/.private/vector_index/index.json`. They are selected as one unit.
  The Performance/profile pair must pass its production loaders, exactly retain
  current public rows/datasets, and add matching unique dataset identities.
  The PassageStore/index pair must pass its production loaders, exactly retain
  the public passage and embedding prefixes, preserve passage ID order/count,
  use the same provider/model and embedding dimension, and bind the exact
  private store digest. Every private-only passage must explicitly carry
  `linked_evaluation_ids=[]` and no performance-observation links, so it stays
  qualitative. A missing artifact, stale prefix, mismatched delta, vector
  mismatch, or digest mismatch fails closed before recommendation. Any original
  private recovery source is provenance, not a runtime activation artifact.
  Explicit `kb_root` generation selection bypasses the complete static overlay.
  Git, wheel package-data, and Docker context rules must exclude the entire
  `.private` directory.
- Normalized scene weights are bounded numerical values. Clamp only
  tolerance-sized drift at `0` or `1` (for example,
  `1.0000000000000002 -> 1.0`) before constructing bounded schemas; materially
  invalid values such as `1.001` remain validation errors.
- Stage 1 reads overall Recall/Precision only. Category `detected`, `total`,
  `R_hat`, and `n_eff` may first appear in `Stage2EvidenceContext`.
- Primary eligibility requires feasibility and comparable-metric support mass
  `>= 0.2`. Selection is score, preferred raw metric, lower known runtime, then
  lexical ID.
- Historical runtime values come only from `PerformanceKnowledgeBase`; ToolCard
  IDs and names are aliases, never numeric runtime evidence. A normalized alias
  owned by more than one tool is ambiguous and must be ignored.
- The Performance KB declares `criteria.runtime_unit = "seconds"` and
  `criteria.runtime_basis_default = "per_contract"`. Runtime fields use this
  priority: `time_sec`, `execution_time_avg`, then
  `execution_time_avg_average_s`. Values must be positive and finite;
  cumulative seconds and timeout counts are never completion-time evidence.
- Row bases are `per_contract`, `per_kloc`, or `campaign_cap`. Convert
  `per_kloc` once with target LOC. A `campaign_cap` is descriptive metadata and
  is never schedulable.
- Collapse duplicate `(source_id, tool)` rows by maximum seconds. A schedulable
  candidate must match the target compiler bucket, must not contradict an
  available LOC bucket, and the compatible candidate set must retain at least
  `0.2` of the original normalized scene mass. Compute weighted P90 only inside
  that qualified set. Zero-weight, weakly linked, incompatible, and unrelated
  global rows remain unknown; there is no linked-max or global-max fallback.
- Runtime provenance retains every candidate row, original scene weight,
  compiler/LOC match, unit/basis, converted seconds, quantile participation,
  support threshold, and available sample/success/timeout/compilation-failure/
  failure counts. GPTScan, HoneyBadger, SAILFISH, VulHunter, and SMARTIAN paper
  observations keep independent source identities. SMARTIAN's campaign cap is
  unschedulable, MANDO-HGT stays unknown, and a paper row without a compatible
  scene profile cannot become an executable estimate.
- Cross-paper literature evidence is a separate descriptive layer.
  `RuntimeLiteratureObservation` retains one independent paper-level mean with
  exact paper/source/locator, reported and normalized unit/basis, denominator
  metadata, normalization, and limitations. Only homogeneous `per_contract` or
  `per_kloc` observations may be constituents of a
  `RuntimeLiteratureSummary`; copied paper identities, campaign caps,
  component-only values, and incompatible bases cannot enter its arithmetic.
- A literature summary must name its exact unique constituents, replay `n`,
  formula, precision, and unweighted arithmetic mean, and remain
  `scheduling_eligible=false`. `n=0` requires a null basis/mean/precision;
  `n=1` is an identity summary with `cross_paper_mean=false`. Exclusions may be
  empty when every reviewed observation is admissible, while limitations stay
  non-empty because the summary is descriptive rather than scheduling input.
- ToolCard ID/name aliases may attach a matching literature summary only to
  `RuntimeEvidenceAssessment.descriptive_literature_summaries`. The summary may
  be displayed by DACE/CEGO, but its mean must never populate a recognized raw
  runtime field, `expected_runtime_minutes`, `RuntimeEstimateProvenance`, Stage
  1 tie-breaking, Stage 2 budget checks, plan constraints, or execution
  timeouts. SMARTIAN and MANDO-HGT therefore retain null summaries rather than
  zero, and VulHunter's one-source value is labelled identity rather than a
  cross-paper mean.
- `ToolCostEntry.expected_runtime_minutes` and `runtime_provenance` are both
  present or both absent. Known runtime must be positive and finite, satisfy
  `minutes = selected_runtime_seconds / 60`, cite a selected source contained
  in the unique candidate-source list, and carry non-empty source/dataset IDs.
  DACE runtime cards expose the scheduling unit as minutes and source unit as
  seconds.
- `ToolCard.d8_mode` is the sole policy selector for fuzz scheduling. Its
  `ToolTableEntry.family == "fuzz"` projection may carry a
  `FuzzCampaignBudget` but may never carry historical completion runtime or
  runtime provenance. A non-fuzz family may never carry a fuzz allocation.
  Missing campaign allocation is allowed only as a fail-closed unresolved cost.
- `FuzzCampaignBudget` is a positive finite per-input user allocation with
  semantics `campaign_allocation_not_completion_estimate`. Its seconds and
  `timeout_source` must exactly match `ExecutionSchedule`; a default-source
  schedule must itself equal the overall runtime budget converted to seconds.
  A zero or unresolved budget creates no campaign allocation.
- `planning_runtime_minutes` is the only Stage 2/3 per-input cost projection:
  fuzz family -> campaign seconds divided by 60; every other family -> qualified
  historical completion minutes. Stage 1 continues to read only
  `expected_runtime_minutes`, so user budget cannot affect `t*` or its rank.
  DACE exposes Performance-KB history and the user-budget campaign as separate
  evidence cards with separate sources; CEGO labels the planning source and
  semantics explicitly.
- Every required `CategoryAssignment.owner_tools` begins with the immutable
  Stage 1 primary. At most one complement follows it.
- `PrimaryCategoryDecision` is the only category search gate. Missing rows,
  missing rates, and missing/`<15` effective evidence are `under_evidenced` and
  `SEARCH_REQUIRED`. With `n_eff >= 15`, non-positive primary `R_hat` is
  `confirmed_weak`; a count-qualified peer with a positive Newcombe gap lower
  bound is also `confirmed_weak`. All other categories are
  `PRIMARY_SUFFICIENT` and expose no complement candidate to DACE, CEGO,
  assembly, or RuleChecker.
- Category `R_hat` and `n_eff` use the normalized `w_D` values owned by the
  Stage 1 scene: `R_hat=sum(w_D*detected_D)/sum(w_D*total_D)` and
  `n_eff=sum(w_D*total_D)`. Raw KDE density remains audit provenance and cannot
  make the `n_eff >= 15` decision depend on an omitted common normalization
  constant.
- `complement_strength_against_primary` is the single quantitative gate shared
  by the primary diagnostic, ownership panel/CEGO surface, and RuleChecker. A
  candidate first requires `R_hat > 0` and `n_eff >= 15`. When the primary also
  has count-qualified evidence, the candidate-minus-primary Newcombe Recall-gap
  lower bound must be strictly positive. A missing or `n_eff < 15` primary row
  is an unreliable comparison baseline; search may remain diagnostic, but no
  candidate may pass the stronger-than-primary ownership gate. A
  count-qualified non-positive primary is a reliable zero baseline and still
  uses the same positive-lower-gap requirement.
- Passing the shared strength gate never overrides feasibility, applicable
  evidence, known runtime, or legal-budget checks. Each candidate is evaluated
  against the primary itself: an infeasible strong peer cannot make another,
  weaker candidate eligible. Search failure retains the primary and records
  `PRIMARY_ONLY_NO_COMPLEMENT`.
- After every hard gate passes, rank complements by descending `R_hat`,
  descending `n_eff`, then tool ID and expose at most five legal candidates per
  category. Overflow candidates remain complete typed matrix rows with
  `NOT_SHORTLISTED` eligibility and cannot be selected by CEGO or assembly.
  RuleChecker rebuilds the canonical partition from `Stage2EvidenceContext`,
  matrix-owned evidence cards, and the matrix budget; it rejects any supplied
  ownership panel whose partitions differ.
- The internal taxonomy uses the long-form DASP identifiers at every boundary.
  At minimum, `denial_service -> denial_of_service`,
  `unchecked_low_calls`/`unchecked_ll_calls -> unchecked_low_level_calls`, and
  `other`/`unknown -> unknown_unknowns`. Performance scores and count tables
  normalize independently, even when only one table is present or their keys
  differ.
- `ContractFeatures.present_input_kinds` records the actual non-empty subset of
  `sol`, `bytecode`, and `runtime`. Feasibility requires both ToolCard support
  and a registered adapter capability for every present kind; unknown adapters
  are not executable. Directory symlink inputs are ignored.
- `ContractFeatures.file_count` remains a profile fact. Its
  `execution_input_count` is the runner work count: Solidity import-graph
  entrypoints plus every accepted creation-bytecode and runtime-bytecode input.
  Imported `.sol` dependencies are not independent work items. Cyclic source
  components receive one deterministic representative so they cannot vanish.
- `ExecutionSchedule.contract_count` is copied from that execution-input count,
  not raw source-file count. `execution_jobs=0` means one worker per selected
  tool; an explicit smaller cap makes the composition illegal. Plan time is
  `max(per-input tool runtime) * contract_count`. Unknown runtime is never zero.
- `tool_timeout_seconds` defaults to the runtime budget in seconds. An explicit
  shorter timeout is a planning constraint. Normal adapters and native fallback
  use that same outer hard deadline. The deadline is absolute from process
  creation, so worker startup consumes the same budget. Native execution runs
  tools concurrently and each tool's inputs sequentially. Fresh elapsed minutes
  are aggregated per tool and never written back into historical
  Performance-KB evidence.
- The runner CLI accepts the exact positive floating-point outer timeout. Plan
  construction and native execution must not round it upward. An analyzer's
  integer inner limit may round up to one second only while the process remains
  bounded by the unchanged fractional outer deadline, so tiny campaigns end in
  a typed timeout instead of silently receiving more wall-clock time.
- Process-group timeout cleanup is part of the typed execution boundary.
  Reaching the absolute deadline sends termination signals immediately;
  `ProcessLookupError` and the macOS leader-exit `PermissionError` race cannot
  escape. Direct-child kill is the bounded fallback, and process reaping plus
  pipe draining each have a fixed `0.2s` upper bound. The result remains
  `returncode=124, timed_out=True`; cleanup time is not analyzer grace.
- Smartian's own integer fuzz limit must finish before the scheduler-owned
  outer deadline so its wrapper can normalize and promote `result.json`.
  `SMARTIAN_LIFECYCLE_RESERVE_SECONDS == 6` is the bounded sum of the
  two-second startup allowance and four-second report-normalization allowance,
  so `inner=max(1, floor(outer-6))`. The exact positive floating-point outer
  deadline is never rounded upward or extended. Budgets at or below six
  seconds may therefore end as a normal typed timeout rather than a successful
  Smartian report.
- `CompositionPlan.category_owners` and `FusedFinding.source_tools` are additive.
  Fusion groups only identical non-empty `(category, location)` keys and keeps
  raw variants plus inconsistent-field markers.
- A SmartBugs-backed current-run finding crosses an explicit three-step
  boundary: tool-native output, SmartBugs conversion to `result.json`, then
  LAKES enrichment of that finding with `raw_name`, canonical `category`, and
  `ignored` when applicable. The exact enriched `result.json` element is the
  accepted object exposed in the final category view. Tool-native tar/SARIF
  artifacts remain available under the raw run artifacts, but are not required
  to be embedded in each category result.
- An accepted current-run finding has two separate representations.
  Parser-owned normalized fields drive category/location fusion, while
  `Finding.raw` is a deep copy of the exact accepted post-adapter,
  post-enrichment JSON object. No parser or fusion step may reconstruct,
  flatten, or further inject fields into that object. The parser marks its
  internal projection with
  `__lakes_parser_finding_projection_v1__`; consumers must never infer that an
  arbitrary analyzer object is a projection merely because it has `raw`,
  `category`, or other canonical-looking keys.
- Persisted `category_results` is the stable union of checked owner categories
  followed by additional observed canonical categories. Checked categories
  preserve their exact owner order, observed categories default to the primary,
  and every owner appears even with `findings=[]`. Each finding value is the
  verbatim JSON object, not a normalized reconstruction. Top-level and
  per-category tool status values must be identical, and both must imply the
  same unavailable/partial category lists.
- `CombinationExplanation` describes only an already-fixed plan. After an
  enabled RuleChecker returns `ACCEPT`, one separate temperature-zero structured
  call may return exactly one non-empty paragraph plus limitations; its schema
  contains no tool, owner, weight, action, or execution control. Valid model
  output records `source=LLM` and the effective model. Missing/invalid clients,
  typed request failure, invalid schema, disabled Checker, or non-acceptance
  records `source=DETERMINISTIC_FALLBACK`, `model=null`, and a stable reason.
  Explanation generation cannot mutate the certificate or gate execution.
- Model explanation text is qualitative checked-plan prose. Statistical audit
  fields or rate-like values, ambiguous rate language, and matrix tools absent
  from the checked owner sets fail semantic validation with
  `LLM_RESPONSE_SEMANTICS_INVALID`; the text is never rewritten. Ordinary plan
  language such as `total runtime` and decimal durations such as
  `0.5 minutes` remain valid.
- Top-level `PipelineStatus` owns whether later fields may exist:
  `PRIMARY_NOT_SELECTED`, `NO_EXECUTABLE_PLAN`, `PLAN_READY`, `EXECUTED`,
  `EXECUTED_PARTIAL`, or `EXECUTION_FAILED`. `EXECUTED_PARTIAL` requires at
  least one usable current-run tool status plus a fused report;
  `EXECUTION_FAILED` means no selected tool produced usable current-run output.
- Production execution is fresh-only. Before running any contracts, the runner
  removes or atomically quarantines each selected tool's directory under the
  run-scoped results root; unselected tool directories are left untouched.
  Quarantine paths live outside every selected `<tool_id>` scan tree. Cleanup
  failure uses return code `74`, prevents analyzer execution, and disables all
  downstream fallback harvesting.
- Every analyzer invocation writes into a private staging directory. Output is
  promoted into the final run directory only after return code zero, readable
  JSON-object validation, a recognized list-valued findings container, absence
  of top-level or nested semantic failure/skip/timeout markers, and any required
  enrichment. Missing, malformed, structurally invalid, failed, skipped, or
  timed-out attempts leave no promotable final report. `PARTIAL` requires at
  least one real success; failure-plus-timeout is `FAIL`. Promotion is a
  same-filesystem copy-and-rename operation and filesystem errors fail closed.
- Slither always uses the pinned generic SmartBugs path. There is no Solidity-
  version branch and no `get_src` dependency. Source-mode SmartBugs staging
  copies only the safe in-project entrypoint and recursive `.sol` import
  closure, preserving relative paths; unrelated sources, `.env` files, and
  escaping symlinks are excluded. A project requiring this bridge fails closed
  when the pinned SmartBugs Python API is unavailable.
- The packaged Docker image is the canonical execution environment. LAKES,
  the Smartian runner, `.NET`, and `Smartian.dll` execute inside that image;
  `/work/docker/vendor/smartian/build/Smartian.dll` is therefore a container-
  local path, not a macOS host dependency. The build checks out the pinned
  `SMARTIAN_REF` only to supply the matching Nethermind/EVMAnalysis dependency
  scaffold, compiles the tracked
  `/work/docker/vendor/smartian/src/Smartian.fsproj` directly into that
  persistent container-local build path, verifies the DLL, and removes the
  temporary checkout/scaffold. No absolute compatibility symlink or host path
  participates. SmartBugs analyzers use the image's internal Docker daemon and
  therefore require the documented privileged container launch.
  `LAKES_IMAGE_PLATFORM` defaults to BuildKit's native `$BUILDPLATFORM`.
  The Smartian SDK builder always runs on `$BUILDPLATFORM`, selects
  `linux-x64` or `linux-arm64` only as the target runtime identifier, and the
  final image installs the matching native `.NET` runtime. Never execute the
  .NET SDK/runtime through QEMU as part of the normal Apple-Silicon build.
  SmartBugs' analyzer images remain pinned to `LAKES_DOCKER_PLATFORM=linux/amd64`.
  Because official Linux `solc` releases are x86-64, an ARM final image adds
  the `amd64` Debian architecture plus `libc6:amd64` and
  `libstdc++6:amd64`; the Docker host's existing platform emulator then runs
  those compilers. Do not install an in-container all-architecture QEMU bundle:
  cross-platform inner Docker execution already requires host binfmt support.
  The slim final image contains the `.NET` runtime rather than the SDK, so
  preflight uses `dotnet --info` and enables invariant globalization before
  executing Smartian; `dotnet --version` is not a valid runtime-only probe.
  GPTScan retains its historical `z3-solver==4.11.2.0` environment on x86-64.
  ARM builds substitute the first compatible pinned wheel,
  `z3-solver==4.13.0.0`, install the pinned Falcon source without dependency
  re-resolution, and verify both versions by import during the image build.
  Running `python -m toolrank` directly on a host is a separate development
  mode: it must explicitly provide a host-valid Smartian DLL override if that
  mode is supported, and failure to resolve `/work` there does not diagnose the
  packaged image.
- The release wheel contains the default `toolcards` package, its root JSON
  knowledge files, and `toolcards/vector_index/index.json`. The recommendation
  CLI resolves that installed sibling package as its default read-only
  knowledge directory. Dynamic ingestion still requires an explicit
  `--toolcards-dir` to identify the caller-selected baseline and never writes
  into packaged data.
- `.bin`/`.hex` inputs are normalized as creation bytecode; `.rt`, `.runtime`,
  `.rt.bin`, and `.runtime.hex` forms are normalized as runtime bytecode and
  dispatched with runtime mode. Unsupported adapter/input pairs fail before
  SmartBugs can report a zero-task success.
- Solidity pragmas use npm-style constraint semantics (exact, caret, tilde,
  comparator ranges, and OR). Comments and quoted text do not create pragmas.
  Multi-file/dependency constraints are intersected, excluded upper bounds are
  never selected, and compiler-dependent adapters choose only an installed
  version satisfying the complete constraint set; no compatible version or a
  failed selector is an execution failure.
- The native SmartBugs fallback follows the same selected-tool cleanup contract.
  Historical reports must never enter production through ancestor-directory
  discovery, an environment variable, an API parameter, or a CLI flag. Offline
  report replay, if ever needed, must be a separate explicit workflow.
- Stage 3 creates a compilation bundle only when a selected Solidity-source
  route has a registered shared-artifact consumer. Smartian consumes ABI plus
  creation bytecode; Vandal consumes runtime bytecode. Upstream analyzers such
  as Slither remain source-mode and record `SOURCE_ONLY`; source-only plans and
  existing bytecode/runtime inputs record `NOT_APPLICABLE` and invoke no
  compiler. Do not claim universal shared compilation for adapters that still
  compile internally.
- A required bundle is one optimizer-disabled, non-via-IR standard-JSON
  compilation of the safe project entrypoint closure. The selected installed
  compiler must satisfy all project pragmas and every selected ToolCard
  `d2_solidity_versions` range. The bundle binds source bytes, settings, input,
  output, compiler binary, requested components, consumer routes, and a stable
  bundle ID with digests. Runner and native fallback validate and reuse that
  same object. Bundle failure occurs before analyzer dispatch, leaves every
  selected tool `NOT_RUN`, and permits no stale-report harvest.
- `ExecutionResult.compilation`, top-level `artifact_consumption`, and each
  `ToolExecutionStatus.artifact_consumption` describe the same run. Top-level
  `consumed` values are derived from actual per-tool statuses after execution;
  they must not retain the bundle's pre-dispatch `False` value after successful
  shared-artifact consumption.
- Shared-artifact `consumed=True` means at least one exact
  `(tool, logical_input_id)` Solidity route returned zero and passed current-run
  report validation/promotion. Route existence, process start, timeout, failure,
  cleanup failure, or `NOT_RUN` is not consumption success. Mixed histories are
  true only when one shared-source invocation succeeded. Runner, native, and
  manual `execute_plan` results derive the top-level map from the same per-tool
  statuses. Return code `74` may suppress harvest, but it must preserve the
  current runner status manifest and any earlier successful consumption.
- Dynamic Performance-KB rows use stable `PerformanceObservation.observation_id`
  values. These IDs are persistent provenance, not run-derived Stage 1
  evaluation IDs. A passage may link an observation only when paper, canonical
  tool, and normalized category match. At recommendation time, project that
  reference only onto an exact source/dataset/tool row already present in the
  current `Stage1EvidenceLineage`; never fabricate an evaluation row.
- PDF ingestion is `MinerU -> strict two-channel LLM JSON -> Map&Check ->
  Commit`. Every metric/capability candidate names an existing MinerU block and
  an excerpt contained in that block. A table locator must identify the exact
  structured table, row, and column containing the excerpt. Tool aliases must
  map uniquely; categories, relations, actions, tags, units, runtime bases,
  numeric ranges, counts, and cross-channel links are allow-list validated.
  Rejected candidates receive safe structured reject records and never become
  KB evidence.
- One canonical dataset scene remains one Stage 1 weight source even when
  several papers add observations. A newly observed dataset without a tracked
  canonical contract profile is stored with `stage1_eligible=False`; ingestion
  must not synthesize a Gower profile or duplicate KDE mass.
- A dynamic KB generation contains a Performance KB, PassageStore, vector
  index, reject log, and digest/count manifest under an immutable generation
  directory. The vector index must match passage ID order, row count, and the
  exact PassageStore digest. Readers resolve `kb_current.json` exactly once and
  load all stores from that generation. Publication validates every artifact,
  then atomically replaces the single pointer; post-flip failure restores the
  exact prior pointer or requires explicit recovery. A dry run uses the current
  generation when one exists and never changes the pointer.
- Dynamic ingestion credentials come only from the environment. Embedding
  index construction disables any fallback that would place an API key in a
  subprocess argv. `--toolcards-dir` remains explicit so ingestion records the
  selected read-only baseline independently from its writable KB root.
- Execution plans and serialized results never contain API keys. The engine
  passes a key only through the runner child's ephemeral environment; generic
  adapter workers receive a sanitized environment and no key in their private
  request. Only GPTScan receives it through private stdin and an environment-to-
  in-memory-argv wrapper. Secret-forwarding CLI flags are forbidden and streamed
  output is redacted.
- Chat defaults are the official DeepSeek endpoint
  `https://api.deepseek.com` and model `deepseek-v4-flash`. Official DeepSeek
  hosts resolve `DEEPSEEK_API_KEY` before generic `OPENAI_API_KEY`;
  SiliconFlow hosts resolve `SILICONFLOW_API_KEY` before generic
  `OPENAI_API_KEY`; every other host may resolve only `OPENAI_API_KEY`.
  Provider-specific credentials must never cross host boundaries. GPTScan may
  retain explicit OpenAI-compatible overrides, but its no-override path uses
  the same official DeepSeek base, model, and endpoint-aware key resolution.
  Structured requests to an official DeepSeek host explicitly disable the
  provider's default thinking mode so temperature zero remains effective, and
  enable DeepSeek JSON output; custom compatible hosts receive neither field.
- SiliconFlow is an embedding provider only. Its Qwen embedding endpoint and
  credential are independent from CEGO, report explanation, KB extraction,
  and GPTScan chat completion.
- Securify first inspects its exact versioned Docker image tag. All three
  inspect attempts must explicitly report `No such image` before a build is
  allowed; one successful attempt reuses the image, and timeout/daemon/context/
  permission ambiguity fails closed. Inspect, build, and run use the current
  Docker user connection without interactive `sudo`. BuildKit output is
  captured in a regular temporary file and replayed after the direct Docker
  client exits, so a descendant-held pipe cannot block the adapter worker.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| No scene evidence | `Stage1Status.NO_SCENE_EVIDENCE`; no Stage 2 objects |
| Packaged profile engine differs from the runtime Gower extractor | reject/fail closed; never compute cross-engine distances |
| A broad/no-pragma source fails under the first canonical profiling compiler | try the next declared compatible bucket; persist the actual successful compiler/bucket |
| Runtime file target imports local Solidity dependencies | profile the same safe import closure as the offline builder |
| Profile artifact count, path, compiler, range, digest, coverage ledger, or bandwidth linkage is stale | `ProfileArtifactError`; never repair or refit at runtime |
| Target source facts exist but no canonical compiler emits a complete AST | retain diagnostics, return no scene evidence |
| None of the four local-private runtime artifacts exists | use all four tracked public static artifacts |
| All four private artifacts pass production loaders, exact public-extension checks, vector binding, and qualitative-link checks | use the complete private snapshot and emit the local-private warning |
| One to three private runtime artifacts exist, any path is not a regular file, or any artifact is invalid/stale/mismatched | `ValueError` before Stage 1; never mix public and private artifacts |
| A private-only passage has `linked_evaluation_ids=None`, a non-empty evaluation link, or any performance-observation link | `ValueError`; private-only knowledge must remain explicitly qualitative |
| Explicit `kb_root` is supplied | use its dynamic Performance/PassageStore/vector generation and the public static profile artifact; bypass every local-private static artifact |
| No feasible tool | `Stage1Status.NO_FEASIBLE_TOOL`; no Stage 2 objects |
| No support mass `>= 0.2` | `NO_PRIMARY_WITH_SUFFICIENT_SUPPORT`; no fallback tool |
| ToolCard contains runtime but the Performance KB does not | runtime remains unknown |
| Tool alias is owned by multiple canonical tools | exclude that alias; do not assign its runtime row |
| Runtime is non-positive/non-finite, cumulative, or a timeout count | reject or ignore it as per-run evidence |
| Runtime and provenance differ in presence or seconds/minutes disagree | schema validation error |
| Compatible runtime support is at least `0.2` | use weighted P90 inside that qualified candidate set |
| Runtime support is below `0.2`, compiler mismatches, or only unrelated history exists | runtime remains unknown; no fallback |
| Literature constituents repeat a paper, mix bases, include cap/component evidence, or disagree with `n`/formula/mean | schema validation error; never create a descriptive summary |
| A valid literature summary exists without independently qualified raw runtime evidence | expose it only in runtime assessment/DACE/CEGO; runtime, provenance, budget eligibility, and timeout planning remain unknown |
| `d8_mode=fuzz` with missing, qualified, campaign-cap, or literature runtime evidence | keep history descriptive; set historical completion runtime/provenance null and plan only from a valid campaign allocation |
| Non-fuzz family carries a campaign, or fuzz family carries historical completion runtime | schema validation error; never choose policy by field presence or tool name |
| Fuzz campaign seconds or timeout source differs from the execution schedule | runtime is unverifiable; reject the plan before execution |
| Default fuzz schedule differs from `runtime_cap_minutes * 60`, or budget is zero/unresolved | create no campaign allocation; fuzz runtime remains unknown and execution fails closed |
| Explicit fuzz timeout exceeds the overall plan budget after sequential-input multiplication | `NO_EXECUTABLE_PLAN`; do not shorten, split, or execute the campaign |
| Primary runtime missing/over budget | `Stage2Status.NO_EXECUTABLE_PLAN`; preserve `t*` |
| Primary row/rate missing or `n_eff < 15` | `SEARCH_REQUIRED / under_evidenced`; retain primary |
| Primary `n_eff >= 15` and `R_hat <= 0`, or credible peer gap | `SEARCH_REQUIRED / confirmed_weak`; retain primary |
| Primary evidence otherwise sufficient | `PRIMARY_SUFFICIENT`; no complement slate exists |
| Complement `R_hat <= 0`, `n_eff < 15`, or runtime missing | exclude complement; retain primary owner |
| Positive count-qualified primary and candidate-minus-primary Newcombe lower bound `<= 0` | exclude that candidate as not evidence-stronger; do not expose it to CEGO |
| Primary row/rate missing or primary `n_eff < 15`; candidate has `R_hat > 0,n_eff >= 15` | open diagnostic search but fail the stronger-than-primary ownership gate because the comparison baseline is unreliable |
| Primary has `R_hat = 0,n_eff >= 15`; candidate has `R_hat > 0,n_eff >= 15` | treat zero as a reliable baseline and require a strictly positive candidate-minus-primary Newcombe lower bound |
| One stronger peer is infeasible while another feasible candidate is weaker than the primary | reject both as complements; retain primary-only ownership |
| Weight differs from `0`/`1` only by configured floating tolerance | clamp before bounded schema construction |
| Weight is materially outside `[0,1]` | schema validation error; do not hide it with clamping |
| Performance category exists only in counts or uses a legacy alias | normalize it independently to the canonical long form |
| Target contains an input kind absent from ToolCard or adapter capabilities | tool is infeasible before execution |
| Directory contains imported Solidity dependencies | schedule only import-graph roots; retain dependencies in staged closure |
| Directory contains only unsafe symlink inputs | ignore them; target becomes unsupported rather than escaping its root |
| Solidity constraints are disjoint or no installed compiler satisfies them | fail closed; never widen or choose an excluded/uninstalled version |
| Applicable `owner_ineligible` evidence | exclude that category complement |
| Passage explicitly cites an unknown or another tool's Stage 1 evaluation | reject matrix construction; never downgrade it to unlinked prose |
| Passage has `linked_evaluation_ids=[]` or no exact same-tool source match | retain it as unweighted qualitative evidence; it cannot independently qualify a complement |
| Two evidence cards share an ID | reject matrix construction; CEGO and RuleChecker must never resolve a ref by list/dict overwrite order |
| Stage 1 evaluation ID differs from canonical tool/benchmark identity | schema validation error before Stage 2 |
| Applicable cited positive relevance is equal to or below applicable negative relevance | RuleChecker rejection and bounded repair |
| LLM emits its own `w_D` or other weight-like fields | ignore them; recompute only from matrix-owned Stage 1 rows |
| Missing/irrelevant cited support | RuleChecker rejection and bounded repair |
| The one CEGO request raises `OpenAICompatError` | raise `CegoError` for that proposal round; the bounded caller fallback remains checked primary-only |
| The one CEGO response fails `CegoProposal` validation | raise `CegoError`; never reinterpret malformed output as primary-only, a vote, or an abstention |
| Repair exhaustion | checked primary-only certificate, never an ownerless/stop action |
| Source-only plan or bytecode/runtime input | compilation `NOT_APPLICABLE`; invoke no compiler |
| Required shared bundle has no common installed solc, malformed output, missing component, timeout, or digest mismatch | fail before every analyzer worker; all selected tools remain `NOT_RUN` |
| Runner/native consumer route or source digest differs from the bundle | reject the bundle; never privately recompile or consume stale artifacts |
| Successful shared consumer is marked consumed only in its per-tool status | recompute top-level consumption from statuses; result must not contain contradictory provenance |
| Shared route exists but its invocation fails, times out, never runs, or fails cleanup before success | `consumed=false` in both per-tool and top-level provenance |
| Mixed input history has at least one validated shared-source success before a later failure/cleanup `74` | preserve `consumed=true` and the current per-tool status manifest; disable harvest only |
| POSIX group leader exits between TERM and KILL and `killpg` raises `PermissionError` | bounded direct-child fallback; return typed `124/TIMEOUT`, never an exception |
| Smartian outer budget is greater than six seconds | run the inner fuzzer for `floor(outer-6)` seconds and retain the exact original outer hard deadline |
| Smartian outer budget is six seconds or less | inner limit is one second; a clean report is best-effort and otherwise the result is typed timeout |
| Packaged Docker execution resolves Smartian at `/work/...` | execute it inside the image; no macOS Smartian path or host bind mount is required |
| Native Apple-Silicon build would execute the x64 .NET SDK/runtime under QEMU | keep the builder and final image native; cross-target only the Smartian runtime identifier |
| ARM image runs an official Linux `solc` without its x86-64 loader/libraries | install `libc6:amd64` and `libstdc++6:amd64`; `solc --version` must succeed during live release verification |
| Runtime-only `.NET` image is probed with `dotnet --version` or before invariant globalization is enabled | use `dotnet --info` with `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1`, then execute the Smartian usage smoke |
| GPTScan's historical Z3 pin has no ARM wheel | select the explicit architecture-specific Z3 pin, patch only the pinned Falcon dependency metadata, install Falcon without dependency resolution, and import-check both |
| Requested release platform is neither `linux/amd64` nor `linux/arm64` | fail the Smartian build stage; never guess a runtime identifier |
| Host-Python development execution uses the container-only Smartian default without an override | report a host-mode configuration error; do not infer that the packaged Docker image is missing Smartian |
| At least one selected tool succeeds and another fails/times out | preserve and fuse valid current-run output; return `EXECUTED_PARTIAL` and mark partial/unavailable categories |
| No selected tool succeeds | return `EXECUTION_FAILED`; never label failure-only or timeout-only output partial |
| Accepted tool finding has arbitrary nested/tool-specific fields or its own `raw` key | preserve the complete outer finding object verbatim; normalized fields remain a separate parser projection |
| SmartBugs converts a native finding and LAKES adds `raw_name`/`category`/`ignored` | treat the resulting enriched `result.json` element as the accepted verbatim boundary; preserve it unchanged from parsing through `category_results` |
| Tool-native tar/SARIF contains fields absent from SmartBugs `result.json` | retain the native artifact under raw run artifacts; do not classify the final category view as lossy relative to a boundary it does not promise |
| Required owner category has zero accepted findings | emit the category and every checked owner with `findings=[]`; never omit it or claim safety |
| Observed primary finding belongs to a non-requested canonical category | append that category after checked categories with primary-only ownership |
| Complement finding belongs to a category it does not own | exclude it from both category and fused result views |
| Explanation client is absent/invalid, request raises `OpenAICompatError`, response is multi-paragraph/malformed, Checker is disabled, or verdict is not `ACCEPT` | persist a non-empty deterministic fallback with null model and stable limitation; execute the unchanged plan |
| Explanation response attempts to add plan-control fields | schema rejection and deterministic fallback; never apply any emitted control |
| Explanation text repeats category statistics, uses an ambiguous rate value, or names an unselected matrix tool | semantic rejection with `LLM_RESPONSE_SEMANTICS_INVALID`; preserve the checked plan and persist a labelled fallback without rewriting model prose |
| Explanation text says `total runtime` or `0.5 minutes` without using a statistical audit field | accept the otherwise valid qualitative LLM paragraph; do not confuse ordinary budget prose with `detected/total` or a rate |
| Category-result owner order/status or availability contradicts the checked/top-level report | schema validation error; do not persist a contradictory final report |
| Stale report in a selected tool directory | delete before analyzer invocation; never treat as success |
| Report for a contract removed from a directory target | remove with the selected tool directory before batch execution |
| Analyzer returns non-zero | do not accept or enrich any report as the current result |
| Analyzer returns zero with a semantic error/skip/timeout marker | reject the report and record non-success |
| Batch contains failures and timeouts but no success | `FAIL`, never `PARTIAL` |
| Analyzer returns zero but produces no recognized valid `result.json` | mark that invocation failed and do not promote artifacts |
| GPTScan raw output is missing, malformed, `success != true`, or lacks list `results` | fail; never synthesize a successful empty report |
| Selected output cannot be deleted but can be renamed | quarantine outside tool scan paths, then continue/fail as the caller requires |
| Selected output cannot be deleted or quarantined | return `74`; do not execute, harvest, fuse, or throw an uncaught cleanup exception |
| Explicit jobs are fewer than selected tools | reject the composition; never switch the estimate from max to sum |
| API key supplied for execution | ephemeral GPTScan-only delivery; absent from plans, argv, reports, logs, and non-GPTScan environments |
| Default chat configuration has no explicit provider override | use `https://api.deepseek.com`, `deepseek-v4-flash`, and `DEEPSEEK_API_KEY` |
| DeepSeek/SiliconFlow key exists but resolved chat host is unrelated | ignore the provider key; only generic `OPENAI_API_KEY` may configure a custom host |
| Securify image inspect succeeds on any retry | cache/reuse the exact tag and do not build |
| Every Securify image inspect attempt explicitly reports `No such image` | build the exact tag once, then cache it only after success |
| Securify inspect times out or reports daemon/context/permission ambiguity | fail closed; do not build, cache, or run |
| Securify execution would require an interactive sudo prompt | invoke direct Docker instead; never block the noninteractive worker on `sudo` |
| MinerU output is missing/ambiguous, LLM JSON is malformed, or document/PDF digests differ | abort extraction; do not publish a generation |
| Provenance excerpt is absent from the named block, or a table locator lacks an exact valid cell | reject that candidate with a structured provenance reason |
| Tool/category/relation/tag/unit/range/count/link validation fails | reject only that candidate; accepted candidates remain independently mergeable |
| Every extracted candidate is rejected or conflicts during merge | report rejected/no accepted change and do not flip the pointer |
| New dataset has no canonical contract profile | retain the observation as Stage 1-ineligible; do not add scene mass |
| Generation file digest/count, observation link, vector order/count/store digest, or manifest ineligible count differs | reject the generation before visibility |
| Failure occurs before pointer flip | original pointer bytes remain unchanged |
| Post-flip verification fails | atomically restore exact prior pointer; otherwise require `recover` |
| Dry-run targets a root with a current generation | merge against that one resolved generation and leave its pointer unchanged |

### 5. Good / Base / Bad Cases

- Good: primary `a`, category evidence qualifies `b`, owners become `[a, b]`,
  both reports contribute, and a shared location has `source_tools=[a, b]`.
- Gower good: the same source produces the same compiler bucket, effective LOC,
  and five complexity values through target analysis and the tracked offline
  builder; comments and quoted pragma-like text do not change the tuple.
- Gower base: a broad pragma compiles only under a later allowed canonical
  bucket, so the stored Gower bucket is that successful emitter while the
  untouched execution constraint remains broad.
- Gower bad: an AST-derived target is compared with a `source_scanner_v1`
  benchmark artifact, a fallback AST is labeled with the first attempted
  compiler, imports are included on only one profiling path, or a parity test
  imports a builder excluded from Git.
- Local-private good: all four ignored runtime artifacts exactly extend the
  current public Performance/profile/Passage/vector data. The source checkout
  uses them together, reports that fact, and the appended private passages have
  explicit empty quantitative links.
- Local-private base: `.private` is absent in a release checkout, so the same
  code uses only the four tracked public artifacts.
- Local-private bad: activate only Performance/profile while silently reading
  the public PassageStore, trust a vector index by filename alone, retain a
  stale public prefix, or let private prose inherit a quantitative source link.
- Base: no complement qualifies, every requested category remains `[a]`, and
  the legal action is `run_primary`.
- Bad: count confidence changes Stage 1 from `a` to `b`, a complement replaces
  the primary, unknown runtime is treated as zero, or fusion deletes primary
  findings after adding a complement.
- Runtime good: KB rows `120s` and `60s` become `2min` and `1min`; a Stage 1
  score tie selects the `1min` tool, and Stage 2 checks that same `1min` value.
- Runtime base: a packaged tool has no valid KB runtime row, so its runtime and
  provenance are both `None`.
- Runtime bad: a ToolCard value overrides the KB, an ambiguous alias assigns a
  row to one tool, `*_total_s` is treated as one run, or downstream code divides
  minutes by 60 again.
- Runtime-literature good: four independent HoneyBadger `per_contract` paper
  means replay to `78.57`, remain `scheduling_eligible=false`, and reach
  DACE/CEGO only through `descriptive_literature_summaries`.
- Runtime-literature base: SMARTIAN has only campaign/component evidence, so
  its summary has `n=0`, null basis/mean/precision, and its scheduling runtime
  stays unknown rather than becoming zero or the campaign cap.
- Runtime-literature bad: write a cross-paper mean into
  `execution_time_avg`, mix GPTScan `per_project` with `per_kloc`, count a
  copied baseline as independent, or let a descriptive mean satisfy a tie,
  budget, plan, or execution-timeout check.
- Fuzz-runtime good: a renamed `d8_mode=fuzz` tool has no historical completion
  estimate, receives the checked explicit 90-second per-input campaign, reaches
  DACE/CEGO/Checker with that source, and the real runner keeps a 90-second hard
  outer deadline.
- Fuzz-runtime base: two fuzzers run concurrently for the same full campaign;
  plan time uses their maximum. Two sequential inputs multiply that maximum and
  may make a default full-budget campaign ineligible.
- Fuzz-runtime bad: identify fuzzers by name, copy a paper mean/campaign cap
  into completion runtime, split allocation across tools, ignore timeout-source
  mismatch, create a positive campaign from zero budget, or round a sub-second
  outer deadline upward.
- Fresh-execution good: a stale `Old.sol` report exists, the current target only
  contains `New.sol`, and the fused output contains findings from `New.sol` only.
- Fresh-execution base: the selected analyzer runs, writes `result.json` beneath
  its freshly recreated `out_dir`, and that report is normalized and fused.
- Fresh-execution bad: a same-named report in an ancestor `smartbugsout` or the
  current output directory bypasses analyzer invocation.
- Final-report good: Slither emits native output, SmartBugs converts it, LAKES
  enriches the converted finding with `raw_name` and canonical `category`, and
  a checked Slither-only plan persists that complete enriched object unchanged
  under its category. Native tar/SARIF remains separately auditable.
- Final-report base: no LLM client is configured, so the same checked plan and
  findings execute and persist with `DETERMINISTIC_FALLBACK`, `model=null`, and
  `LLM_CLIENT_UNAVAILABLE` rather than fabricated model provenance.
- Final-report bad: reconstruct raw findings from five canonical fields, guess
  an internal projection from the presence of a `raw` key, drop empty owner
  categories, repeat contradictory tool statuses, or let explanation prose
  change the certificate. Prose that repeats `R_hat`, `n_eff`, raw count fields,
  rate-like values, or an unselected tool is also rejected rather than edited.
- Container-execution good: `lakes:latest` contains the Smartian runner, DLL,
  and `.NET`; `/work/...` resolves inside the container without a host mount.
- Container-architecture good: an Apple-Silicon build produces a native ARM
  outer image, starts the native Smartian DLL, and executes an official x86-64
  `solc` through the host platform emulator plus the two packaged x86 runtime
  libraries. The runtime-only `.NET` preflight uses `dotnet --info`, and
  GPTScan imports the pinned ARM-compatible Z3/Falcon pair.
- Container-execution base: a developer invokes the host Python CLI and passes
  an explicit host-valid Smartian DLL path for that non-production mode.
- Container-execution bad: treat a host Python `/work` lookup failure as proof
  that the packaged image is broken, or require the production container to
  read a developer-specific absolute macOS path.
- Container-architecture bad: force the outer image to `linux/amd64` on an ARM
  host so the .NET runtime itself runs under QEMU, or install the full
  `qemu-user-static` package inside the image instead of relying on the host
  platform contract already required by SmartBugs.
- Primary-evidence good: `R_hat=0,n_eff=15` is confirmed weak and opens search;
  `R_hat>0,n_eff>=15` without a credible peer gap closes search.
- Primary-evidence base: missing or low `n_eff` opens search as under-evidenced,
  but no qualified complement still yields primary-only ownership.
- Complement-strength good: primary `R_hat=0.2,n_eff=100` and candidate
  `R_hat=0.8,n_eff=100` produce a positive Newcombe gap lower bound; the
  candidate may enter the eligible panel if every non-statistical gate passes.
- Complement-strength base: a missing or under-evidenced primary opens
  diagnostic search but no candidate enters the legal panel because the
  comparison baseline is unreliable. A count-qualified zero primary is a
  reliable baseline and still requires a positive Newcombe lower bound.
- Complement-strength bad: Smartcheck has positive count evidence but a lower
  category Recall than Slither, and is selected merely because infeasible
  Osiris opened search. Smartcheck must remain rejected and the checked plan
  must stay Slither-only.
- Weighted-evidence good: a passage for tool `b` explicitly links two canonical
  Stage 1 rows, CEGO sees both rows with their separate `w_D` and `s_t,D`, and
  RuleChecker resolves the same IDs from the matrix without trusting the model.
- Weighted-evidence base: a qualitative passage has no exact or explicit
  evaluation link, so it remains visible with null relevance but contributes
  zero to the support predicate.
- Weighted-evidence bad: infer a table link from similar source names, flatten
  several benchmark rows into one prompt-only weight, count the same evaluation
  repeatedly because several passages cite it, or let duplicate evidence IDs
  make ref resolution order-dependent.
- Execution good: two tools over two files run as two concurrent tool workers,
  each worker processes its two files sequentially, and plan time uses max times
  two.
- Project-input good: `Main.sol` imports `Lib.sol` and the target also contains
  one `.bin`; `file_count == 3`, `execution_input_count == 2`, the source
  staging contains `Main.sol` and `Lib.sol`, and the bytecode is dispatched once.
- Project-input base: an import cycle has no graph root, so one stable cycle
  representative is scheduled and its full closure is staged.
- Project-input bad: count `Lib.sol` as another sequential target, copy `.env`
  or unrelated source files into a container, silently omit a runtime file, or
  let an unregistered adapter pass feasibility.
- Compiler good: `^0.8.20` with installed `0.8.19` and `0.8.30` selects
  `0.8.30`; `<0.8.20` never selects `0.8.20`.
- Compiler bad: select the lowest textual version literal, widen an exact
  pragma to a newer patch, or use a representative version not installed by
  `solc-select`.
- Execution bad: native fallback runs tools serially, a timeout leaves a late
  report, return code zero without a valid report is marked success, or a key is
  embedded in `runner_command`/analyzer argv.
- Timeout good: a 30-second Smartian outer budget gives the inner fuzzer 24
  seconds while preserving six bounded lifecycle seconds and the unchanged
  outer deadline.
- Timeout base: a five-second Smartian outer budget reaches the hard boundary,
  returns `TIMEOUT/124`, promotes no report, and leaves no worker or dotnet
  process.
- Timeout bad: give Smartian the entire outer budget internally, let macOS
  `PermissionError` escape from the second group signal, add unbounded cleanup
  grace, or convert the race into `FAIL`.
- CEGO good: one valid structured proposal chooses `vandal` for one category,
  `assemble_decision` constrains it against the matrix, and RuleChecker checks
  that resulting certificate once.
- CEGO base: the proposal omits a category, so the immutable primary remains
  its sole owner for that category.
- CEGO bad: call the model three times, vote or aggregate proposals, treat a
  malformed response as an abstention, or merge citations across responses.
- Shared-compilation good: Smartian and Vandal over one Solidity project receive
  projections carrying the same bundle ID after one compiler invocation; a
  concurrently selected Slither route remains `SOURCE_ONLY`.
- Shared-compilation base: a Slither-only plan invokes zero compilers and
  records `NOT_APPLICABLE` compilation plus `SOURCE_ONLY` consumption.
- Shared-compilation bad: build a decorative bundle no adapter consumes, let
  Vandal privately compile again, mark a merely started/failed route consumed,
  or discard prior success provenance when a later cleanup returns `74`.
- Dynamic-KB good: a validated paper adds observations and a linked capability
  passage, rebuilds the matching vector index, validates the immutable
  generation, and flips one pointer.
- Dynamic-KB base: dry-run merges against the current visible generation,
  reports accepted/rejected counts, and leaves the pointer byte-identical.
- Dynamic-KB bad: accept an excerpt found in another block, guess a table row,
  create a second scene for the same dataset, expose an embedding key in argv,
  or publish one store before the others are valid.
- Provider good: one `DEEPSEEK_API_KEY` drives official DeepSeek CEGO,
  explanation, KB extraction, and GPTScan calls; SiliconFlow remains confined
  to Qwen embeddings.
- Provider base: a custom OpenAI-compatible host uses an explicit
  `OPENAI_API_KEY`, base, and model without receiving either provider-specific
  key.
- Provider bad: send a SiliconFlow key to DeepSeek, send a DeepSeek key to a
  custom host, or silently use the embedding endpoint for chat completion.
- Securify good: an existing exact image tag is confirmed and reused, then the
  analyzer runs through direct Docker without rebuilding or prompting.
- Securify base: three explicit missing-image results cause one successful
  build and cache insertion.
- Securify bad: treat a daemon error as a missing image, cache a failed build,
  pipe BuildKit output through a descendant-held stdout pipe, or prepend
  noninteractive execution with `sudo`.

### 6. Tests Required

- Stage 1: exact ranks/scores/weights, `0.2` boundaries, tie order, empty states,
  a count-only metamorphic change with identical `t*`, tolerance-sized weight
  drift acceptance, material-overflow rejection, and target/offline Gower
  parity for comments, quoted fake pragmas, OR/range pragmas, single-file import
  closure, actual-emitter fallback labeling, and AST failure.
- Profile artifact: a clean-checkout test proves the builder is available and
  deterministic; manifest/configurable-root, duplicate-corpus, safe-closure,
  atomic-write, bounded-skip, compiler-selection, count/range/digest/bandwidth,
  engine-mismatch, and legacy/mixed/stale rejection paths are asserted. A full
  rebuild replay must be byte-identical under a fixed timestamp and must retain
  the before/after weight and `t*` audit.
- Local-private snapshot: four-artifact public fallback, complete activation and
  warning, every missing-artifact failure, stale Performance/profile/passage/
  embedding prefix rejection, mismatched dataset delta, passage/vector ID and
  order mismatch, embedding dimension/provider/model mismatch, store-digest
  mismatch, explicit qualitative-only private links, explicit-`kb_root` bypass,
  private-only BM25 fallback retrieval, and Git/wheel/Docker exclusion.
- Stage 2: normalized-weight `R_hat`/`n_eff`, common-KDE-scale invariance,
  `15` boundaries, primary under-evidence,
  confirmed-zero and credible-peer cases, candidate-minus-primary Newcombe
  lower-bound boundaries, unreliable-primary fallback, infeasible-strong-peer/
  feasible-weak-candidate isolation, primary-sufficient closed slates,
  hard ineligibility, post-gate Top-5 ordering and overflow audit rows,
  missing/over-budget runtime, evidence citation, action ID,
  repair exhaustion, primary-only fallback acceptance, exact Stage 1 lineage
  projection, zero/one/many passage links, invalid/cross-tool explicit links,
  duplicate evidence IDs, JSON round-trip, symmetric applicability, weighted
  positive/negative conflicts, and model-supplied weight tampering.
- Retrieval/matrix: every category-primary/feasible-candidate action cell,
  deterministic BM25 ranking, BM25+dense reciprocal-rank fusion, missing-key/
  missing-index/query-failure diagnostics, lexical fallback preservation,
  complete typed row coverage, one byte-equivalent top-level Stage 1 lineage,
  compact legal-candidate projections without nested lineage, and a
  full-category prompt-size regression bound.
- Stage 3: ordered additive plan, max-times-file-count runtime, jobs boundary,
  owner filtering, shared-location provenance/conflicts, distinct locationless
  findings, timeout availability, measured per-tool runtime aggregation,
  generic/SARIF and SmartBugs-post-enrichment verbatim-finding round trips
  (including analyzer-owned `raw` keys and arbitrary nested fields), separation
  of tool-native raw artifacts from the accepted embedded-object boundary,
  empty required and observed category views, owner/status parity,
  ignored/non-owner exclusion, valid LLM explanation provenance, every typed
  fallback reason, one-paragraph/schema rejection, plan immutability, and secret
  absence from explanation prompts/reports.
- Cross-layer: trace one fixture through packet → context → matrix → certificate
  → checker → composition → fusion and assert the same primary/owner sets.
- CLI: render every nullable boundary and `PipelineStatus`, including
  `EXECUTED_PARTIAL`, without legacy fields.
- Release packaging: build a fresh wheel and assert every default ToolCard/KB
  JSON plus the vector index is present and resolves through the CLI default;
  build or inspect a fresh pinned Docker context that excludes local Smartian
  output, compiles the tracked project, and contains a runnable Smartian DLL
  without a host path. On ARM, assert the final image architecture, native
  `.NET --info`, `solc --version`, architecture-specific Z3/Falcon imports,
  bundled profile count/bandwidth, and a short real Smartian run over a
  compatible Solidity contract. `docker build --check .` must report no
  Dockerfile warnings.
- Provider configuration: assert official DeepSeek base/model defaults,
  host-aware key precedence, no cross-provider fallback for custom hosts,
  GPTScan inheritance/override precedence, sanitized generic workers, and
  secret absence from requests, argv, output, and serialized reports.
- Securify lifecycle: assert exact-tag reuse, three explicit-missing attempts
  before build, retry recovery, ambiguous fail-closed behavior, build-launch/
  build-result failure, cache insertion only after success, bounded build
  output replay, and a production command containing direct `docker` with no
  `sudo`.
- Runner lifecycle: same-named ancestor reports and stale current-output reports
  cannot bypass analyzer invocation; reports for deleted directory-target
  contracts disappear; unselected tool directories remain untouched; fresh
  reports still normalize and fuse.
- Native fallback: selected tool directories are cleared before rerun, stale
  findings cannot be harvested, and the newly generated report is harvested.
- Runtime evidence: field precedence, finite gate, alias collision, same-source
  maximum, compiler/LOC compatibility, original-support `0.2` boundaries,
  weighted P90, no global fallback, unit/basis conversion, paper-row ownership,
  runtime/provenance schema rejection, DACE/CEGO trace, and KB seconds →
  ToolTable minutes → Stage 1 tie → Stage 2 budget.
- Runtime literature: ten atomic observations and six summaries replay exactly;
  paper identities and summary memberships are unique; bases are homogeneous;
  copied/campaign/component evidence is excluded; SMARTIAN and MANDO-HGT are
  null; VulHunter is identity-only; JSON/alias/DACE/CEGO round trips preserve
  descriptive provenance without creating raw runtime, scheduling provenance,
  tie-break input, budget eligibility, or execution-timeout input.
- Fuzz campaign runtime: all packaged fuzz modes plus a renamed synthetic card;
  mode-bound schema exclusivity; missing/qualified/campaign-cap history;
  default, explicit, zero, unresolved, inconsistent, and over-budget
  allocations; Stage 1 non-interference; shared Stage 2/Checker/composition
  projection; static explicit-timeout preservation; concurrent maximum and
  sequential-input multiplication; separate DACE/CEGO labels/sources; exact
  normal/native outer-timeout propagation; Smartian lifecycle reserve; and
  sub-second typed-timeout behavior without outer-deadline extension.
- Execution boundary: normal/native result matrices for nonzero, timeout,
  semantic skip/failure, missing, malformed, wrong-shape, valid-empty, and
  valid-findings reports; failure-only aggregation; process-group descendant
  kill; startup-inclusive absolute deadline and early child exit; no late
  promotion; two-tool/two-input ordering; delete-or-quarantine and double-
  failure `74`; no fallback harvest; POSIX `PermissionError` during TERM/KILL;
  bounded reap/drain; Smartian exact outer-deadline propagation and small-budget
  typed timeout.
- Input/adapter boundary: canonical category aliases in scores and counts;
  import roots, cycles, quoted fake imports, dependency-closure staging, secret/
  unrelated/symlink exclusion; creation/runtime normalization; mixed targets;
  registered capability intersection; Slither SmartBugs-only dispatch;
  packaged-image presence of the Smartian runner, DLL, and `.NET`; container-
  local `/work` resolution without a host bind mount; exact, range, OR, and
  disjoint pragmas; installed-compiler selection for every compiler-dependent
  special adapter.
- Secret boundary: sentinel absent from serialized plans/results, persisted raw/
  fused reports, OS argv, logs, and generic adapter environments, while GPTScan
  receives it only through the private wrapper boundary.
- CEGO proposal: exactly one call per round at temperature zero, direct strict
  `CegoProposal` validation and assembly, explicit request/schema `CegoError`,
  no application sampling/voting/abstention/aggregation, one Checker call per
  certificate, and one fresh request for each bounded repair round.
- Shared compilation: zero compiler calls for source-only and bytecode/runtime
  plans; one call for Smartian+Vandal; exact pragma/ToolCard/compiler
  intersection; minimal components; stable digests; ambiguous/missing/malformed/
  timeout failures before dispatch; runner/native bundle-ID parity; source-only
  provenance; exact-route success-only consumption; failure/timeout/NOT_RUN/
  cleanup false; mixed-success `74` preservation; top-level/per-tool equality.
- Dynamic KB: MinerU command/output discovery; strict two-channel schema;
  block-local and table-cell provenance; normalization and numeric/count/unit
  gates; stable observation IDs and exact observation links; duplicate-dataset
  scene identity; Stage 1-ineligible rows; current-lineage projection; complete
  generation digests/counts/vector binding; pointer-once reads; dry-run current-
  generation semantics; pre/post-flip rollback and recovery; all-rejected/no-op
  behavior; CLI help; and secret absence from process argv.

### 7. Wrong vs Correct

#### Wrong: infer consistency from partial file existence

```python
if private_performance.exists() and private_profiles.exists():
    return private_performance, private_profiles  # RAG silently stays public
```

#### Correct: validate one exact public extension

```python
snapshot = resolve_static_toolcard_snapshot(toolcards_dir)
# The resolver validates all four production artifacts, exact public prefixes,
# matching Performance/profile deltas, vector order/dimensions, store digest,
# and explicitly qualitative private-only passages before return.
kb = load_performance_db(snapshot.performance_db_path)
profiles = load_profiles(snapshot.contract_profiles_path)
passages = load_passage_store(snapshot.passage_store_path)
index = VectorIndex.load(snapshot.vector_index_path)
```

#### Wrong

```python
# Category counts silently decide or replace the Stage 1 primary.
primary = max(tools, key=lambda tool: category_detected[tool] / category_total[tool])
owners[category] = [complement]
runtime = sum(runtime_by_tool.get(tool, 0) for tool in selected)
```

#### Correct

```python
selection = select_primary(scene_pool, score_panel, tool_table, tau=0.2)
owners[category] = [selection.primary_tool]
if complement_is_eligible:
    owners[category].append(complement)
runtime = parallel_runtime_minutes(selected, tool_table)  # max or None
```

#### Wrong: reconstruct raw output or let explanation control execution

```python
finding.raw = {
    "category": normalized.category,
    "location": normalized.location,
    "severity": normalized.severity,
}
composition = model_response["selected_tools"]
```

#### Correct: define the accepted boundary, then separate verbatim data,
normalized index, and non-controlling prose

```python
converted = smartbugs_convert(tool_native_output)
accepted = _enrich_report_with_categories(converted, tool, mapping)["findings"][0]
projection = {
    PARSER_PROJECTION_MARKER: True,
    "category": normalize_category(accepted),
    "location": derive_location(accepted),
    "raw": deepcopy(accepted),
}
certificate = checked_certificate  # immutable before explanation
explanation = generate_combination_explanation(
    client=client,
    model=model,
    certificate=certificate,
    checker_verdict=verdict,
    matrix=matrix,
    checker_enabled=True,
)
execute(composition_from_certificate(certificate))
```

#### Wrong: any positive complement, or strength borrowed from another peer

```python
search_required = any(peer.rate > primary.rate for peer in peers)
eligible = candidate.rate > 0 and candidate.n_eff >= 15
```

#### Correct: candidate-specific strength shared by every Stage 2 layer

```python
strength = complement_strength_against_primary(
    candidate_rate=candidate.R_hat,
    candidate_n_eff=candidate.n_eff,
    primary_rate=primary.R_hat if primary else None,
    primary_n_eff=primary.n_eff if primary else None,
)
eligible = (
    strength.evidence_stronger
    and candidate.feasible
    and runtime_within_budget(candidate)
    and not applicable_hard_blocks(candidate)
)
# Ownership construction and RuleChecker recompute/compare this same result.
```

#### Wrong: prompt-owned or model-owned evidence weights

```python
payload["weight"] = fuzzy_match(passage.source_id, dataset_names)
positive = sum(model_response.get("weights", []))
```

#### Correct: matrix-owned weighted lineage

```python
evaluation_id = stage1_evaluation_id(tool, benchmark_id)
card.linked_evaluation_ids = [evaluation_id]
positive, negative = checker_balance(matrix, cited_refs)  # resolves canonical w_D rows
```

#### Wrong: independent or cross-engine Gower profiles

```python
target = {"solc": bucket(features.primary_solidity_version), "loc": raw_loc}
benchmarks = load_profiles("source_scanner_v1.json")  # target uses AST metrics
```

#### Correct: one extractor and a compatible artifact

```python
named_sources = safe_import_closure(entrypoint, project_root)
profile = profile_sources(named_sources)  # first successful canonical emitter
features.gower_solc_bucket = profile["solc"]
features.loc_total = profile["loc"]
assert profile_artifact.meta.engine == CANONICAL_PROFILE_ENGINE
assert profile_artifact.meta.profiles_digest == profiles_digest(profile_artifact.datasets)
```

#### Wrong: runtime from a ToolCard or untyped conversion

```python
runtime_minutes = card.d1_metrics["default"].time_sec / 60
runtime_minutes = runtime_minutes / 60  # downstream guesses the unit again
```

#### Correct: one Performance-KB-owned runtime boundary

```python
tool_table = build_tool_table(cards, features, budget, kb, scene_pool)
runtime_minutes = tool_table_by_id[tool_id].tool_cost.expected_runtime_minutes
# RuntimeEstimateProvenance proves which KB seconds row produced this value.
```

#### Wrong: derived literature mean masquerades as a raw scheduling row

```python
observation.metrics.execution_time_avg = literature_summary.mean_seconds
tool_cost.expected_runtime_minutes = literature_summary.mean_seconds / 60
```

#### Correct: preserve the derived summary as descriptive provenance only

```python
assessment.descriptive_literature_summaries = [literature_summary]
assert literature_summary.scheduling_eligible is False
assert tool_cost.expected_runtime_minutes is None
assert tool_cost.runtime_provenance is None
```

#### Wrong: unrelated runtime and unconditional report promotion

```python
runtime = max(all_historical_rows)
copytree(attempt_dir, final_dir)  # before return-code/report validation
```

#### Correct: qualified runtime and validated fresh promotion

```python
runtime = weighted_p90(compatible_rows) if original_support >= 0.2 else None
if return_code == 0 and find_valid_report(attempt_dir):
    promote_valid_report_tree(attempt_dir, final_dir, quarantine_root=run_quarantine)
```

#### Wrong: report reuse in production

```python
if find_cached_report(contract_path):
    return SUCCESS
```

#### Correct: consume only the current invocation

```python
remove_selected_tool_output(tool_id)
out_dir = recreate_invocation_output(tool_id, contract_path)
return_code = run_analyzer(tool_id, contract_path, out_dir)
result = find_result_json(out_dir) if return_code == 0 else None
```

#### Wrong: estimate imported dependencies as independent analyzer targets

```python
schedule.contract_count = features.file_count
for source in project.rglob("*.sol"):
    run_analyzer(source)
```

#### Correct: share one typed input decomposition between planning and execution

```python
features.execution_input_count = (
    len(source_entrypoints(sol_files, root))
    + len(bytecode_inputs)
    + len(runtime_inputs)
)
schedule.contract_count = max(1, features.execution_input_count)
stage_only(entrypoint, dependency_closure(entrypoint, root))
```

#### Wrong: application-level CEGO sampling and voting

```python
responses = [call_cego(temperature=0.0) for _ in range(3)]
proposal = majority_vote(responses)
verdict = check_decision(assemble_decision(proposal), context, matrix)
```

#### Correct: one proposal, then one checked certificate

```python
proposal = CegoProposal.model_validate(call_cego(temperature=0.0))
certificate = assemble_decision(proposal.model_dump(), context, matrix, budget)
verdict = check_decision(certificate, context, matrix)
# A fresh single request occurs only if this verdict is rejected.
```

#### Wrong: decorative/private compilation

```python
bundle = compile_project(target)       # even for source-only tools
smartian.compile_again(target)
vandal.compile_again(target)
```

#### Correct: one conditional, validated bundle

```python
bundle = build_compilation_bundle(target, selected, selected_tool_solc_ranges=ranges)
validate_compilation_bundle(bundle, target, selected)
if bundle.manifest.status == CompilationStatus.READY:
    dispatch_all(selected, compilation_bundle=bundle)
```

#### Wrong: give an internally timed analyzer the full outer deadline

```python
smartian_fuzz_seconds = schedule.tool_timeout_seconds
os.killpg(proc.pid, signal.SIGKILL)  # PermissionError escapes
consumed = route_exists
```

#### Correct: reserve bounded lifecycle time and derive provenance from success

```python
smartian_fuzz_seconds = max(1, math.floor(outer_timeout_seconds - 6))
result = run_process_with_deadline(command, timeout_seconds=outer_timeout_seconds)
consumed = any(
    invocation.returncode == 0 and invocation.valid_report
    for invocation in exact_shared_source_routes
)
```

#### Wrong: independent KB writes or guessed provenance

```python
performance_path.write_text(new_performance)
passage_path.write_text(new_passages)
linked_evaluation_id = stage1_evaluation_id(tool, guessed_dataset)
```

#### Correct: validate one immutable generation and project links at runtime

```python
publish_generation(
    kb_root=root,
    performance_kb=performance,
    passage_store=passages,
    vector_index=index,
    rejects=rejects,
    old_pointer_bytes=current_pointer,
    created_at=created_at,
    run_id=run_id,
)
linked_ids = project_performance_observation_links(current_lineage, passage)
```

#### Wrong: emulate the complete outer runtime on Apple Silicon

```dockerfile
ARG LAKES_IMAGE_PLATFORM=linux/amd64
FROM --platform=${LAKES_IMAGE_PLATFORM} mcr.microsoft.com/dotnet/sdk:8.0
RUN dotnet build Smartian.fsproj
```

#### Correct: keep .NET native and cross-target only the Smartian output

```dockerfile
ARG LAKES_IMAGE_PLATFORM=$BUILDPLATFORM
FROM --platform=$BUILDPLATFORM mcr.microsoft.com/dotnet/sdk:8.0 AS smartian-builder
RUN dotnet build Smartian.fsproj --runtime "${smartian_runtime}"
FROM --platform=${LAKES_IMAGE_PLATFORM} python:3.10-slim-bookworm
# ARM only: add amd64 and install libc6:amd64 + libstdc++6:amd64 for official solc.
COPY --from=smartian-builder /work/docker/vendor/smartian/build/ /work/docker/vendor/smartian/build/
```

#### Wrong: mix chat providers or guess that Docker inspect failure means missing

```python
api_key = os.getenv("SILICONFLOW_API_KEY") or os.getenv("DEEPSEEK_API_KEY")
subprocess.run(["sudo", "docker", "image", "inspect", image])
build_image()  # any non-zero inspect result
```

#### Correct: bind credentials to the resolved host and fail closed on ambiguity

```python
api_key = resolve_api_key_from_env(base_url)
state = _inspect_docker_image(image)
if state == "missing":
    build_image_once()
elif state == "error":
    return typed_failure
run_direct_docker_without_sudo()
```
