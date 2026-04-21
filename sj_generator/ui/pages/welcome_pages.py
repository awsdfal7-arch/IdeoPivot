from __future__ import annotations

from dataclasses import replace
from datetime import date
from datetime import datetime
from pathlib import Path
import re

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenuBar,
    QMessageBox,
    QTextEdit,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWizard,
    QWizardPage,
    QWidget,
)

from sj_generator.config import load_welcome_table_column_visibility, save_welcome_table_column_visibility
from sj_generator.io.export_md import export_questions_to_markdown
from sj_generator.io.excel_repo import load_questions
from sj_generator.io.sqlite_repo import DbQuestionRecord, list_level_paths, load_questions_by_level_path, update_question
from sj_generator.models import Question
from sj_generator.ui.constants import PAGE_AI_SELECT
from sj_generator.ui.api_config_dialog import ApiConfigDialog
from sj_generator.ui.program_settings_dialog import ProgramSettingsDialog
from sj_generator.ui.state import WizardState

DEFAULT_LIBRARY_DB_PATH = Path(__file__).resolve().parents[3] / "converted_db" / "思政题库.db"
LAST_COLUMN_MIN_WIDTH = 140
TABLE_COLUMNS = [
    ("stem", "题目", True),
    ("options", "选项", True),
    ("answer", "答案", True),
    ("analysis", "解析", True),
    ("id", "题目id", False),
    ("question_type", "类型", False),
    ("textbook_version", "教材版本", False),
    ("source_filename", "来源文件名", False),
    ("level_path", "所属层级", False),
    ("difficulty_score", "难度评级", False),
    ("knowledge_points", "考察知识点", False),
    ("abilities", "考察能力", False),
    ("created_at", "入库时间", False),
    ("updated_at", "最后修改时间", False),
]


