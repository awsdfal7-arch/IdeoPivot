from __future__ import annotations

from decimal import Decimal
from datetime import datetime
import threading

from sj_generator.application.settings.import_cost_history import append_import_cost_history_entry, build_total_balance_text
from sj_generator.infrastructure.llm.import_questions import question_content_model_specs
from sj_generator.infrastructure.llm.question_ref_scan import question_ref_model_specs
from sj_generator.infrastructure.llm.balance import query_provider_balance_snapshots
from sj_generator.application.settings import load_deepseek_config, load_kimi_config, load_qwen_config
from sj_generator.application.state import ImportWizardSession

_APP_IMPORT_COST_LOCK = threading.Lock()
_APP_IMPORT_COST_THREAD: threading.Thread | None = None
_APP_IMPORT_COST_SNAPSHOTS: list = []
_APP_IMPORT_COST_LOADING = False
_APP_IMPORT_COST_STARTED = False
_APP_IMPORT_COST_STARTUP_LOGGED = False


def _format_cost_amount_text(currency: str, amount: Decimal) -> str:
    prefix = {"CNY": "¥", "USD": "$"}.get((currency or "").upper(), "")
    if prefix:
        return f"{prefix}{amount:.4f}"
    return f"{(currency or 'UNKNOWN').upper()} {amount:.4f}"


def _query_import_cost_before_snapshots() -> list:
    return query_provider_balance_snapshots(
        deepseek_cfg=load_deepseek_config(),
        kimi_cfg=load_kimi_config(),
        qwen_cfg=load_qwen_config(),
    )


def begin_app_import_cost_capture(*, retry_if_empty: bool = False) -> None:
    global _APP_IMPORT_COST_THREAD, _APP_IMPORT_COST_LOADING, _APP_IMPORT_COST_STARTED, _APP_IMPORT_COST_SNAPSHOTS
    with _APP_IMPORT_COST_LOCK:
        has_snapshots = bool(_APP_IMPORT_COST_SNAPSHOTS)
        if _APP_IMPORT_COST_LOADING:
            return
        if _APP_IMPORT_COST_STARTED and (has_snapshots or not retry_if_empty):
            return
        _APP_IMPORT_COST_LOADING = True
        _APP_IMPORT_COST_STARTED = True
        _APP_IMPORT_COST_SNAPSHOTS = []

        def worker() -> None:
            global _APP_IMPORT_COST_THREAD, _APP_IMPORT_COST_LOADING, _APP_IMPORT_COST_SNAPSHOTS, _APP_IMPORT_COST_STARTUP_LOGGED
            try:
                snapshots = _query_import_cost_before_snapshots()
            except Exception:
                snapshots = []
            should_append_startup_log = False
            with _APP_IMPORT_COST_LOCK:
                _APP_IMPORT_COST_SNAPSHOTS = list(snapshots)
                _APP_IMPORT_COST_LOADING = False
                _APP_IMPORT_COST_THREAD = None
                if snapshots and not _APP_IMPORT_COST_STARTUP_LOGGED:
                    _APP_IMPORT_COST_STARTUP_LOGGED = True
                    should_append_startup_log = True
            if should_append_startup_log:
                _append_startup_balance_history(snapshots)

        thread = threading.Thread(target=worker, name="app-import-cost-before", daemon=True)
        _APP_IMPORT_COST_THREAD = thread
    thread.start()


def _set_state_import_cost_before_snapshots(state: ImportWizardSession, snapshots: list) -> None:
    state.execution.import_cost_before_amounts = {
        snapshot.provider: f"{snapshot.currency}|{snapshot.amount}"
        for snapshot in snapshots
    }
    state.execution.import_cost_before_details = {snapshot.provider: snapshot.detail for snapshot in snapshots}


def _apply_app_import_cost_capture_to_state(state: ImportWizardSession) -> None:
    with _APP_IMPORT_COST_LOCK:
        snapshots = list(_APP_IMPORT_COST_SNAPSHOTS)
        loading = bool(_APP_IMPORT_COST_LOADING)
        thread = _APP_IMPORT_COST_THREAD
    if loading:
        state.execution.import_cost_before_loading = True
        state.execution.import_cost_capture_thread = thread
        return
    _set_state_import_cost_before_snapshots(state, snapshots)
    state.execution.import_cost_before_loading = False
    state.execution.import_cost_capture_thread = None


