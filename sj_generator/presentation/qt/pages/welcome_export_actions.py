from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QFileDialog, QMessageBox, QTreeWidgetItem, QWidget

from sj_generator.application.state import WizardState
from sj_generator.infrastructure.persistence.sqlite_repo import DbQuestionRecord, load_all_questions
from sj_generator.presentation.qt.message_box import show_message_box
from sj_generator.presentation.qt.pages.welcome_export import (
    default_export_dir,
    display_export_level_name,
    export_current_level_to_markdown,
    export_current_level_to_pdf,
    export_db_records_to_xlsx,
    sanitize_export_name,
)


def selected_tree_level_path(current: QTreeWidgetItem | None, role_level_path: int) -> str:
    if current is None:
        return ""
    return str(current.data(0, role_level_path) or "").strip()


def export_current_level_markdown(
    *,
    parent: QWidget,
    current_item: QTreeWidgetItem | None,
    current_records: list[DbQuestionRecord],
    db_path: Path,
    state: WizardState,
    role_level_path: int,
) -> Path | None:
    if not current_records:
        show_message_box(parent, title="无法导出", text="当前页面没有可导出的题目。", icon=QMessageBox.Icon.Warning)
        return None
    level_path = selected_tree_level_path(current_item, role_level_path)
    if not level_path:
        show_message_box(parent, title="无法导出", text="请先选择要导出的层级。", icon=QMessageBox.Icon.Warning)
        return None
    safe_level_name = sanitize_export_name(display_export_level_name(level_path))
    suggested = str(db_path.parent / f"{safe_level_name}.md")
    file_path, _ = QFileDialog.getSaveFileName(parent, "导出 Markdown", suggested, "Markdown (*.md)")
    if not file_path:
        return None
    target_path = Path(file_path)
    try:
        export_current_level_to_markdown(
            records=list(current_records),
            level_path=level_path,
            target_path=target_path,
            convertible_multi_mode=state.export_convertible_multi_mode,
            include_answers=state.export_include_answers,
            include_analysis=state.export_include_analysis,
        )
    except Exception as exc:
        show_message_box(parent, title="导出失败", text=f"写入 Markdown 失败：{exc}", icon=QMessageBox.Icon.Critical)
        return None
    return target_path


def export_current_level_pdf(
    *,
    parent: QWidget,
    current_item: QTreeWidgetItem | None,
    current_records: list[DbQuestionRecord],
    db_path: Path,
    state: WizardState,
    role_level_path: int,
) -> Path | None:
    if not current_records:
        show_message_box(parent, title="无法导出", text="当前页面没有可导出的题目。", icon=QMessageBox.Icon.Warning)
        return None
    level_path = selected_tree_level_path(current_item, role_level_path)
    if not level_path:
        show_message_box(parent, title="无法导出", text="请先选择要导出的层级。", icon=QMessageBox.Icon.Warning)
        return None
    safe_level_name = sanitize_export_name(display_export_level_name(level_path))
    suggested = str(default_export_dir(state.last_export_dir, db_path) / f"{safe_level_name}.pdf")
    file_path, _ = QFileDialog.getSaveFileName(parent, "导出 PDF", suggested, "PDF (*.pdf)")
    if not file_path:
        return None
    target_path = Path(file_path)
    try:
        export_current_level_to_pdf(
            records=list(current_records),
            level_path=level_path,
            target_path=target_path,
            convertible_multi_mode=state.export_convertible_multi_mode,
            include_answers=state.export_include_answers,
            include_analysis=state.export_include_analysis,
        )
    except Exception as exc:
        show_message_box(parent, title="导出失败", text=f"写入 PDF 失败：{exc}", icon=QMessageBox.Icon.Critical)
        return None
    return target_path


def export_current_level_xlsx(
    *,
    parent: QWidget,
    current_item: QTreeWidgetItem | None,
    current_records: list[DbQuestionRecord],
    db_path: Path,
    state: WizardState,
    role_level_path: int,
) -> Path | None:
    if not current_records:
        show_message_box(parent, title="无法导出", text="当前页面没有可导出的题目。", icon=QMessageBox.Icon.Warning)
        return None
    level_path = selected_tree_level_path(current_item, role_level_path)
    if not level_path:
        show_message_box(parent, title="无法导出", text="请先选择要导出的层级。", icon=QMessageBox.Icon.Warning)
        return None
    safe_level_name = sanitize_export_name(display_export_level_name(level_path))
    suggested = str(default_export_dir(state.last_export_dir, db_path) / f"{safe_level_name}.xlsx")
    file_path, _ = QFileDialog.getSaveFileName(parent, "导出当前页面 xlsx", suggested, "Excel (*.xlsx)")
    if not file_path:
        return None
    target_path = Path(file_path)
    try:
        export_db_records_to_xlsx(records=list(current_records), target_path=target_path)
    except Exception as exc:
        show_message_box(parent, title="导出失败", text=f"写入 xlsx 失败：{exc}", icon=QMessageBox.Icon.Critical)
        return None
    return target_path


def export_db_table_xlsx(*, parent: QWidget, db_path: Path, last_export_dir: Path | None) -> Path | None:
    if not db_path.exists():
        show_message_box(parent, title="无法导出", text="当前数据库文件不存在。", icon=QMessageBox.Icon.Warning)
        return None
    records = load_all_questions(db_path)
    if not records:
        show_message_box(parent, title="无法导出", text="当前数据库表没有可导出的题目。", icon=QMessageBox.Icon.Warning)
        return None
    suggested_name = f"{sanitize_export_name(db_path.stem)}_整体数据库表.xlsx"
    suggested = str(default_export_dir(last_export_dir, db_path) / suggested_name)
    file_path, _ = QFileDialog.getSaveFileName(parent, "导出整体数据库表 xlsx", suggested, "Excel (*.xlsx)")
    if not file_path:
        return None
    target_path = Path(file_path)
    try:
        export_db_records_to_xlsx(records=records, target_path=target_path)
    except Exception as exc:
        show_message_box(parent, title="导出失败", text=f"写入 xlsx 失败：{exc}", icon=QMessageBox.Icon.Critical)
        return None
    return target_path
