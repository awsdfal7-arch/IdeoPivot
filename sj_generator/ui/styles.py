from __future__ import annotations


APP_STYLESHEET = """
QPushButton {
    border: 1px solid #000000;
    border-radius: 0px;
}

QLineEdit,
QComboBox,
QTextEdit,
QPlainTextEdit,
QAbstractSpinBox {
    border: 1px solid #000000;
    border-radius: 0px;
    background: #ffffff;
}

QToolButton {
    border: 1px solid #000000;
    border-radius: 0px;
}

QPushButton:hover,
QToolButton:hover {
    background: #f2f2f2;
}

QPushButton:pressed,
QToolButton:pressed {
    background: #d9d9d9;
}
""".strip()


def rounded_panel_stylesheet(*, background: str = "#fafafa", border_color: str = "#000000", radius: int = 10) -> str:
    return (
        f"border: 1px solid {border_color}; "
        f"border-radius: {int(radius)}px; "
        f"background: {background};"
    )
