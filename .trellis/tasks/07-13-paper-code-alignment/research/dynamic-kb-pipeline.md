# Research: Dynamic knowledge-base ingestion pipeline

- Query: Research item 8 — design an offline-testable production pipeline for PDF -> MinerU Markdown -> LLM metric/capability extraction -> Map & Check -> atomic Commit/link, aligned with the effective paper and the repository's current schemas, stores, retrieval, packaging, CLI, and file-writing conventions.
- Scope: mixed (repository code, effective paper source, and official MinerU/Python documentation)
- Date: 2026-07-19

## Findings

### Executive conclusion

The production design should treat ingestion as one deterministic transaction over two authoritative stores: `PerformanceKnowledgeBase` and `PassageStore`. MinerU, the LLM, and dense embedding generation must sit behind injected interfaces. Every extracted candidate must pass strict normalization, schema, provenance, and cross-store linkage checks before it can enter an immutable generation.

Replacing the two current JSON files one after the other is not an atomic two-store commit. The safe design is to stage both complete stores in an immutable generation directory and atomically replace one small `kb_current.json` pointer only after both stores and any required vector index have been reloaded and validated. Readers must resolve that pointer once per request. Rollback is another pointer replacement to the previous immutable generation.

The existing source tree has useful pieces but no production dynamic-KB ingestion implementation. In particular:

- `dataset_kb.refresh_performance_db()` validates individual metric entries and range gates, but replaces by `source_id`, writes files directly, and has no two-store transaction or provenance/linkage validation.
- `Passage` already encodes the paper's stance semantics more strictly than its four-field prose summary, but lacks a typed, resolvable source locator and a stable link to a performance observation.
- Stage-1 evaluation IDs are run-derived. They must not be guessed during ingestion. Persist stable performance-row references, then project them to existing Stage-1 `linked_evaluation_ids` only when those rows actually occur in the current Stage-1 lineage.
- The current passage vector index is derived state. A passage-changing commit must build and validate a matching index inside the same generation, or fail before the pointer flip; it must never reuse an index for a different passage-store digest.
- Ignored `build/lib/toolrank/kb_extract/` files are stale build archaeology, not importable source or a package contract. They should inform migration only, not be revived wholesale.

### Effective paper contract

The effective source is `main_revised.tex`:

- `main_revised.tex:438-441` defines the dynamic-KB subsection and the three phases: **Extract**, **Map & Check**, and **Commit**.
- `main_revised.tex:450` requires PDF conversion to structured Markdown with MinerU, preserving headings and table layouts. It then requires a fixed LLM extraction template with two channels:
  - dataset evidence: precision, recall, and runtime;
  - capability evidence: strengths, weaknesses, comparisons, and applicability.
- `main_revised.tex:459-467` defines the complete stance mapping:
  - `supports_owner -> FOR`
  - `owner_complements -> FOR`
  - `opposes_owner -> AGAINST`
  - `owner_ineligible -> AGAINST`
  - `owner_stronger -> COMPARE`
  - `owner_weaker -> COMPARE`
  - `evidence_gap -> GAP`
- `main_revised.tex:472` requires Map & Check to normalize `owner_tool`, `category`, `relation_to_owner`, and `applicability_tags`; align categories to the valid DASP-10 taxonomy; check presence, type, allowed stance consistency, and concrete provenance; and reject/log failed items.
- `main_revised.tex:474` requires capability evidence to enter tool knowledge for DACE-RAG, benchmark metrics to enter dataset knowledge for Stage 1/Stage 2, and capability/evaluation rows from the same paper, tool, and category to be linked.
- `main_revised.tex:476` is commented-out prior wording and is not an effective contract.

The four paper fields are a normalization minimum, not a complete persisted passage schema. The current `Passage` model also requires `passage_id`, `source_id`, `knowledge_kind`, `evidence_stance`, `relation_to_owner`, text, scope, tags, evidence level, and other semantic invariants (`toolrank/schemas_v2.py:972-1159`). The implementation should keep those stronger contracts rather than weaken them to four strings.

### Files found

