from __future__ import annotations

import re

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QGuiApplication, QKeySequence, QWheelEvent
from PyQt6.QtWidgets import (
    QApplication,
    QAbstractButton,
    QComboBox,
    QFrame,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetSelectionRange,
    QTextEdit,
    QWidget,
)

_INLINE_WHITESPACE_RE = re.compile(r"[\t\r\n]+")


def _normalize_copy_text(value: object) -> str:
    text = str(value or "")
    text = _INLINE_WHITESPACE_RE.sub(" ", text)
    return text.strip()


def _widget_belongs_to_table(widget: QWidget | None, table: QTableWidget) -> bool:
    current = widget
    while current is not None:
        if current is table:
            return True
        current = current.parentWidget()
    return False


def _copy_focused_text_widget(table: QTableWidget) -> bool:
    widget = QApplication.focusWidget()
    if not isinstance(widget, QWidget) or not _widget_belongs_to_table(widget, table):
        return False
    if isinstance(widget, QLineEdit):
        if widget.hasSelectedText():
            widget.copy()
            return True
        return False
    if isinstance(widget, (QTextEdit, QPlainTextEdit)):
        if widget.textCursor().hasSelection():
            widget.copy()
            return True
        return False
    return False


def _table_cell_widget_text(widget: QWidget | None) -> str:
    if widget is None:
        return ""
    if isinstance(widget, QComboBox):
        return widget.currentText()
    if isinstance(widget, (QLabel, QLineEdit)):
        return widget.text()
    if isinstance(widget, (QTextEdit, QPlainTextEdit)):
        return widget.toPlainText()
    if isinstance(widget, QAbstractButton):
        return widget.text()
    text_attr = getattr(widget, "text", None)
    if callable(text_attr):
        try:
            return str(text_attr())
        except Exception:
            return ""
    return ""


def table_cell_text(table: QTableWidget, row: int, col: int) -> str:
    item = table.item(row, col)
    if item is not None:
        display_value = item.data(Qt.ItemDataRole.DisplayRole)
        if display_value is not None:
            return _normalize_copy_text(display_value)
        return _normalize_copy_text(item.text())
    return _normalize_copy_text(_table_cell_widget_text(table.cellWidget(row, col)))


def selected_table_as_tsv(table: QTableWidget, *, fallback_to_all: bool = True) -> str:
    ranges = sorted(table.selectedRanges(), key=lambda rng: (rng.topRow(), rng.leftColumn()))
    if not ranges and fallback_to_all and table.rowCount() > 0 and table.columnCount() > 0:
        ranges = [QTableWidgetSelectionRange(0, 0, table.rowCount() - 1, table.columnCount() - 1)]
    if not ranges:
        return ""

    blocks: list[str] = []
    for selected_range in ranges:
        top_row = selected_range.topRow()
        bottom_row = selected_range.bottomRow()
        left_col = selected_range.leftColumn()
        right_col = selected_range.rightColumn()
        rows: list[str] = []
        for row in range(top_row, bottom_row + 1):
            if table.isRowHidden(row):
                continue
            cells = [
                table_cell_text(table, row, col)
                for col in range(left_col, right_col + 1)
                if not table.isColumnHidden(col)
            ]
            if cells:
                rows.append("\t".join(cells))
        if rows:
            blocks.append("\n".join(rows))
    return "\n".join(blocks)


def copy_table_as_tsv(table: QTableWidget, *, fallback_to_all: bool = True) -> bool:
    if _copy_focused_text_widget(table):
        return True
    text = selected_table_as_tsv(table, fallback_to_all=fallback_to_all)
    if not text:
        return False
    QGuiApplication.clipboard().setText(text)
    return True


class CopyableTableWidget(QTableWidget):
    def __init__(self, *args, fallback_copy_all: bool = True, zoom_callback=None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._fallback_copy_all = fallback_copy_all
        self._zoom_callback = zoom_callback
        self.setShowGrid(True)
        self.setFrameShape(QFrame.Shape.Box)
        self.setFrameShadow(QFrame.Shadow.Plain)
        self.setLineWidth(1)
        self.setMidLineWidth(0)
        copy_action = QAction("复制表格文本", self)
        copy_action.setShortcut(QKeySequence.StandardKey.Copy)
        copy_action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        copy_action.triggered.connect(self.copy_selection_as_tsv)
        self.addAction(copy_action)
        self._copy_action = copy_action

    def copy_selection_as_tsv(self) -> bool:
        return copy_table_as_tsv(self, fallback_to_all=self._fallback_copy_all)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if self._zoom_callback is not None:
                delta = event.angleDelta().y()
                if delta != 0:
                    self._zoom_callback(1 if delta > 0 else -1)
                    event.accept()
                    return
        super().wheelEvent(event)
