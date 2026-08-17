# Technical Design: Paper-aligned `screc_v2`

## Status

AC1–AC36 were implemented and independently verified before the post-audit
hardening follow-up. The design below includes AC37–AC43's normalized Stage 2
evidence, full-sample bandwidth, action-conditioned retrieval, reproducible
packaging, partial execution, explanation validation, and paper-alignment
boundaries in addition to the earlier contracts.

## Design Principles

1. **Stage isolation.** Overall benchmark metrics select the Stage 1 primary. Category counts are consumed only after `t^star` is fixed.
2. **Typed boundary ownership.** One model owns each status, primary selection, category owner set, and terminal reason. Downstream layers import these models rather than reconstructing them.
3. **Paper behavior first.** Additional code-level rules may refine an underspecified paper step, but cannot change its observable result.
4. **Deterministic fallback.** Missing complement evidence yields a primary-only plan. Missing primary evidence or an unexecutable primary yields an explicit terminal result.
5. **Surgical data handling.** Preserve the user's dirty performance database and all unrelated retrieval/runner behavior.

## End-to-End Data Flow

```text
Target + requirements
  -> contract profile + feasibility inputs
  -> all profile-backed benchmark weights w_D
  -> Performance-KB runtime estimates (scene-weighted P90, seconds -> minutes)
  -> feasible ToolTable with typed runtime provenance
  -> comparable-metric per-benchmark scores s_t,D
  -> S_t + support_mass_t
  -> PrimarySelection(t^star | terminal Stage 1 status)
  -> category evidence for required categories only
  -> primary evidence diagnostics + complement eligibility (n_eff >= 15)
  -> DACE-RAG matrix and CEGO complement proposals
  -> verified additive category owner sets
  -> primary-only fallback or executable composition
  -> parallel execution
  -> provenance-preserving additive fusion
```

An early terminal Stage 1 result does not construct Stage 2 objects. A Stage 2 `NO_EXECUTABLE_PLAN` result does not invoke CEGO, RuleChecker repair, or execution.

## Stage 1 Design

### Scene construction

- `toolrank._complexity.profile_sources` is the canonical owner of the Gower
  profile tuple `(compiler bucket, effective LOC, five complexity metrics)`.
  Runtime target analysis projects this result into `ContractFeatures`; the
  offline builder persists the same keys without independently recomputing LOC
  or compiler semantics.
- Effective LOC is counted after comment/string masking. Both paths derive the
  same allowed compiler buckets from parsed pragma intersections, including OR
  expressions. The first canonical compiler that emits a complete AST owns the
  Gower bucket. Target-only facts such as source kind, file count, import roots,
  original constraints, and exact representative compiler remain owned by
  `analyze_target`.
- AST profiling uses a fixed canonical compiler patch for each `0.4.x` through
  `0.8.x` bucket. Constrained sources try intersecting buckets oldest-first;
  no-pragma sources try `0.8.x` through `0.4.x`. A private profiling copy may
  rewrite an exact pragma to each attempted patch. The successful compiler is
  persisted, while feasibility and execution continue to use untouched source
  constraints.
- Keep every unique benchmark corpus that has a contract profile and a
  performance-KB entry. When multiple Performance-KB aliases resolve to the
  same physical corpus, choose one declared canonical scene identity instead
  of duplicating its KDE mass.
- Remove the call to `filter_scene_pool_to_count_bearing()` from Stage 1.
- Preserve normalized `SceneNeighbor.weight = w_D` as the statistical evidence
  boundary. Raw `kernel_density = p_hat_D` remains diagnostic provenance only:
  - Stage 1 scoring and support mass use normalized `w_D`.
  - Stage 2 `R_hat` and `n_eff` also use normalized `w_D`, so an arbitrary
    common kernel normalization factor cannot change category eligibility.

### AST profile artifact build

The artifact boundary is:

```text
tracked dataset manifest + configurable corpus root
  -> safe deterministic Solidity sample discovery
  -> canonical profile_sources(source/import closure)
  -> emitted per-sample AST profiles + failure ledger
  -> ranges from emitted samples
  -> deterministic full-sample LOO bandwidth search over those normalized samples
  -> atomic toolcards/contract_profiles.json
  -> strict runtime engine/schema validation
```

The manifest owns exact Performance-KB dataset names, relative corpus roots,
canonical identities, and explicit duplicate exclusions. The build rejects an
undeclared duplicate root/content digest and a missing required dataset. Every
sample keeps a stable relative ID and the profiling compiler used. Dataset and
global metadata retain attempted/succeeded/skipped counts, deterministic
compiler-selection orders, and bounded error classes so coverage can be
audited without placing thousands of raw compiler messages in the release
artifact.

The engine identifier is versioned whenever any of these change: source
masking, compiler-bucket selection, canonical compiler patches, AST traversal,
metric definitions, sample-unit/import-closure semantics, or normalization.
`scene_kde.load_profiles` validates that identifier, required dimensions,
finite ranges, positive finite bandwidth, unique sample IDs, and non-empty
eligible datasets. It never fits a replacement bandwidth at load time.

Target analysis records whether the AST tuple is available. Source facts may
still support feasibility and diagnostics after an AST failure, but
`build_scene_pool` returns no scene evidence instead of comparing source facts
plus synthetic zero metrics with AST benchmark samples.

