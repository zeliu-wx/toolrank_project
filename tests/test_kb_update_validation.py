from __future__ import annotations

from copy import deepcopy
import hashlib

import pytest

from tests.test_kb_update_extract import _document, extraction_fixture
from toolrank.dace_rag import project_performance_observation_links
from toolrank.kb_update_models import RejectCode
from toolrank.kb_update_service import KnowledgeMapper, merge_snapshots
from toolrank.schemas import (
    DatasetProfile,
    PerformanceEntry,
    PerformanceKnowledgeBase,
    ToolCard,
)
from toolrank.schemas_v2 import (
    PassageStore,
    Stage1BenchmarkEvidence,
    Stage1EvidenceLineage,
    Stage1ToolEvidence,
)


def _card(tool_id: str = "slither", tool_name: str = "Slither") -> ToolCard:
    return ToolCard.model_validate(
        {
            "tool_id": tool_id,
            "tool_name": tool_name,
            "d7_input_support": {"sol": True, "bytecode": True, "runtime": True},
            "d8_mode": "static",
            "d2_solidity_versions": ">=0.4.0",
            "d3_multifile_support": "yes",
        }
    )


def test_map_check_normalizes_and_links_same_paper_tool_category() -> None:
    mapper = KnowledgeMapper([_card()], profiled_dataset_names=set())
    first = mapper.map_and_check(_document(), extraction_fixture())
    second = mapper.map_and_check(_document(), extraction_fixture())

    assert first.rejects == []
    assert [item.observation_id for item in first.observations] == [
        item.observation_id for item in second.observations
    ]
    assert [item.model_dump() for item in first.passages] == [
        item.model_dump() for item in second.passages
    ]
    count = next(item for item in first.observations if item.metric_kind == "category_count")
    assert count.category == "reentrancy"
    assert count.detected == 8 and count.total == 10
    passage = first.passages[0]
    assert passage.relation_to_owner == "supports_owner"
    assert passage.action_scope == ["SINGLE_TOOL", "PLAN_COMPOSITION"]
    assert passage.linked_performance_observation_ids == [count.observation_id]
    assert passage.linked_evaluation_ids == []
    assert all(item.stage1_eligible is False for item in first.observations)
    assert all(item.stage1_ineligible_reason == "DATASET_PROFILE_MISSING" for item in first.observations)


@pytest.mark.parametrize(
    "mutate,code",
    [
        (lambda raw: setattr(raw.dataset_claims[0], "category_label", "not a DASP category"), RejectCode.CATEGORY_UNKNOWN),
        (lambda raw: setattr(raw.dataset_claims[0], "detected", 11), RejectCode.METRIC_COUNT_INCONSISTENT),
        (lambda raw: setattr(raw.dataset_claims[1], "unit", "unknown"), RejectCode.METRIC_UNIT_AMBIGUOUS),
        (lambda raw: setattr(raw.capability_claims[0], "relation_to_owner", "invented"), RejectCode.RELATION_ILLEGAL),
        (lambda raw: setattr(raw.capability_claims[0].source_locator, "block_id", "absent"), RejectCode.PROVENANCE_NOT_FOUND),
    ],
)
def test_map_check_has_stable_reject_codes(mutate, code: RejectCode) -> None:
    extraction = extraction_fixture()
    mutate(extraction)
    result = KnowledgeMapper([_card()], profiled_dataset_names=set()).map_and_check(
        _document(), extraction
    )
    assert code in {item.reason_code for item in result.rejects}
    assert all(len(item.safe_message) <= 240 for item in result.rejects)


def test_locator_excerpt_must_occur_in_the_selected_block() -> None:
    document = _document()
    evidence = document.blocks[0].normalized_text
    unrelated = "This block contains unrelated benchmark prose."
    selected = document.blocks[0].model_copy(
        update={
            "normalized_text": unrelated,
            "text_sha256": hashlib.sha256(unrelated.encode()).hexdigest(),
            "table_rows": [[unrelated]],
        }
    )
    elsewhere = document.blocks[0].model_copy(
        update={
            "block_id": "block-2",
            "ordinal": 1,
            "normalized_text": evidence,
            "text_sha256": hashlib.sha256(evidence.encode()).hexdigest(),
            "table_rows": [[evidence]],
        }
    )
    document = document.model_copy(update={"blocks": [selected, elsewhere]})

    result = KnowledgeMapper([_card()], profiled_dataset_names=set()).map_and_check(
        document, extraction_fixture()
    )

    assert {item.reason_code for item in result.rejects} == {
        RejectCode.PROVENANCE_NOT_FOUND
    }
    assert result.observations == []
    assert result.passages == []


def test_actual_table_block_requires_exact_cell_coordinates() -> None:
    extraction = extraction_fixture()
    extraction.dataset_claims[0].source_locator.block_type = None
    extraction.dataset_claims[0].source_locator.row = None
    extraction.dataset_claims[0].source_locator.column = None

    result = KnowledgeMapper([_card()], profiled_dataset_names=set()).map_and_check(
        _document(), extraction
    )

    assert RejectCode.REQUIRED_FIELD_MISSING in {
        item.reason_code for item in result.rejects
    }


