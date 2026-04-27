from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QLineEdit,
    QVBoxLayout,
)

from sj_generator.application.settings import save_program_settings_merged
from sj_generator.application.state import (
    WizardState,
    normalize_export_convertible_multi_mode,
    normalize_export_include_answers,
    normalize_export_include_analysis,
    normalize_default_repo_parent_dir_text,
    normalize_import_source_dir_text,
    normalize_analysis_model_name,
    normalize_analysis_provider,
    normalize_preferred_textbook_version,
    library_db_path_from_repo_parent_dir_text,
    default_import_source_dir,
    desktop_import_source_dir,
)
from sj_generator.infrastructure.persistence.sqlite_repo import load_all_questions
SECTION_GENERAL = "general"
SECTION_IMPORT = "import"
SECTION_EXPORT = "export"
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


class ProgramSettingsDialog(QDialog):
    def __init__(self, state: WizardState, parent=None, *, section: str = SECTION_GENERAL) -> None:
        super().__init__(parent)
        self._state = state
        self._section = section if section in {SECTION_GENERAL, SECTION_IMPORT, SECTION_EXPORT} else SECTION_GENERAL
        self.setWindowTitle(self._dialog_title())
        self.resize(500, 260)

        self._dedupe_checkbox = QCheckBox("导入流程默认执行库内查重")
        self._dedupe_checkbox.setChecked(bool(self._state.dedupe_enabled))

        self._import_analysis_combo = QComboBox()
        self._import_analysis_combo.addItem("自动生成", True)
        self._import_analysis_combo.addItem("不生成", False)
        analysis_idx = self._import_analysis_combo.findData(bool(self._state.analysis_enabled))
        if analysis_idx >= 0:
            self._import_analysis_combo.setCurrentIndex(analysis_idx)

        self._convertible_multi_export_combo = QComboBox()
        self._convertible_multi_export_combo.addItem("保留组合映射", "keep_combo")
        self._convertible_multi_export_combo.addItem("按新多选输出", "as_multi")
        export_idx = self._convertible_multi_export_combo.findData(
            normalize_export_convertible_multi_mode(self._state.export_convertible_multi_mode)
        )
        if export_idx >= 0:
            self._convertible_multi_export_combo.setCurrentIndex(export_idx)
        self._export_include_answers_checkbox = QCheckBox("包含答案")
        self._export_include_answers_checkbox.setChecked(
            normalize_export_include_answers(self._state.export_include_answers)
        )
        self._export_include_analysis_checkbox = QCheckBox("包含解析")
        self._export_include_analysis_checkbox.setChecked(
            normalize_export_include_analysis(self._state.export_include_analysis)
        )

        self._default_repo_parent_dir_edit = QLineEdit()
        self._default_repo_parent_dir_edit.setText(
            normalize_default_repo_parent_dir_text(self._state.default_repo_parent_dir_text)
        )
        self._default_repo_parent_dir_edit.setPlaceholderText("例如：C:/Users/你的用户名/Desktop/思政题库")
        self._default_repo_parent_dir_browse_btn = QPushButton("选择…")
        self._default_repo_parent_dir_browse_btn.setMinimumSize(BUTTON_MIN_WIDTH, BUTTON_MIN_HEIGHT)
        self._default_repo_parent_dir_browse_btn.clicked.connect(self._browse_default_repo_parent_dir)
        self._preferred_textbook_version_combo = QComboBox()
        self._preferred_textbook_version_combo.setEditable(True)
        self._preferred_textbook_version_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        for version in self._collect_textbook_version_options():
            self._preferred_textbook_version_combo.addItem(version)
        self._preferred_textbook_version_combo.setCurrentText(
            normalize_preferred_textbook_version(self._state.preferred_textbook_version)
        )
        self._import_source_dir_preset_combo = QComboBox()
        self._import_source_dir_preset_combo.addItem("下载", "downloads")
        self._import_source_dir_preset_combo.addItem("桌面", "desktop")
        self._import_source_dir_preset_combo.addItem("自定义", "custom")
        self._import_source_dir_edit = QLineEdit()
        self._import_source_dir_edit.setText(
            normalize_import_source_dir_text(self._state.import_source_dir_text)
        )
        self._import_source_dir_edit.setPlaceholderText("例如：C:/Users/你的用户名/Downloads")
        self._import_source_dir_browse_btn = QPushButton("选择…")
        self._import_source_dir_browse_btn.setMinimumSize(BUTTON_MIN_WIDTH, BUTTON_MIN_HEIGHT)
        self._import_source_dir_browse_btn.clicked.connect(self._browse_import_source_dir)
        self._apply_import_source_dir_preset_from_text(self._import_source_dir_edit.text())

        default_repo_row = QHBoxLayout()
        default_repo_row.addWidget(self._default_repo_parent_dir_edit, 1)
        default_repo_row.addWidget(self._default_repo_parent_dir_browse_btn)
        import_source_dir_row = QHBoxLayout()
        import_source_dir_row.addWidget(self._import_source_dir_preset_combo)
        import_source_dir_row.addWidget(self._import_source_dir_edit, 1)
        import_source_dir_row.addWidget(self._import_source_dir_browse_btn)

        form = QFormLayout()
        if self._section == SECTION_GENERAL:
            form.addRow("默认题库保存位置：", default_repo_row)
            form.addRow("题目版本首选项：", self._preferred_textbook_version_combo)
        elif self._section == SECTION_IMPORT:
            form.addRow("默认导入目录：", import_source_dir_row)
            form.addRow("导入文档时解析生成：", self._import_analysis_combo)
            form.addRow("", self._dedupe_checkbox)
        else:
            form.addRow("可转多选 Markdown 导出：", self._convertible_multi_export_combo)
            form.addRow("导出 Markdown/PDF：", self._export_include_answers_checkbox)
            form.addRow("", self._export_include_analysis_checkbox)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        self._buttons = buttons
        _style_dialog_button(buttons.button(QDialogButtonBox.StandardButton.Ok), "确定")
        _style_dialog_button(buttons.button(QDialogButtonBox.StandardButton.Cancel), "取消")

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.setLayout(layout)

        self._import_source_dir_preset_combo.currentIndexChanged.connect(self._on_import_source_dir_preset_changed)
        self._import_source_dir_edit.textChanged.connect(self._on_import_source_dir_text_changed)
    
    def _on_accept(self) -> None:
        if self._section == SECTION_GENERAL:
            self._state.default_repo_parent_dir_text = normalize_default_repo_parent_dir_text(
                self._default_repo_parent_dir_edit.text()
            )
            self._state.preferred_textbook_version = normalize_preferred_textbook_version(
                self._preferred_textbook_version_combo.currentText()
            )
        elif self._section == SECTION_IMPORT:
            self._state.import_source_dir_text = normalize_import_source_dir_text(self._import_source_dir_edit.text())
            self._state.analysis_enabled = bool(self._import_analysis_combo.currentData())
            self._state.dedupe_enabled = self._dedupe_checkbox.isChecked()
        else:
            self._state.export_convertible_multi_mode = normalize_export_convertible_multi_mode(
                self._convertible_multi_export_combo.currentData()
            )
            self._state.export_include_answers = normalize_export_include_answers(
                self._export_include_answers_checkbox.isChecked()
            )
            self._state.export_include_analysis = normalize_export_include_analysis(
                self._export_include_analysis_checkbox.isChecked()
            )
        self._save_program_settings()
        self.accept()

    def _dialog_title(self) -> str:
        if self._section == SECTION_IMPORT:
            return "导入设定"
        if self._section == SECTION_EXPORT:
            return "导出设定"
        return "常规设定"

    def _save_program_settings(self) -> None:
        save_program_settings_merged(
            {
                "default_repo_parent_dir_text": normalize_default_repo_parent_dir_text(
                    self._state.default_repo_parent_dir_text
                ),
                "import_source_dir_text": normalize_import_source_dir_text(
                    self._state.import_source_dir_text
                ),
                "analysis_enabled": bool(self._state.analysis_enabled),
                "dedupe_enabled": bool(self._state.dedupe_enabled),
                "analysis_provider": normalize_analysis_provider(self._state.analysis_provider),
                "analysis_model_name": normalize_analysis_model_name(self._state.analysis_model_name),
                "export_convertible_multi_mode": normalize_export_convertible_multi_mode(
                    self._state.export_convertible_multi_mode
                ),
                "export_include_answers": normalize_export_include_answers(self._state.export_include_answers),
                "export_include_analysis": normalize_export_include_analysis(self._state.export_include_analysis),
                "preferred_textbook_version": normalize_preferred_textbook_version(
                    self._state.preferred_textbook_version
                ),
            }
        )

    def _collect_textbook_version_options(self) -> list[str]:
        versions: list[str] = []
        seen: set[str] = set()

        def add_version(value: str) -> None:
            normalized = str(value or "").strip()
            if not normalized or normalized in seen:
                return
            seen.add(normalized)
            versions.append(normalized)

        add_version(self._state.preferred_textbook_version)
        db_path = library_db_path_from_repo_parent_dir_text(self._state.default_repo_parent_dir_text)
        if db_path.exists():
            for record in load_all_questions(db_path):
                add_version(record.textbook_version)
        return versions

    def _browse_default_repo_parent_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "选择默认题库保存位置",
            normalize_default_repo_parent_dir_text(self._default_repo_parent_dir_edit.text()),
        )
        if folder:
            self._default_repo_parent_dir_edit.setText(folder)

    def _import_source_dir_for_preset(self, preset: str) -> str:
        if preset == "desktop":
            return str(desktop_import_source_dir())
        return str(default_import_source_dir())

    def _apply_import_source_dir_preset_from_text(self, text: str) -> None:
        normalized = str(Path(normalize_import_source_dir_text(text))).strip().lower()
        downloads = str(default_import_source_dir()).strip().lower()
        desktop = str(desktop_import_source_dir()).strip().lower()
        if normalized == downloads:
            preset = "downloads"
        elif normalized == desktop:
            preset = "desktop"
        else:
            preset = "custom"
        index = self._import_source_dir_preset_combo.findData(preset)
        if index >= 0:
            self._import_source_dir_preset_combo.blockSignals(True)
            self._import_source_dir_preset_combo.setCurrentIndex(index)
            self._import_source_dir_preset_combo.blockSignals(False)

    def _on_import_source_dir_preset_changed(self) -> None:
        preset = str(self._import_source_dir_preset_combo.currentData() or "downloads")
        if preset == "custom":
            return
        self._import_source_dir_edit.setText(self._import_source_dir_for_preset(preset))

    def _on_import_source_dir_text_changed(self, text: str) -> None:
        self._apply_import_source_dir_preset_from_text(text)

    def _browse_import_source_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "选择默认导入目录",
            normalize_import_source_dir_text(self._import_source_dir_edit.text()),
        )
        if not folder:
            return
        self._import_source_dir_edit.setText(folder)
        self._apply_import_source_dir_preset_from_text(folder)