The rebuild audit compares the legacy and rebuilt artifacts on a deterministic
fixture/target set. It reports membership, counts, ranges, bandwidth, weights,
compiler-fallback recovery, and resulting Stage 1 primary selections. It also
records a full-sample leave-one-out validation of the selected bandwidth. These
values are evidence of the migration; they are not acceptance thresholds that
force the old ranking to survive.

### Comparable-metric participation

For benchmark `D`, a tool participates in `D_t` only when both overall Recall and Precision are present and valid. The rank comparison pool for `D` is the feasible tools with both metrics on that benchmark. This avoids treating a missing metric as zero.

Metric ties receive average ranks. The paper normalization remains:

```text
phi(r, n) = (n - r + 1) / n
```

Therefore a one-tool comparison yields `phi(1, 1) = 1`.

For each participating `(tool, benchmark)` row, store:

- benchmark/source identifier;
- `w_D`;
- Recall and Precision raw values;
- Recall and Precision ranks;
- `s_t,D`.

For each tool, compute:

```text
support_mass_t = sum(w_D for D in D_t)
S_t = sum(w_D * s_t,D) / support_mass_t
```

The tool is support-qualified iff `support_mass_t >= 0.2`.

### Primary selection and ties

Select from feasible, support-qualified tools using this total order:

1. greater `S_t`;
2. greater relevance-weighted raw value of the developer-preferred metric over `D_t`;
3. lower known runtime estimate;
4. lexical tool ID only as a deterministic final tie-break.

Unknown runtime loses a tie to known runtime but does not remove a tool from Stage 1. Runtime budget never changes Stage 1 scoring or selection.

### Runtime evidence resolution

ToolCards describe analyzer identity, accepted input, compiler compatibility, and
execution mode. They do not own historical performance. Runtime estimates are
resolved from `PerformanceKnowledgeBase` only after the target scene has been
constructed:

1. Canonicalize each ToolCard's ID and display name as aliases for matching
   Performance-KB observation names.
2. Read one positive finite seconds value per observation in this order:
   `time_sec`, `execution_time_avg`, then
   `execution_time_avg_average_s`. Ignore cumulative `*_total_s` fields.
3. Collapse duplicate rows for the same `(source_id, tool)` conservatively by
   retaining the maximum seconds value.
4. Retain only compiler/LOC-compatible scene-linked rows and require their
   original normalized support mass to reach `0.2`. Then compute weighted P90;
   the selected quantile is an observed source row. Weak, incompatible, and
   unrelated evidence remains unknown without a linked/global-max fallback.
5. Convert the selected seconds value to minutes once when constructing
   `ToolCostEntry`, and carry method/source provenance with it.

The current Performance KB stores one runtime scalar per tool and dataset, not a
runtime table indexed by solc, LOC, and all five complexity dimensions. The
follow-up therefore uses a qualified dataset proxy without pretending that
missing empirical cells exist:

1. `criteria.runtime_unit` must explicitly be `seconds` and
   `criteria.runtime_basis_default` must be `per_contract`. A row may override
   the basis with `per_contract`, `per_kloc`, or `campaign_cap`. `per_kloc` is
   converted using target LOC; `campaign_cap` is retained as provenance but is
   not a schedulable completion-time estimate.
2. Candidate datasets must include the target major/minor compiler bucket.
3. When LOC-bin counts exist, retain the target LOC-bin match in provenance and
   prefer rows whose dataset contains that compiler/LOC combination.
4. Gower-KDE scene weights continue to represent structural similarity.
5. The sum of original scene weights over qualified runtime rows must be at
   least `MIN_RUNTIME_SUPPORT_MASS = 0.2`; do not normalize before this check.
6. Compute weighted P90 only after the support check. Below threshold, runtime
   is unknown and cannot satisfy a planning budget.

Typed provenance stores the target buckets, support mass and threshold,
quantile, and complete candidate rows with original scene weights. Optional
success/timeout/failure counts are preserved as limitations and risk evidence.
The old unrelated global-maximum executable fallback is removed. A future
fine-grained runtime table can replace the candidate resolver without changing
the minute-valued `ToolTable` boundary.

Verified paper runtimes are stored as distinct Performance-KB observations,
never grafted onto an unrelated benchmark row: GPTScan is `14.39 sec/KLoC`,
HoneyBadger `142 sec/contract`, SAILFISH `30.79 sec/contract`, and VulHunter
`4.4 sec/contract`. SMARTIAN's one-hour campaign cap is retained only as
non-schedulable metadata; MANDO-HGT stays numerically unknown. These rows still
need compiler/profile compatibility and `0.2` scene support before they can
produce an executable estimate.

#### Cross-paper literature summaries

The packaged Performance KB gains two typed, non-overlapping evidence layers:

```text
RuntimeLiteratureObservation:
  observation_id, tool, paper_id, title, year, venue, doi, source_url,
  evidence_locator, runtime_seconds, runtime_basis, original_value/unit,
  normalization_formula, attempted/success/timeout/failure counts,
  independent, admitted_to_summary, exclusion_reason, limitations

RuntimeLiteratureSummary:
  summary_id, tool, aggregation, runtime_basis, runtime_unit,
  constituent_observation_ids, n, formula, mean_seconds,
  cross_paper_mean, scheduling_eligible=false, limitations
```

