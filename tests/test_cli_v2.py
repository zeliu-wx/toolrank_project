from __future__ import annotations

import json

from typer.testing import CliRunner

import toolrank.cli as cli
from toolrank.cego import build_primary_only_certificate
from toolrank.dace_rag import build_action_evidence_matrix
from toolrank.engine import PipelineResult
from toolrank.schemas import ContractFeatures
from toolrank.schemas_v2 import CheckerVerdict, PipelineStatus, Stage2Outcome, Stage2Status
from tests.stage2_fixtures import budget, stage2_context


runner = CliRunner()


def plan_result() -> PipelineResult:
    context = stage2_context()
    matrix = build_action_evidence_matrix(context, budget())
    certificate = build_primary_only_certificate(context, matrix, budget())
    return PipelineResult(
        status=PipelineStatus.PLAN_READY,
        features=ContractFeatures(),
        packet=context.stage1,
        context=context,
        stage2_outcome=Stage2Outcome(status=Stage2Status.PLAN_READY),
        matrix=matrix,
        certificate=certificate,
        checker_verdict=CheckerVerdict(status="ACCEPT"),
    )


def test_summary_renders_v2_status_without_certification(monkeypatch) -> None:
    result = plan_result()
    monkeypatch.setattr(cli, "run_recommendation", lambda **_kwargs: result)
    response = runner.invoke(cli.app, ["recommend", "A.sol", "--emit", "summary"])
    assert response.exit_code == 0
    assert "status: PLAN_READY" in response.stdout
    assert "stage1: PRIMARY_SELECTED" in response.stdout
    assert "certification" not in response.stdout


def test_json_renders_nullable_v2_boundaries(monkeypatch) -> None:
    result = plan_result()
    monkeypatch.setattr(cli, "run_recommendation", lambda **_kwargs: result)
    response = runner.invoke(cli.app, ["recommend", "A.sol", "--emit", "json"])
    assert response.exit_code == 0
    payload = json.loads(response.stdout)
    assert payload["status"] == "PLAN_READY"
    assert payload["packet"]["schema_version"] == "screc_v2"
    assert payload["stage2_context"]["schema_version"] == "dace_context_v2"
    assert payload["certificate"]["schema_version"] == "dace_orch_v2"
