from PyQt6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWizardPage,
)

from sj_generator.models import Question
from sj_generator.ui.state import WizardState
from sj_generator.ui.constants import PAGE_DEDUPE_OPTION


class ReviewPage(QWizardPage):
    def __init__(self, state: WizardState) -> None:
        super().__init__()
        self._state = state
        self.setTitle("题目预览与编辑")

        self._table = QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(["编号", "题目", "选项", "答案", "解析"])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self._reload)

        save_btn = QPushButton("保存到当前草稿")
        save_btn.clicked.connect(self._save)

        btns = QHBoxLayout()
        btns.addWidget(refresh_btn)
        btns.addWidget(save_btn)
        btns.addStretch(1)

        hint = QLabel("双击单元格可编辑；本页保存仅更新当前草稿，后续流程会继续使用最新草稿。")
        hint.setWordWrap(True)

        layout = QVBoxLayout()
        layout.addLayout(btns)
        layout.addWidget(self._table)
        layout.addWidget(hint)
        self.setLayout(layout)

    def initializePage(self) -> None:
        self._reload()

    def _reload(self) -> None:
        questions = list(self._state.draft_questions)

        self._table.setRowCount(len(questions))
        for r, q in enumerate(questions):
            self._set_item(r, 0, q.number)
            self._set_item(r, 1, q.stem)
            self._set_item(r, 2, q.options)
            self._set_item(r, 3, q.answer)
            self._set_item(r, 4, q.analysis)

    def _save(self) -> None:
        questions: list[Question] = []
        for r in range(self._table.rowCount()):
            number = self._get_item_text(r, 0).strip()
            stem = self._get_item_text(r, 1).strip()
            options = self._get_item_text(r, 2).strip()
            answer = self._get_item_text(r, 3).strip()
            analysis = self._get_item_text(r, 4).strip()
            if not any([number, stem, options, answer, analysis]):
                continue
            questions.append(
                Question(
                    number=number,
                    stem=stem,
                    options=options,
                    answer=answer,
                    analysis=analysis,
                )
            )

        self._state.draft_questions = questions
        QMessageBox.information(self, "已保存", "已保存到当前草稿。")

    def _set_item(self, row: int, col: int, text: str) -> None:
        item = QTableWidgetItem(text or "")
        self._table.setItem(row, col, item)

    def _get_item_text(self, row: int, col: int) -> str:
        item = self._table.item(row, col)
        return item.text() if item is not None else ""

    def nextId(self) -> int:
        return PAGE_DEDUPE_OPTION
