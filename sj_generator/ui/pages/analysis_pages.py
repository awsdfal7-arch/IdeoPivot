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
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

from sj_generator.ai.client import LlmClient, LlmConfig
from sj_generator.ai.explanations import ExplanationInputs, generate_explanation
from sj_generator.ai.task_runner import run_tasks_in_parallel
from sj_generator.config import (
    load_deepseek_config,
    load_kimi_config,
    load_qwen_config,
    to_analysis_llm_config,
    to_kimi_llm_config,
    to_qwen_llm_config,
)
from sj_generator.io.draft_db_import import import_draft_questions_to_db
from sj_generator.models import Question
from sj_generator.paths import app_paths, common_mistakes_md_path
from sj_generator.ui.state import (
    WizardState,
    library_db_path_from_repo_parent_dir_text,
    normalize_ai_concurrency,
    normalize_analysis_model_name,
    normalize_analysis_provider,
)
from sj_generator.ui.constants import PAGE_AI_ANALYSIS, PAGE_IMPORT_SUCCESS

COL_NUMBER = 0
COL_STEM = 1
COL_OPTIONS = 2
COL_ANSWER = 3
COL_CHOICE_SUMMARY = 4
COL_ANALYSIS = 5
COL_ELAPSED = 6


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


def _commit_draft_questions_to_db(page: QWizardPage, state: WizardState) -> bool:
    if state.db_import_completed:
        return True

    questions = list(state.draft_questions)
    if not questions:
        QMessageBox.warning(page, "无法导入数据库", "当前草稿为空，无法写入数据库。")
        return False

    level_path = state.ai_import_level_path.strip()
    if not level_path:
        QMessageBox.warning(page, "无法导入数据库", "未填写层级归属，无法写入数据库。")
        return False

    try:
        count = import_draft_questions_to_db(
            db_path=library_db_path_from_repo_parent_dir_text(state.default_repo_parent_dir_text),
            questions=questions,
            level_path=level_path,
            source_files=state.ai_source_files or [],
        )
    except Exception as e:
        state.db_import_error = str(e)
        QMessageBox.critical(page, "导入数据库失败", str(e))
        return False

    state.mark_db_import_completed(count)
    return True


