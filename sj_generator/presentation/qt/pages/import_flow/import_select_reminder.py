from __future__ import annotations

from pathlib import Path

from docx import Document
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import QTableWidget, QTableWidgetItem


def inspect_docx_content(path: Path) -> tuple[bool, bool, str]:
    try:
        doc = Document(str(path))
        has_table = len(doc.tables) > 0
        has_image = len(doc.inline_shapes) > 0
        return has_image, has_table, ""
    except Exception as e:
        return False, False, str(e)


def make_import_check_item(text: str, state: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setTextAlignment(int(Qt.AlignmentFlag.AlignCenter))
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    if state == "found":
        item.setForeground(QBrush(QColor(156, 0, 6)))
        item.setBackground(QBrush(QColor(255, 199, 206)))
    elif state == "clear":
        item.setForeground(QBrush(QColor(0, 97, 0)))
        item.setBackground(QBrush(QColor(198, 239, 206)))
    elif state == "error":
        item.setForeground(QBrush(QColor(156, 0, 6)))
        item.setBackground(QBrush(QColor(255, 235, 156)))
    return item


def populate_import_reminder_columns(
    table: QTableWidget,
    paths: list[Path],
    *,
    image_col: int,
    table_col: int,
) -> None:
    if not paths:
        return

    for row, path in enumerate(paths):
        has_image, has_table, error_text = inspect_docx_content(path)
        if error_text:
            fail_text = f"失败：{error_text}"
            table.setItem(row, image_col, make_import_check_item(fail_text, "error"))
            table.setItem(row, table_col, make_import_check_item(fail_text, "error"))
            continue
        table.setItem(
            row,
            image_col,
            make_import_check_item("发现" if has_image else "未发现", "found" if has_image else "clear"),
        )
        table.setItem(
            row,
            table_col,
            make_import_check_item("发现" if has_table else "未发现", "found" if has_table else "clear"),
        )
    table.resizeRowsToContents()
