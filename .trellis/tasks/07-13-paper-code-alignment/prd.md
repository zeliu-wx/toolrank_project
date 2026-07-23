# Align implementation with paper

## Goal

Make the released LAKES implementation faithfully execute the effective, uncommented workflow in `/Users/liuze/Downloads/LAKES/main_revised.tex`, so the paper, CLI-visible trace, execution plan, and fused report describe one coherent algorithm.

## Source of Truth and Constraints

- Effective, uncommented paper prose is authoritative for observable Stage 1–3 behavior. Code may add deterministic detail where the paper is silent, provided that detail does not change or contradict the paper's workflow.
- Paper edits are not required merely to expose every code-level threshold.
- The current uncommitted `toolcards/performance_db.json` belongs to the user and must be preserved. This task must not retune its metrics or rewrite unrelated knowledge-base data. The 2026-07-14 follow-up explicitly permits additive runtime unit/basis metadata and independently sourced paper-runtime observations; all pre-existing metric and category-count edits must otherwise remain byte-for-byte unchanged.
- The alignment is a breaking pre-1.0 contract change: `screc_v1` runtime compatibility is not required.
- The scope remains one Trellis task because `screc_v2` changes a shared engine→packet→prompt→checker→execution boundary; partially migrated child deliverables would not form runnable independent releases.

## Requirements

### R1 — Direct, paper-faithful Stage 1 primary selection

The effective paper defines:

\[
t^\star=\arg\max_{t\in\mathcal T_C,\;\sum_{D\in\mathcal D_t}w_D\ge0.2}S_t
\]

and passes `(t^star, {S_t}, {s_t,D}, {w_D})` to Stage 2 (`main_revised.tex:292-309`).

- Compute benchmark relevance weights and per-benchmark Recall/Precision rank scores without requiring category count data.
- Restrict primary eligibility to the paper-defined feasible domain and comparable-metric support mass `sum(w_D) >= tau`, with `tau=0.2`.
- Choose the highest `S_t` directly as `t^star`.
- Resolve final ties by the relevance-weighted raw developer-preferred metric, then lower runtime; use a deterministic final key only when both paper tie-breakers remain equal or unavailable.
- Preserve `t^star`, `{S_t}`, `{s_t,D}`, and `{w_D}` across the Stage 1→2 boundary.
- Changing only category `detected/total` evidence must not change scene membership, Stage 1 scoring, eligibility, or `t^star`.
- If no feasible tool reaches `tau`, return `NO_PRIMARY_WITH_SUFFICIENT_SUPPORT`; do not select a below-threshold fallback or enter Stage 2.
- Empty scene evidence and no feasible tools must also return explicit deterministic Stage 1 outcomes rather than alphabetic fallbacks.

Current gaps: Stage 1 filters count-free scene neighbors (`toolrank/engine.py:995-999`), derives count-based confidence intervals inside nominal scoring (`toolrank/scene_scoring.py:41-47,87-130`), may skip rank 1 during certification (`toolrank/certification.py:45-66`), drops `{s_t,D}`, lacks the `0.2` support gate and paper tie-breaks, and gives a one-tool metric rank score of `0` instead of `phi(1,1)=1` (`toolrank/scene_scoring.py:22-31,98-138`).

### R2 — Remove Stage 1 certification semantics

The effective paper contains no primary certification state. Its only `statistical certification` wording is commented out (`main_revised.tex:190`).

- Remove count/CI sufficiency, `local_strong`, `certified_primary`, and singleton Stage 1 `candidate_set` from primary selection and the finalized public contract.
- Remove `RUN_ROBUST_SINGLE` as an end-to-end scheduling outcome.
- Stage 2 statistical evidence, including `n_eff >= 15`, must never certify, replace, reorder, or otherwise alter `t^star`.

### R3 — Stage 2 category evidence, ownership, and fallback

The paper initializes each developer-required category owner set to `{t^star}`, adds complements only when evidence and runtime checks pass, and falls back to `{t^star}` when no candidate qualifies (`main_revised.tex:336,401-425`).

- Keep `t^star` as the default owner of every developer-required category.
- Retain `detected/total`, `R_hat`, and `n_eff` exclusively as category-level Stage 2 evidence.
- Require `n_eff >= 15` as a hard eligibility threshold for a non-primary complementary tool to become a category owner.
- Treat primary `n_eff < 15` as an under-evidence diagnostic that triggers complement search; it must never revoke primary ownership.
- When the primary has count-qualified positive category evidence, require a
  complementary tool to have a statistically credible positive Recall gap over
  that primary; positive Recall alone is not evidence that the complement is
  stronger. Missing, under-evidenced, or non-positive primary evidence may
  still be complemented by a count-qualified positive candidate because no
  reliable positive primary baseline exists.
- Require accepted complements to pass the finalized cited-evidence predicate, feasibility checks, and runtime checks in addition to the `n_eff` gate.
- Missing, weak, rejected, or exhausted complement evidence must retain `t^star`; it must not produce an ownerless category or globally stop the plan.
- Ensure the action matrix and decision certificate reference the same legal primary action ID.
- Keep runtime budget out of Stage 1 scoring. If `t^star` alone exceeds the budget, Stage 2 must return `NO_EXECUTABLE_PLAN`, preserve the analytical primary, avoid substituting a lower-ranked tool, and perform no execution.