def _wait_app_import_cost_capture() -> None:
    with _APP_IMPORT_COST_LOCK:
        thread = _APP_IMPORT_COST_THREAD
    if thread is None:
        return
    if thread is threading.current_thread():
        return
    thread.join()


def _update_app_import_cost_snapshots(snapshots: list) -> None:
    global _APP_IMPORT_COST_SNAPSHOTS, _APP_IMPORT_COST_LOADING, _APP_IMPORT_COST_THREAD, _APP_IMPORT_COST_STARTED
    with _APP_IMPORT_COST_LOCK:
        _APP_IMPORT_COST_SNAPSHOTS = list(snapshots)
        _APP_IMPORT_COST_LOADING = False
        _APP_IMPORT_COST_THREAD = None
        _APP_IMPORT_COST_STARTED = True


def _append_startup_balance_history(snapshots: list) -> None:
    provider_balances = _build_after_provider_balances(snapshots)
    if not provider_balances:
        return
    append_import_cost_history_entry(
        run_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        source_label="启动",
        provider_balances=provider_balances,
    )


def capture_import_cost_before(state: ImportWizardSession) -> None:
    state.execution.reset_import_cost_tracking()
    begin_app_import_cost_capture()
    _wait_app_import_cost_capture()
    _apply_app_import_cost_capture_to_state(state)


def capture_import_cost_before_async(state: ImportWizardSession) -> None:
    state.execution.reset_import_cost_tracking()
    begin_app_import_cost_capture()
    _apply_app_import_cost_capture_to_state(state)


def wait_import_cost_before_capture(state: ImportWizardSession) -> None:
    _wait_app_import_cost_capture()
    _apply_app_import_cost_capture_to_state(state)