Atomic observations preserve what each paper actually measured. Summaries are
recomputed and validated from admitted constituents rather than trusted as an
unrelated scalar. The validator requires unique independent papers, identical
supported bases, positive finite seconds, exact `n`, and an arithmetic mean
that matches the constituent values within numeric tolerance. An empty
constituent set requires `mean_seconds=null`; one constituent is an identity
summary with `cross_paper_mean=false`.

The runtime resolver continues to read scheduling candidates only from the
existing raw runtime metric fields. It attaches the literature summary to
`RuntimeEvidenceAssessment` as explicitly descriptive provenance, but never
copies `mean_seconds` into `ToolCostEntry.expected_runtime_minutes` or
`RuntimeEstimateProvenance`. This preserves the paper's matching/nearest-
compatible-bucket contract while making missing-runtime literature visible to
DACE/CEGO and machine-readable audits.

The initial summaries are basis-specific and replayable:

| Tool | Basis | Included paper means (seconds) | Derived result |
|---|---|---|---|
| GPTScan | `per_kloc` | `14.39`, `29.3` | `21.845`, `n=2` |
| HoneyBadger | `per_contract` | `142`, `98`, `72`, `2.28` | `78.57`, `n=4` |
| SAILFISH | `per_contract` | `30.79`, `10.9`, `29.34` | `23.6766667`, `n=3` |
| VulHunter | `per_contract` | `4.4` | `4.4`, `n=1`, identity only |
| SMARTIAN | — | no admissible end-to-end mean | `null`, `n=0` |
| MANDO-HGT | — | no published admissible runtime | `null`, `n=0` |

Campaign limits, component microbenchmarks, throughput, conditional time to a
bug, plot readings, copied tables, and incompatible denominator bases remain
audit records or research exclusions; none enter arithmetic constituents.

#### Budget-driven fuzz campaign runtime

Historical completion evidence and executable fuzz duration are separate
concepts. A fuzzer is an anytime campaign, so a paper's fixed cap or arithmetic
mean must not be re-labelled as time-to-completion. `build_tool_table` detects
this policy only through `ToolCard.d8_mode == "fuzz"` and attaches a typed
campaign allocation alongside, not inside, historical runtime provenance:

```text
FuzzCampaignBudget:
  method = user_budget_fuzz_campaign
  allocated_runtime_seconds = ExecutionSchedule.tool_timeout_seconds
  timeout_source = budget_default | explicit
  runtime_semantics = campaign_allocation_not_completion_estimate
```

For fuzz entries, `expected_runtime_minutes` and
`RuntimeEstimateProvenance` remain absent. `RuntimeEvidenceAssessment` may
still carry raw Performance-KB candidates and descriptive literature material,
but it has no scheduling authority. This keeps the Stage 1 runtime tie-break
truthful and prevents the developer budget from changing `t^star`.

One shared `planning_runtime_minutes(entry)` projection owns the Stage 2 and
Stage 3 cost boundary:

```text
fuzz tool     -> allocated_runtime_seconds / 60
non-fuzz tool -> expected_runtime_minutes
```

An explicit per-tool timeout is itself the developer's shorter fuzz campaign,
not a comparison against an absent historical estimate. The existing plan
formula remains `max(per-input planning runtime) * execution_input_count`.
Parallel fuzz tools each receive the full allocation; the allocation is not
split among tools. Inputs remain sequential, so a default full-budget campaign
on more than one execution input is honestly over the overall plan budget
unless the developer supplies a smaller per-input timeout.

DACE and CEGO expose `expected_runtime_minutes=null`, the descriptive
historical assessment, and the separate typed campaign allocation. The
RuleChecker and all eligibility/budget consumers import the shared planning
projection rather than reading the historical field directly.

Execution already has the required one-source timeout path. Generic SmartBugs
commands pass `ExecutionSchedule.tool_timeout_seconds` to `$TIMEOUT`, which the
ConFuzzius and sFuzz wrapper scripts convert to their internal campaign
duration. Smartian receives the same outer value and uses
`inner=max(1, floor(outer-6))`, with two bounded startup seconds and four
report-normalization seconds. The exact floating-point outer process deadline
never grows or rounds upward; small allocations may therefore produce a typed
timeout rather than a promoted report.

### `screc_v2` Stage 1 models

Introduce or reshape these models in `toolrank/schemas_v2.py`:

```text
Stage1Status =
  PRIMARY_SELECTED
  NO_SCENE_EVIDENCE
  NO_FEASIBLE_TOOL
  NO_PRIMARY_WITH_SUFFICIENT_SUPPORT

BenchmarkToolScore:
  tool, benchmark_id, weight, recall, precision,
  recall_rank, precision_rank, score

NominalToolScore:
  tool, S_scene, rank, support_mass,
  preferred_metric_value, P_scene, R_scene

ScorePanel:
  benchmark_weights, benchmark_scores, nominal_scores

PrimarySelection:
  status, primary_tool?, tau, eligible_tools, reason_codes

Stage1EvidencePacket:
  schema_version = "screc_v2"
  target_contract, tool_table, scene_pool, score_panel,
  primary_selection, provenance_index
```

