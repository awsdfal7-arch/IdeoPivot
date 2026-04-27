from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import QThread
from PyQt6.QtWidgets import QHeaderView, QTableWidget

from sj_generator.infrastructure.llm.question_ref_scan import question_ref_model_specs
from .import_question_ref_detail import (
    build_question_ref_detail_rows,
    populate_question_ref_detail_table,
    question_ref_detail_headers,
    question_ref_detail_model_specs,
)
from .import_ref_session import QuestionRefRuntimeState
from .import_workers import AiQuestionRefWorker

_PROVIDER_LABELS = {
    "deepseek": "DeepSeek",
    "kimi": "Kimi",
    "qwen": "千问",
}


def missing_question_ref_provider_labels(ready_map: dict[str, bool]) -> list[str]:
    required_providers = {
        str(item.get("provider") or "").strip().lower()
        for item in question_ref_model_specs()
        if str(item.get("provider") or "").strip()
    }
    return [
        _PROVIDER_LABELS.get(provider, provider)
        for provider in required_providers
        if not ready_map.get(provider, False)
    ]


def render_question_ref_detail_table(
    *,
    table: QTableWidget,
    ref_state: QuestionRefRuntimeState,
    build_combo: Callable[..., object],
) -> None:
    model_specs = question_ref_detail_model_specs(ref_state.question_ref_payloads)
    header_labels = question_ref_detail_headers(model_specs)
    table.setColumnCount(len(header_labels))
    table.setHorizontalHeaderLabels(header_labels)
    apply_question_ref_detail_column_widths(table)
    table.clearContents()
    rows = build_question_ref_detail_rows(
        payloads=ref_state.question_ref_payloads,
        model_specs=model_specs,
        resolve_manual_type=ref_state.resolve_manual_question_type,
    )
    rows.extend(ref_state.build_waiting_detail_rows(model_specs))
    populate_question_ref_detail_table(
        table=table,
        rows=rows,
        manual_col=table.columnCount() - 1,
        overridden_pairs=set(ref_state.manual_question_type_overrides.keys()),
        build_combo=build_combo,
    )


def apply_question_ref_detail_column_widths(table: QTableWidget) -> None:
    header = table.horizontalHeader()
    column_count = table.columnCount()
    if column_count <= 0:
        return
    for col in range(max(0, column_count - 1)):
        header.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
    for col in range(max(0, column_count - 1), column_count):
        header.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
        table.setColumnWidth(col, 120)


@dataclass
class QuestionRefWorkerBundle:
    thread: QThread
    worker: AiQuestionRefWorker


def create_question_ref_worker_bundle(
    *,
    parent,
    cfg,
    paths: list[Path],
    on_progress,
    on_scan_progress,
    on_progress_count,
    on_compare,
    on_done,
    on_error,
) -> QuestionRefWorkerBundle:
    thread = QThread(parent)
    worker = AiQuestionRefWorker(cfg=cfg, paths=paths)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.progress.connect(on_progress)
    worker.scan_progress.connect(on_scan_progress)
    worker.progress_count.connect(on_progress_count)
    worker.compare.connect(on_compare)
    worker.done.connect(on_done)
    worker.error.connect(on_error)
    worker.done.connect(thread.quit)
    worker.error.connect(thread.quit)
    thread.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    return QuestionRefWorkerBundle(thread=thread, worker=worker)