def freeze_import_cost_result(state: ImportWizardSession) -> None:
    if state.execution.import_cost_ready:
        return
    state.execution.import_cost_ready = True
    begin_app_import_cost_capture()
    wait_import_cost_before_capture(state)
    state.execution.import_cost_total_text = ""
    state.execution.import_cost_summary_text = ""
    state.execution.import_cost_detail_text = ""
    used_models = _collect_import_used_models()
    before_amounts = dict(getattr(state.execution, "import_cost_before_amounts", {}) or {})
    after_snapshots = query_provider_balance_snapshots(
        deepseek_cfg=load_deepseek_config(),
        kimi_cfg=load_kimi_config(),
        qwen_cfg=load_qwen_config(),
    )
    if not before_amounts:
        state.execution.import_cost_detail_text = "未记录导入前余额，无法计算本次 docx 解析费用。"
        state.execution.import_cost_rows = _build_unavailable_rows(
            used_models,
            before_text="未记录",
            current_text="未查询" if not after_snapshots else "已记录到下方日志",
            cost_text="无法计算",
        )
        _append_import_cost_history(
            before_amounts,
            after_snapshots,
            total_cost="",
            cost_summary="",
            cost_detail=state.execution.import_cost_detail_text,
        )
        if after_snapshots:
            _update_app_import_cost_snapshots(after_snapshots)
        return
    if not after_snapshots:
        state.execution.import_cost_detail_text = "未获取到导入后余额，无法计算本次 docx 解析费用。"
        state.execution.import_cost_rows = _build_unavailable_rows(
            used_models,
            before_text="已记录",
            current_text="未获取",
            cost_text="无法计算",
        )
        _append_import_cost_history(
            before_amounts,
            after_snapshots,
            total_cost="",
            cost_summary="",
            cost_detail=state.execution.import_cost_detail_text,
        )
        return
    after_map = {snapshot.provider: snapshot for snapshot in after_snapshots}
    deltas: list[tuple[str, str, Decimal]] = []
    detail_lines: list[str] = []
    provider_labels = {"deepseek": "DeepSeek", "kimi": "Kimi", "qwen": "千问"}
    rows: list[dict[str, str]] = []
    for provider, models in used_models.items():
        snapshot = after_map.get(provider)
        raw_before = str(before_amounts.get(provider) or "").strip()
        if "|" not in raw_before:
            rows.append(
                {
                    "provider": provider_labels.get(provider, provider),
                    "models": "\n".join(models) if models else "-",
                    "before_balance": "未记录",
                    "current_balance": snapshot.detail if snapshot is not None else "未查询",
                    "cost": "无法计算",
                }
            )
            continue
        before_currency, _, before_amount_text = raw_before.partition("|")
        if snapshot is None:
            rows.append(
                {
                    "provider": provider_labels.get(provider, provider),
                    "models": "\n".join(models) if models else "-",
                    "before_balance": _format_cost_amount_text(before_currency.strip().upper() or "CNY", Decimal(before_amount_text.strip() or "0")),
                    "current_balance": "未查询",
                    "cost": "无法计算",
                }
            )
            continue
        before_currency = before_currency.strip().upper() or snapshot.currency
        try:
            before_amount = Decimal(before_amount_text.strip())
        except Exception:
            rows.append(
                {
                    "provider": provider_labels.get(provider, provider),
                    "models": "\n".join(models) if models else "-",
                    "before_balance": "格式异常",
                    "current_balance": snapshot.detail,
                    "cost": "无法计算",
                }
            )
            continue
        if before_currency != snapshot.currency:
            rows.append(
                {
                    "provider": provider_labels.get(provider, provider),
                    "models": "\n".join(models) if models else "-",
                    "before_balance": _format_cost_amount_text(before_currency, before_amount),
                    "current_balance": _format_cost_amount_text(snapshot.currency, snapshot.amount),
                    "cost": "币种不一致",
                }
            )
            continue
        delta = before_amount - snapshot.amount
        if delta < Decimal("0"):
            delta = Decimal("0")
        deltas.append((provider, snapshot.currency, delta))
        detail_lines.append(f"{provider_labels.get(provider, provider)}：{_format_cost_amount_text(snapshot.currency, delta)}")
        rows.append(
            {
                "provider": provider_labels.get(provider, provider),
                "models": "\n".join(models) if models else "-",
                "before_balance": _format_cost_amount_text(snapshot.currency, before_amount),
                "current_balance": _format_cost_amount_text(snapshot.currency, snapshot.amount),
                "cost": _format_cost_amount_text(snapshot.currency, delta),
            }
        )
    state.execution.import_cost_rows = rows
    if not deltas:
        state.execution.import_cost_detail_text = "导入前后余额币种不一致或缺少可比较快照，无法计算本次 docx 解析费用。"
        _append_import_cost_history(
            before_amounts,
            after_snapshots,
            total_cost="",
            cost_summary="",
            cost_detail=state.execution.import_cost_detail_text,
        )
        _update_app_import_cost_snapshots(after_snapshots)
        return
    totals_by_currency: dict[str, Decimal] = {}
    for _provider, currency, delta in deltas:
        totals_by_currency[currency] = totals_by_currency.get(currency, Decimal("0")) + delta
    non_zero_deltas = [item for item in deltas if item[2] > Decimal("0")]
    summary_parts = [
        f"{provider_labels.get(provider, provider)} {_format_cost_amount_text(currency, delta)}"
        for provider, currency, delta in non_zero_deltas
    ]
    total_parts = [
        _format_cost_amount_text(currency, amount)
        for currency, amount in sorted(totals_by_currency.items(), key=lambda item: item[0])
    ]
    state.execution.import_cost_total_text = "；".join(total_parts) if total_parts else "0"
    state.execution.import_cost_summary_text = "；".join(summary_parts) if summary_parts else "0"
    state.execution.import_cost_detail_text = "；".join(detail_lines)
    _append_import_cost_history(
        before_amounts,
        after_snapshots,
        total_cost=state.execution.import_cost_total_text,
        cost_summary=state.execution.import_cost_summary_text,
        cost_detail=state.execution.import_cost_detail_text,
    )
    _update_app_import_cost_snapshots(after_snapshots)


