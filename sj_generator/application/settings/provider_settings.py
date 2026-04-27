from __future__ import annotations

import os
import sys
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from sj_generator.application.settings.project_parse_settings import project_parse_model_override
from sj_generator.application.settings.storage import (
    clean_base_url,
    deepseek_config_path,
    kimi_config_path,
    load_json_config_file,
    provider_config_path,
    qwen_config_path,
    save_json_config_file,
)

if TYPE_CHECKING:
    from sj_generator.infrastructure.llm.client import LlmConfig


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


_DEFAULT_AVAILABLE_MODELS: dict[str, list[str]] = {
    "deepseek": ["deepseek-v4-pro", "deepseek-chat", "deepseek-reasoner"],
    "kimi": [
        "kimi-k2.6",
        "kimi-k2.5",
        "kimi-k2-thinking",
        "kimi-k2-thinking-turbo",
        "kimi-k2-0905-preview",
        "kimi-k2-0711-preview",
        "kimi-k2-turbo-preview",
        "moonshot-v1-32k",
        "moonshot-v1-8k",
        "moonshot-v1-128k",
    ],
    "qwen": [
        "qwen-max",
        "qwen-max-latest",
        "qwen3.6-plus",
        "qwen3.5-plus",
        "qwen-plus",
        "qwen-turbo",
        "qwen-long",
        "qwen-deep-research",
        "qwen-ocr",
        "gui-plus",
    ],
}


def with_capped_timeout(cfg, max_timeout_s: float):
    capped_timeout_s = min(float(getattr(cfg, "timeout_s", max_timeout_s)), float(max_timeout_s))
    if float(getattr(cfg, "timeout_s", capped_timeout_s)) <= capped_timeout_s:
        return cfg
    return replace(cfg, timeout_s=capped_timeout_s)