Current gaps: primary-category diagnosis and complement eligibility use inconsistent statistical rules (`toolrank/assignment_evidence.py:13-37`; `toolrank/evidence_packet.py:399-517`); current assembly can create ownerless gaps and retry exhaustion can globally stop (`toolrank/cego.py:1042-1066,1123-1133`; `toolrank/engine.py:577-645`); and `run_primary` does not match matrix ID `run_primary_<tool>` (`toolrank/dace_rag.py:581-589`; `toolrank/cego.py:1144-1155`; `toolrank/checker.py:46-59`).

### R4 — Additive Stage 3 execution and fusion

The paper models category ownership as a set containing `t^star` plus accepted complements, executes tools in parallel, and merges same-category/same-location findings while preserving provenance and inconsistent fields (`main_revised.tex:336,403,434-436`).

- Execute exactly the verified Stage 2 owner sets.
- Keep primary findings when a complement is added; complements augment rather than replace the primary.
- Merge findings sharing category and code location into one fused result with all source-tool provenance.
- Preserve conflicting severity or description values and mark the inconsistent fields instead of forcing a value.
- Validate parallel plan runtime using `max(tool runtime)`, not a sum.
- Treat an unknown runtime as unverifiable rather than zero: an unknown-runtime complement is ineligible, and an unknown-runtime primary yields `NO_EXECUTABLE_PLAN`.

Current gaps: fusion removes primary findings for complement-owned categories (`toolrank/fusion.py:21-50`), while budget accounting sums tool runtimes (`toolrank/dace_rag.py:102-109`; `toolrank/cego.py:854-881`).

### R5 — Clean `screc_v2` cross-layer contract

- Replace the certification-bearing `screc_v1` packet with a clean `screc_v2` contract.
- Do not provide a runtime compatibility facade for `screc_v1`.
- Give Stage 1 selection status, Stage 2 executability status, selected primary, score/support evidence, owner sets, and terminal reasons one typed owner each; consumers must not reconstruct these fields independently.
- Update CLI summary, JSON output, Pydantic schemas, CEGO prompts, action matrix, RuleChecker, execution adapters, and release documentation together.
- Remove certification, singleton candidate, and robust-single fields and terminology from the new contract and user-visible trace.
- Preserve unrelated toolcard, retrieval, runner, parser, and knowledge-base behavior.

Current gap: certification and robust-action concepts are required or rendered across `toolrank/schemas_v2.py:13-19,244-254,325-340` and `toolrank/cli.py:107-132`, with further consumers in the engine, evidence packet, prompts, action matrix, and checker.

### R6 — Tracked regression verification

- Make Python test sources trackable; the release branch currently ignores `tests/` and retains only cache files.
- Add focused tests for Stage 1 rank scoring, ties, comparable-metric participation, support mass below/equal/above `0.2`, count independence, empty evidence, and no eligible primary.
- Add Stage 2 tests for `n_eff` below/equal/above `15`, primary-under-evidence behavior, complement rejection, no-complement fallback, checker retry exhaustion, primary-over-budget, and unknown runtime.
- Add Stage 3 tests for additive owner sets, finding merge/provenance, inconsistent fields, timeout behavior, and `max` runtime accounting.
- Add contract tests for `screc_v2`, CLI summary/JSON output, removed legacy fields, action-ID consistency, and early terminal outcomes.
- Run focused tests, the complete tracked test suite, static checks available in the repository, and a representative CLI smoke test.

### R7 — Fresh execution only

The production runner must execute every selected analyzer for the current
target before reading and fusing its output. Historical SmartBugs reports are
not valid execution results for a new run.

- Remove automatic ancestor-directory discovery of `smartbugsout`.
- Remove environment, API, and CLI inputs that enable known-report reuse.
- Remove every pre-execution fast path that accepts an existing report instead
  of invoking the selected analyzer.
- Keep report discovery only after analyzer invocation and scope it to that
  invocation's output directory.
- Add regressions proving same-named historical reports cannot bypass execution
  and freshly produced reports are still normalized and fused.

### R8 — Performance-KB-owned runtime evidence

Historical runtime is evaluation evidence, not a ToolCard capability and not an
execution-report cache. The effective paper uses a per-tool knowledge-base
estimate for the Stage 1 runtime tie-break and the Stage 2 runtime requirement
(`main_revised.tex:309,336,351,403`).

- Source per-tool runtime values only from `toolcards/performance_db.json`.
  ToolCard `d1_metrics` must not populate the scheduling runtime.
- Interpret `time_sec`, `execution_time_avg`, and the explicit
  `execution_time_avg_average_s` fallback as seconds. Never interpret
  `execution_time_avg_total_s` as a per-run estimate.
- Match Performance-KB tool names through ToolCard ID/name aliases, preserve
  missing evidence as unknown, and convert the selected statistic to minutes
  exactly once at the `ToolTable` boundary.
