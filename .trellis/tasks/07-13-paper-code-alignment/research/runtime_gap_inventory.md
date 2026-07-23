# Research: Runtime evidence gap inventory

- Query: Inventory every canonical ToolCard against the shipped Performance KB; separate absent, non-schedulable, profile-incompatible, globally schedulable, and target-specific runtime states; trace the exact schema/loader/P90/provenance/test contract; and propose an auditable insertion contract for roughly five paper measurements plus an arithmetic mean.
- Scope: internal only (repository data, code, specs, tests, and the retained 0.4.x smoke record); external paper search was explicitly deferred.
- Date: 2026-07-21

## Findings

### Executive result

There are **20 canonical tools**. `load_toolcards()` defines the universe by sorting every JSON file in `toolcards/`, accepting only objects with both `tool_id` and `tool_name`, and validating each as a `ToolCard` (`toolrank/retrieval.py:10-20`; schema at `toolrank/schemas.py:85-95`).

Using the existing data only, the mutually exclusive global runtime classes are:

| Class | Count | Tools |
|---|---:|---|
| Can produce a qualified runtime estimate for at least one shipped canonical AST scene | 14 | `confuzzius`, `conkas`, `maian`, `manticore`, `mythril`, `osiris`, `oyente`, `securify`, `securify2`, `sfuzz`, `slither`, `smartcheck`, `solhint`, `vandal` |
| Has a positive completion-time observation, but its paper dataset has no canonical scene/compiler profile and therefore cannot schedule | 4 | `gptscan`, `honeybadger`, `sailfish`, `vulhunter` |
| Has only a non-schedulable campaign cap | 1 | `smartian` |
| Has no positive runtime value in any recognized completion-time field | 1 | `mando-hgt` |

The exact retained `TinyBank04.sol` 0.4.26 smoke has **13 runtime-known ToolTable rows and 7 runtime-unknown rows**. Of those seven, six are globally runtime-unknown and `vandal` is only target-specific unknown because its compatible scene support is `0.1537868616 < 0.2`. The smoke record independently notes that Smartian or VulHunter won the tested Stage 1 preferences but remained runtime-unknown (`.trellis/tasks/07-13-paper-code-alignment/progress.md:334-342`).

The planned paper search therefore has two different scopes:

1. **Global gaps:** GPTScan, HoneyBadger, MANDO-HGT, SAILFISH, SMARTIAN, and VulHunter.
2. **0.4.26 smoke gap:** the same six plus Vandal. Vandal already has a valid runtime row, but that row alone does not carry the required `0.2` original scene mass for this target.

Finding five papers per tool is not sufficient by itself. A new value remains unschedulable unless it has an explicit completion-time basis and maps to compiler-compatible evidence carrying at least `0.2` of the target's existing scene mass. The current four direct paper averages fail because `dataset_profile.solc=[]`, their datasets are absent from the canonical profile artifact, and hence their scene weight is zero (`toolcards/performance_db.json:2863-2957`; canonical datasets at `toolcards/contract_profiles.json:69-83`).

### Canonical tool matrix

Legend:

- `*` = the runtime source is one of the seven shipped scene identities and has non-empty compiler metadata.
- `!` = a positive completion-time row exists, but it is not a usable canonical scene source (missing scene identity/compiler profile, or an excluded duplicate).
- `cap` = campaign limit, not completion time.
- `total` = a cumulative total coexists with a recognized average; the total is never used.
- `Q` = qualified estimate for the exact retained 0.4.26/12-effective-LOC target.
- `X` = no compatible completion-time evidence; `NR` = no recognized runtime row; `S<.2` = compatible evidence exists but original support is insufficient.

