from __future__ import annotations

from html import escape
from pathlib import Path
import random

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

from sj_generator.shared.paths import app_paths
from sj_generator.presentation.qt.constants import PAGE_WELCOME
from sj_generator.presentation.qt.styles import rounded_panel_stylesheet

_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")
BUTTON_MIN_WIDTH = 96
BUTTON_MIN_HEIGHT = 36


def _style_dialog_button(button: QPushButton | None, text: str | None = None) -> None:
    if button is None:
        return
    if text:
        button.setText(text)
    button.setMinimumSize(BUTTON_MIN_WIDTH, BUTTON_MIN_HEIGHT)


def _style_message_box_buttons(box: QMessageBox) -> None:
    for button_type, text in (
        (QMessageBox.StandardButton.Ok, "确定"),
        (QMessageBox.StandardButton.Cancel, "取消"),
        (QMessageBox.StandardButton.Yes, "是"),
        (QMessageBox.StandardButton.No, "否"),
    ):
        _style_dialog_button(box.button(button_type), text)


def _show_message_box(
    parent,
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
    _style_message_box_buttons(box)
    return QMessageBox.StandardButton(box.exec())


def _quotation_dir() -> Path:
    return app_paths().reference_quotation_dir


def _find_quote_file() -> Path | None:
    quote_dir = _quotation_dir()
    if not quote_dir.exists():
        return None
    txt_files = sorted(path for path in quote_dir.iterdir() if path.is_file() and path.suffix.lower() == ".txt")
    return txt_files[0] if txt_files else None


def _find_photo_file(author_name: str) -> Path | None:
    picture_dir = app_paths().reference_picture_dir
    if not picture_dir.exists():
        return None

    normalized_author = author_name.strip()
    if normalized_author:
        for suffix in _IMAGE_SUFFIXES:
            candidate = picture_dir / f"{normalized_author}{suffix}"
            if candidate.exists():
                return candidate

    image_files = sorted(path for path in picture_dir.iterdir() if path.is_file() and path.suffix.lower() in _IMAGE_SUFFIXES)
    return image_files[0] if image_files else None


def _load_quote_content() -> tuple[str, str, Path | None]:
    quote_file = _find_quote_file()
    if quote_file is None:
        return "名言文件缺失。请在 reference/quotation 目录放入 .txt 文件。", "未提供作者", None

    lines = [line.strip() for line in quote_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    quote_text = random.choice(lines) if lines else "名言文件为空。"
    author_name = quote_file.stem.strip() or "未提供作者"
    return quote_text, author_name, _find_photo_file(author_name)


class IntroPage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.setTitle("登录")
        self._photo_path: Path | None = None
        self._photo_pixmap: QPixmap | None = None

        self._photo_label = QLabel()
        self._photo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._photo_label.setScaledContents(False)
        self._photo_label.setMinimumSize(300, 380)
        self._photo_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._photo_label.setStyleSheet(rounded_panel_stylesheet(background="#f7f7f7"))
        self._photo_label.setText("正在加载图片…")

        self._quote_label = QLabel()
        self._quote_label.setText("正在加载名言…")
        self._quote_label.setTextFormat(Qt.TextFormat.RichText)
        self._quote_label.setWordWrap(True)
        self._quote_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self._quote_label.setStyleSheet(
            "background: transparent; border: none; "
            "font-size: 26px; font-weight: 600; color: #c00000; "
            "font-family: 'KaiTi', 'STKaiti', 'SimSun', 'Songti SC';"
        )
        self._quote_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._quote_label.setContentsMargins(0, 0, 0, 0)

        username_edit = QLineEdit()
        username_edit.setPlaceholderText("请输入用户名")
        username_edit.setMinimumHeight(36)
        username_edit.setStyleSheet("border: 1px solid #000000; border-radius: 0px; background: #ffffff;")

        password_edit = QLineEdit()
        password_edit.setPlaceholderText("请输入密码")
        password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        password_edit.setMinimumHeight(36)
        password_edit.setStyleSheet("border: 1px solid #000000; border-radius: 0px; background: #ffffff;")
        password_edit.returnPressed.connect(self._go_next)

        btn_style = (
            "QPushButton {"
            "font-size: 16px; font-weight: 600; padding: 6px 18px; "
            "background: #ffffff; border: 1px solid #000000; border-radius: 0px;"
            "}"
            "QPushButton:hover {"
            "background: #f2f2f2;"
            "}"
            "QPushButton:pressed {"
            "background: #d9d9d9; padding-top: 8px; padding-bottom: 4px;"
            "}"
        )
        btn_height = 44

        user_login_btn = QPushButton("用户登录")
        user_login_btn.setFixedHeight(btn_height)
        user_login_btn.setStyleSheet(btn_style)
        user_login_btn.clicked.connect(self._show_login_error)

        local_login_btn = QPushButton("本地登录")
        local_login_btn.setFixedHeight(btn_height)
        local_login_btn.setStyleSheet(btn_style)
        local_login_btn.clicked.connect(self._go_next)

        exit_btn = QPushButton("退出程序")
        exit_btn.setFixedHeight(btn_height)
        exit_btn.setStyleSheet(btn_style)
        exit_btn.clicked.connect(self._exit_program)

        login_form = QFormLayout()
        login_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        login_form.setFormAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        login_form.setHorizontalSpacing(12)
        login_form.setVerticalSpacing(12)
        username_label = QLabel("用户名：")
        username_label.setStyleSheet("border: none; background: transparent;")
        password_label = QLabel("密   码：")
        password_label.setStyleSheet("border: none; background: transparent;")
        login_form.addRow(username_label, username_edit)
        login_form.addRow(password_label, password_edit)

        self._login_panel = QFrame()
        self._login_panel.setStyleSheet(rounded_panel_stylesheet())
        self._login_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._login_layout = QVBoxLayout()
        self._login_layout.setContentsMargins(20, 18, 20, 18)
        self._login_layout.setSpacing(12)
        login_title = QLabel("系统登陆")
        login_title.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        login_title.setStyleSheet("font-size: 18px; font-weight: 600;")
        self._login_layout.addWidget(login_title)
        self._login_layout.addLayout(login_form)
        self._btn_row = QHBoxLayout()
        self._btn_row.setSpacing(10)
        self._btn_row.setContentsMargins(0, 0, 0, 0)
        self._btn_row.addWidget(user_login_btn)
        self._btn_row.addWidget(local_login_btn)
        self._btn_row.addWidget(exit_btn)
        self._login_layout.addLayout(self._btn_row)
        self._login_panel.setLayout(self._login_layout)
        self._login_buttons = [user_login_btn, local_login_btn, exit_btn]

        photo_layout = QVBoxLayout()
        photo_layout.addWidget(self._photo_label, 1)

        quote_panel = QFrame()
        quote_panel.setStyleSheet(rounded_panel_stylesheet())
        quote_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        quote_layout = QVBoxLayout()
        quote_layout.setContentsMargins(0, 0, 0, 0)
        quote_layout.addWidget(self._quote_label, 1)
        quote_panel.setLayout(quote_layout)

        right_layout = QVBoxLayout()
        right_layout.setSpacing(18)
        right_layout.addWidget(quote_panel, 5)
        right_layout.addWidget(self._login_panel, 5)

        content_layout = QHBoxLayout()
        content_layout.addLayout(photo_layout, 4)
        content_layout.addLayout(right_layout, 6)

        layout = QVBoxLayout()
        layout.addLayout(content_layout, 1)
        self.setLayout(layout)
        QTimer.singleShot(0, self._load_quote_and_photo)
        QTimer.singleShot(0, self._refresh_photo_display)
        QTimer.singleShot(0, self._sync_login_button_widths)

    def initializePage(self) -> None:
        wizard = self.wizard()
        if wizard is not None:
            wizard.setButtonText(QWizard.WizardButton.NextButton, "下一步")
            QTimer.singleShot(0, lambda: self._set_wizard_nav_visible(False))

    def cleanupPage(self) -> None:
        self._set_wizard_nav_visible(True)

    def nextId(self) -> int:
        return PAGE_WELCOME

    def _go_next(self) -> None:
        wizard = self.wizard()
        if wizard is not None:
            wizard.next()

    def _show_login_error(self) -> None:
        _show_message_box(self, title="登录失败", text="账号密码错误", icon=QMessageBox.Icon.Warning)

    def _load_quote_and_photo(self) -> None:
        quote_text, _author_name, photo_path = _load_quote_content()
        self._quote_label.setText(
            '<div style="margin: 0; line-height: 1.2; white-space: pre-wrap;">'
            f"{escape(f'　　{quote_text}')}"
            "</div>"
        )
        self._photo_path = photo_path
        self._apply_photo()

    def _exit_program(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _set_wizard_nav_visible(self, visible: bool) -> None:
        wizard = self.wizard()
        if wizard is None:
            return
        for which in (
            QWizard.WizardButton.BackButton,
            QWizard.WizardButton.NextButton,
            QWizard.WizardButton.CancelButton,
            QWizard.WizardButton.FinishButton,
        ):
            button = wizard.button(which)
            if button is not None:
                button.setVisible(visible)

    def _apply_photo(self) -> None:
        if self._photo_path is None:
            self._photo_pixmap = None
            self._photo_label.clear()
            self._photo_label.setText("暂无照片\n\n请将图片文件放入 reference/picture 目录\n并优先使用与作者同名的文件名。")
            return

        pixmap = QPixmap(str(self._photo_path))
        if pixmap.isNull():
            self._photo_pixmap = None
            self._photo_label.clear()
            self._photo_label.setText("照片加载失败")
            return

        self._photo_pixmap = pixmap
        self._refresh_photo_display()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_photo_display()
        self._sync_login_button_widths()

    def _refresh_photo_display(self) -> None:
        if self._photo_pixmap is None:
            return

        contents = self._photo_label.contentsRect()
        target_width = max(1, contents.width())
        target_height = max(1, contents.height())
        scaled = self._photo_pixmap.scaled(
            target_width,
            target_height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._photo_label.setPixmap(scaled)

    def _sync_login_button_widths(self) -> None:
        panel = getattr(self, "_login_panel", None)
        layout = getattr(self, "_login_layout", None)
        buttons = getattr(self, "_login_buttons", None)
        if panel is None or layout is None or not buttons:
            return
        margins = layout.contentsMargins()
        spacing = self._btn_row.spacing()
        available_width = panel.contentsRect().width() - margins.left() - margins.right() - spacing * (len(buttons) - 1)
        if available_width <= 0:
            return
        button_width = max(80, available_width // len(buttons))
        for button in buttons:
            button.setFixedWidth(button_width)

__all__ = ["IntroPage"]
