"""CLI for transactional dynamic knowledge-base updates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from toolrank.kb_generation import (
    GenerationCommitError,
    GenerationValidationError,
    RecoveryRequiredError,
    recover_kb_root,
    validate_kb_root,
)
from toolrank.kb_update_service import (
    DensePassageIndexBuilder,
    KbUpdateService,
    KnowledgeExtractionError,
    MinerUConversionError,
    MinerUConverter,
    OpenAIKnowledgeExtractor,
)
from toolrank.openai_compat import DEFAULT_OPENAI_MODEL
from toolrank.retrieval import load_toolcards


app = typer.Typer(
    help="Extract, validate, and atomically publish dynamic LAKES knowledge.",
    no_args_is_help=True,
)

def _profiled_dataset_names(path: Path) -> set[str]:
    if not path.exists():
        return set()
    payload = json.loads(path.read_text(encoding="utf-8"))
    datasets = payload.get("datasets") if isinstance(payload, dict) else None
    if isinstance(datasets, dict):
        return {str(name) for name in datasets}
    return set()


def _result_payload(result) -> dict:
    return {
        "status": result.status,
        "paper_id": result.paper_id,
        "accepted_observations": result.accepted_observations,
        "accepted_passages": result.accepted_passages,
        "rejected_candidates": result.rejected_candidates,
        "generation_id": result.generation_id,
        "pointer_changed": result.pointer_changed,
        "reject_log_path": result.reject_log_path,
    }


@app.command("ingest")
def ingest(
    pdf: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True, help="Local paper PDF."),
    kb_root: Path = typer.Option(
        ...,
        "--kb-root",
        file_okay=False,
        help="Explicit writable KB root containing kb_current.json and immutable generations.",
    ),
    toolcards_dir: Path = typer.Option(
        ...,
        "--toolcards-dir",
        exists=True,
        file_okay=False,
        readable=True,
        help="Explicit read-only ToolCard alias source and baseline directory.",
    ),
    performance_db: Optional[Path] = typer.Option(
        None,
        "--performance-db",
        dir_okay=False,
        help="Baseline Performance KB (default: TOOLCARDS/performance_db.json).",
    ),
    passage_store: Optional[Path] = typer.Option(
        None,
        "--passage-store",
        dir_okay=False,
        help="Baseline PassageStore (default: TOOLCARDS/passage_store.json).",
    ),
    vector_index: Optional[Path] = typer.Option(
        None,
        "--vector-index",
        dir_okay=False,
        help="Baseline vector index (default: TOOLCARDS/vector_index/index.json).",
    ),
    contract_profiles: Optional[Path] = typer.Option(
        None,
        "--contract-profiles",
        dir_okay=False,
        help="Profile artifact used only to mark Stage 1 eligibility.",
    ),
    work_dir: Optional[Path] = typer.Option(
        None,
        "--work-dir",
        file_okay=False,
        help="Optional parent for private conversion/extraction work data.",
    ),
    mineru_command: str = typer.Option(
        "mineru",
        "--mineru-command",
        help="MinerU executable name/path; invoked as `mineru -p PDF -o DIR`.",
    ),
    llm_model: str = typer.Option(
        DEFAULT_OPENAI_MODEL,
        "--llm-model",
        help="OpenAI-compatible extraction model (credentials come from environment).",
    ),
    embedding_model: Optional[str] = typer.Option(
        None,
        "--embedding-model",
        help="Embedding model for the replacement passage index.",
    ),
    embedding_base_url: Optional[str] = typer.Option(
        None,
        "--embedding-base-url",
        help="Embedding endpoint; credentials come from environment, never argv.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Run conversion, extraction, mapping, index build, and validation without publishing.",
    ),
    emit: str = typer.Option("summary", "--emit", help="Output format: summary|json."),
) -> None:
    emit = emit.strip().lower()
    if emit not in {"summary", "json"}:
        raise typer.BadParameter("--emit must be summary or json")
    if kb_root.exists() and not kb_root.is_dir():
        raise typer.BadParameter("--kb-root must be a directory path")
    profile_path = contract_profiles or toolcards_dir / "contract_profiles.json"
    service = KbUpdateService(
        converter=MinerUConverter(command=mineru_command),
        extractor=OpenAIKnowledgeExtractor(model=llm_model),
        index_builder=DensePassageIndexBuilder(
            model=embedding_model,
            base_url=embedding_base_url,
        ),
        toolcards=load_toolcards(toolcards_dir),
        profiled_dataset_names=_profiled_dataset_names(profile_path),
        baseline_performance_path=performance_db or toolcards_dir / "performance_db.json",
        baseline_passage_path=passage_store or toolcards_dir / "passage_store.json",
        baseline_vector_index_path=(
            vector_index or toolcards_dir / "vector_index" / "index.json"
        ),
    )
    try:
        result = service.update(
            pdf=pdf,
            kb_root=kb_root,
            dry_run=dry_run,
            work_dir=work_dir,
        )
    except (
        MinerUConversionError,
        KnowledgeExtractionError,
        GenerationValidationError,
        GenerationCommitError,
        RecoveryRequiredError,
        OSError,
        ValueError,
    ) as exc:
        typer.echo(f"KB update failed: {exc}", err=True)
        raise typer.Exit(1) from exc
    payload = _result_payload(result)
    if emit == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    else:
        typer.echo(
            "\n".join(
                [
                    f"status: {result.status}",
                    f"paper_id: {result.paper_id}",
                    f"accepted_observations: {result.accepted_observations}",
                    f"accepted_passages: {result.accepted_passages}",
                    f"rejected_candidates: {result.rejected_candidates}",
                    f"generation_id: {result.generation_id or 'none'}",
                    f"pointer_changed: {str(result.pointer_changed).lower()}",
                ]
            )
        )
    if result.status == "REJECTED":
        raise typer.Exit(3)


@app.command("validate")
def validate(
    kb_root: Path = typer.Option(
        ...,
        "--kb-root",
        exists=True,
        file_okay=False,
        readable=True,
        help="Writable/readable dynamic KB root.",
    ),
    emit: str = typer.Option("summary", "--emit", help="Output format: summary|json."),
) -> None:
    try:
        manifest = validate_kb_root(kb_root)
    except (GenerationValidationError, OSError, ValueError) as exc:
        typer.echo(f"KB validation failed: {exc}", err=True)
        raise typer.Exit(1) from exc
    payload = manifest.model_dump(mode="json")
    if emit.strip().lower() == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    else:
        typer.echo(f"valid generation: {manifest.generation_id}")


@app.command("recover")
def recover(
    kb_root: Path = typer.Option(
        ...,
        "--kb-root",
        exists=True,
        file_okay=False,
        help="Dynamic KB root whose journal/pointer should be reconciled.",
    ),
) -> None:
    try:
        result = recover_kb_root(kb_root)
    except (RecoveryRequiredError, OSError, ValueError) as exc:
        typer.echo(f"KB recovery failed: {exc}", err=True)
        raise typer.Exit(5) from exc
    typer.echo(f"recovery: {result.status} generation={result.generation_id or 'none'}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
