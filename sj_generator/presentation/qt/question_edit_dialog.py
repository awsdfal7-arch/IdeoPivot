from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from PyQt6.QtCore import QRegularExpression, Qt
from PyQt6.QtGui import QKeyEvent, QRegularExpressionValidator
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStackedLayout,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from sj_generator.infrastructure.persistence.sqlite_repo import DbQuestionRecord
from sj_generator.presentation.qt.message_box import show_message_box


class LevelPathPartLineEdit(QLineEdit):
    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self._prev_edit: QLineEdit | None = None
        self._next_edit: QLineEdit | None = None

    def set_neighbors(self, prev_edit: QLineEdit | None, next_edit: QLineEdit | None) -> None:
        self._prev_edit = prev_edit
        self._next_edit = next_edit

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key == Qt.Key.Key_Left and self.cursorPosition() == 0 and self._prev_edit is not None:
            self._prev_edit.setFocus()
            self._prev_edit.setCursorPosition(len(self._prev_edit.text()))
            event.accept()
            return
        if key == Qt.Key.Key_Right and self.cursorPosition() == len(self.text()) and self._next_edit is not None:
            self._next_edit.setFocus()
            self._next_edit.setCursorPosition(0)
            event.accept()
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Tab):
            if self._next_edit is not None:
                self._next_edit.setFocus()
                self._next_edit.selectAll()
            else:
                self.focusNextPrevChild(True)
            event.accept()
            return
        if key == Qt.Key.Key_Backtab:
            if self._prev_edit is not None:
                self._prev_edit.setFocus()
                self._prev_edit.selectAll()
            else:
                self.focusNextPrevChild(False)
            event.accept()
            return
        super().keyPressEvent(event)


