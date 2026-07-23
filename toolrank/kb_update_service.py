"""Production Extract -> Map & Check -> Commit service for dynamic KB updates."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unicodedata
import uuid
from typing import Any, Protocol

from pydantic import ValidationError

from toolrank.categories import DASP10_CATEGORIES, normalize_category
from toolrank.dataset_kb import load_performance_db
from toolrank.kb_generation import (
    POINTER_FILE,
    REJECTS_DIR,
    atomic_replace_bytes,
    kb_writer_lock,
    load_current_generation,
    passage_bytes,
    publish_generation,
    reject_bytes,
)
from toolrank.kb_update_models import (
    DocumentArtifact,
    DocumentBlock,
    RawCapabilityClaim,
    RawKnowledgeExtraction,
    RawMetricClaim,
    RawSourceLocator,
    RejectCode,
    RejectRecord,
    canonical_json_bytes,
    normalize_evidence_text,
    stable_digest,
)
from toolrank.openai_compat import create_json_chat_completion, load_openai_client
from toolrank.passage_store import build_passage_vector_index, load_passage_store
from toolrank.schemas import (
    DatasetProfile,
    KnowledgeSourceLocator,
    PerformanceEntry,
    PerformanceKnowledgeBase,
    PerformanceObservation,
    ToolCard,
    ToolPerformanceObservation,
)
from toolrank.schemas_v2 import (
    ALLOWED_RELATIONS,
    ALLOWED_TAG_PREFIXES,
    Passage,
    PassageStore,
)
from toolrank.vector_store import VectorIndex


class MinerUConversionError(RuntimeError):
    pass


class KnowledgeExtractionError(RuntimeError):
    pass


class MapCheckEnvelopeError(RuntimeError):
    pass


class PdfConverter(Protocol):
    def convert(self, pdf: Path, work_dir: Path) -> DocumentArtifact: ...


class EvidenceExtractor(Protocol):
    def extract(self, document: DocumentArtifact) -> RawKnowledgeExtraction: ...


class PassageIndexBuilder(Protocol):
    def build(self, store: PassageStore) -> VectorIndex: ...


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _identity_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return re.sub(r"[^a-z0-9]+", "", normalized.casefold())


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", normalized)).strip("_")


def canonical_dataset_id(
    dataset_label: str,
    experiment_setting_id: str = "default",
    split_identity: str | None = None,
) -> str:
    identity = [
        normalize_evidence_text(unicodedata.normalize("NFKC", dataset_label)).casefold(),
        normalize_evidence_text(experiment_setting_id).casefold(),
        normalize_evidence_text(split_identity or "").casefold(),
    ]
    return "dataset_" + stable_digest(identity)[:32]


def _dataset_source_id(dataset_id: str) -> str:
    return "src_" + stable_digest([dataset_id])[:32]


class MinerUConverter:
    """Local MinerU adapter using the documented argv without a shell."""

    def __init__(
        self,
        *,
        command: str = "mineru",
        runner: Callable[..., Any] = subprocess.run,
        executable_resolver: Callable[[str], str | None] = shutil.which,
        version: str = "unknown",
    ) -> None:
        self._command = command
        self._runner = runner
        self._resolver = executable_resolver
        self._version = version

    def _resolve_command(self) -> str:
        resolved = self._resolver(self._command)
        if not resolved:
            raise MinerUConversionError(
                "MinerU executable not found. Install MinerU and ensure `mineru` is on PATH, "
                "or pass --mineru-command."
            )
        return resolved

    @staticmethod
    def _structured_rows(payload: object) -> list[dict[str, Any]]:
        rows: object = payload
        if isinstance(payload, dict):
            candidates = [
                payload.get(key)
                for key in ("content_list", "blocks")
                if key in payload
            ]
            if len(candidates) != 1:
                raise MinerUConversionError(
                    "MinerU structured output must contain exactly one content_list/blocks array"
                )
            rows = candidates[0]
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise MinerUConversionError("MinerU structured output is not a block list")
        return rows

    @staticmethod
    def _block_text(row: dict[str, Any]) -> tuple[str, list[list[str]]]:
        raw_rows = row.get("table_rows") or row.get("rows") or []
        table_rows: list[list[str]] = []
        if isinstance(raw_rows, list):
            for raw_row in raw_rows:
                if isinstance(raw_row, list):
                    table_rows.append([normalize_evidence_text(str(cell)) for cell in raw_row])
        for key in ("text", "content", "markdown", "html"):
            value = row.get(key)
            if isinstance(value, str) and value.strip():
                return normalize_evidence_text(value), table_rows
        flattened = " ".join(cell for values in table_rows for cell in values if cell)
        return normalize_evidence_text(flattened), table_rows

    @classmethod
    def _blocks(cls, payload: object) -> list[DocumentBlock]:
        blocks: list[DocumentBlock] = []
        for ordinal, row in enumerate(cls._structured_rows(payload)):
            text, table_rows = cls._block_text(row)
            if not text:
                continue
            block_type = _slug(str(row.get("type") or row.get("block_type") or "text")) or "text"
            raw_page = row.get("page_number")
            if raw_page is None and row.get("page_idx") is not None:
                raw_page = int(row["page_idx"]) + 1
            page_number = int(raw_page) if raw_page is not None else None
            if page_number is not None and page_number < 1:
                raise MinerUConversionError("MinerU block page number must be positive")
            block_id = str(row.get("block_id") or row.get("id") or "").strip()
            if not block_id:
                block_id = "block_" + stable_digest(
                    [page_number, block_type, ordinal, _sha256(text.encode("utf-8"))]
                )[:24]
            table_id = row.get("table_id")
            blocks.append(
                DocumentBlock(
                    block_id=block_id,
                    page_number=page_number,
                    block_type=block_type,
                    ordinal=ordinal,
                    normalized_text=text,
                    text_sha256=_sha256(text.encode("utf-8")),
                    table_id=str(table_id) if table_id is not None else None,
                    table_rows=table_rows,
                )
            )
        if not blocks:
            raise MinerUConversionError("MinerU structured output contained no textual blocks")
        return blocks

    def convert(self, pdf: Path, work_dir: Path) -> DocumentArtifact:
        pdf = Path(pdf)
        if not pdf.is_file() or pdf.suffix.casefold() != ".pdf":
            raise MinerUConversionError("input must be an existing local PDF file")
        pdf_bytes = pdf.read_bytes()
        if not pdf_bytes:
            raise MinerUConversionError("input PDF is empty")
        command = self._resolve_command()
        Path(work_dir).mkdir(parents=True, exist_ok=True)
        output_dir = Path(work_dir) / "mineru"
        if output_dir.exists():
            raise MinerUConversionError("private MinerU output directory already exists")
        argv = [command, "-p", str(pdf), "-o", str(output_dir)]
        try:
            result = self._runner(
                argv,
                text=True,
                capture_output=True,
                check=False,
            )
        except FileNotFoundError as exc:
            raise MinerUConversionError(f"MinerU executable not found: {command}") from exc
        except OSError as exc:
            raise MinerUConversionError(f"MinerU could not be started: {exc}") from exc
        if result.returncode != 0:
            detail = normalize_evidence_text(str(result.stderr or result.stdout or ""))[:240]
            raise MinerUConversionError(
                f"MinerU conversion failed with exit code {result.returncode}: {detail or 'no diagnostic'}"
            )
        markdown_paths = sorted(path for path in output_dir.rglob("*.md") if path.is_file())
        structured_paths = sorted(
            path
            for path in output_dir.rglob("*.json")
            if path.is_file() and "content_list" in path.stem.casefold()
        )
        if len(markdown_paths) != 1:
            raise MinerUConversionError(
                f"MinerU output must contain exactly one Markdown file; found {len(markdown_paths)}"
            )
        if len(structured_paths) != 1:
            raise MinerUConversionError(
                "MinerU output must contain exactly one structured content-list JSON file; "
                f"found {len(structured_paths)}"
            )
        try:
            markdown_bytes = markdown_paths[0].read_bytes()
            markdown_text = markdown_bytes.decode("utf-8")
            structured_bytes = structured_paths[0].read_bytes()
            structured = json.loads(structured_bytes.decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise MinerUConversionError("MinerU output is not valid UTF-8") from exc
        except json.JSONDecodeError as exc:
            raise MinerUConversionError("MinerU structured output is not valid JSON") from exc
        if not markdown_text.strip():
            raise MinerUConversionError("MinerU Markdown output is empty")
        pdf_digest = _sha256(pdf_bytes)
        return DocumentArtifact(
            paper_id=f"paper_{pdf_digest[:32]}",
            pdf_sha256=pdf_digest,
            pdf_size_bytes=len(pdf_bytes),
            converter_name="mineru",
            converter_version=self._version,
            markdown_relative_path=markdown_paths[0].relative_to(output_dir).as_posix(),
            markdown_sha256=_sha256(markdown_bytes),
            markdown_text=markdown_text,
            structured_relative_path=structured_paths[0].relative_to(output_dir).as_posix(),
            structured_sha256=_sha256(structured_bytes),
            blocks=self._blocks(structured),
        )


_EXTRACTION_SYSTEM_PROMPT = """You extract auditable smart-contract analyzer knowledge.
Return one JSON object with both channels: dataset_claims and capability_claims.
Every item must cite an exact MinerU block and excerpt. Do not infer units, counts,
categories, tools, relations, applicability, or runtime bases that the paper omits.
Do not return reasoning or prose outside the JSON object."""


class OpenAIKnowledgeExtractor:
    """Strict two-channel extractor over the existing OpenAI-compatible client."""

    def __init__(
        self,
        *,
        model: str,
        client: object | None = None,
        client_factory: Callable[[], object | None] = load_openai_client,
        completion_fn: Callable[..., dict | None] = create_json_chat_completion,
    ) -> None:
        if not model.strip():
            raise KnowledgeExtractionError("an explicit LLM model is required")
        self._model = model.strip()
        self._client = client
        self._client_factory = client_factory
        self._completion = completion_fn

    def extract(self, document: DocumentArtifact) -> RawKnowledgeExtraction:
        client = self._client or self._client_factory()
        if client is None:
            raise KnowledgeExtractionError(
                "OpenAI-compatible LLM configuration is unavailable; configure the endpoint and API key"
            )
        block_index = [
            {
                "block_id": block.block_id,
                "page_number": block.page_number,
                "block_type": block.block_type,
                "table_id": block.table_id,
                "text": block.normalized_text,
            }
            for block in document.blocks
        ]
        user_prompt = json.dumps(
            {
                "paper_id": document.paper_id,
                "pdf_sha256": document.pdf_sha256,
                "markdown": document.markdown_text,
                "blocks": block_index,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        payload = self._completion(
            client=client,
            model=self._model,
            system_prompt=_EXTRACTION_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.0,
            schema=RawKnowledgeExtraction.model_json_schema(),
            raise_on_error=True,
        )
        if payload is None:
            raise KnowledgeExtractionError("LLM extraction returned no JSON object")
        try:
            extraction = RawKnowledgeExtraction.model_validate(payload)
        except ValidationError as exc:
            raise KnowledgeExtractionError(f"LLM extraction schema validation failed: {exc}") from exc
        if (
            extraction.paper_id != document.paper_id
            or extraction.pdf_sha256 != document.pdf_sha256
        ):
            raise KnowledgeExtractionError("LLM extraction paper/PDF digest mismatch")
        return extraction


class DensePassageIndexBuilder:
    """Production embedding boundary; tests inject an offline builder."""

    def __init__(self, **embedding_kwargs: Any) -> None:
        embedding_kwargs.setdefault("allow_curl_fallback", False)
        self._embedding_kwargs = embedding_kwargs

    def build(self, store: PassageStore) -> VectorIndex:
        return build_passage_vector_index(store, **self._embedding_kwargs)


class _CandidateRejected(Exception):
    def __init__(
        self,
        code: RejectCode,
        gate: str,
        field_path: str,
        message: str,
        locator_key: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.gate = gate
        self.field_path = field_path
        self.message = message
        self.locator_key = locator_key


class ToolAliasResolver:
    def __init__(self, cards: Sequence[ToolCard]) -> None:
        aliases: dict[str, set[str]] = {}
        for card in cards:
            for alias in (card.tool_id, card.tool_name):
                key = _identity_text(alias)
                if key:
                    aliases.setdefault(key, set()).add(card.tool_id)
        self._aliases = aliases

    def resolve(self, label: str) -> str:
        owners = self._aliases.get(_identity_text(label), set())
        if not owners:
            raise _CandidateRejected(
                RejectCode.TOOL_UNKNOWN,
                "identity",
                "tool_label",
                f"unknown tool label: {normalize_evidence_text(label)[:80]}",
            )
        if len(owners) != 1:
            raise _CandidateRejected(
                RejectCode.TOOL_ALIAS_AMBIGUOUS,
                "identity",
                "tool_label",
                "tool alias resolves to more than one canonical tool",
            )
        return next(iter(owners))


def _canonical_category(label: str) -> str:
    raw_category = _slug(label)
    category = normalize_category(label)
    if (
        category not in DASP10_CATEGORIES
        or (category == "unknown_unknowns" and raw_category != "unknown_unknowns")
    ):
        raise _CandidateRejected(
            RejectCode.CATEGORY_UNKNOWN,
            "category",
            "category_label",
            f"unrecognized DASP category: {normalize_evidence_text(label)[:80]}",
        )
    return category


def _enum_token(value: str) -> str:
    return _slug(value)


_RELATIONS = {
    "supports_owner",
    "owner_complements",
    "opposes_owner",
    "owner_ineligible",
    "owner_stronger",
    "owner_weaker",
    "evidence_gap",
}
_KNOWLEDGE_KINDS = set(ALLOWED_RELATIONS)
_ACTION_SCOPE_ALIASES = {
    "single_tool": "SINGLE_TOOL",
    "plan_composition": "PLAN_COMPOSITION",
    "continue_hedge": "CONTINUE_HEDGE",
}
_ACTION_ORDER = {"SINGLE_TOOL": 0, "PLAN_COMPOSITION": 1, "CONTINUE_HEDGE": 2}
_EVIDENCE_BASES = {
    "benchmark_result",
    "paired_ablation",
    "official_documentation",
    "reproducible_issue",
    "manual_curation",
}
_SOURCE_RELIABILITIES = {
    "peer_reviewed",
    "artifact",
    "manual_curated",
    "official_tool_doc",
    "maintainer_issue",
    "internal_eval",
    "community_report",
}
_RATE_UNITS = {
    "%": "percent",
    "percent": "percent",
    "percentage": "percent",
    "fraction": "fraction",
    "rate": "fraction",
    "ratio": "fraction",
}
_TIME_UNITS = {
    "s": 1.0,
    "sec": 1.0,
    "second": 1.0,
    "seconds": 1.0,
    "ms": 0.001,
    "millisecond": 0.001,
    "milliseconds": 0.001,
    "min": 60.0,
    "minute": 60.0,
    "minutes": 60.0,
    "h": 3600.0,
    "hour": 3600.0,
    "hours": 3600.0,
}
_RUNTIME_BASES = {
    "per_contract",
    "per_file",
    "per_project",
    "total_benchmark",
    "per_kloc",
    "campaign_cap",
}


@dataclass(frozen=True)
class MapCheckResult:
    observations: list[PerformanceObservation]
    passages: list[Passage]
    datasets: dict[str, DatasetProfile]
    rejects: list[RejectRecord]


class KnowledgeMapper:
    """Single owner for normalization, provenance, gates, and stable links."""

    def __init__(
        self,
        toolcards: Sequence[ToolCard],
        *,
        profiled_dataset_names: set[str],
    ) -> None:
        self._tools = ToolAliasResolver(toolcards)
        self._profiled_names = {_identity_text(name) for name in profiled_dataset_names}

    @staticmethod
    def _locator(
        document: DocumentArtifact,
        raw: RawSourceLocator,
        *,
        require_table_cell: bool,
    ) -> KnowledgeSourceLocator:
        block = next((item for item in document.blocks if item.block_id == raw.block_id), None)
        if block is None:
            raise _CandidateRejected(
                RejectCode.PROVENANCE_NOT_FOUND,
                "provenance",
                "source_locator.block_id",
                "source locator block does not exist in the MinerU artifact",
                raw.block_id,
            )
        excerpt = normalize_evidence_text(raw.excerpt)
        if excerpt not in block.normalized_text:
            raise _CandidateRejected(
                RejectCode.PROVENANCE_NOT_FOUND,
                "provenance",
                "source_locator.excerpt",
                "source excerpt does not occur in the located document block",
                raw.block_id,
            )
        excerpt_digest = _sha256(excerpt.encode("utf-8"))
        if raw.excerpt_sha256 is not None and raw.excerpt_sha256 != excerpt_digest:
            raise _CandidateRejected(
                RejectCode.PROVENANCE_DIGEST_MISMATCH,
                "provenance",
                "source_locator.excerpt_sha256",
                "source excerpt digest does not match normalized excerpt",
                raw.block_id,
            )
        if raw.page_number is not None and raw.page_number != block.page_number:
            raise _CandidateRejected(
                RejectCode.PROVENANCE_NOT_FOUND,
                "provenance",
                "source_locator.page_number",
                "source locator page does not match the MinerU block",
                raw.block_id,
            )
        if raw.block_type is not None and _slug(raw.block_type) != block.block_type:
            raise _CandidateRejected(
                RejectCode.PROVENANCE_NOT_FOUND,
                "provenance",
                "source_locator.block_type",
                "source locator block type does not match MinerU output",
                raw.block_id,
            )
        if raw.table_id is not None and raw.table_id != block.table_id:
            raise _CandidateRejected(
                RejectCode.PROVENANCE_NOT_FOUND,
                "provenance",
                "source_locator.table_id",
                "source locator table does not match MinerU output",
                raw.block_id,
            )
        table_evidence = (
            require_table_cell
            or _slug(block.block_type) == "table"
            or block.table_id is not None
            or bool(block.table_rows)
        )
        if table_evidence and (raw.row is None or raw.column is None):
            raise _CandidateRejected(
                RejectCode.REQUIRED_FIELD_MISSING,
                "provenance",
                "source_locator",
                "table evidence requires exact row and column coordinates",
                raw.block_id,
            )
        if table_evidence and not block.table_rows:
            raise _CandidateRejected(
                RejectCode.PROVENANCE_NOT_FOUND,
                "provenance",
                "source_locator.row",
                "MinerU table structure is unavailable for exact cell validation",
                raw.block_id,
            )
        if block.table_rows and raw.row is not None and raw.column is not None:
            if raw.row >= len(block.table_rows) or raw.column >= len(block.table_rows[raw.row]):
                raise _CandidateRejected(
                    RejectCode.PROVENANCE_NOT_FOUND,
                    "provenance",
                    "source_locator.row",
                    "table row/cell is outside the MinerU structured table",
                    raw.block_id,
                )
            if excerpt not in normalize_evidence_text(block.table_rows[raw.row][raw.column]):
                raise _CandidateRejected(
                    RejectCode.PROVENANCE_NOT_FOUND,
                    "provenance",
                    "source_locator.excerpt",
                    "table excerpt does not occur in the located cell",
                    raw.block_id,
                )
        return KnowledgeSourceLocator(
            block_id=block.block_id,
            page_number=block.page_number,
            block_type=block.block_type,
            table_id=block.table_id,
            row=raw.row,
            column=raw.column,
            excerpt=excerpt,
            excerpt_sha256=excerpt_digest,
        )

    @staticmethod
    def _reject(
        *,
        channel: str,
        candidate: object,
        paper_id: str,
        error: _CandidateRejected,
    ) -> RejectRecord:
        candidate_payload = (
            candidate.model_dump(mode="json")
            if hasattr(candidate, "model_dump")
            else candidate
        )
        return RejectRecord(
            channel=channel,
            candidate_digest=stable_digest(candidate_payload),
            gate=error.gate,
            reason_code=error.code,
            field_path=error.field_path,
            safe_message=normalize_evidence_text(error.message)[:240],
            paper_id=paper_id,
            locator_key=error.locator_key,
        )

    def _metric(
        self,
        document: DocumentArtifact,
        extraction: RawKnowledgeExtraction,
        claim: RawMetricClaim,
    ) -> tuple[PerformanceObservation, DatasetProfile]:
        tool = self._tools.resolve(claim.tool_label)
        category = (
            _canonical_category(claim.category_label)
            if claim.category_label is not None
            else None
        )
        if claim.metric_kind in {"category_rate", "category_count"} and category is None:
            raise _CandidateRejected(
                RejectCode.REQUIRED_FIELD_MISSING,
                "metric",
                "category_label",
                f"{claim.metric_kind} requires a category",
            )
        locator = self._locator(
            document,
            claim.source_locator,
            require_table_cell=claim.source_locator.block_type == "table",
        )
        unit_token = claim.unit.strip().casefold()
        normalized_unit: str
        normalized_value: float | None = None
        original_value = float(claim.value) if claim.value is not None else None
        runtime_basis: str | None = None
        detected = claim.detected
        total = claim.total
        if claim.metric_kind == "category_count":
            if _slug(unit_token) != "count":
                raise _CandidateRejected(
                    RejectCode.METRIC_UNIT_AMBIGUOUS,
                    "metric",
                    "unit",
                    "count metrics require an explicit count unit",
                    locator.locator_key,
                )
            if detected is None or total is None or detected > total:
                raise _CandidateRejected(
                    RejectCode.METRIC_COUNT_INCONSISTENT,
                    "metric",
                    "detected",
                    "detected/total counts are missing or detected exceeds total",
                    locator.locator_key,
                )
            normalized_unit = "count"
        elif claim.metric_kind == "runtime":
            factor = _TIME_UNITS.get(unit_token) or _TIME_UNITS.get(_slug(unit_token))
            if factor is None:
                raise _CandidateRejected(
                    RejectCode.METRIC_UNIT_AMBIGUOUS,
                    "metric",
                    "unit",
                    "runtime unit is missing or unsupported",
                    locator.locator_key,
                )
            runtime_basis = _enum_token(claim.runtime_basis or "")
            if runtime_basis not in _RUNTIME_BASES:
                raise _CandidateRejected(
                    RejectCode.METRIC_BASIS_AMBIGUOUS,
                    "metric",
                    "runtime_basis",
                    "runtime requires an explicit supported aggregation basis",
                    locator.locator_key,
                )
            normalized_value = float(claim.value) * factor
            if not math.isfinite(normalized_value) or normalized_value <= 0:
                raise _CandidateRejected(
                    RejectCode.METRIC_RANGE,
                    "metric",
                    "value",
                    "runtime must normalize to positive finite seconds",
                    locator.locator_key,
                )
            normalized_unit = "seconds"
        else:
            rate_unit = _RATE_UNITS.get(unit_token) or _RATE_UNITS.get(_slug(unit_token))
            if rate_unit is None:
                raise _CandidateRejected(
                    RejectCode.METRIC_UNIT_AMBIGUOUS,
                    "metric",
                    "unit",
                    "rate unit must explicitly be percent or fraction",
                    locator.locator_key,
                )
            normalized_value = float(claim.value)
            if rate_unit == "percent":
                normalized_value /= 100.0
            if not math.isfinite(normalized_value) or not 0.0 <= normalized_value <= 1.0:
                raise _CandidateRejected(
                    RejectCode.METRIC_RANGE,
                    "metric",
                    "value",
                    "rate must normalize into [0, 1]",
                    locator.locator_key,
                )
            normalized_unit = "fraction"
        dataset_id = canonical_dataset_id(
            claim.dataset.dataset_label,
            claim.dataset.experiment_setting_id,
            claim.dataset.split_identity,
        )
        source_id = _dataset_source_id(dataset_id)
        stage1_eligible = _identity_text(claim.dataset.dataset_label) in self._profiled_names
        observation_id = "perf_" + stable_digest(
            [
                extraction.paper_id,
                dataset_id,
                tool,
                claim.metric_kind,
                category,
                locator.locator_key,
            ]
        )[:32]
        observation = PerformanceObservation(
            observation_id=observation_id,
            paper_id=extraction.paper_id,
            publication_date=extraction.publication_date,
            source_id=source_id,
            canonical_dataset_id=dataset_id,
            dataset_name=claim.dataset.dataset_label,
            tool=tool,
            metric_kind=claim.metric_kind,
            category=category,
            value=normalized_value,
            detected=detected,
            total=total,
            normalized_unit=normalized_unit,
            original_value=original_value,
            original_unit=claim.unit,
            runtime_basis=runtime_basis,
            source_locator=locator,
            stage1_eligible=stage1_eligible,
            stage1_ineligible_reason=(None if stage1_eligible else "DATASET_PROFILE_MISSING"),
        )
        profile = DatasetProfile(
            dataset_name=claim.dataset.dataset_label,
            solc=claim.dataset.solc,
            contract_count_total=claim.dataset.contract_count_total,
            domain_tags=claim.dataset.domain_tags,
            what_contracts=claim.dataset.what_contracts,
            how_collected=claim.dataset.how_collected,
        )
        return observation, profile

    def _capability_base(
        self,
        document: DocumentArtifact,
        extraction: RawKnowledgeExtraction,
        claim: RawCapabilityClaim,
    ) -> Passage:
        owner = self._tools.resolve(claim.owner_tool_label)
        counterparts = sorted(
            {self._tools.resolve(label) for label in claim.counterpart_tool_labels}
        )
        category = _canonical_category(claim.category_label)
        relation = _enum_token(claim.relation_to_owner)
        if relation not in _RELATIONS:
            raise _CandidateRejected(
                RejectCode.RELATION_ILLEGAL,
                "relation",
                "relation_to_owner",
                "relation_to_owner is not one of the seven paper relations",
            )
        knowledge_kind = _enum_token(claim.knowledge_kind)
        if knowledge_kind not in _KNOWLEDGE_KINDS:
            raise _CandidateRejected(
                RejectCode.RELATION_ILLEGAL,
                "relation",
                "knowledge_kind",
                "knowledge_kind is unsupported",
            )
        if relation not in ALLOWED_RELATIONS[knowledge_kind]:
            raise _CandidateRejected(
                RejectCode.RELATION_ILLEGAL,
                "relation",
                "relation_to_owner",
                "relation is illegal for the selected knowledge kind",
            )
        scopes: list[str] = []
        for raw_scope in claim.action_scope:
            scope = _ACTION_SCOPE_ALIASES.get(_enum_token(raw_scope))
            if scope is None:
                raise _CandidateRejected(
                    RejectCode.ACTION_SCOPE_ILLEGAL,
                    "scope",
                    "action_scope",
                    "action scope is unsupported",
                )
            if scope not in scopes:
                scopes.append(scope)
        scopes.sort(key=_ACTION_ORDER.__getitem__)
        tags: list[str] = []
        for raw_tag in claim.applicability_tags:
            prefix, separator, raw_value = raw_tag.partition(":")
            prefix = prefix.strip().casefold()
            value = normalize_evidence_text(raw_value).casefold()
            tag = f"{prefix}:{value}"
            if not separator or not value or not tag.startswith(ALLOWED_TAG_PREFIXES):
                raise _CandidateRejected(
                    RejectCode.TAG_ILLEGAL,
                    "tag",
                    "applicability_tags",
                    "applicability tag has an unsupported namespace or empty value",
                )
            if tag not in tags:
                tags.append(tag)
        tags.sort()
        evidence_basis = _enum_token(claim.evidence_basis)
        source_reliability = _enum_token(claim.source_reliability)
        if evidence_basis not in _EVIDENCE_BASES:
            raise _CandidateRejected(
                RejectCode.CANONICAL_SCHEMA,
                "schema",
                "evidence_basis",
                "unsupported evidence basis",
            )
        if source_reliability not in _SOURCE_RELIABILITIES:
            raise _CandidateRejected(
                RejectCode.CANONICAL_SCHEMA,
                "schema",
                "source_reliability",
                "unsupported source reliability",
            )
        locator = self._locator(
            document,
            claim.source_locator,
            require_table_cell=claim.source_locator.block_type == "table",
        )
        claim_text = normalize_evidence_text(claim.claim_text)
        limitations = normalize_evidence_text(claim.limitations_text)
        passage_id = "p_" + stable_digest(
            [
                extraction.paper_id,
                owner,
                category,
                relation,
                tags,
                claim_text,
                locator.locator_key,
            ]
        )[:32]
        try:
            return Passage(
                passage_id=passage_id,
                source_id=extraction.paper_id,
                owner_tool=owner,
                counterpart_tool_ids=counterparts,
                category=category,
                knowledge_kind=knowledge_kind,
                action_scope=scopes,
                applicability_tags=tags,
                relation_to_owner=relation,
                evidence_basis=evidence_basis,
                source_reliability=source_reliability,
                claim_text=claim_text,
                limitations_text=limitations,
                source_excerpt=locator.excerpt,
                linked_evaluation_ids=[],
                paper_id=extraction.paper_id,
                source_locator=locator,
                linked_performance_observation_ids=[],
                performance_observation_refs=[],
            )
        except ValidationError as exc:
            raise _CandidateRejected(
                RejectCode.CANONICAL_SCHEMA,
                "schema",
                "capability_claim",
                f"canonical passage validation failed: {exc.errors()[0].get('msg', 'invalid')}",
                locator.locator_key,
            ) from exc

    def map_and_check(
        self,
        document: DocumentArtifact,
        extraction: RawKnowledgeExtraction,
    ) -> MapCheckResult:
        if (
            extraction.paper_id != document.paper_id
            or extraction.pdf_sha256 != document.pdf_sha256
        ):
            raise MapCheckEnvelopeError("extraction paper/PDF digest does not match document")
        observations: dict[str, PerformanceObservation] = {}
        datasets: dict[str, DatasetProfile] = {}
        passages: dict[str, Passage] = {}
        rejects: list[RejectRecord] = []
        for claim in extraction.dataset_claims:
            try:
                observation, profile = self._metric(document, extraction, claim)
                prior = observations.get(observation.observation_id)
                if prior is not None and prior != observation:
                    raise _CandidateRejected(
                        RejectCode.DUPLICATE_CONFLICT,
                        "deduplication",
                        "observation_id",
                        "stable observation identity has conflicting content",
                        observation.source_locator.locator_key,
                    )
                observations[observation.observation_id] = observation
                prior_profile = datasets.get(observation.canonical_dataset_id)
                if prior_profile is not None and prior_profile != profile:
                    raise _CandidateRejected(
                        RejectCode.DUPLICATE_CONFLICT,
                        "deduplication",
                        "dataset",
                        "canonical dataset identity has conflicting profile content",
                        observation.source_locator.locator_key,
                    )
                datasets[observation.canonical_dataset_id] = profile
            except _CandidateRejected as exc:
                rejects.append(
                    self._reject(
                        channel="dataset",
                        candidate=claim,
                        paper_id=extraction.paper_id,
                        error=exc,
                    )
                )
            except (ValidationError, ValueError, TypeError) as exc:
                rejects.append(
                    self._reject(
                        channel="dataset",
                        candidate=claim,
                        paper_id=extraction.paper_id,
                        error=_CandidateRejected(
                            RejectCode.CANONICAL_SCHEMA,
                            "schema",
                            "dataset_claim",
                            f"canonical metric validation failed: {str(exc)[:160]}",
                        ),
                    )
                )
        for claim in extraction.capability_claims:
            try:
                passage = self._capability_base(document, extraction, claim)
                matching = sorted(
                    (
                        observation
                        for observation in observations.values()
                        if observation.paper_id == extraction.paper_id
                        and observation.tool == passage.owner_tool
                        and observation.category == passage.category
                        and observation.metric_kind
                        in {"category_count", "category_rate", "precision", "recall"}
                    ),
                    key=lambda item: item.observation_id,
                )
                passage = passage.model_copy(
                    update={
                        "linked_performance_observation_ids": [
                            item.observation_id for item in matching
                        ],
                        "performance_observation_refs": [item.to_ref() for item in matching],
                    }
                )
                passage = Passage.model_validate(passage.model_dump(mode="json"))
                prior = passages.get(passage.passage_id)
                if prior is not None and prior != passage:
                    raise _CandidateRejected(
                        RejectCode.DUPLICATE_CONFLICT,
                        "deduplication",
                        "passage_id",
                        "stable passage identity has conflicting content",
                        passage.source_locator.locator_key if passage.source_locator else None,
                    )
                passages[passage.passage_id] = passage
            except _CandidateRejected as exc:
                rejects.append(
                    self._reject(
                        channel="capability",
                        candidate=claim,
                        paper_id=extraction.paper_id,
                        error=exc,
                    )
                )
            except (ValidationError, ValueError, TypeError) as exc:
                rejects.append(
                    self._reject(
                        channel="capability",
                        candidate=claim,
                        paper_id=extraction.paper_id,
                        error=_CandidateRejected(
                            RejectCode.CANONICAL_SCHEMA,
                            "schema",
                            "capability_claim",
                            f"canonical passage validation failed: {str(exc)[:160]}",
                        ),
                    )
                )
        return MapCheckResult(
            observations=sorted(observations.values(), key=lambda item: item.observation_id),
            passages=sorted(passages.values(), key=lambda item: item.passage_id),
            datasets=dict(sorted(datasets.items())),
            rejects=sorted(
                rejects,
                key=lambda item: (
                    item.channel,
                    item.candidate_digest,
                    item.reason_code.value,
                    item.field_path,
                ),
            ),
        )


def _existing_dataset_id(entry: PerformanceEntry) -> str:
    return entry.canonical_dataset_id or canonical_dataset_id(
        entry.dataset_profile.dataset_name
    )


def _aggregate_observations(entry: PerformanceEntry) -> list[ToolPerformanceObservation]:
    rows = [item.model_copy(deep=True) for item in entry.tool_performance_data]
    by_tool = {_identity_text(item.tool_name): item for item in rows}
    for observation in sorted(
        entry.performance_observations,
        key=lambda item: (
            item.publication_date or "",
            item.paper_id,
            item.observation_id,
        ),
    ):
        key = _identity_text(observation.tool)
        row = by_tool.get(key)
        if row is None:
            row = ToolPerformanceObservation(
                tool_name=observation.tool,
                metrics={},
                observation_ids=[],
            )
            rows.append(row)
            by_tool[key] = row
        metrics = row.metrics.model_dump(mode="python", by_alias=False)
        scores = dict(row.vulnerability_scores or {})
        counts = {
            category: value.model_dump(mode="python")
            for category, value in (row.vulnerability_score_counts or {}).items()
        }
        if observation.category is None and observation.metric_kind in {
            "precision",
            "recall",
            "f1",
            "accuracy",
        }:
            metrics[observation.metric_kind] = observation.value
        elif observation.metric_kind == "runtime":
            metrics["execution_time_avg"] = observation.value
            metrics["runtime_unit"] = "seconds"
            metrics["runtime_basis"] = observation.runtime_basis
        elif observation.category is not None and observation.metric_kind == "category_count":
            counts[observation.category] = {
                "detected": observation.detected,
                "total": observation.total,
            }
            if observation.total:
                scores[observation.category] = observation.detected / observation.total
        elif observation.category is not None and observation.value is not None:
            scores[observation.category] = observation.value
        updated = ToolPerformanceObservation(
            tool_name=row.tool_name,
            metrics=metrics,
            vulnerability_scores=scores or None,
            vulnerability_score_counts=counts or None,
            observation_ids=sorted({*row.observation_ids, observation.observation_id}),
            evidence_source=(
                f"{observation.paper_id}:{observation.source_locator.locator_key}"
            ),
        )
        row_index = rows.index(row)
        rows[row_index] = updated
        by_tool[key] = updated
    return rows


@dataclass(frozen=True)
class MergedSnapshots:
    performance_kb: PerformanceKnowledgeBase
    passage_store: PassageStore
    rejects: list[RejectRecord]
    accepted_observations: int
    accepted_passages: int


def merge_snapshots(
    base_kb: PerformanceKnowledgeBase,
    base_store: PassageStore,
    mapped: MapCheckResult,
) -> MergedSnapshots:
    entries = [entry.model_copy(deep=True) for entry in base_kb.entries]
    by_dataset: dict[str, PerformanceEntry] = {}
    for index, entry in enumerate(entries):
        dataset_id = _existing_dataset_id(entry)
        if dataset_id in by_dataset:
            raise ValueError("baseline contains duplicate canonical dataset identities")
        eligible = entry.stage1_eligible
        normalized = entry.model_copy(
            update={
                "canonical_dataset_id": dataset_id,
                "stage1_eligible": True if eligible is None else eligible,
                "stage1_ineligible_reason": (
                    None if eligible is None or eligible else entry.stage1_ineligible_reason
                ),
            }
        )
        entries[index] = normalized
        by_dataset[dataset_id] = normalized
    merge_rejects: list[RejectRecord] = []
    committed_observations: dict[str, PerformanceObservation] = {}
    accepted_observations = 0
    for raw_observation in mapped.observations:
        observation = raw_observation
        entry = by_dataset.get(observation.canonical_dataset_id)
        if entry is None:
            entry = PerformanceEntry(
                source_id=observation.source_id,
                publication_date=observation.publication_date,
                canonical_dataset_id=observation.canonical_dataset_id,
                stage1_eligible=observation.stage1_eligible,
                stage1_ineligible_reason=observation.stage1_ineligible_reason,
                dataset_profile=mapped.datasets[observation.canonical_dataset_id],
                tool_performance_data=[],
                performance_observations=[],
            )
            entries.append(entry)
            by_dataset[observation.canonical_dataset_id] = entry
        elif observation.source_id != entry.source_id:
            observation = PerformanceObservation.model_validate(
                observation.model_copy(
                    update={"source_id": entry.source_id}
                ).model_dump(mode="json")
            )
        existing = {
            item.observation_id: item for item in entry.performance_observations
        }.get(observation.observation_id)
        if existing is not None and existing != observation:
            merge_rejects.append(
                RejectRecord(
                    channel="dataset",
                    candidate_digest=stable_digest(observation.model_dump(mode="json")),
                    gate="deduplication",
                    reason_code=RejectCode.DUPLICATE_CONFLICT,
                    field_path="observation_id",
                    safe_message="stable observation identity conflicts with the current generation",
                    paper_id=observation.paper_id,
                    locator_key=observation.source_locator.locator_key,
                )
            )
            continue
        if existing is None:
            entry.performance_observations.append(observation)
        accepted_observations += 1
        committed_observations[observation.observation_id] = observation
        entry.performance_observations.sort(key=lambda item: item.observation_id)
        entry.publication_date = max(
            filter(None, [entry.publication_date, observation.publication_date]),
            default=None,
        )
        entry.tool_performance_data = _aggregate_observations(entry)
    entries.sort(key=lambda item: (_existing_dataset_id(item), item.source_id))
    passages = {passage.passage_id: passage for passage in base_store.passages}
    accepted_passages = 0
    for mapped_passage in mapped.passages:
        linked = [
            committed_observations[observation_id]
            for observation_id in mapped_passage.linked_performance_observation_ids
            if observation_id in committed_observations
        ]
        passage = Passage.model_validate(
            mapped_passage.model_copy(
                update={
                    "linked_performance_observation_ids": [
                        observation.observation_id for observation in linked
                    ],
                    "performance_observation_refs": [
                        observation.to_ref() for observation in linked
                    ],
                }
            ).model_dump(mode="json")
        )
        existing = passages.get(passage.passage_id)
        if existing is None:
            passages[passage.passage_id] = passage
            accepted_passages += 1
            continue
        if existing == passage:
            accepted_passages += 1
            continue
        existing_core = existing.model_dump(
            exclude={"linked_performance_observation_ids", "performance_observation_refs"}
        )
        new_core = passage.model_dump(
            exclude={"linked_performance_observation_ids", "performance_observation_refs"}
        )
        if existing_core == new_core:
            refs = {
                ref.observation_id: ref
                for ref in [
                    *existing.performance_observation_refs,
                    *passage.performance_observation_refs,
                ]
            }
            ordered_refs = [refs[key] for key in sorted(refs)]
            passages[passage.passage_id] = Passage.model_validate(
                existing.model_copy(
                    update={
                        "linked_performance_observation_ids": [
                            ref.observation_id for ref in ordered_refs
                        ],
                        "performance_observation_refs": ordered_refs,
                    }
                ).model_dump(mode="json")
            )
            accepted_passages += 1
            continue
        merge_rejects.append(
            RejectRecord(
                channel="capability",
                candidate_digest=stable_digest(passage.model_dump(mode="json")),
                gate="deduplication",
                reason_code=RejectCode.DUPLICATE_CONFLICT,
                field_path="passage_id",
                safe_message="stable passage identity conflicts with the current generation",
                paper_id=passage.paper_id or passage.source_id,
                locator_key=(
                    passage.source_locator.locator_key if passage.source_locator else None
                ),
            )
        )
    kb = PerformanceKnowledgeBase.model_validate(
        {
            **base_kb.model_dump(mode="json", by_alias=True),
            "entries": [entry.model_dump(mode="json", by_alias=True) for entry in entries],
        }
    )
    store = PassageStore(passages=[passages[key] for key in sorted(passages)])
    return MergedSnapshots(
        performance_kb=kb,
        passage_store=store,
        rejects=sorted(
            [*mapped.rejects, *merge_rejects],
            key=lambda item: (
                item.channel,
                item.candidate_digest,
                item.reason_code.value,
                item.field_path,
            ),
        ),
        accepted_observations=accepted_observations,
        accepted_passages=accepted_passages,
    )


@dataclass(frozen=True)
class KbUpdateResult:
    status: str
    paper_id: str
    accepted_observations: int
    accepted_passages: int
    rejected_candidates: int
    generation_id: str | None
    pointer_changed: bool
    reject_log_path: str | None = None


class KbUpdateService:
    def __init__(
        self,
        *,
        converter: PdfConverter,
        extractor: EvidenceExtractor,
        index_builder: PassageIndexBuilder,
        toolcards: Sequence[ToolCard],
        profiled_dataset_names: set[str],
        baseline_performance_path: Path | None = None,
        baseline_passage_path: Path | None = None,
        baseline_vector_index_path: Path | None = None,
        clock: Callable[[], str] = lambda: __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(),
        run_id_factory: Callable[[], str] = lambda: uuid.uuid4().hex,
        fault_hook: Callable[[str], None] | None = None,
    ) -> None:
        self._converter = converter
        self._extractor = extractor
        self._index_builder = index_builder
        self._mapper = KnowledgeMapper(
            toolcards, profiled_dataset_names=profiled_dataset_names
        )
        self._baseline_performance_path = baseline_performance_path
        self._baseline_passage_path = baseline_passage_path
        self._baseline_vector_index_path = baseline_vector_index_path
        self._clock = clock
        self._run_id_factory = run_id_factory
        self._fault_hook = fault_hook

    def _baseline(
        self,
    ) -> tuple[PerformanceKnowledgeBase, PassageStore, VectorIndex]:
        if self._baseline_performance_path and self._baseline_performance_path.exists():
            kb = load_performance_db(self._baseline_performance_path)
        else:
            kb = PerformanceKnowledgeBase(
                knowledge_base_type="performance_context_db", entries=[]
            )
        if self._baseline_passage_path and self._baseline_passage_path.exists():
            store = load_passage_store(self._baseline_passage_path) or PassageStore()
        else:
            store = PassageStore()
        if self._baseline_vector_index_path and self._baseline_vector_index_path.exists():
            index = VectorIndex.load(self._baseline_vector_index_path)
        else:
            index = VectorIndex()
        return kb, store, index

    def _unique_run_id(self, root: Path) -> str:
        base = _slug(self._run_id_factory()) or uuid.uuid4().hex
        candidate = base
        suffix = 2
        while (root / ".kb_transactions" / candidate).exists():
            candidate = f"{base}-{suffix}"
            suffix += 1
        return candidate

    def _prepare(
        self,
        *,
        pdf: Path,
        work_dir: Path,
    ) -> tuple[DocumentArtifact, MapCheckResult]:
        document = self._converter.convert(pdf, work_dir)
        extraction = self._extractor.extract(document)
        mapped = self._mapper.map_and_check(document, extraction)
        return document, mapped

    def update(
        self,
        *,
        pdf: Path,
        kb_root: Path,
        dry_run: bool = False,
        work_dir: Path | None = None,
    ) -> KbUpdateResult:
        root = Path(kb_root)
        if root.exists() and not root.is_dir():
            raise ValueError("kb_root must be a writable directory path")
        temporary_parent = Path(work_dir) if work_dir is not None else None
        if temporary_parent is not None:
            temporary_parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix="lakes-kb-update-",
            dir=str(temporary_parent) if temporary_parent else None,
        ) as temporary_name:
            transaction_work = Path(temporary_name)
            document, mapped = self._prepare(
                pdf=Path(pdf), work_dir=transaction_work / "extract"
            )
            if dry_run:
                pointer_path = root / POINTER_FILE
                if pointer_path.exists():
                    current = load_current_generation(root)
                    base_kb = current.performance_kb
                    base_store = current.passage_store
                    base_index = current.vector_index
                else:
                    base_kb, base_store, base_index = self._baseline()
                merged = merge_snapshots(base_kb, base_store, mapped)
                if passage_bytes(merged.passage_store) == passage_bytes(base_store):
                    index = base_index
                else:
                    index = self._index_builder.build(merged.passage_store)
                dry_root = transaction_work / "dry-run-root"
                run_id = "dry_run"
                dry_root.mkdir()
                with kb_writer_lock(dry_root, run_id):
                    published = publish_generation(
                        kb_root=dry_root,
                        performance_kb=merged.performance_kb,
                        passage_store=merged.passage_store,
                        vector_index=index,
                        rejects=merged.rejects,
                        created_at=self._clock(),
                        run_id=run_id,
                        old_pointer_bytes=None,
                        fault_hook=self._fault_hook,
                    )
                return KbUpdateResult(
                    status="DRY_RUN",
                    paper_id=document.paper_id,
                    accepted_observations=merged.accepted_observations,
                    accepted_passages=merged.accepted_passages,
                    rejected_candidates=len(merged.rejects),
                    generation_id=published.generation.pointer.generation_id,
                    pointer_changed=False,
                )
            root.mkdir(parents=True, exist_ok=True)
            run_id = self._unique_run_id(root)
            with kb_writer_lock(root, run_id):
                pointer_path = root / POINTER_FILE
                if pointer_path.exists():
                    current = load_current_generation(root)
                    base_kb = current.performance_kb
                    base_store = current.passage_store
                    base_index = current.vector_index
                    old_pointer_bytes = current.pointer_bytes
                else:
                    base_kb, base_store, base_index = self._baseline()
                    old_pointer_bytes = None
                merged = merge_snapshots(base_kb, base_store, mapped)
                if not merged.accepted_observations and not merged.accepted_passages:
                    reject_path = root / REJECTS_DIR / f"{run_id}.json"
                    atomic_replace_bytes(reject_path, reject_bytes(merged.rejects))
                    return KbUpdateResult(
                        status="REJECTED",
                        paper_id=document.paper_id,
                        accepted_observations=0,
                        accepted_passages=0,
                        rejected_candidates=len(merged.rejects),
                        generation_id=(current.pointer.generation_id if pointer_path.exists() else None),
                        pointer_changed=False,
                        reject_log_path=str(reject_path),
                    )
                if passage_bytes(merged.passage_store) == passage_bytes(base_store):
                    index = base_index
                else:
                    index = self._index_builder.build(merged.passage_store)
                published = publish_generation(
                    kb_root=root,
                    performance_kb=merged.performance_kb,
                    passage_store=merged.passage_store,
                    vector_index=index,
                    rejects=merged.rejects,
                    created_at=self._clock(),
                    run_id=run_id,
                    old_pointer_bytes=old_pointer_bytes,
                    fault_hook=self._fault_hook,
                )
                return KbUpdateResult(
                    status=published.status,
                    paper_id=document.paper_id,
                    accepted_observations=merged.accepted_observations,
                    accepted_passages=merged.accepted_passages,
                    rejected_candidates=len(merged.rejects),
                    generation_id=published.generation.pointer.generation_id,
                    pointer_changed=published.status == "COMMITTED",
                )