Remove Stage 1 `effective_total`, Recall CI fields, `evidence_level`, and `CertificationVerdict` from this contract.

### Early result handling

`PipelineResult` gains an explicit overall status and optional later-stage fields. When Stage 1 does not select a primary, return the Stage 1 packet plus its terminal status. Do not create an action matrix, decision certificate, checker verdict, execution, or fused report.

Resolve early Stage 1 states in this order:

1. no profile-backed scene benchmark -> `NO_SCENE_EVIDENCE`;
2. scene exists but the feasible tool set is empty -> `NO_FEASIBLE_TOOL`;
3. feasible tools exist but none has comparable-metric support mass at least `0.2` -> `NO_PRIMARY_WITH_SUFFICIENT_SUPPORT`.

A scene with no comparable Recall/Precision rows therefore reaches the third state rather than selecting an alphabetic fallback.

## Stage 2 Design

### Context boundary

Build a `Stage2EvidenceContext` only after `PRIMARY_SELECTED`. It contains:

- the immutable Stage 1 packet;
- required categories from the user requirement profile;
- category Recall coverage rows;
- performance-DB evidence rows;
- primary category diagnostics;
- DACE-RAG focus and provenance.

When no required categories are supplied, Stage 2 produces a primary-only plan after runtime validation.

### Weighted evidence lineage

The Stage 1 packet is the sole source of `S_t`, `s_t,D`, and normalized `w_D`.
Stage 2 projects those values into a typed evidence-lineage structure instead
of rebuilding them inside the prompt. For every primary or legal-candidate
tool, the matrix retains its aggregate `S_t` and the participating benchmark
rows containing dataset/source identity, `w_D`, Recall, Precision, ranks, and
`s_t,D`.

Capability passages reference zero or more quantitative rows by stable IDs.
Each link preserves its own benchmark values; a passage linked to several
datasets therefore exposes several links rather than one prematurely summed
weight. A passage without a quantitative link is represented as qualitative
evidence with a null benchmark relevance weight. Applicability metadata remains
separate from provenance, and no consumer may manufacture a benchmark weight
for such a passage.

The CEGO payload consumes this typed projection and includes:

```text
stage1_evidence:
  benchmark_weights
  tools[tool_id]: S_t + benchmark_rows[]

category evidence item:
  evidence_id, stance, applicability, passage/source
  linked_evaluations[]: dataset/source + w_D + s_t,D + raw metrics
```

RuleChecker owns the arithmetic. It resolves the cited evidence IDs back to
the matrix, discards non-applicable entries symmetrically, hard-rejects any
applicable `owner_ineligible` entry, and compares applicable relevance-weighted
positive evidence with applicable relevance-weighted negative evidence. CEGO
can reason about and cite the weights but cannot emit authoritative weights.
Unlinked qualitative prose may explain a proposal but cannot independently
make a complement eligible.

### Category statistics

For category counts, use the normalized scene relevance already owned by
Stage 1:

```text
R_hat = sum(w_D * detected_D) / sum(w_D * total_D)
n_eff = sum(w_D * total_D)
```

The same normalized `w_D` is the evidence relevance shown to DACE-RAG. Raw
`p_hat_D` may be retained for KDE audit diagnostics but cannot affect the hard
`n_eff >= 15` eligibility boundary.

Complement eligibility requires all of:

- non-primary, feasible tool;
- category `R_hat > 0`;
- `n_eff >= 15`;
- a reliable primary comparison baseline and a Newcombe
  candidate-minus-primary Recall-gap interval whose lower bound is strictly
  positive;
- no hard `owner_ineligible` evidence;
- positive cited support under the existing four-slot evidence rules;
- known runtime and an executable parallel plan.

After every hard gate passes, sort legal complements by descending `R_hat`,
descending `n_eff`, then tool ID and expose at most five per category. Keep
overflow candidates as typed `NOT_SHORTLISTED` audit rows; they remain visible
but cannot enter the CEGO legal-candidate set. RuleChecker reconstructs the
canonical ownership panel from the Stage 2 context, matrix-owned evidence cards,
and matrix budget; any supplied partition that differs is rejected.

If the primary row is missing or below `n_eff = 15`, search remains useful as a
diagnostic but no candidate can be proven stronger and therefore none is a
legal complement. A count-qualified non-positive primary is a reliable zero
baseline and still requires a strictly positive lower gap bound. Feasibility
or budget failure of the peer that opened search does not relax this
candidate-level comparison.

For the primary, one shared decision classifies each required category:

```text
SEARCH_REQUIRED / under_evidenced when:
  primary row or R_hat is missing
  or n_eff is missing/below 15

SEARCH_REQUIRED / confirmed_weak when:
  n_eff >= 15 and R_hat <= 0
  or a count-qualified peer has a credible positive Newcombe gap

PRIMARY_SUFFICIENT otherwise
```

Only `SEARCH_REQUIRED` categories build a complement candidate slate.
`PRIMARY_SUFFICIENT` categories expose no complement candidate to DACE-RAG,
CEGO, assembly, or RuleChecker. Search failure still retains the primary.
These statistics never remove the primary and never flow backward into Stage 1.

