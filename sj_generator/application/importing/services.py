from __future__ import annotations

from pathlib import Path
from typing import Callable

from sj_generator.domain.entities import Question
from sj_generator.infrastructure.document.source_reader import read_source_text
from sj_generator.infrastructure.llm.client import LlmClient
from sj_generator.infrastructure.llm.import_questions import (
    import_questions_from_sources,
    question_content_llm_config,
)
from sj_generator.infrastructure.llm.question_ref_scan import resolve_question_refs_with_scan
from sj_generator.infrastructure.persistence.draft_db_import import (
    import_draft_questions_to_db,
)


def load_docx_sources(paths: list[Path]) -> list[tuple[Path, str]]:
    sources: list[tuple[Path, str]] = []
    for path in paths:
        if path.suffix.lower() != ".docx":
            raise RuntimeError(f"当前仅支持 Word 文档导入：{path.name}")
        sources.append((path, read_source_text(path)))
    return sources


def resolve_question_refs_for_sources(
    *,
    paths: list[Path],
    progress_cb: Callable[[str], None] | None = None,
    compare_cb: Callable[[object], None] | None = None,
    scan_progress_cb: Callable[[object], None] | None = None,
    progress_count_cb: Callable[[int, int], None] | None = None,
    stop_cb: Callable[[], bool] | None = None,
):
    return resolve_question_refs_with_scan(
        sources=load_docx_sources(paths),
        progress_cb=progress_cb,
        compare_cb=compare_cb,
        scan_progress_cb=scan_progress_cb,
        progress_count_cb=progress_count_cb,
        stop_cb=stop_cb,
    )


def import_questions_for_sources(
    *,
    model_specs: list[dict[str, str]],
    paths: list[Path],
    question_refs_by_source: dict[str, list[dict[str, str]]],
    strategy: str,
    max_question_workers: int,
    progress_cb: Callable[[str], None] | None = None,
    question_cb: Callable[[Question], None] | None = None,
    compare_cb: Callable[[dict], None] | None = None,
    progress_count_cb: Callable[[int, int], None] | None = None,
    stop_cb: Callable[[], bool] | None = None,
):
    client_factories = {
        str(spec.get("key") or ""): _build_question_content_client_factory(
            provider=str(spec.get("provider") or ""),
            model_name=str(spec.get("model_name") or ""),
        )
        for spec in model_specs
        if str(spec.get("key") or "").strip()
    }
    return import_questions_from_sources(
        model_specs=model_specs,
        client_factories=client_factories,
        sources=load_docx_sources(paths),
        strategy=strategy,
        max_question_workers=max_question_workers,
        progress_cb=progress_cb,
        question_cb=question_cb,
        compare_cb=compare_cb,
        progress_count_cb=progress_count_cb,
        stop_cb=stop_cb,
        question_refs_by_source=question_refs_by_source,
    )


def commit_questions_to_db(
    *,
    db_path: Path,
    questions: list[Question],
    level_path: str,
    source_files: list[Path],
    textbook_version: str,
) -> int:
    return import_draft_questions_to_db(
        db_path=db_path,
        questions=questions,
        level_path=level_path,
        source_files=source_files,
        textbook_version=textbook_version,
    )


def _build_question_content_client_factory(
    *,
    provider: str,
    model_name: str,
) -> Callable[[], LlmClient]:
    return lambda provider=provider, model_name=model_name: LlmClient(
        question_content_llm_config(provider, model_name)
    )