| Canonical tool | Positive recognized runtime sources | Global class | Exact 0.4.26 target |
|---|---|---|---|
| `confuzzius` / ConFuzzius (`toolcards/Confuzzius.json:2-3`) | `2.md*`, `smartbug2.0empirical*` | schedulable | `Q 18.150000 min` |
| `conkas` / Conkas (`toolcards/Conkas.json:2-3`) | `2.md*`, `smartbug2.0empirical*` | schedulable | `Q 48.000000 min` |
| `honeybadger` / Honeybadger (`toolcards/Honeybadger.json:2-3`) | `honeybadger!` | profile/compiler gap | `X` |
| `maian` / Maian (`toolcards/Maian.json:2-3`) | `2.md*`, `smartbug2.0empirical*` | schedulable | `Q 1.976000 min` |
| `mando-hgt` / Mando-HGT (`toolcards/Mando-HGT.json:2-3`) | none; three metric rows have `execution_time_avg=null` | no runtime | `NR` |
| `mythril` / Mythril (`toolcards/Mythril.json:2-3`) | `1!`, `2*`, `3*`, `4*`, `5*`, `2.md*`, `smartbug2.0empirical*`, `sast_dataset1!+total` | schedulable | `Q 35.071667 min` |
| `osiris` / Osiris (`toolcards/Osiris.json:2-3`) | same eight source classes as Mythril | schedulable | `Q 18.153333 min` |
| `oyente` / Oyente (`toolcards/Oyente.json:2-3`) | same eight source classes as Mythril | schedulable | `Q 1.640000 min` |
| `sailfish` / Sailfish (`toolcards/Sailfish.json:2-3`) | `sailfish!` | profile/compiler gap | `X` |
| `securify` / Securify (`toolcards/Securify.json:2-3`) | `1!`, `2.md*`, `smartbug2.0empirical*` | schedulable | `Q 1.715333 min` |
| `sfuzz` / Sfuzz (`toolcards/Sfuzz.json:2-3`) | `2.md*`, `smartbug2.0empirical*` | schedulable | `Q 18.000000 min` |
| `slither` / Slither (`toolcards/Slither.json:2-3`) | `1!`, `2*`, `3*`, `4*`, `5*`, `2.md*`, `smartbug2.0empirical*`, `sast_dataset1!+total` | schedulable | `Q 0.298333 min` |
| `smartcheck` / Smartcheck (`toolcards/Smartcheck.json:2-3`) | same eight source classes as Slither | schedulable | `Q 0.108333 min` |
| `smartian` / Smartian (`toolcards/Smartian.json:2-3`) | `smartian!` (`3600 s`, `cap`) | campaign cap only | `X` |
| `solhint` / Solhint (`toolcards/Solhint.json:2-3`) | `2.md*`, `smartbug2.0empirical*` | schedulable | `Q 0.016667 min` |
| `vandal` / Vandal (`toolcards/Vandal.json:2-3`) | `smartbug2.0empirical*` | schedulable in at least one 0.4.x scene | `S<.2` (`0.1537868616`) |
| `vulhunter` / Vulhunter (`toolcards/VulHunter.json:2-3`) | `VulHunter!` | profile/compiler gap | `X` |
| `gptscan` / GPTScan (`toolcards/gptscan.json:2-3`) | `gptscan!` (`per_kloc`) | profile/compiler gap | `X` |
| `manticore` / Manticore (`toolcards/manticore.json:2-3`) | `1!`, `2*`, `3*`, `4*`, `5*`, `2.md*`, `smartbug2.0empirical*`, `sast_dataset1!+total` | schedulable | `Q 43.415000 min` |
| `securify2` / Securify2 (`toolcards/securify2.json:2-3`) | `1!`, `2*`, `3*`, `4*`, `5*`, `sast_dataset1!+total` | schedulable for a supported 0.5.x scene | runtime `Q 0.545000 min`, but the tool itself is infeasible for 0.4.26 |

The legacy runtime blocks for sources `1` through `5`, `2.md`, and `smartbug2.0empirical` begin at `toolcards/performance_db.json:66`, `:255`, `:513`, `:770`, `:1027`, `:1287`, and `:1706`. Vandal's only positive runtime is under `smartbug2.0empirical` (`toolcards/performance_db.json:2161`). MANDO-HGT's null runtime rows are visible at `toolcards/performance_db.json:2665-2677`, `:2847-2856`, and `:3172-3177`.

