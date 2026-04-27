import re
from pathlib import Path

from PyQt6.QtCore import QObject, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QMessageBox,
    QSplitter,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

from sj_generator.application.dedupe.service import (
    DedupeHit,
    dedupe_between_questions_and_db,
)
from sj_generator.application.state import (
    ImportWizardSession,
    library_db_path_from_repo_parent_dir_text,
)
from sj_generator.domain.entities import Question
from sj_generator.infrastructure.persistence.sqlite_repo import (
    DbQuestionRecord,
    load_all_questions,
)
from sj_generator.presentation.qt.constants import PAGE_AI_ANALYSIS, PAGE_IMPORT_SUCCESS
from sj_generator.presentation.qt.pages.import_flow.import_db_service import commit_draft_questions_to_db
from sj_generator.presentation.qt.table_copy import CopyableTableWidget

BUTTON_MIN_WIDTH = 96
BUTTON_MIN_HEIGHT = 36


def _style_dialog_button(button, text: str | None = None) -> None:
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


def _format_db_question_options(record: DbQuestionRecord) -> str:
    option_texts = [record.option_1, record.option_2, record.option_3, record.option_4]
    if record.question_type == "可转多选":
        lines = [
            f"{marker}. {text.strip()}".rstrip()
            for marker, text in zip(["①", "②", "③", "④"], option_texts)
            if text.strip()
        ]
        for letter, digits in (
            ("A", record.choice_1),
            ("B", record.choice_2),
            ("C", record.choice_3),
            ("D", record.choice_4),
        ):
            digits = (digits or "").strip()
            if not digits:
                continue
            lines.append(f"{letter}. {_digits_to_circled(digits)}")
        return "\n".join(lines)
    if record.question_type == "多选":
        markers = ["①", "②", "③", "④"]
    else:
        markers = ["A", "B", "C", "D"]
    return "\n".join(
        f"{marker}. {text.strip()}".rstrip()
        for marker, text in zip(markers, option_texts)
        if text.strip()
    )


def _format_db_question_answer(record: DbQuestionRecord) -> str:
    answer = (record.answer or "").strip()
    if record.question_type == "可转多选" and any(
        value.strip() for value in (record.choice_1, record.choice_2, record.choice_3, record.choice_4)
    ):
        return answer
    if record.question_type not in {"多选", "可转多选"}:
        return answer
    return _digits_to_circled(answer.replace(",", ""))


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


class DedupeResultPage(QWizardPage):
    def __init__(self, state: ImportWizardSession) -> None:
        super().__init__()
        self._state = state
        self.setTitle("库内查重（结果）")

        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)

        self._table = CopyableTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(["当前题目", "当前序号", "库内来源", "所属层级", "相似度"])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.setRowCount(0)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.cellDoubleClicked.connect(self._open_detail)

        hint = QLabel("双击行可查看当前题目与库内题目的题干、选项与答案。")
        hint.setWordWrap(True)

        layout = QVBoxLayout()
        layout.addWidget(self._status_label)
        layout.addWidget(self._table, 1)
        layout.addWidget(hint)
        self.setLayout(layout)

        self._thread: QThread | None = None
        self._worker: _DedupeWorker | None = None
        self._running = False
        self._done = False
        self._hits: list[DedupeHit] = []
        self._questions_cache: dict[Path, list[Question]] = {}
        self._current_left_source_path = self._resolve_left_source_path()

    def initializePage(self) -> None:
        self._sync_wizard_buttons()
        self._current_left_source_path = self._resolve_left_source_path()
        if self._state.draft.dedupe_hits is not None:
            self._hits = self._state.draft.dedupe_hits
            self._render_hits(self._hits)
            self._running = False
            self._done = True
            self._sync_wizard_buttons()
            self.completeChanged.emit()
            return

        self._hits = []
        self._table.setRowCount(0)
        self._status_label.setText("正在查重…")
        self._running = True
        self._done = False
        self.completeChanged.emit()

        repo = self._current_left_source_path
        left_questions = list(self._state.draft.questions)
        threshold = self._state.dedupe_threshold
        if not left_questions:
            self._on_error("当前题库草稿为空，无法执行查重。")
            return
        db_path = self._library_db_path()
        if not db_path.exists():
            self._on_error(f"当前总库不存在：{db_path}")
            return

        thread = QThread(self)
        worker = _DedupeWorker(left_repo=repo, left_questions=left_questions, db_path=db_path, threshold=threshold)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_done)
        worker.error.connect(self._on_error)
        worker.done.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._thread = thread
        self._worker = worker
        thread.start()

    def isComplete(self) -> bool:
        return self._done and (not self._running)

    def validatePage(self) -> bool:
        if not self._state.analysis_enabled:
            return commit_draft_questions_to_db(self, self._state)
        return True

    def nextId(self) -> int:
        if self._state.analysis_enabled:
            return PAGE_AI_ANALYSIS
        return PAGE_IMPORT_SUCCESS

    def _sync_wizard_buttons(self) -> None:
        wizard = self.wizard()
        if not isinstance(wizard, QWizard):
            return
        next_text = "查重中…"
        if self._done and not self._running:
            next_text = "进入解析" if self._state.analysis_enabled else "写入题库"
        wizard.setButtonText(QWizard.WizardButton.BackButton, "返回解析")
        wizard.setButtonText(QWizard.WizardButton.NextButton, next_text)
        wizard.setButtonText(QWizard.WizardButton.CancelButton, "返回开始页")

    def _render_hits(self, hits: list[DedupeHit]) -> None:
        self._table.setRowCount(len(hits))
        for row, hit in enumerate(hits):
            self._table.setItem(row, 0, QTableWidgetItem(hit.left_stem.strip()[:40]))
            self._table.setItem(row, 1, QTableWidgetItem(hit.left_number or ""))
            self._table.setItem(row, 2, QTableWidgetItem(hit.right_file.name))
            self._table.setItem(row, 3, QTableWidgetItem(hit.right_level_path or ""))
            self._table.setItem(row, 4, QTableWidgetItem(f"{hit.similarity:.3f}"))

    def _on_done(self, hits: list[DedupeHit]) -> None:
        self._running = False
        self._done = True
        self._thread = None
        self._worker = None

        self._hits = hits
        self._state.set_dedupe_hits(hits)
        if not hits:
            self._status_label.setText("未发现达到阈值的重复题。")
            self._table.setRowCount(0)
        else:
            self._render_hits(hits)
            self._status_label.setText(f"库内查重完成：{len(hits)} 条结果（双击查看详情）")
        self._sync_wizard_buttons()
        self.completeChanged.emit()

    def _on_error(self, msg: str) -> None:
        self._running = False
        self._done = False
        self._thread = None
        self._worker = None
        _show_message_box(self, title="查重失败", text=msg, icon=QMessageBox.Icon.Critical)
        self._status_label.setText("查重失败。")
        self._sync_wizard_buttons()
        self.completeChanged.emit()

    def _open_detail(self, row: int, _col: int) -> None:
        if row < 0 or row >= len(self._hits):
            return
        hit = self._hits[row]
        dialog = _DedupeDetailDialog(self, hit=hit, loader=self._load_questions_cached)
        dialog.exec()

    def _resolve_left_source_path(self) -> Path:
        if self._state.repo_path is not None:
            return self._state.repo_path
        if self._state.project_dir is not None:
            return self._state.project_dir / "当前草稿.xlsx"
        return self._library_db_path().parent / "当前草稿.xlsx"

    def _load_questions_cached(self, path: Path) -> list[Question]:
        resolved_path = path.resolve()
        if resolved_path in self._questions_cache:
            return self._questions_cache[resolved_path]
        if resolved_path == self._current_left_source_path.resolve():
            questions = list(self._state.draft.questions)
        else:
            if resolved_path == self._library_db_path().resolve():
                records = load_all_questions(resolved_path)
                questions = [
                    Question(
                        number=record.id,
                        stem=record.stem,
                        options=_format_db_question_options(record),
                        answer=_format_db_question_answer(record),
                        analysis=record.analysis,
                        question_type=record.question_type,
                        choice_1=record.choice_1,
                        choice_2=record.choice_2,
                        choice_3=record.choice_3,
                        choice_4=record.choice_4,
                    )
                    for record in records
                ]
            else:
                from sj_generator.infrastructure.persistence.excel_repo import load_questions

                questions = load_questions(resolved_path)
        self._questions_cache[resolved_path] = questions
        return questions

    def _library_db_path(self) -> Path:
        return library_db_path_from_repo_parent_dir_text(self._state.default_repo_parent_dir_text)


