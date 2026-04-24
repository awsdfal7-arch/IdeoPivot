from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sj_generator.ai.client import LlmConfig


@dataclass(frozen=True)
class DeepSeekConfig:
    base_url: str = "https://api.deepseek.com"
    api_key: str = ""
    number_model: str = "deepseek-chat"
    model: str = "deepseek-chat"
    analysis_model: str = "deepseek-reasoner"
    timeout_s: float = 120.0

    def is_ready(self) -> bool:
        return bool(
            self.api_key.strip()
            and self.base_url.strip()
            and self.number_model.strip()
            and self.model.strip()
            and self.analysis_model.strip()
        )


@dataclass(frozen=True)
class KimiConfig:
    base_url: str = "https://api.moonshot.cn/v1"
    api_key: str = ""
    number_model: str = "kimi-k2.6"
    model: str = "kimi-k2.6"
    timeout_s: float = 120.0

    def is_ready(self) -> bool:
        return bool(self.api_key.strip() and self.base_url.strip() and self.number_model.strip() and self.model.strip())


@dataclass(frozen=True)
class QwenConfig:
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    api_key: str = ""
    number_model: str = "qwen-max"
    model: str = "qwen-max"
    account_access_key_id: str = ""
    account_access_key_secret: str = ""
    timeout_s: float = 120.0

    def is_ready(self) -> bool:
        return bool(self.api_key.strip() and self.base_url.strip() and self.number_model.strip() and self.model.strip())

    def has_account_balance_credentials(self) -> bool:
        return bool(self.account_access_key_id.strip() and self.account_access_key_secret.strip())


def load_deepseek_config() -> DeepSeekConfig:
    env_base_url = os.getenv("DEEPSEEK_BASE_URL", "").strip()
    env_api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    env_model = os.getenv("DEEPSEEK_QUESTION_UNIT_MODEL", "").strip() or os.getenv("DEEPSEEK_MODEL", "").strip()
    env_number_model = os.getenv("DEEPSEEK_QUESTION_NUMBER_MODEL", "").strip()
    env_analysis_model = os.getenv("DEEPSEEK_ANALYSIS_MODEL", "").strip()
    env_timeout = os.getenv("DEEPSEEK_TIMEOUT_S", "").strip()
    project_number_model = project_parse_model_override("question_number_parse", "deepseek")
    project_unit_model = project_parse_model_override("question_content_parse", "deepseek")

    file_cfg = _load_json_config_file(_config_path())
    file_timeout = file_cfg.get("timeout_s")
    timeout_s = DeepSeekConfig.timeout_s
    try:
        if env_timeout:
            timeout_s = float(env_timeout)
        elif file_timeout is not None:
            timeout_s = float(file_timeout)
    except Exception:
        timeout_s = DeepSeekConfig.timeout_s

    cfg = DeepSeekConfig(
        base_url=_clean_base_url(env_base_url or file_cfg.get("base_url") or DeepSeekConfig.base_url),
        api_key=env_api_key,
        number_model=(
            project_number_model
            or env_number_model
            or str(file_cfg.get("question_number_model") or file_cfg.get("number_model") or DeepSeekConfig.number_model).strip()
        ),
        model=(project_unit_model or env_model or file_cfg.get("model") or DeepSeekConfig.model).strip(),
        analysis_model=(env_analysis_model or file_cfg.get("analysis_model") or DeepSeekConfig.analysis_model).strip(),
        timeout_s=timeout_s,
    )
    return cfg


def save_deepseek_config(cfg: DeepSeekConfig) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "base_url": cfg.base_url.strip(),
        "question_number_model": cfg.number_model.strip(),
        "model": cfg.model.strip(),
        "analysis_model": cfg.analysis_model.strip(),
        "timeout_s": cfg.timeout_s,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def to_llm_config(cfg: DeepSeekConfig) -> LlmConfig:
    from sj_generator.ai.client import LlmConfig

    return LlmConfig(
        base_url=cfg.base_url.strip(),
        api_key=cfg.api_key.strip(),
        model=cfg.model.strip(),
        timeout_s=float(cfg.timeout_s),
    )