### Row-level classification details

#### No recognized runtime observations

Only MANDO-HGT is globally in this class. It has evaluation observations, but none supplies a positive value in `time_sec`, `execution_time_avg`, or `execution_time_avg_average_s`. A null `execution_time_avg` does not create a runtime row because `_runtime_value()` skips nulls (`toolrank/evidence_packet.py:92-100`).

#### Non-schedulable caps and cumulative totals

SMARTIAN has a single numeric runtime-like row: `3600 s`, explicitly marked `runtime_basis="campaign_cap"` (`toolcards/performance_db.json:2961-2981`). The scheduler records `CAMPAIGN_CAP_NOT_SCHEDULABLE`, sets no completion estimate, and admits only `per_contract` or `per_kloc` into the compatible set (`toolrank/evidence_packet.py:193-205`, `:262-300`). The campaign-cap behavior is regression-tested at `tests/test_runtime_reliability.py:231-249` and the packaged SMARTIAN row at `:288-307`, `:320-362`.

Seven canonical tools have `execution_time_avg_total_s` in `sast_dataset1`: Securify2, Slither, Smartcheck, Manticore, Mythril, Osiris, and Oyente (`toolcards/performance_db.json:2213-2358`). In every real row, a recognized `execution_time_avg_average_s` is also present. Therefore:

- zero canonical tools depend only on a cumulative total;
- seven tools carry an ancillary total that is deliberately ignored;
- those seven `sast_dataset1` averages are themselves non-participating because that dataset has `solc=[]`, `loc_profile={}`, and no canonical profile (`toolcards/performance_db.json:2184-2210`).

Both `D1Metric.resolved_time_sec` and the scheduling resolver omit `*_total_s` (`toolrank/schemas.py:60-69`; `toolrank/evidence_packet.py:49-53`, `:92-100`). The synthetic regression proves that an average plus a total selects the average, while a total alone remains unknown (`tests/test_runtime_evidence.py:174-226`).

#### Positive paper runtimes without compatible dataset provenance

The four current completion-time paper rows are:

| Tool | Existing value | Basis | Blocking profile facts |
|---|---:|---|---|
| GPTScan | `14.39 s` | `per_kloc` | `solc=[]`; dataset absent from canonical profile artifact (`toolcards/performance_db.json:2863-2883`) |
| HoneyBadger | `142 s` | `per_contract` | `solc=[]`; bytecode corpus absent from canonical profile artifact (`toolcards/performance_db.json:2887-2908`) |
| SAILFISH | `30.79 s` | `per_contract` | `solc=[]`; dataset absent from canonical profile artifact (`toolcards/performance_db.json:2912-2933`) |
| VulHunter | `4.4 s` | `per_contract` | `solc=[]`; dataset absent from canonical profile artifact (`toolcards/performance_db.json:2937-2957`) |

All four are valid descriptive observations. None is a scheduling estimate. `dataset_profile.solc=[]` is not a wildcard: compiler matching requires a non-empty list containing a range compatible with the exact target (`toolrank/evidence_packet.py:238-245`). Scene weights are keyed by the Performance-entry `source_id` exposed as `SceneNeighbor.paper_id`; a source absent from the seven canonical scene datasets receives weight zero (`toolrank/scene_pool.py:59-93`; `toolrank/evidence_packet.py:417-443`).

LOC absence is a limitation but is not independently fatal in the current implementation. `_loc_match()` returns `None` when LOC data is unavailable; compatible rows reject only `loc_match is False` (`toolrank/evidence_packet.py:159-179`, `:291-304`). Thus the four rows fail on scene/compiler identity even before LOC refinement.

#### Tools schedulable in at least one canonical scene