| Path | Role / finding |
|---|---|
| `.trellis/workflow.md` | Trellis workflow and task lifecycle; research is persisted under the active task. |
| `.trellis/tasks/07-13-paper-code-alignment/{task.json,prd.md,design.md,implement.md,progress.md}` | Active paper/code-alignment task context. The current PRD reaches R16/AC30 for weighted evidence lineage but does not yet contain a dynamic-KB implementation requirement. |
| `.trellis/tasks/07-13-paper-code-alignment/research/paper-effective-contract.md` | Existing effective-paper analysis; confirms that uncommented TeX governs and records the dynamic-KB prose. |
| `.trellis/spec/backend/index.md` | Backend spec index; most linked general backend pages are placeholders. |
| `.trellis/spec/backend/lakes-scheduling-contract.md` | The active executable scheduling contract, including evidence-lineage behavior that new dynamic links must preserve. |
| `.trellis/spec/guides/cross-layer-thinking-guide.md` | Requires tracing data contracts across producer, persistence, and consumer boundaries. |
| `.trellis/spec/guides/code-reuse-guide.md` | Requires searching for and reusing existing validation/atomic-write patterns rather than duplicating them. |
| `main_revised.tex` | Effective paper source, especially lines 438-474. |
| `toolrank/dataset_kb.py` | Current performance-KB loader, entry range checks, refresh/merge behavior, and non-atomic writes. |
| `toolrank/schemas.py` | Current performance-entry and tool-card models; performance models are permissive (`extra="allow"`). |
| `toolrank/categories.py` | DASP-10 category list and alias normalizer; unknown labels are normalized but not rejected. |
| `toolrank/schemas_v2.py` | Strict Stage-1 lineage, passage, evidence-card, and action-matrix schemas and semantic validators. |
| `toolrank/passage_store.py` | Passage-store loading, graph filtering, vector-index building, and retrieval. |
| `toolrank/retrieval.py` | Tool-card file discovery/loading convention. |
| `toolrank/vector_store.py` | Embedding-provider credential resolution, remote calls, vector-index persistence, and vector search. |
| `toolrank/openai_compat.py` | Existing OpenAI-compatible LLM configuration/client and JSON-completion helper. |
| `toolrank/scene_pool.py` | Converts performance entries to benchmark slices; only datasets present in the contract profiles enter Stage 1. |
| `toolrank/scene_scoring.py` | Produces Stage-1 evaluation rows and run-derived evaluation IDs. |
| `toolrank/dace_rag.py` | Converts retrieved passages to evidence cards and enforces explicit/fallback evaluation linkage. |
| `toolrank/engine.py` | Resolves default KB paths and currently loads passage store/vector index as two fixed paths. |
| `toolrank/cli.py` | Current Typer conventions, error handling, output modes, and source-relative tool-card default. |
| `toolrank/profile_builder.py` | Best existing single-file atomic-write helper. |
| `toolrank/report_validity.py` | Existing quarantine/promotion pattern; useful recovery precedent but not a two-store atomic reader contract. |
| `pyproject.toml`, `requirements.txt`, `README.md` | Core dependencies, console scripts, package-data rules, installation, and environment-variable conventions. |
| `.gitignore`, `.dockerignore` | MinerU scripts/output/token and build output are intentionally excluded from source/package contexts. |
| `tests/test_profile_builder.py` | Existing fault-injection test for the atomic single-file writer. |
| `tests/test_cleanup_quarantine.py` | Existing quarantine/promotion failure tests. |
| `tests/test_weighted_evidence_lineage.py` | Exact current zero/one/many link and invalid/cross-tool lineage behavior to retain. |
| `build/lib/toolrank/kb_extract/` | Ignored, stale build output containing an older extraction prototype; not production source. |

### Current code patterns and gaps

#### Performance knowledge base

`load_performance_db()` reads JSON and validates the complete object with `PerformanceKnowledgeBase.model_validate()` (`toolrank/dataset_kb.py:13-15`). That complete-snapshot validation is worth retaining at the transaction boundary.

`_gate_numeric_ranges()` checks fraction-like fields in `[0,1]` and time fields for non-negative values (`toolrank/dataset_kb.py:30-55`). `_validate_entry()` first parses one `PerformanceEntry`, then reports the first range error (`toolrank/dataset_kb.py:58-70`). These checks are too narrow for ingestion because they do not establish:

- finite values (`NaN`/`Infinity` must be rejected explicitly);
- percent-versus-fraction normalization;
- runtime unit and aggregation basis;
- `detected <= total` for count metrics;
- category membership;
- canonical tool identity;
- field-level source provenance;
- cross-store linkage.

`refresh_performance_db()` treats the extraction artifact as a loose dictionary, validates incoming entries one at a time, replaces an existing entry solely on equal `source_id`, then writes the output and reject log directly with `Path.write_text()` (`toolrank/dataset_kb.py:80-141`). Consequences:

- malformed or missing top-level keys can degrade into an empty refresh rather than a strict envelope failure;
- one `source_id` collision can replace a complete existing entry;
- a performance write can succeed before a reject-log write fails;
- there is no fsync, atomic replacement, rollback, lock, transaction journal, or passage-store update;
- a stale reject log remains after a later clean run because the file is written only when rejects exist;
- valid candidates can be committed without any link/provenance checks.

The performance models use `ConfigDict(extra="allow")` (`toolrank/schemas.py:34-62,116-210`). That is suitable for reading historical data but unsuitable for the LLM boundary. A new strict staging schema must use `extra="forbid"` and strict scalar types. Historical compatibility should be handled only when loading the pre-existing canonical store.

`VulnerabilityScoreCount` requires non-negative `detected` and `total` but does not enforce `detected <= total` (`toolrank/schemas.py:65-69`). The ingestion validator must add that invariant.

#### Category and tool normalization

The valid taxonomy is enumerated in `toolrank/categories.py:8-19`. `normalize_category()` handles aliases but returns an arbitrary normalized string for an unknown label (`toolrank/categories.py:22-38`). Therefore this is the required sequence:

1. normalize an alias;
2. require the normalized result to be a member of `VALID_CATEGORIES`;
3. reject an unmappable label with a stable reason code.

An unrecognized paper label must not be silently mapped to `unknown_unknowns`. That category is valid only when the source explicitly means the taxonomy's unknown-unknowns class. The stale prototype violates this rule by defaulting failed mappings to `unknown_unknowns` (`build/lib/toolrank/kb_extract/relation_first.py:418-427`).

Tool aliases need one canonicalization authority shared by both extraction channels and runtime scoring. Canonicalization should use normalized Unicode, trimmed/collapsed whitespace, case-insensitive alias lookup, and an explicit alias table. If one alias resolves to two canonical tools, or two extracted owners collapse ambiguously, reject rather than choose. The local `_tool_key()` in `toolrank/scene_scoring.py:22-24` is not an ingestion identity contract.

#### Passage schema, storage, and retrieval

`Passage` is strict and already validates much of the paper's stance semantics (`toolrank/schemas_v2.py:972-1159`):

- identity: `passage_id`, `source_id` (`:982-985`);
- owner/category/scope/knowledge fields (`:986-1005`);
- allowed applicability tag prefixes and field relationships;
- allowed `knowledge_kind`/`relation_to_owner` combinations;
- linked evaluation IDs.

However, `source_excerpt` is audit text, not a resolvable structured locator. The model has no typed page/block/table/row/benchmark record and no stable performance-observation reference. Both are necessary for the paper's provenance and same-paper/tool/category link checks.