class AiAnalysisPage(QWizardPage):
    def __init__(self, state: WizardState) -> None:
        super().__init__()
        self._state = state
        self.setTitle("AI 生成解析")

        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)
        self._current_label = QLabel("")
        self._current_label.setWordWrap(True)

        self._table = QTableWidget()
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

        self._retry_btn = QPushButton("重试")
        self._retry_btn.clicked.connect(self._retry)
        self._retry_btn.setEnabled(False)

        progress_row = QHBoxLayout()
        progress_row.addWidget(self._progress, 1)
        progress_row.addWidget(self._stop_btn)
        progress_row.addWidget(self._retry_btn)

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
        self._tasks: list[tuple[int, str, str]] = []
        self._failed_rows: set[int] = set()
        self._current_task_no = 0
        self._total_task_count = 0
        self._completed_task_count = 0
        self._refresh_status()

    def initializePage(self) -> None:
        self._thread = None
        self._worker = None
        self._running = False
        self._done = False
        self._tasks = []
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

    def isComplete(self) -> bool:
        return self._done and (not self._running)

    def validatePage(self) -> bool:
        if self._running or (not self._done):
            return False
        return _commit_draft_questions_to_db(self, self._state)

    def _refresh_status(self) -> None:
        self._stop_btn.setEnabled(self._running)
        self._retry_btn.setEnabled((not self._running) and bool(self._tasks))

    def _load_repo(self) -> None:
        questions = list(self._state.draft_questions)
        self._table.setRowCount(len(questions))
        for r, q in enumerate(questions):
            self._table.setItem(r, COL_NUMBER, QTableWidgetItem(q.number or ""))
            self._table.setItem(r, COL_STEM, QTableWidgetItem(q.stem or ""))
            self._table.setItem(r, COL_OPTIONS, QTableWidgetItem(q.options or ""))
            self._table.setItem(r, COL_ANSWER, QTableWidgetItem(q.answer or ""))
            self._table.setItem(r, COL_CHOICE_SUMMARY, QTableWidgetItem(_format_choice_summary(q)))
            self._table.setItem(r, COL_ANALYSIS, QTableWidgetItem(q.analysis or ""))
            self._table.setItem(r, COL_ELAPSED, QTableWidgetItem(""))

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
        for r in range(self._table.rowCount()):
            analysis = self._table.item(r, COL_ANALYSIS).text().strip() if self._table.item(r, COL_ANALYSIS) else ""
            if analysis:
                continue
            qtext, atext = self._build_inputs_for_row(r)
            if qtext and atext:
                tasks.append((r, qtext, atext))
        return tasks

    def _prepare_tasks(self) -> None:
        self._tasks = self._collect_tasks()
        self._total_task_count = len(self._tasks)
        self._current_task_no = 0
        self._completed_task_count = 0
        self._progress.setRange(0, len(self._tasks) if self._tasks else 0)
        self._progress.setValue(0)
        w = self.wizard()
        if isinstance(w, QWizard):
            w.setButtonText(QWizard.WizardButton.NextButton, "下一步")
        if not self._tasks:
            self._status_label.setText("无需生成解析。")
            self._current_label.setText("")
            self._done = True
            self.completeChanged.emit()
        else:
            self._status_label.setText("进入本页后将自动开始生成解析。")
            self._current_label.setText("")

    def cleanupPage(self) -> None:
        w = self.wizard()
        if isinstance(w, QWizard):
            w.setButtonText(QWizard.WizardButton.NextButton, "下一步")

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
            QMessageBox.warning(self, "未配置", f"请先完成 {provider_label} 配置。")
            self._status_label.setText("未配置：无法开始生成解析。")
            w = self.wizard()
            if isinstance(w, QWizard):
                w.setButtonText(QWizard.WizardButton.NextButton, "下一步")
            self.completeChanged.emit()
            return

        root_dir = Path(__file__).resolve().parents[3]
        ref_paths: list[Path] = []
        if self._state.analysis_use_reference_folder:
            ref_dir = app_paths(root_dir).reference_resource_dir
            if ref_dir.exists():
                ref_paths = sorted([p for p in ref_dir.glob("*.md")], key=lambda p: p.name)
        tasks = self._tasks
        if not tasks:
            self._done = True
            self.completeChanged.emit()
            return

        if self._thread is not None and self._thread.isRunning():
            return

        self._running = True
        self.completeChanged.emit()
        self._stop_btn.setEnabled(True)
        self._retry_btn.setEnabled(False)
        self._progress.setRange(0, len(tasks))
        self._progress.setValue(0)
        self._status_label.setText(f"批量生成：准备开始…（模型：{_analysis_target_text(provider, model_name)}）")
        self._current_label.setText("")
        w = self.wizard()
        if isinstance(w, QWizard):
            w.setButtonText(QWizard.WizardButton.NextButton, "生成中…")

        thread = QThread(self)
        worker = _AiAnalysisWorker(
            llm_config=llm_config,
            provider_label=provider_label,
            tasks=tasks,
            reference_md_paths=ref_paths,
            include_common_mistakes=self._state.analysis_include_common_mistakes,
            root_dir=root_dir,
            max_workers=normalize_ai_concurrency(self._state.ai_concurrency),
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
        self._stop_btn.setEnabled(False)
        self._status_label.setText("正在停止…")
        self._current_label.setText("")

    def prepare_to_close(self) -> bool:
        thread = self._thread
        if thread is None or (not thread.isRunning()):
            return True
        if self._worker is not None:
            self._worker.request_stop()
        self._stop_btn.setEnabled(False)
        self._status_label.setText("正在停止…")
        self._current_label.setText("")
        QMessageBox.information(self, "正在停止", "当前解析线程仍在收尾，请稍候片刻后再关闭窗口。")
        return False

    def _on_batch_progress(self, cur: int, total: int) -> None:
        self._progress.setRange(0, total)
        self._progress.setValue(max(0, min(cur, total)))
        self._completed_task_count = cur
        self._status_label.setText(self._build_running_status())

    def _on_batch_processing(self, current: int, total: int) -> None:
        self._current_task_no = current
        self._total_task_count = total
        self._status_label.setText(self._build_running_status())
        workers = normalize_ai_concurrency(self._state.ai_concurrency)
        target_text = _analysis_target_text(self._state.analysis_provider, self._state.analysis_model_name)
        self._current_label.setText(f"选择题 {current}/{total} 题已发起解析（模型：{target_text}，并发 {workers} 路）")

    def _on_batch_row_done(self, row: int, text: str, elapsed_s: float) -> None:
        existing = (
            self._table.item(row, COL_ANALYSIS).text().strip() if self._table.item(row, COL_ANALYSIS) else ""
        )
        if existing:
            return
        if row in self._failed_rows:
            self._failed_rows.remove(row)
        self._table.setItem(row, COL_ANALYSIS, QTableWidgetItem(text))
        self._table.setItem(row, COL_ELAPSED, QTableWidgetItem(f"{elapsed_s:.1f}s"))

    def _on_batch_row_failed(self, row: int, msg: str) -> None:
        self._failed_rows.add(row)
        row_no = row + 1
        self._status_label.setText(f"第 {row_no} 行生成失败：{msg}")
        self._current_label.setText(f"第 {row_no} 行处理失败")

    def _on_batch_done(self, stopped: bool) -> None:
        self._status_label.setText("批量生成：写回当前草稿…")
        self._current_label.setText("")
        questions: list[Question] = []
        for r in range(self._table.rowCount()):
            original = self._state.draft_questions[r] if r < len(self._state.draft_questions) else None
            number = self._table.item(r, COL_NUMBER).text().strip() if self._table.item(r, COL_NUMBER) else ""
            stem = self._table.item(r, COL_STEM).text().strip() if self._table.item(r, COL_STEM) else ""
            options = self._table.item(r, COL_OPTIONS).text().strip() if self._table.item(r, COL_OPTIONS) else ""
            answer = self._table.item(r, COL_ANSWER).text().strip() if self._table.item(r, COL_ANSWER) else ""
            analysis = (
                self._table.item(r, COL_ANALYSIS).text().strip() if self._table.item(r, COL_ANALYSIS) else ""
            )
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

        self._state.draft_questions = questions
        self._state.reset_db_import()

        self._progress.setValue(self._progress.maximum())
        self._tasks = self._collect_tasks()
        self._current_task_no = 0
        self._completed_task_count = 0
        self._total_task_count = len(self._tasks)
        pending = len(self._tasks)
        failed = len(self._failed_rows)
        if pending > 0:
            self._status_label.setText(
                (
                    f"已停止生成（剩余 {pending} 题可重试，失败 {failed} 题）。"
                    if stopped
                    else f"批量生成完成（剩余 {pending} 题可重试，失败 {failed} 题）。"
                )
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
        w = self.wizard()
        if isinstance(w, QWizard):
            w.setButtonText(QWizard.WizardButton.NextButton, "下一步")
        self.completeChanged.emit()

    def _on_batch_error(self, msg: str) -> None:
        QMessageBox.critical(self, "生成失败", msg)
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
        w = self.wizard()
        if isinstance(w, QWizard):
            w.setButtonText(QWizard.WizardButton.NextButton, "下一步")
        self.completeChanged.emit()

    def _retry(self) -> None:
        if self._running:
            return
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

    def _build_running_status(self) -> str:
        total = self._total_task_count
        current = self._current_task_no
        completed = self._completed_task_count
        workers = normalize_ai_concurrency(self._state.ai_concurrency)
        target_text = _analysis_target_text(self._state.analysis_provider, self._state.analysis_model_name)
        if total > 0 and current > 0:
            return f"批量生成：模型 {target_text}，并发 {workers} 路，已发起 {current}/{total}，已完成 {completed}/{total}"
        if total > 0:
            return f"批量生成：模型 {target_text}，并发 {workers} 路，已完成 {completed}/{total}"
        return "批量生成中…"


class _AiAnalysisWorker(QObject):
    processing = pyqtSignal(int, int)
    progress = pyqtSignal(int, int)
    row_done = pyqtSignal(int, str, float)
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
            
            def run_one(task: tuple[int, str, str]) -> tuple[str, float]:
                _, qtext, atext = task
                client = LlmClient(self._llm_config)
                started_at = time.perf_counter()
                inp = ExplanationInputs(
                    question_text=qtext,
                    answer_text=atext,
                    reference_md_paths=self._reference_md_paths,
                    include_common_mistakes=self._include_common_mistakes,
                    root_dir=self._root_dir,
                )
                text = generate_explanation(client, inp)
                elapsed_s = time.perf_counter() - started_at
                return text, elapsed_s

            def on_task_start(current: int, total_count: int, task: tuple[int, str, str]) -> None:
                self.processing.emit(current, total_count)

            def on_task_done(task: tuple[int, str, str], result: tuple[str, float]) -> None:
                nonlocal done_count
                row, _, _ = task
                text, elapsed_s = result
                self.row_done.emit(row, text, elapsed_s)
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
        except Exception as e:
            self.error.emit(str(e))

    def _should_stop(self) -> bool:
        return self._stop