def to_question_number_llm_config(cfg: DeepSeekConfig) -> LlmConfig:
    from sj_generator.ai.client import LlmConfig

    return LlmConfig(
        base_url=cfg.base_url.strip(),
        api_key=cfg.api_key.strip(),
        model=cfg.number_model.strip(),
        timeout_s=float(cfg.timeout_s),
    )


def to_analysis_llm_config(cfg: DeepSeekConfig) -> LlmConfig:
    from sj_generator.ai.client import LlmConfig

    return LlmConfig(
        base_url=cfg.base_url.strip(),
        api_key=cfg.api_key.strip(),
        model=cfg.analysis_model.strip(),
        timeout_s=float(cfg.timeout_s),
    )


def load_kimi_config() -> KimiConfig:
    env_base_url = os.getenv("KIMI_BASE_URL", "").strip()
    env_api_key = os.getenv("KIMI_API_KEY", "").strip()
    env_model = os.getenv("KIMI_QUESTION_UNIT_MODEL", "").strip() or os.getenv("KIMI_MODEL", "").strip()
    env_number_model = os.getenv("KIMI_QUESTION_NUMBER_MODEL", "").strip()
    env_timeout = os.getenv("KIMI_TIMEOUT_S", "").strip()
    project_number_model = project_parse_model_override("question_number_parse", "kimi")
    project_unit_model = project_parse_model_override("question_content_parse", "kimi")

    file_cfg = _load_json_config_file(_kimi_config_path())
    file_timeout = file_cfg.get("timeout_s")
    timeout_s = KimiConfig.timeout_s
    try:
        if env_timeout:
            timeout_s = float(env_timeout)
        elif file_timeout is not None:
            timeout_s = float(file_timeout)
    except Exception:
        timeout_s = KimiConfig.timeout_s

    return KimiConfig(
        base_url=_clean_base_url(env_base_url or file_cfg.get("base_url") or KimiConfig.base_url),
        api_key=env_api_key,
        number_model=(
            project_number_model
            or env_number_model
            or str(file_cfg.get("question_number_model") or file_cfg.get("number_model") or file_cfg.get("model") or KimiConfig.number_model).strip()
        ),
        model=(project_unit_model or env_model or file_cfg.get("model") or KimiConfig.model).strip(),
        timeout_s=timeout_s,
    )


def save_kimi_config(cfg: KimiConfig) -> None:
    path = _kimi_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "base_url": _clean_base_url(cfg.base_url),
        "question_number_model": cfg.number_model.strip(),
        "model": cfg.model.strip(),
        "timeout_s": cfg.timeout_s,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def to_kimi_llm_config(cfg: KimiConfig) -> LlmConfig:
    from sj_generator.ai.client import LlmConfig

    return LlmConfig(
        base_url=_clean_base_url(cfg.base_url),
        api_key=cfg.api_key.strip(),
        model=cfg.model.strip(),
        timeout_s=float(cfg.timeout_s),
    )


def to_kimi_question_number_llm_config(cfg: KimiConfig) -> LlmConfig:
    from sj_generator.ai.client import LlmConfig

    return LlmConfig(
        base_url=_clean_base_url(cfg.base_url),
        api_key=cfg.api_key.strip(),
        model=cfg.number_model.strip(),
        timeout_s=float(cfg.timeout_s),
    )


