from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from toolrank.kb_update_models import (
    DocumentArtifact,
    DocumentBlock,
    RawCapabilityClaim,
    RawDatasetProfile,
    RawKnowledgeExtraction,
    RawMetricClaim,
    RawSourceLocator,
)
from toolrank.kb_update_service import (
    MinerUConversionError,
    MinerUConverter,
    OpenAIKnowledgeExtractor,
)


def _pdf(path: Path) -> Path:
    path.write_bytes(b"%PDF-1.7\nfixture\n")
    return path


def _document() -> DocumentArtifact:
    text = "Slither detected 8 of 10 reentrancy cases in Table 2."
    return DocumentArtifact(
        paper_id="paper_" + "a" * 32,
        pdf_sha256="a" * 64,
        pdf_size_bytes=20,
        converter_name="mineru",
        converter_version="test",
        markdown_relative_path="paper.md",
        markdown_sha256=hashlib.sha256(text.encode()).hexdigest(),
        markdown_text=text,
        structured_relative_path="paper_content_list.json",
        structured_sha256="b" * 64,
        blocks=[
            DocumentBlock(
                block_id="block-1",
                page_number=2,
                block_type="table",
                ordinal=0,
                normalized_text=text,
                text_sha256=hashlib.sha256(text.encode()).hexdigest(),
                table_id="table-2",
                table_rows=[
                    ["tool", "detected", "evidence"],
                    ["Slither", "8/10", text],
                ],
            )
        ],
    )


