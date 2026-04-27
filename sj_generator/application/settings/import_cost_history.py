from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation

from sj_generator.application.settings.storage import import_cost_history_path, load_json_config_file, save_json_config_file

_MAX_IMPORT_COST_HISTORY_ROWS = 200
_PROVIDER_KEYS = ("deepseek", "kimi", "qwen")


def load_import_cost_history_rows(*, limit: int | None = None) -> list[dict[str, str]]:
    data = load_json_config_file(import_cost_history_path())
    raw_rows = data.get("rows")
    if not isinstance(raw_rows, list):
        return []
    rows = [_normalize_history_row(item) for item in raw_rows if isinstance(item, dict)]
    rows = _coalesce_same_run_rows([item for item in rows if item])
    _save_history_rows(rows)
    rows.reverse()
    if limit is not None and limit > 0:
        rows = rows[:limit]
    return rows


def append_import_cost_history_entry(
    *,
    run_at: str | None = None,
    source_label: str = "",
    before_provider_balances: dict[str, str] | None = None,
    provider_balances: dict[str, str] | None = None,
    total_balance: str = "",
    total_cost: str = "",
    cost_summary: str = "",
    cost_detail: str = "",
) -> dict[str, str]:
    data = load_json_config_file(import_cost_history_path())
    raw_rows = data.get("rows")
    rows = [item for item in raw_rows if isinstance(item, dict)] if isinstance(raw_rows, list) else []
    rows = _coalesce_same_run_rows([_normalize_history_row(item) for item in rows])
    entry = _normalize_history_row(
        {
            "run_at": _format_run_at_text(run_at=run_at, source_label=source_label),
            "deepseek_balance": str((provider_balances or {}).get("deepseek") or ""),
            "kimi_balance": str((provider_balances or {}).get("kimi") or ""),
            "qwen_balance": str((provider_balances or {}).get("qwen") or ""),
        }
    )
    if rows and str(rows[-1].get("run_at") or "").strip() == entry["run_at"]:
        rows[-1] = _prefer_history_row(rows[-1], entry)
        entry = rows[-1]
    else:
        rows.append(entry)
    if len(rows) > _MAX_IMPORT_COST_HISTORY_ROWS:
        rows = rows[-_MAX_IMPORT_COST_HISTORY_ROWS :]
    _save_history_rows(rows)
    return entry


def append_balance_history_for_provider_results(
    results: list[tuple[str, dict[str, object]]],
    *,
    source_label: str = "",
) -> None:
    provider_balances: dict[str, str] = {}
    for provider_key, result in results:
        provider = str(provider_key or "").strip().lower()
        if provider not in _PROVIDER_KEYS:
            continue
        if not isinstance(result, dict):
            continue
        provider_balances[provider] = str(result.get("balance_value") or "").strip()
    if not any(provider_balances.values()):
        return
    append_import_cost_history_entry(provider_balances=provider_balances, source_label=source_label)


def clear_import_cost_history() -> None:
    _save_history_rows([])


def _format_run_at_text(*, run_at: str | None, source_label: str) -> str:
    base = str(run_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")).strip()
    label = str(source_label or "").strip()
    if not label:
        return base
    if base.endswith(f" [{label}]"):
        return base
    return f"{base} [{label}]"


def _save_history_rows(rows: list[dict[str, str]]) -> None:
    save_json_config_file(import_cost_history_path(), {"rows": rows})


def build_total_balance_text(provider_balances: dict[str, str]) -> str:
    totals_by_currency: dict[str, Decimal] = {}
    text_parts: list[str] = []
    for provider in _PROVIDER_KEYS:
        balance_text = str((provider_balances or {}).get(provider) or "").strip()
        amount, currency = _parse_amount_text(balance_text)
        if amount is None or not currency:
            continue
        totals_by_currency[currency] = totals_by_currency.get(currency, Decimal("0")) + amount
    if totals_by_currency:
        for currency, amount in sorted(totals_by_currency.items(), key=lambda item: item[0]):
            prefix = {"CNY": "¥", "USD": "$"}.get(currency, "")
            text_parts.append(f"{prefix}{amount:.4f}" if prefix else f"{currency} {amount:.4f}")
    if text_parts:
        return "；".join(text_parts)
    values = [str((provider_balances or {}).get(provider) or "").strip() for provider in _PROVIDER_KEYS]
    values = [value for value in values if value]
    return "；".join(values) if values else ""


def _normalize_history_row(row: dict) -> dict[str, str]:
    return {
        "run_at": str(row.get("run_at") or "").strip(),
        "deepseek_balance": str(row.get("deepseek_balance") or "").strip(),
        "kimi_balance": str(row.get("kimi_balance") or "").strip(),
        "qwen_balance": str(row.get("qwen_balance") or "").strip(),
    }


def _coalesce_same_run_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    merged: list[dict[str, str]] = []
    for row in rows:
        if not merged:
            merged.append(row)
            continue
        if str(merged[-1].get("run_at") or "").strip() == str(row.get("run_at") or "").strip():
            merged[-1] = _prefer_history_row(merged[-1], row)
            continue
        merged.append(row)
    return merged


def _prefer_history_row(left: dict[str, str], right: dict[str, str]) -> dict[str, str]:
    left_score = _history_row_score(left)
    right_score = _history_row_score(right)
    return right if right_score >= left_score else left


def _history_row_score(row: dict[str, str]) -> tuple[int, int]:
    provider_values = [
        str(row.get("deepseek_balance") or "").strip(),
        str(row.get("kimi_balance") or "").strip(),
        str(row.get("qwen_balance") or "").strip(),
    ]
    non_empty_provider_count = sum(1 for value in provider_values if value)
    non_zero_provider_count = sum(1 for value in provider_values if _is_non_zero_amount_text(value))
    return (
        non_empty_provider_count,
        non_zero_provider_count,
    )


def _is_non_zero_amount_text(text: str) -> bool:
    amount, _currency = _parse_amount_text(text)
    return amount is not None and amount != Decimal("0")


def _parse_amount_text(text: str) -> tuple[Decimal | None, str]:
    value = str(text or "").strip()
    if not value:
        return None, ""
    currency = "CNY" if value.startswith("¥") else "USD" if value.startswith("$") else ""
    if not currency and " " in value:
        prefix, _, remainder = value.partition(" ")
        currency = prefix.strip().upper()
        value = remainder.strip()
    elif currency:
        value = value[1:].strip()
    try:
        return Decimal(value), currency
    except (InvalidOperation, ValueError):
        return None, ""