def test_table_id_is_optional_when_block_and_cell_resolve() -> None:
    document = _document()
    document = document.model_copy(
        update={
            "blocks": [
                document.blocks[0].model_copy(update={"table_id": None})
            ]
        }
    )
    extraction = extraction_fixture()
    for claim in [*extraction.dataset_claims, *extraction.capability_claims]:
        claim.source_locator.table_id = None

    result = KnowledgeMapper([_card()], profiled_dataset_names=set()).map_and_check(
        document, extraction
    )

    assert result.rejects == []


def test_ambiguous_tool_alias_is_rejected() -> None:
    extraction = extraction_fixture()
    mapper = KnowledgeMapper(
        [_card("slither-a", "Slither"), _card("slither-b", "Slither")],
        profiled_dataset_names=set(),
    )
    result = mapper.map_and_check(_document(), extraction)
    assert {item.reason_code for item in result.rejects} == {RejectCode.TOOL_ALIAS_AMBIGUOUS}


def test_overall_metric_is_not_forced_into_category_link() -> None:
    extraction = extraction_fixture()
    extraction.dataset_claims = [
        item for item in extraction.dataset_claims if item.metric_kind != "category_count"
    ]
    result = KnowledgeMapper([_card()], profiled_dataset_names=set()).map_and_check(
        _document(), extraction
    )
    assert result.passages[0].linked_performance_observation_ids == []
    assert result.passages[0].linked_evaluation_ids == []


def test_unrecognized_unknown_alias_is_not_coerced_to_unknown_unknowns() -> None:
    extraction = extraction_fixture(category="other")
    result = KnowledgeMapper([_card()], profiled_dataset_names=set()).map_and_check(
        _document(), extraction
    )
    assert RejectCode.CATEGORY_UNKNOWN in {item.reason_code for item in result.rejects}


def test_existing_dataset_keeps_one_scene_source_and_retargets_observation_refs() -> None:
    mapped = KnowledgeMapper(
        [_card()], profiled_dataset_names={"Benchmark A"}
    ).map_and_check(_document(), extraction_fixture())
    baseline = PerformanceKnowledgeBase(
        knowledge_base_type="performance_context_db",
        entries=[
            PerformanceEntry(
                source_id="legacy-benchmark-source",
                dataset_profile=DatasetProfile(dataset_name="Benchmark A"),
            )
        ],
    )
    merged = merge_snapshots(baseline, PassageStore(), mapped)
    assert len(merged.performance_kb.entries) == 1
    entry = merged.performance_kb.entries[0]
    assert entry.source_id == "legacy-benchmark-source"
    assert {item.source_id for item in entry.performance_observations} == {
        "legacy-benchmark-source"
    }
    assert {
        ref.source_id
        for ref in merged.passage_store.passages[0].performance_observation_refs
    } == {"legacy-benchmark-source"}


def test_projection_uses_only_exact_observation_rows_present_in_lineage() -> None:
    mapped = KnowledgeMapper(
        [_card()], profiled_dataset_names={"Benchmark A"}
    ).map_and_check(_document(), extraction_fixture())
    passage = mapped.passages[0]
    reference = passage.performance_observation_refs[0]
    row = Stage1BenchmarkEvidence(
        evaluation_id="stage1_eval::slither::slice-a",
        tool="slither",
        benchmark_id="slice-a",
        source_id=reference.source_id,
        dataset_id=reference.dataset_name,
        w_D=1.0,
        s_t_D=0.8,
        recall=0.8,
        precision=0.75,
        recall_rank=1.0,
        precision_rank=1.0,
    )
    lineage = Stage1EvidenceLineage(
        primary_tool="slither",
        benchmark_weights={"slice-a": 1.0},
        tools={
            "slither": Stage1ToolEvidence(
                tool="slither",
                S_t=0.8,
                support_mass=1.0,
                benchmark_evaluations=[row],
            )
        },
    )
    assert project_performance_observation_links(lineage, passage) == [row.evaluation_id]

    absent = deepcopy(lineage)
    absent.tools["slither"].benchmark_evaluations = []
    absent.benchmark_weights = {}
    assert project_performance_observation_links(absent, passage) == []


def test_candidate_order_does_not_change_ids() -> None:
    forward = extraction_fixture()
    reverse = extraction_fixture()
    reverse.dataset_claims = list(reversed(reverse.dataset_claims))
    mapper = KnowledgeMapper([_card()], profiled_dataset_names=set())
    a = mapper.map_and_check(_document(), forward)
    b = mapper.map_and_check(_document(), reverse)
    assert [item.observation_id for item in a.observations] == [
        item.observation_id for item in b.observations
    ]
    assert [item.passage_id for item in a.passages] == [item.passage_id for item in b.passages]