def test_mineru_uses_concrete_argv_and_discovers_exact_outputs(tmp_path: Path) -> None:
    pdf = _pdf(tmp_path / "paper.pdf")
    calls: list[list[str]] = []

    def runner(argv: list[str], **_kwargs):
        calls.append(argv)
        out = Path(argv[-1]) / "paper" / "auto"
        out.mkdir(parents=True)
        (out / "paper.md").write_text("Evidence text", encoding="utf-8")
        (out / "paper_content_list.json").write_text(
            json.dumps(
                [
                    {
                        "page_idx": 0,
                        "type": "text",
                        "text": "Evidence text",
                    }
                ]
            ),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    artifact = MinerUConverter(
        command="mineru",
        runner=runner,
        executable_resolver=lambda value: value,
        version="fixture",
    ).convert(pdf, tmp_path / "work")

    assert calls == [["mineru", "-p", str(pdf), "-o", str(tmp_path / "work" / "mineru")]]
    assert artifact.markdown_relative_path == "paper/auto/paper.md"
    assert artifact.structured_relative_path == "paper/auto/paper_content_list.json"
    assert artifact.blocks[0].block_id.startswith("block_")


@pytest.mark.parametrize("missing", ["markdown", "structured", "ambiguous"])
def test_mineru_requires_one_markdown_and_one_structured_output(
    tmp_path: Path,
    missing: str,
) -> None:
    pdf = _pdf(tmp_path / "paper.pdf")

    def runner(argv: list[str], **_kwargs):
        out = Path(argv[-1])
        out.mkdir(parents=True)
        if missing != "markdown":
            (out / "paper.md").write_text("Evidence", encoding="utf-8")
        if missing != "structured":
            (out / "paper_content_list.json").write_text("[]", encoding="utf-8")
        if missing == "ambiguous":
            (out / "duplicate.md").write_text("Evidence", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    converter = MinerUConverter(
        runner=runner,
        executable_resolver=lambda value: value,
    )
    with pytest.raises(MinerUConversionError, match="exactly one"):
        converter.convert(pdf, tmp_path / "work")


def test_missing_mineru_dependency_fails_clearly_before_subprocess(tmp_path: Path) -> None:
    pdf = _pdf(tmp_path / "paper.pdf")
    converter = MinerUConverter(executable_resolver=lambda _value: None)
    with pytest.raises(MinerUConversionError, match="MinerU executable not found"):
        converter.convert(pdf, tmp_path / "work")


def test_two_channel_extraction_schema_is_strict() -> None:
    payload = {
        "schema_version": "dynamic_kb_extract.v1",
        "paper_id": "paper_" + "a" * 32,
        "pdf_sha256": "a" * 64,
        "publication_date": "2026-07-19",
        "dataset_claims": [
            {
                "tool_label": "Slither",
                "dataset": {
                    "dataset_label": "Benchmark A",
                    "experiment_setting_id": "default",
                    "solc": ["0.8.x"],
                },
                "metric_kind": "recall",
                "value": 80.0,
                "unit": "percent",
                "category_label": None,
                "runtime_basis": None,
                "detected": None,
                "total": None,
                "source_locator": {
                    "block_id": "block-1",
                    "page_number": 2,
                    "block_type": "table",
                    "table_id": "table-2",
                    "row": 1,
                    "column": 2,
                    "excerpt": "Slither detected 8 of 10 reentrancy cases in Table 2.",
                },
            }
        ],
        "capability_claims": [],
    }
    assert RawKnowledgeExtraction.model_validate(payload).dataset_claims[0].value == 80.0

    payload["unexpected"] = True
    with pytest.raises(ValidationError):
        RawKnowledgeExtraction.model_validate(payload)
    payload.pop("unexpected")
    payload["dataset_claims"][0]["value"] = "80"
    with pytest.raises(ValidationError):
        RawKnowledgeExtraction.model_validate(payload)


def test_openai_extractor_uses_one_fixed_two_channel_schema_at_temperature_zero() -> None:
    calls: list[dict] = []

    def completion(**kwargs):
        calls.append(kwargs)
        document = _document()
        return {
            "schema_version": "dynamic_kb_extract.v1",
            "paper_id": document.paper_id,
            "pdf_sha256": document.pdf_sha256,
            "publication_date": "2026-07-19",
            "dataset_claims": [],
            "capability_claims": [],
        }

    extractor = OpenAIKnowledgeExtractor(
        model="fixture-model",
        client=object(),
        completion_fn=completion,
    )
    result = extractor.extract(_document())

    assert result.dataset_claims == []
    assert len(calls) == 1
    assert calls[0]["temperature"] == 0.0
    schema = calls[0]["schema"]
    assert set(schema["properties"]) >= {"dataset_claims", "capability_claims"}
    assert schema["additionalProperties"] is False


def extraction_fixture(*, category: str = "reentrancy") -> RawKnowledgeExtraction:
    locator = RawSourceLocator(
        block_id="block-1",
        page_number=2,
        block_type="table",
        table_id="table-2",
        row=1,
        column=2,
        excerpt="Slither detected 8 of 10 reentrancy cases in Table 2.",
    )
    dataset = RawDatasetProfile(
        dataset_label="Benchmark A",
        experiment_setting_id="default",
        solc=["0.8.x"],
    )
    return RawKnowledgeExtraction(
        paper_id="paper_" + "a" * 32,
        pdf_sha256="a" * 64,
        publication_date="2026-07-19",
        dataset_claims=[
            RawMetricClaim(
                tool_label="Slither",
                dataset=dataset,
                metric_kind="category_count",
                unit="count",
                category_label=category,
                detected=8,
                total=10,
                source_locator=locator,
            ),
            RawMetricClaim(
                tool_label="Slither",
                dataset=dataset,
                metric_kind="recall",
                value=80.0,
                unit="percent",
                source_locator=locator,
            ),
            RawMetricClaim(
                tool_label="Slither",
                dataset=dataset,
                metric_kind="precision",
                value=0.75,
                unit="fraction",
                source_locator=locator,
            ),
        ],
        capability_claims=[
            RawCapabilityClaim(
                owner_tool_label="Slither",
                category_label=category,
                relation_to_owner="supports owner",
                knowledge_kind="category capability",
                action_scope=["single tool", "plan composition"],
                applicability_tags=["solc:0.8.x", "input:sol"],
                claim_text="Slither detects this category on the reported benchmark.",
                limitations_text="Limited to the evaluated benchmark.",
                evidence_basis="benchmark result",
                source_reliability="peer reviewed",
                source_locator=locator,
            )
        ],
    )
