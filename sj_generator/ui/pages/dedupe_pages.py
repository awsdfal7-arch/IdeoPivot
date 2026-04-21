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
    QRadioButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWizardPage,
)

from sj_generator.io.dedupe import (
    DedupeHit,
    dedupe_between_questions_and_db,
)
from sj_generator.io.sqlite_repo import load_all_questions
from sj_generator.models import Question
from sj_generator.ui.state import WizardState
from sj_generator.ui.constants import (
    PAGE_AI_ANALYSIS_OPTION,
    PAGE_DEDUPE_RESULT,
)

DEFAULT_LIBRARY_DB_PATH = Path(__file__).resolve().parents[3] / "converted_db" / "思政题库.db"

class DedupeOptionPage(QWizardPage):
    def __init__(self, state: WizardState) -> None:
        super().__init__()
        self._state = state
        self.setTitle("查重选项")

        self._yes_radio = QRadioButton("运行库内查重")
        self._no_radio = QRadioButton("跳过库内查重")
        self._yes_radio.setChecked(True)

        hint = QLabel("选择“运行库内查重”后，将直接使用当前总库执行查重，无需再指定路径。")
        hint.setWordWrap(True)

        layout = QVBoxLayout()
        layout.addWidget(self._yes_radio)
        layout.addWidget(self._no_radio)
        layout.addWidget(hint)
        layout.addStretch(1)
        self.setLayout(layout)

    def initializePage(self) -> None:
        if self._state.dedupe_enabled:
            self._yes_radio.setChecked(True)
        else:
            self._no_radio.setChecked(True)

    def validatePage(self) -> bool:
        self._state.dedupe_enabled = self._yes_radio.isChecked()
        if not self._state.dedupe_enabled:
            self._state.dedupe_hits = None
        return True

    def nextId(self) -> int:
        return PAGE_DEDUPE_RESULT if self._state.dedupe_enabled else PAGE_AI_ANALYSIS_OPTION


class DedupeResultPage(QWizardPage):
    def __init__(self, state: WizardState) -> None:
        super().__init__()
        self._state = state
        self.setTitle("库内查重（结果）")

        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)

        self._table = QTableWidget()
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
        self._current_left_source_path = self._resolve_left_source_path()
        if self._state.dedupe_hits is not None:
            self._hits = self._state.dedupe_hits
            self._render_hits(self._hits)
            self._running = False
            self._done = True
            self.completeChanged.emit()
            return

        self._hits = []
        self._table.setRowCount(0)
        self._status_label.setText("正在查重…")
        self._running = True
        self._done = False
        self.completeChanged.emit()

        repo = self._current_left_source_path
        left_questions = list(self._state.draft_questions)
        threshold = self._state.dedupe_threshold
        if not left_questions:
            self._on_error("当前题库草稿为空，无法执行查重。")
            return
        db_path = DEFAULT_LIBRARY_DB_PATH
        if not db_path.exists():
            self._on_error(f"当前总库不存在：{db_path}")
            return
        if not load_all_questions(db_path):
            self._on_done([])
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

    def nextId(self) -> int:
        return PAGE_AI_ANALYSIS_OPTION

    def _render_hits(self, hits: list[DedupeHit]) -> None:
        self._table.setRowCount(len(hits))
        for r, h in enumerate(hits):
            self._table.setItem(r, 0, QTableWidgetItem(h.left_stem.strip()[:40]))
            self._table.setItem(r, 1, QTableWidgetItem(h.left_number or ""))
            self._table.setItem(r, 2, QTableWidgetItem(h.right_file.name))
            self._table.setItem(r, 3, QTableWidgetItem(h.right_level_path or ""))
            self._table.setItem(r, 4, QTableWidgetItem(f"{h.similarity:.3f}"))

    def _on_done(self, hits: list[DedupeHit]) -> None:
        self._running = False
        self._done = True
        self._thread = None
        self._worker = None

        self._hits = hits
        self._state.dedupe_hits = hits
        if not hits:
            self._status_label.setText("未发现达到阈值的重复题。")
            self._table.setRowCount(0)
        else:
            self._render_hits(hits)
            self._status_label.setText(f"库内查重完成：{len(hits)} 条结果（双击查看详情）")
        self.completeChanged.emit()

    def _on_error(self, msg: str) -> None:
        self._running = False
        self._done = False
        self._thread = None
        self._worker = None
        QMessageBox.critical(self, "查重失败", msg)
        self._status_label.setText("查重失败。")
        self.completeChanged.emit()

    def _open_detail(self, row: int, col: int) -> None:
        if row < 0 or row >= len(self._hits):
            return
        hit = self._hits[row]
        dlg = _DedupeDetailDialog(self, hit=hit, loader=self._load_questions_cached)
        dlg.exec()

    def _resolve_left_source_path(self) -> Path:
        if self._state.repo_path is not None:
            return self._state.repo_path
        if self._state.project_dir is not None:
            return self._state.project_dir / "当前草稿.xlsx"
        return DEFAULT_LIBRARY_DB_PATH.parent / "当前草稿.xlsx"

    def _load_questions_cached(self, path: Path) -> list[Question]:
        p = path.resolve()
        if p in self._questions_cache:
            return self._questions_cache[p]
        if p == self._current_left_source_path.resolve():
            qs = list(self._state.draft_questions)
        else:
            if p == DEFAULT_LIBRARY_DB_PATH.resolve():
                records = load_all_questions(p)
                qs = [
                    Question(
                        number=record.id,
                        stem=record.stem,
                        options="\n".join(
                            f"{idx}. {text}"
                            for idx, text in enumerate(
                                [record.option_1, record.option_2, record.option_3, record.option_4],
                                start=1,
                            )
                            if text.strip()
                        ),
                        answer=record.answer,
                        analysis=record.analysis,
                    )
                    for record in records
                ]
            else:
                from sj_generator.io.excel_repo import load_questions

                qs = load_questions(p)
        self._questions_cache[p] = qs
        return qs


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
        except Exception as e:
            self.error.emit(str(e))


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

        layout = QVBoxLayout()
        layout.addWidget(QLabel(f"相似度：{hit.similarity:.3f}"))
        layout.addWidget(splitter)
        layout.addWidget(buttons)
        self.setLayout(layout)

        left_q = _find_question(loader(hit.left_file), hit.left_number, hit.left_stem)
        right_q = _find_question(loader(hit.right_file), hit.right_number, hit.right_stem)
        left.setPlainText(_format_question_block(hit.left_file, left_q, fallback_stem=hit.left_stem))
        right.setPlainText(_format_question_block(hit.right_file, right_q, fallback_stem=hit.right_stem))


def _format_question_block(path: Path, q: Question | None, *, fallback_stem: str) -> str:
    if q is None:
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
            f"编号：{(q.number or '').strip()}",
            "",
            "题干：",
            (q.stem or "").strip(),
            "",
            "选项：",
            (q.options or "").strip(),
            "",
            "答案：",
            (q.answer or "").strip(),
        ]
    ).strip() + "\n"


def _find_question(questions: list[Question], number: str, stem: str) -> Question | None:
    num = (number or "").strip()
    if num:
        for q in questions:
            if (q.number or "").strip() == num:
                return q
    key = _norm_text(stem)
    if not key:
        return None
    for q in questions:
        if _norm_text(q.stem) == key:
            return q
    return None


def _norm_text(text: str) -> str:
    s = (text or "").strip().replace("\r", "\n")
    s = re.sub(r"\s+", " ", s)
    return s.strip()
