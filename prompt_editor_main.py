from __future__ import annotations

import sys

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from sj_generator.ai.prompt_templates import (
    PROMPT_FIELDS,
    default_import_prompts,
    import_prompt_config_path,
    load_import_prompts,
    save_import_prompts,
)


class PromptEditorWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("思政智题云枢 - 提示词编辑器")
        self.resize(1200, 860)

        self._status_label = QLabel("尚未加载")
        self._status_label.setWordWrap(True)
        self._path_label = QLabel(f"配置文件：{import_prompt_config_path()}")
        self._path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._placeholder_label = QLabel(
            "支持占位符：{{source_name}}、{{chunk_text}}、{{requested_number}}。"
        )
        self._placeholder_label.setWordWrap(True)

        self._tab_widget = QTabWidget()
        self._editors: dict[str, QPlainTextEdit] = {}
        for field in PROMPT_FIELDS:
            self._tab_widget.addTab(self._build_tab(field), field.title)

        self._reload_btn = QPushButton("重新加载")
        self._reload_btn.clicked.connect(self._load_prompts)

        self._reset_btn = QPushButton("恢复默认")
        self._reset_btn.clicked.connect(self._reset_to_defaults)

        self._save_btn = QPushButton("保存")
        self._save_btn.clicked.connect(self._save_prompts)

        button_row = QHBoxLayout()
        button_row.addWidget(self._reload_btn)
        button_row.addWidget(self._reset_btn)
        button_row.addStretch(1)
        button_row.addWidget(self._save_btn)

        layout = QVBoxLayout()
        layout.addWidget(QLabel("主导入流程提示词编辑"))
        layout.addWidget(self._path_label)
        layout.addWidget(self._placeholder_label)
        layout.addWidget(self._tab_widget, 1)
        layout.addLayout(button_row)
        layout.addWidget(self._status_label)
        self.setLayout(layout)

        self._load_prompts()

    def _build_tab(self, field) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout()
        desc = QLabel(field.description)
        desc.setWordWrap(True)
        if field.placeholders:
            tips = QLabel("可用占位符：" + "、".join(field.placeholders))
        else:
            tips = QLabel("此项通常不需要占位符。")
        tips.setWordWrap(True)
        editor = QPlainTextEdit()
        editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._editors[field.key] = editor
        layout.addWidget(desc)
        layout.addWidget(tips)
        layout.addWidget(editor, 1)
        page.setLayout(layout)
        return page

    def _load_prompts(self) -> None:
        prompts = load_import_prompts(force_reload=True)
        for field in PROMPT_FIELDS:
            editor = self._editors[field.key]
            editor.setPlainText(prompts.get(field.key, ""))
        self._status_label.setText("已加载当前提示词配置。")

    def _reset_to_defaults(self) -> None:
        answer = QMessageBox.question(
            self,
            "恢复默认",
            "确定要将编辑器内容恢复为默认提示词吗？当前未保存的修改会丢失。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        prompts = default_import_prompts()
        for field in PROMPT_FIELDS:
            self._editors[field.key].setPlainText(prompts.get(field.key, ""))
        self._status_label.setText("已恢复为默认提示词，尚未保存到配置文件。")

    def _save_prompts(self) -> None:
        prompts: dict[str, str] = {}
        for field in PROMPT_FIELDS:
            prompts[field.key] = self._editors[field.key].toPlainText()
        try:
            save_import_prompts(prompts)
        except Exception as exc:
            QMessageBox.warning(self, "保存失败", f"无法保存提示词配置：{exc}")
            return
        self._path_label.setText(f"配置文件：{import_prompt_config_path()}")
        self._status_label.setText("已保存。主导入流程后续发起的新请求会使用当前提示词。")


def main() -> None:
    app = QApplication(sys.argv)
    window = PromptEditorWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
