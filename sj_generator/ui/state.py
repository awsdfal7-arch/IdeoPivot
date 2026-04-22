from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from sj_generator.io.dedupe import DedupeHit
from sj_generator.models import Question

AI_CONCURRENCY_OPTIONS = (1, 2, 3, 4, 5)
ANALYSIS_PROVIDER_OPTIONS = ("deepseek", "kimi", "qwen")
EXPORT_CONVERTIBLE_MULTI_MODE_OPTIONS = ("keep_combo", "as_multi")
DEFAULT_ANALYSIS_MODEL_NAME = "deepseek-reasoner"
DEFAULT_REPO_PARENT_DIR_NAME = "思政题库"
DEFAULT_LIBRARY_DB_FILE_NAME = "思政题库.db"


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


def normalize_default_repo_parent_dir_text(value: str | None) -> str:
    text = (value or "").strip()
    return text or str(default_repo_parent_dir())


def library_db_path_from_repo_parent_dir_text(value: str | None) -> Path:
    return Path(normalize_default_repo_parent_dir_text(value)) / DEFAULT_LIBRARY_DB_FILE_NAME


@dataclass
class AiSourceFileItem:
    path: str
    version: str = ""
    level_path: str = ""


@dataclass
class WizardState:
    project_dir: Optional[Path] = None
    repo_path: Optional[Path] = None
    last_export_dir: Optional[Path] = None
    draft_questions: list[Question] = field(default_factory=list)
    start_mode: str = "wizard"
    project_name_is_placeholder: bool = False
    batch_source_files: Optional[list[Path]] = None
    batch_source_files_text: str = ""
    ai_source_files: Optional[list[Path]] = None
    ai_source_files_text: str = ""
    ai_source_file_items: list[AiSourceFileItem] = field(default_factory=list)
    ai_import_questions: Optional[list[Question]] = None
    ai_import_level_path: str = ""
    dedupe_hits: Optional[list[DedupeHit]] = None
    dedupe_enabled: bool = True
    dedupe_threshold: float = 0.85
    default_repo_parent_dir_text: str = field(default_factory=lambda: str(default_repo_parent_dir()))
    analysis_enabled: bool = True
    analysis_use_reference_folder: bool = True
    analysis_use_reference_md: bool = False
    analysis_reference_md_path_text: str = ""
    analysis_include_common_mistakes: bool = True
    analysis_provider: str = "deepseek"
    analysis_model_name: str = DEFAULT_ANALYSIS_MODEL_NAME
    export_convertible_multi_mode: str = "keep_combo"
    ai_concurrency: int = 3
    db_import_completed: bool = False
    db_import_count: int = 0
    db_import_error: str = ""

    def reset_db_import(self) -> None:
        self.db_import_completed = False
        self.db_import_count = 0
        self.db_import_error = ""

    def mark_db_import_completed(self, count: int) -> None:
        self.db_import_completed = True
        self.db_import_count = max(0, int(count))
        self.db_import_error = ""