`PassageStore` is only a list of passages (`toolrank/schemas_v2.py:1162-1165`). It carries no schema version, generation ID, canonical digest, or source-document manifest. Those belong in the generation manifest; adding them to the historical JSON shape is optional and would be a compatibility decision.

`load_passage_store()` strictly parses a file (`toolrank/passage_store.py:13-17`). The graph index declares a dataset-name index but the constructor does not populate it (`toolrank/passage_store.py:61,65-71`), while candidate filtering can consult it (`toolrank/passage_store.py:86-113`). Dynamic records should not rely on dataset-name graph filtering until that independent defect is fixed and tested.

The vector-index builder records provider, base URL, model, passage IDs, and text fields (`toolrank/passage_store.py:131-179`). The retriever checks only that the number of embeddings equals the number of passages (`toolrank/passage_store.py:182-194`). It does not require the metadata passage-ID sequence to equal the store sequence and does not bind the index to a passage-store digest. A valid generation must require all three:

- exact passage-ID sequence equality;
- embedding count/dimension consistency;
- `passage_store_sha256` equality in index metadata.

`VectorIndex.save()` writes directly (`toolrank/vector_store.py:295-305`), and `VectorIndex.load()` only verifies the broad schema/list type (`toolrank/vector_store.py:307-316`). The generation writer must serialize the index into staging rather than invoke this direct writer on a live path.

#### Existing evidence linkage

The current contract deliberately distinguishes explicit and fallback linking. In `toolrank/dace_rag.py:120-147`:

- `linked_evaluation_ids is None` permits exact same-source/same-tool fallback;
- `linked_evaluation_ids == []` is explicit no-link;
- a non-empty list must point to existing Stage-1 evaluations for the same tool, or matrix construction fails;
- fuzzy linking is prohibited.

`tests/test_weighted_evidence_lineage.py:179-218` covers explicit zero/one/many link cases, with invalid/cross-tool cases later in the file. New ingestion must not weaken these tests.

The persistent link should not be an invented Stage-1 evaluation ID. `stage1_evaluation_id(tool, benchmark_id)` (`toolrank/schemas_v2.py:123-125`) is derived from runtime benchmark construction. `scene_pool` creates slices only for datasets that occur in `contract_profiles` (`toolrank/scene_pool.py:63-93`), and `scene_scoring` then constructs evaluation rows (`toolrank/scene_scoring.py:114-127`). A newly ingested metric can exist in the performance KB yet be absent from a particular Stage-1 run.

The current checked-in passage store has 97 unique passages, but none has an explicit non-null `linked_evaluation_ids`. The performance DB has 17 unique entries. Only three source IDs are exact overlaps between the stores (`VulHunter`, `gptscan`, and `sailfish`), so current exact-source fallback cannot link most passages. This inventory is descriptive, not a proposed automatic fuzzy backfill.

#### Current external-service boundaries

The repository already separates some provider mechanics, but not at the orchestration boundary needed for offline tests:

- `openai_compat.load_openai_client()` takes no injected configuration and resolves a local/OpenAI-compatible client from environment state (`toolrank/openai_compat.py:194-201`). JSON completion accepts a client but still performs remote/local HTTP and tolerant JSON extraction (`toolrank/openai_compat.py:204-289`).
- Embedding configuration defaults to SiliconFlow and resolves `embeddingAPI`, `SILICONFLOW_API_KEY`, or `QWEN_API_KEY` (`toolrank/vector_store.py:17-21,41-96`). Remote embedding raises when a key is absent (`toolrank/vector_store.py:134-202`).
- The curl fallback includes the authorization header in the process argument vector (`toolrank/vector_store.py:162-181`). A new ingestion adapter should not use that fallback because local process inspection can expose credentials.

The ignored prototype hardwires `load_openai_client()` and fails if no client is available (`build/lib/toolrank/kb_extract/pipeline.py:70-85`). It consumes already-produced MinerU directories rather than accepting PDFs (`:70-78,91`), performs separate channel calls (`:106-173`), tolerates one channel's broad exception (`:146-172`), and directly writes passage/performance staging JSON (`:174-207`). It has no production transaction. Its order-based passage IDs (`build/lib/toolrank/kb_extract/relation_first.py:517-532`) are unstable when extraction order changes.

#### Atomic-write precedent

`write_artifact_atomic()` uses a same-parent `NamedTemporaryFile`, writes canonical JSON plus a newline, flushes and fsyncs the temporary file, and calls `os.replace()` (`toolrank/profile_builder.py:470-492`). Its fault test proves a failed replacement preserves the old output and removes the temp file (`tests/test_profile_builder.py:262-281`). This helper should be generalized for pointer, journal, reject-log, and manifest writes, with parent-directory fsync added after rename.

`report_validity` uses quarantine and promotion (`toolrank/report_validity.py:93-127,153-189`). Its tests explicitly allow the final path to be absent after old-output quarantine followed by promotion failure (`tests/test_cleanup_quarantine.py:278-318`). That behavior is appropriate for report cleanup but not for live KB readers, so it is not the two-store commit primitive.

### Proposed production design

#### 1. Architecture and injected boundaries

Use one orchestration service with narrow protocols. Concrete class/module names can follow repository style, but the contracts should be equivalent to:

```python
class PdfConverter(Protocol):
    def convert(self, pdf: Path, work_dir: Path) -> DocumentArtifact: ...

class EvidenceExtractor(Protocol):
    def extract(self, document: DocumentArtifact) -> RawExtractionEnvelope: ...

class PassageIndexBuilder(Protocol):
    def build(self, passages: Sequence[Passage]) -> VectorIndexArtifact: ...

class Clock(Protocol):
    def now_utc(self) -> datetime: ...
```