def _collect_import_used_models() -> dict[str, list[str]]:
    provider_map: dict[str, list[str]] = {}
    seen: dict[str, set[str]] = {}

    def add(provider: str, model_name: str, stage_label: str) -> None:
        provider_key = str(provider or "").strip().lower()
        model_text = str(model_name or "").strip()
        if not provider_key or not model_text:
            return
        if provider_key not in provider_map:
            provider_map[provider_key] = []
            seen[provider_key] = set()
        value = f"{stage_label}：{model_text}"
        if value in seen[provider_key]:
            return
        seen[provider_key].add(value)
        provider_map[provider_key].append(value)

    for spec in question_ref_model_specs():
        add(str(spec.get("provider") or ""), str(spec.get("model_name") or ""), "题号题型")
    for spec in question_content_model_specs():
        add(str(spec.get("provider") or ""), str(spec.get("model_name") or ""), "题目内容")
    return provider_map


def _build_unavailable_rows(
    used_models: dict[str, list[str]],
    *,
    before_text: str,
    current_text: str,
    cost_text: str,
) -> list[dict[str, str]]:
    provider_labels = {"deepseek": "DeepSeek", "kimi": "Kimi", "qwen": "千问"}
    rows: list[dict[str, str]] = []
    for provider, models in used_models.items():
        rows.append(
            {
                "provider": provider_labels.get(provider, provider),
                "models": "\n".join(models) if models else "-",
                "before_balance": before_text,
                "current_balance": current_text,
                "cost": cost_text,
            }
        )
    return rows


def _append_import_cost_history(
    before_amounts: dict[str, str],
    after_snapshots: list,
    *,
    total_cost: str,
    cost_summary: str,
    cost_detail: str,
) -> None:
    before_provider_balances = _build_before_provider_balances(before_amounts)
    provider_balances = _build_after_provider_balances(after_snapshots)
    append_import_cost_history_entry(
        run_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        source_label="导入完成",
        before_provider_balances=before_provider_balances,
        provider_balances=provider_balances,
        total_balance=build_total_balance_text(provider_balances),
        total_cost=total_cost,
        cost_summary=cost_summary,
        cost_detail=cost_detail,
    )


def _build_after_provider_balances(after_snapshots: list) -> dict[str, str]:
    values: dict[str, str] = {}
    for snapshot in after_snapshots:
        provider = str(getattr(snapshot, "provider", "") or "").strip().lower()
        if not provider:
            continue
        currency = str(getattr(snapshot, "currency", "") or "").strip().upper() or "CNY"
        amount = getattr(snapshot, "amount", None)
        try:
            values[provider] = _format_cost_amount_text(currency, Decimal(str(amount)))
        except Exception:
            detail = str(getattr(snapshot, "detail", "") or "").strip()
            values[provider] = detail
    return values


def _build_before_provider_balances(before_amounts: dict[str, str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for provider, raw_value in dict(before_amounts or {}).items():
        provider_key = str(provider or "").strip().lower()
        raw_text = str(raw_value or "").strip()
        if not provider_key or "|" not in raw_text:
            continue
        currency, _, amount_text = raw_text.partition("|")
        try:
            values[provider_key] = _format_cost_amount_text(currency.strip().upper() or "CNY", Decimal(amount_text.strip()))
        except Exception:
            continue
    return values


def _reset_app_import_cost_capture_for_tests() -> None:
    global _APP_IMPORT_COST_THREAD, _APP_IMPORT_COST_LOADING, _APP_IMPORT_COST_STARTED, _APP_IMPORT_COST_SNAPSHOTS, _APP_IMPORT_COST_STARTUP_LOGGED
    with _APP_IMPORT_COST_LOCK:
        _APP_IMPORT_COST_THREAD = None
        _APP_IMPORT_COST_LOADING = False
        _APP_IMPORT_COST_STARTED = False
        _APP_IMPORT_COST_SNAPSHOTS = []
        _APP_IMPORT_COST_STARTUP_LOGGED = False
