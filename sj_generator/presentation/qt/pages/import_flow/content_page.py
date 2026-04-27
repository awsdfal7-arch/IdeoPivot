from PyQt6.QtCore import QThread, QTimer, Qt
from PyQt6.QtWidgets import (
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QTableWidget,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

from sj_generator.application.state import ImportWizardSession, normalize_ai_concurrency
from sj_generator.domain.entities import Question
from sj_generator.infrastructure.llm.import_questions import (
    _to_question,
    question_content_provider_ready,
    question_content_round_limit,
)
from sj_generator.presentation.qt.constants import (
    PAGE_AI_ANALYSIS,
    PAGE_DEDUPE_RESULT,
    PAGE_IMPORT_SUCCESS,
)
from .import_content_detail import (
    effective_content_question_workers,
    question_content_active_model_specs,
    question_content_detail_headers,
    question_content_model_signature,
    question_ref_total_count,
    set_content_detail_item,
)
from .import_page_common import style_busy_progress
from .import_progress import parse_content_progress_message
from .import_db_service import commit_draft_questions_to_db
from .import_workers import AiImportContentWorker
from sj_generator.presentation.qt.message_box import show_message_box
from .content_support import (
    apply_content_compare_payload,
    apply_content_detail_column_widths_if_needed,
    build_content_status_text,
    create_content_worker_bundle,
    missing_content_model_labels,
)
from sj_generator.presentation.qt.table_copy import CopyableTableWidget


class AiImportContentPage(QWizardPage):
    _DETAIL_TABLE_FONT_POINT_SIZE_MIN = 8
    _DETAIL_TABLE_FONT_POINT_SIZE_MAX = 28

    def __init__(self, state: ImportWizardSession) -> None:
        super().__init__()
        self._state = state
        self.setTitle("题目内容解析")
        self._detail_row_resize_pending = False
        self._detail_table_font_point_size = self._load_detail_table_font_point_size()

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setFormat("正在统计题数…")
        style_busy_progress(self._progress)

        self._stop_btn = QPushButton("停止解析")
        self._stop_btn.clicked.connect(self._stop)
        self._stop_btn.setEnabled(False)
        self._stop_btn.hide()

        self._retry_btn = QPushButton("重试")
        self._retry_btn.clicked.connect(self._retry)
        self._retry_btn.setEnabled(False)
        self._retry_btn.hide()

        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)

        self._detail_table = CopyableTableWidget(zoom_callback=self._adjust_detail_table_font_size)
        self._detail_table.setColumnCount(len(question_content_detail_headers()))
        self._detail_table.setHorizontalHeaderLabels(question_content_detail_headers())
        self._detail_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self._detail_table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._detail_table.setWordWrap(True)
        self._detail_table.setTextElideMode(Qt.TextElideMode.ElideNone)
        self._detail_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._detail_table.setRowCount(0)
        self._detail_table.horizontalHeader().sectionResized.connect(
            lambda *_: self._schedule_detail_row_resize()
        )
        self._detail_row_map: dict[int, int] = {}
        self._detail_width_signature = ""
        self._apply_detail_table_font_size()

        layout = QVBoxLayout()
        layout.addWidget(self._status_label)
        layout.addWidget(self._detail_table)
        self.setLayout(layout)

        self._items: list[Question] = []
        self._last_files_text: str = ""
        self._last_ref_version: int = -1
        self._last_content_model_signature: str = ""
        self._thread: QThread | None = None
        self._worker: AiImportContentWorker | None = None
        self._running = False
        self._stopped = False
        self._discard_run_results = False
        self._stop_requested = False
        self._retry_pending = False
        self._close_after_stop_requested = False
        self._force_finish_requested = False
        self._force_finish_detached = False
        self._force_finish_advance_attempts = 0
        self._finished = False
        self._failed = False
        self._progress_cur = 0
        self._progress_total = 0
        self._accepted_count = 0
        self._skipped_count = 0
        self._phase_text = "准备开始解析…"
        self._detail_text = ""
        self._parallel_text = ""
        self._consistency_text = ""
        self._detail_row_map = {}
        self._compare_secs: dict[int, dict[str, dict[int, int]]] = {}
        self._accepted_items_by_index: dict[int, Question] = {}
        self._content_model_specs = question_content_active_model_specs()
        self._content_model_ready: dict[str, bool] = {}
        self._cur_source_name = "-"
        self._cur_question_no = "-"
        self._cur_round_no = "-"
        self._waiting_detail_timer = QTimer(self)
        self._waiting_detail_timer.setInterval(1000)
        self._waiting_detail_timer.timeout.connect(self._refresh_waiting_placeholder_rows)
        self._waiting_elapsed_s = 0

    def initializePage(self) -> None:
        self._sync_wizard_buttons()
        if self._state.source.files:
            self._cur_source_name = self._state.source.files[0].name
        ref_version = int(self._state.refs.revision)
        content_model_specs = question_content_active_model_specs()
        content_model_signature = question_content_model_signature(content_model_specs)
        self._content_model_specs = content_model_specs
        self._detail_table.setColumnCount(len(question_content_detail_headers(self._content_model_specs)))
        self._detail_table.setHorizontalHeaderLabels(question_content_detail_headers(self._content_model_specs))
        self._apply_content_detail_column_widths_if_needed(model_specs=self._content_model_specs)
        should_restart = (
            self._state.source.files_text
            and (
                self._state.source.files_text != self._last_files_text
                or ref_version != self._last_ref_version
                or content_model_signature != self._last_content_model_signature
            )
        )
        should_auto_start = bool(
            self._state.source.files_text
            and question_ref_total_count(self._state.refs.question_refs_by_source) > 0
            and not self._running
            and not self._items
            and (self._thread is None or not self._thread.isRunning())
        )
        if should_restart or should_auto_start:
            self._last_files_text = self._state.source.files_text
            self._last_ref_version = ref_version
            self._last_content_model_signature = content_model_signature
            if should_restart:
                self._detail_table.setRowCount(0)
                self._detail_row_map = {}
                self._compare_secs = {}
                self._items = []
                self._progress.setRange(0, 0)
                self._progress.setValue(0)
            self._reset_progress_meta()
            self._phase_text = "正在解析题目内容，请稍候…"
            self._status_label.setText(self._phase_text)
            self._running = True
            self._stopped = False
            self._finished = False
            self._failed = False
            self._render_status()
            self.completeChanged.emit()
            QTimer.singleShot(30, self._start_import)

    def nextId(self) -> int:
        if self._state.dedupe_enabled:
            return PAGE_DEDUPE_RESULT
        return PAGE_AI_ANALYSIS if self._state.analysis_enabled else PAGE_IMPORT_SUCCESS

    def _sync_wizard_buttons(self) -> None:
        wizard = self.wizard()
        if not isinstance(wizard, QWizard):
            return
        back_button = wizard.button(QWizard.WizardButton.BackButton)
        if back_button is not None:
            back_button.setVisible(False)
        next_text = "开始导题"
        if self._stop_requested or self._stopped or self._failed:
            next_text = "重试后继续"
        elif self._force_finish_requested:
            next_text = "强制完成中…"
        elif self._running:
            next_text = "解析中…"
        elif self._items:
            if self._state.dedupe_enabled:
                next_text = "进入查重"
            elif self._state.analysis_enabled:
                next_text = "进入解析"
            else:
                next_text = "写入题库"
        wizard.setButtonText(QWizard.WizardButton.NextButton, next_text)
        self._sync_custom_wizard_button()

    def _sync_custom_wizard_button(self) -> None:
        wizard = self.wizard()
        if not isinstance(wizard, QWizard):
            return
        stop_button = wizard.button(QWizard.WizardButton.CustomButton1)
        retry_button = wizard.button(QWizard.WizardButton.CustomButton2)
        if stop_button is not None:
            stop_button.setText("停止解析")
            stop_button.setVisible(True)
            stop_button.setEnabled(self._stop_btn.isEnabled())
            try:
                stop_button.clicked.disconnect()
            except TypeError:
                pass
            stop_button.clicked.connect(self._stop)
        if retry_button is not None:
            retry_button.setText("重试")
            retry_button.setVisible(True)
            retry_button.setEnabled(self._retry_btn.isEnabled())
            try:
                retry_button.clicked.disconnect()
            except TypeError:
                pass
            retry_button.clicked.connect(self._retry)
        force_finish_button = wizard.button(QWizard.WizardButton.CustomButton3)
        if force_finish_button is not None:
            force_finish_button.setText("强制完成")
            force_finish_button.setVisible(True)
            force_finish_button.setEnabled(self._can_force_finish())
            try:
                force_finish_button.clicked.disconnect()
            except TypeError:
                pass
            force_finish_button.clicked.connect(self._force_finish)

    def isComplete(self) -> bool:
        if self._running or self._failed:
            return False
        if self._stopped or not self._finished:
            return False
        return len(self._items) > 0

    def validatePage(self) -> bool:
        if self._running:
            return False
        self._materialize_items_from_accepted_cache()
        if not self._items:
            show_message_box(self, title="暂无结果", text="当前没有可进入下一步的题目。", icon=QMessageBox.Icon.Warning)
            return False
        self._state.apply_draft_questions(self._items)
        if not self._state.dedupe_enabled and not self._state.analysis_enabled:
            return commit_draft_questions_to_db(self, self._state)
        self.completeChanged.emit()
        return True

    def _can_force_finish(self) -> bool:
        return self._running and (not self._force_finish_requested) and bool(
            self._items or self._accepted_items_by_index
        )

    def _start_import(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            return

        paths = self._state.source.files or []
        if not paths:
            show_message_box(self, title="未选择文件", text="请先选择待处理的资料文件。", icon=QMessageBox.Icon.Warning)
            return
        if question_ref_total_count(self._state.refs.question_refs_by_source) <= 0:
            show_message_box(self, title="缺少题号", text="请先完成题号与题型解析。", icon=QMessageBox.Icon.Warning)
            return

        self._content_model_specs = question_content_active_model_specs()
        ready_map = {
            str(spec.get("key") or ""): question_content_provider_ready(str(spec.get("provider") or ""))
            for spec in self._content_model_specs
        }
        self._content_model_ready = ready_map
        self._render_status()
        if not self._content_model_specs or not all(ready_map.values()):
            self._sync_wizard_buttons()
            missing_labels = missing_content_model_labels(self._content_model_specs, ready_map)
            missing_text = "、".join(label for label in missing_labels if label) or "题目内容解析模型"
            show_message_box(
                self,
                title="未配置",
                text=f"请先完成以下题目内容解析模型配置并通过可用性测试：{missing_text}",
                icon=QMessageBox.Icon.Warning,
            )
            return

        self._status_label.setText("正在解析题目内容，请稍候…")
        self._reset_progress_meta()
        self._phase_text = "正在解析题目内容，请稍候…"
        self._show_waiting_placeholder_rows()
        self._render_status()
        self._stop_btn.setEnabled(True)
        self._retry_btn.setEnabled(False)
        self._running = True
        self._stopped = False
        self._discard_run_results = False
        self._stop_requested = False
        self._retry_pending = False
        self._force_finish_requested = False
        self._force_finish_detached = False
        self._force_finish_advance_attempts = 0
        self._finished = False
        self._failed = False
        self._sync_wizard_buttons()
        self.completeChanged.emit()

        bundle = create_content_worker_bundle(
            parent=self,
            model_specs=self._content_model_specs,
            paths=paths,
            question_refs_by_source=dict(self._state.refs.question_refs_by_source),
            max_question_workers=effective_content_question_workers(
                normalize_ai_concurrency(self._state.question_content_concurrency),
                len(self._content_model_specs),
            ),
            on_progress=self._on_progress,
            on_progress_count=self._on_progress_count,
            on_question=self._on_question,
            on_compare=self._on_compare,
            on_done=self._on_done,
            on_error=self._on_error,
        )
        self._thread = bundle.thread
        self._worker = bundle.worker
        self._thread.start()

    def _on_progress(self, msg: str) -> None:
        if self._discard_run_results:
            return
        self._phase_text = msg
        self._update_detail_from_progress(msg)
        self._render_status()

    def _on_progress_count(self, current: int, total: int) -> None:
        if self._discard_run_results:
            return
        self._progress_cur = max(0, current)
        self._progress_total = max(0, total)
        if total <= 0:
            self._progress.setRange(0, 0)
            self._progress.setFormat("正在统计题数…")
            self._render_status()
            return
        if self._progress.maximum() != total:
            self._progress.setRange(0, total)
        self._progress.setValue(max(0, min(current, total)))
        self._progress.setFormat("选择题 %v/%m题")
        self._render_status()
        self._sync_wizard_buttons()

    def _on_question(self, question: Question) -> None:
        if self._discard_run_results:
            return
        self._items.append(question)
        self._accepted_count = len(self._items)
        self._render_status()
        self._sync_wizard_buttons()
        self.completeChanged.emit()

    def _on_compare(self, payload: object) -> None:
        if self._discard_run_results:
            return
        if not isinstance(payload, dict):
            return
        update = apply_content_compare_payload(
            table=self._detail_table,
            payload=payload,
            fallback_specs=self._content_model_specs,
            row_map=self._detail_row_map,
            compare_secs=self._compare_secs,
        )
        if update is None:
            return
        self._content_model_specs = update.model_specs
        self._detail_width_signature = apply_content_detail_column_widths_if_needed(
            table=self._detail_table,
            model_specs=self._content_model_specs,
            current_signature=self._detail_width_signature,
        )
        self._schedule_detail_row_resize()
        self._cur_question_no = str(update.index)
        self._cur_round_no = update.round_no
        self._cache_accepted_question(payload)
        self._phase_text = f"解析中：已回传第 {update.index} 题第 {update.round_no}/{update.round_limit} 轮比对结果"
        self._render_status()
        self._sync_wizard_buttons()

    def _schedule_detail_row_resize(self) -> None:
        if getattr(self, "_detail_row_resize_pending", False):
            return
        self._detail_row_resize_pending = True
        QTimer.singleShot(0, self._resize_detail_rows_to_contents)

    def _resize_detail_rows_to_contents(self) -> None:
        self._detail_row_resize_pending = False
        self._detail_table.resizeRowsToContents()

    def _load_detail_table_font_point_size(self) -> int:
        default_size = self.font().pointSize()
        if default_size <= 0:
            default_size = 10
        return max(
            self._DETAIL_TABLE_FONT_POINT_SIZE_MIN,
            min(self._DETAIL_TABLE_FONT_POINT_SIZE_MAX, default_size),
        )

    def _apply_detail_table_font_size(self) -> None:
        font = self._detail_table.font()
        font.setPointSize(self._detail_table_font_point_size)
        self._detail_table.setFont(font)
        self._detail_table.horizontalHeader().setFont(font)
        self._detail_table.verticalHeader().setFont(font)
        self._detail_table.doItemsLayout()
        self._detail_table.viewport().update()
        self._detail_table.horizontalHeader().viewport().update()
        self._schedule_detail_row_resize()

    def _adjust_detail_table_font_size(self, step: int) -> None:
        new_size = max(
            self._DETAIL_TABLE_FONT_POINT_SIZE_MIN,
            min(self._DETAIL_TABLE_FONT_POINT_SIZE_MAX, self._detail_table_font_point_size + int(step)),
        )
        if new_size == self._detail_table_font_point_size:
            return
        self._detail_table_font_point_size = new_size
        self._apply_detail_table_font_size()

    def _apply_content_detail_column_widths_if_needed(self, *, model_specs: list[dict[str, str]]) -> None:
        self._detail_width_signature = apply_content_detail_column_widths_if_needed(
            table=self._detail_table,
            model_specs=model_specs,
            current_signature=self._detail_width_signature,
        )

    def _apply_content_detail_column_widths(self, model_specs: list[dict[str, str]]) -> None:
        self._detail_width_signature = apply_content_detail_column_widths_if_needed(
            table=self._detail_table,
            model_specs=model_specs,
            current_signature="",
        )

    def _set_content_detail_item(self, row: int, col: int, text: str, *, is_json: bool = False) -> None:
        set_content_detail_item(self._detail_table, row, col, text, is_json=is_json)

    def _on_done(self, total: int) -> None:
        self._waiting_detail_timer.stop()
        if self._discard_run_results:
            if self._force_finish_detached:
                self._thread = None
                self._worker = None
                self._finish_close_after_stop_if_needed()
                return
            if self._force_finish_requested:
                self._finish_force_complete()
                return
            self._clear_partial_results()
            self._phase_text = "已停止解析，本轮结果已丢弃，请点击重试重新解析。"
            self._stop_btn.setEnabled(False)
            self._retry_btn.setEnabled(True)
            self._running = False
            self._stop_requested = False
            self._stopped = True
            self._finished = False
            self._thread = None
            self._worker = None
            self._render_status()
            self._sync_wizard_buttons()
            self.completeChanged.emit()
            self._finish_close_after_stop_if_needed()
            if self._retry_pending:
                self._retry_pending = False
                QTimer.singleShot(0, self._retry)
            return
        self._phase_text = f"解析完成：{total} 题（可继续进入下一步）"
        if self._progress.maximum() > 0:
            self._progress.setValue(self._progress.maximum())
            self._progress_cur = self._progress.maximum()
            self._progress_total = self._progress.maximum()
        self._stop_btn.setEnabled(False)
        self._retry_btn.setEnabled(True)
        self._running = False
        self._stop_requested = False
        self._stopped = False
        self._finished = True
        self._thread = None
        self._worker = None
        self._render_status()
        self._sync_wizard_buttons()
        self.completeChanged.emit()

    def _on_error(self, msg: str) -> None:
        self._waiting_detail_timer.stop()
        if self._discard_run_results:
            if self._force_finish_detached:
                self._thread = None
                self._worker = None
                self._finish_close_after_stop_if_needed()
                return
            if self._force_finish_requested:
                self._finish_force_complete(error_message=msg)
                return
            self._clear_partial_results()
            self._phase_text = "已停止解析，本轮结果已丢弃，请点击重试重新解析。"
            self._stop_btn.setEnabled(False)
            self._retry_btn.setEnabled(True)
            self._running = False
            self._stop_requested = False
            self._failed = False
            self._thread = None
            self._worker = None
            self._render_status()
            self._sync_wizard_buttons()
            self.completeChanged.emit()
            self._finish_close_after_stop_if_needed()
            if self._retry_pending:
                self._retry_pending = False
                QTimer.singleShot(0, self._retry)
            return
        show_message_box(self, title="解析失败", text=msg, icon=QMessageBox.Icon.Critical)
        self._phase_text = f"解析失败：{msg}"
        self._detail_text = msg
        self._append_failure_row(msg)
        self._stop_btn.setEnabled(False)
        self._retry_btn.setEnabled(True)
        self._running = False
        self._stop_requested = False
        self._failed = True
        self._thread = None
        self._worker = None
        self._render_status()
        self._sync_wizard_buttons()
        self.completeChanged.emit()

    def _append_failure_row(self, msg: str) -> None:
        row = self._detail_table.rowCount()
        self._detail_table.setRowCount(row + 1)
        text = f"失败：{msg}"
        self._set_content_detail_item(row, 0, "-")
        payload_col_start = 1 + len(self._content_model_specs)
        payload_col_end = payload_col_start + len(self._content_model_specs)
        for col in range(payload_col_start, payload_col_end):
            self._set_content_detail_item(row, col, "", is_json=True)
        self._set_content_detail_item(row, payload_col_end, text)
        self._schedule_detail_row_resize()

    def _stop(self) -> None:
        if self._worker is not None:
            self._worker.request_stop()
            self._discard_run_results = True
            self._stop_requested = True
            self._force_finish_requested = False
            self._stop_btn.setEnabled(False)
            self._retry_btn.setEnabled(True)
            self._running = False
            self._phase_text = "正在停止…可点击重试，收尾完成后将重新解析。"
            self._stopped = True
            self._clear_partial_results()
            self._render_status()
            self._sync_wizard_buttons()
            self.completeChanged.emit()

    def prepare_to_close(self) -> bool:
        thread = self._thread
        if thread is None or (not thread.isRunning()):
            return True
        if self._worker is not None:
            self._worker.request_stop()
        self._discard_run_results = True
        self._stop_requested = True
        self._force_finish_requested = False
        self._close_after_stop_requested = True
        self._stop_btn.setEnabled(False)
        self._retry_btn.setEnabled(False)
        self._running = False
        self._phase_text = "正在停止，收尾完成后将自动退出…"
        self._stopped = True
        self._clear_partial_results()
        self._render_status()
        self._sync_wizard_buttons()
        self.completeChanged.emit()
        return False

    def _retry(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            self._retry_pending = True
            self._retry_btn.setEnabled(False)
            self._phase_text = "正在停止当前解析，收尾完成后自动重试…"
            self._render_status()
            self._sync_wizard_buttons()
            return
        if self._running:
            return
        self._discard_run_results = False
        self._stop_requested = False
        self._retry_pending = False
        self._close_after_stop_requested = False
        self._force_finish_requested = False
        self._force_finish_detached = False
        self._force_finish_advance_attempts = 0
        self._clear_partial_results()
        self._phase_text = "准备重试解析…"
        self._stopped = False
        self._finished = False
        self._failed = False
        self._retry_btn.setEnabled(False)
        self._render_status()
        self._sync_wizard_buttons()
        self.completeChanged.emit()
        QTimer.singleShot(0, self._start_import)

    def _clear_partial_results(self) -> None:
        self._waiting_detail_timer.stop()
        self._waiting_elapsed_s = 0
        self._detail_table.setRowCount(0)
        self._detail_row_map = {}
        self._compare_secs = {}
        self._accepted_items_by_index = {}
        self._items = []
        self._progress.setRange(0, 0)
        self._progress.setValue(0)
        self._progress.setFormat("正在统计题数…")
        self._reset_progress_meta()

    def _show_waiting_placeholder_rows(self) -> None:
        refs = self._current_source_question_refs()
        if not refs:
            return
        self._waiting_detail_timer.stop()
        self._waiting_elapsed_s = 0
        self._detail_table.setRowCount(len(refs))
        self._detail_row_map = {}
        model_count = len(self._content_model_specs)
        payload_col_offset = 1 + model_count
        verdict_col = payload_col_offset + model_count
        for row_index, item in enumerate(refs):
            display_number = str(item.get("number") or row_index + 1)
            self._detail_row_map[row_index + 1] = row_index
            set_content_detail_item(self._detail_table, row_index, 0, display_number)
            for model_index in range(model_count):
                set_content_detail_item(self._detail_table, row_index, 1 + model_index, "等待 0s")
                set_content_detail_item(self._detail_table, row_index, payload_col_offset + model_index, "", is_json=True)
            set_content_detail_item(self._detail_table, row_index, verdict_col, "等待返回")
        self._schedule_detail_row_resize()
        self._waiting_detail_timer.start()

    def _refresh_waiting_placeholder_rows(self) -> None:
        if not self._running:
            return
        self._waiting_elapsed_s += 1
        model_count = len(self._content_model_specs)
        for row_index in range(self._detail_table.rowCount()):
            for model_index in range(model_count):
                item = self._detail_table.item(row_index, 1 + model_index)
                if item is None:
                    continue
                text = item.text().strip()
                if not text.startswith("等待 "):
                    continue
                item.setText(f"等待 {self._waiting_elapsed_s}s")

    def _current_source_question_refs(self) -> list[dict[str, str]]:
        source_files = list(self._state.source.files or [])
        refs_by_source = dict(self._state.refs.question_refs_by_source or {})
        for path in source_files:
            items = refs_by_source.get(str(path))
            if isinstance(items, list) and items:
                return [item for item in items if isinstance(item, dict)]
        for items in refs_by_source.values():
            if isinstance(items, list) and items:
                return [item for item in items if isinstance(item, dict)]
        return []

    def _reset_progress_meta(self) -> None:
        self._progress_cur = 0
        self._progress_total = 0
        self._accepted_count = 0
        self._skipped_count = 0
        self._detail_text = ""
        self._parallel_text = ""
        self._consistency_text = ""
        self._cur_question_no = "-"
        self._cur_round_no = "-"
        self._render_status()

    def _update_detail_from_progress(self, msg: str) -> None:
        parsed = parse_content_progress_message(msg)
        self._skipped_count += int(parsed.get("skipped_delta") or 0)
        source_name = str(parsed.get("source_name") or "").strip()
        if source_name:
            self._cur_source_name = source_name
        question_no = str(parsed.get("question_no") or "").strip()
        if question_no:
            self._cur_question_no = question_no
        round_no = str(parsed.get("round_no") or "").strip()
        if round_no:
            self._cur_round_no = round_no
        if "parallel_text" in parsed:
            self._parallel_text = str(parsed.get("parallel_text") or "")
            return
        if "consistency_text" in parsed:
            self._consistency_text = str(parsed.get("consistency_text") or "")
            if "parallel_text" in parsed:
                self._parallel_text = str(parsed.get("parallel_text") or "")
            return
        detail_text = str(parsed.get("detail_text") or "")
        if detail_text:
            self._detail_text = detail_text
            return

    def _render_status(self) -> None:
        self._status_label.setText(
            build_content_status_text(
                progress_cur=self._progress_cur,
                progress_total=self._progress_total,
                round_limit=question_content_round_limit(),
                concurrency=normalize_ai_concurrency(self._state.question_content_concurrency),
                available_count=self._accepted_count,
                running=self._running,
                failed=self._failed,
                stopped=self._stopped,
                finished=self._finished,
            )
        )

    def _force_finish(self) -> None:
        if not self._running:
            return
        if not (self._items or self._accepted_items_by_index):
            show_message_box(
                self,
                title="暂无可用结果",
                text="至少需要已有 1 题完整通过后，才能强制完成并进入下一步。",
                icon=QMessageBox.Icon.Warning,
            )
            return
        if self._worker is None:
            return
        self._worker.request_stop()
        self._discard_run_results = True
        self._force_finish_requested = False
        self._force_finish_detached = True
        self._stop_requested = False
        self._stop_btn.setEnabled(False)
        self._retry_btn.setEnabled(False)
        current_count = max(len(self._items), len(self._accepted_items_by_index))
        self._materialize_items_from_accepted_cache()
        self._running = False
        self._stopped = False
        self._finished = bool(self._items)
        self._failed = False
        self._phase_text = f"正在强制完成…已立即保留当前已处理完成的题目（{current_count} 题），马上进入下一步。"
        self._render_status()
        self._sync_wizard_buttons()
        self.completeChanged.emit()
        if self._items:
            QTimer.singleShot(0, self._advance_after_force_finish)

    def _finish_force_complete(self, *, error_message: str = "") -> None:
        self._materialize_items_from_accepted_cache()
        self._stop_btn.setEnabled(False)
        self._retry_btn.setEnabled(True)
        self._running = False
        self._discard_run_results = False
        self._stop_requested = False
        self._stopped = False
        self._finished = bool(self._items)
        self._failed = False
        self._force_finish_requested = False
        self._thread = None
        self._worker = None
        self._force_finish_advance_attempts = 0
        if self._items:
            self._phase_text = f"已强制完成：保留当前已完整返回的 {len(self._items)} 题，正在进入下一步…"
        else:
            self._phase_text = "强制完成失败：当前没有可进入下一步的完整题目。"
            if error_message:
                self._detail_text = error_message
        self._render_status()
        self._sync_wizard_buttons()
        self.completeChanged.emit()
        if not self._items:
            show_message_box(
                self,
                title="暂无结果",
                text="当前没有可进入下一步的完整题目，无法强制完成。",
                icon=QMessageBox.Icon.Warning,
            )
            return
        QTimer.singleShot(0, self._advance_after_force_finish)

    def _advance_after_force_finish(self) -> None:
        wizard = self.wizard()
        if not isinstance(wizard, QWizard):
            return
        next_button = wizard.button(QWizard.WizardButton.NextButton)
        if next_button is not None and next_button.isEnabled():
            next_button.click()
            return
        self._force_finish_advance_attempts += 1
        if self._force_finish_advance_attempts <= 5 and self._finished and self._items:
            QTimer.singleShot(50, self._advance_after_force_finish)

    def _cache_accepted_question(self, payload: dict[str, object]) -> None:
        if not bool(payload.get("accepted")):
            return
        accepted_obj = payload.get("accepted_obj")
        if not isinstance(accepted_obj, dict):
            return
        try:
            question = _to_question(accepted_obj)
        except Exception:
            return
        index = int(payload.get("index") or 0)
        if index <= 0:
            return
        self._accepted_items_by_index[index] = question
        self._accepted_count = max(self._accepted_count, len(self._accepted_items_by_index))

    def _materialize_items_from_accepted_cache(self) -> None:
        if self._items or not self._accepted_items_by_index:
            return
        self._items = [self._accepted_items_by_index[index] for index in sorted(self._accepted_items_by_index.keys())]
        self._accepted_count = len(self._items)

    def _finish_close_after_stop_if_needed(self) -> None:
        if not self._close_after_stop_requested:
            return
        self._close_after_stop_requested = False
        wizard = self.wizard()
        if isinstance(wizard, QWizard):
            QTimer.singleShot(0, wizard.close)

__all__ = ["AiImportContentPage"]
