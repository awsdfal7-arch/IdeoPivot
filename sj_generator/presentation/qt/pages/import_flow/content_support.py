from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import QThread
from PyQt6.QtWidgets import QTableWidget

from .import_content_detail import (
    apply_compare_row_background,
    apply_content_detail_column_widths,
    apply_partial_pass_highlight,
    build_compare_verdict,
    content_detail_width_signature,
    format_json_cell,
    format_round_secs,
    question_content_detail_headers,
    question_content_payload_model_specs,
    record_round_sec,
    set_content_detail_item,
)
from .import_workers import AiImportContentWorker


def missing_content_model_labels(model_specs: list[dict[str, str]], ready_map: dict[str, bool]) -> list[str]:
    return [
        str(spec.get("label") or spec.get("provider") or spec.get("key") or "").replace("\n", " / ")
        for spec in model_specs
        if not ready_map.get(str(spec.get("key") or ""), False)
    ]


def build_content_status_text(
    *,
    progress_cur: int,
    progress_total: int,
    round_limit: int,
    concurrency: int,
    available_count: int,
    running: bool,
    failed: bool,
    stopped: bool,
    finished: bool,
) -> str:
    if progress_total > 0:
        completed = min(max(int(progress_cur), 0), progress_total)
        progress_text = f"选择题 {completed}/{progress_total}题"
    else:
        progress_text = "选择题 统计中"
    line = f"{progress_text}；最高轮次 {round_limit}轮；并发 {concurrency} 路"
    if not running and not failed and not stopped and finished and progress_total > 0 and progress_cur >= progress_total:
        line = f"{line}；可用题目 {max(0, int(available_count))}题"
    return line


def apply_content_detail_column_widths_if_needed(
    *,
    table: QTableWidget,
    model_specs: list[dict[str, str]],
    current_signature: str,
) -> str:
    signature = content_detail_width_signature(model_specs)
    if signature == current_signature:
        return current_signature
    apply_content_detail_column_widths(table, model_specs)
    return signature


@dataclass
class ContentCompareUpdate:
    model_specs: list[dict[str, str]]
    index: int
    round_no: str
    round_limit: int


def apply_content_compare_payload(
    *,
    table: QTableWidget,
    payload: dict[str, object],
    fallback_specs: list[dict[str, str]],
    row_map: dict[int, int],
    compare_secs: dict[int, dict[str, dict[int, int]]],
) -> ContentCompareUpdate | None:
    idx = int(payload.get("index") or 0)
    if idx <= 0:
        return None
    model_specs = question_content_payload_model_specs(payload, fallback_specs)
    table.setColumnCount(len(question_content_detail_headers(model_specs)))
    table.setHorizontalHeaderLabels(question_content_detail_headers(model_specs))
    row = row_map.get(idx)
    if row is None:
        row = table.rowCount()
        table.setRowCount(row + 1)
        row_map[idx] = row
    display_number = str(payload.get("requested_number") or idx)
    set_content_detail_item(table, row, 0, display_number)
    round_no_raw = payload.get("round")
    round_no_int = int(round_no_raw or 0)
    costs_sec_by_model = payload.get("costs_sec_by_model") if isinstance(payload.get("costs_sec_by_model"), dict) else {}
    results_by_model = payload.get("results_by_model") if isinstance(payload.get("results_by_model"), dict) else {}
    for spec in model_specs:
        model_key = str(spec.get("key") or "")
        record_round_sec(
            compare_secs,
            idx=idx,
            round_no=round_no_int,
            model_key=model_key,
            sec_value=costs_sec_by_model.get(model_key),
            ms_value=None,
        )
    for col_index, spec in enumerate(model_specs):
        model_key = str(spec.get("key") or "")
        set_content_detail_item(
            table,
            row,
            1 + col_index,
            format_round_secs(compare_secs, idx=idx, model_key=model_key),
        )
    value_col_offset = 1 + len(model_specs)
    for col_index, spec in enumerate(model_specs):
        model_key = str(spec.get("key") or "")
        set_content_detail_item(
            table,
            row,
            value_col_offset + col_index,
            format_json_cell(results_by_model.get(model_key)),
            is_json=True,
        )
    verdict = build_compare_verdict(payload)
    set_content_detail_item(table, row, value_col_offset + len(model_specs), verdict)
    apply_compare_row_background(table, row=row, payload=payload)
    apply_partial_pass_highlight(table, row=row, payload=payload, model_specs=model_specs)
    return ContentCompareUpdate(
        model_specs=model_specs,
        index=idx,
        round_no=str(round_no_raw or "?"),
        round_limit=max(1, int(payload.get("round_limit") or len(model_specs) or 1)),
    )


@dataclass
class ContentWorkerBundle:
    thread: QThread
    worker: AiImportContentWorker


def create_content_worker_bundle(
    *,
    parent,
    model_specs: list[dict[str, str]],
    paths: list[Path],
    question_refs_by_source: dict[str, list[dict[str, str]]],
    max_question_workers: int,
    on_progress,
    on_progress_count,
    on_question,
    on_compare,
    on_done,
    on_error,
) -> ContentWorkerBundle:
    thread = QThread(parent)
    worker = AiImportContentWorker(
        model_specs=model_specs,
        paths=paths,
        question_refs_by_source=dict(question_refs_by_source),
        strategy="per_question",
        max_question_workers=max_question_workers,
    )
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.progress.connect(on_progress)
    worker.progress_count.connect(on_progress_count)
    worker.question.connect(on_question)
    worker.compare.connect(on_compare)
    worker.done.connect(on_done)
    worker.error.connect(on_error)
    worker.done.connect(thread.quit)
    worker.error.connect(thread.quit)
    thread.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    return ContentWorkerBundle(thread=thread, worker=worker)