def load_qwen_config() -> QwenConfig:
    env_base_url = os.getenv("QWEN_BASE_URL", "").strip()
    env_api_key = os.getenv("QWEN_API_KEY", "").strip()
    env_model = os.getenv("QWEN_QUESTION_UNIT_MODEL", "").strip() or os.getenv("QWEN_MODEL", "").strip()
    env_number_model = os.getenv("QWEN_QUESTION_NUMBER_MODEL", "").strip()
    env_account_access_key_id = (
        os.getenv("QWEN_ACCOUNT_ACCESS_KEY_ID", "").strip() or os.getenv("ALIBABA_CLOUD_ACCESS_KEY_ID", "").strip()
    )
    env_account_access_key_secret = (
        os.getenv("QWEN_ACCOUNT_ACCESS_KEY_SECRET", "").strip()
        or os.getenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET", "").strip()
    )
    env_timeout = os.getenv("QWEN_TIMEOUT_S", "").strip()
    project_number_model = project_parse_model_override("question_number_parse", "qwen")
    project_unit_model = project_parse_model_override("question_content_parse", "qwen")

    file_cfg = _load_json_config_file(_qwen_config_path())
    file_timeout = file_cfg.get("timeout_s")
    timeout_s = QwenConfig.timeout_s
    try:
        if env_timeout:
            timeout_s = float(env_timeout)
        elif file_timeout is not None:
            timeout_s = float(file_timeout)
    except Exception:
        timeout_s = QwenConfig.timeout_s

    return QwenConfig(
        base_url=_clean_base_url(env_base_url or file_cfg.get("base_url") or QwenConfig.base_url),
        api_key=env_api_key,
        number_model=(
            project_number_model
            or env_number_model
            or str(file_cfg.get("question_number_model") or file_cfg.get("number_model") or file_cfg.get("model") or QwenConfig.number_model).strip()
        ),
        model=(project_unit_model or env_model or file_cfg.get("model") or QwenConfig.model).strip(),
        account_access_key_id=env_account_access_key_id,
        account_access_key_secret=env_account_access_key_secret,
        timeout_s=timeout_s,
    )


def save_qwen_config(cfg: QwenConfig) -> None:
    path = _qwen_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "base_url": _clean_base_url(cfg.base_url),
        "question_number_model": cfg.number_model.strip(),
        "model": cfg.model.strip(),
        "timeout_s": cfg.timeout_s,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_welcome_table_column_visibility() -> dict[str, bool]:
    data = _load_welcome_view_config()
    raw = data.get("table_column_visibility")
    if not isinstance(raw, dict):
        return {}
    result: dict[str, bool] = {}
    for key, value in raw.items():
        if isinstance(key, str):
            result[key] = bool(value)
    return result


def save_welcome_table_column_visibility(visibility: dict[str, bool]) -> None:
    _save_welcome_view_config_values(
        {"table_column_visibility": {str(key): bool(value) for key, value in visibility.items()}}
    )


def load_welcome_table_font_point_size() -> int | None:
    data = _load_welcome_view_config()
    raw = data.get("table_font_point_size")
    try:
        value = int(raw)
    except Exception:
        return None
    return value if value > 0 else None


def save_welcome_table_font_point_size(point_size: int) -> None:
    try:
        value = int(point_size)
    except Exception:
        return
    if value <= 0:
        return
    _save_welcome_view_config_values({"table_font_point_size": value})


def load_welcome_tree_expanded_prefixes() -> list[str] | None:
    data = _load_welcome_view_config()
    raw = data.get("tree_expanded_prefixes")
    if raw is None:
        return None
    if not isinstance(raw, list):
        return []
    return [str(value).strip() for value in raw if str(value).strip()]


def save_welcome_tree_expanded_prefixes(prefixes: list[str]) -> None:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in prefixes:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    _save_welcome_view_config_values({"tree_expanded_prefixes": normalized})


def load_program_settings() -> dict:
    data = _load_json_config_file(_program_settings_path())
    return data if isinstance(data, dict) else {}


def save_program_settings(settings: dict) -> None:
    path = _program_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def save_program_analysis_target(*, provider: str, model_name: str) -> dict:
    data = load_program_settings()
    data["analysis_provider"] = str(provider or "").strip().lower() or "deepseek"
    data["analysis_model_name"] = str(model_name or "").strip() or "deepseek-reasoner"
    save_program_settings(data)
    return data


_PROJECT_PARSE_ROW_KEYS = ("question_number_parse", "question_content_parse")


def default_project_parse_model_rows() -> list[dict]:
    return [
        {"key": "question_number_parse", "round": "1", "ratio": "1/4", "models": []},
        {"key": "question_content_parse", "round": "2", "ratio": "1/4", "models": []},
    ]


def load_project_parse_model_rows() -> list[dict]:
    data = load_program_settings()
    return normalize_project_parse_model_rows(data.get("project_parse_model_rows"))


def save_project_parse_model_rows(rows: list[dict]) -> dict:
    data = load_program_settings()
    data["project_parse_model_rows"] = normalize_project_parse_model_rows(rows)
    save_program_settings(data)
    return data


