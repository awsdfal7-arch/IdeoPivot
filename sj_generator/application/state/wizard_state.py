from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import threading
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from sj_generator.domain.entities import Question
    from sj_generator.application.dedupe.service import DedupeHit

AI_CONCURRENCY_OPTIONS = tuple(range(1, 21))
ANALYSIS_PROVIDER_OPTIONS = ("deepseek", "kimi", "qwen")
EXPORT_CONVERTIBLE_MULTI_MODE_OPTIONS = ("keep_combo", "as_multi")
DEFAULT_ANALYSIS_MODEL_NAME = "deepseek-reasoner"
DEFAULT_REPO_PARENT_DIR_NAME = "思政题库"
DEFAULT_LIBRARY_DB_FILE_NAME = "思政题库.db"
DEFAULT_PREFERRED_TEXTBOOK_VERSION = "2026年春"
DEFAULT_EXPORT_INCLUDE_ANSWERS = True
DEFAULT_EXPORT_INCLUDE_ANALYSIS = True


def normalize_ai_concurrency(value: int | None) -> int:
    try:
        workers = int(value or 0)
    except Exception:
        workers = 0
    return workers if workers in AI_CONCURRENCY_OPTIONS else 3


def normalize_analysis_provider(value: str | None) -> str:
    provider = (value or "").strip().lower()
    return provider if provider in ANALYSIS_PROVIDER_OPTIONS else "deepseek"


def normalize_analysis_model_name(value: str | None) -> str:
    model_name = (value or "").strip()
    return model_name or DEFAULT_ANALYSIS_MODEL_NAME


def normalize_export_convertible_multi_mode(value: str | None) -> str:
    mode = (value or "").strip().lower()
    return mode if mode in EXPORT_CONVERTIBLE_MULTI_MODE_OPTIONS else "keep_combo"


def default_repo_parent_dir() -> Path:
    return Path.home() / "Desktop" / DEFAULT_REPO_PARENT_DIR_NAME


def default_import_source_dir() -> Path:
    return Path.home() / "Downloads"


def desktop_import_source_dir() -> Path:
    return Path.home() / "Desktop"


def normalize_default_repo_parent_dir_text(value: str | None) -> str:
    text = (value or "").strip()
    return text or str(default_repo_parent_dir())


def normalize_import_source_dir_text(value: str | None) -> str:
    text = (value or "").strip()
    return text or str(default_import_source_dir())


def normalize_preferred_textbook_version(value: str | None) -> str:
    text = (value or "").strip()
    return text or DEFAULT_PREFERRED_TEXTBOOK_VERSION


def normalize_export_include_answers(value: object) -> bool:
    return bool(DEFAULT_EXPORT_INCLUDE_ANSWERS if value is None else value)


def normalize_export_include_analysis(value: object) -> bool:
    return bool(DEFAULT_EXPORT_INCLUDE_ANALYSIS if value is None else value)


def library_db_path_from_repo_parent_dir_text(value: str | None) -> Path:
    return Path(normalize_default_repo_parent_dir_text(value)) / DEFAULT_LIBRARY_DB_FILE_NAME


@dataclass
class AiSourceFileItem:
    path: str
    version: str = ""
    level_path: str = ""


@dataclass
class ImportSourceState:
    files: list[Path] = field(default_factory=list)
    files_text: str = ""
    file_items: list[AiSourceFileItem] = field(default_factory=list)
    import_level_path: str = ""


@dataclass
class ImportQuestionRefState:
    question_refs_by_source: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    revision: int = 0


@dataclass
class ImportDraftState:
    questions: list[Question] = field(default_factory=list)
    dedupe_hits: Optional[list[DedupeHit]] = None

    def clear_questions(self) -> None:
        self.questions = []
        self.dedupe_hits = None

    def replace_questions(self, questions: list[Question]) -> None:
        self.questions = list(questions)
        self.dedupe_hits = None


