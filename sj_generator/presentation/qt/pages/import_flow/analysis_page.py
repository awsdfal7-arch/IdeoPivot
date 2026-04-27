import copy
import time
from pathlib import Path

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QProgressBar,
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
from sj_generator.application.state import (
    ImportWizardSession,
    normalize_ai_concurrency,
    normalize_analysis_model_name,
    normalize_analysis_provider,
)
from sj_generator.domain.entities import Question
from sj_generator.infrastructure.llm.client import LlmClient, LlmConfig
from sj_generator.infrastructure.llm.explanations import (
    ExplanationInputs,
    generate_explanation_result,
)
from sj_generator.infrastructure.llm.task_runner import run_tasks_in_parallel
from sj_generator.shared.paths import app_paths
from sj_generator.presentation.qt.constants import PAGE_IMPORT_SUCCESS
from sj_generator.presentation.qt.pages.import_flow.import_db_service import commit_draft_questions_to_db
from sj_generator.presentation.qt.table_copy import CopyableTableWidget

COL_NUMBER = 0
COL_STEM = 1
COL_OPTIONS = 2
COL_ANSWER = 3
COL_CHOICE_SUMMARY = 4
COL_ANALYSIS = 5
COL_ELAPSED = 6
BUTTON_MIN_WIDTH = 96
BUTTON_MIN_HEIGHT = 36


def _style_dialog_button(button: QPushButton | None, text: str | None = None) -> None:
    if button is None:
        return
    if text:
        button.setText(text)
    button.setMinimumSize(BUTTON_MIN_WIDTH, BUTTON_MIN_HEIGHT)


def _style_message_box_buttons(box: QMessageBox) -> None:
    for button_type, text in (
        (QMessageBox.StandardButton.Ok, "确定"),
        (QMessageBox.StandardButton.Cancel, "取消"),
        (QMessageBox.StandardButton.Yes, "是"),
        (QMessageBox.StandardButton.No, "否"),
    ):
        _style_dialog_button(box.button(button_type), text)


def _show_message_box(
    parent,
    *,
    title: str,
    text: str,
    icon: QMessageBox.Icon,
    buttons: QMessageBox.StandardButton = QMessageBox.StandardButton.Ok,
    default_button: QMessageBox.StandardButton = QMessageBox.StandardButton.NoButton,
) -> QMessageBox.StandardButton:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setIcon(icon)
    box.setStandardButtons(buttons)
    if default_button != QMessageBox.StandardButton.NoButton:
        box.setDefaultButton(default_button)
    _style_message_box_buttons(box)
    return QMessageBox.StandardButton(box.exec())


def _analysis_provider_label(provider: str) -> str:
    labels = {"deepseek": "DeepSeek", "kimi": "Kimi", "qwen": "千问"}
    return labels.get(normalize_analysis_provider(provider), "DeepSeek")


def _analysis_target_text(provider: str, model_name: str) -> str:
    return f"{_analysis_provider_label(provider)} / {normalize_analysis_model_name(model_name)}"


def _digits_to_circled(text: str) -> str:
    return "".join(
        {
            "1": "①",
            "2": "②",
            "3": "③",
            "4": "④",
            "5": "⑤",
            "6": "⑥",
            "7": "⑦",
            "8": "⑧",
            "9": "⑨",
        }.get(ch, ch)
        for ch in text
    )


def _format_choice_summary(question: Question) -> str:
    lines = [
        f"{letter}：{_digits_to_circled(value.strip())}"
        for letter, value in (
            ("A", question.choice_1),
            ("B", question.choice_2),
            ("C", question.choice_3),
            ("D", question.choice_4),
        )
        if value.strip()
    ]
    return "\n".join(lines)


