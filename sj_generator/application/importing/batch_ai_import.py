from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
from pathlib import Path
import re
from typing import Callable

from sj_generator.infrastructure.llm.client import LlmClient
from sj_generator.infrastructure.llm.explanations import ExplanationInputs, generate_explanation_result
from sj_generator.infrastructure.llm.import_questions import import_questions_from_sources
from sj_generator.infrastructure.persistence.excel_repo import save_questions
from sj_generator.infrastructure.exporting.export_md import export_questions_to_markdown
from sj_generator.infrastructure.document.source_reader import read_source_text
from sj_generator.domain.entities import Question
from sj_generator.shared.paths import app_paths, common_mistakes_md_path


_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\\\|?*]+')


@dataclass(frozen=True)
class BatchAiImportResult:
    source_path: Path
    target_dir: Path
    target_xlsx: Path
    target_md: Path
    question_count: int


@dataclass(frozen=True)
class BatchAiProgress:
    file_index: int
    total_files: int
    file_name: str
    stage: str
    message: str
    question_current: int = 0
    question_total: int = 0
    question_count: int = 0


def process_source_files_to_folders(
    *,
    paths: list[Path],
    client: LlmClient | None = None,
    analysis_client: LlmClient | None = None,
    kimi_client: LlmClient | None = None,
    qwen_client: LlmClient | None = None,
    client_factory: Callable[[], LlmClient] | None = None,
    analysis_client_factory: Callable[[], LlmClient] | None = None,
    kimi_client_factory: Callable[[], LlmClient] | None = None,
    qwen_client_factory: Callable[[], LlmClient] | None = None,
    max_workers: int = 1,
    max_question_workers: int = 1,
    max_analysis_workers: int = 1,
    export_date: date | None = None,
    progress_cb: Callable[[str], None] | None = None,
    progress_info_cb: Callable[[BatchAiProgress], None] | None = None,
) -> list[BatchAiImportResult]:
    total = len(paths)
    if total <= 0:
        return []

    worker_count = max(1, int(max_workers))
    if worker_count == 1:
        if client is None or kimi_client is None or qwen_client is None:
            raise ValueError("串行模式需要提供 client、kimi_client 和 qwen_client。")
        results: list[BatchAiImportResult] = []
        for idx, raw_path in enumerate(paths, start=1):
            results.append(
                _process_single_source(
                    path=Path(raw_path),
                    idx=idx,
                    total=total,
                    client=client,
                    analysis_client=analysis_client or client,
                    kimi_client=kimi_client,
                    qwen_client=qwen_client,
                    client_factory=client_factory,
                    analysis_client_factory=analysis_client_factory or client_factory,
                    kimi_client_factory=kimi_client_factory,
                    qwen_client_factory=qwen_client_factory,
                    max_question_workers=max_question_workers,
                    max_analysis_workers=max_analysis_workers,
                    export_date=export_date,
                    progress_cb=progress_cb,
                    progress_info_cb=progress_info_cb,
                )
            )
        return results

    if client_factory is None or kimi_client_factory is None or qwen_client_factory is None:
        raise ValueError("并发模式需要提供 client_factory、kimi_client_factory 和 qwen_client_factory。")

    results_by_index: dict[int, BatchAiImportResult] = {}
    with ThreadPoolExecutor(max_workers=min(worker_count, total)) as executor:
        future_map = {
            executor.submit(
                _process_single_source,
                path=Path(raw_path),
                idx=idx,
                total=total,
                client=client_factory(),
                analysis_client=(analysis_client_factory or client_factory)(),
                kimi_client=kimi_client_factory(),
                qwen_client=qwen_client_factory(),
                client_factory=client_factory,
                analysis_client_factory=analysis_client_factory or client_factory,
                kimi_client_factory=kimi_client_factory,
                qwen_client_factory=qwen_client_factory,
                max_question_workers=max_question_workers,
                max_analysis_workers=max_analysis_workers,
                export_date=export_date,
                progress_cb=progress_cb,
                progress_info_cb=progress_info_cb,
            ): idx
            for idx, raw_path in enumerate(paths, start=1)
        }
        for future in as_completed(future_map):
            idx = future_map[future]
            results_by_index[idx] = future.result()
    return [results_by_index[idx] for idx in sorted(results_by_index.keys())]