class WelcomePage(QWizardPage):
    def __init__(self, state: WizardState) -> None:
        super().__init__()
        self._state = state
        self._db_path = DEFAULT_LIBRARY_DB_PATH
        self._current_db_records: list[DbQuestionRecord] = []
        self._row_resize_pending = False
        self._row_resize_followup_pending = False
        self._column_defs = TABLE_COLUMNS
        self._column_visibility = self._load_column_visibility()
        self.setTitle("开始")

        title_label = QLabel("欢迎使用思政智题云枢")
        title_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        title_label.setStyleSheet("font-size: 22px; font-weight: 600;")

        menu_bar = QMenuBar(self)
        import_menu = menu_bar.addMenu("导入")
        self._doc_import_action = import_menu.addAction("从文档文件解析导入")
        self._doc_import_action.triggered.connect(self._enter_main_flow)
        self._table_import_action = import_menu.addAction("从表格文件直接导入")
        self._table_import_action.triggered.connect(self._import_from_table_file)
        export_menu = menu_bar.addMenu("导出")
        self._export_md_action = export_menu.addAction("导出当前层级为 Markdown")
        self._export_md_action.triggered.connect(self._export_current_level_to_markdown)
        view_menu = menu_bar.addMenu("视图")
        column_menu = view_menu.addMenu("表格列显示")
        settings_menu = menu_bar.addMenu("设置")
        self._general_settings_action = settings_menu.addAction("常规设定")
        self._general_settings_action.triggered.connect(self._open_program_settings)
        self._api_settings_action = settings_menu.addAction("配置API")
        self._api_settings_action.triggered.connect(self._open_api_cfg)

        self._folder_tree = QTreeWidget()
        self._folder_tree.setHeaderHidden(True)
        self._folder_tree.setAlternatingRowColors(True)
        self._folder_tree.currentItemChanged.connect(self._on_level_selection_changed)

        left_layout = QVBoxLayout()
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self._folder_tree, 1)
        left_panel = QWidget()
        left_panel.setStyleSheet("border: 1px solid black;")
        left_panel.setLayout(left_layout)

        self._table = QTableWidget(0, len(self._column_defs))
        self._table.setHorizontalHeaderLabels([title for _key, title, _visible in self._column_defs])
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setWordWrap(True)
        self._table.horizontalHeader().sectionResized.connect(self._schedule_table_row_resize)
        self._table.cellDoubleClicked.connect(self._on_table_cell_double_clicked)
        self._column_actions: dict[int, object] = {}
        for idx, (key, title, _visible) in enumerate(self._column_defs):
            visible = self._column_visibility.get(key, False)
            action = column_menu.addAction(title)
            action.setCheckable(True)
            action.setChecked(visible)
            action.toggled.connect(lambda checked, col=idx: self._set_column_visible(col, checked))
            self._column_actions[idx] = action
            self._table.setColumnHidden(idx, not visible)
        self._rebalance_visible_columns()

        right_layout = QVBoxLayout()
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self._table, 1)
        right_panel = QWidget()
        right_panel.setStyleSheet("border: 1px solid black;")
        right_panel.setLayout(right_layout)

        self._content_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._content_splitter.addWidget(left_panel)
        self._content_splitter.addWidget(right_panel)
        self._content_splitter.setChildrenCollapsible(False)
        self._content_splitter.setHandleWidth(8)
        self._content_splitter.setStyleSheet("QSplitter::handle { background-color: #d0d0d0; }")
        self._content_splitter.setStretchFactor(0, 1)
        self._content_splitter.setStretchFactor(1, 4)
        self._content_splitter.setSizes([180, 720])
        self._content_splitter.splitterMoved.connect(self._schedule_table_row_resize)

        layout = QVBoxLayout()
        layout.setMenuBar(menu_bar)
        layout.addWidget(title_label)
        layout.addWidget(self._content_splitter, 1)
        self.setLayout(layout)

    def initializePage(self) -> None:
        self._refresh_level_tree()
        if self._folder_tree.currentItem() is None:
            self._populate_questions_table(self._state.draft_questions)

    def nextId(self) -> int:
        self._state.start_mode = "wizard"
        return PAGE_AI_SELECT

    def _enter_main_flow(self) -> None:
        self._state.start_mode = "wizard"
        wizard = self.wizard()
        if wizard is not None:
            wizard.next()

    def _open_api_cfg(self) -> None:
        dlg = ApiConfigDialog(self)
        dlg.exec()

    def _open_program_settings(self) -> None:
        dlg = ProgramSettingsDialog(self._state, self)
        if dlg.exec():
            self._refresh_level_tree()

    def _import_from_table_file(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(self, "选择表格文件", "", "Excel (*.xlsx);;All Files (*)")
        if not file_path:
            return
        path = Path(file_path)
        try:
            questions = load_questions(path)
        except Exception as e:
            QMessageBox.critical(self, "导入失败", f"读取表格文件失败：{e}")
            return

        self._state.draft_questions = list(questions)
        self._populate_questions_table(questions)
        QMessageBox.information(self, "导入完成", f"已从表格文件导入 {len(questions)} 道题。")

    def _export_current_level_to_markdown(self) -> None:
        if not self._current_db_records:
            QMessageBox.warning(self, "无法导出", "当前层级没有可导出的题目。")
            return

        current = self._folder_tree.currentItem()
        if current is None:
            QMessageBox.warning(self, "无法导出", "请先选择要导出的层级。")
            return

        level_path = str(current.data(0, Qt.ItemDataRole.UserRole) or "").strip()
        if not level_path:
            QMessageBox.warning(self, "无法导出", "当前层级无效，无法导出。")
            return

        safe_level_name = self._sanitize_export_name(level_path)
        suggested = str(self._db_path.parent / f"{safe_level_name}.md")
        file_path, _ = QFileDialog.getSaveFileName(self, "导出 Markdown", suggested, "Markdown (*.md)")
        if not file_path:
            return

        questions = [self._db_record_to_question(record) for record in self._current_db_records]
        md_text = export_questions_to_markdown(
            excel_file_name=level_path,
            export_date=date.today(),
            questions=questions,
        )
        md_path = Path(file_path)
        try:
            md_path.parent.mkdir(parents=True, exist_ok=True)
            md_path.write_text(md_text, encoding="utf-8")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", f"写入 Markdown 失败：{e}")
            return

        self._state.last_export_dir = md_path.parent
        QMessageBox.information(self, "导出完成", f"已导出 Markdown：\n{md_path}")

    def _refresh_level_tree(self) -> None:
        self._folder_tree.clear()
        if not self._db_path.exists():
            return

        item_map: dict[tuple[str, ...], QTreeWidgetItem] = {}
        first_selectable_item: QTreeWidgetItem | None = None
        for level_path in list_level_paths(self._db_path):
            parts = self._parse_level_parts(level_path)
            if not parts:
                continue
            parent_item: QTreeWidgetItem | None = None
            path_parts: list[str] = []
            for idx, part in enumerate(parts):
                path_parts.append(part)
                key = tuple(path_parts)
                item = item_map.get(key)
                if item is None:
                    item = QTreeWidgetItem([self._format_level_label(idx, part)])
                    item.setToolTip(0, ".".join(path_parts))
                    if parent_item is None:
                        self._folder_tree.addTopLevelItem(item)
                    else:
                        parent_item.addChild(item)
                    item_map[key] = item
                if idx == len(parts) - 1:
                    item.setData(0, Qt.ItemDataRole.UserRole, level_path)
                    if first_selectable_item is None:
                        first_selectable_item = item
                parent_item = item

        if first_selectable_item is not None:
            self._folder_tree.setCurrentItem(first_selectable_item)
            self._expand_item_ancestors(first_selectable_item)
        else:
            self._table.setRowCount(0)
            self._schedule_table_row_resize()

    def _on_level_selection_changed(self, current: QTreeWidgetItem | None, _previous: QTreeWidgetItem | None) -> None:
        if current is None:
            self._current_db_records = []
            self._table.setRowCount(0)
            return
        level_path = current.data(0, Qt.ItemDataRole.UserRole)
        if not level_path:
            self._current_db_records = []
            self._table.setRowCount(0)
            return
        records = load_questions_by_level_path(self._db_path, str(level_path))
        self._current_db_records = records
        self._populate_db_records_table(records)

    def _parse_level_parts(self, level_path: str) -> list[str]:
        return [part.strip() for part in str(level_path).split(".") if part.strip()]

    def _format_level_label(self, depth: int, part: str) -> str:
        if not part.isdigit():
            return part
        if depth == 0:
            return f"必修{self._to_chinese_number(int(part))}"
        if depth == 1:
            return f"第{self._to_chinese_number(int(part))}课"
        if depth == 2:
            return f"第{self._to_chinese_number(int(part))}框"
        return part

    def _expand_item_ancestors(self, item: QTreeWidgetItem) -> None:
        current: QTreeWidgetItem | None = item
        while current is not None:
            current.setExpanded(True)
            current = current.parent()

    def _to_chinese_number(self, value: int) -> str:
        digits = {
            0: "零",
            1: "一",
            2: "二",
            3: "三",
            4: "四",
            5: "五",
            6: "六",
            7: "七",
            8: "八",
            9: "九",
            10: "十",
        }
        if value <= 10:
            return digits[value]
        if value < 20:
            return "十" + digits[value - 10]
        tens, ones = divmod(value, 10)
        if ones == 0:
            return digits[tens] + "十"
        return digits[tens] + "十" + digits[ones]

    def _populate_questions_table(self, questions: list[Question]) -> None:
        self._current_db_records = []
        self._table.setRowCount(len(questions))
        for row, question in enumerate(questions):
            values = self._build_question_row_values(row + 1, question)
            self._populate_row_by_values(row, values)
        self._schedule_table_row_resize()

    def _populate_db_records_table(self, records: list[DbQuestionRecord]) -> None:
        self._table.setRowCount(len(records))
        for row, record in enumerate(records):
            values = self._build_db_row_values(row + 1, record)
            self._populate_row_by_values(row, values)
        self._schedule_table_row_resize()

    def _build_question_row_values(self, sequence: int, question: Question) -> dict[str, str]:
        return {
            "stem": self._format_stem_with_sequence(sequence, question.stem),
            "options": question.options,
            "answer": question.answer,
            "analysis": question.analysis,
            "id": "",
            "question_type": "",
            "textbook_version": "",
            "source_filename": "",
            "level_path": "",
            "difficulty_score": "",
            "knowledge_points": "",
            "abilities": "",
            "created_at": "",
            "updated_at": "",
        }

    def _build_db_row_values(self, sequence: int, record: DbQuestionRecord) -> dict[str, str]:
        return {
            "stem": self._format_stem_with_sequence(sequence, record.stem),
            "options": self._format_db_options(record),
            "answer": self._format_db_answer(record),
            "analysis": record.analysis,
            "id": record.id,
            "question_type": record.question_type,
            "textbook_version": record.textbook_version,
            "source_filename": record.source_filename,
            "level_path": record.level_path,
            "difficulty_score": "" if record.difficulty_score is None else str(record.difficulty_score),
            "knowledge_points": record.knowledge_points,
            "abilities": record.abilities,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }

    def _db_record_to_question(self, record: DbQuestionRecord) -> Question:
        return Question(
            number=record.id,
            stem=record.stem,
            options=self._format_db_options(record),
            answer=self._format_db_answer(record),
            analysis=record.analysis,
        )

    def _populate_row_by_values(self, row: int, values: dict[str, str]) -> None:
        for col, (key, _title, _visible) in enumerate(self._column_defs):
            alignment = Qt.AlignmentFlag.AlignCenter if key == "answer" else Qt.AlignmentFlag.AlignLeft
            self._set_table_item(row, col, values.get(key, ""), alignment)

    def _format_db_options(self, record: DbQuestionRecord) -> str:
        options = [record.option_1, record.option_2, record.option_3, record.option_4]
        if record.question_type in ("多选", "可转多选"):
            markers = ["①", "②", "③", "④"]
        else:
            markers = ["A", "B", "C", "D"]
        lines = [
            f"{markers[idx - 1]}. {text.strip()}".rstrip()
            for idx, text in enumerate(options, start=1)
            if text.strip()
        ]
        return "\n".join(lines)

    def _format_db_answer(self, record: DbQuestionRecord) -> str:
        answer = (record.answer or "").strip()
        if record.question_type not in ("多选", "可转多选"):
            return answer
        marker_map = {
            "1": "①",
            "2": "②",
            "3": "③",
            "4": "④",
            "5": "⑤",
            "6": "⑥",
            "7": "⑦",
            "8": "⑧",
            "9": "⑨",
            "10": "⑩",
        }
        tokens = [token.strip() for token in answer.replace("，", ",").split(",") if token.strip()]
        if not tokens:
            return answer
        return "".join(marker_map.get(token, token) for token in tokens)

    def _format_stem_with_sequence(self, sequence: int, stem: str) -> str:
        return f"{sequence}. {stem or ''}".strip()

    def _sanitize_export_name(self, name: str) -> str:
        cleaned = re.sub(r'[<>:"/\\\\|?*]+', "_", (name or "").strip())
        cleaned = cleaned.strip(" .")
        return cleaned or "导出结果"

    def _set_table_item(
        self,
        row: int,
        col: int,
        text: str,
        alignment: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft,
    ) -> None:
        item = QTableWidgetItem(text or "")
        item.setTextAlignment(
            int(alignment | Qt.AlignmentFlag.AlignVCenter)
        )
        self._table.setItem(row, col, item)

    def _set_column_visible(self, column: int, visible: bool) -> None:
        if visible:
            self._table.setColumnHidden(column, False)
            self._save_column_visibility()
            self._refresh_table_layout_after_column_change()
            return

        visible_columns = [idx for idx in range(self._table.columnCount()) if not self._table.isColumnHidden(idx)]
        if len(visible_columns) <= 1:
            action = self._column_actions.get(column)
            if action is not None:
                action.blockSignals(True)
                action.setChecked(True)
                action.blockSignals(False)
            return

        self._table.setColumnHidden(column, True)
        self._save_column_visibility()
        self._refresh_table_layout_after_column_change()

    def _schedule_table_row_resize(self, *_args) -> None:
        if self._row_resize_pending:
            return
        self._row_resize_pending = True
        QTimer.singleShot(0, self._apply_table_row_resize)

    def _apply_table_row_resize(self) -> None:
        self._row_resize_pending = False
        if self._table.rowCount() == 0:
            return
        self._table.doItemsLayout()
        self._table.resizeRowsToContents()
        if not self._row_resize_followup_pending:
            self._row_resize_followup_pending = True
            QTimer.singleShot(30, self._apply_table_row_resize_followup)

    def _apply_table_row_resize_followup(self) -> None:
        self._row_resize_followup_pending = False
        if self._table.rowCount() == 0:
            return
        self._table.doItemsLayout()
        self._table.viewport().update()
        self._table.resizeRowsToContents()

    def _refresh_table_layout_after_column_change(self) -> None:
        self._rebalance_visible_columns()
        self._table.doItemsLayout()
        self._table.viewport().update()
        self._schedule_table_row_resize()

    def _rebalance_visible_columns(self) -> None:
        visible_columns = [idx for idx in range(self._table.columnCount()) if not self._table.isColumnHidden(idx)]
        if not visible_columns:
            return
        available_width = max(1, self._table.viewport().width())
        if len(visible_columns) == 1:
            self._table.setColumnWidth(visible_columns[0], available_width)
            return
        fixed_columns = visible_columns[:-1]
        reserved_last_width = min(available_width, LAST_COLUMN_MIN_WIDTH)
        distributable_width = max(len(fixed_columns), available_width - reserved_last_width)
        base_width = max(1, distributable_width // len(fixed_columns))
        consumed_width = 0
        for column in fixed_columns:
            self._table.setColumnWidth(column, base_width)
            consumed_width += base_width
        self._table.setColumnWidth(visible_columns[-1], max(1, available_width - consumed_width))

    def _load_column_visibility(self) -> dict[str, bool]:
        saved = load_welcome_table_column_visibility()
        defaults = {key: visible for key, _title, visible in self._column_defs}
        merged = defaults | {key: value for key, value in saved.items() if key in defaults}
        if not any(merged.values()):
            first_key = self._column_defs[0][0]
            merged[first_key] = True
        return merged

    def _save_column_visibility(self) -> None:
        visibility = {
            key: (not self._table.isColumnHidden(idx))
            for idx, (key, _title, _visible) in enumerate(self._column_defs)
        }
        save_welcome_table_column_visibility(visibility)

    def _on_table_cell_double_clicked(self, row: int, _column: int) -> None:
        if row < 0 or row >= len(self._current_db_records):
            return
        record = self._current_db_records[row]
        dlg = _QuestionEditDialog(record, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        updated = dlg.updated_record()
        try:
            update_question(self._db_path, updated)
        except Exception as e:
            QMessageBox.critical(self, "保存失败", f"更新题目失败：{e}")
            return
        self._current_db_records[row] = updated
        current = self._folder_tree.currentItem()
        if current is None:
            return
        level_path = current.data(0, Qt.ItemDataRole.UserRole)
        if not level_path:
            return
        records = load_questions_by_level_path(self._db_path, str(level_path))
        self._current_db_records = records
        self._populate_db_records_table(records)


class _QuestionEditDialog(QDialog):
    def __init__(self, record: DbQuestionRecord, parent=None) -> None:
        super().__init__(parent)
        self._record = record
        self.setWindowTitle("编辑条目")
        self.resize(760, 620)

        self._type_combo = QComboBox()
        self._type_combo.addItems(["单选", "多选", "可转多选"])
        self._type_combo.setCurrentText(record.question_type or "单选")

        self._stem_edit = QTextEdit()
        self._stem_edit.setPlainText(record.stem)
        self._option_1_edit = QLineEdit(record.option_1)
        self._option_2_edit = QLineEdit(record.option_2)
        self._option_3_edit = QLineEdit(record.option_3)
        self._option_4_edit = QLineEdit(record.option_4)
        self._answer_edit = QLineEdit(record.answer)
        self._analysis_edit = QTextEdit()
        self._analysis_edit.setPlainText(record.analysis)

        self._source_label = QLabel(record.source_filename)
        self._level_label = QLabel(record.level_path)
        self._version_label = QLabel(record.textbook_version)

        form = QFormLayout()
        form.addRow("类型：", self._type_combo)
        form.addRow("题目：", self._stem_edit)
        form.addRow("选项1：", self._option_1_edit)
        form.addRow("选项2：", self._option_2_edit)
        form.addRow("选项3：", self._option_3_edit)
        form.addRow("选项4：", self._option_4_edit)
        form.addRow("答案：", self._answer_edit)
        form.addRow("解析：", self._analysis_edit)
        form.addRow("来源文件名：", self._source_label)
        form.addRow("所属层级：", self._level_label)
        form.addRow("教材版本：", self._version_label)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.setLayout(layout)

    def updated_record(self) -> DbQuestionRecord:
        return replace(
            self._record,
            stem=self._stem_edit.toPlainText().strip(),
            option_1=self._option_1_edit.text().strip(),
            option_2=self._option_2_edit.text().strip(),
            option_3=self._option_3_edit.text().strip(),
            option_4=self._option_4_edit.text().strip(),
            answer=self._answer_edit.text().strip(),
            analysis=self._analysis_edit.toPlainText().strip(),
            question_type=self._type_combo.currentText().strip(),
            updated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
