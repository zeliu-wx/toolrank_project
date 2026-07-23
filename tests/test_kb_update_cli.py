from __future__ import annotations

from typer.testing import CliRunner

from toolrank.cli import app as lakes_app
from toolrank.kb_update import app as kb_app


def test_kb_update_help_exposes_explicit_root_dry_run_and_no_secret_options() -> None:
    result = CliRunner().invoke(
        kb_app,
        ["ingest", "--help"],
        terminal_width=120,
    )
    assert result.exit_code == 0
    assert "--kb-root" in result.stdout
    assert "--toolcards-dir" in result.stdout
    assert "required" in result.stdout.lower()
    assert "--dry-run" in result.stdout
    normalized_help = " ".join(result.stdout.replace("│", " ").split())
    assert "mineru -p PDF -o DIR" in normalized_help
    assert "--api-key" not in result.stdout
    assert "--token" not in result.stdout


def test_main_cli_exposes_nested_kb_commands_and_pointer_reader_option() -> None:
    kb_help = CliRunner().invoke(lakes_app, ["kb", "--help"])
    recommend_help = CliRunner().invoke(lakes_app, ["recommend", "--help"])
    assert kb_help.exit_code == 0
    assert {"ingest", "validate", "recover"}.issubset(set(kb_help.stdout.split()))
    assert recommend_help.exit_code == 0
    assert "--kb-root" in recommend_help.stdout