The shipped AST artifact has seven scene datasets and 2,934 successful profiles (`toolcards/contract_profiles.json:58-76`, `:106-109`). The global classification above was calculated by replaying each of those 2,934 profiles as a target, using its actual compiler bucket, LOC, and five complexity dimensions, then applying the production `build_scene_pool()` and `build_tool_table()` path. A tool counted as globally schedulable only when at least one replay produced non-null `expected_runtime_minutes`; every one of the 14 also has at least one such scene inside its ToolCard-supported compiler range.

This calculation does not mean all 14 are known for every target. Vandal demonstrates the distinction: its valid `smartbug2.0empirical` row can qualify for some 0.4.x scenes, but its `0.1537868616` support on TinyBank is below the mandatory threshold.

### Exact 0.4.26 target calculation

The retained target has compiler `0.4.26`, canonical Gower bucket `0.4.x`, effective LOC `12`, and complexity tuple `(avg=1, max=1, sum=2, nest=0, coupling=0)`. Its scene weights are:

| Performance source | Dataset | Original weight |
|---|---|---:|
| `smartbugsdb` | smartbugsdb | `0.2527263129` |
| `3` | Not So Smart Contracts | `0.2466262135` |
| `2.md` | Custom Benchmark Dataset | `0.1706835192` |
| `2` | Smart Contracts Benchmark Suite | `0.1661318155` |
| `smartbug2.0empirical` | smartbug2.0empirical | `0.1537868616` |
| `4` | SolidiFI Benchmark | `0.0089091164` |
| `5` | BNB Benchmark | `0.0011361608` |

Consequences for new evidence are concrete:

- a genuine runtime measured on canonical `smartbugsdb` or Not So Smart Contracts would individually clear `0.2` for this target;
- a row on only Custom Benchmark Dataset, Smart Contracts Benchmark Suite, or `smartbug2.0empirical` would not clear `0.2` alone, though compatible sources combine;
- Vandal needs at least one additional genuine compatible dataset row whose combined existing scene mass lifts it to `0.2`;
- assigning a paper to one of these datasets merely to obtain its weight would violate provenance. The paper must actually evaluate that dataset or a formally established canonical identity.

The production path intentionally checks original, unrenormalized support and uses no global fallback (`toolrank/evidence_packet.py:291-369`). Boundary and no-fallback regressions are at `tests/test_runtime_reliability.py:122-131`, `:177-202` and `tests/test_runtime_evidence.py:303-332`.

### Exact Performance-KB schema and normalization path

#### Legacy packaged representation

The shipped file declares seconds and a default `per_contract` basis (`toolcards/performance_db.json:1-6`). Its legacy hierarchy is:

```text
PerformanceKnowledgeBase
  criteria
  entries[]: PerformanceEntry
    source_id
    dataset_profile: DatasetProfile(dataset_name, solc[], loc_profile, ...)
    tool_performance_data[]: ToolPerformanceObservation
      tool_name
      metrics: D1Metric
      vulnerability scores/counts
```

The exact models are at `toolrank/schemas.py:41-69`, `:145-162`, `:302-366`. The full loader performs JSON parsing, Pydantic validation, then dynamic identity validation (`toolrank/dataset_kb.py:13-17`). Numeric gates accept only positive finite recognized time fields (`toolrank/dataset_kb.py:54-106`).

The current shipped file is entirely legacy-shaped: it has no `canonical_dataset_id` and no entries in `performance_observations`. Its direct paper rows retain only a free-text `evidence_source`, not stable paper/locator IDs. New auditable paper evidence should not copy that limitation.

#### Canonical aliases and recognized fields

Tool matching normalizes ToolCard ID/name to lowercase alphanumerics, drops aliases owned by multiple tools, and resolves Performance rows through that unique map (`toolrank/evidence_packet.py:45-89`). Runtime field priority is exactly:

1. `time_sec`
2. `execution_time_avg`
3. `execution_time_avg_average_s`

Only positive finite values survive (`toolrank/evidence_packet.py:92-100`). For duplicate rows sharing `(source_id, canonical tool)`, the resolver retains the maximum seconds value (`toolrank/evidence_packet.py:103-134`). Alias collision and same-source maximum behavior are tested at `tests/test_runtime_evidence.py:242-281`.