@dataclass
class ImportExecutionState:
    db_import_completed: bool = False
    db_import_count: int = 0
    db_import_error: str = ""
    import_cost_before_amounts: dict[str, str] = field(default_factory=dict)
    import_cost_before_details: dict[str, str] = field(default_factory=dict)
    import_cost_rows: list[dict[str, str]] = field(default_factory=list)
    import_cost_total_text: str = ""
    import_cost_summary_text: str = ""
    import_cost_detail_text: str = ""
    import_cost_ready: bool = False
    import_cost_before_loading: bool = False
    import_cost_capture_revision: int = 0
    import_cost_capture_thread: threading.Thread | None = field(default=None, repr=False, compare=False)

    def reset_db_import(self) -> None:
        self.db_import_completed = False
        self.db_import_count = 0
        self.db_import_error = ""

    def mark_db_import_completed(self, count: int) -> None:
        self.db_import_completed = True
        self.db_import_count = max(0, int(count))
        self.db_import_error = ""

    def reset_import_cost_tracking(self) -> None:
        self.import_cost_capture_revision += 1
        self.import_cost_before_amounts = {}
        self.import_cost_before_details = {}
        self.import_cost_rows = []
        self.import_cost_total_text = ""
        self.import_cost_summary_text = ""
        self.import_cost_detail_text = ""
        self.import_cost_ready = False
        self.import_cost_before_loading = False
        self.import_cost_capture_thread = None


@dataclass
class ImportWizardSession:
    project_dir: Optional[Path] = None
    repo_path: Optional[Path] = None
    last_export_dir: Optional[Path] = None
    project_name_is_placeholder: bool = False
    dedupe_enabled: bool = True
    dedupe_threshold: float = 0.85
    default_repo_parent_dir_text: str = field(default_factory=lambda: str(default_repo_parent_dir()))
    import_source_dir_text: str = field(default_factory=lambda: str(default_import_source_dir()))
    analysis_enabled: bool = True
    analysis_use_reference_folder: bool = True
    analysis_use_reference_md: bool = False
    analysis_reference_md_path_text: str = ""
    analysis_include_common_mistakes: bool = True
    analysis_provider: str = "deepseek"
    analysis_model_name: str = DEFAULT_ANALYSIS_MODEL_NAME
    export_convertible_multi_mode: str = "keep_combo"
    export_include_answers: bool = DEFAULT_EXPORT_INCLUDE_ANSWERS
    export_include_analysis: bool = DEFAULT_EXPORT_INCLUDE_ANALYSIS
    preferred_textbook_version: str = DEFAULT_PREFERRED_TEXTBOOK_VERSION
    ai_concurrency: int = 3
    question_content_concurrency: int = 3
    analysis_generation_concurrency: int = 3
    source: ImportSourceState = field(default_factory=ImportSourceState)
    refs: ImportQuestionRefState = field(default_factory=ImportQuestionRefState)
    draft: ImportDraftState = field(default_factory=ImportDraftState)
    execution: ImportExecutionState = field(default_factory=ImportExecutionState)

    def apply_question_refs(self, question_refs_by_source: dict[str, list[dict[str, str]]]) -> None:
        self.refs.question_refs_by_source = dict(question_refs_by_source or {})
        self.refs.revision = max(0, int(self.refs.revision)) + 1
        self.draft.clear_questions()
        self.execution.reset_db_import()

    def apply_draft_questions(self, questions: list[Question]) -> None:
        self.draft.replace_questions(questions)
        self.execution.reset_db_import()

    def set_dedupe_hits(self, hits: list[DedupeHit] | None) -> None:
        self.draft.dedupe_hits = hits

    def build_import_session(
        self,
        *,
        source_files: list[Path],
        source_items: list[AiSourceFileItem] | None = None,
        question_refs_by_source: dict[str, list[dict[str, str]]] | None = None,
        question_refs_version: int = 0,
        import_level_path: str = "",
    ) -> ImportWizardSession:
        return build_import_flow_session(
            self,
            source_files=source_files,
            source_items=source_items,
            question_refs_by_source=question_refs_by_source,
            question_refs_version=question_refs_version,
            import_level_path=import_level_path,
        )