class QuestionEditDialog(QDialog):
    DELETE_RESULT = 2

    def __init__(self, record: DbQuestionRecord, parent=None, *, create_mode: bool = False) -> None:
        super().__init__(parent)
        self._record = record
        self._create_mode = create_mode
        self.setWindowTitle("新增题目" if create_mode else "编辑条目")
        self.resize(760, 484)

        self._type_combo = QComboBox()
        self._type_combo.addItems(["单选", "多选", "可转多选"])
        self._type_combo.setCurrentText(record.question_type or "单选")

        self._stem_edit = QTextEdit()
        self._stem_edit.setPlainText(record.stem)
        self._stem_edit.setPlaceholderText("题目内容")
        self._option_1_edit = QLineEdit(record.option_1)
        self._option_2_edit = QLineEdit(record.option_2)
        self._option_3_edit = QLineEdit(record.option_3)
        self._option_4_edit = QLineEdit(record.option_4)
        self._choice_1_edit = QLineEdit(record.choice_1)
        self._choice_2_edit = QLineEdit(record.choice_2)
        self._choice_3_edit = QLineEdit(record.choice_3)
        self._choice_4_edit = QLineEdit(record.choice_4)
        self._answer_line_edit = QLineEdit(record.answer)
        self._answer_line_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._answer_combo = QComboBox()
        self._answer_combo.addItems(["", "A", "B", "C", "D"])
        self._answer_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        combo_answer = (record.answer or "").strip().upper()
        combo_idx = self._answer_combo.findText(combo_answer)
        self._answer_combo.setCurrentIndex(combo_idx if combo_idx >= 0 else 0)
        answer_parts = self._split_multi_answer(record.answer)
        self._answer_part_1_edit = self._create_answer_part_edit(answer_parts[0])
        self._answer_part_2_edit = self._create_answer_part_edit(answer_parts[1])
        self._answer_part_3_edit = self._create_answer_part_edit(answer_parts[2])
        self._answer_part_4_edit = self._create_answer_part_edit(answer_parts[3])
        self._answer_part_1_edit.set_neighbors(None, self._answer_part_2_edit)
        self._answer_part_2_edit.set_neighbors(self._answer_part_1_edit, self._answer_part_3_edit)
        self._answer_part_3_edit.set_neighbors(self._answer_part_2_edit, self._answer_part_4_edit)
        self._answer_part_4_edit.set_neighbors(self._answer_part_3_edit, None)
        self._analysis_edit = QTextEdit()
        self._analysis_edit.setPlainText(record.analysis)
        self._analysis_edit.setPlaceholderText("解析内容")

        self._source_value = QLineEdit(self._format_source_display(record.source))
        self._source_value.setReadOnly(True)
        self._source_value.setPlaceholderText("题目来源：")
        level_parts = self._split_level_path(record.level_path)
        self._level_prefix_label = QLabel("所属层级：")
        self._level_part_1_edit = self._create_level_part_edit(level_parts[0])
        self._level_part_2_edit = self._create_level_part_edit(level_parts[1])
        self._level_part_3_edit = self._create_level_part_edit(level_parts[2])
        self._level_part_1_edit.set_neighbors(None, self._level_part_2_edit)
        self._level_part_2_edit.set_neighbors(self._level_part_1_edit, self._level_part_3_edit)
        self._level_part_3_edit.set_neighbors(self._level_part_2_edit, None)
        self._version_edit = QComboBox()
        self._version_edit.setEditable(True)
        self._version_edit.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        for version in self._collect_textbook_version_options(record.textbook_version):
            self._version_edit.addItem(self._format_prefixed_display("教材版本：", version))
        self._version_edit.setCurrentText(self._format_prefixed_display("教材版本：", record.textbook_version))
        if self._version_edit.lineEdit() is not None:
            self._version_edit.lineEdit().setPlaceholderText("教材版本：")
        if self._version_edit.lineEdit() is not None:
            self._bind_locked_prefix(self._version_edit.lineEdit(), "教材版本：")
        self._option_1_label = QLabel("A：")
        self._option_2_label = QLabel("B：")
        self._option_3_label = QLabel("C：")
        self._option_4_label = QLabel("D：")
        self._choice_1_label = QLabel("A：")
        self._choice_2_label = QLabel("B：")
        self._choice_3_label = QLabel("C：")
        self._choice_4_label = QLabel("D：")
        self._stem_edit.setMinimumHeight(180)
        self._analysis_edit.setMinimumHeight(140)

        def wrap_panel(title: str, body_layout: QGridLayout | QVBoxLayout | QHBoxLayout) -> QWidget:
            panel = QWidget()
            layout = QVBoxLayout(panel)
            layout.setContentsMargins(2, 2, 2, 2)
            layout.setSpacing(8)
            if title:
                title_label = QLabel(title)
                title_label.setStyleSheet("font-weight: 600;")
                layout.addWidget(title_label)
            layout.addLayout(body_layout)
            return panel

        stem_layout = QVBoxLayout()
        stem_layout.setContentsMargins(0, 0, 0, 0)
        stem_layout.addWidget(self._stem_edit)
        stem_panel = wrap_panel("", stem_layout)

        option_fields_layout = QGridLayout()
        option_fields_layout.setContentsMargins(0, 0, 0, 0)
        option_fields_layout.setHorizontalSpacing(8)
        option_fields_layout.setVerticalSpacing(8)
        option_fields_layout.addWidget(self._option_1_label, 0, 0)
        option_fields_layout.addWidget(self._option_1_edit, 0, 1)
        option_fields_layout.addWidget(self._option_2_label, 1, 0)
        option_fields_layout.addWidget(self._option_2_edit, 1, 1)
        option_fields_layout.addWidget(self._option_3_label, 2, 0)
        option_fields_layout.addWidget(self._option_3_edit, 2, 1)
        option_fields_layout.addWidget(self._option_4_label, 3, 0)
        option_fields_layout.addWidget(self._option_4_edit, 3, 1)
        option_fields_layout.setColumnStretch(1, 1)

        choice_fields_layout = QGridLayout()
        choice_fields_layout.setContentsMargins(0, 0, 0, 0)
        choice_fields_layout.setHorizontalSpacing(8)
        choice_fields_layout.setVerticalSpacing(8)
        choice_fields_layout.addWidget(self._choice_1_label, 0, 0)
        choice_fields_layout.addWidget(self._choice_1_edit, 0, 1)
        choice_fields_layout.addWidget(self._choice_2_label, 1, 0)
        choice_fields_layout.addWidget(self._choice_2_edit, 1, 1)
        choice_fields_layout.addWidget(self._choice_3_label, 2, 0)
        choice_fields_layout.addWidget(self._choice_3_edit, 2, 1)
        choice_fields_layout.addWidget(self._choice_4_label, 3, 0)
        choice_fields_layout.addWidget(self._choice_4_edit, 3, 1)
        choice_fields_layout.setColumnStretch(1, 1)

        option_fields_widget = QWidget()
        option_fields_widget.setLayout(option_fields_layout)
        self._choice_fields_widget = QWidget()
        self._choice_fields_widget.setLayout(choice_fields_layout)

        options_layout = QHBoxLayout()
        options_layout.setContentsMargins(0, 0, 0, 0)
        options_layout.setSpacing(12)
        options_layout.addWidget(option_fields_widget, 3)
        options_layout.addWidget(self._choice_fields_widget, 2)
        options_panel_layout = QVBoxLayout()
        options_panel_layout.setContentsMargins(0, 0, 0, 0)
        options_panel_layout.setSpacing(8)
        options_panel_layout.addLayout(options_layout)
        options_panel = wrap_panel("", options_panel_layout)

        answer_layout = QGridLayout()
        answer_layout.setContentsMargins(0, 0, 0, 0)
        answer_layout.setHorizontalSpacing(8)
        answer_layout.setVerticalSpacing(8)
        self._answer_stack = QStackedLayout()
        self._answer_stack.setContentsMargins(0, 0, 0, 0)
        answer_stack_widget = QWidget()
        answer_stack_widget.setLayout(self._answer_stack)
        answer_stack_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._answer_stack.addWidget(self._answer_line_edit)
        self._answer_stack.addWidget(self._answer_combo)
        answer_multi_row = QHBoxLayout()
        answer_multi_row.setContentsMargins(0, 0, 0, 0)
        answer_multi_row.setSpacing(6)
        answer_multi_row.addWidget(self._answer_part_1_edit)
        answer_multi_row.addWidget(self._answer_part_2_edit)
        answer_multi_row.addWidget(self._answer_part_3_edit)
        answer_multi_row.addWidget(self._answer_part_4_edit)
        answer_multi_row.addStretch(1)
        answer_multi_widget = QWidget()
        answer_multi_widget.setLayout(answer_multi_row)
        answer_multi_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._answer_stack.addWidget(answer_multi_widget)
        answer_layout.addWidget(QLabel("答案："), 0, 0)
        answer_layout.addWidget(answer_stack_widget, 0, 1)
        answer_layout.addWidget(QLabel("题型："), 1, 0)
        answer_layout.addWidget(self._type_combo, 1, 1)
        answer_layout.setColumnStretch(1, 1)
        answer_panel = wrap_panel("", answer_layout)

        analysis_layout = QVBoxLayout()
        analysis_layout.setContentsMargins(0, 0, 0, 0)
        analysis_layout.addWidget(self._analysis_edit)
        analysis_panel = wrap_panel("", analysis_layout)

        source_content_layout = QVBoxLayout()
        source_content_layout.setContentsMargins(0, 0, 0, 0)
        source_content_layout.addWidget(self._source_value)
        source_content_panel = wrap_panel("", source_content_layout)

        level_content_layout = QVBoxLayout()
        level_content_layout.setContentsMargins(0, 0, 0, 0)
        level_row = QHBoxLayout()
        level_row.setContentsMargins(0, 0, 0, 0)
        level_row.setSpacing(6)
        level_row.addWidget(self._level_prefix_label)
        level_row.addWidget(self._level_part_1_edit)
        level_row.addWidget(QLabel("."))
        level_row.addWidget(self._level_part_2_edit)
        level_row.addWidget(QLabel("."))
        level_row.addWidget(self._level_part_3_edit)
        level_row.addStretch(1)
        level_content_layout.addLayout(level_row)
        level_content_panel = wrap_panel("", level_content_layout)

        version_content_layout = QVBoxLayout()
        version_content_layout.setContentsMargins(0, 0, 0, 0)
        version_content_layout.addWidget(self._version_edit)
        version_content_panel = wrap_panel("", version_content_layout)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_button is not None:
            ok_button.setText("确定")
            ok_button.setMinimumSize(96, 36)
        cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_button is not None:
            cancel_button.setText("取消")
            cancel_button.setMinimumSize(96, 36)

        button_row = QHBoxLayout()
        self._delete_btn = QPushButton("删除题目")
        self._delete_btn.setMinimumSize(96, 36)
        self._delete_btn.setStyleSheet("border: 1px solid #c00000;")
        self._delete_btn.clicked.connect(self._on_delete_clicked)
        if not self._create_mode:
            button_row.addWidget(self._delete_btn)
        button_row.addStretch(1)
        button_row.addWidget(buttons)

        content_grid = QGridLayout()
        content_grid.setContentsMargins(0, 0, 0, 0)
        content_grid.setHorizontalSpacing(10)
        content_grid.setVerticalSpacing(10)
        content_grid.addWidget(stem_panel, 0, 0, 5, 2)
        content_grid.addWidget(answer_panel, 0, 2, 1, 2)
        content_grid.addWidget(options_panel, 1, 2, 4, 2)
        content_grid.addWidget(analysis_panel, 5, 0, 2, 4)
        content_grid.addWidget(level_content_panel, 7, 0, 1, 4)
        content_grid.addWidget(version_content_panel, 8, 0, 1, 4)
        content_grid.addWidget(source_content_panel, 9, 0, 1, 4)
        for col in range(4):
            content_grid.setColumnStretch(col, 1)
        for row in range(10):
            content_grid.setRowStretch(row, 0)
        content_grid.setRowStretch(5, 1)
        content_grid.setRowStretch(6, 1)

        layout = QVBoxLayout()
        layout.addLayout(content_grid)
        layout.addLayout(button_row)
        self.setLayout(layout)
        self._type_combo.currentTextChanged.connect(self._sync_choice_fields_visibility)
        self._sync_choice_fields_visibility(self._type_combo.currentText())

    def accept(self) -> None:
        level_parts = [
            self._level_part_1_edit.text().strip(),
            self._level_part_2_edit.text().strip(),
            self._level_part_3_edit.text().strip(),
        ]
        if any(level_parts) and not all(level_parts):
            show_message_box(
                self,
                title="所属层级不完整",
                text="所属层级需要按“数字.数字.数字”完整填写。",
                icon=QMessageBox.Icon.Warning,
            )
            return
        super().accept()

    def updated_record(self) -> DbQuestionRecord:
        return replace(
            self._record,
            stem=self._stem_edit.toPlainText().strip(),
            option_1=self._option_1_edit.text().strip(),
            option_2=self._option_2_edit.text().strip(),
            option_3=self._option_3_edit.text().strip(),
            option_4=self._option_4_edit.text().strip(),
            choice_1=self._choice_1_edit.text().strip(),
            choice_2=self._choice_2_edit.text().strip(),
            choice_3=self._choice_3_edit.text().strip(),
            choice_4=self._choice_4_edit.text().strip(),
            answer=self._current_answer_text(),
            analysis=self._analysis_edit.toPlainText().strip(),
            question_type=self._type_combo.currentText().strip(),
            source=self._parse_source_display(self._source_value.text()),
            level_path=self._compose_level_path(),
            textbook_version=self._parse_prefixed_display("教材版本：", self._version_edit.currentText()),
            updated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )

    def _format_source_display(self, source: str) -> str:
        return self._format_prefixed_display("题目来源：", source)

    def _parse_source_display(self, text: str) -> str:
        return self._parse_prefixed_display("题目来源：", text)

    def _bind_locked_prefix(self, edit: QLineEdit, prefix: str) -> None:
        edit.textEdited.connect(
            lambda _text, target=edit, locked_prefix=prefix: self._ensure_locked_prefix(target, locked_prefix)
        )
        edit.cursorPositionChanged.connect(
            lambda _old, new, target=edit, locked_prefix=prefix: self._clamp_prefix_cursor(
                target, locked_prefix, new
            )
        )
        self._ensure_locked_prefix(edit, prefix)

    def _create_level_part_edit(self, value: str) -> LevelPathPartLineEdit:
        edit = LevelPathPartLineEdit((value or "").strip()[:1])
        edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        edit.setMaxLength(1)
        edit.setFixedWidth(36)
        edit.setPlaceholderText("0")
        edit.setValidator(QRegularExpressionValidator(QRegularExpression(r"^\d?$"), edit))
        return edit

    def _split_level_path(self, value: str) -> tuple[str, str, str]:
        parts = [part.strip() for part in str(value or "").split(".")]
        return (
            parts[0][:1] if len(parts) > 0 else "",
            parts[1][:1] if len(parts) > 1 else "",
            parts[2][:1] if len(parts) > 2 else "",
        )

    def _compose_level_path(self) -> str:
        parts = [
            self._level_part_1_edit.text().strip(),
            self._level_part_2_edit.text().strip(),
            self._level_part_3_edit.text().strip(),
        ]
        if not any(parts):
            return ""
        if all(parts):
            return ".".join(parts)
        return ""

    def _current_answer_text(self) -> str:
        answer_mode = self._answer_input_mode(self._type_combo.currentText())
        if answer_mode == "combo":
            return self._answer_combo.currentText().strip()
        if answer_mode == "multi_parts":
            digits = [
                self._circled_to_digit(self._answer_part_1_edit.text()),
                self._circled_to_digit(self._answer_part_2_edit.text()),
                self._circled_to_digit(self._answer_part_3_edit.text()),
                self._circled_to_digit(self._answer_part_4_edit.text()),
            ]
            return ",".join(digit for digit in digits if digit)
        return self._answer_line_edit.text().strip()

    def _set_answer_text(self, value: str, *, mode: str) -> None:
        normalized = (value or "").strip()
        if mode == "combo":
            combo_value = normalized.upper()
            combo_idx = self._answer_combo.findText(combo_value)
            self._answer_combo.setCurrentIndex(combo_idx if combo_idx >= 0 else 0)
            return
        if mode == "multi_parts":
            parts = self._split_multi_answer(normalized)
            self._answer_part_1_edit.setText(parts[0])
            self._answer_part_2_edit.setText(parts[1])
            self._answer_part_3_edit.setText(parts[2])
            self._answer_part_4_edit.setText(parts[3])
            return
        self._answer_line_edit.setText(normalized)

    def _answer_input_mode(self, question_type: str) -> str:
        normalized_type = (question_type or "").strip()
        if normalized_type in ("单选", "可转多选"):
            return "combo"
        if normalized_type == "多选":
            return "multi_parts"
        return "line"

    def _create_answer_part_edit(self, value: str) -> LevelPathPartLineEdit:
        edit = LevelPathPartLineEdit((value or "").strip()[:1])
        edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        edit.setMaxLength(1)
        edit.setFixedWidth(36)
        edit.setPlaceholderText("")
        edit.setValidator(QRegularExpressionValidator(QRegularExpression(r"^[①②③④1-4]?$"), edit))
        edit.textEdited.connect(
            lambda _text, target=edit: target.setText(self._normalize_multi_answer_part(target.text()))
        )
        return edit

    def _split_multi_answer(self, value: str) -> tuple[str, str, str, str]:
        chars = [
            self._normalize_multi_answer_part(ch)
            for ch in str(value or "")
            if self._normalize_multi_answer_part(ch)
        ]
        return (
            chars[0] if len(chars) > 0 else "",
            chars[1] if len(chars) > 1 else "",
            chars[2] if len(chars) > 2 else "",
            chars[3] if len(chars) > 3 else "",
        )

    def _normalize_multi_answer_part(self, value: str) -> str:
        text = (value or "").strip()
        if not text:
            return ""
        return {
            "1": "①",
            "2": "②",
            "3": "③",
            "4": "④",
            "①": "①",
            "②": "②",
            "③": "③",
            "④": "④",
        }.get(text[:1], "")

    def _circled_to_digit(self, value: str) -> str:
        text = (value or "").strip()
        return {
            "①": "1",
            "②": "2",
            "③": "3",
            "④": "4",
            "1": "1",
            "2": "2",
            "3": "3",
            "4": "4",
        }.get(text[:1], "")

    def _collect_textbook_version_options(self, current_value: str) -> list[str]:
        versions: list[str] = []
        seen: set[str] = set()

        def add_version(value: str) -> None:
            normalized = str(value or "").strip()
            if not normalized or normalized in seen:
                return
            seen.add(normalized)
            versions.append(normalized)

        add_version(current_value)
        parent = self.parent()
        current_records = getattr(parent, "_current_db_records", None)
        if isinstance(current_records, list):
            for record in current_records:
                add_version(getattr(record, "textbook_version", ""))
        return versions

    def _ensure_locked_prefix(self, edit: QLineEdit, prefix: str) -> None:
        min_pos = len(prefix)
        normalized_text = self._format_prefixed_display(prefix, self._parse_prefixed_display(prefix, edit.text()))
        if edit.text() != normalized_text:
            current_pos = max(min_pos, edit.cursorPosition())
            edit.setText(normalized_text)
            edit.setCursorPosition(min(current_pos, len(normalized_text)))
            return
        if edit.cursorPosition() < min_pos:
            edit.setCursorPosition(min_pos)

    def _clamp_prefix_cursor(self, edit: QLineEdit, prefix: str, new_position: int) -> None:
        min_pos = len(prefix)
        if new_position < min_pos:
            edit.setCursorPosition(min_pos)

    def _format_prefixed_display(self, prefix: str, value: str) -> str:
        normalized_prefix = str(prefix or "").strip()
        normalized_value = (value or "").strip()
        if not normalized_prefix:
            return normalized_value
        if not normalized_value:
            return normalized_prefix
        if normalized_value.startswith(normalized_prefix):
            return normalized_value
        return f"{normalized_prefix}{normalized_value}"

    def _parse_prefixed_display(self, prefix: str, text: str) -> str:
        normalized_prefix = str(prefix or "").strip()
        normalized_value = (text or "").strip()
        if normalized_prefix and normalized_value.startswith(normalized_prefix):
            return normalized_value[len(normalized_prefix):].strip()
        return normalized_value

    def _on_delete_clicked(self) -> None:
        answer = show_message_box(
            self,
            title="确认删除",
            text="确定删除这道题目吗？此操作不可撤销。",
            icon=QMessageBox.Icon.Warning,
            buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            default_button=QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.done(self.DELETE_RESULT)

    def _sync_choice_fields_visibility(self, question_type: str) -> None:
        normalized_type = (question_type or "").strip()
        current_answer = self._current_answer_text()
        answer_mode = self._answer_input_mode(normalized_type)
        self._answer_stack.setCurrentIndex({"line": 0, "combo": 1, "multi_parts": 2}.get(answer_mode, 0))
        self._set_answer_text(current_answer, mode=answer_mode)
        option_labels = (
            ("①：", "②：", "③：", "④：")
            if normalized_type in ("多选", "可转多选")
            else ("A：", "B：", "C：", "D：")
        )
        for widget, text in (
            (self._option_1_label, option_labels[0]),
            (self._option_2_label, option_labels[1]),
            (self._option_3_label, option_labels[2]),
            (self._option_4_label, option_labels[3]),
        ):
            widget.setText(text)
        visible = normalized_type == "可转多选"
        self._choice_fields_widget.setVisible(visible)
        for widget in (
            self._choice_1_label,
            self._choice_1_edit,
            self._choice_2_label,
            self._choice_2_edit,
            self._choice_3_label,
            self._choice_3_edit,
            self._choice_4_label,
            self._choice_4_edit,
        ):
            widget.setVisible(visible)