#### Compiler, LOC, support, and weighted P90

For each candidate row, the resolver records source/dataset identity, selected metric field, source seconds, converted schedulable seconds, unit/basis, original scene weight, compiler match, LOC match, counts, and limitations (`toolrank/evidence_packet.py:217-289`; typed model at `toolrank/schemas_v2.py:215-255`).

Qualification is:

```text
KB criteria runtime_unit == seconds
KB criteria runtime_basis_default == per_contract
row unit == seconds
row basis in {per_contract, per_kloc}
positive schedulable seconds
compiler match
LOC match is not false
sum(original compatible scene weights) >= 0.2
```

`per_kloc` converts once using target LOC; `campaign_cap` never produces schedulable seconds (`toolrank/evidence_packet.py:262-300`). When LOC-exact rows alone carry at least `0.2`, only those rows aggregate; otherwise all compiler-compatible rows whose LOC does not contradict the target aggregate (`toolrank/evidence_packet.py:302-307`).

Weighted P90 sorts candidates by schedulable seconds (then `source_id`), sets the threshold to `0.9 * qualified_support_mass`, and selects the first observed candidate whose cumulative original scene weight reaches it (`toolrank/evidence_packet.py:371-414`). It does **not** compute an arithmetic mean and does **not** synthesize a new runtime value. The only seconds-to-minutes conversion occurs while building `ToolCostEntry` (`toolrank/evidence_packet.py:465-505`). Weighted P90 and its selected observed source are tested at `tests/test_runtime_evidence.py:284-300`.

#### Typed scheduling provenance

`RuntimeEstimateProvenance` requires method `scene_weighted_p90_compatible_dataset_proxy`, selected source/dataset/field, source and scheduled seconds, basis, target compiler/LOC buckets, support/threshold/quantile, unique candidate source IDs, every candidate row, and limitations (`toolrank/schemas_v2.py:284-352`). `ToolCostEntry` requires runtime and provenance to appear together and checks `minutes == selected_runtime_seconds / 60` (`toolrank/schemas_v2.py:355-386`). Negative, non-finite, missing, mismatched, blank, and duplicate identities are tested at `tests/test_runtime_evidence.py:411-469`.

### Dynamic paper-observation schema and provenance IDs

The implemented ingestion path has a stronger atomic representation that new research should use:

- `paper_id = paper_<first 32 hex of PDF SHA-256>` and is checked against the document digest (`toolrank/kb_update_models.py:57-89`).
- `canonical_dataset_id` hashes normalized dataset label, experiment setting, and split identity; the source ID is deterministically dataset-derived, not paper-derived (`toolrank/kb_update_service.py:104-118`).
- `PerformanceObservation` requires stable observation/paper/source/dataset/tool identities, `metric_kind`, normalized/original values and units, explicit runtime basis, an exact source locator, and Stage 1 eligibility (`toolrank/schemas.py:200-299`).
- `observation_id` hashes paper ID, dataset ID, tool, metric kind, category, and exact locator key (`toolrank/kb_update_service.py:754-790`).
- a table claim must resolve to the exact block/cell and excerpt; the mapper normalizes supported time units to seconds and requires a positive finite runtime plus explicit allowed basis (`toolrank/kb_update_service.py:654-731`).
- duplicate observation IDs, dataset/source mismatches, and conflicting content fail validation (`toolrank/dataset_kb.py:20-51`; `toolrank/kb_update_service.py:1167-1215`).

Stable IDs, exact excerpt/table provenance, one scene identity, and deterministic observation ordering are tested at `tests/test_kb_update_validation.py:39-60`, `:83-158`, `:181-256`; generation no-op and one-dataset behavior are tested at `tests/test_kb_update_transaction.py:262-280`.

