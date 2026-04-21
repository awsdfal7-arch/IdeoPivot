from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtCore import QObject, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

from sj_generator.ai.client import LlmClient
from sj_generator.config import (
    load_deepseek_config,
    load_kimi_config,
    load_qwen_config,
    to_analysis_llm_config,
    to_kimi_llm_config,
    to_llm_config,
    to_qwen_llm_config,
)
from sj_generator.io.batch_ai_import import BatchAiProgress, process_source_files_to_folders
from sj_generator.ui.state import WizardState


def _merge_paths_text(existing_text: str, paths: list[Path]) -> str:
    existing = [p.strip() for p in (existing_text or "").split(";") if p.strip()]
    seen: set[str] = set()
    merged: list[str] = []
    for s in existing:
        if s not in seen:
            merged.append(s)
            seen.add(s)
    for p in paths:
        s = str(p)
        if s not in seen:
            merged.append(s)
            seen.add(s)
    return "; ".join(merged)


class BatchProcessPage(QWizardPage):
    def __init__(self, state: WizardState) -> None:
        super().__init__()
        self._state = state
        self.setTitle("批量处理")
        self.setFinalPage(True)

        self._files_edit = QLineEdit()
        self._files_edit.setReadOnly(True)
        self._files_edit.setPlaceholderText("选择需要 AI 批处理的 docx 资料文件")

        browse_btn = QPushButton("选择文件…")
        browse_btn.clicked.connect(self._browse)

        self._status = QLabel("批量处理会对所选资料文件执行 AI 解析，并直接输出到同名文件夹中的 xlsx 和 Markdown。")
        self._status.setWordWrap(True)
        self._progress = QProgressBar()
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        self._progress_detail = QLabel("待开始")
        self._progress_detail.setWordWrap(True)
        self._recent_log = QLabel("")
        self._recent_log.setWordWrap(True)
        self._processed = False
        self._running = False
        self._thread: QThread | None = None
        self._worker: _BatchProcessWorker | None = None
        self._progress_rows: dict[int, BatchAiProgress] = {}
        self._recent_messages: list[str] = []
        self._files_edit.textChanged.connect(lambda *_: self.completeChanged.emit())

        row = QHBoxLayout()
        row.addWidget(self._files_edit, 1)
        row.addWidget(browse_btn)

        layout = QVBoxLayout()
        layout.addLayout(row)
        layout.addWidget(self._status)
        layout.addWidget(self._progress)
        layout.addWidget(self._progress_detail)
        layout.addWidget(self._recent_log)
        layout.addStretch(1)
        self.setLayout(layout)

    def initializePage(self) -> None:
        if self._state.batch_source_files_text:
            self._files_edit.setText(self._state.batch_source_files_text)
        self._processed = False
        self._running = False
        self._thread = None
        self._worker = None
        self._progress_rows = {}
        self._recent_messages = []
        self._status.setText("批量处理会对所选资料文件执行 AI 解析，并直接输出到同名文件夹中的 xlsx 和 Markdown。")
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        self._progress_detail.setText("待开始")
        self._recent_log.setText("")
        w = self.wizard()
        if isinstance(w, QWizard):
            w.setButtonText(QWizard.WizardButton.FinishButton, "处理并打开文件夹")
            w.setButtonText(QWizard.WizardButton.NextButton, "处理并打开文件夹")
        self.completeChanged.emit()

    def cleanupPage(self) -> None:
        w = self.wizard()
        if isinstance(w, QWizard):
            w.setButtonText(QWizard.WizardButton.NextButton, "下一步")
            w.setButtonText(QWizard.WizardButton.FinishButton, "导出并打开文件夹")

    def nextId(self) -> int:
        return -1

    def isComplete(self) -> bool:
        return (self._processed or bool(self._selected_paths())) and (not self._running)

    def validatePage(self) -> bool:
        if self._processed:
            return True
        if self._running:
            return False
        paths = self._selected_paths()
        if not paths:
            QMessageBox.warning(self, "未选择文件", "请选择至少一个 docx 文件。")
            return False
        deepseek = load_deepseek_config()
        kimi = load_kimi_config()
        qwen = load_qwen_config()
        if not (deepseek.is_ready() and kimi.is_ready() and qwen.is_ready()):
            QMessageBox.warning(self, "配置不足", "批量 AI 处理需要先配置 DeepSeek、Kimi 和 千问。")
            return False
        self._state.batch_source_files = paths
        self._state.batch_source_files_text = self._files_edit.text().strip()
        self._start_batch_process(paths, deepseek, kimi, qwen)
        return False

    def _selected_paths(self) -> list[Path]:
        paths = [Path(p.strip()) for p in self._files_edit.text().split(";") if p.strip()]
        return [p for p in paths if p.exists() and p.suffix.lower() == ".docx"]

    def _browse(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "选择资料文件", "", "Word (*.docx)")
        if files:
            self._files_edit.setText(_merge_paths_text(self._files_edit.text(), [Path(p) for p in files]))

    def _set_status_text(self, text: str) -> None:
        self._status.setText(text)
        self.completeChanged.emit()

    def _on_progress_info(self, payload: object) -> None:
        if not isinstance(payload, BatchAiProgress):
            return
        self._progress_rows[payload.file_index] = payload
        if payload.message:
            self._recent_messages.append(payload.message)
            self._recent_messages = self._recent_messages[-6:]
            self._recent_log.setText("\n".join(self._recent_messages))

        total_files = max((row.total_files for row in self._progress_rows.values()), default=0)
        completed_files = sum(1 for row in self._progress_rows.values() if row.stage == "done")
        question_done = 0
        question_total = 0
        for row in self._progress_rows.values():
            if row.question_total > 0:
                question_total += row.question_total
                question_done += min(row.question_current, row.question_total)
            elif row.stage == "done" and row.question_count > 0:
                question_total += row.question_count
                question_done += row.question_count

        if question_total > 0:
            self._progress.setRange(0, question_total)
            self._progress.setValue(min(question_done, question_total))
            self._status.setText(f"文件进度 {completed_files}/{total_files}，题目进度 {question_done}/{question_total}")
        else:
            self._progress.setRange(0, max(total_files, 1))
            self._progress.setValue(min(completed_files, max(total_files, 1)))
            self._status.setText(f"文件进度 {completed_files}/{total_files}")

        stage_map = {
            "reading": "读取资料",
            "counting": "统计题数",
            "processing": "AI 解析",
            "generating_analysis": "生成解析",
            "saving_xlsx": "写入 xlsx",
            "saving_md": "生成 Markdown",
            "done": "已完成",
        }
        detail = f"当前文件：{payload.file_name}｜阶段：{stage_map.get(payload.stage, payload.stage)}"
        if payload.question_total > 0:
            detail += f"｜单文件题目进度：{payload.question_current}/{payload.question_total}"
        elif payload.question_count > 0:
            detail += f"｜输出题数：{payload.question_count}"
        self._progress_detail.setText(detail)
        self.completeChanged.emit()

    def _start_batch_process(self, paths: list[Path], deepseek, kimi, qwen) -> None:
        self._running = True
        self._processed = False
        self._set_status_text("批量处理：准备开始…")
        w = self.wizard()
        if isinstance(w, QWizard):
            w.setButtonText(QWizard.WizardButton.FinishButton, "处理中…")
            w.setButtonText(QWizard.WizardButton.NextButton, "处理中…")
        thread = QThread(self)
        worker = _BatchProcessWorker(
            paths=paths,
            deepseek_cfg=deepseek,
            kimi_cfg=kimi,
            qwen_cfg=qwen,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._set_status_text)
        worker.progress_info.connect(self._on_progress_info)
        worker.done.connect(self._on_batch_done)
        worker.error.connect(self._on_batch_error)
        worker.done.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._thread = thread
        self._worker = worker
        thread.start()
        self.completeChanged.emit()

    def _on_batch_done(self, results: object) -> None:
        self._running = False
        self._processed = True
        self._thread = None
        self._worker = None
        if isinstance(results, list) and results:
            parent_dirs = [str(item.target_dir.parent) for item in results]
            common = Path(os.path.commonpath(parent_dirs))
            self._state.last_export_dir = common
            self._status.setText(
                f"已处理 {len(results)} 个文件，共生成 {sum(item.question_count for item in results)} 道题的 Markdown。"
            )
            self._progress.setRange(0, max(sum(item.question_count for item in results), 1))
            self._progress.setValue(max(sum(item.question_count for item in results), 1))
            self._progress_detail.setText("全部文件处理完成")
        else:
            self._status.setText("批量处理完成。")
            self._progress_detail.setText("全部文件处理完成")
        w = self.wizard()
        if isinstance(w, QWizard):
            w.setButtonText(QWizard.WizardButton.FinishButton, "打开文件夹")
            w.setButtonText(QWizard.WizardButton.NextButton, "打开文件夹")
        QMessageBox.information(self, "处理完成", "批量处理已完成。")
        self.completeChanged.emit()

    def _on_batch_error(self, msg: str) -> None:
        self._running = False
        self._processed = False
        self._thread = None
        self._worker = None
        self._status.setText("批量处理失败。")
        self._progress_detail.setText("处理已中断")
        w = self.wizard()
        if isinstance(w, QWizard):
            w.setButtonText(QWizard.WizardButton.FinishButton, "处理并打开文件夹")
            w.setButtonText(QWizard.WizardButton.NextButton, "处理并打开文件夹")
        QMessageBox.critical(self, "处理失败", msg)
        self.completeChanged.emit()


class _BatchProcessWorker(QObject):
    progress = pyqtSignal(str)
    progress_info = pyqtSignal(object)
    done = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, *, paths: list[Path], deepseek_cfg, kimi_cfg, qwen_cfg) -> None:
        super().__init__()
        self._paths = paths
        self._deepseek_cfg = deepseek_cfg
        self._kimi_cfg = kimi_cfg
        self._qwen_cfg = qwen_cfg

    def run(self) -> None:
        try:
            results = process_source_files_to_folders(
                paths=self._paths,
                client_factory=lambda: LlmClient(to_llm_config(self._deepseek_cfg)),
                analysis_client_factory=lambda: LlmClient(to_analysis_llm_config(self._deepseek_cfg)),
                kimi_client_factory=lambda: LlmClient(to_kimi_llm_config(self._kimi_cfg)),
                qwen_client_factory=lambda: LlmClient(to_qwen_llm_config(self._qwen_cfg)),
                max_workers=3,
                max_question_workers=2,
                max_analysis_workers=2,
                progress_cb=self.progress.emit,
                progress_info_cb=self.progress_info.emit,
            )
            self.done.emit(results)
        except Exception as e:
            self.error.emit(str(e))
