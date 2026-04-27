from __future__ import annotations

from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QWizard

from sj_generator.application.state import ImportWizardSession
from sj_generator.presentation.qt.pages import register_import_flow_pages
from sj_generator.presentation.qt.constants import (
    DEFAULT_WINDOW_HEIGHT,
    DEFAULT_WINDOW_WIDTH,
    PAGE_AI_ANALYSIS,
    PAGE_AI_IMPORT,
    PAGE_AI_IMPORT_CONTENT,
    PAGE_AI_SELECT,
    PAGE_DEDUPE_RESULT,
    PAGE_IMPORT_SUCCESS,
    QT_MAX_WINDOW_SIZE,
)
from sj_generator.presentation.qt.wizard_base import AppWizardBase

BUTTON_MIN_WIDTH = 128
BUTTON_MIN_HEIGHT = 40


def configure_import_flow_pages(wizard: QWizard, state: ImportWizardSession) -> None:
    register_import_flow_pages(wizard, state)


class ImportFlowWizard(AppWizardBase):
    def __init__(self, state: ImportWizardSession, parent=None, *, launcher=None, start_page_id: int = PAGE_AI_SELECT) -> None:
        super().__init__(parent)
        self._state = state
        self._launcher = launcher
        self._start_page_id = start_page_id
        self._deferred_close_requested = False
        self.apply_button_texts(
            {
                QWizard.WizardButton.CustomButton1: "添加文档",
                QWizard.WizardButton.CustomButton2: "打开文档",
                QWizard.WizardButton.CustomButton3: "打开文档",
                QWizard.WizardButton.NextButton: "开始导题",
            }
        )
        self.setOption(QWizard.WizardOption.HaveCustomButton1, True)
        self.setOption(QWizard.WizardOption.HaveCustomButton2, True)
        self.setOption(QWizard.WizardOption.HaveCustomButton3, True)
        self.setButtonLayout(
            [
                QWizard.WizardButton.CustomButton1,
                QWizard.WizardButton.CustomButton2,
                QWizard.WizardButton.CustomButton3,
                QWizard.WizardButton.Stretch,
                QWizard.WizardButton.NextButton,
            ]
        )
        configure_import_flow_pages(self, self._state)
        self.cache_and_hide_page_titles()
        self.setStartId(start_page_id)
        self.currentIdChanged.connect(self.update_window_title)
        self.currentIdChanged.connect(self._sync_window_resizability)
        self.currentIdChanged.connect(self._style_navigation_buttons)
        self.currentIdChanged.connect(self._sync_page_navigation_buttons)
        self.update_window_title(self.startId())
        self._sync_window_resizability(self.startId())
        self._style_navigation_buttons(self.startId())
        self._sync_page_navigation_buttons(self.startId())
        self.resize(DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)

    def _sync_window_resizability(self, _page_id: int) -> None:
        self.setMinimumSize(0, 0)
        self.setMaximumSize(QT_MAX_WINDOW_SIZE, QT_MAX_WINDOW_SIZE)

    def _style_navigation_buttons(self, _page_id: int) -> None:
        for which in (
            QWizard.WizardButton.CustomButton1,
            QWizard.WizardButton.CustomButton2,
            QWizard.WizardButton.CustomButton3,
            QWizard.WizardButton.NextButton,
        ):
            button = self.button(which)
            if button is None:
                continue
            button.setMinimumSize(BUTTON_MIN_WIDTH, BUTTON_MIN_HEIGHT)
            button.setStyleSheet("padding: 6px 18px;")

    def _sync_page_navigation_buttons(self, _page_id: int) -> None:
        page = self.currentPage()
        sync = getattr(page, "_sync_wizard_buttons", None)
        if callable(sync):
            sync()
        button = self.button(QWizard.WizardButton.CustomButton1)
        if button is not None:
            button.setVisible(False)
        button2 = self.button(QWizard.WizardButton.CustomButton2)
        if button2 is not None:
            button2.setVisible(False)
        button3 = self.button(QWizard.WizardButton.CustomButton3)
        if button3 is not None:
            button3.setVisible(False)
        back_button = self.button(QWizard.WizardButton.BackButton)
        if back_button is not None:
            back_button.setVisible(False)
        cancel_button = self.button(QWizard.WizardButton.CancelButton)
        if cancel_button is not None:
            cancel_button.setVisible(False)
        finish_button = self.button(QWizard.WizardButton.FinishButton)
        if finish_button is not None:
            finish_button.setVisible(False)
        handler = getattr(page, "_sync_custom_wizard_button", None)
        if callable(handler):
            handler()

    def back(self) -> None:
        # 导入向导进入下一页后不允许回退到上一步。
        return

    def accept(self) -> None:
        super().accept()

    def reject(self) -> None:
        if not self._can_close_current_page():
            self._deferred_close_requested = True
            self.hide()
            return
        super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._can_close_current_page():
            self._deferred_close_requested = True
            self.hide()
            event.ignore()
            return
        self._deferred_close_requested = False
        super().closeEvent(event)

    def _can_close_current_page(self) -> bool:
        page_ids = (
            PAGE_AI_SELECT,
            PAGE_AI_IMPORT,
            PAGE_AI_IMPORT_CONTENT,
            PAGE_DEDUPE_RESULT,
            PAGE_AI_ANALYSIS,
            PAGE_IMPORT_SUCCESS,
        )
        for page_id in page_ids:
            page = self.page(page_id)
            guard = getattr(page, "prepare_to_close", None)
            if callable(guard) and not bool(guard()):
                return False
        return True

    def open_additional_documents(self, source_paths, *, message_parent=None) -> bool:
        handler = getattr(self._launcher, "_open_import_flow_windows", None)
        if not callable(handler):
            return False
        return bool(handler(source_paths, message_parent=message_parent))

    def open_split_import_flow_windows(self, states, *, start_page_id: int) -> bool:
        handler = getattr(self._launcher, "_open_split_import_flow_windows", None)
        if not callable(handler):
            return False
        return bool(handler(states, start_page_id=start_page_id))