There is a crucial current projection limitation. Atomic `performance_observations` are aggregated into one `ToolPerformanceObservation` per tool/dataset. Runtime observations are sorted, then each successive observation overwrites `metrics.execution_time_avg`; all observation IDs are retained, but no mean is calculated (`toolrank/kb_update_service.py:1069-1129`). The runtime scheduler then reads only `tool_performance_data`, not the atomic observations (`toolrank/evidence_packet.py:103-134`). Therefore five atomic paper rows on the same canonical dataset do **not** currently become five P90 candidates or an arithmetic mean.

There is also a basis-boundary mismatch worth making explicit during paper screening. Dynamic ingestion accepts `per_file`, `per_project`, and `total_benchmark` in addition to the three scheduling bases (`toolrank/schemas.py:242-251`; `toolrank/kb_update_service.py:492-499`), but scheduling admits only `per_contract` and `per_kloc`, retaining `campaign_cap` only as a limitation (`toolrank/evidence_packet.py:54-56`, `:291-301`). A dataset total cannot be written as a per-contract completion time unless the paper provides an exact valid denominator and compatible semantics and the derivation is itself preserved.

### Minimal auditable insertion contract for about five papers per missing tool

The minimal safe contract is a **two-layer measurement plus summary design**. It preserves the existing scheduling rule rather than disguising a cross-paper mean as an observed row.

#### Layer A — atomic paper measurements (authoritative evidence)

For each of roughly five independent papers per tool, persist one `PerformanceObservation` per genuinely reported runtime cell with:

1. content-derived `paper_id` and stable `observation_id`;
2. canonical tool ID resolved through ToolCards;
3. canonical dataset ID, exact dataset/split/experiment-setting identity, and existing canonical scene source when the dataset truly matches one;
4. exact `source_locator` block/page/table/row/column, excerpt, and excerpt digest;
5. original numeric value and original unit;
6. normalized positive seconds;
7. explicit basis (`per_contract`, `per_kloc`, `campaign_cap`, `total_benchmark`, etc.);
8. compiler buckets actually supported by the evaluated corpus, plus LOC-bin counts when the paper/artifact supports them;
9. paper-reported sample/success/timeout/compilation-failure/failure counts when available;
10. `stage1_eligible=false` with `DATASET_PROFILE_MISSING` when the dataset lacks a shipped canonical contract profile.

Do not attach a paper to `smartbugsdb`, `2.md`, or another high-weight source unless its evaluated corpus is genuinely that canonical dataset. Do not turn a one-hour cap or whole-benchmark wall time into per-contract completion time. Do not treat multiple configurations from one paper as five independent papers; use `experiment_setting_id` and keep each cell distinct.

#### Layer B — derived arithmetic mean (auditable summary, non-authoritative for scheduling)

Compute means only inside a homogeneous cohort:

```text
same canonical tool
same runtime basis
same normalized unit (seconds)
same declared comparison cohort / setting policy
exclude campaign caps and cumulative benchmark totals
mean_seconds = fsum(constituent normalized seconds) / n
```

`per_contract` and `per_kloc` must have separate means. They cannot be averaged together without a target-specific LOC conversion. A paper's own reported average is one atomic paper measurement, not many inferred samples.

The derived record must retain at least:

```text
summary_id
tool
aggregation = arithmetic_mean
runtime_basis
runtime_unit = seconds
mean_seconds
n
constituent_observation_ids[]
included_observation_ids[]
excluded_observation_ids[] + bounded reasons
cohort definition / setting policy
generated_at
```

No current typed schema has this summary object. The safe minimal implementation is to add a typed `RuntimeDerivedSummary` collection while leaving it **non-schedulable**. Do not write the cross-paper mean into `time_sec`, `execution_time_avg`, or `execution_time_avg_average_s`: the existing loader would misclassify it as an observed candidate, collapse provenance to one `(source_id, tool)` row, and claim a P90 method that did not produce the number.

Scheduling should continue to use the atomic, compatible dataset rows and the existing weighted P90. If the product decision is that the arithmetic mean itself must drive scheduling, that is not a data-only edit: the scheduling spec, method literal, candidate provenance, runtime loader, and tests must first change so the mean's constituent IDs and basis conversions survive into `RuntimeEstimateProvenance`.

