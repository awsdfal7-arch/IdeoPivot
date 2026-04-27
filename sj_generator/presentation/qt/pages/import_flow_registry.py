from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PyQt6.QtWidgets import QWizard, QWizardPage

from sj_generator.application.state import ImportWizardSession
from sj_generator.presentation.qt.pages.import_flow import (
    AiAnalysisPage,
    AiImportContentPage,
    AiImportPage,
    AiSelectFilesPage,
    DedupeResultPage,
    ImportSuccessPage,
)
from sj_generator.presentation.qt.constants import (
    PAGE_AI_ANALYSIS,
    PAGE_AI_IMPORT,
    PAGE_AI_IMPORT_CONTENT,
    PAGE_AI_SELECT,
    PAGE_DEDUPE_RESULT,
    PAGE_IMPORT_SUCCESS,
)


@dataclass(frozen=True)
class WizardPageRegistration:
    page_id: int
    build: Callable[[ImportWizardSession], QWizardPage]


def build_import_flow_pages() -> tuple[WizardPageRegistration, ...]:
    return (
        WizardPageRegistration(PAGE_AI_SELECT, AiSelectFilesPage),
        WizardPageRegistration(PAGE_AI_IMPORT, AiImportPage),
        WizardPageRegistration(PAGE_AI_IMPORT_CONTENT, AiImportContentPage),
        WizardPageRegistration(PAGE_DEDUPE_RESULT, DedupeResultPage),
        WizardPageRegistration(PAGE_AI_ANALYSIS, AiAnalysisPage),
        WizardPageRegistration(PAGE_IMPORT_SUCCESS, ImportSuccessPage),
    )


def register_import_flow_pages(wizard: QWizard, state: ImportWizardSession) -> None:
    for registration in build_import_flow_pages():
        wizard.setPage(registration.page_id, registration.build(state))
