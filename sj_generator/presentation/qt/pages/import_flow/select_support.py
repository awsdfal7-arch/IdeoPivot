from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QPushButton, QTableWidget, QTableWidgetItem, QWidget

from sj_generator.application.state import AiSourceFileItem, ImportWizardSession
from .import_page_common import style_dialog_button
from .import_select_reminder import populate_import_reminder_columns
from .import_select_session import select_first_changed_row


def serialize_selected_paths(table: QTableWidget) -> str:
    parts: list[str] = []
    for row in range(table.rowCount()):
        item = table.item(row, 0)
        raw = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if raw:
            parts.append(str(raw))
    return "; ".join(parts)


def rebuild_selected_paths_table(
    *,
    table: QTableWidget,
    state: ImportWizardSession,
    paths: list[Path],
    selected_path: Path | None,
    on_open_row,
    on_remove_row,
) -> None:
    existing_map = {item.path: item for item in state.source.file_items}
    table.blockSignals(True)
    table.setRowCount(0)
    selected_row = 0
    updated_items: list[AiSourceFileItem] = []
    for index, path in enumerate(paths):
        raw_path = str(path)
        existing = existing_map.get(raw_path, AiSourceFileItem(path=raw_path))
        default_version = existing.version or state.preferred_textbook_version
        updated_items.append(
            AiSourceFileItem(path=raw_path, version=default_version, level_path=existing.level_path)
        )
        table.insertRow(index)
        name_item = QTableWidgetItem(path.name)
        name_item.setToolTip(raw_path)
        name_item.setData(Qt.ItemDataRole.UserRole, raw_path)
        name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        version_item = QTableWidgetItem(default_version)
        version_item.setTextAlignment(int(Qt.AlignmentFlag.AlignCenter))
        level_item = QTableWidgetItem(existing.level_path)
        level_item.setTextAlignment(int(Qt.AlignmentFlag.AlignCenter))
        image_item = QTableWidgetItem("")
        image_item.setFlags(image_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        image_item.setTextAlignment(int(Qt.AlignmentFlag.AlignCenter))
        table_item = QTableWidgetItem("")
        table_item.setFlags(table_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        table_item.setTextAlignment(int(Qt.AlignmentFlag.AlignCenter))
        open_button = QPushButton("打开并编辑")
        style_dialog_button(open_button)
        remove_button = QPushButton("移除")
        style_dialog_button(remove_button)
        open_button.clicked.connect(lambda _checked=False, row_index=index: on_open_row(row_index))
        remove_button.clicked.connect(lambda _checked=False, row_index=index: on_remove_row(row_index))
        action_layout = QHBoxLayout()
        action_layout.setContentsMargins(4, 2, 4, 2)
        action_layout.setSpacing(6)
        action_layout.addWidget(open_button)
        action_layout.addWidget(remove_button)
        action_widget = QWidget(table)
        action_widget.setLayout(action_layout)
        table.setItem(index, 0, name_item)
        table.setItem(index, 1, version_item)
        table.setItem(index, 2, level_item)
        table.setItem(index, 3, image_item)
        table.setItem(index, 4, table_item)
        table.setCellWidget(index, 5, action_widget)
        if selected_path is not None and path == selected_path:
            selected_row = index
    state.source.file_items = updated_items
    table.blockSignals(False)
    if table.rowCount() > 0:
        table.selectRow(selected_row)


def collect_table_items(table: QTableWidget, preferred_textbook_version: str) -> list[AiSourceFileItem]:
    items: list[AiSourceFileItem] = []
    for row in range(table.rowCount()):
        name_item = table.item(row, 0)
        if name_item is None:
            continue
        raw_path = str(name_item.data(Qt.ItemDataRole.UserRole) or "").strip()
        if not raw_path:
            continue
        version = (
            (table.item(row, 1).text() if table.item(row, 1) else "").strip() or preferred_textbook_version
        )
        level_path = (table.item(row, 2).text() if table.item(row, 2) else "").strip()
        items.append(AiSourceFileItem(path=raw_path, version=version, level_path=level_path))
    return items


def find_invalid_level_paths(table: QTableWidget, is_valid_level_path) -> list[str]:
    invalid_names: list[str] = []
    for row in range(table.rowCount()):
        name_item = table.item(row, 0)
        level_item = table.item(row, 2)
        if name_item is None or level_item is None:
            continue
        level_path = level_item.text().strip()
        if level_path and not is_valid_level_path(level_path):
            invalid_names.append(name_item.text().strip() or f"第{row + 1}行")
    return invalid_names


def build_split_import_states_for_paths(
    *,
    base_state: ImportWizardSession,
    paths: list[Path],
    items: list[AiSourceFileItem],
    rename_project,
) -> list[ImportWizardSession]:
    item_map = {item.path: item for item in items if str(item.path or "").strip()}
    split_states: list[ImportWizardSession] = []
    for path in paths:
        raw_path = str(path)
        source_item = item_map.get(raw_path, AiSourceFileItem(path=raw_path, version=base_state.preferred_textbook_version))
        child_state = base_state.build_import_session(
            source_files=[path],
            source_items=[source_item],
            import_level_path=source_item.level_path,
        )
        child_state.preferred_textbook_version = source_item.version or base_state.preferred_textbook_version
        if child_state.project_name_is_placeholder and child_state.project_dir is not None:
            rename_project(child_state, new_name=path.stem)
        split_states.append(child_state)
    return split_states


def update_import_reminder(table: QTableWidget, paths: list[Path], *, image_col: int, table_col: int) -> None:
    table.blockSignals(True)
    populate_import_reminder_columns(table, paths, image_col=image_col, table_col=table_col)
    table.blockSignals(False)


def reminder_doc_path(table: QTableWidget, row: int) -> Path | None:
    if row < 0 or row >= table.rowCount():
        return None
    item = table.item(row, 0)
    if item is None:
        return None
    raw = item.data(Qt.ItemDataRole.UserRole)
    if not raw:
        return None
    return Path(str(raw))


def remove_file_row(table: QTableWidget, row: int) -> tuple[list[Path], Path | None]:
    if row < 0 or row >= table.rowCount():
        return [], None
    remaining_paths: list[Path] = []
    removed_path: Path | None = None
    for row_index in range(table.rowCount()):
        item = table.item(row_index, 0)
        if item is None:
            continue
        raw = item.data(Qt.ItemDataRole.UserRole)
        if not raw:
            continue
        path = Path(str(raw))
        if row_index == row:
            removed_path = path
            continue
        remaining_paths.append(path)
    return remaining_paths, removed_path


def refresh_after_external_doc_edit(
    *,
    table: QTableWidget,
    items: list[AiSourceFileItem],
    changed_paths: list[Path],
    image_col: int,
    table_col: int,
) -> None:
    paths = [Path(item.path) for item in items]
    update_import_reminder(table, paths, image_col=image_col, table_col=table_col)
    select_first_changed_row(table, changed_paths)