def _process_single_source(
    *,
    path: Path,
    idx: int,
    total: int,
    client: LlmClient,
    analysis_client: LlmClient,
    kimi_client: LlmClient,
    qwen_client: LlmClient,
    client_factory: Callable[[], LlmClient] | None,
    analysis_client_factory: Callable[[], LlmClient] | None,
    kimi_client_factory: Callable[[], LlmClient] | None,
    qwen_client_factory: Callable[[], LlmClient] | None,
    max_question_workers: int,
    max_analysis_workers: int,
    export_date: date | None,
    progress_cb: Callable[[str], None] | None,
    progress_info_cb: Callable[[BatchAiProgress], None] | None,
) -> BatchAiImportResult:
    _emit_progress(
        idx=idx,
        total=total,
        file_name=path.name,
        stage="reading",
        message=f"({idx}/{total}) {path.name}：读取资料…",
        progress_cb=progress_cb,
        progress_info_cb=progress_info_cb,
    )
    text = read_source_text(path).strip()
    _emit_progress(
        idx=idx,
        total=total,
        file_name=path.name,
        stage="counting",
        message=f"({idx}/{total}) {path.name}：AI 解析准备中…",
        progress_cb=progress_cb,
        progress_info_cb=progress_info_cb,
    )
    imported = import_questions_from_sources(
        client=client,
        kimi_client=kimi_client,
        qwen_client=qwen_client,
        client_factory=client_factory,
        kimi_client_factory=kimi_client_factory,
        qwen_client_factory=qwen_client_factory,
        sources=[(path, text)],
        strategy="per_question",
        max_question_workers=max_question_workers,
        progress_cb=lambda msg: _emit_progress(
            idx=idx,
            total=total,
            file_name=path.name,
            stage="processing",
            message=msg,
            progress_cb=progress_cb,
            progress_info_cb=progress_info_cb,
        ),
        progress_count_cb=lambda current, total_questions: _emit_progress(
            idx=idx,
            total=total,
            file_name=path.name,
            stage="processing",
            message=f"({idx}/{total}) {path.name}：已完成 {current}/{total_questions} 题",
            question_current=current,
            question_total=total_questions,
            progress_cb=None,
            progress_info_cb=progress_info_cb,
        ),
    )
    questions_with_analysis = _fill_missing_explanations(
        questions=imported.questions,
        client=analysis_client,
        client_factory=analysis_client_factory,
        source_name=path.name,
        idx=idx,
        total=total,
        max_analysis_workers=max_analysis_workers,
        progress_cb=progress_cb,
        progress_info_cb=progress_info_cb,
    )
    safe_name = _sanitize_filename(path.stem) or path.stem or f"未命名_{idx}"
    target_dir = path.parent / safe_name
    target_dir.mkdir(parents=True, exist_ok=True)
    target_xlsx = target_dir / f"{safe_name}.xlsx"
    _emit_progress(
        idx=idx,
        total=total,
        file_name=path.name,
        stage="saving_xlsx",
        message=f"({idx}/{total}) {path.name}：写入 xlsx…",
        question_count=len(questions_with_analysis),
        progress_cb=progress_cb,
        progress_info_cb=progress_info_cb,
    )
    save_questions(target_xlsx, questions_with_analysis)
    target_md = target_dir / f"{safe_name}.md"
    md_text = export_questions_to_markdown(
        excel_file_name=safe_name,
        export_date=export_date or date.today(),
        questions=questions_with_analysis,
    )
    _emit_progress(
        idx=idx,
        total=total,
        file_name=path.name,
        stage="saving_md",
        message=f"({idx}/{total}) {path.name}：生成 Markdown…",
        question_count=len(questions_with_analysis),
        progress_cb=progress_cb,
        progress_info_cb=progress_info_cb,
    )
    target_md.write_text(md_text, encoding="utf-8")
    _emit_progress(
        idx=idx,
        total=total,
        file_name=path.name,
        stage="done",
        message=f"({idx}/{total}) {path.name}：完成，输出 {len(questions_with_analysis)} 题。",
        question_current=len(questions_with_analysis),
        question_total=len(questions_with_analysis),
        question_count=len(questions_with_analysis),
        progress_cb=progress_cb,
        progress_info_cb=progress_info_cb,
    )
    return BatchAiImportResult(
        source_path=path,
        target_dir=target_dir,
        target_xlsx=target_xlsx,
        target_md=target_md,
        question_count=len(questions_with_analysis),
    )


def _sanitize_filename(name: str) -> str:
    s = (name or "").strip()
    s = _INVALID_FILENAME_CHARS.sub("_", s)
    s = s.replace("\n", " ").replace("\r", " ").replace("\t", " ")
    return s.strip(" .")