The named Newcombe peer-gap comparison is a Stage 2 search gate. Other retained
CI diagnostics are explanatory only. Neither count evidence nor a peer gap may
replace the primary or flow backward into Stage 1. Every diagnostic has one
named owner and boundary tests that distinguish it from the `n_eff` hard gate.

### Additive owner contract

Replace single-owner/replacement language with additive owners:

```text
CategoryAssignment:
  category
  owner_tools: list[str]       # always begins with t^star
  complement_tool: str | None
  status: PRIMARY_ONLY | COMPLEMENT_ADDED
  evidence claims and caveats
```

CEGO returns complement proposals, not replacements. Deterministic assembly initializes every required category to `[t^star]` and appends at most one accepted complement under the current paper algorithm. Invalid or absent proposals leave the list unchanged.

### Actions, checker, and fallback

- The `screc_v2` default action space is `RUN_PRIMARY` and `PLAN_COMPOSITION`.
- Remove `RUN_ROBUST_SINGLE` and the synthetic `STOP_WITH_GAPS` fallback from the default pipeline.
- Create action IDs in one helper and look them up from the matrix during assembly; never independently hard-code the same ID in CEGO.
- RuleChecker verifies:
  - primary equals `Stage1EvidencePacket.primary_selection.primary_tool`;
  - primary is present in every required category owner set;
  - every complement passes `n_eff >= 15`, evidence, feasibility, scope, and runtime checks;
  - action ID exists and is legal;
  - no ownerless required category exists.
- After exhausted CEGO repair attempts, deterministically emit the legal primary-only action. This fallback must itself pass RuleChecker.

### CEGO single-proposal boundary

One logical CEGO generation is one structured request at `temperature=0.0`.
The request receives the typed matrix/prompt and, during repair, the previous
RuleChecker verdict. The response boundary strictly validates one
`CegoProposal`; transport or schema failure raises `CegoError`.

For each required category, the proposal either omits a complement, retaining
the immutable primary owner, or emits one exact complement tool with evidence
references. The existing assembler applies eligibility and budget constraints
to that proposal, and RuleChecker remains the only acceptance authority.
There is no sampling, ballot, voting, abstention, or cross-response citation
merge. A rejected certificate starts one fresh single-request round with the
rejection reasons.

### Runtime conflict

Compute estimated parallel runtime as the maximum known runtime among selected tools.

- Primary runtime missing or above budget -> `NO_EXECUTABLE_PLAN`, preserve the analytical primary, stop before CEGO/execution.
- Complement runtime missing -> complement is ineligible.
- Composition runtime above budget -> reject that complement proposal and retain the primary-only owner set.

`NO_EXECUTABLE_PLAN` is a Stage 2 status, not a fake executable action.

### Execution-aware plan time

`ToolCostEntry.expected_runtime_minutes` remains a per-contract historical
estimate. A shared execution-schedule contract carries:

```text
contract_count = number of .sol files executed sequentially
execution_jobs = 0 for one worker per selected tool, otherwise the explicit cap
tool_timeout_seconds = runtime budget in seconds unless explicitly overridden
```

For one contract, the scheduler retains the paper formula `max(selected
runtimes)`. A composition is legal only when the effective worker count is at
least the number of selected tools; a lower explicit `execution_jobs` cap can
therefore keep the primary executable while making a complement ineligible.
Total plan time is the one-contract maximum multiplied by `contract_count`.
Budget construction, ownership filtering, certificate, RuleChecker,
composition, CLI, and execution use this same schedule object.

The explicit timeout is also a plan constraint: any selected tool whose
per-contract estimate exceeds it is not executable. The normal runner and
native fallback receive the same resolved value. Fresh execution measures and
reports per-tool elapsed minutes but never mutates the historical KB.

### Stage 1 trace order

One shared comparator ranks nominal scores and selects `t^star`: score,
preferred raw metric, known/lower runtime, then lexical tool ID. The visible
rank is generated only after the ToolTable exists so it cannot disagree with a
runtime tie-break.

## Stage 3 Design

### Shared compilation bundle

The compilation flow precedes tool parallelism:

```text
Solidity project + stable union of safe import closures + exact compatible solc
  -> one standard-JSON compiler invocation
  -> validate source digest and complete compiler output
  -> immutable CompilationBundle + manifest
  -> parallel adapters consume source and/or declared shared artifacts
```

The bundle owns compiler version/binary digest, input/source digest, entrypoint
and fully-qualified contract identities, optimizer/via-IR/EVM settings, and the
minimal raw standard-JSON result needed by real consumers. Smartian requests
ABI plus creation bytecode; Vandal requests runtime bytecode; their union is
produced by one invocation. AST/source-map fields are not requested or claimed
until a production adapter consumes their exact format. Bundle IDs are content
digests, not temporary paths. Creation/runtime bytecode inputs skip this step
because they are already compiled artifacts.

The first-wave canonical settings are optimizer disabled, no via-IR, and the
compiler-default EVM version. This deliberately replaces Smartian's former
private optimized compile and matches Vandal's default-unoptimized path. A
settings change changes the bundle digest; adapters cannot receive different
settings while claiming one bundle.