- Until the Performance KB contains genuine per-tool solc/size/complexity runtime
  cells, use the Gower-KDE scene weights as a nearest-bucket proxy and a
  relevance-weighted P90 as the deterministic conservative statistic. Only
  compiler/LOC-compatible rows whose original scene support reaches `0.2` may
  participate; otherwise runtime remains unknown without a linked/global-max
  fallback.
- Preserve the selected Performance-KB source and aggregation method as typed
  provenance. DACE-RAG runtime evidence must cite that source rather than claim
  that the number originated in a ToolCard or generic Stage 1 artifact.
- Feed the same minute-valued estimate to the Stage 1 tie-break, Stage 2
  eligibility/budget checks, RuleChecker, and execution planning.

### R9 — Reliable, replayable runtime evidence

The dataset-level proxy must fail closed when the available historical rows do
not meaningfully support the target. It must not turn a negligible scene weight
into apparently complete evidence by silently renormalizing only the rows that
happen to contain runtime.

- Declare the Performance-KB runtime unit explicitly as seconds and its default
  basis as `per_contract`; reject scheduling values whose source unit or basis
  is absent or unsupported. Allow typed row-level basis overrides for
  `per_contract`, `per_kloc`, and `campaign_cap`: convert `per_kloc` using the
  target LOC, while `campaign_cap` is not a completion-time estimate and must
  remain unschedulable.
- Match runtime rows to the target compiler bucket using the source
  `dataset_profile.solc`; use target LOC-bin availability when the dataset
  exposes it, and retain Gower-KDE relevance for structural similarity.
- Require compatible runtime rows to carry at least `0.2` of the original,
  unrenormalized scene mass. Below that threshold, preserve runtime as unknown
  rather than using a weak row or unrelated global maximum as an executable
  estimate.
- Keep weighted P90 as the conservative statistic only inside the qualified
  compatible evidence set.
- Make the calculation replayable from typed provenance: target compiler/LOC
  bucket, original support mass, threshold, quantile, and every candidate's
  source, metric field, seconds, scene weight, compiler match, and LOC match.
- Preserve available sample, success, timeout, compilation-failure, and failure
  counts as runtime limitations/risk evidence. Do not invent a timeout cap,
  hardware normalization, variance, or fine-grained runtime cell when the
  Performance KB does not provide it.
- Add only locally verifiable paper runtime observations with their own source,
  dataset, unit, and basis: GPTScan `14.39 seconds/KLoC`, HoneyBadger
  `142 seconds/contract`, SAILFISH `30.79 seconds/contract`, and VulHunter
  `4.4 seconds/contract`. Do not attach them to the unrelated `smartbugsdb`
  evaluation row. SMARTIAN's one-hour campaign cap is non-schedulable metadata,
  and MANDO-HGT remains unknown because no numeric completion runtime is
  supported. A paper runtime without a compatible scene profile still remains
  unknown for scheduling.
- DACE-RAG and the CEGO payload must expose each relevant tool's minute-valued
  runtime, evidence quality/provenance, and limitations. Runtime cards must not
  disappear because they have no vulnerability category.

### R10 — Primary category evidence controls supplementation

Category statistics must decide whether Stage 2 opens complement search for a
required category; merely computing a diagnostic list is insufficient.

- Define one shared primary-category decision from Stage 2 evidence only.
- A category requires complement search when the primary row is missing,
  `R_hat` is missing or non-positive, `n_eff < 15`, or a count-qualified peer
  has a statistically credible positive recall gap over the primary.
- A count-qualified positive primary may receive a complement only when that
  same candidate is itself credibly stronger than the primary. A stronger but
  infeasible peer may explain a diagnostic gap but cannot make a weaker legal
  candidate eligible.
- Otherwise mark the primary evidence sufficient and do not expose complement
  candidates for that category to DACE-RAG, CEGO, certificate assembly, or the
  RuleChecker legal set.
- A search-required category with no eligible complement remains primary-only
  with an explicit reason. The primary is never removed or replaced.
- The typed context, ownership panel, prompt, checker, CLI/JSON trace, and tests
  must distinguish `PRIMARY_SUFFICIENT`, `SEARCH_REQUIRED`,
  `COMPLEMENT_AVAILABLE`, and `PRIMARY_ONLY_NO_COMPLEMENT` semantics without
  allowing any of them to affect Stage 1.

### R11 — Planning and execution share one runtime model

- Preserve the paper's one-contract plan formula `max(selected runtimes)` and
  require enough execution jobs to run every selected tool concurrently.
  `execution_jobs=0` means one worker per selected tool; an explicit smaller
  cap makes that composition ineligible rather than changing the paper formula.
- Multiply the one-contract estimate by the number of Solidity files because
  directory targets are executed sequentially by the production runner.
- Treat the default per-tool timeout as the runtime budget converted to
  seconds. If the user explicitly supplies a lower timeout, reject any plan
  whose selected per-tool estimate exceeds it.
- Pass the same resolved timeout through the normal runner and native SmartBugs
  fallback; no execution path may substitute a hard-coded timeout.
- Record measured per-tool runtime for the fresh execution in
  `ToolExecutionStatus.runtime_minutes`. Measured runtime is report metadata,
  not an automatic write-back into historical Performance-KB evidence.
- Name the cross-layer result as estimated plan runtime because sequential
  multi-contract targets multiply the one-contract parallel estimate.