`PdfConverter` is the MinerU boundary. `EvidenceExtractor` is the LLM boundary. `PassageIndexBuilder` is a derived-index boundary and must also be injectable because the current dense provider can require network credentials. `Clock` is optional but avoids timestamps contaminating deterministic fixture comparisons.

The orchestrator performs no HTTP, subprocess, or environment lookup itself. Tests pass fakes returning checked-in fixtures. Concrete adapters resolve environment variables only when their methods are invoked. Importing schemas, running Map & Check, validating old stores, and testing commit failure must require no MinerU installation, API key, LLM key, embedding key, or network.

Logical flow:

```text
PDF bytes
  -> hash/identify
  -> injected MinerU adapter
  -> normalized DocumentArtifact
  -> injected two-channel extractor
  -> strict RawExtractionEnvelope
  -> normalize candidates
  -> schema + provenance + stance checks
  -> stable performance rows and passages
  -> same-paper/tool/category links
  -> merge two complete in-memory snapshots
  -> cross-store + index validation
  -> immutable generation
  -> one atomic kb_current.json pointer flip
```

Do not let either adapter write canonical KB paths. Adapter output is confined to a transaction work directory.

#### 2. Document artifact contract

MinerU output varies by backend, so normalize it once into a strict internal `DocumentArtifact`:

```text
schema_version
paper_id
pdf_sha256
pdf_size_bytes
converter = {name, version, mode, backend}
markdown = {relative_path, sha256}
content_list = {relative_path, sha256, format_version}
blocks[] = {
  block_id, page_number, block_type, ordinal,
  normalized_text, text_sha256,
  optional table_id/row/column coordinates
}
```

Rules:

- Validate the input is a regular, non-empty PDF and hash bytes before conversion.
- Require exactly one Markdown artifact and one compatible structured content-list artifact for the input stem. Reject ambiguous recursive “first match” behavior.
- Never decode with `errors="ignore"`; malformed text is an extraction failure.
- Generate `block_id` deterministically from page, block type, ordinal, and normalized-content digest if the chosen MinerU backend does not supply a stable ID.
- Record the exact MinerU version/mode/backend and all artifact digests. Do not persist a token, signed upload URL, API response headers, or absolute private path.
- Keep table structure in `blocks` so a metric locator can identify an exact table row/cell, not merely a page number.

The stale asset loader recursively picks a first Markdown/content-list match and decodes permissively (`build/lib/toolrank/kb_extract/assets.py:70-141`); production should explicitly reject those ambiguities.

#### 3. Strict LLM response schema

The logical extraction result should be one envelope containing both paper-required channels, even if an adapter internally makes more than one model request:

```text
RawExtractionEnvelope (extra=forbid, strict=True)
  schema_version: Literal["dynamic_kb_extract.v1"]
  paper_id: StrictStr
  pdf_sha256: Sha256
  extractor: {provider, model, prompt_id, prompt_sha256}
  dataset_claims: list[RawMetricClaim]
  capability_claims: list[RawCapabilityClaim]
```

Every `RawMetricClaim` must contain canonicalization inputs, not pretrusted canonical values:

- tool label;
- dataset label and experimental/split identity;
- metric kind (`precision`, `recall`, `runtime`, or an explicitly supported count/score kind);
- numeric value and source unit/basis;
- optional category label when the benchmark row is category-specific;
- a structured source locator.

Every `RawCapabilityClaim` must contain:

- owner tool label;
- category label;
- one of the seven paper relations;
- applicability tags;
- concise claim/evidence text;
- a structured source locator;
- optional dataset/benchmark references used only as link candidates.

The LLM schema uses `extra="forbid"`, strict numbers/strings, bounded list sizes, and non-empty text. No string-to-number coercion or tolerant trailing prose should occur after the adapter returns. If an OpenAI-compatible provider cannot enforce response JSON schema, the adapter may isolate JSON from the response, but strict validation remains authoritative and a malformed envelope fails the extraction phase before any candidate is mapped.

Do not persist chain-of-thought/reasoning. A diagnostic record may store provider/model/prompt identifiers, response digest, token counts, and a redacted error summary.

#### 4. Normalization and Map & Check

Map & Check should produce either an accepted typed candidate or one/more stable `RejectReason` records. It must not silently drop candidates.

Recommended gate order:

1. **Envelope** — matching paper/PDF digest, supported schema version, strict shape.
2. **Identity** — canonical tool and dataset identity; reject ambiguity/collision.
3. **Category alignment** — normalize alias, then require exact `VALID_CATEGORIES` membership.
4. **Metric normalization** — normalize percent/fraction and time units without guessing.
5. **Paper four-field presence** — owner, category, relation, applicability are present and type-valid for capability candidates.
6. **Stance semantics** — relation maps to the required stance and is legal for the chosen current `knowledge_kind` under `ALLOWED_RELATIONS` (`toolrank/schemas_v2.py:73-110`).
7. **Provenance** — locator resolves to the normalized document and the excerpt/table-cell digest matches.
8. **Canonical schema** — instantiate the final strict passage/performance staging model.
9. **Conflict/deduplication** — exact duplicate is a no-op; same identity with different content is a conflict, not last-write-wins.
10. **Cross-store link** — establish only verified same-paper/tool/category links.

Metric rules should be explicit:

- Fractions are stored in `[0,1]`. A source unit of `%` is divided by 100; a source unit of `fraction` is unchanged. An absent/ambiguous unit is rejected rather than inferred from magnitude.
- Reject non-finite values and post-normalization values outside `[0,1]`.
- Runtime requires a supported time unit and an aggregation basis such as per contract, per file, per project, or total benchmark. Normalize the unit while preserving basis and original value.
- Counts require non-negative integers and `detected <= total`.
- Precision/recall rows need sufficient denominator/basis provenance to be comparable; a bare number without benchmark identity remains rejectable or explicitly non-Stage-1 evidence according to the extraction contract.
- Category-level links require an explicit valid category. An overall metric must not be assigned a category merely to create a link.

