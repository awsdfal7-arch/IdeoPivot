from sj_generator.application.settings import provider_settings as _provider_settings
from sj_generator.application.settings import storage as _storage
from sj_generator.application.settings.program_settings import (
    load_program_settings,
    save_program_analysis_target,
    save_program_settings,
    save_program_settings_merged,
)
from sj_generator.application.settings.project_parse_settings import (
    default_project_parse_model_rows,
    load_project_parse_model_rows,
    normalize_project_parse_model_rows,
    project_parse_model_override,
    save_project_parse_model_rows,
)
from sj_generator.application.settings.provider_settings import (
    DeepSeekConfig,
    KimiConfig,
    QwenConfig,
    default_available_models,
    load_available_models,
    load_deepseek_config,
    load_kimi_config,
    load_qwen_config,
    normalize_available_models,
    save_available_models,
    save_deepseek_config,
    save_kimi_config,
    save_qwen_config,
    set_user_environment_variable,
    to_analysis_llm_config,
    to_kimi_llm_config,
    to_kimi_question_number_llm_config,
    to_llm_config,
    to_question_number_llm_config,
    to_qwen_llm_config,
    to_qwen_question_number_llm_config,
    with_capped_timeout,
)
from sj_generator.application.settings.view_settings import (
    load_welcome_table_column_visibility,
    load_welcome_table_font_point_size,
    load_welcome_tree_expanded_prefixes,
    save_welcome_table_column_visibility,
    save_welcome_table_font_point_size,
    save_welcome_tree_expanded_prefixes,
)


def _config_path():
    return _storage.deepseek_config_path()


def _kimi_config_path():
    return _storage.kimi_config_path()


def _qwen_config_path():
    return _storage.qwen_config_path()


def _program_settings_path():
    return _storage.program_settings_path()


def _read_json_dict(path):
    return _storage.read_json_dict(path)


def sync_deepseek_runtime_env(cfg: DeepSeekConfig) -> None:
    _provider_settings.set_user_environment_variable = set_user_environment_variable
    _provider_settings.sync_deepseek_runtime_env(cfg)


def sync_kimi_runtime_env(cfg: KimiConfig) -> None:
    _provider_settings.set_user_environment_variable = set_user_environment_variable
    _provider_settings.sync_kimi_runtime_env(cfg)


def sync_qwen_runtime_env(cfg: QwenConfig) -> None:
    _provider_settings.set_user_environment_variable = set_user_environment_variable
    _provider_settings.sync_qwen_runtime_env(cfg)

__all__ = [
    "DeepSeekConfig",
    "KimiConfig",
    "QwenConfig",
    "default_available_models",
    "default_project_parse_model_rows",
    "load_available_models",
    "load_deepseek_config",
    "load_kimi_config",
    "load_program_settings",
    "load_project_parse_model_rows",
    "load_qwen_config",
    "load_welcome_table_column_visibility",
    "load_welcome_table_font_point_size",
    "load_welcome_tree_expanded_prefixes",
    "normalize_available_models",
    "normalize_project_parse_model_rows",
    "project_parse_model_override",
    "save_available_models",
    "save_deepseek_config",
    "save_kimi_config",
    "save_program_analysis_target",
    "save_program_settings",
    "save_program_settings_merged",
    "save_project_parse_model_rows",
    "save_qwen_config",
    "save_welcome_table_column_visibility",
    "save_welcome_table_font_point_size",
    "save_welcome_tree_expanded_prefixes",
    "set_user_environment_variable",
    "sync_deepseek_runtime_env",
    "sync_kimi_runtime_env",
    "sync_qwen_runtime_env",
    "sync_deepseek_runtime_env",
    "sync_kimi_runtime_env",
    "sync_qwen_runtime_env",
    "to_analysis_llm_config",
    "to_kimi_llm_config",
    "to_kimi_question_number_llm_config",
    "to_llm_config",
    "to_question_number_llm_config",
    "to_qwen_llm_config",
    "to_qwen_question_number_llm_config",
    "with_capped_timeout",
    "_config_path",
    "_kimi_config_path",
    "_qwen_config_path",
    "_program_settings_path",
    "_read_json_dict",
]