### R12 — Stage 1 rank trace matches selection

- Assign visible `NominalToolScore.rank` with the same complete comparator used
  by `select_primary`, including lower known runtime and lexical fallback.
- The first support-qualified feasible score row must agree with `t^star`; a
  visible rank must never contradict the final tie-break result.

### R13 — Robust recommendation and execution boundaries

The 2026-07-16 runtime audit exposed concrete failures on the same Stage 1
profile -> execution -> fusion boundary. These fixes are part of the current
task and supersede the earlier out-of-scope wording for the exact files and
behaviours listed here.

- Treat normalized-weight accumulation as bounded numerical arithmetic. A
  floating-point roundoff such as `1.0000000000000002` must be normalized to
  `1.0` before constructing bounded schema fields, while materially invalid
  values must still fail validation.
- Use one canonical internal DASP taxonomy across Stage 2 owner sets, runner
  enrichment, report parsing, and fusion. Legacy short aliases such as
  `denial_service`, `unchecked_low_calls`, and `other` must normalize to
  `denial_of_service`, `unchecked_low_level_calls`, and `unknown_unknowns`.
- Analyzer non-zero exits, timeouts, skips, and semantically failed reports
  must produce typed non-success statuses without crashing the runner. A batch
  may be `PARTIAL` only when at least one invocation succeeded.
- Fresh-run cleanup must cover every selected-tool artifact that downstream
  parsing or status loading can consume, including root-level legacy report
  files and the prior status manifest. A failed current run must never fuse a
  stale finding or reuse a stale success status.
- Slither must use the same SmartBugs adapter path as the other generic tools
  for every supported Solidity version. Remove the undeclared `get_src`
  execution branch.
- Source-directory execution must preserve the project/import tree instead of
  treating imported `.sol` files as unrelated standalone contracts. Bytecode
  and runtime-bytecode targets accepted by feasibility must be dispatched by
  the runner rather than rejected as "no .sol files"; mixed targets must not
  silently ignore their non-source inputs. Planning must count the same source
  entrypoints plus bytecode/runtime inputs that execution dispatches, not raw
  imported source files.
- Parse Solidity pragmas as constraints, not as unordered version literals.
  The representative target/compiler version must satisfy the target's
  constraint intersection, must never select an excluded upper bound, and an
  unsatisfiable multi-file intersection must fail closed.

### R14 — One canonical Gower profile definition

The target contract and every offline benchmark sample must be measured with
the same feature definition before Gower distance is computed.

- Give Solidity source profiling one shared owner for effective LOC, compiler
  bucket, and the five AST-derived complexity dimensions.
- Make runtime target analysis and the offline contract-profile builder consume
  that shared profile instead of reconstructing LOC or compiler semantics.
- Comments and quoted text must not increase effective LOC or create pragma
  versions.
- OR/range pragmas must produce the same compiler bucket through both paths.
- AST extraction uses one fixed, documented patch compiler per supported
  major/minor bucket. Constrained sources try only intersecting buckets in the
  declared order; no-pragma sources use their own declared order. If the first
  candidate cannot parse the source, later compatible buckets may be tried and
  the compiler that actually emits the AST determines the Gower bucket.
  Rewriting is limited to the profiling copy of the pragma.
  This substitution is profiling-only: the exact source constraint and
  `primary_solidity_version` remain authoritative for feasibility and
  execution.
- A target whose AST profile cannot be produced must not be compared against an
  AST benchmark artifact by silently substituting zero complexity values.

### R15 — Rebuild and publish one traceable AST profile artifact

The shipped benchmark profiles, numeric ranges, and KDE bandwidth must be
regenerated together from the canonical AST extractor. The resulting artifact
is allowed to change scene weights and `t^star`; preserving legacy output is not
an objective.

- Put the builder and its dataset manifest in tracked, installable project
  code. Dataset locations must be supplied by a configurable root rather than
  embedded as one developer's absolute paths.
- Include only datasets that can participate in the Performance-KB scene.
  Detect duplicate physical roots or identical corpora before fitting; the
  SmartBugs corpus must contribute scene mass once rather than once per alias.
- For every configured dataset, record attempted, succeeded, and skipped sample
  counts plus bounded failure reasons. Missing roots, duplicate corpora, and
  silent sample loss are build failures unless explicitly represented by the
  manifest policy and artifact metadata.
- Derive `_ranges` from exactly the emitted AST samples and fit `_bandwidth`
  from exactly those same normalized samples. Do not carry either value over
  from `source_scanner_v1` or from an artifact with a different sample set.
- Record extractor version, canonical profiling compilers and selection orders,
  manifest/source digests, corpus counts, skip summary, ranges, bandwidth
  seed/search grid, and generation timestamp in `_meta`. Write the output
  atomically.
- The runtime loader must validate the engine/schema and numerical shape before
  computing Gower distance. Legacy, mixed-engine, malformed, empty, or stale
  artifacts fail closed.
- Produce a deterministic before/after audit for benchmark membership, sample
  counts, ranges, bandwidth, representative scene weights, and `t^star`. A
  change is reported rather than normalized away.

### R16 — Preserve weighted evidence lineage through CEGO and RuleChecker

