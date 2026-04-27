from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtWidgets import QFileDialog, QMessageBox, QWidget

from sj_generator.application.state import WizardState
from sj_generator.infrastructure.persistence.excel_repo import load_db_question_records
from sj_generator.infrastructure.persistence.sqlite_repo import append_questions
from sj_generator.presentation.qt.api_config_dialog import ApiConfigDialog
from sj_generator.presentation.qt.message_box import show_message_box
from sj_generator.presentation.qt.program_settings_dialog import ProgramSettingsDialog


def open_api_config(parent: QWidget, state: WizardState) -> None:
    dlg = ApiConfigDialog(parent, state=state)
    dlg.exec()


def open_program_settings(parent: QWidget, state: WizardState, *, section: str) -> bool:
    dlg = ProgramSettingsDialog(state, parent, section=section)
    return bool(dlg.exec())


@dataclass
class TableImportResult:
    count: int
    preferred_level_path: str


def import_from_table_file(parent: QWidget, db_path: Path) -> TableImportResult | None:
    file_path, _ = QFileDialog.getOpenFileName(parent, "选择表格文件", "", "Excel (*.xlsx);;All Files (*)")
    if not file_path:
        return None
    path = Path(file_path)
    try:
        records = load_db_question_records(path)
    except Exception as exc:
        show_message_box(parent, title="导入失败", text=f"读取表格文件失败：{exc}", icon=QMessageBox.Icon.Critical)
        return None
    if not records:
        show_message_box(parent, title="无法导入", text="当前 xlsx 中没有可写入数据库的记录。", icon=QMessageBox.Icon.Warning)
        return None
    try:
        append_questions(db_path, records)
    except Exception as exc:
        show_message_box(parent, title="导入失败", text=f"写入数据库失败：{exc}", icon=QMessageBox.Icon.Critical)
        return None
    preferred_level_path = next((record.level_path for record in records if record.level_path.strip()), "")
    show_message_box(parent, title="导入完成", text=f"已从数据库字段表 xlsx 导入 {len(records)} 道题。", icon=QMessageBox.Icon.Information)
    return TableImportResult(count=len(records), preferred_level_path=preferred_level_path)