def load_deepseek_config() -> DeepSeekConfig:
    env_base_url = os.getenv("DEEPSEEK_BASE_URL", "").strip()
    env_api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    env_model = os.getenv("DEEPSEEK_QUESTION_UNIT_MODEL", "").strip() or os.getenv("DEEPSEEK_MODEL", "").strip()
    env_number_model = os.getenv("DEEPSEEK_QUESTION_NUMBER_MODEL", "").strip()
    env_analysis_model = os.getenv("DEEPSEEK_ANALYSIS_MODEL", "").strip()
    env_timeout = os.getenv("DEEPSEEK_TIMEOUT_S", "").strip()
    project_number_model = project_parse_model_override("question_number_parse", "deepseek")
    project_unit_model = project_parse_model_override("question_content_parse", "deepseek")

    file_cfg = load_json_config_file(deepseek_config_path())
    file_timeout = file_cfg.get("timeout_s")
    timeout_s = DeepSeekConfig.timeout_s
    try:
        if env_timeout:
            timeout_s = float(env_timeout)
        elif file_timeout is not None:
            timeout_s = float(file_timeout)
    except Exception:
        timeout_s = DeepSeekConfig.timeout_s

    return DeepSeekConfig(
        base_url=clean_base_url(env_base_url or file_cfg.get("base_url") or DeepSeekConfig.base_url),
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


def save_deepseek_config(cfg: DeepSeekConfig) -> None:
    path = deepseek_config_path()
    data = load_json_config_file(path)
    data.pop("api_key", None)
    data.update(
        {
            "base_url": cfg.base_url.strip(),
            "question_number_model": cfg.number_model.strip(),
            "model": cfg.model.strip(),
            "analysis_model": cfg.analysis_model.strip(),
            "timeout_s": cfg.timeout_s,
        }
    )
    save_json_config_file(path, data)


def to_llm_config(cfg: DeepSeekConfig) -> LlmConfig:
    from sj_generator.infrastructure.llm.client import LlmConfig

    return LlmConfig(
        base_url=cfg.base_url.strip(),
        api_key=cfg.api_key.strip(),
        model=cfg.model.strip(),
        timeout_s=float(cfg.timeout_s),
    )


def to_question_number_llm_config(cfg: DeepSeekConfig) -> LlmConfig:
    from sj_generator.infrastructure.llm.client import LlmConfig

    return LlmConfig(
        base_url=cfg.base_url.strip(),
        api_key=cfg.api_key.strip(),
        model=cfg.number_model.strip(),
        timeout_s=float(cfg.timeout_s),
    )


def to_analysis_llm_config(cfg: DeepSeekConfig) -> LlmConfig:
    from sj_generator.infrastructure.llm.client import LlmConfig

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

    file_cfg = load_json_config_file(kimi_config_path())
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
        base_url=clean_base_url(env_base_url or file_cfg.get("base_url") or KimiConfig.base_url),
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
    path = kimi_config_path()
    data = load_json_config_file(path)
    data.pop("api_key", None)
    data.update(
        {
            "base_url": clean_base_url(cfg.base_url),
            "question_number_model": cfg.number_model.strip(),
            "model": cfg.model.strip(),
            "timeout_s": cfg.timeout_s,
        }
    )
    save_json_config_file(path, data)


def to_kimi_llm_config(cfg: KimiConfig) -> LlmConfig:
    from sj_generator.infrastructure.llm.client import LlmConfig

    return LlmConfig(
        base_url=clean_base_url(cfg.base_url),
        api_key=cfg.api_key.strip(),
        model=cfg.model.strip(),
        timeout_s=float(cfg.timeout_s),
    )


def to_kimi_question_number_llm_config(cfg: KimiConfig) -> LlmConfig:
    from sj_generator.infrastructure.llm.client import LlmConfig

    return LlmConfig(
        base_url=clean_base_url(cfg.base_url),
        api_key=cfg.api_key.strip(),
        model=cfg.number_model.strip(),
        timeout_s=float(cfg.timeout_s),
    )


def load_qwen_config() -> QwenConfig:
    env_base_url = os.getenv("QWEN_BASE_URL", "").strip()
    env_api_key = os.getenv("QWEN_API_KEY", "").strip()
    env_model = os.getenv("QWEN_QUESTION_UNIT_MODEL", "").strip() or os.getenv("QWEN_MODEL", "").strip()
    env_number_model = os.getenv("QWEN_QUESTION_NUMBER_MODEL", "").strip()
    env_account_access_key_id = os.getenv("QWEN_ACCOUNT_ACCESS_KEY_ID", "").strip() or os.getenv("ALIBABA_CLOUD_ACCESS_KEY_ID", "").strip()
    env_account_access_key_secret = os.getenv("QWEN_ACCOUNT_ACCESS_KEY_SECRET", "").strip() or os.getenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET", "").strip()
    env_timeout = os.getenv("QWEN_TIMEOUT_S", "").strip()
    project_number_model = project_parse_model_override("question_number_parse", "qwen")
    project_unit_model = project_parse_model_override("question_content_parse", "qwen")

    file_cfg = load_json_config_file(qwen_config_path())
    file_timeout = file_cfg.get("timeout_s")
    timeout_s = QwenConfig.timeout_s
    try:
        if file_timeout is not None:
            timeout_s = float(file_timeout)
        elif env_timeout:
            timeout_s = float(env_timeout)
    except Exception:
        timeout_s = QwenConfig.timeout_s

    return QwenConfig(
        base_url=clean_base_url(file_cfg.get("base_url") or env_base_url or QwenConfig.base_url),
        api_key=str(file_cfg.get("api_key") or "").strip() or env_api_key,
        number_model=(
            project_number_model
            or str(file_cfg.get("question_number_model") or file_cfg.get("number_model") or file_cfg.get("model") or "").strip()
            or env_number_model
            or QwenConfig.number_model
        ),
        model=(project_unit_model or str(file_cfg.get("model") or "").strip() or env_model or QwenConfig.model).strip(),
        account_access_key_id=str(file_cfg.get("account_access_key_id") or "").strip() or env_account_access_key_id,
        account_access_key_secret=str(file_cfg.get("account_access_key_secret") or "").strip() or env_account_access_key_secret,
        timeout_s=timeout_s,
    )


def save_qwen_config(cfg: QwenConfig) -> None:
    path = qwen_config_path()
    data = load_json_config_file(path)
    data.update(
        {
            "base_url": clean_base_url(cfg.base_url),
            "api_key": cfg.api_key.strip(),
            "question_number_model": cfg.number_model.strip(),
            "model": cfg.model.strip(),
            "account_access_key_id": cfg.account_access_key_id.strip(),
            "account_access_key_secret": cfg.account_access_key_secret.strip(),
            "timeout_s": cfg.timeout_s,
        }
    )
    save_json_config_file(path, data)


def to_qwen_llm_config(cfg: QwenConfig) -> LlmConfig:
    from sj_generator.infrastructure.llm.client import LlmConfig

    return LlmConfig(
        base_url=clean_base_url(cfg.base_url),
        api_key=cfg.api_key.strip(),
        model=cfg.model.strip(),
        timeout_s=float(cfg.timeout_s),
    )


def to_qwen_question_number_llm_config(cfg: QwenConfig) -> LlmConfig:
    from sj_generator.infrastructure.llm.client import LlmConfig

    return LlmConfig(
        base_url=clean_base_url(cfg.base_url),
        api_key=cfg.api_key.strip(),
        model=cfg.number_model.strip(),
        timeout_s=float(cfg.timeout_s),
    )


def default_available_models(provider: str) -> list[str]:
    key = str(provider or "").strip().lower()
    return list(_DEFAULT_AVAILABLE_MODELS.get(key, []))


def normalize_available_models(models: object, provider: str) -> list[str]:
    default_models = default_available_models(provider)
    if not isinstance(models, list):
        return default_models
    normalized: list[str] = []
    seen: set[str] = set()
    for item in models:
        model_name = str(item or "").strip()
        if not model_name:
            continue
        key = model_name.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(model_name)
    return normalized or default_models


def load_available_models(provider: str) -> list[str]:
    path = provider_config_path(provider)
    data = load_json_config_file(path)
    return normalize_available_models(data.get("available_models"), provider)


def save_available_models(provider: str, models: list[str]) -> list[str]:
    normalized = normalize_available_models(models, provider)
    path = provider_config_path(provider)
    data = load_json_config_file(path)
    data["available_models"] = normalized
    save_json_config_file(path, data)
    return normalized


def sync_deepseek_runtime_env(cfg: DeepSeekConfig) -> None:
    set_user_environment_variable("DEEPSEEK_BASE_URL", clean_base_url(cfg.base_url))
    set_user_environment_variable("DEEPSEEK_API_KEY", cfg.api_key.strip())
    set_user_environment_variable("DEEPSEEK_QUESTION_NUMBER_MODEL", cfg.number_model.strip())
    set_user_environment_variable("DEEPSEEK_QUESTION_UNIT_MODEL", cfg.model.strip())
    set_user_environment_variable("DEEPSEEK_MODEL", cfg.model.strip())
    set_user_environment_variable("DEEPSEEK_ANALYSIS_MODEL", cfg.analysis_model.strip())
    set_user_environment_variable("DEEPSEEK_TIMEOUT_S", str(float(cfg.timeout_s)))


def sync_kimi_runtime_env(cfg: KimiConfig) -> None:
    set_user_environment_variable("KIMI_BASE_URL", clean_base_url(cfg.base_url))
    set_user_environment_variable("KIMI_API_KEY", cfg.api_key.strip())
    set_user_environment_variable("KIMI_QUESTION_NUMBER_MODEL", cfg.number_model.strip())
    set_user_environment_variable("KIMI_QUESTION_UNIT_MODEL", cfg.model.strip())
    set_user_environment_variable("KIMI_MODEL", cfg.model.strip())
    set_user_environment_variable("KIMI_TIMEOUT_S", str(float(cfg.timeout_s)))


def sync_qwen_runtime_env(cfg: QwenConfig) -> None:
    set_user_environment_variable("QWEN_BASE_URL", clean_base_url(cfg.base_url))
    set_user_environment_variable("QWEN_API_KEY", cfg.api_key.strip())
    set_user_environment_variable("QWEN_QUESTION_NUMBER_MODEL", cfg.number_model.strip())
    set_user_environment_variable("QWEN_QUESTION_UNIT_MODEL", cfg.model.strip())
    set_user_environment_variable("QWEN_MODEL", cfg.model.strip())
    set_user_environment_variable("QWEN_TIMEOUT_S", str(float(cfg.timeout_s)))
    set_user_environment_variable("QWEN_ACCOUNT_ACCESS_KEY_ID", cfg.account_access_key_id.strip())
    set_user_environment_variable("QWEN_ACCOUNT_ACCESS_KEY_SECRET", cfg.account_access_key_secret.strip())
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
    ctypes.windll.user32.SendNotifyMessageW(HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment")
