from __future__ import annotations

from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QWizard

from sj_generator.ui.constants import (
    PAGE_AI_ANALYSIS,
    PAGE_AI_IMPORT,
    PAGE_AI_SELECT,
    PAGE_DEDUPE_RESULT,
    PAGE_IMPORT_SUCCESS,
)
from sj_generator.ui.pages.analysis_pages import AiAnalysisPage
from sj_generator.ui.pages.dedupe_pages import DedupeResultPage
from sj_generator.ui.pages.export_pages import ImportSuccessPage
from sj_generator.ui.pages.import_pages import AiImportPage, AiSelectFilesPage
from sj_generator.ui.state import WizardState

DEFAULT_WINDOW_WIDTH = 976
DEFAULT_WINDOW_HEIGHT = 575
QT_MAX_WINDOW_SIZE = 16777215


def configure_import_flow_pages(wizard: QWizard, state: WizardState) -> None:
    wizard.setPage(PAGE_AI_SELECT, AiSelectFilesPage(state))
    wizard.setPage(PAGE_AI_IMPORT, AiImportPage(state))
    wizard.setPage(PAGE_DEDUPE_RESULT, DedupeResultPage(state))
    wizard.setPage(PAGE_AI_ANALYSIS, AiAnalysisPage(state))
    wizard.setPage(PAGE_IMPORT_SUCCESS, ImportSuccessPage(state))


class ImportFlowWizard(QWizard):
    def __init__(self, state: WizardState, parent=None) -> None:
        super().__init__(parent)
        self._state = state
        self.setWindowTitle("导入资料")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self._default_button_layout = [
            QWizard.WizardButton.Stretch,
            QWizard.WizardButton.BackButton,
            QWizard.WizardButton.NextButton,
            QWizard.WizardButton.FinishButton,
            QWizard.WizardButton.CancelButton,
        ]
        self.setButtonLayout(self._default_button_layout)
        self.setButtonText(QWizard.WizardButton.BackButton, "上一步")
        self.setButtonText(QWizard.WizardButton.NextButton, "下一步")
        self.setButtonText(QWizard.WizardButton.CancelButton, "取消")
        self.setButtonText(QWizard.WizardButton.FinishButton, "完成")
        configure_import_flow_pages(self, self._state)
        self._cache_and_hide_page_titles()
        self.setStartId(PAGE_AI_SELECT)
        self.currentIdChanged.connect(self._update_window_title)
        self.currentIdChanged.connect(self._sync_window_resizability)
        self._update_window_title(self.startId())
        self._sync_window_resizability(self.startId())
        self.resize(DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)

    def _cache_and_hide_page_titles(self) -> None:
        for page_id in self.pageIds():
            page = self.page(page_id)
            if page is None:
                continue
            page.setProperty("_window_title_text", page.title())
            page.setTitle("")

    def _update_window_title(self, _page_id: int) -> None:
        self.setWindowTitle("思政智题云枢")

    def _sync_window_resizability(self, _page_id: int) -> None:
        self.setMinimumSize(0, 0)
        self.setMaximumSize(QT_MAX_WINDOW_SIZE, QT_MAX_WINDOW_SIZE)

    def accept(self) -> None:
        super().accept()

    def reject(self) -> None:
        if not self._can_close_current_page():
            return
        super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._can_close_current_page():
            event.ignore()
            return
        super().closeEvent(event)

    def _can_close_current_page(self) -> bool:
        page = self.currentPage()
        guard = getattr(page, "prepare_to_close", None)
        if callable(guard):
            return bool(guard())
        return True
