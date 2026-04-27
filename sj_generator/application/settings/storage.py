from __future__ import annotations

import json
import os
from pathlib import Path


def clean_base_url(url: str) -> str:
    value = (url or "").strip()
    value = value.strip("`").strip('"').strip("'").strip()
    if value.endswith("/"):
        value = value[:-1]
    return value


def default_config_dir() -> Path:
    app_data = os.getenv("APPDATA", "").strip()
    if app_data:
        return Path(app_data) / "sj_generator"
    return Path.home() / ".sj_generator"


def legacy_config_path(file_name: str) -> Path | None:
    base_dir = Path(__file__).resolve().parents[3]
    path = base_dir / ".local" / file_name
    return path if path.exists() else None


def read_json_dict(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def load_json_config_file(path: Path) -> dict:
    if not path.exists():
        legacy = legacy_config_path(path.name)
        if legacy is not None and legacy.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            data = read_json_dict(legacy)
            if data:
                path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                return data
        return {}
    return read_json_dict(path)


def save_json_config_file(path: Path, data: dict) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def merge_json_config_values(path: Path, values: dict) -> dict:
    data = load_json_config_file(path)
    data.update(values)
    return save_json_config_file(path, data)


def deepseek_config_path() -> Path:
    env = os.getenv("SJ_GENERATOR_CONFIG_PATH", "").strip()
    return Path(env) if env else default_config_dir() / "deepseek.json"


def kimi_config_path() -> Path:
    env = os.getenv("SJ_GENERATOR_KIMI_CONFIG_PATH", "").strip()
    return Path(env) if env else default_config_dir() / "kimi.json"


def qwen_config_path() -> Path:
    env = os.getenv("SJ_GENERATOR_QWEN_CONFIG_PATH", "").strip()
    return Path(env) if env else default_config_dir() / "qwen.json"


def provider_config_path(provider: str) -> Path:
    key = str(provider or "").strip().lower()
    if key == "kimi":
        return kimi_config_path()
    if key == "qwen":
        return qwen_config_path()
    return deepseek_config_path()


def welcome_view_config_path() -> Path:
    env = os.getenv("SJ_GENERATOR_WELCOME_VIEW_CONFIG_PATH", "").strip()
    return Path(env) if env else default_config_dir() / "welcome_view.json"


def program_settings_path() -> Path:
    env = os.getenv("SJ_GENERATOR_PROGRAM_SETTINGS_PATH", "").strip()
    return Path(env) if env else default_config_dir() / "program_settings.json"


def import_cost_history_path() -> Path:
    env = os.getenv("SJ_GENERATOR_IMPORT_COST_HISTORY_PATH", "").strip()
    return Path(env) if env else default_config_dir() / "import_cost_history.json"