Stage 2 must not reduce Stage 1 evidence to an unweighted prose summary. The
paper passes `(t^star, {S_t}, {s_t,D}, {w_D})` into Stage 2 and requires the
category-level decision to retain links between capability passages and their
quantitative evaluation rows (`main_revised.tex:309,341,351-355,377`).

- Define one typed cross-layer representation for Stage 1 score evidence and
  benchmark-linked evidence lineage. Do not reconstruct these fields only in
  the CEGO prompt.
- Expose `S_t` for the primary and every legal candidate, together with the
  relevant per-benchmark `s_t,D`, normalized `w_D`, raw Recall/Precision rows,
  source/dataset identifiers, and linked capability-passage identifiers.
- Preserve one-to-many links. If a passage is linked to multiple evaluation
  rows, retain every row and its own `w_D`/`s_t,D`; do not collapse the links
  into an opaque prompt-only scalar.
- Evidence without a benchmark/evaluation link remains explicitly qualitative
  with a null benchmark relevance weight. Never invent `w_D` for an unlinked
  passage.
- Make the CEGO payload carry the typed Stage 1 evidence and each candidate's
  cited evidence lineage so the model can distinguish target-relevant evidence
  from generic capability prose.
- Make RuleChecker deterministically recompute the applicable relevance-
  weighted positive-versus-negative support predicate from the same typed
  evidence. The model may explain weights but may not supply or override them.
- Applicable `owner_ineligible` evidence remains a hard rejection. Positive
  and negative evidence must use the same applicability rule; non-applicable
  evidence and unweighted qualitative prose cannot independently qualify a
  complement.
- Add cross-layer regressions proving all values survive Stage 1 packet ->
  Stage 2 matrix -> CEGO JSON -> RuleChecker without changing `t^star`.

### R17 — Low-temperature CEGO majority voting

Every CEGO generation attempt must implement the paper's `k`-sample majority
vote before deterministic certificate assembly and RuleChecker validation.

- Use one code-owned odd sample count, initially `k=3`, and the existing
  low-temperature structured-output boundary. One logical CEGO attempt must
  collect three independent model responses to the same prompt and checker
  feedback.
- Canonicalize each response into per-category ballots. A ballot is either one
  exact complement tool ID or an explicit primary-only choice. A complement is
  retained only when the same tool receives a strict majority; a tie,
  disagreement, or majority primary-only vote retains the primary.
- Malformed/failed model responses abstain and never lower the fixed two-vote
  threshold or count as a model choice. If all three samples are unusable,
  raise `CegoError`; otherwise a category without two matching valid votes
  remains primary-only.
- Majority aggregation may select only model-emitted tools and citations. For
  a winning tool, it takes the deterministic sorted union of references from
  samples that voted for that tool; it may not borrow losing-tool references,
  invent references, or pre-filter invalid references before the independent
  RuleChecker sees them.
- Every bounded repair iteration performs a fresh `k`-sample vote using the
  previous RuleChecker reasons. Only the aggregated certificate is accepted,
  and the final plan must still pass the unchanged RuleChecker.

### R18 — One shared Stage 3 compilation boundary

For each Solidity source project containing at least one declared
artifact-aware selected adapter, LAKES must create one auditable compilation
bundle before launching the selected tools in parallel. A source-only plan
skips decorative compilation and records `NOT_APPLICABLE`.

- Select one installed compiler satisfying the complete project pragma
  intersection and selected-tool ranges. Invoke that exact binary once over
  the stable union of safe dependency closures. Request only components with a
  real consumer: Smartian needs ABI plus creation bytecode and Vandal needs
  runtime bytecode. Retain exact compiler/settings/source digests and raw
  standard-JSON provenance in a typed manifest; do not advertise an AST until
  an adapter can consume its exact format.
- The canonical first-wave policy uses optimizer disabled, no via-IR, and the
  compiler-default EVM target. This replaces Smartian's prior private optimized
  compile so Smartian and Vandal can consume bit-identical projections; every
  setting is digest-bound and visible in provenance.
- Build one bundle outside per-tool workers and pass the same immutable bundle
  identity to both packaged-runner and native-fallback paths. Existing
  bytecode/runtime inputs are already compiled inputs and must not trigger a
  Solidity compilation or be overwritten by a source-derived projection.
- Every adapter declares its real artifact-consumption mode. LAKES-owned
  source-to-bytecode conversions, including Vandal and Smartian, must consume
  the shared bundle and may not invoke `solc` again. Source-only upstream
  analyzers may continue to receive the safe source project when their public
  interface cannot consume standard artifacts, but that limitation and any
  analyzer-internal compilation must be recorded explicitly rather than being
  reported as shared-artifact consumption.
- When a bundle is required, a missing compiler, incompatible version,
  malformed/error output, ambiguous deployable contract, missing requested
  artifact, timeout, or source-digest mismatch fails preflight before any
  analyzer worker starts. Failed compilation cannot harvest or fuse stale
  reports; tool statuses remain `NOT_RUN` with the compilation reason.
- Execution results expose compilation provenance and per-tool consumption so
  a run can prove which tools consumed the shared ABI/bytecode/AST and which
  were constrained by a source-only upstream interface.

