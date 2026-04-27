from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidgetItem,
    QVBoxLayout,
)

from sj_generator.application.settings.import_cost_history import clear_import_cost_history, load_import_cost_history_rows
from sj_generator.presentation.qt.table_copy import CopyableTableWidget

BUTTON_MIN_WIDTH = 96
BUTTON_MIN_HEIGHT = 36


def _style_dialog_button(button, text: str | None = None) -> None:
    if button is None:
        return
    if text:
        button.setText(text)
    button.setMinimumSize(BUTTON_MIN_WIDTH, BUTTON_MIN_HEIGHT)


def _style_message_box_buttons(box: QMessageBox) -> None:
    for button_type, text in (
        (QMessageBox.StandardButton.Yes, "是"),
        (QMessageBox.StandardButton.No, "否"),
        (QMessageBox.StandardButton.Ok, "确定"),
        (QMessageBox.StandardButton.Cancel, "取消"),
    ):
        _style_dialog_button(box.button(button_type), text)


class ImportCostHistoryDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("余额日志")
        self.resize(760, 420)

        self._hint = QLabel("")
        self._hint.setWordWrap(True)

        self._table = CopyableTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["运行日期时间", "DeepSeek", "Kimi", "千问"])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(CopyableTableWidget.EditTrigger.NoEditTriggers)
        self._table.setWordWrap(True)

        self._clear_btn = QPushButton("清空日志")
        self._clear_btn.clicked.connect(self._on_clear_logs)
        _style_dialog_button(self._clear_btn, "清空日志")

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        _style_dialog_button(buttons.button(QDialogButtonBox.StandardButton.Close), "关闭")

        layout = QVBoxLayout()
        layout.addWidget(self._hint)
        layout.addWidget(self._table, 1)
        button_row = QHBoxLayout()
        button_row.addWidget(self._clear_btn)
        button_row.addStretch(1)
        button_row.addWidget(buttons)
        layout.addLayout(button_row)
        self.setLayout(layout)

        self._reload_rows()

    def _on_clear_logs(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("确认清空")
        box.setText("确定要清空全部余额日志吗？")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        _style_message_box_buttons(box)
        if box.exec() != QMessageBox.StandardButton.Yes:
            return
        clear_import_cost_history()
        self._reload_rows()

    def _reload_rows(self) -> None:
        rows = load_import_cost_history_rows(limit=200)
        if not rows:
            self._hint.setText("当前还没有余额记录。")
            self._table.setRowCount(0)
            return
        self._hint.setText(f"共 {len(rows)} 条余额记录。")
        self._table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = [
                str(row.get("run_at") or ""),
                str(row.get("deepseek_balance") or ""),
                str(row.get("kimi_balance") or ""),
                str(row.get("qwen_balance") or ""),
            ]
            for col_index, value in enumerate(values):
                item = self._table.item(row_index, col_index)
                if item is None:
                    item = QTableWidgetItem()
                    self._table.setItem(row_index, col_index, item)
                item.setText(value)
                alignment = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
                item.setTextAlignment(int(alignment))
        self._table.resizeRowsToContents()
