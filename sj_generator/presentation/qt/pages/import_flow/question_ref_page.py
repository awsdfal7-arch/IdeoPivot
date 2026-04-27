import os
from pathlib import Path

from PyQt6.QtCore import QThread, QTimer, Qt
from PyQt6.QtGui import QBrush
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

from sj_generator.application.settings import (
    load_deepseek_config,
    load_kimi_config,
    load_qwen_config,
)
from sj_generator.application.state import ImportWizardSession
from sj_generator.infrastructure.llm.question_ref_scan import question_ref_model_specs
from sj_generator.presentation.qt.constants import PAGE_AI_IMPORT_CONTENT
from .import_content_detail import question_ref_total_count
from .import_page_common import style_busy_progress
from .import_question_ref_detail import (
    build_manual_type_combo,
    question_ref_detail_headers,
)
from .import_ref_session import QuestionRefRuntimeState
from .import_workers import AiQuestionRefWorker
from sj_generator.presentation.qt.message_box import show_message_box
from .question_ref_support import (
    apply_question_ref_detail_column_widths,
    create_question_ref_worker_bundle,
    missing_question_ref_provider_labels,
    render_question_ref_detail_table,
)
from sj_generator.presentation.qt.table_copy import CopyableTableWidget


class AiImportPage(QWizardPage):
    def __init__(self, state: ImportWizardSession) -> None:
        super().__init__()
        self._state = state
        self.setTitle("题号与题型解析")
        self._detail_row_resize_pending = False

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setFormat("正在统计题数…")
        style_busy_progress(self._progress)
        self._progress.hide()

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
        self._status_label.hide()

        self._detail_table = CopyableTableWidget()
        self._detail_table.setColumnCount(len(question_ref_detail_headers()))
        self._detail_table.setHorizontalHeaderLabels(question_ref_detail_headers())
        self._detail_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._apply_question_ref_detail_column_widths()
        self._detail_table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._detail_table.setShowGrid(True)
        self._detail_table.setWordWrap(True)
        self._detail_table.setTextElideMode(Qt.TextElideMode.ElideNone)
        self._detail_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._detail_table.setStyleSheet(
            """
            QTableWidget {
                border: 1px solid black;
                gridline-color: black;
                selection-background-color: rgba(0, 0, 0, 0);
                selection-color: black;
            }
            """
        )
        self._detail_table.setRowCount(0)
        self._detail_table.itemSelectionChanged.connect(self._sync_open_doc_button)
        self._detail_table.itemDoubleClicked.connect(self._on_detail_item_double_clicked)
        self._detail_table.horizontalHeader().sectionResized.connect(
            lambda *_: self._schedule_detail_row_resize()
        )
        self._detail_row_map: dict[int, int] = {}
        layout = QVBoxLayout()
        layout.addWidget(self._detail_table)
        self.setLayout(layout)

        self._ref_state = QuestionRefRuntimeState()
        self._last_files_text: str = ""
        self._thread: QThread | None = None
        self._worker: AiQuestionRefWorker | None = None
        self._running = False
        self._stopped = False
        self._discard_run_results = False
        self._stop_requested = False
        self._retry_pending = False
        self._close_after_stop_requested = False
        self._finished = False
        self._failed = False
        self._phase_text = "准备开始解析…"
        self._detail_row_map = {}
        self._deepseek_ready = False
        self._qwen_ready = False
        self._kimi_ready = False
        self._wait_timer = QTimer(self)
        self._wait_timer.setInterval(1000)
        self._wait_timer.timeout.connect(self._refresh_waiting_detail_rows)

    def initializePage(self) -> None:
        self._sync_wizard_buttons()
        if self._state.source.files:
            self._ref_state.cur_source_name = self._state.source.files[0].name
        if self._state.source.files_text and self._state.source.files_text != self._last_files_text:
            self._last_files_text = self._state.source.files_text
            self._detail_table.setRowCount(0)
            self._detail_row_map = {}
            self._wait_timer.stop()
            self._ref_state.reset(source_name=self._ref_state.cur_source_name)
            self._progress.setRange(0, 0)
            self._progress.setValue(0)
            self._reset_progress_meta()
            self._phase_text = "正在解析题号与题型，请稍候…"
            self._status_label.setText(self._phase_text)
            self._state.refs.question_refs_by_source = {}
            self._running = True
            self._stopped = False
            self._finished = False
            self._failed = False
            self._render_status()
            self.completeChanged.emit()
            self.repaint()
            QApplication.processEvents()
            QTimer.singleShot(30, self._start_import)

    def nextId(self) -> int:
        return PAGE_AI_IMPORT_CONTENT

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
        elif self._running:
            next_text = "解析中…"
        elif self._ref_state.question_refs_by_source:
            next_text = "进入题目内容解析"
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
        open_button = wizard.button(QWizard.WizardButton.CustomButton3)
        if open_button is not None:
            open_button.setText("打开文档")
            open_button.setVisible(True)
            open_button.setEnabled(self._detail_table.currentRow() >= 0)
            try:
                open_button.clicked.disconnect()
            except TypeError:
                pass
            open_button.clicked.connect(self._open_selected_source_doc)

    def _sync_open_doc_button(self) -> None:
        wizard = self.wizard()
        if not isinstance(wizard, QWizard):
            return
        button = wizard.button(QWizard.WizardButton.CustomButton3)
        if button is None:
            return
        button.setEnabled(self._detail_table.currentRow() >= 0)

    def isComplete(self) -> bool:
        if self._running or self._failed:
            return False
        if self._stopped or not self._finished:
            return False
        if self._ref_state.has_unresolved_manual_types():
            return False
        return self._ref_state.accepted_count > 0

    def validatePage(self) -> bool:
        if self._running:
            return False
        if question_ref_total_count(self._ref_state.question_refs_by_source) <= 0:
            show_message_box(self, title="暂无结果", text="当前没有可进入下一步的题号。", icon=QMessageBox.Icon.Warning)
            return False
        if self._ref_state.has_unresolved_manual_types():
            show_message_box(
                self,
                title="请选择题型",
                text="当前仍有“对比结论不一致”的题目未选择题型，请先手动选择后再继续。",
                icon=QMessageBox.Icon.Warning,
            )
            return False
        self._state.apply_question_refs(self._ref_state.question_refs_by_source)
        self.completeChanged.emit()
        return True

    def _start_import(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            return

        paths = self._state.source.files or []
        if not paths:
            show_message_box(self, title="未选择文件", text="请先选择待处理的资料文件。", icon=QMessageBox.Icon.Warning)
            return

        cfg = load_deepseek_config()
        kimi_cfg = load_kimi_config()
        qwen_cfg = load_qwen_config()
        self._deepseek_ready = cfg.is_ready()
        self._kimi_ready = kimi_cfg.is_ready()
        self._qwen_ready = qwen_cfg.is_ready()
        self._render_status()
        ready_map = {
            "deepseek": cfg.is_ready(),
            "kimi": kimi_cfg.is_ready(),
            "qwen": qwen_cfg.is_ready(),
        }
        missing_labels = missing_question_ref_provider_labels(ready_map)
        if missing_labels:
            self._sync_wizard_buttons()
            show_message_box(
                self,
                title="未配置",
                text="题号与题型解析所需模型尚未全部可用：" + "、".join(missing_labels),
                icon=QMessageBox.Icon.Warning,
            )
            return

        self._status_label.setText("正在解析题号与题型，请稍候…")
        self._reset_progress_meta()
        self._wait_timer.stop()
        self._ref_state.stop_waiting_feedback()
        self._phase_text = "正在解析题号与题型，请稍候…"
        self._show_waiting_placeholder(paths)
        self._render_status()
        self._stop_btn.setEnabled(True)
        self._retry_btn.setEnabled(False)
        self._running = True
        self._stopped = False
        self._discard_run_results = False
        self._stop_requested = False
        self._retry_pending = False
        self._finished = False
        self._failed = False
        self._sync_wizard_buttons()
        self.completeChanged.emit()

        bundle = create_question_ref_worker_bundle(
            parent=self,
            cfg=cfg,
            paths=paths,
            on_progress=self._on_progress,
            on_scan_progress=self._on_scan_progress,
            on_progress_count=self._on_progress_count,
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
        self._ref_state.update_progress(current, total)
        if total <= 0:
            self._progress.setRange(0, 0)
            self._progress.setFormat("正在统计资料…")
            self._render_status()
            return
        if self._progress.maximum() != total:
            self._progress.setRange(0, total)
        self._progress.setValue(max(0, min(current, total)))
        self._progress.setFormat("资料 %v/%m个")
        self._render_status()

    def _on_compare(self, payload: object) -> None:
        if self._discard_run_results:
            return
        if not isinstance(payload, dict):
            return
        source_name = self._ref_state.apply_compare_payload(payload)
        if not source_name:
            return
        self._render_question_ref_detail_rows()
        self._phase_text = f"题号与题型解析中：{source_name} 已返回结果"
        self._render_status()

    def _schedule_detail_row_resize(self) -> None:
        if getattr(self, "_detail_row_resize_pending", False):
            return
        self._detail_row_resize_pending = True
        QTimer.singleShot(0, self._resize_detail_rows_to_contents)

    def _resize_detail_rows_to_contents(self) -> None:
        self._detail_row_resize_pending = False
        self._detail_table.resizeRowsToContents()

    def _on_done(self, result: object) -> None:
        self._wait_timer.stop()
        self._ref_state.stop_waiting_feedback()
        if self._discard_run_results:
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
        self._ref_state.apply_done_payload(result)
        self._render_question_ref_detail_rows()
        total = self._ref_state.accepted_count
        self._phase_text = f"题号与题型解析完成：共 {total} 个题号（可继续进入下一步）"
        if self._progress.maximum() > 0:
            self._progress.setValue(self._progress.maximum())
            self._ref_state.update_progress(self._progress.maximum(), self._progress.maximum())
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
        self._wait_timer.stop()
        self._ref_state.stop_waiting_feedback()
        if self._discard_run_results:
            self._clear_partial_results()
            self._phase_text = "已停止解析，本轮结果已丢弃，请点击重试重新解析。"
            self._stop_btn.setEnabled(False)
            self._retry_btn.setEnabled(True)
            self._running = False
            self._stop_requested = False
            self._stopped = True
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
        self._phase_text = f"题号与题型解析失败：{msg}"
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
        self._finish_close_after_stop_if_needed()

    def _append_failure_row(self, msg: str) -> None:
        row = self._detail_table.rowCount()
        self._detail_table.setRowCount(row + 1)
        values = ["失败"] + [""] * (self._detail_table.columnCount() - 3) + [f"失败：{msg}", ""]
        for col, value in enumerate(values):
            self._detail_table.setItem(row, col, QTableWidgetItem(value))
        self._schedule_detail_row_resize()

    def _stop(self) -> None:
        if self._worker is not None:
            self._worker.request_stop()
            self._discard_run_results = True
            self._stop_requested = True
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
        self._clear_partial_results()
        self._phase_text = "准备重试题号与题型解析…"
        self._stopped = False
        self._finished = False
        self._failed = False
        self._retry_btn.setEnabled(False)
        self._render_status()
        self._sync_wizard_buttons()
        self.completeChanged.emit()
        QTimer.singleShot(0, self._start_import)

    def _reset_progress_meta(self) -> None:
        self._ref_state.reset_progress()
        self._render_status()

    def _update_detail_from_progress(self, msg: str) -> None:
        self._ref_state.update_source_from_progress(msg)

    def _render_status(self) -> None:
        self._status_label.setText(self._ref_state.status_text())

    def _build_question_progress_text(self) -> str:
        return self._ref_state.question_progress_text()

    def _render_question_ref_detail_rows(self) -> None:
        self._render_question_ref_detail_rows_with_view_restore()

    def _render_question_ref_detail_rows_with_view_restore(self) -> None:
        view_state = self._capture_detail_table_view_state()
        render_question_ref_detail_table(
            table=self._detail_table,
            ref_state=self._ref_state,
            build_combo=self._build_manual_type_combo,
        )
        self._restore_detail_table_view_state(view_state)
        self._schedule_detail_row_resize()

    def _apply_question_ref_detail_column_widths(self) -> None:
        apply_question_ref_detail_column_widths(self._detail_table)

    def _build_manual_type_combo(
        self,
        *,
        source_key: str,
        number: str,
        current_type: str,
        background: QBrush | None,
    ) -> QComboBox:
        return build_manual_type_combo(
            table=self._detail_table,
            current_type=current_type,
            background=background,
            on_changed=lambda text, sk=source_key, num=number: self._on_manual_question_type_changed(sk, num, text),
        )

    def _open_source_doc(self, source_key: str) -> None:
        path = Path(str(source_key or "").strip())
        if not path.exists():
            show_message_box(self, title="文件不存在", text=f"未找到文档：{path}", icon=QMessageBox.Icon.Warning)
            return
        try:
            os.startfile(str(path))
        except Exception as exc:
            show_message_box(self, title="打开失败", text=f"无法打开 Word 文档：{exc}", icon=QMessageBox.Icon.Critical)

    def _open_selected_source_doc(self) -> None:
        self._sync_open_doc_button()
        row = self._detail_table.currentRow()
        if row < 0:
            show_message_box(self, title="未选择题目", text="请先在表格中选择一行。", icon=QMessageBox.Icon.Warning)
            return
        item = self._detail_table.item(row, 0)
        source_key = str(item.data(Qt.ItemDataRole.UserRole) or "").strip() if item is not None else ""
        if not source_key:
            show_message_box(self, title="无法打开", text="当前行没有可打开的来源文档。", icon=QMessageBox.Icon.Warning)
            return
        self._open_source_doc(source_key)

    def _on_detail_item_double_clicked(self, item: QTableWidgetItem) -> None:
        if item is None:
            return
        if item.column() != 0:
            return
        source_key = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
        if not source_key:
            return
        self._open_source_doc(source_key)

    def _on_manual_question_type_changed(self, source_key: str, number: str, value: str) -> None:
        self._ref_state.set_manual_question_type(source_key, number, value)
        self._render_status()
        self._sync_wizard_buttons()
        self.completeChanged.emit()
        self._render_question_ref_detail_rows_with_view_restore()

    def _on_scan_progress(self, payload: object) -> None:
        if self._discard_run_results:
            return
        action = self._ref_state.handle_scan_progress(payload)
        if action == "start_waiting":
            self._render_question_ref_detail_rows()
            self._wait_timer.start()
            return
        if action == "refresh_waiting":
            self._refresh_waiting_detail_rows()

    def _refresh_waiting_detail_rows(self) -> None:
        if self._discard_run_results:
            return
        if not self._ref_state.waiting_model_specs:
            return
        self._render_question_ref_detail_rows()
        self._ref_state.tick_waiting_feedback()

    def _show_waiting_placeholder(self, paths: list[Path]) -> None:
        if not paths:
            return
        current_path = paths[0]
        self._ref_state.waiting_source_key = str(current_path)
        self._ref_state.waiting_source_name = current_path.name
        self._ref_state.waiting_model_specs = [item for item in question_ref_model_specs() if isinstance(item, dict)]
        self._ref_state.wait_round = 1
        self._ref_state.start_waiting_feedback()
        self._render_question_ref_detail_rows()
        self._wait_timer.start()

    def _clear_partial_results(self) -> None:
        self._wait_timer.stop()
        self._ref_state.reset(source_name=self._ref_state.cur_source_name)
        self._detail_table.setRowCount(0)
        self._detail_row_map = {}
        self._progress.setRange(0, 0)
        self._progress.setValue(0)
        self._progress.setFormat("正在统计资料…")
        self._reset_progress_meta()

    def _capture_detail_table_view_state(self) -> dict[str, object]:
        current_row = self._detail_table.currentRow()
        anchor_item = self._detail_table.item(current_row, 0) if current_row >= 0 else None
        return {
            "vertical_scroll": self._detail_table.verticalScrollBar().value(),
            "horizontal_scroll": self._detail_table.horizontalScrollBar().value(),
            "source_key": str(anchor_item.data(Qt.ItemDataRole.UserRole) or "").strip() if anchor_item is not None else "",
            "number": str(anchor_item.data(Qt.ItemDataRole.UserRole + 1) or "").strip() if anchor_item is not None else "",
        }

    def _restore_detail_table_view_state(self, view_state: dict[str, object]) -> None:
        source_key = str(view_state.get("source_key") or "").strip()
        number = str(view_state.get("number") or "").strip()
        if source_key:
            for row in range(self._detail_table.rowCount()):
                item = self._detail_table.item(row, 0)
                if item is None:
                    continue
                row_source_key = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
                row_number = str(item.data(Qt.ItemDataRole.UserRole + 1) or "").strip()
                if row_source_key == source_key and row_number == number:
                    self._detail_table.setCurrentCell(row, 0)
                    break
        self._detail_table.verticalScrollBar().setValue(int(view_state.get("vertical_scroll") or 0))
        self._detail_table.horizontalScrollBar().setValue(int(view_state.get("horizontal_scroll") or 0))

    def _finish_close_after_stop_if_needed(self) -> None:
        if not self._close_after_stop_requested:
            return
        self._close_after_stop_requested = False
        wizard = self.wizard()
        if isinstance(wizard, QWizard):
            QTimer.singleShot(0, wizard.close)

__all__ = ["AiImportPage"]