### R19 — Runnable dynamic knowledge-base update pipeline

Implement the paper's Extract -> Map & Check -> Commit flow as an explicit CLI
and importable service. Tests use injected local fakes; production uses MinerU
and the configured OpenAI-compatible endpoint and fails clearly when either is
unavailable.

- Extract accepts a local PDF, converts it to structured Markdown through the
  MinerU CLI, and submits a fixed low-temperature two-channel schema to the
  LLM. The dataset channel emits benchmark profiles, overall/category metrics,
  counts, and runtime with units/basis. The capability channel emits atomic
  owner-oriented claims, comparisons, limitations, applicability, and concrete
  source locators/excerpts.
- Map & Check canonicalizes known tool aliases, DASP categories, relation
  labels, action scopes, applicability tags, runtime units, and rate/count
  representations. It applies the existing Pydantic schemas and numeric gates,
  requires every accepted item to cite text/table evidence in the converted
  document, and records a bounded reason for every rejected item.
- Dataset identity remains the single Gower/KDE scene identity even when a new
  paper contributes fresher tool observations. New observations retain their
  own paper/locator provenance and must not duplicate benchmark weight merely
  because several papers evaluate the same dataset.
- When accepted capability and category-metric evidence share the same paper,
  canonical tool, and canonical category, persist a stable performance-
  observation link. Stage 1 evaluation IDs are run-derived: project a
  persistent observation link to an evaluation ID only when that exact row
  occurs in the current Stage 1 lineage. Do not guess IDs, fuzzy-link similar
  source names, or link an overall metric that lacks category evidence.
- Stage the merged Performance KB, PassageStore, synchronized retrieval index,
  generation manifest, and reject log, validate their round trip, then publish
  one immutable generation by atomically swapping a single current-generation
  pointer. Readers resolve that pointer once for both stores. Any extraction,
  validation, indexing, or publish failure leaves the visible generation
  byte-for-byte unchanged.
- Do not rewrite the packaged knowledge bases merely by adding this feature.
  Repository tests operate only on temporary stores and make no network,
  MinerU, compiler-download, or analyzer call.

### R20 — Auditable final report with plan explanation and verbatim findings

The persisted Stage 3 report is the user-facing result, not merely an internal
normalized fusion index.

- Add one non-empty paragraph explaining why the checked tool combination was
  selected. When an LLM endpoint is available, generate this paragraph from
  the immutable Stage 1 primary, checked Stage 2 certificate, category evidence,
  runtime constraints, and cited matrix evidence. Record whether the text came
  from the LLM or a deterministic fallback, plus the model when applicable; a
  fallback must never be presented as model-generated prose.
- The explanation may justify tool roles and evidence limitations but must not
  infer that the target contains or lacks a vulnerability, override Checker
  decisions, change the selected plan, or treat an empty finding set as safety.
- Keep model prose qualitative. Statistical audit fields and values, ambiguous
  rate language, unselected tool names, and inferred rejection causes remain in
  machine evidence rather than the paragraph; reject non-conforming prose with
  a truthfully labelled deterministic fallback instead of rewriting it.
- Persist category-oriented results. Include every requested owner category,
  even when it has zero findings, plus every additional canonical category
  reported by the primary. Under each category, group findings by source tool.
- Preserve each accepted tool finding as the exact JSON object extracted from
  the accepted current-run `result.json`. For SmartBugs-backed tools, this
  boundary is deliberately after SmartBugs conversion and after LAKES adds
  `raw_name`, canonical `category`, and `ignored` when applicable. From that
  boundary onward, normalized category/location/severity fields may coexist as
  an index, but must never replace, rewrite, flatten, or inject fields into the
  verbatim object. Tool-native tar/SARIF remains separately auditable under the
  raw run artifacts and need not be embedded in each category result.
- Keep the existing additive fused view for cross-tool de-duplication and
  conflict inspection. The new category/tool view is additive and backward-
  compatible; raw report envelopes remain under `raw/<tool>/`.
- Continue excluding analyzer findings marked `ignored`/`IGNORE`; preserving
  an accepted finding verbatim does not make ignored informational findings
  actionable.

### R21 — Auditable cross-paper runtime summaries for tools with missing estimates

The Performance KB must retain the literature evidence gathered for packaged
tools whose target-compatible runtime remains unknown, without turning a
cross-paper arithmetic mean into a fabricated target-scene observation.

- Review approximately five primary or independent empirical evaluation works
  per affected tool when the literature permits. Record fewer honestly when no
  additional independent runtime evidence exists; never pad the corpus with
  reviews, copied baseline tables, citation-only papers, plot guesses, or a
  derivative tool's timing.
- Store every accepted paper-level runtime as an atomic, independently
  identified observation with tool identity, paper metadata, source URL,
  exact locator, reported value/unit/basis, normalization, denominator and
  timeout/failure metadata when available, and explicit limitations.
- Compute one unweighted arithmetic mean only across independent paper-level
  means with the same supported runtime basis. Keep `per_contract` and
  `per_kloc` summaries separate; never relabel `per_project`, `per_case`,
  contract-group, component-only, throughput, timeout, or campaign-cap values.
