from __future__ import annotations

import re

from typer.testing import CliRunner

from toolrank.cli import app as lakes_app
from toolrank.kb_update import app as kb_app

_ANSI_CSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _strip_ansi(output: str) -> str:
    return _ANSI_CSI_RE.sub("", output)


def test_kb_update_help_exposes_explicit_root_dry_run_and_no_secret_options() -> None:
    result = CliRunner().invoke(
        kb_app,
        ["ingest", "--help"],
        terminal_width=120,
    )
    assert result.exit_code == 0
    help_output = _strip_ansi(result.stdout)
    assert "--kb-root" in help_output
    assert "--toolcards-dir" in help_output
    assert "required" in help_output.lower()
    assert "--dry-run" in help_output
    normalized_help = " ".join(help_output.replace("│", " ").split())
    assert "mineru -p PDF -o DIR" in normalized_help
    assert "--api-key" not in help_output
    assert "--token" not in help_output


def test_main_cli_exposes_nested_kb_commands_and_pointer_reader_option() -> None:
    kb_help = CliRunner().invoke(lakes_app, ["kb", "--help"])
    recommend_help = CliRunner().invoke(lakes_app, ["recommend", "--help"])
    assert kb_help.exit_code == 0
    kb_help_output = _strip_ansi(kb_help.stdout)
    assert {"ingest", "validate", "recover"}.issubset(set(kb_help_output.split()))
    assert recommend_help.exit_code == 0
    recommend_help_output = _strip_ansi(recommend_help.stdout)
    assert "--kb-root" in recommend_help_output