Capability rules:

- Derive `evidence_stance` from `relation_to_owner`; never accept two independently supplied values that can disagree.
- Use the current `Passage` invariants for knowledge kind, relation, scope, tags, and stance.
- Normalize applicability tags to allowed prefixes and deterministic ordering; reject unrecognized namespaces.
- Preserve the source's meaning. Do not synthesize a strength/weakness or comparison that is not directly supported by the located block/table row.

Stable reject codes should include at least:

```text
ENVELOPE_SCHEMA
DOCUMENT_DIGEST_MISMATCH
TOOL_UNKNOWN
TOOL_ALIAS_AMBIGUOUS
CATEGORY_UNKNOWN
REQUIRED_FIELD_MISSING
RELATION_ILLEGAL
METRIC_UNIT_AMBIGUOUS
METRIC_RANGE
METRIC_COUNT_INCONSISTENT
PROVENANCE_NOT_FOUND
PROVENANCE_DIGEST_MISMATCH
DUPLICATE_CONFLICT
LINK_ENDPOINT_MISMATCH
CANONICAL_SCHEMA
```

#### 5. Deterministic IDs and idempotent merge

Use canonical JSON (UTF-8, sorted keys, compact separators, trailing newline at file level) for all content hashes. IDs should be stable across retries, model output ordering, machines, and timestamps.

Recommended identities:

- `paper_id = "paper_" + sha256(pdf_bytes)[:32]`; retain the full PDF digest in provenance. DOI/title are searchable metadata, not byte identity.
- `performance_source_id = "src_" + sha256([paper_id, canonical_dataset_id, experiment_setting_id])[:32]`.
- `performance_observation_id = "perf_" + sha256([performance_source_id, canonical_tool, metric_kind, category_or_null, source_locator_key])[:32]`.
- `passage_id = "p_" + sha256([paper_id, canonical_tool, category, relation, applicability_tags, normalized_claim_text, source_locator_key])[:32]`.
- `generation_id = "kbgen_" + sha256([canonical_performance_bytes, canonical_passage_bytes, required_index_manifest])[:32]`.

Do not use array indexes (`p_<doc>_<index>`), timestamps, random UUIDs, display-case tool labels, or a raw title as an identity component.

Merge semantics:

- Same stable ID and byte-equivalent canonical payload: idempotent no-op.
- Same stable identity but a different payload: reject `DUPLICATE_CONFLICT` unless an explicit, separately designed supersession operation identifies the expected old digest.
- New IDs: append, then sort by stable ID before serialization.
- Never replace an entire performance entry just because an LLM emitted the same loose `source_id`.
- A mixed extraction may commit accepted candidates and atomically log rejected candidates, but the committed generation always contains two complete validated snapshots. A malformed top-level envelope or failed document conversion aborts the run rather than partially trusting a channel.

#### 6. Link model and Stage-1 projection

Add a stable persistent reference from a capability passage to the exact accepted performance observation, for example:

```text
PerformanceObservationRef
  observation_id
  source_id
  canonical_dataset_id
  canonical_tool
  category
  paper_id
```

Call the passage field `linked_performance_observation_ids` (or an equivalently strict typed field). Establish a link only when:

- paper IDs are equal;
- canonical owner/tool IDs are equal;
- both sides carry the same explicit category;
- both provenance locators resolve;
- the metric row is a genuine evaluation observation, not unrelated metadata.

One capability can link zero, one, or many observations. Sort and deduplicate IDs. Paper/tool/category disagreement means no link and, if the LLM explicitly asserted the link, a `LINK_ENDPOINT_MISMATCH` reject.

At recommendation time, project persistent observation IDs through the current Stage-1 packet's evaluation lineage:

```text
performance observation ID
  -> source/dataset/tool/category key
  -> exact Stage-1 evaluation row, if present
  -> existing Passage.linked_evaluation_ids / EvidenceCard link
```

If no matching Stage-1 evaluation exists, the passage remains qualitative and unweighted for that run. It must not carry a fabricated dangling evaluation ID. This preserves the explicit zero/one/many semantics and CEGO weighting in `tests/test_weighted_evidence_lineage.py`.

A performance observation enters Stage 1 only when its dataset has a unique compatible `contract_profiles` entry and the required metrics for scoring. `scene_pool` currently drops other datasets. Such observations may still be retained for Stage 2/audit, but the generation manifest should mark them `stage1_eligible=false` with a reason. Adding new dataset profiles automatically is a separate contract and must not be guessed from the paper.

#### 7. True two-store atomic commit and rollback

Recommended layout under an explicit writable `kb_root`:

```text
kb_root/
  kb_current.json
  .kb_generations/
    kbgen_<digest>/
      manifest.json
      performance_db.json
      passage_store.json
      vector_index.json
  .kb_transactions/
    <run_id>/journal.json
  kb_rejects/
    <run_id>.json
```

The two JSON stores are authoritative. The vector index is derived, but when passages change it must be built and validated before publication so the new capability evidence is immediately retrievable. A metric-only generation may reuse the previous index only when the passage-store digest is byte-identical and the manifest records that exact digest.

Commit algorithm:

1. Acquire a single-writer lock scoped to `kb_root`. Use an atomic lock-directory creation plus an owner/journal record, or a small well-tested cross-platform lock dependency. Never silently break a live lock; stale recovery must inspect journal state.
2. Resolve `kb_current.json` once. If absent, strictly import the legacy fixed files as an initial immutable baseline generation.
3. Load and validate both baseline stores and the current vector metadata.
4. Convert/extract/map into a private transaction directory on the same filesystem.
5. Merge accepted records into complete in-memory copies. Serialize both deterministically.
6. Build the vector index through the injected builder if passage bytes changed.
7. Write generation files to a staging directory, flush/fsync each, and fsync the directory.
8. Reload from disk and validate:
   - both complete Pydantic snapshots;
   - unique deterministic IDs;
   - every provenance locator;
   - every persistent cross-store link and same-paper/tool/category invariant;
   - exact vector passage-ID order/count and store digest;
   - manifest file sizes/digests/schema versions.
9. Write the reject log atomically with stable reason codes and safe metadata. It is a per-run file, so a later clean run cannot leave a misleading “current rejects” file.
10. Atomically rename the immutable staged generation to `.kb_generations/<generation_id>` and fsync `.kb_generations`. An already-existing byte-identical generation is an idempotent no-op; a different generation at the same digest path is a corruption error.
11. Write a temporary `kb_current.json` containing the generation ID and manifest digest, fsync it, `os.replace()` it over the old pointer, and fsync `kb_root`. This one pointer replacement is the visibility commit.
12. Re-open through the same public generation loader. If post-commit verification fails, atomically restore the prior pointer and report rollback status.
13. Mark the journal `COMMITTED`/`ROLLED_BACK`, then release the lock. Retain old immutable generations according to a separate retention policy; never delete the only rollback target during ingestion.

Pointer readers must read the pointer once and use only paths under that generation. Reading the pointer independently for each store can still mix generations. `engine._load_passage_retriever()` and performance loading need one shared generation resolver; current fixed-path loading (`toolrank/engine.py:202-216,428-429,505-518`) cannot provide this guarantee.

Crash recovery on the next invocation is deterministic:

- journal prepared, pointer still old: quarantine/remove unpublished staging and mark aborted;
- generation published, pointer still old: leave/dedupe immutable generation and mark aborted/no-op;
- pointer names new generation and manifest/digests validate: finalize committed;
- pointer names an invalid/incomplete generation: restore the recorded old pointer; if that cannot be verified, refuse all new writes with a recovery-required error.

Sequential `os.replace(performance_db)` followed by `os.replace(passage_store)` plus backups is not an acceptable substitute. It can restore after an exception, but a concurrent reader can observe one new and one old store between replacements. The generation pointer is the atomic reader contract.

Reject logs should include run/paper IDs, channel, candidate digest, locator, gate, reason code, safe message, adapter/model/prompt/schema versions, and final disposition. They should not include credentials, signed URLs, raw authorization headers, chain-of-thought, or unrestricted full-paper/model output.

### CLI and packaging design

The existing CLI is a Typer app with typed options, `typer.BadParameter`, stderr errors, and `typer.Exit(1)` (`toolrank/cli.py:12-106`). It supports summary and JSON output (`toolrank/cli.py:108-144`). A consistent addition is a nested app:

```text
lakes kb ingest PAPER.pdf --kb-root PATH [options]
lakes kb validate --kb-root PATH
lakes kb recover --kb-root PATH
```

Minimum ingest options:

```text
--kb-root PATH                 explicit writable store root
--work-dir PATH               optional private staging parent
--mineru-mode local|precision-api
--mineru-command PATH         local adapter executable, not shell text
--llm-model NAME              non-secret provider setting
--embedding-model NAME        non-secret provider setting
--dry-run                     convert/extract/map/validate, never publish pointer
--output summary|json
```

Do not accept API keys as command-line values because they can enter shell history/process listings. Resolve them inside adapters from documented environment variables or an explicitly named credential-file option whose contents are never logged. Validate `--kb-root` before constructing network adapters. JSON output should report IDs, digests, accepted/rejected counts, generation/no-op/rollback status, and artifact paths without secrets.

Suggested exit behavior:

- `0`: committed, deterministic no-op, or successful dry run;
- `1`: conversion/extraction/provider failure before mutation;
- `2`: invalid CLI arguments (Typer convention);
- `3`: valid extraction but every candidate rejected; reject log written, pointer unchanged;
- `4`: transaction failed but prior pointer was verified/restored;
- `5`: recovery required because rollback or baseline verification failed.

**Historical pre-AC40 packaging note (obsolete):** the default ToolCard
directory was source-relative and wheels did not include root `toolcards/`.
AC40 now packages those files as a read-only sibling package used by
recommendation. The lasting ingestion rule is unchanged: require an explicit
writable `--kb-root` and explicit baseline `--toolcards-dir`; never modify
package installation files.

MinerU should not be added to core dependencies. Current core dependencies are small (`pyproject.toml:12-18`; `requirements.txt`), while MinerU is a large optional stack. Package concrete adapters in source, keep their imports lazy, and expose optional extras only if the project chooses an in-process adapter. A subprocess CLI adapter avoids coupling the core package to MinerU internals.

The ignored `build/lib/toolrank/kb_extract/` directory cannot satisfy packaging: `.gitignore` excludes build/MinerU/script artifacts, and no corresponding `toolrank/kb_extract/` source directory exists. Any implementation must be created under tracked `toolrank/`, with config assets included explicitly in `pyproject.toml` if used.

### External dependency and credential behavior

Official MinerU behavior as of the research date:

- The [MinerU API documentation](https://mineru.net/doc/docs/index_en/) documents Bearer-token precision APIs and asynchronous submit/poll behavior. Batch local upload uses `POST /api/v4/file-urls/batch`, signed `PUT` upload URLs, and polling by batch ID. The documented batch limit is 200 files, with per-file page/size limits. Returned archives contain Markdown and structured outputs.
- The same API documentation describes a lightweight Agent API without a token, but with IP limits and materially smaller file/page limits. It is not a safe default for full research papers.
- The [MinerU quick start](https://opendatalab.github.io/MinerU/quick_start/) documents `mineru[all]`, Python 3.10-3.13, and substantial local model/hardware/storage requirements.
- The [MinerU CLI documentation](https://opendatalab.github.io/MinerU/usage/cli_tools/) documents `mineru -p <input> -o <output>` and notes the current CLI/API orchestration.
- The [MinerU output-file documentation](https://opendatalab.github.io/MinerU/reference/output_files/) describes Markdown, content-list JSON, and backend-dependent intermediate outputs. The adapter must normalize rather than assume one recursive filename.
- MinerU's [official `pyproject.toml`](https://github.com/opendatalab/MinerU/blob/master/pyproject.toml) currently declares Python `>=3.10,<3.14`; its [changelog](https://opendatalab.github.io/MinerU/reference/changelog/) shows that names, backends, and output behavior have changed across releases.

Production adapter policy:

- **Local adapter:** invoke an explicit executable argument vector such as `mineru -p <pdf> -o <transaction-output>`, never `shell=True`; capture a bounded/redacted log; record `mineru --version` and backend; fail clearly if executable/models are unavailable. It needs no API token but may download models and require significant resources.
- **Precision API adapter:** resolve `MINERU_TOKEN` at call time (an explicitly supported legacy alias may be documented); send it only in the HTTP authorization header; never store it, place it in argv, print it, or include signed upload URLs in diagnostics; apply bounded poll interval/deadline; verify HTTP status, batch/file identity, archive size/type, safe zip paths, and output digests.
- **LLM adapter:** resolve the current OpenAI-compatible provider/base/model/key configuration at call time. Existing key precedence is in `toolrank/openai_compat.py:15-45,185-201`, but the new adapter should receive an explicit non-secret config object so import-time environment capture does not affect tests. Redact keys and raw response reasoning.
- **Embedding adapter:** use an injected builder. Missing credentials fail before publication only when a changed passage store requires a new dense index. Do not fall back to a curl command containing the authorization header in argv.
- **Tests:** instantiate fake protocol implementations directly. No test should read `.mineru_token`, require provider environment variables, start a local server, download MinerU models, or make network calls. Adapter-specific integration tests must be separately marked and skipped unless explicitly enabled.

The repository contains an ignored `.mineru_token` path and bytecode remnants of an old batch script, but their contents were not read and they are not a supported source contract. Production should not silently discover a repository secret file.

### Exact test plan

Add tracked source tests; historical `.pyc` test names or ignored build artifacts are not coverage.

#### `tests/test_dynamic_kb_boundaries.py`

- `test_pipeline_uses_injected_converter_extractor_and_index_builder_without_environment`
- `test_import_and_map_check_do_not_construct_network_clients`
- `test_converter_rejects_missing_markdown`
- `test_converter_rejects_missing_structured_content_list`
- `test_converter_rejects_ambiguous_artifact_matches`
- `test_converter_rejects_invalid_utf8_instead_of_ignoring_it`
- `test_document_artifact_records_pdf_markdown_content_and_converter_digests`
- `test_extractor_envelope_rejects_wrong_paper_or_pdf_digest`
- `test_extractor_envelope_forbids_unknown_fields_and_scalar_coercion`
- `test_same_fixtures_in_different_candidate_order_produce_identical_ids_and_bytes`
- `test_provider_errors_leave_canonical_pointer_unchanged`
- `test_logs_and_manifests_never_contain_injected_secret_or_signed_url`

Use fake MinerU and LLM classes returning fixture `DocumentArtifact`/`RawExtractionEnvelope`. Monkeypatch socket/subprocess constructors to raise, proving the pure pipeline does not escape the boundary.

#### `tests/test_dynamic_kb_map_check.py`

- `test_all_seven_paper_relations_map_to_required_stances`
- `test_illegal_relation_for_knowledge_kind_is_rejected`
- parameterized `test_each_required_capability_field_is_required`
- `test_category_alias_normalizes_then_requires_valid_membership`
- `test_unmappable_category_is_not_coerced_to_unknown_unknowns`
- `test_explicit_unknown_unknowns_category_is_allowed`
- `test_ambiguous_tool_alias_is_rejected`
- `test_percent_and_fraction_units_normalize_explicitly`
- `test_missing_metric_unit_is_rejected_even_when_magnitude_looks_like_percent`
- parameterized `test_nan_infinity_and_out_of_range_metrics_are_rejected`
- `test_runtime_preserves_unit_and_aggregation_basis`
- `test_runtime_without_basis_is_rejected`
- `test_detected_count_cannot_exceed_total`
- `test_provenance_block_must_exist_in_document_artifact`
- `test_provenance_excerpt_digest_must_match`
- `test_table_metric_requires_exact_table_row_or_cell_locator`
- `test_equal_duplicate_is_idempotent`
- `test_same_identity_with_different_payload_is_rejected_as_conflict`
- `test_reject_record_has_stable_gate_code_field_path_and_safe_locator`

#### `tests/test_dynamic_kb_linkage.py`

- `test_same_paper_tool_and_category_links_capability_to_observation`
- parameterized `test_paper_tool_or_category_mismatch_does_not_link`
- `test_overall_metric_without_category_is_not_forced_into_category_link`
- `test_one_capability_can_link_multiple_exact_observations_deterministically`
- `test_persistent_observation_reference_survives_stage1_evaluation_id_changes`
- `test_projection_emits_only_evaluation_ids_present_in_current_stage1_lineage`
- `test_unprofiled_dataset_is_retained_but_marked_not_stage1_eligible`
- `test_unprojected_passage_remains_explicitly_unlinked_and_unweighted`
- `test_explicit_cross_tool_link_is_rejected_before_commit`
- retain and run all `tests/test_weighted_evidence_lineage.py` zero/one/many, invalid, cross-tool, and CEGO weight tests.

#### `tests/test_dynamic_kb_transaction.py`

- `test_validation_failure_does_not_create_or_move_current_pointer`
- parameterized failure injection after each staged store/index/manifest write proves the old pointer remains readable.
- `test_generation_is_reloaded_and_cross_validated_before_pointer_flip`
- `test_pointer_replace_failure_preserves_old_generation_and_cleans_temp_pointer`
- `test_post_flip_verification_failure_atomically_restores_old_pointer`
- `test_reader_resolves_pointer_once_and_never_mixes_store_generations`
- `test_passage_change_requires_matching_vector_store_digest_and_id_order`
- `test_vector_builder_failure_prevents_two_store_publication`
- `test_metric_only_commit_reuses_index_only_when_passage_digest_is_identical`
- `test_mixed_accepts_and_rejects_publish_complete_two_store_snapshot_and_reject_log`
- `test_all_rejected_writes_log_but_does_not_move_pointer`
- `test_clean_later_run_has_separate_log_and_cannot_leave_stale_current_rejects`
- `test_retry_with_same_inputs_is_generation_noop`
- `test_second_writer_cannot_enter_while_lock_is_live`
- parameterized crash-recovery tests for prepared, generation-published, pointer-committed-valid, and pointer-committed-invalid journal states.
- `test_rollback_failure_blocks_future_writes_with_recovery_required_status`
- extend the atomic helper fault test to assert parent-directory fsync/cleanup behavior where portable.

#### `tests/test_dynamic_kb_cli.py`

- `test_kb_ingest_help_documents_explicit_kb_root_and_no_key_option`
- `test_dry_run_never_creates_or_changes_current_pointer`
- `test_summary_and_json_outputs_report_counts_generation_and_rollback_status`
- `test_every_exit_status_matches_documented_failure_class`
- `test_missing_local_mineru_executable_has_clear_pre_mutation_error`
- `test_missing_cloud_or_llm_credential_has_clear_pre_mutation_error`
- `test_cli_output_never_contains_credentials_or_signed_urls`
- `test_installed_wheel_does_not_assume_source_relative_writable_toolcards`
- `test_validate_command_detects_cross_store_and_vector_digest_mismatch`
- `test_recover_command_is_idempotent`

#### Verification commands

```bash
python -m pytest -q \
  tests/test_dynamic_kb_boundaries.py \
  tests/test_dynamic_kb_map_check.py \
  tests/test_dynamic_kb_linkage.py \
  tests/test_dynamic_kb_transaction.py \
  tests/test_dynamic_kb_cli.py \
  tests/test_weighted_evidence_lineage.py \
  tests/test_profile_builder.py \
  tests/test_cleanup_quarantine.py
python -m pytest -q
python -m compileall -q toolrank tests
python -m toolrank.cli kb ingest --help
```

An explicitly enabled integration suite may exercise a pinned MinerU CLI/API and one real LLM provider, but it is not part of the default/offline quality gate.

### Related specs and task contracts

- `.trellis/spec/backend/lakes-scheduling-contract.md` is the active executable backend contract. The persistent-observation-to-runtime-evaluation projection must preserve its exact lineage and CEGO weighting rules.
- `.trellis/spec/guides/cross-layer-thinking-guide.md` applies because this feature crosses extraction producers, two persistence schemas, Stage-1 scene construction, passage retrieval, evidence cards, and action scoring.
- `.trellis/spec/guides/code-reuse-guide.md` supports generalizing the tested atomic writer in `profile_builder` and reusing `VALID_CATEGORIES`, `ALLOWED_RELATIONS`, Pydantic models, and existing evaluation-lineage helpers.
- `.trellis/tasks/07-13-paper-code-alignment/prd.md:314-344,384-387` defines the currently accepted R16/AC30 weighted-evidence lineage. Dynamic ingestion is additive and must not make unlinked evidence eligible for evaluation weight.
- General backend database/directory/error/logging/quality spec pages are currently placeholders, so they do not resolve the transaction-root, retention, error-code, or secret-redaction choices. Those choices need an implementation PRD/spec update before code is written.

## Caveats / Not Found

- No tracked production `toolrank/kb_extract/` package, MinerU adapter, dynamic-ingestion CLI, or tracked source tests exist. Only ignored `build/lib` output and bytecode remnants were found; they are not reliable source of truth.
- The current active PRD does not yet specify dynamic-KB acceptance criteria. This research is a proposed design; implementation should first add explicit requirements for strict provenance, generation-pointer loading, stable observation links, and offline tests.
- Current canonical performance schemas are permissive and lack field-level provenance/observation IDs. Backward-compatible schema evolution and migration of existing JSON need a separate concrete decision.
- The current engine reads fixed paths. True two-store atomic visibility requires all consumers to resolve one generation pointer once. A writer-only change cannot supply the guarantee.
- The current graph dataset-name index is declared but not populated. This is an adjacent retrieval defect, not permission to fix it as part of research.
- New datasets do not enter Stage 1 without compatible contract profiles. The paper does not define automatic profile extraction, so the pipeline must report this limitation rather than invent profiles.
- MinerU output filenames/formats and provider limits can change. Pin and record the tested MinerU version/backend; normalize through the adapter; do not import unversioned internal modules.
- Exact retention duration, lock timeout, maximum PDF/model payload sizes, prompt text/version, accepted dataset aliases, and supersession policy are not specified in the repository. They must be made explicit before implementation; the safe default is bounded input, no silent supersession, and retained prior generations.
- Atomic rename guarantees require the staging directory, generation directory, and pointer to be on the same filesystem. The implementation must validate/enforce that condition and fsync files/directories where supported.
- No credentials were read, and no external MinerU/LLM/embedding request was made during this research.