#### Minimum acceptance tests for inserted paper data

Existing tests that every insertion must continue to satisfy:

- field priority, total exclusion, finite seconds, and one conversion: `tests/test_runtime_evidence.py:174-239`;
- alias resolution/collision and same-source maximum: `tests/test_runtime_evidence.py:242-281`;
- weighted P90, zero weight, and no global fallback: `tests/test_runtime_evidence.py:284-332`;
- runtime/provenance coupling and identity validation: `tests/test_runtime_evidence.py:411-469`;
- original support boundary, compiler compatibility, LOC/count provenance, and typed bases: `tests/test_runtime_reliability.py:122-249`;
- packaged paper-row source/basis behavior: `tests/test_runtime_reliability.py:288-362`;
- stable atomic IDs, exact locators, canonical dataset identity, and no duplicate scene: `tests/test_kb_update_validation.py:39-60`, `:83-158`, `:181-256`; `tests/test_kb_update_transaction.py:262-280`.

New tests required specifically for the requested five-paper/mean work:

1. five atomic runtime observations survive merge with five distinct `observation_id` values and exact locator refs;
2. the arithmetic mean replays exactly from its declared constituent IDs using `math.fsum`;
3. caps, `total_benchmark`, cumulative totals, incompatible bases, and incompatible settings are excluded with deterministic reasons;
4. `per_contract` and `per_kloc` never enter the same mean;
5. a derived summary cannot populate a recognized scheduling runtime field unless the scheduling contract is explicitly migrated;
6. multiple papers on one canonical dataset do not silently become last-write-wins in the scheduling projection;
7. a paper source absent from the canonical scene has zero scheduling support even when its mean exists;
8. TinyBank-specific fixtures prove exact behavior below/equal/above support `0.2`, including Vandal's current `0.1537868616` baseline;
9. the selected weighted-P90 source and every atomic/derived provenance ID survive JSON round trip;
10. all 20 canonical tools remain uniquely alias-resolvable after insertion.

### Files found

| Path | Role / one-line finding |
|---|---|
| `toolcards/*.json` (20 ToolCards listed in the matrix) | Canonical analyzer IDs, names, supported compiler ranges, and input modes. |
| `toolcards/performance_db.json` | Shipped legacy Performance KB; owns all current runtime numbers and criteria. |
| `toolcards/contract_profiles.json` | Seven canonical AST scene datasets and 2,934 successful profiles used for the global replay. |
| `toolrank/retrieval.py` | Defines canonical ToolCard discovery/loading. |
| `toolrank/schemas.py` | ToolCard, legacy Performance-KB, atomic dynamic observation, source-locator, and basis schemas. |
| `toolrank/dataset_kb.py` | Full KB loader, dynamic identity checks, and legacy numeric range gate. |
| `toolrank/scene_pool.py` | Maps canonical dataset names to Performance-entry source IDs and produces original scene weights. |
| `toolrank/evidence_packet.py` | Sole runtime row normalization, compatibility, support, weighted-P90, and seconds-to-minutes owner. |
| `toolrank/schemas_v2.py` | Typed runtime candidate, assessment, selected provenance, and ToolCost coupling. |
| `toolrank/kb_update_models.py` | Strict two-channel extraction envelope and content-addressed paper identity. |
| `toolrank/kb_update_service.py` | Unit/basis normalization, stable observation IDs, canonical dataset merge, and current last-write runtime projection. |
| `tests/test_runtime_evidence.py` | Core field/alias/dedup/P90/no-fallback/provenance regressions. |
| `tests/test_runtime_reliability.py` | Compiler/LOC/support/basis/cap/paper-row regressions. |
| `tests/test_kb_update_validation.py` | Stable observation/link/source-locator/dataset identity regressions. |
| `tests/test_kb_update_transaction.py` | Immutable-generation/no-op/one-scene merge regressions. |
| `.trellis/spec/backend/lakes-scheduling-contract.md` | Executable project contract for runtime ownership, bases, support, P90, provenance, and error cases. |
| `.trellis/tasks/07-13-paper-code-alignment/{prd.md,design.md,implement.md,progress.md}` | Active requirements/design/plan plus the retained 0.4.x smoke evidence. |

