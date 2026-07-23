"""Strict extraction-boundary models for dynamic knowledge-base updates."""

from __future__ import annotations

import hashlib
import json
import math
import re
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SHA256_PATTERN = r"^[0-9a-f]{64}$"
PAPER_ID_PATTERN = r"^paper_[0-9a-f]{32}$"


def canonical_json_bytes(value: object) -> bytes:
    """Serialize content-addressed data identically across runs and machines."""
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def stable_digest(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def normalize_evidence_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class DocumentBlock(StrictModel):
    block_id: Annotated[str, Field(min_length=6, max_length=96)]
    page_number: int | None = Field(default=None, ge=1)
    block_type: Annotated[str, Field(min_length=1, max_length=32)]
    ordinal: int = Field(ge=0)
    normalized_text: Annotated[str, Field(min_length=1)]
    text_sha256: Annotated[str, Field(pattern=SHA256_PATTERN)]
    table_id: str | None = Field(default=None, max_length=96)
    table_rows: list[list[str]] = Field(default_factory=list)

    @model_validator(mode="after")
    def _text_digest_matches(self) -> "DocumentBlock":
        expected = hashlib.sha256(self.normalized_text.encode("utf-8")).hexdigest()
        if self.text_sha256 != expected:
            raise ValueError("document block text digest does not match normalized_text")
        return self


class DocumentArtifact(StrictModel):
    schema_version: Literal["mineru_document.v1"] = "mineru_document.v1"
    paper_id: Annotated[str, Field(pattern=PAPER_ID_PATTERN)]
    pdf_sha256: Annotated[str, Field(pattern=SHA256_PATTERN)]
    pdf_size_bytes: int = Field(gt=0)
    converter_name: Annotated[str, Field(min_length=1, max_length=64)]
    converter_version: Annotated[str, Field(min_length=1, max_length=64)]
    markdown_relative_path: Annotated[str, Field(min_length=1, max_length=512)]
    markdown_sha256: Annotated[str, Field(pattern=SHA256_PATTERN)]
    markdown_text: Annotated[str, Field(min_length=1)]
    structured_relative_path: Annotated[str, Field(min_length=1, max_length=512)]
    structured_sha256: Annotated[str, Field(pattern=SHA256_PATTERN)]
    blocks: Annotated[list[DocumentBlock], Field(min_length=1)]

    @field_validator("markdown_relative_path", "structured_relative_path")
    @classmethod
    def _relative_artifact_path(cls, value: str) -> str:
        normalized = value.replace("\\", "/")
        if normalized.startswith("/") or ".." in normalized.split("/"):
            raise ValueError("document artifact paths must be relative and in-root")
        return normalized

    @model_validator(mode="after")
    def _document_consistency(self) -> "DocumentArtifact":
        if self.paper_id != f"paper_{self.pdf_sha256[:32]}":
            raise ValueError("paper_id must derive from the PDF digest")
        markdown_digest = hashlib.sha256(self.markdown_text.encode("utf-8")).hexdigest()
        if self.markdown_sha256 != markdown_digest:
            raise ValueError("Markdown digest does not match markdown_text")
        block_ids = [block.block_id for block in self.blocks]
        if len(block_ids) != len(set(block_ids)):
            raise ValueError("document block IDs must be unique")
        return self


class RawSourceLocator(StrictModel):
    block_id: Annotated[str, Field(min_length=1, max_length=96)]
    page_number: int | None = Field(default=None, ge=1)
    block_type: str | None = Field(default=None, max_length=32)
    table_id: str | None = Field(default=None, max_length=96)
    row: int | None = Field(default=None, ge=0)
    column: int | None = Field(default=None, ge=0)
    excerpt: Annotated[str, Field(min_length=1, max_length=1000)]
    excerpt_sha256: Annotated[str | None, Field(default=None, pattern=SHA256_PATTERN)]


class RawDatasetProfile(StrictModel):
    dataset_label: Annotated[str, Field(min_length=1, max_length=180)]
    experiment_setting_id: Annotated[str, Field(default="default", min_length=1, max_length=120)]
    split_identity: str | None = Field(default=None, max_length=120)
    solc: list[str] = Field(default_factory=list, max_length=32)
    domain_tags: list[str] = Field(default_factory=list, max_length=32)
    contract_count_total: int | None = Field(default=None, ge=0)
    what_contracts: str | None = Field(default=None, max_length=500)
    how_collected: str | None = Field(default=None, max_length=500)


MetricKind = Literal[
    "precision",
    "recall",
    "f1",
    "accuracy",
    "runtime",
    "category_rate",
    "category_count",
]


class RawMetricClaim(StrictModel):
    tool_label: Annotated[str, Field(min_length=1, max_length=96)]
    dataset: RawDatasetProfile
    metric_kind: MetricKind
    value: float | int | None = None
    unit: Annotated[str, Field(min_length=1, max_length=48)]
    category_label: str | None = Field(default=None, max_length=96)
    runtime_basis: str | None = Field(default=None, max_length=48)
    detected: int | None = Field(default=None, ge=0)
    total: int | None = Field(default=None, ge=0)
    source_locator: RawSourceLocator

    @model_validator(mode="after")
    def _strict_numeric_shape(self) -> "RawMetricClaim":
        if self.value is not None and not math.isfinite(float(self.value)):
            raise ValueError("metric value must be finite")
        if self.metric_kind == "category_count":
            if self.detected is None or self.total is None:
                raise ValueError("category_count requires detected and total")
        elif self.value is None:
            raise ValueError(f"{self.metric_kind} requires value")
        return self


class RawCapabilityClaim(StrictModel):
    owner_tool_label: Annotated[str, Field(min_length=1, max_length=96)]
    counterpart_tool_labels: list[str] = Field(default_factory=list, max_length=8)
    category_label: Annotated[str, Field(min_length=1, max_length=96)]
    relation_to_owner: Annotated[str, Field(min_length=1, max_length=64)]
    knowledge_kind: Annotated[str, Field(min_length=1, max_length=64)]
    action_scope: Annotated[list[str], Field(min_length=1, max_length=8)]
    applicability_tags: list[str] = Field(default_factory=list, max_length=24)
    claim_text: Annotated[str, Field(min_length=1, max_length=500)]
    limitations_text: str = Field(default="", max_length=500)
    evidence_basis: Annotated[str, Field(min_length=1, max_length=64)]
    source_reliability: Annotated[str, Field(min_length=1, max_length=64)]
    source_locator: RawSourceLocator


class RawKnowledgeExtraction(StrictModel):
    schema_version: Literal["dynamic_kb_extract.v1"] = "dynamic_kb_extract.v1"
    paper_id: Annotated[str, Field(pattern=PAPER_ID_PATTERN)]
    pdf_sha256: Annotated[str, Field(pattern=SHA256_PATTERN)]
    publication_date: Annotated[str | None, Field(default=None, max_length=32)]
    dataset_claims: list[RawMetricClaim] = Field(default_factory=list, max_length=2000)
    capability_claims: list[RawCapabilityClaim] = Field(default_factory=list, max_length=2000)


class RejectCode(str, Enum):
    ENVELOPE_SCHEMA = "ENVELOPE_SCHEMA"
    DOCUMENT_DIGEST_MISMATCH = "DOCUMENT_DIGEST_MISMATCH"
    TOOL_UNKNOWN = "TOOL_UNKNOWN"
    TOOL_ALIAS_AMBIGUOUS = "TOOL_ALIAS_AMBIGUOUS"
    CATEGORY_UNKNOWN = "CATEGORY_UNKNOWN"
    REQUIRED_FIELD_MISSING = "REQUIRED_FIELD_MISSING"
    RELATION_ILLEGAL = "RELATION_ILLEGAL"
    ACTION_SCOPE_ILLEGAL = "ACTION_SCOPE_ILLEGAL"
    TAG_ILLEGAL = "TAG_ILLEGAL"
    METRIC_UNIT_AMBIGUOUS = "METRIC_UNIT_AMBIGUOUS"
    METRIC_BASIS_AMBIGUOUS = "METRIC_BASIS_AMBIGUOUS"
    METRIC_RANGE = "METRIC_RANGE"
    METRIC_COUNT_INCONSISTENT = "METRIC_COUNT_INCONSISTENT"
    PROVENANCE_NOT_FOUND = "PROVENANCE_NOT_FOUND"
    PROVENANCE_DIGEST_MISMATCH = "PROVENANCE_DIGEST_MISMATCH"
    DUPLICATE_CONFLICT = "DUPLICATE_CONFLICT"
    LINK_ENDPOINT_MISMATCH = "LINK_ENDPOINT_MISMATCH"
    CANONICAL_SCHEMA = "CANONICAL_SCHEMA"


class RejectRecord(StrictModel):
    channel: Literal["dataset", "capability", "transaction"]
    candidate_digest: Annotated[str, Field(pattern=SHA256_PATTERN)]
    gate: Annotated[str, Field(min_length=1, max_length=48)]
    reason_code: RejectCode
    field_path: Annotated[str, Field(min_length=1, max_length=180)]
    safe_message: Annotated[str, Field(min_length=1, max_length=240)]
    paper_id: Annotated[str, Field(pattern=PAPER_ID_PATTERN)]
    locator_key: str | None = Field(default=None, max_length=220)