def normalize_project_parse_model_rows(rows: object) -> list[dict]:
    raw_rows = rows if isinstance(rows, list) else []
    normalized: list[dict] = []
    defaults = default_project_parse_model_rows()
    for index, key in enumerate(_PROJECT_PARSE_ROW_KEYS):
        raw = raw_rows[index] if index < len(raw_rows) and isinstance(raw_rows[index], dict) else {}
        default_row = defaults[index]
        round_value = str(raw.get("round") or default_row["round"]).strip()
        if round_value not in {"1", "2", "3", "4", "5"}:
            round_value = default_row["round"]
        ratio_value = str(raw.get("ratio") or default_row["ratio"]).strip() or default_row["ratio"]
        normalized.append(
            {
                "key": key,
                "round": round_value,
                "ratio": ratio_value,
                "models": _normalize_project_parse_models(raw.get("models")),
            }
        )
    return normalized


def project_parse_model_override(row_key: str, provider: str) -> str:
    provider_key = _normalize_project_model_provider(provider)
    for row in load_project_parse_model_rows():
        if str(row.get("key") or "").strip() != row_key:
            continue
        for item in row.get("models") or []:
            if str(item.get("provider") or "").strip() == provider_key:
                return str(item.get("model_name") or "").strip()
    return ""


def _normalize_project_parse_models(models: object) -> list[dict]:
    raw_models = models if isinstance(models, list) else []
    normalized: list[dict] = []
    for raw in raw_models[:8]:
        if not isinstance(raw, dict):
            continue
        provider = _normalize_project_model_provider(raw.get("provider"))
        model_name = str(raw.get("model_name") or "").strip()
        if not provider or not model_name:
            continue
        normalized.append({"provider": provider, "model_name": model_name})
    return normalized


def _normalize_project_model_provider(value: object) -> str:
    raw = str(value or "").strip().lower()
    aliases = {
        "deepseek": "deepseek",
        "deep seek": "deepseek",
        "kimi": "kimi",
        "moonshot": "kimi",
        "qwen": "qwen",
        "千问": "qwen",
    }
    return aliases.get(raw, "")


def to_qwen_llm_config(cfg: QwenConfig) -> LlmConfig:
    from sj_generator.ai.client import LlmConfig

    return LlmConfig(
        base_url=_clean_base_url(cfg.base_url),
        api_key=cfg.api_key.strip(),
        model=cfg.model.strip(),
        timeout_s=float(cfg.timeout_s),
    )


def to_qwen_question_number_llm_config(cfg: QwenConfig) -> LlmConfig:
    from sj_generator.ai.client import LlmConfig

    return LlmConfig(
        base_url=_clean_base_url(cfg.base_url),
        api_key=cfg.api_key.strip(),
        model=cfg.number_model.strip(),
        timeout_s=float(cfg.timeout_s),
    )


def sync_deepseek_runtime_env(cfg: DeepSeekConfig) -> None:
    set_user_environment_variable("DEEPSEEK_BASE_URL", _clean_base_url(cfg.base_url))
    set_user_environment_variable("DEEPSEEK_API_KEY", cfg.api_key.strip())
    set_user_environment_variable("DEEPSEEK_QUESTION_NUMBER_MODEL", cfg.number_model.strip())
    set_user_environment_variable("DEEPSEEK_QUESTION_UNIT_MODEL", cfg.model.strip())
    set_user_environment_variable("DEEPSEEK_MODEL", cfg.model.strip())
    set_user_environment_variable("DEEPSEEK_ANALYSIS_MODEL", cfg.analysis_model.strip())
    set_user_environment_variable("DEEPSEEK_TIMEOUT_S", str(float(cfg.timeout_s)))


def sync_kimi_runtime_env(cfg: KimiConfig) -> None:
    set_user_environment_variable("KIMI_BASE_URL", _clean_base_url(cfg.base_url))
    set_user_environment_variable("KIMI_API_KEY", cfg.api_key.strip())
    set_user_environment_variable("KIMI_QUESTION_NUMBER_MODEL", cfg.number_model.strip())
    set_user_environment_variable("KIMI_QUESTION_UNIT_MODEL", cfg.model.strip())
    set_user_environment_variable("KIMI_MODEL", cfg.model.strip())
    set_user_environment_variable("KIMI_TIMEOUT_S", str(float(cfg.timeout_s)))