### Code patterns

- One owner: Performance-KB runtime normalization belongs to `toolrank/evidence_packet.py`; downstream consumers receive minutes plus typed provenance and must not reinterpret raw fields (`toolrank/evidence_packet.py:417-505`).
- Fail closed: missing compiler/scene linkage, support below `0.2`, unsupported basis, or unknown primary runtime remains unknown; there is no global maximum fallback (`toolrank/evidence_packet.py:291-369`).
- Observed quantile: weighted P90 chooses an actual candidate row and source ID rather than interpolating or averaging (`toolrank/evidence_packet.py:371-414`).
- Content-addressed provenance: dynamic paper, dataset, observation, and locator identities are deterministic (`toolrank/kb_update_models.py:19-32`, `:57-89`; `toolrank/kb_update_service.py:104-118`, `:754-790`).
- One scene per physical/canonical dataset: new papers add observations to that dataset rather than duplicating KDE mass (`toolrank/kb_update_service.py:1141-1216`; test at `tests/test_kb_update_validation.py:181-204`).
- Current gap: multi-paper atomic runtime rows are preserved in `performance_observations` but projected last-write-wins into the single scheduling row (`toolrank/kb_update_service.py:1069-1129`).

### External references

None. Per instruction, no paper/web search was performed in this research pass. Existing paper titles, values, and free-text citations were inventoried only as already stored in `toolcards/performance_db.json`.

### Related specs

- `.trellis/spec/backend/lakes-scheduling-contract.md:146-178` — Performance-KB-only ownership, accepted fields/bases, compatible support, weighted P90, and paper-row limitations.
- `.trellis/spec/backend/lakes-scheduling-contract.md:399-421` — required fail-closed outcomes for unknown, cumulative, incompatible, and below-support runtime evidence.
- `.trellis/spec/guides/cross-layer-thinking-guide.md:13-77` — map producer/store/loader/consumer boundaries and assign validation once.
- `.trellis/spec/guides/code-reuse-thinking-guide.md:13-65` — reuse the one runtime owner rather than adding a second aggregation path.
- `.trellis/tasks/07-13-paper-code-alignment/prd.md:102-143` — R8/R9 runtime ownership and reliability requirements.
- `.trellis/tasks/07-13-paper-code-alignment/design.md:120-190` — dataset-proxy, compiler/LOC support, and P90 design.

## Caveats / Not Found

- No external paper search was performed, so the availability of roughly five independent, usable runtime papers for each missing tool is unknown. Niche/new tools may have fewer than five compatible evaluations.
- The four existing direct paper values are descriptive and source-grounded in free text, but they are not stable locator-backed `PerformanceObservation` records and cannot schedule without canonical scene/compiler linkage.
- The exhaustive global replay establishes existence of at least one schedulable shipped scene; it does not claim uniform coverage over arbitrary unseen contracts.
- TinyBank is a retained local smoke fixture under `/private/tmp`, not a tracked repository fixture. The task progress file preserves its outcome, and this report preserves the exact replayed feature/weight/runtime matrix.
- Hardware, timeout, tool version, success rate, and dataset size differ across papers. The requested arithmetic mean is reproducible only after declaring a comparison cohort; it is not automatically a scientifically comparable or conservative scheduling statistic.
- LOC metadata is currently optional for compatibility (`None` is allowed). Treating missing LOC as a hard blocker would be a new contract decision, not a faithful description of current code.
- Dynamic ingestion accepts some bases that scheduling rejects (`per_file`, `per_project`, `total_benchmark`), and there is no focused regression for that cross-layer mismatch today.
- There is no current typed `RuntimeDerivedSummary`; persisting a cross-paper mean without adding one would either be opaque metadata or would falsely masquerade as a raw runtime observation.