Adapter capability metadata distinguishes three truthful outcomes:

```text
SHARED_ARTIFACT       adapter consumes declared ABI/bytecode from the bundle
SOURCE_ONLY           upstream interface consumes source and may compile internally
NOT_APPLICABLE        non-Solidity input or analyzer does not compile
```

Vandal's source conversion and Smartian's ABI/bytecode preparation are
LAKES-owned and therefore must be `SHARED_ARTIFACT`; their old private compiler
calls are removed. Source-only upstream tools retain their safe import closure
and are reported as `SOURCE_ONLY`, never as having eliminated internal
compilation. If no selected route consumes an artifact, compilation status is
`NOT_APPLICABLE` and `solc` is not called. The packaged runner and native
fallback share the same compiler, bundle validator, adapter-consumption
registry, and failure semantics.

A required Solidity compilation failure is a pre-execution failure for the
source project. No worker starts, no staged report is promoted, and selected
tool statuses remain `NOT_RUN` with the typed compiler failure. Compilation
artifacts are run-scoped and cannot be discovered as analyzer reports.

### Reliability follow-up (2026-07-16)

Normalize cross-layer values at their owning boundary:

- scene-weight sums use a small floating-point tolerance and clamp only values
  within that tolerance of `[0, 1]`;
- one shared category normalizer emits the long-form internal DASP identifiers
  consumed by `CompositionPlan.category_owners` and `fuse_reports`;
- analyzer wrappers and report validation expose semantic outcomes, not merely
  the wrapper process return code or the presence of a list-valued JSON field.

Fresh-run cleanup covers selected-tool directories, selected root-level legacy
JSON/SARIF files, and the prior `tool_run_statuses.json` before invocation.
Status loading consumes only a manifest written by the current runner. Batch
aggregation returns `PARTIAL` only for a true mixture containing at least one
successful invocation; a mixture of failures and timeouts remains unusable.

Slither has no special version branch and always uses the generic SmartBugs
path. Source-directory execution preserves a common project root so relative
imports remain available to the analyzer. Input discovery is typed (`sol`,
`bytecode`, `runtime`) and must agree with feasibility; unsupported
combinations fail explicitly rather than being silently omitted.

`ContractFeatures.file_count` remains a descriptive profile value. Planning
uses `execution_input_count`, computed as Solidity import-graph entrypoints plus
creation-bytecode and runtime-bytecode inputs, so imported dependencies are not
charged as independent sequential analyzer runs.

The target profile retains parsed Solidity constraint sets. Feasibility and
compiler selection operate on the intersection of target constraints with tool
or installed-compiler ranges. Any reported representative version is a member
of that intersection; an excluded upper bound is never used as the target
version.

### Composition and execution

Change `CompositionPlan.category_assignments: dict[str, str]` to an additive `category_owners: dict[str, list[str]]`. Selected tools are the ordered union of the primary followed by accepted complements.

The runner adapter may continue sending category filters only for complements. The primary still runs as the default analyzer; the additive owner map controls fusion rather than removing its output.

Execution is fresh-only. Each selected tool's old run directory is removed or
atomically quarantined outside every tool scan tree before invocation. Failure
to do either returns `74` and disables analyzer execution, fallback harvesting,
and fusion. Each invocation writes to private staging; only return-code-zero,
structurally valid reports are promoted. Missing, malformed, failed, timed-out,
or late reports cannot enter the final run.

The engine and standalone runner also share one public output-layout helper.
For a target `Token.sol`, both resolve to
`<results-root>/LAKES_out/Token/`, except that a root already named
`LAKES_out` is used directly. Before invoking an analyzer, the orchestrator
invalidates the prior fused report first and then the other three top-level
artifacts. Final files are atomically replaced in plan/execution/status/fused
order, so `fused_report.json` is the completed-generation marker. The child
runner uses `sys.executable`, preserving the environment that launched the
installed `lakes` command.

The engine passes an API key only in the runner child's ephemeral environment.
Generic adapters receive a sanitized environment. GPTScan alone receives the
secret through private stdin and converts it to in-memory arguments inside its
wrapper; plans, OS argv, persisted reports, and streamed logs contain no key.

### Fusion model

Keep `Finding` as the normalized atomic per-tool finding. Introduce a fused finding representation instead of overloading its singular `source_tool`:

```text
FusedFinding:
  category, location
  source_tools
  severity_values
  explanation_variants
  inconsistent_fields
  raw_findings
```

Fusion rules:

1. Retain a finding only when its source tool is in the category's verified owner set; categories without an explicit set default to primary-only.
2. Merge findings with the same non-empty `(category, location)` key.
3. Do not collapse locationless findings merely because their categories match.
4. Union source provenance and raw variants.
5. Mark `severity` and/or `explanation` inconsistent when distinct non-empty values exist.

The compact LAKES output uses `tools: [...]` rather than a singular `tool` for fused findings.

### Final report presentation and provenance

`fused_report.json` remains the canonical Stage 3 artifact and gains two typed
views without removing the current fused index:

```text
CombinationExplanation:
  text: non-empty paragraph
  source: LLM | DETERMINISTIC_FALLBACK
  model: str | null
  limitations: list[str]

CategoryResult:
  category: canonical DASP identifier
  owner_tools: ordered checked owner set (primary-only by default)
  tools[tool_id]:
    status: ToolExecutionStatus
    findings: list[JSON object]  # exact accepted post-adapter/enrichment objects

FusedReport:
  combination_explanation
  category_results
  findings                    # existing normalized/deduplicated FusedFinding[]
  availability and tool statuses
```

The raw object and normalized index are intentionally separate. A parser may
derive category, location, severity, confidence, and explanation for fusion,
but `Finding.raw` receives an unmodified deep copy of the accepted individual
finding object before parser normalization. SARIF stores the accepted result
object; generic JSON stores the accepted element of its findings array. For a
SmartBugs-backed analyzer, the accepted boundary is explicitly tool-native
output -> SmartBugs conversion -> LAKES `raw_name`/canonical-category
enrichment. The resulting current-run `result.json` element is preserved
unchanged from parsing through the category view; native tar/SARIF remains a
separate raw artifact. The category view groups only findings that passed
existing ignored/owner filters.
Its category set is the stable union of requested owner categories and observed
accepted categories, so an executed zero-finding owner is represented by an
empty list rather than omitted.

After RuleChecker accepts the certificate, a separate low-temperature,
structured LLM call may explain the already-fixed combination. Its prompt uses
the checked certificate and matrix-owned evidence; it cannot emit tools,
owners, weights, or actions. Transport/schema failure produces an explicitly
labelled deterministic explanation. The explanation is passed into Stage 3 as
data and cannot affect execution or fusion. This call is independent of CEGO:
a primary-only plan with no legal complement may still receive an LLM
explanation when a client is configured.

The persisted paragraph is deliberately qualitative. It may name only selected
tools and may not repeat category count fields, rate-like statistical values,
or guessed rejection reasons. A post-decode semantic check accepts the model
text unchanged or replaces the whole explanation with a provenance-labelled
fallback; it never edits prose or changes the checked certificate. Ordinary
budget wording such as `total runtime` or a decimal duration is not mistaken
for a count/rate field.

### Post-audit retrieval, packaging, and lifecycle hardening

DACE constructs one retrieval query per
`(category, owner_tool, PLAN_COMPOSITION)` cell. The query combines BM25 with
dense similarity when the embedding boundary is configured. Dense
unavailability is represented in retrieval diagnostics and falls back to BM25;
it is not swallowed as an empty evidence result. Matrix construction retains
the complete primary and feasible-candidate rows, including Stage 1 lineage,
category evidence, applicability, target constraints/compiler bucket, and
runtime provenance. CEGO serializes this typed matrix rather than rebuilding a
filtered prompt-only view.

The release boundary is reproducible from tracked files. The wheel carries the
default `toolcards` JSON/index data expected by the CLI. The Dockerfile builds
Smartian from the tracked source tree and places the resulting DLL at the
container-local runtime path; ignored developer build output and macOS paths
are not build inputs.

The fuzz campaign remains bounded by the exact user outer deadline. The
Smartian wrapper derives its inner campaign from that deadline after reserving
a bounded startup/report-normalization allowance. Execution aggregation keeps
valid current-run reports when another selected tool fails or times out and
marks the result partial; it reports total execution failure only when no
selected tool produced a valid current-run result.

## Pipeline and CLI Status Contract

The top-level result exposes one of:

```text
PRIMARY_NOT_SELECTED       # inspect Stage 1 status for reason
NO_EXECUTABLE_PLAN         # analytical primary exists; Stage 2 budget failed
PLAN_READY                 # checker accepted, execution not requested
EXECUTED
EXECUTED_PARTIAL           # at least one usable current-run tool result
EXECUTION_FAILED
```

CLI summary prints overall status, Stage 1 status, primary tool when present, selected action when present, checker status when present, and selected tools. JSON uses nullable/optional later-stage objects instead of synthetic placeholder certificates.

## Dynamic Knowledge-Base Update Design

The update service is independent from recommendation/execution and has four
typed boundaries:

```text
PDF
  -> MinerU converter -> MarkdownDocument(source digest + generated files)
  -> LLM extractor -> RawKnowledgeExtraction(dataset[], capability[])
  -> mapper/checker -> accepted metrics/passages + RejectRecord[]
  -> staged transaction -> Performance KB + PassageStore + vector index + log
```

The production converter invokes the documented MinerU CLI with a private
output directory and resolves the generated Markdown deterministically. An
injectable converter is used in tests. The extractor uses the existing
OpenAI-compatible client, temperature zero, a fixed two-channel JSON schema,
and injectable call boundary. Missing MinerU/LLM configuration fails before
live stores are opened for write.

Raw items carry a paper ID, publication date, concrete locator, and excerpt.
The mapper owns all normalization. Tool names must resolve unambiguously to a
ToolCard. Categories use the shared long-form DASP normalizer. Relation labels,
action scopes, tags, units, bases, rates, and detected/total values are checked
against their typed domains. Whitespace-normalized excerpts must occur in the
MinerU Markdown; a locator without source text is not provenance.