def sync_qwen_runtime_env(cfg: QwenConfig) -> None:
    set_user_environment_variable("QWEN_BASE_URL", _clean_base_url(cfg.base_url))
    set_user_environment_variable("QWEN_API_KEY", cfg.api_key.strip())
    set_user_environment_variable("QWEN_QUESTION_NUMBER_MODEL", cfg.number_model.strip())
    set_user_environment_variable("QWEN_QUESTION_UNIT_MODEL", cfg.model.strip())
    set_user_environment_variable("QWEN_MODEL", cfg.model.strip())
    set_user_environment_variable("QWEN_TIMEOUT_S", str(float(cfg.timeout_s)))
    set_user_environment_variable("QWEN_ACCOUNT_ACCESS_KEY_ID", cfg.account_access_key_id.strip())
    set_user_environment_variable("QWEN_ACCOUNT_ACCESS_KEY_SECRET", cfg.account_access_key_secret.strip())
    # Keep the ali-cloud aliases in sync for current-user usage.
    set_user_environment_variable("ALIBABA_CLOUD_ACCESS_KEY_ID", cfg.account_access_key_id.strip())
    set_user_environment_variable("ALIBABA_CLOUD_ACCESS_KEY_SECRET", cfg.account_access_key_secret.strip())


def set_user_environment_variable(name: str, value: str) -> None:
    value = (value or "").strip()
    if value:
        os.environ[name] = value
    else:
        os.environ.pop(name, None)

    if sys.platform != "win32":
        return

    import ctypes
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as key:
        if value:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        else:
            try:
                winreg.DeleteValue(key, name)
            except FileNotFoundError:
                pass

    HWND_BROADCAST = 0xFFFF
    WM_SETTINGCHANGE = 0x001A
    # Use async notify to avoid freezing the UI while other windows process the broadcast.
    ctypes.windll.user32.SendNotifyMessageW(
        HWND_BROADCAST,
        WM_SETTINGCHANGE,
        0,
        "Environment",
    )


def _config_path() -> Path:
    env = os.getenv("SJ_GENERATOR_CONFIG_PATH", "").strip()
    if env:
        return Path(env)
    return _default_config_dir() / "deepseek.json"


def _kimi_config_path() -> Path:
    env = os.getenv("SJ_GENERATOR_KIMI_CONFIG_PATH", "").strip()
    if env:
        return Path(env)
    return _default_config_dir() / "kimi.json"


def _qwen_config_path() -> Path:
    env = os.getenv("SJ_GENERATOR_QWEN_CONFIG_PATH", "").strip()
    if env:
        return Path(env)
    return _default_config_dir() / "qwen.json"


def _welcome_view_config_path() -> Path:
    env = os.getenv("SJ_GENERATOR_WELCOME_VIEW_CONFIG_PATH", "").strip()
    if env:
        return Path(env)
    return _default_config_dir() / "welcome_view.json"


def _program_settings_path() -> Path:
    env = os.getenv("SJ_GENERATOR_PROGRAM_SETTINGS_PATH", "").strip()
    if env:
        return Path(env)
    return _default_config_dir() / "program_settings.json"


def _load_welcome_view_config() -> dict:
    return _load_json_config_file(_welcome_view_config_path())


def _save_welcome_view_config_values(values: dict) -> None:
    path = _welcome_view_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _load_json_config_file(path)
    data.update(values)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_json_config_file(path: Path) -> dict:
    if not path.exists():
        legacy = _legacy_config_path(path.name)
        if legacy is not None and legacy.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            data = _read_json_dict(legacy)
            if data:
                path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                return data
        return {}
    return _read_json_dict(path)


def _clean_base_url(url: str) -> str:
    s = (url or "").strip()
    s = s.strip("`").strip('"').strip("'").strip()
    if s.endswith("/"):
        s = s[:-1]
    return s


def _default_config_dir() -> Path:
    app_data = os.getenv("APPDATA", "").strip()
    if app_data:
        return Path(app_data) / "sj_generator"
    return Path.home() / ".sj_generator"


def _legacy_config_path(file_name: str) -> Path | None:
    base_dir = Path(__file__).resolve().parents[1]
    path = base_dir / ".local" / file_name
    return path if path.exists() else None


def _read_json_dict(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if isinstance(data, dict):
        return data
    return {}