- Persist the mean as a typed derived summary that names every constituent
  observation, `n`, formula, precision, inclusion policy, exclusions, and
  limitations. A one-paper identity summary must state that it is not a
  cross-paper average. No usable observations produces `null`, never zero.
- Record the verified summaries exactly: GPTScan `21.845 seconds/KLoC` from
  two comparable papers; HoneyBadger `78.57 seconds/contract` from four;
  SAILFISH `23.6766667 seconds/contract` from three; and VulHunter
  `4.4 seconds/contract` as a one-source identity summary. SMARTIAN and
  MANDO-HGT remain `null` because no reviewed paper reports an admissible
  end-to-end completion mean.
- Keep derived literature summaries separate from the recognized raw runtime
  fields (`time_sec`, `execution_time_avg`, and
  `execution_time_avg_average_s`). They may be shown as descriptive evidence
  in DACE/CEGO provenance, but must not satisfy compiler/LOC compatibility,
  the `0.2` support gate, Stage 1 runtime tie-breaking, Stage 2 budgets, or
  execution timeouts.
- Validate all arithmetic from the constituent records and add regressions
  proving that incompatible bases and copied/unsupported observations cannot
  enter a summary or silently become schedulable.

### R22 — Budget-driven fuzz campaigns

Fuzzers do not have a natural completion time that can be inferred from an
historical mean. Their campaign duration is controlled by the developer's
budget. The current packaged fuzz tools are ConFuzzius, sFuzz, and Smartian,
but the policy must be selected from `ToolCard.d8_mode == "fuzz"`, not a
hard-coded name list.

- Keep historical Performance-KB runtime rows, paper campaign caps, and
  literature summaries as descriptive evidence for fuzz tools. They must not
  become a fabricated completion-time estimate, populate
  `expected_runtime_minutes`, or gate Stage 1 eligibility/selection.
- Add one typed fuzz-campaign allocation owned by `ToolCostEntry`. It must
  state that the value is a user-controlled campaign duration rather than a
  completion estimate and retain the resolved per-input seconds and timeout
  source.
- For the default schedule, allocate the full per-tool timeout derived from
  the user's runtime budget to every selected fuzz tool. A user-supplied
  explicit timeout becomes that fuzzer's campaign duration rather than a
  reason to reject the fuzzer for being shorter than historical runtime.
- Stage 2, complement eligibility, RuleChecker, certificate budget accounting,
  and composition planning must consume one shared planning-runtime accessor:
  fuzz campaign allocation for fuzz tools and qualified historical completion
  time for non-fuzz tools. Missing historical runtime must therefore never
  make a fuzz primary or complement ineligible.
- Preserve the paper's parallel/sequential formula. Fuzz tools selected for one
  input receive the same full campaign allocation and run concurrently, so the
  plan uses their maximum rather than summing them. Directory inputs remain
  sequential, so the per-input campaign allocation is multiplied by the
  execution-input count and must still fit the overall plan budget.
- Pass the same resolved campaign seconds to both production execution paths.
  ConFuzzius and sFuzz receive it through SmartBugs `$TIMEOUT`; Smartian derives
  its inner fuzz duration while retaining the bounded report-shutdown reserve.
  The outer deadline is the hard user boundary and must never be silently
  extended, including for very small budgets.
- Expose historical runtime evidence and the separate campaign allocation in
  DACE/CEGO with unambiguous labels. The model may explain the allocation but
  cannot replace it, infer a completion time, or alter the checked plan.
- Measured Stage 3 elapsed time remains fresh report metadata and must not be
  written back as a historical completion estimate.

## Acceptance Criteria

