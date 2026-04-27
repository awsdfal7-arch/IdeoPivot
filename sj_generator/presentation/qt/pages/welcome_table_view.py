from __future__ import annotations

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QTableWidget, QWidget

from sj_generator.application.settings import (
    load_welcome_table_column_visibility,
    load_welcome_table_font_point_size,
    save_welcome_table_column_visibility,
    save_welcome_table_font_point_size,
)


def load_column_visibility(column_defs: list[tuple[str, str, bool]]) -> dict[str, bool]:
    saved = load_welcome_table_column_visibility()
    defaults = {key: visible for key, _title, visible in column_defs}
    merged = defaults | {key: value for key, value in saved.items() if key in defaults}
    if not any(merged.values()):
        first_key = column_defs[0][0]
        merged[first_key] = True
    return merged


def save_column_visibility(table: QTableWidget, column_defs: list[tuple[str, str, bool]]) -> None:
    visibility = {
        key: (not table.isColumnHidden(idx))
        for idx, (key, _title, _visible) in enumerate(column_defs)
    }
    save_welcome_table_column_visibility(visibility)


def set_column_visible(
    *,
    table: QTableWidget,
    column_actions: dict[int, QAction | object],
    column_defs: list[tuple[str, str, bool]],
    column: int,
    visible: bool,
    last_column_min_width: int,
    schedule_table_row_resize,
) -> None:
    if visible:
        table.setColumnHidden(column, False)
        save_column_visibility(table, column_defs)
        refresh_table_layout_after_column_change(
            table=table,
            last_column_min_width=last_column_min_width,
            schedule_table_row_resize=schedule_table_row_resize,
        )
        return

    visible_columns = [idx for idx in range(table.columnCount()) if not table.isColumnHidden(idx)]
    if len(visible_columns) <= 1:
        action = column_actions.get(column)
        if action is not None:
            action.blockSignals(True)
            action.setChecked(True)
            action.blockSignals(False)
        return

    table.setColumnHidden(column, True)
    save_column_visibility(table, column_defs)
    refresh_table_layout_after_column_change(
        table=table,
        last_column_min_width=last_column_min_width,
        schedule_table_row_resize=schedule_table_row_resize,
    )


def schedule_table_row_resize(*, row_resize_pending: bool, apply_cb) -> bool:
    if row_resize_pending:
        return row_resize_pending
    QTimer.singleShot(0, apply_cb)
    return True


def apply_table_row_resize(
    *,
    table: QTableWidget,
    row_resize_followup_pending: bool,
    followup_cb,
) -> bool:
    if table.rowCount() == 0:
        return row_resize_followup_pending
    table.doItemsLayout()
    table.resizeRowsToContents()
    if row_resize_followup_pending:
        return row_resize_followup_pending
    QTimer.singleShot(30, followup_cb)
    return True


def apply_table_row_resize_followup(table: QTableWidget) -> None:
    if table.rowCount() == 0:
        return
    table.doItemsLayout()
    table.viewport().update()
    table.resizeRowsToContents()


def refresh_table_layout_after_column_change(
    *,
    table: QTableWidget,
    last_column_min_width: int,
    schedule_table_row_resize,
) -> None:
    rebalance_visible_columns(table, last_column_min_width=last_column_min_width)
    table.doItemsLayout()
    table.viewport().update()
    schedule_table_row_resize()


def rebalance_visible_columns(table: QTableWidget, *, last_column_min_width: int) -> None:
    visible_columns = [idx for idx in range(table.columnCount()) if not table.isColumnHidden(idx)]
    if not visible_columns:
        return
    available_width = max(1, table.viewport().width())
    if len(visible_columns) == 1:
        table.setColumnWidth(visible_columns[0], available_width)
        return
    fixed_columns = visible_columns[:-1]
    reserved_last_width = min(available_width, last_column_min_width)
    distributable_width = max(len(fixed_columns), available_width - reserved_last_width)
    base_width = max(1, distributable_width // len(fixed_columns))
    consumed_width = 0
    for column in fixed_columns:
        table.setColumnWidth(column, base_width)
        consumed_width += base_width
    table.setColumnWidth(visible_columns[-1], max(1, available_width - consumed_width))


def load_table_font_point_size(widget: QWidget, *, min_size: int, max_size: int) -> int:
    saved = load_welcome_table_font_point_size()
    default_size = widget.font().pointSize()
    if default_size <= 0:
        default_size = 10
    if saved is None:
        return default_size
    return max(min_size, min(max_size, saved))


def apply_table_font_size(
    *,
    table: QTableWidget,
    table_placeholder: QWidget,
    font_point_size: int,
    schedule_table_row_resize,
) -> None:
    font = table.font()
    font.setPointSize(font_point_size)
    table.setFont(font)
    table.horizontalHeader().setFont(font)
    table_placeholder.setFont(font)
    table.doItemsLayout()
    table.viewport().update()
    table.horizontalHeader().viewport().update()
    schedule_table_row_resize()


def adjust_table_font_size(current_size: int, step: int, *, min_size: int, max_size: int) -> int:
    return max(min_size, min(max_size, current_size + int(step)))


def persist_table_font_point_size(font_point_size: int) -> None:
    save_welcome_table_font_point_size(font_point_size)