Performance entries retain one scene identity per physical dataset. A new
paper adds stable observation records inside that dataset view while each
observation keeps its own paper/locator provenance. Capability passages persist
zero/one/many observation IDs only when an accepted category metric from the
same extraction has the same paper, canonical tool, and canonical category.
At recommendation time, one projection resolves those observation IDs through
the actual Stage 1 lineage; absent rows remain explicitly qualitative rather
than receiving a guessed `stage1_evaluation_id`.

Commit builds complete candidate stores and a complete replacement retrieval
index in an immutable staging generation, reloads all of them through
production validators, then atomically replaces one `kb_current.json` pointer.
Readers resolve that pointer once and load both stores/index from the named
generation, so no reader can observe a mixed old/new pair. A journal supports
recovery or pointer rollback after failure. Reject records are deterministic
and bounded; they never silently convert rejected evidence into qualitative
passages. The default CLI targets an explicit writable KB root and never
changes packaged artifacts unless the caller imports them as a baseline.

## Local-Private Benchmark Snapshot

The tracked `toolcards` directory remains the reproducible public release
baseline. A developer checkout may additionally contain the ignored directory
`toolcards/.private/` with a complete runtime snapshot:

```text
toolcards/.private/performance_db.json
toolcards/.private/contract_profiles.json
toolcards/.private/passage_store.json
toolcards/.private/vector_index/index.json
```

These are full runtime snapshots, not independently merged fragments. The
private Performance KB exactly extends the current tracked Performance KB with
the local-private evaluation rows recovered from a private recovery source.
The private profile artifact is rebuilt from a local manifest with the current
canonical AST profiler and a full leave-one-out KDE fit over public and private
samples. The private PassageStore exactly retains the public passage prefix and
appends current-schema qualitative passages. Its vector index exactly retains
the public vector prefix, appends the corresponding bound embeddings, and binds
the complete ID order, dimensions, and current store digest.

The ignored private recovery source is provenance only. Runtime passages are
validated by the current strict schema, omit removed legacy fields, and set
`linked_evaluation_ids=[]`. They therefore remain qualitative RAG evidence:
retrieval may cite them, but deterministic applicability, count strength,
runtime, weighted conflict, and RuleChecker boundaries remain authoritative.

For the normal static path, the engine resolves the complete snapshot once
before Stage 1.
If no private runtime file exists, it uses the tracked public knowledge. If the
complete four-artifact snapshot exists, it selects all four together and emits
a visible local-private warning. Any missing artifact, stale public prefix,
Performance/profile delta mismatch, PassageStore/vector order mismatch, vector
dimension mismatch, or digest mismatch fails closed. An explicit `kb_root`
dynamic generation remains authoritative and bypasses the entire private
static snapshot.

The entire `.private` directory is excluded by both Git and Docker. Package
data rules continue to include only the tracked public root files, so a wheel
cannot acquire the local snapshot accidentally.

## Compatibility and Migration

- Breaking output version: `screc_v2`.
- Delete `CertificationVerdict` and certification consumers.
- Remove legacy certification fields from prompts and CLI output.
- Remove `RUN_ROBUST_SINGLE` from the default action literal and consumers.
- No `screc_v1` loader or compatibility facade.
- Add a release note describing renamed/removed fields and the new early terminal statuses.

## Test Strategy

- Remove the repository-level `tests/` ignore so new Python tests are tracked.
- Use focused new tests, consulting historical pre-`c875f03` tests only as behavioral references; do not blindly restore stale certification expectations.
- Build fixtures around small in-memory KBs and packets. Avoid LLM/network calls.
- Mock CEGO responses at the typed response boundary and exercise real deterministic assembly and RuleChecker logic.
- Test fusion with atomic findings from two tools, including identical locations, conflicting fields, and missing locations.
- Add a CLI test with the engine call mocked at the command boundary, plus an offline Stage 1 integration test using fixture profiles/KB.
- Add artifact tests for tracked-builder availability, manifest/root
  configuration, duplicate detection, compiler-bucket substitution isolation,
  failure accounting, deterministic fitting, atomic output, and strict loader
  rejection. Run one real full-corpus rebuild and retain its audit summary.

## Risk and Rollback

### Main risks

- A cross-layer field rename can leave one consumer reconstructing legacy state.
- Stage 2 can accidentally consume diagnostic KDE density instead of the
  normalized relevance weight owned by the statistical boundary.
- Additive fusion can duplicate findings unless merge keys and provenance are explicit.
- Early terminal results can break callers that assume matrix/certificate/checker are always present.

### Controls

- Search the repository for every legacy field/action before and after implementation.
- Centralize status/action/owner-set creation in shared typed helpers.
- Add boundary tests before removing old models.
- Verify `git diff -- toolcards/performance_db.json` remains identical to its pre-task diff.

### Rollback shape

Implementation proceeds in runnable checkpoints: Stage 1 models/scoring, Stage 2 context/decisions, Stage 3 fusion, then CLI cleanup. If a checkpoint fails, revert only files changed by that checkpoint; never reset the user's dirty worktree or performance DB.

## Task Decomposition Decision

Do not split this into independent child tasks. Stage 1, Stage 2, Stage 3, and CLI all share the breaking `screc_v2` contract, and no intermediate child result would be a complete runnable release. The implementation plan uses ordered validation gates instead.