class _DedupeWorker(QObject):
    done = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, *, left_repo: Path, left_questions: list[Question], db_path: Path, threshold: float) -> None:
        super().__init__()
        self._left_repo = left_repo
        self._left_questions = left_questions
        self._db_path = db_path
        self._threshold = threshold

    def run(self) -> None:
        try:
            hits = dedupe_between_questions_and_db(
                left_questions=self._left_questions,
                left_file=self._left_repo,
                db_path=self._db_path,
                threshold=self._threshold,
            )
            self.done.emit(hits)
        except Exception as exc:
            self.error.emit(str(exc))


class _DedupeDetailDialog(QDialog):
    def __init__(self, parent, *, hit, loader) -> None:
        super().__init__(parent)
        self.setWindowTitle("查重详情")

        left = QTextEdit()
        left.setReadOnly(True)
        right = QTextEdit()
        right.setReadOnly(True)

        splitter = QSplitter()
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        _style_dialog_button(buttons.button(QDialogButtonBox.StandardButton.Ok), "确定")

        layout = QVBoxLayout()
        layout.addWidget(QLabel(f"相似度：{hit.similarity:.3f}"))
        layout.addWidget(splitter)
        layout.addWidget(buttons)
        self.setLayout(layout)

        left_question = _find_question(loader(hit.left_file), hit.left_number, hit.left_stem)
        right_question = _find_question(loader(hit.right_file), hit.right_number, hit.right_stem)
        left.setPlainText(_format_question_block(hit.left_file, left_question, fallback_stem=hit.left_stem))
        right.setPlainText(_format_question_block(hit.right_file, right_question, fallback_stem=hit.right_stem))


def _format_question_block(path: Path, question: Question | None, *, fallback_stem: str) -> str:
    if question is None:
        return "\n".join(
            [
                f"文件：{path.name}",
                "编号：",
                "",
                "题干：",
                (fallback_stem or "").strip(),
            ]
        ).strip() + "\n"
    return "\n".join(
        [
            f"文件：{path.name}",
            f"编号：{(question.number or '').strip()}",
            "",
            "题干：",
            (question.stem or "").strip(),
            "",
            "选项：",
            (question.options or "").strip(),
            "",
            "答案：",
            (question.answer or "").strip(),
        ]
    ).strip() + "\n"


def _find_question(questions: list[Question], number: str, stem: str) -> Question | None:
    normalized_number = (number or "").strip()
    if normalized_number:
        for question in questions:
            if (question.number or "").strip() == normalized_number:
                return question
    key = _norm_text(stem)
    if not key:
        return None
    for question in questions:
        if _norm_text(question.stem) == key:
            return question
    return None


def _norm_text(text: str) -> str:
    normalized = (text or "").strip().replace("\r", "\n")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()

__all__ = ["DedupeResultPage"]