class AiAnalysisPage(QWizardPage):
    def __init__(self, state: ImportWizardSession) -> None:
        super().__init__()
        self._state = state
        self.setTitle("AI 生成解析")

        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)
        self._current_label = QLabel("")
        self._current_label.setWordWrap(True)

        self._table = CopyableTableWidget()
        self._table.setColumnCount(7)
        self._table.setHorizontalHeaderLabels(["编号", "题目", "选项", "答案", "组合属性", "解析", "解析用时"])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.setRowCount(0)
        self._table.setColumnHidden(COL_NUMBER, True)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setValue(0)

        self._stop_btn = QPushButton("停止生成")
        self._stop_btn.clicked.connect(self._stop)
        self._stop_btn.setEnabled(False)
        self._stop_btn.hide()

        self._retry_btn = QPushButton("重试")
        self._retry_btn.clicked.connect(self._retry)
        self._retry_btn.setEnabled(False)
        self._retry_btn.hide()

        progress_row = QHBoxLayout()
        progress_row.addWidget(self._progress, 1)

        layout = QVBoxLayout()
        layout.addWidget(self._status_label)
        layout.addWidget(self._current_label)
        layout.addLayout(progress_row)
        layout.addWidget(self._table, 3)
        self.setLayout(layout)
        self._thread: QThread | None = None
        self._worker: _AiAnalysisWorker | None = None
        self._running = False
        self._done = False
        self._discard_run_results = False
        self._close_after_stop_requested = False
        self._tasks: list[tuple[int, str, str]] = []
        self._baseline_questions: list[Question] = []
        self._failed_rows: set[int] = set()
        self._current_task_no = 0
        self._total_task_count = 0
        self._completed_task_count = 0
        self._refresh_status()

    def initializePage(self) -> None:
        self._sync_wizard_buttons()
        self._thread = None
        self._worker = None
        self._running = False
        self._done = False
        self._discard_run_results = False
        self._close_after_stop_requested = False
        self._tasks = []
        self._baseline_questions = copy.deepcopy(list(self._state.draft.questions))
        self._failed_rows = set()
        self._current_task_no = 0
        self._total_task_count = 0
        self._completed_task_count = 0
        self._stop_btn.setEnabled(False)
        self._retry_btn.setEnabled(False)
        self._load_repo()
        self._refresh_status()
        self._prepare_tasks()
        if self._tasks and (not self._done) and (not self._running):
            QTimer.singleShot(0, self._start_generation)

    def nextId(self) -> int:
        return PAGE_IMPORT_SUCCESS

    def _sync_wizard_buttons(self) -> None:
        wizard = self.wizard()
        if not isinstance(wizard, QWizard):
            return
        next_text = "开始生成解析"
        if self._running:
            next_text = "生成中…"
        elif self._done and not self._running:
            next_text = "写入题库"
        wizard.setButtonText(QWizard.WizardButton.BackButton, "返回查重")
        wizard.setButtonText(QWizard.WizardButton.NextButton, next_text)
        wizard.setButtonText(QWizard.WizardButton.CancelButton, "返回开始页")
        self._sync_custom_wizard_button()

    def _sync_custom_wizard_button(self) -> None:
        wizard = self.wizard()
        if not isinstance(wizard, QWizard):
            return
        stop_button = wizard.button(QWizard.WizardButton.CustomButton1)
        retry_button = wizard.button(QWizard.WizardButton.CustomButton2)
        if stop_button is not None:
            stop_button.setText("停止生成")
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

    def isComplete(self) -> bool:
        return self._done and (not self._running)

    def validatePage(self) -> bool:
        if self._running or (not self._done):
            return False
        return commit_draft_questions_to_db(self, self._state)

    def _refresh_status(self) -> None:
        self._stop_btn.setEnabled(self._running)
        self._retry_btn.setEnabled((not self._running) and bool(self._tasks))

    def _load_repo(self) -> None:
        questions = list(self._state.draft.questions)
        self._table.setRowCount(len(questions))
        for row, question in enumerate(questions):
            self._table.setItem(row, COL_NUMBER, QTableWidgetItem(question.number or ""))
            self._table.setItem(row, COL_STEM, QTableWidgetItem(question.stem or ""))
            self._table.setItem(row, COL_OPTIONS, QTableWidgetItem(question.options or ""))
            self._table.setItem(row, COL_ANSWER, QTableWidgetItem(question.answer or ""))
            self._table.setItem(row, COL_CHOICE_SUMMARY, QTableWidgetItem(_format_choice_summary(question)))
            self._table.setItem(row, COL_ANALYSIS, QTableWidgetItem(question.analysis or ""))
            self._table.setItem(row, COL_ELAPSED, QTableWidgetItem(""))

    def _build_inputs_for_row(self, row: int) -> tuple[str, str]:
        stem = self._table.item(row, COL_STEM).text() if self._table.item(row, COL_STEM) else ""
        options = self._table.item(row, COL_OPTIONS).text() if self._table.item(row, COL_OPTIONS) else ""
        answer = self._table.item(row, COL_ANSWER).text() if self._table.item(row, COL_ANSWER) else ""
        choice_summary = (
            self._table.item(row, COL_CHOICE_SUMMARY).text().strip() if self._table.item(row, COL_CHOICE_SUMMARY) else ""
        )
        question_text = stem.strip()
        if options.strip():
            question_text = (question_text + "\n" + options.strip()).strip()
        if choice_summary:
            question_text = (question_text + "\n\n" + choice_summary).strip()
        return question_text, answer.strip()

    def _collect_tasks(self) -> list[tuple[int, str, str]]:
        tasks: list[tuple[int, str, str]] = []
        for row in range(self._table.rowCount()):
            analysis = self._table.item(row, COL_ANALYSIS).text().strip() if self._table.item(row, COL_ANALYSIS) else ""
            if analysis:
                continue
            question_text, answer_text = self._build_inputs_for_row(row)
            if question_text:
                tasks.append((row, question_text, answer_text))
        return tasks

    def _prepare_tasks(self) -> None:
        self._tasks = self._collect_tasks()
        self._total_task_count = len(self._tasks)
        self._current_task_no = 0
        self._completed_task_count = 0
        self._progress.setRange(0, len(self._tasks) if self._tasks else 0)
        self._progress.setValue(0)
        self._sync_wizard_buttons()
        if not self._tasks:
            self._status_label.setText("无需生成解析。")
            self._current_label.setText("")
            self._done = True
            self.completeChanged.emit()
        else:
            self._status_label.setText("进入本页后将自动开始生成解析。")
            self._current_label.setText("")

    def cleanupPage(self) -> None:
        self._sync_wizard_buttons()

    def _start_generation(self) -> None:
        if self._running or self._done:
            return

        provider = normalize_analysis_provider(self._state.analysis_provider)
        provider_label = _analysis_provider_label(provider)
        model_name = normalize_analysis_model_name(self._state.analysis_model_name)
        if provider == "kimi":
            cfg = load_kimi_config()
            llm_config = LlmConfig(
                base_url=cfg.base_url.strip(),
                api_key=cfg.api_key.strip(),
                model=model_name,
                timeout_s=float(cfg.timeout_s),
            )
        elif provider == "qwen":
            cfg = load_qwen_config()
            llm_config = LlmConfig(
                base_url=cfg.base_url.strip(),
                api_key=cfg.api_key.strip(),
                model=model_name,
                timeout_s=float(cfg.timeout_s),
            )
        else:
            cfg = load_deepseek_config()
            llm_config = LlmConfig(
                base_url=cfg.base_url.strip(),
                api_key=cfg.api_key.strip(),
                model=model_name,
                timeout_s=float(cfg.timeout_s),
            )

        if not cfg.is_ready():
            _show_message_box(self, title="未配置", text=f"请先完成 {provider_label} 配置。", icon=QMessageBox.Icon.Warning)
            self._status_label.setText("未配置：无法开始生成解析。")
            self._sync_wizard_buttons()
            self.completeChanged.emit()
            return

        resource_paths = app_paths()
        ref_paths: list[Path] = []
        if self._state.analysis_use_reference_folder:
            ref_dir = resource_paths.reference_resource_dir
            if ref_dir.exists():
                ref_paths = sorted([path for path in ref_dir.glob("*.md")], key=lambda path: path.name)
        tasks = self._tasks
        if not tasks:
            self._done = True
            self.completeChanged.emit()
            return

        if self._thread is not None and self._thread.isRunning():
            return

        self._running = True
        self._discard_run_results = False
        self.completeChanged.emit()
        self._stop_btn.setEnabled(True)
        self._retry_btn.setEnabled(False)
        self._progress.setRange(0, len(tasks))
        self._progress.setValue(0)
        self._status_label.setText(f"批量生成：准备开始…（模型：{_analysis_target_text(provider, model_name)}）")
        self._current_label.setText("")
        self._sync_wizard_buttons()

        thread = QThread(self)
        worker = _AiAnalysisWorker(
            llm_config=llm_config,
            provider_label=provider_label,
            tasks=tasks,
            reference_md_paths=ref_paths,
            include_common_mistakes=self._state.analysis_include_common_mistakes,
            root_dir=resource_paths.base_dir,
            max_workers=normalize_ai_concurrency(self._state.analysis_generation_concurrency),
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.processing.connect(self._on_batch_processing)
        worker.progress.connect(self._on_batch_progress)
        worker.row_done.connect(self._on_batch_row_done)
        worker.row_failed.connect(self._on_batch_row_failed)
        worker.done.connect(self._on_batch_done)
        worker.error.connect(self._on_batch_error)
        worker.done.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._thread = thread
        self._worker = worker
        thread.start()

    def _stop(self) -> None:
        if self._worker is None:
            return
        self._worker.request_stop()
        self._discard_run_results = True
        self._stop_btn.setEnabled(False)
        self._status_label.setText("正在停止…")
        self._current_label.setText("")
        self._restore_baseline_questions()
        self._tasks = self._collect_tasks()
        self._refresh_status()
        self._sync_wizard_buttons()

    def prepare_to_close(self) -> bool:
        thread = self._thread
        if thread is None or (not thread.isRunning()):
            return True
        if self._worker is not None:
            self._worker.request_stop()
        self._discard_run_results = True
        self._close_after_stop_requested = True
        self._stop_btn.setEnabled(False)
        self._retry_btn.setEnabled(False)
        self._status_label.setText("正在停止，收尾完成后将自动退出…")
        self._current_label.setText("")
        self._restore_baseline_questions()
        self._tasks = self._collect_tasks()
        self._refresh_status()
        self._sync_wizard_buttons()
        return False

    def _on_batch_progress(self, current: int, total: int) -> None:
        if self._discard_run_results:
            return
        self._progress.setRange(0, total)
        self._progress.setValue(max(0, min(current, total)))
        self._completed_task_count = current
        self._status_label.setText(self._build_running_status())

    def _on_batch_processing(self, current: int, total: int) -> None:
        if self._discard_run_results:
            return
        self._current_task_no = current
        self._total_task_count = total
        self._status_label.setText(self._build_running_status())
        workers = normalize_ai_concurrency(self._state.analysis_generation_concurrency)
        target_text = _analysis_target_text(self._state.analysis_provider, self._state.analysis_model_name)
        self._current_label.setText(f"选择题 {current}/{total} 题已发起解析（模型：{target_text}，并发 {workers} 路）")

    def _on_batch_row_done(self, row: int, answer_text: str, text: str, elapsed_s: float) -> None:
        if self._discard_run_results:
            return
        existing = self._table.item(row, COL_ANALYSIS).text().strip() if self._table.item(row, COL_ANALYSIS) else ""
        if existing:
            return
        if row in self._failed_rows:
            self._failed_rows.remove(row)
        if answer_text:
            self._table.setItem(row, COL_ANSWER, QTableWidgetItem(answer_text))
        self._table.setItem(row, COL_ANALYSIS, QTableWidgetItem(text))
        self._table.setItem(row, COL_ELAPSED, QTableWidgetItem(f"{elapsed_s:.1f}s"))

    def _on_batch_row_failed(self, row: int, msg: str) -> None:
        if self._discard_run_results:
            return
        self._failed_rows.add(row)
        row_no = row + 1
        self._status_label.setText(f"第 {row_no} 行生成失败：{msg}")
        self._current_label.setText(f"第 {row_no} 行处理失败")

    def _on_batch_done(self, stopped: bool) -> None:
        if self._discard_run_results or stopped:
            self._restore_baseline_questions()
            self._tasks = self._collect_tasks()
            self._current_task_no = 0
            self._completed_task_count = 0
            self._total_task_count = len(self._tasks)
            self._progress.setRange(0, len(self._tasks) if self._tasks else 0)
            self._progress.setValue(0)
            self._running = False
            self._done = False
            self._thread = None
            self._worker = None
            self._current_label.setText("")
            self._status_label.setText("已停止生成，本轮结果已丢弃，请点击重试重新生成。")
            self._refresh_status()
            self._sync_wizard_buttons()
            self.completeChanged.emit()
            self._finish_close_after_stop_if_needed()
            return
        self._status_label.setText("批量生成：写回当前草稿…")
        self._current_label.setText("")
        questions: list[Question] = []
        for row in range(self._table.rowCount()):
            original = self._state.draft.questions[row] if row < len(self._state.draft.questions) else None
            number = self._table.item(row, COL_NUMBER).text().strip() if self._table.item(row, COL_NUMBER) else ""
            stem = self._table.item(row, COL_STEM).text().strip() if self._table.item(row, COL_STEM) else ""
            options = self._table.item(row, COL_OPTIONS).text().strip() if self._table.item(row, COL_OPTIONS) else ""
            answer = self._table.item(row, COL_ANSWER).text().strip() if self._table.item(row, COL_ANSWER) else ""
            analysis = self._table.item(row, COL_ANALYSIS).text().strip() if self._table.item(row, COL_ANALYSIS) else ""
            if not any([number, stem, options, answer, analysis]):
                continue
            questions.append(
                Question(
                    number=number,
                    stem=stem,
                    options=options,
                    answer=answer,
                    analysis=analysis,
                    question_type=original.question_type if original is not None else "",
                    choice_1=original.choice_1 if original is not None else "",
                    choice_2=original.choice_2 if original is not None else "",
                    choice_3=original.choice_3 if original is not None else "",
                    choice_4=original.choice_4 if original is not None else "",
                )
            )

        self._state.apply_draft_questions(questions)

        self._progress.setValue(self._progress.maximum())
        self._tasks = self._collect_tasks()
        self._current_task_no = 0
        self._completed_task_count = 0
        self._total_task_count = len(self._tasks)
        pending = len(self._tasks)
        failed = len(self._failed_rows)
        if pending > 0:
            self._status_label.setText(
                f"已停止生成（剩余 {pending} 题可重试，失败 {failed} 题）。"
                if stopped
                else f"批量生成完成（剩余 {pending} 题可重试，失败 {failed} 题）。"
            )
        else:
            self._status_label.setText(
                (f"已停止生成（失败 {failed} 题）。" if stopped else f"批量生成完成（失败 {failed} 题）。")
                if failed > 0
                else ("已停止生成。" if stopped else "批量生成完成。")
            )
        self._running = False
        self._done = True
        self._thread = None
        self._worker = None
        self._current_label.setText("")
        self._refresh_status()
        self._sync_wizard_buttons()
        self.completeChanged.emit()

    def _on_batch_error(self, msg: str) -> None:
        if self._discard_run_results:
            self._restore_baseline_questions()
            self._tasks = self._collect_tasks()
            self._current_task_no = 0
            self._completed_task_count = 0
            self._total_task_count = len(self._tasks)
            self._running = False
            self._done = False
            self._thread = None
            self._worker = None
            self._status_label.setText("已停止生成，本轮结果已丢弃，请点击重试重新生成。")
            self._current_label.setText("")
            self._refresh_status()
            self._sync_wizard_buttons()
            self.completeChanged.emit()
            self._finish_close_after_stop_if_needed()
            return
        _show_message_box(self, title="生成失败", text=msg, icon=QMessageBox.Icon.Critical)
        self._status_label.setText("生成失败。")
        self._current_label.setText("")
        self._running = False
        self._done = False
        self._thread = None
        self._worker = None
        self._tasks = self._collect_tasks()
        self._current_task_no = 0
        self._completed_task_count = 0
        self._total_task_count = len(self._tasks)
        self._refresh_status()
        self._sync_wizard_buttons()
        self.completeChanged.emit()

    def _retry(self) -> None:
        if self._running:
            return
        self._discard_run_results = False
        self._close_after_stop_requested = False
        self._restore_baseline_questions()
        self._tasks = self._collect_tasks()
        if self._tasks:
            self._total_task_count = len(self._tasks)
            self._current_task_no = 0
            self._completed_task_count = 0
            self._progress.setRange(0, len(self._tasks))
            self._progress.setValue(0)
            self._done = False
            self._refresh_status()
            self._status_label.setText("准备重试生成解析…")
            self._current_label.setText("")
            QTimer.singleShot(0, self._start_generation)

    def _restore_baseline_questions(self) -> None:
        questions = copy.deepcopy(self._baseline_questions)
        self._state.apply_draft_questions(questions)
        self._failed_rows = set()
        self._load_repo()

    def _build_running_status(self) -> str:
        total = self._total_task_count
        current = self._current_task_no
        completed = self._completed_task_count
        workers = normalize_ai_concurrency(self._state.analysis_generation_concurrency)
        target_text = _analysis_target_text(self._state.analysis_provider, self._state.analysis_model_name)
        if total > 0 and current > 0:
            return f"批量生成：模型 {target_text}，并发 {workers} 路，已发起 {current}/{total}，已完成 {completed}/{total}"
        if total > 0:
            return f"批量生成：模型 {target_text}，并发 {workers} 路，已完成 {completed}/{total}"
        return "批量生成中…"

    def _finish_close_after_stop_if_needed(self) -> None:
        if not self._close_after_stop_requested:
            return
        self._close_after_stop_requested = False
        wizard = self.wizard()
        if isinstance(wizard, QWizard):
            QTimer.singleShot(0, wizard.close)


class _AiAnalysisWorker(QObject):
    processing = pyqtSignal(int, int)
    progress = pyqtSignal(int, int)
    row_done = pyqtSignal(int, str, str, float)
    row_failed = pyqtSignal(int, str)
    done = pyqtSignal(bool)
    error = pyqtSignal(str)

    def __init__(
        self,
        *,
        llm_config,
        provider_label: str,
        tasks: list[tuple[int, str, str]],
        reference_md_paths: list[Path],
        include_common_mistakes: bool,
        root_dir: Path,
        max_workers: int,
    ) -> None:
        super().__init__()
        self._llm_config = llm_config
        self._provider_label = provider_label
        self._tasks = tasks
        self._reference_md_paths = reference_md_paths
        self._include_common_mistakes = include_common_mistakes
        self._root_dir = root_dir
        self._max_workers = normalize_ai_concurrency(max_workers)
        self._stop = False

    def request_stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        try:
            total = len(self._tasks)
            done_count = 0

            def run_one(task: tuple[int, str, str]) -> tuple[str, str, float]:
                _, question_text, answer_text = task
                client = LlmClient(self._llm_config)
                started_at = time.perf_counter()
                inp = ExplanationInputs(
                    question_text=question_text,
                    answer_text=answer_text,
                    reference_md_paths=self._reference_md_paths,
                    include_common_mistakes=self._include_common_mistakes,
                    root_dir=self._root_dir,
                )
                result = generate_explanation_result(client, inp)
                elapsed_s = time.perf_counter() - started_at
                return result.answer_text, result.analysis_text, elapsed_s

            def on_task_start(current: int, total_count: int, task: tuple[int, str, str]) -> None:
                self.processing.emit(current, total_count)

            def on_task_done(task: tuple[int, str, str], result: tuple[str, str, float]) -> None:
                nonlocal done_count
                row, _, _ = task
                answer_text, text, elapsed_s = result
                self.row_done.emit(row, answer_text, text, elapsed_s)
                done_count += 1
                self.progress.emit(done_count, total)

            def on_task_failed(task: tuple[int, str, str], exc: Exception) -> None:
                nonlocal done_count
                row, _, _ = task
                self.row_failed.emit(row, str(exc))
                done_count += 1
                self.progress.emit(done_count, total)

            run_tasks_in_parallel(
                tasks=self._tasks,
                max_workers=self._max_workers,
                stop_cb=self._should_stop,
                on_task_start=on_task_start,
                on_task_done=on_task_done,
                on_task_failed=on_task_failed,
                run_one=run_one,
            )
            self.done.emit(self._stop)
        except Exception as exc:
            self.error.emit(str(exc))

    def _should_stop(self) -> bool:
        return self._stop

__all__ = ["AiAnalysisPage"]
