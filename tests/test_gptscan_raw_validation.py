from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

from toolrank import runner


_RAW_CASES = [
    ("missing", None, False),
    ("unreadable", "__DIRECTORY__", False),
    ("malformed", "{not-json", False),
    ("wrong_shape", "[]", False),
    ("success_false", '{"success": false, "results": []}', False),
    ("results_missing", '{"success": true}', False),
    ("results_wrong_type", '{"success": true, "results": {}}', False),
    ("valid_empty", '{"success": true, "results": []}', True),
    (
        "valid_results",
        json.dumps(
            {
                "success": True,
                "results": [
                    {
                        "code": "GPT-1",
                        "description": "issue",
                        "affectedFiles": [],
                    }
                ],
            }
        ),
        True,
    ),
]


@pytest.mark.parametrize(("case", "raw_content", "valid"), _RAW_CASES)
def test_gptscan_promotes_only_explicitly_successful_structural_raw_output(
    case: str,
    raw_content: str | None,
    valid: bool,
    tmp_path: Path,
    monkeypatch,
) -> None:
    fake_main = tmp_path / "gptscan" / "src" / "main.py"
    fake_main.parent.mkdir(parents=True)
    fake_main.write_text("# test stub\n", encoding="utf-8")
    target = tmp_path / "Token.sol"
    target.write_text("pragma solidity ^0.8.20; contract Token {}", encoding="utf-8")
    out_dir = tmp_path / "out" / case
    monkeypatch.setattr(runner, "GPTSCAN_MAIN", fake_main)
    monkeypatch.setattr(runner, "GPTSCAN_PY", Path(sys.executable))
    monkeypatch.setattr(
        runner,
        "_run_solc_select",
        lambda *args, **kwargs: True,
    )

    def fake_stream(command, **kwargs):
        raw_path = Path(kwargs["env"]["LAKES_GPTSCAN_OUTPUT"])
        if raw_content == "__DIRECTORY__":
            raw_path.mkdir(parents=True)
        elif raw_content is not None:
            raw_path.write_text(raw_content, encoding="utf-8")
        return 0

    monkeypatch.setattr(runner, "_stream_process", fake_stream)

    rc = runner._run_gptscan(
        target,
        out_dir,
        "sk-private",
        7,
        "https://example.invalid",
    )

    assert rc == (0 if valid else 1)
    assert (out_dir / "result.json").exists() is valid
    if valid:
        normalized = json.loads((out_dir / "result.json").read_text(encoding="utf-8"))
        assert isinstance(normalized["findings"], list)
