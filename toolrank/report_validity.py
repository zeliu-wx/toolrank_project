"""Current-run report validation and final-directory promotion."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import tempfile
import uuid
from typing import Any


_REPORT_LIST_KEYS = ("findings", "results", "vulnerabilities", "issues", "detectors")
OUTPUT_CLEANUP_FAILURE_RETURN_CODE = 74
CANONICAL_FINAL_ARTIFACTS = (
    "fused_report.json",
    "execution.json",
    "tool_run_statuses.json",
    "fusion_plan.json",
)


def canonical_contract_output_dir(
    results_root: str | Path,
    target_path: str | Path,
) -> Path:
    """Return the one public LAKES output directory for a target."""
    root = Path(results_root).expanduser().absolute()
    lakes_root = root if root.name == "LAKES_out" else root / "LAKES_out"
    target = Path(target_path)
    contract_id = target.stem if target.suffix.lower() == ".sol" else target.name
    return lakes_root.resolve() / contract_id


def atomic_write_text(path: str | Path, payload: str) -> None:
    """Publish one UTF-8 text artifact without exposing a partial file."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / (
        f".{destination.name}.{uuid.uuid4().hex}.tmp"
    )
    fd = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o666,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _has_semantic_failure(payload: dict[str, Any]) -> bool:
    analysis = payload.get("analysis")
    scopes = [payload]
    if isinstance(analysis, dict):
        scopes.append(analysis)
    for scope in scopes:
        success = scope.get("success")
        if success is not None and (
            success is False
            or str(success).strip().lower() in {"false", "0", "no"}
        ):
            return True
        for key in ("error", "errors", "fail", "fails", "failures"):
            if scope.get(key):
                return True
    parser = payload.get("parser")
    parser_status = parser.get("status") if isinstance(parser, dict) else None
    statuses = [parser_status, *(scope.get("status") for scope in scopes)]
    failed_statuses = {
        "error",
        "fail",
        "failed",
        "failure",
        "skip",
        "skipped",
        "timeout",
        "timed_out",
        "unsupported",
    }
    return any(
        str(status or "").strip().lower() in failed_statuses
        for status in statuses
    )


def load_valid_report(path: str | Path) -> dict[str, Any] | None:
    """Return a report object only when it has a recognized findings container."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if _has_semantic_failure(payload):
        return None
    if any(isinstance(payload.get(key), list) for key in _REPORT_LIST_KEYS):
        return payload
    analysis = payload.get("analysis")
    if isinstance(analysis, dict) and any(
        isinstance(analysis.get(key), list) for key in ("findings", "results")
    ):
        return payload
    return None


def find_valid_report(root: str | Path) -> Path | None:
    """Find a valid ``result.json`` inside one private invocation tree."""
    path = Path(root)
    if path.is_file():
        return path if path.name == "result.json" and load_valid_report(path) is not None else None
    if not path.is_dir():
        return None
    direct = path / "result.json"
    candidates = [direct] if direct.is_file() else []
    candidates.extend(
        candidate
        for candidate in sorted(path.rglob("result.json"))
        if candidate != direct
    )
    return next(
        (candidate for candidate in candidates if load_valid_report(candidate) is not None),
        None,
    )


def make_run_quarantine_root(scan_root: str | Path) -> Path:
    """Return a unique quarantine root outside selected tool directories."""
    return Path(scan_root) / f".lakes_quarantine_{uuid.uuid4().hex}"


def _path_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def remove_or_quarantine_tree(
    output_tree: str | Path,
    quarantine_root: str | Path,
) -> bool:
    """Remove an output tree or atomically isolate it from report scanning."""
    output = Path(output_tree)
    quarantine = Path(quarantine_root)
    if not _path_exists(output):
        return True
    try:
        if output.is_dir() and not output.is_symlink():
            shutil.rmtree(output)
        else:
            output.unlink()
    except OSError:
        if not _path_exists(output):
            return True
        try:
            quarantine.mkdir(parents=True, exist_ok=True)
            isolated = quarantine / f"{output.name}_{uuid.uuid4().hex}"
            os.replace(output, isolated)
        except OSError:
            return not _path_exists(output)
        try:
            if isolated.is_dir() and not isolated.is_symlink():
                shutil.rmtree(isolated)
            else:
                isolated.unlink()
        except OSError:
            pass
        return not _path_exists(output)
    return not _path_exists(output)


def clear_canonical_final_artifacts(output_dir: str | Path) -> bool:
    """Invalidate the previous public result before a new analyzer run starts."""
    output = Path(output_dir)
    quarantine_root = make_run_quarantine_root(output.parent)
    return all(
        remove_or_quarantine_tree(output / filename, quarantine_root)
        for filename in CANONICAL_FINAL_ARTIFACTS
    )


def clear_selected_run_artifacts(
    results_root: str | Path,
    selected_tool_ids: list[str],
    *,
    quarantine_root: str | Path,
) -> bool:
    """Remove every selected artifact that report/status loaders can consume."""
    root = Path(results_root)
    paths = [root / "tool_run_statuses.json"]
    for tool_id in dict.fromkeys(selected_tool_ids):
        paths.extend(
            (
                root / tool_id,
                root / f"{tool_id}.json",
                root / f"{tool_id}.sarif",
            )
        )
    return all(
        remove_or_quarantine_tree(path, quarantine_root)
        for path in paths
    )


def promote_valid_report_tree(
    staged_root: str | Path,
    final_dir: str | Path,
    *,
    quarantine_root: str | Path,
) -> bool:
    """Copy a validated snapshot beside the destination, then rename it into place."""
    staged = Path(staged_root)
    final = Path(final_dir)
    quarantine = Path(quarantine_root)
    if find_valid_report(staged) is None:
        return False
    promotion_root: Path | None = None
    try:
        final.parent.mkdir(parents=True, exist_ok=True)
        quarantine.mkdir(parents=True, exist_ok=True)
        promotion_root = Path(
            tempfile.mkdtemp(prefix=".lakes_report_promotion_", dir=quarantine)
        )
        candidate = promotion_root / "payload"
        shutil.copytree(staged, candidate)
        if find_valid_report(candidate) is None:
            return False
        if _path_exists(final) and not remove_or_quarantine_tree(final, quarantine):
            return False
        os.replace(candidate, final)
        return True
    except OSError:
        return False
    finally:
        if promotion_root is not None:
            for _attempt in range(2):
                try:
                    shutil.rmtree(promotion_root, ignore_errors=True)
                    break
                except OSError:
                    continue