@dataclass
class WizardState:
    project_dir: Optional[Path] = None
    repo_path: Optional[Path] = None
    last_export_dir: Optional[Path] = None
    start_mode: str = "wizard"
    project_name_is_placeholder: bool = False
    dedupe_enabled: bool = True
    dedupe_threshold: float = 0.85
    default_repo_parent_dir_text: str = field(default_factory=lambda: str(default_repo_parent_dir()))
    import_source_dir_text: str = field(default_factory=lambda: str(default_import_source_dir()))
    analysis_enabled: bool = True
    analysis_use_reference_folder: bool = True
    analysis_reference_md_path_text: str = ""
    analysis_include_common_mistakes: bool = True
    analysis_provider: str = "deepseek"
    analysis_model_name: str = DEFAULT_ANALYSIS_MODEL_NAME
    export_convertible_multi_mode: str = "keep_combo"
    export_include_answers: bool = DEFAULT_EXPORT_INCLUDE_ANSWERS
    export_include_analysis: bool = DEFAULT_EXPORT_INCLUDE_ANALYSIS
    preferred_textbook_version: str = DEFAULT_PREFERRED_TEXTBOOK_VERSION
    ai_concurrency: int = 3
    question_content_concurrency: int = 3
    analysis_generation_concurrency: int = 3

    def build_import_session(
        self,
        *,
        source_files: list[Path],
        source_items: list[AiSourceFileItem] | None = None,
        question_refs_by_source: dict[str, list[dict[str, str]]] | None = None,
        question_refs_version: int = 0,
        import_level_path: str = "",
    ) -> ImportWizardSession:
        return build_import_flow_session(
            self,
            source_files=source_files,
            source_items=source_items,
            question_refs_by_source=question_refs_by_source,
            question_refs_version=question_refs_version,
            import_level_path=import_level_path,
        )


def build_import_flow_session(
    base_state: WizardState | ImportWizardSession,
    *,
    source_files: list[Path],
    source_items: list[AiSourceFileItem] | None = None,
    question_refs_by_source: dict[str, list[dict[str, str]]] | None = None,
    question_refs_version: int = 0,
    import_level_path: str = "",
) -> ImportWizardSession:
    cleaned_paths = [Path(path) for path in source_files if str(path).strip()]
    raw_paths = [str(path) for path in cleaned_paths]
    item_map = {
        item.path: item
        for item in (source_items or [])
        if isinstance(item, AiSourceFileItem) and str(item.path or "").strip()
    }
    default_version = base_state.preferred_textbook_version
    built_items = [
        AiSourceFileItem(
            path=raw_path,
            version=(item_map.get(raw_path).version or default_version) if raw_path in item_map else default_version,
            level_path=(item_map.get(raw_path).level_path or "") if raw_path in item_map else "",
        )
        for raw_path in raw_paths
    ]
    return ImportWizardSession(
        project_dir=base_state.project_dir,
        repo_path=base_state.repo_path,
        last_export_dir=base_state.last_export_dir,
        project_name_is_placeholder=base_state.project_name_is_placeholder,
        dedupe_enabled=base_state.dedupe_enabled,
        dedupe_threshold=base_state.dedupe_threshold,
        default_repo_parent_dir_text=base_state.default_repo_parent_dir_text,
        import_source_dir_text=base_state.import_source_dir_text,
        analysis_enabled=base_state.analysis_enabled,
        analysis_use_reference_folder=base_state.analysis_use_reference_folder,
        analysis_use_reference_md=base_state.analysis_use_reference_md,
        analysis_reference_md_path_text=base_state.analysis_reference_md_path_text,
        analysis_include_common_mistakes=base_state.analysis_include_common_mistakes,
        analysis_provider=base_state.analysis_provider,
        analysis_model_name=base_state.analysis_model_name,
        export_convertible_multi_mode=base_state.export_convertible_multi_mode,
        export_include_answers=base_state.export_include_answers,
        export_include_analysis=base_state.export_include_analysis,
        preferred_textbook_version=base_state.preferred_textbook_version,
        ai_concurrency=base_state.ai_concurrency,
        question_content_concurrency=base_state.question_content_concurrency,
        analysis_generation_concurrency=base_state.analysis_generation_concurrency,
        source=ImportSourceState(
            files=list(cleaned_paths),
            files_text="; ".join(raw_paths),
            file_items=built_items,
            import_level_path=str(import_level_path or "").strip(),
        ),
        refs=ImportQuestionRefState(
            question_refs_by_source=dict(question_refs_by_source or {}),
            revision=max(0, int(question_refs_version)),
        ),
    )