def _fill_missing_explanations(
    *,
    questions: list[Question],
    client: LlmClient,
    client_factory: Callable[[], LlmClient] | None,
    source_name: str,
    idx: int,
    total: int,
    max_analysis_workers: int,
    progress_cb: Callable[[str], None] | None,
    progress_info_cb: Callable[[BatchAiProgress], None] | None,
) -> list[Question]:
    if not questions:
        return questions
    resource_paths = app_paths()
    root_dir = resource_paths.base_dir
    ref_dir = resource_paths.reference_resource_dir
    reference_md_paths = sorted(ref_dir.glob("*.md"), key=lambda p: p.name) if ref_dir.exists() else []
    include_common_mistakes = common_mistakes_md_path(root_dir).exists()

    tasks = [(i, q) for i, q in enumerate(questions) if not q.analysis.strip()]
    if not tasks:
        return questions

    updated = list(questions)
    total_tasks = len(tasks)
    worker_count = max(1, int(max_analysis_workers))
    if worker_count <= 1:
        for current, (row, q) in enumerate(tasks, start=1):
            result = _generate_one_explanation(
                client=client,
                question=q,
                reference_md_paths=reference_md_paths,
                include_common_mistakes=include_common_mistakes,
                root_dir=root_dir,
            )
            updated[row] = Question(
                number=q.number,
                stem=q.stem,
                options=q.options,
                answer=result.answer_text or q.answer,
                analysis=result.analysis_text,
                question_type=q.question_type,
                choice_1=q.choice_1,
                choice_2=q.choice_2,
                choice_3=q.choice_3,
                choice_4=q.choice_4,
            )
            _emit_progress(
                idx=idx,
                total=total,
                file_name=source_name,
                stage="generating_analysis",
                message=f"({idx}/{total}) {source_name}：已生成解析 {current}/{total_tasks}",
                question_current=current,
                question_total=total_tasks,
                question_count=len(questions),
                progress_cb=progress_cb,
                progress_info_cb=progress_info_cb,
            )
        return updated

    if client_factory is None:
        raise ValueError("解析并发需要提供 client_factory。")

    _emit_progress(
        idx=idx,
        total=total,
        file_name=source_name,
        stage="generating_analysis",
        message=f"({idx}/{total}) {source_name}：并发生成解析中…",
        question_current=0,
        question_total=total_tasks,
        question_count=len(questions),
        progress_cb=progress_cb,
        progress_info_cb=progress_info_cb,
    )
    completed = 0
    with ThreadPoolExecutor(max_workers=min(worker_count, total_tasks)) as executor:
        future_map = {
            executor.submit(
                _generate_one_explanation,
                client=client_factory(),
                question=q,
                reference_md_paths=reference_md_paths,
                include_common_mistakes=include_common_mistakes,
                root_dir=root_dir,
            ): (row, q)
            for row, q in tasks
        }
        for future in as_completed(future_map):
            row, q = future_map[future]
            result = future.result()
            updated[row] = Question(
                number=q.number,
                stem=q.stem,
                options=q.options,
                answer=result.answer_text or q.answer,
                analysis=result.analysis_text,
                question_type=q.question_type,
                choice_1=q.choice_1,
                choice_2=q.choice_2,
                choice_3=q.choice_3,
                choice_4=q.choice_4,
            )
            completed += 1
            _emit_progress(
                idx=idx,
                total=total,
                file_name=source_name,
                stage="generating_analysis",
                message=f"({idx}/{total}) {source_name}：已生成解析 {completed}/{total_tasks}",
                question_current=completed,
                question_total=total_tasks,
                question_count=len(questions),
                progress_cb=progress_cb,
                progress_info_cb=progress_info_cb,
            )
    return updated


def _generate_one_explanation(
    *,
    client: LlmClient,
    question: Question,
    reference_md_paths: list[Path],
    include_common_mistakes: bool,
    root_dir: Path,
) -> str:
    inp = ExplanationInputs(
        question_text=_question_text_for_explanation(question),
        answer_text=question.answer,
        reference_md_paths=reference_md_paths,
        include_common_mistakes=include_common_mistakes,
        root_dir=root_dir,
    )
    return generate_explanation_result(client, inp)


def _question_text_for_explanation(q: Question) -> str:
    stem = q.stem.strip()
    options = q.options.strip()
    if not options:
        return stem
    return f"{stem}\n{options}"


def _emit_progress(
    *,
    idx: int,
    total: int,
    file_name: str,
    stage: str,
    message: str,
    question_current: int = 0,
    question_total: int = 0,
    question_count: int = 0,
    progress_cb: Callable[[str], None] | None,
    progress_info_cb: Callable[[BatchAiProgress], None] | None,
) -> None:
    if progress_cb is not None:
        progress_cb(message)
    if progress_info_cb is not None:
        progress_info_cb(
            BatchAiProgress(
                file_index=idx,
                total_files=total,
                file_name=file_name,
                stage=stage,
                message=message,
                question_current=question_current,
                question_total=question_total,
                question_count=question_count,
            )
        )
