from __future__ import annotations

from PyQt6.QtWidgets import QMessageBox, QWidget

MESSAGE_BOX_BUTTON_MIN_WIDTH = 96
MESSAGE_BOX_BUTTON_MIN_HEIGHT = 36


def style_message_box_buttons(box: QMessageBox) -> None:
    for button_type, text in (
        (QMessageBox.StandardButton.Ok, "确定"),
        (QMessageBox.StandardButton.Cancel, "取消"),
        (QMessageBox.StandardButton.Yes, "是"),
        (QMessageBox.StandardButton.No, "否"),
    ):
        button = box.button(button_type)
        if button is None:
            continue
        button.setText(text)
        button.setMinimumSize(MESSAGE_BOX_BUTTON_MIN_WIDTH, MESSAGE_BOX_BUTTON_MIN_HEIGHT)


def show_message_box(
    parent: QWidget | None,
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
    style_message_box_buttons(box)
    return QMessageBox.StandardButton(box.exec())
