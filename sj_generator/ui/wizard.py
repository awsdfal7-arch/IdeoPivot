import sys
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QWizard

from sj_generator.config import load_program_settings
from sj_generator.ui.state import (
    WizardState,
    normalize_ai_concurrency,
    normalize_analysis_model_name,
    normalize_analysis_provider,
    normalize_default_repo_parent_dir_text,
    normalize_export_convertible_multi_mode,
    normalize_export_include_answers,
    normalize_export_include_analysis,
    normalize_import_source_dir_text,
    normalize_preferred_textbook_version,
)
from sj_generator.ui.styles import APP_STYLESHEET
from sj_generator.ui.constants import (
    DEFAULT_WINDOW_HEIGHT,
    DEFAULT_WINDOW_WIDTH,
    PAGE_INTRO,
    PAGE_WELCOME,
    QT_MAX_WINDOW_SIZE,
)
from sj_generator.ui.pages.intro_pages import IntroPage


class GeneratorWizard(QWizard):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("思政智题云枢")
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

        self._state = WizardState()
        self._welcome_page_loaded = False
        self._apply_saved_program_settings()
        self.setPage(PAGE_INTRO, IntroPage())
        self._cache_and_hide_page_titles()
        self.setStartId(PAGE_INTRO)
        self.currentIdChanged.connect(self._update_window_title)
        self.currentIdChanged.connect(self._sync_navigation_buttons)
        self.currentIdChanged.connect(self._sync_window_resizability)
        self._update_window_title(self.startId())
        self._sync_navigation_buttons(self.startId())
        self._sync_window_resizability(self.startId())

    def _cache_and_hide_page_titles(self) -> None:
        for page_id in self.pageIds():
            page = self.page(page_id)
            if page is None:
                continue
            page.setProperty("_window_title_text", page.title())
            page.setTitle("")

    def _update_window_title(self, page_id: int) -> None:
        self.setWindowTitle("思政智题云枢")

    def next(self) -> None:
        if self.currentId() == PAGE_INTRO:
            self._ensure_welcome_page_loaded()
        super().next()

    def _sync_navigation_buttons(self, page_id: int) -> None:
        show_nav = page_id not in (PAGE_INTRO, PAGE_WELCOME)
        self.setButtonLayout([] if not show_nav else self._default_button_layout)
        for which in (
            QWizard.WizardButton.BackButton,
            QWizard.WizardButton.NextButton,
            QWizard.WizardButton.CancelButton,
            QWizard.WizardButton.FinishButton,
        ):
            button = self.button(which)
            if button is not None:
                button.setVisible(show_nav)

    def _sync_window_resizability(self, page_id: int) -> None:
        if page_id == PAGE_INTRO:
            self.resize(DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
            self.setFixedSize(DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
            return

        self.setMinimumSize(0, 0)
        self.setMaximumSize(QT_MAX_WINDOW_SIZE, QT_MAX_WINDOW_SIZE)

    def _apply_saved_program_settings(self) -> None:
        data = load_program_settings()
        self._state.default_repo_parent_dir_text = normalize_default_repo_parent_dir_text(
            data.get("default_repo_parent_dir_text")
        )
        self._state.import_source_dir_text = normalize_import_source_dir_text(
            data.get("import_source_dir_text")
        )
        self._state.ai_concurrency = normalize_ai_concurrency(data.get("ai_concurrency"))
        self._state.analysis_enabled = bool(data.get("analysis_enabled", self._state.analysis_enabled))
        self._state.dedupe_enabled = bool(data.get("dedupe_enabled", self._state.dedupe_enabled))
        self._state.analysis_provider = normalize_analysis_provider(data.get("analysis_provider"))
        self._state.analysis_model_name = normalize_analysis_model_name(data.get("analysis_model_name"))
        self._state.export_convertible_multi_mode = normalize_export_convertible_multi_mode(
            data.get("export_convertible_multi_mode")
        )
        legacy_include = data.get("export_include_answers_and_analysis")
        self._state.export_include_answers = normalize_export_include_answers(
            data.get("export_include_answers", legacy_include)
        )
        self._state.export_include_analysis = normalize_export_include_analysis(
            data.get("export_include_analysis", legacy_include)
        )
        self._state.preferred_textbook_version = normalize_preferred_textbook_version(
            data.get("preferred_textbook_version")
        )

    def _ensure_welcome_page_loaded(self) -> None:
        if self._welcome_page_loaded:
            return
        from sj_generator.ui.pages.welcome_pages import WelcomePage

        page = WelcomePage(self._state)
        page.setProperty("_window_title_text", page.title())
        page.setTitle("")
        self.setPage(PAGE_WELCOME, page)
        self._welcome_page_loaded = True

def main() -> None:
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication(sys.argv)
    app.setStyleSheet(APP_STYLESHEET)
    icon_path = Path(__file__).resolve().parents[2] / "logo.png"
    icon: QIcon | None = None
    if icon_path.exists():
        loaded_icon = QIcon(str(icon_path))
        if not loaded_icon.isNull():
            icon = loaded_icon
            app.setWindowIcon(icon)
    w = GeneratorWizard()
    if icon is not None:
        w.setWindowIcon(icon)
    w.resize(DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
    w.show()
    raise SystemExit(app.exec())