- [x] AC1: Stage 1 selects exactly the highest-scoring feasible tool with support mass at least `0.2`, using the paper tie-break order.
- [x] AC2: Category counts cannot alter Stage 1 scene membership, scores, support mass, or `t^star`.
- [x] AC3: `{S_t}`, `{s_t,D}`, and `{w_D}` survive the Stage 1→2 typed boundary.
- [x] AC4: No certification, singleton Stage 1 candidate, or robust-single semantics remain in `screc_v2` or the default pipeline.
- [x] AC5: No support-qualified primary returns `NO_PRIMARY_WITH_SUFFICIENT_SUPPORT` and performs no later-stage work.
- [x] AC6: `n_eff < 15` can trigger primary supplementation but cannot remove `t^star` or create an ownerless category.
- [x] AC7: No valid complement, rejected LLM output, or exhausted repair loop produces a legal primary-only plan that passes RuleChecker.
- [x] AC8: Primary runtime over budget or unknown returns `NO_EXECUTABLE_PLAN`, preserves the analytical primary, and performs no execution.
- [x] AC9: Stage 3 uses additive owner sets, merges duplicate locations with provenance, marks conflicting fields, and checks parallel runtime with `max`.
- [x] AC10: CLI and JSON output emit only the documented `screc_v2` contract and terminal statuses.
- [x] AC11: New tracked regression tests cover AC1–AC10 and pass without modifying unrelated behavior or user-owned knowledge-base data.
- [x] AC12: Every production run invokes the selected analyzers and consumes only reports produced in the current run directory; no known-report cache path, option, or environment hook remains.
- [x] AC13: Scheduling runtime is resolved only from Performance-KB evidence with deterministic scene-aware conservative aggregation, typed provenance, one seconds-to-minutes conversion, and unknown preservation; ToolCard runtime values cannot affect selection or budgets.
- [x] AC14: Runtime rows are compiler/LOC compatible, retain at least `0.2` original scene support, and expose replayable candidate-level provenance; weak or incompatible evidence remains unknown.
- [x] AC15: Runtime unit and available timeout/failure/sample metadata are explicit and survive Performance KB → ToolTable → DACE/CEGO without invented values.
- [x] AC16: Primary category `R_hat`/`n_eff` and credible peer-gap evidence open or close complement search; primary-sufficient categories expose no legal complement candidate.
- [x] AC17: Plan runtime reflects execution jobs and sequential contract count, explicit timeout constraints are checked, and both execution paths receive the same resolved timeout.
- [x] AC18: Fresh execution records actual per-tool runtime without reading or mutating historical scheduling evidence.
- [x] AC19: Stage 1 visible rank and `t^star` use one comparator and cannot disagree on runtime ties.
- [x] AC20: Real normalized scene weights cannot crash bounded schema construction because of floating-point roundoff.
- [x] AC21: Canonical category aliases survive runner normalization and additive owner filtering without dropping complement findings.
- [x] AC22: Every execution outcome is typed correctly; failures/skips never crash or report `SUCCESS`, and `PARTIAL` requires at least one success.
- [x] AC23: Root-level stale reports and stale status manifests cannot enter a later failed run.
- [x] AC24: Slither always executes through SmartBugs; no `get_src` dependency or branch remains.
- [x] AC25: Multi-file source imports and supported bytecode/runtime inputs reach execution without silent decomposition or omission.
- [x] AC26: Solidity pragma constraints are intersected correctly and excluded upper bounds are never selected.
- [x] AC27: The same Solidity source produces identical Gower compiler, LOC,
  and complexity values through runtime target analysis and the offline
  benchmark-profile builder, including comment-only changes and OR pragmas.
- [x] AC28: A tracked, configurable builder regenerates all eligible benchmark
  profiles with the canonical AST engine, de-duplicates identical corpora, and
  records complete attempted/succeeded/skipped provenance without modifying
  `toolcards/performance_db.json`.
- [x] AC29: The shipped AST artifact's ranges and KDE bandwidth are fitted from
  its emitted samples, the runtime rejects incompatible artifacts or missing
  target AST profiles, and a before/after weight/`t^star` audit is retained.
- [x] AC30: `S_t`, per-benchmark `s_t,D`, normalized `w_D`, linked evaluation
  rows, and capability-passage provenance reach CEGO through typed evidence;
  RuleChecker uses the same applicable relevance weights for deterministic
  conflict resolution, while unlinked qualitative evidence remains unweighted.
- [x] AC31: Every CEGO attempt performs three low-temperature structured
  samples, accepts only a strict per-category tool majority, merges citations
  only from votes for the winner, repeats the vote on repair, and sends only
  the aggregate through RuleChecker; unusable or unresolved votes retain a
  checked primary-only plan.
- [x] AC32: When Smartian or Vandal is selected for Solidity source, Stage 3
  performs one canonical project compilation before tool workers, passes one
  digest-verified typed bundle through both execution paths, makes both
  LAKES-owned consumers use it without another `solc` call, skips decorative
  compilation for source-only plans, and records honest per-tool provenance.
- [x] AC33: A production CLI and importable service execute PDF -> MinerU
  Markdown -> two-channel LLM extraction -> normalization/provenance/schema
  checks -> stable observation/capability links -> runtime Stage 1 projection ->
  single-pointer Performance KB, PassageStore, and retrieval-index generation
  commit, with deterministic offline tests and no visible partial generation.
- [x] AC34: A fresh executed `fused_report.json` contains a provenance-labelled
  tool-combination explanation, category -> tool grouping (including empty
  required categories), exact accepted original finding JSON, and the existing
  normalized fused/conflict view; explanation or parsing failure cannot alter
  the checked plan or fabricate LLM provenance.
- [x] AC35: The Performance KB contains typed, replayable paper-level runtime
  observations and derived summaries for GPTScan, HoneyBadger, SAILFISH,
  VulHunter, SMARTIAN, and MANDO-HGT; every stored mean replays exactly from
  homogeneous independent observations, missing means remain `null`, and no
  descriptive summary can masquerade as target-compatible scheduling runtime.
- [x] AC36: Every `d8_mode=fuzz` tool is schedulable from the user-controlled
  campaign allocation without historical completion-time evidence; the same
  allocation reaches Stage 2, RuleChecker, DACE/CEGO, plan accounting, and the
  real runner while Stage 1 and historical runtime provenance remain unchanged.

## Out of Scope

- Changing the vulnerability taxonomy or adding analyzers.
- Re-extracting existing unrelated RAG passages or retuning existing benchmark
  metrics; R19 only processes explicitly supplied new papers.
- Refactoring unrelated runner, parser, UI, packaging, or knowledge-base code.
- Adding every code-level Stage 2 threshold to the paper when effective prose is merely less detailed and not contradictory.
- Runtime compatibility with serialized `screc_v1` packets.
