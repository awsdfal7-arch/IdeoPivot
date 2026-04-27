from __future__ import annotations

from collections.abc import Mapping

from PyQt6.QtWidgets import QWizard

PRODUCT_TITLE = "思政智题云枢"

DEFAULT_WIZARD_BUTTON_LAYOUT = [
    QWizard.WizardButton.Stretch,
    QWizard.WizardButton.BackButton,
    QWizard.WizardButton.NextButton,
    QWizard.WizardButton.FinishButton,
    QWizard.WizardButton.CancelButton,
]


class AppWizardBase(QWizard):
    def __init__(self, parent=None, *, window_title: str = PRODUCT_TITLE) -> None:
        super().__init__(parent)
        self._window_title_text = window_title
        self._default_button_layout = list(DEFAULT_WIZARD_BUTTON_LAYOUT)
        self.setWindowTitle(window_title)
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setButtonLayout(self._default_button_layout)

    def apply_button_texts(self, button_texts: Mapping[QWizard.WizardButton, str]) -> None:
        for button, text in button_texts.items():
            self.setButtonText(button, text)

    def cache_and_hide_page_titles(self) -> None:
        for page_id in self.pageIds():
            page = self.page(page_id)
            if page is None:
                continue
            page.setProperty("_window_title_text", page.title())
            page.setTitle("")

    def cache_and_hide_page_title(self, page_id: int) -> None:
        page = self.page(page_id)
        if page is None:
            return
        page.setProperty("_window_title_text", page.title())
        page.setTitle("")

    def update_window_title(self, _page_id: int) -> None:
        self.setWindowTitle(self._window_title_text)
