from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

from sj_generator.infrastructure.llm.client import LlmClient, LlmConfig
from sj_generator.infrastructure.llm.import_questions import (
    _QuestionRefSpecialCaseError,
    _as_str,
    _get_question_numbers_with_fallback,
    _normalize_question_ref_list,
)
from sj_generator.application.settings import (
    load_deepseek_config,
    load_kimi_config,
    load_project_parse_model_rows,
    load_qwen_config,
    with_capped_timeout,
)

QUESTION_REF_TEST_TIMEOUT_S = 300.0


def question_ref_numbers(items: list[dict[str, str]]) -> list[str]:
    return [_as_str(item.get("number", "")) for item in items if _as_str(item.get("number", ""))]


def question_ref_type_map(items: list[dict[str, str]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in _normalize_question_ref_list(items):
        number = _as_str(item.get("number", ""))
        if not number:
            continue
        result[number] = _as_str(item.get("question_type", ""))
    return result


def question_ref_warning_text(items: list[dict[str, str]]) -> str:
    for item in _normalize_question_ref_list(items):
        warning = _as_str(item.get("duplicate_warning", ""))
        if warning == "存在可疑的题号重复":
            return warning
    return ""


def special_marker_text(value: object) -> str:
    return _as_str(value)


def merged_question_ref_numbers(*groups: list[dict[str, str]]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for items in groups:
        for number in question_ref_numbers(items):
            if number in seen:
                continue
            seen.add(number)
            ordered.append(number)
    return ordered


def question_ref_header_labels(model_specs: list[dict[str, str]] | None = None) -> list[str]:
    specs = model_specs or question_ref_model_specs()
    return ["题号", *[str(item.get("label") or "") for item in specs], "最终", "行一致性"]


def row_consistency_text(values: list[str]) -> str:
    normalized = [str(value or "").strip() for value in values]
    total = len(normalized)
    if total <= 0:
        return "0/0"
    counts: dict[str, int] = {}
    for value in normalized:
        key = value if value else "__EMPTY__"
        counts[key] = counts.get(key, 0) + 1
    best_count = max(counts.values()) if counts else 0
    return f"{best_count}/{total} {'一致' if best_count == total else '不一致'}"


def question_ref_model_specs() -> list[dict[str, str]]:
    row = _question_number_parse_row()
    models = row.get("models") or []
    if models:
        specs: list[dict[str, str]] = []
        for index, item in enumerate(models):
            provider = str(item.get("provider") or "").strip().lower()
            model_name = str(item.get("model_name") or "").strip()
            if not provider or not model_name:
                continue
            specs.append(
                {
                    "key": f"model_{index + 1}",
                    "provider": provider,
                    "model_name": model_name,
                    "label": f"{_provider_label(provider)}\n{model_name}",
                }
            )
        if specs:
            return specs

    deepseek_model = load_deepseek_config().number_model.strip() or "deepseek-chat"
    kimi_model = load_kimi_config().number_model.strip() or "kimi-k2.6"
    qwen_model = load_qwen_config().number_model.strip() or "qwen-max"
    return [
        {"key": "model_1", "provider": "deepseek", "model_name": deepseek_model, "label": f"DeepSeek\n{deepseek_model}"},
        {"key": "model_2", "provider": "kimi", "model_name": kimi_model, "label": f"Kimi\n{kimi_model}"},
        {"key": "model_3", "provider": "qwen", "model_name": qwen_model, "label": f"千问\n{qwen_model}"},
    ]


def run_question_ref_scan(
    *,
    text: str,
    source_name: str,
    progress_cb: Callable[[dict[str, object]], None] | None = None,
) -> dict[str, object]:
    model_specs = question_ref_model_specs()
    round_limit = _question_ref_round_limit()
    ratio_numerator, ratio_denominator = _question_ref_ratio()
    for spec in model_specs:
        provider = str(spec.get("provider") or "").strip()
        if not _question_ref_provider_ready(provider):
            raise RuntimeError(f"{_provider_label(provider)} 未配置，无法识别题号。")

    clients = {
        str(spec["key"]): LlmClient(
            _question_ref_llm_config(
                str(spec.get("provider") or ""),
                str(spec.get("model_name") or ""),
            )
        )
        for spec in model_specs
    }
    all_results: list[dict[str, object]] = []
    last_round_results: dict[str, list[dict[str, str]]] = {}
    last_round_markers: dict[str, str] = {}
    last_round_elapsed_s: dict[str, int] = {}
    accepted = False
    best_count = 0
    executed_rounds = 0
    best_items: list[dict[str, str]] = []

    for round_index in range(1, round_limit + 1):
        round_results: dict[str, list[dict[str, str]]] = {}
        round_markers: dict[str, str] = {}
        round_elapsed_s: dict[str, int] = {}
        round_started_at = time.monotonic()
        if progress_cb is not None:
            progress_cb(
                {
                    "event": "round_started",
                    "round": round_index,
                    "model_specs": model_specs,
                }
            )
        with ThreadPoolExecutor(max_workers=max(1, len(clients))) as executor:
            future_map = {
                executor.submit(
                    _get_question_numbers_with_fallback,
                    client=client,
                    source_name=source_name,
                    chunk_text=text,
                    depth=2,
                ): model_key
                for model_key, client in clients.items()
            }
            for future in as_completed(future_map):
                model_key = future_map[future]
                try:
                    items = _normalize_question_ref_list(future.result())
                except _QuestionRefSpecialCaseError as e:
                    round_markers[model_key] = str(e)
                    items = []
                except Exception as e:
                    round_markers[model_key] = f"识别失败：{e}"
                    items = []
                if progress_cb is not None:
                    elapsed_s = int(max(0.0, time.monotonic() - round_started_at))
                    round_elapsed_s[model_key] = elapsed_s
                    progress_cb(
                        {
                            "event": "model_finished",
                            "round": round_index,
                            "model_key": model_key,
                            "elapsed_s": elapsed_s,
                            "marker": round_markers.get(model_key, ""),
                            "item_count": len(items),
                        }
                    )
                round_results[model_key] = items
                all_results.append(
                    {
                        "round": round_index,
                        "model_key": model_key,
                        "items": items,
                        "fingerprint": special_marker_text(round_markers.get(model_key)) or _question_ref_fingerprint(items),
                    }
                )

        last_round_results = round_results
        last_round_markers = round_markers
        last_round_elapsed_s = round_elapsed_s
        executed_rounds = round_index

        if round_markers:
            break

        fingerprint_counts: dict[str, int] = {}
        fingerprint_items: dict[str, list[dict[str, str]]] = {}
        for entry in all_results:
            fingerprint = str(entry.get("fingerprint") or "")
            fingerprint_counts[fingerprint] = fingerprint_counts.get(fingerprint, 0) + 1
            fingerprint_items.setdefault(fingerprint, entry.get("items") or [])

        if fingerprint_counts:
            best_fingerprint = max(
                fingerprint_counts,
                key=lambda value: (fingerprint_counts[value], len(value), value),
            )
            best_count = fingerprint_counts[best_fingerprint]
            best_items = _normalize_question_ref_list(fingerprint_items.get(best_fingerprint, []))

        required_count = ratio_numerator * round_index
        if best_count >= required_count:
            accepted = True
            break

    total_count = len(all_results)
    consistency_text = f"{best_count}/{total_count}" if total_count else "0/0"
    return {
        "model_specs": model_specs,
        "round_limit": round_limit,
        "executed_rounds": executed_rounds,
        "ratio_numerator": ratio_numerator,
        "ratio_denominator": ratio_denominator,
        "best_count": best_count,
        "total_count": total_count,
        "consistency_text": consistency_text,
        "accepted": accepted,
        "final_refs": best_items,
        "results": last_round_results,
        "markers": last_round_markers,
        "elapsed_s_by_model": last_round_elapsed_s,
    }


def resolve_question_refs_with_scan(
    *,
    sources: list[tuple[Path, str]],
    progress_cb: Callable[[str], None] | None = None,
    compare_cb: Callable[[dict[str, object]], None] | None = None,
    scan_progress_cb: Callable[[dict[str, object]], None] | None = None,
    progress_count_cb: Callable[[int, int], None] | None = None,
    stop_cb: Callable[[], bool] | None = None,
) -> dict[str, object]:
    refs_by_source: dict[str, list[dict[str, str]]] = {}
    payloads_by_source: dict[str, dict[str, object]] = {}
    total_sources = len(sources)
    completed = 0
    if progress_count_cb is not None:
        progress_count_cb(0, total_sources)
    for path, text in sources:
        if stop_cb and stop_cb():
            break
        normalized_text = text.strip()
        if not normalized_text:
            completed += 1
            if progress_count_cb is not None:
                progress_count_cb(completed, total_sources)
            continue
        if progress_cb is not None:
            progress_cb(f"{path.name}：题号与题型解析中…")
        if scan_progress_cb is not None:
            scan_progress_cb(
                {
                    "event": "source_started",
                    "source_name": path.name,
                    "source_path": str(path),
                }
            )
        payload = run_question_ref_scan(
            text=normalized_text,
            source_name=path.name,
            progress_cb=(
                (lambda event: scan_progress_cb(
                    {
                        **event,
                        "source_name": path.name,
                        "source_path": str(path),
                    }
                ))
                if scan_progress_cb is not None
                else None
            ),
        )
        payload = {
            **payload,
            "source_name": path.name,
            "source_path": str(path),
        }
        payloads_by_source[str(path)] = payload
        if compare_cb is not None:
            compare_cb(payload)
        if bool(payload.get("accepted")):
            refs_by_source[str(path)] = _normalize_question_ref_list(payload.get("final_refs", []))
        completed += 1
        if progress_count_cb is not None:
            progress_count_cb(completed, total_sources)
    total_refs = sum(len(items) for items in refs_by_source.values())
    return {
        "refs_by_source": refs_by_source,
        "payloads_by_source": payloads_by_source,
        "total_refs": total_refs,
    }


def _question_ref_fingerprint(items: list[dict[str, str]]) -> str:
    normalized = [
        {
            key: value
            for key, value in item.items()
            if key in {"number", "question_type"} and str(value or "").strip()
        }
        for item in _normalize_question_ref_list(items)
    ]
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _provider_label(provider: str) -> str:
    labels = {"deepseek": "DeepSeek", "kimi": "Kimi", "qwen": "千问"}
    return labels.get(str(provider or "").strip().lower(), provider or "")


def _question_number_parse_row() -> dict:
    rows = load_project_parse_model_rows()
    for row in rows:
        if str(row.get("key") or "").strip() == "question_number_parse":
            return row
    return {"key": "question_number_parse", "round": "1", "ratio": "1/4", "models": []}


def _question_ref_round_limit() -> int:
    row = _question_number_parse_row()
    try:
        value = int(str(row.get("round") or "1").strip())
    except Exception:
        return 1
    return min(8, max(1, value))


def _question_ref_ratio() -> tuple[int, int]:
    row = _question_number_parse_row()
    raw = str(row.get("ratio") or "1/4").strip()
    left, sep, right = raw.partition("/")
    if not sep:
        return 1, 1
    try:
        numerator = int(left.strip())
        denominator = int(right.strip())
    except Exception:
        return 1, 1
    return max(1, numerator), max(1, denominator)


def _question_ref_llm_config(provider: str, model_name: str) -> LlmConfig:
    provider_key = str(provider or "").strip().lower()
    if provider_key == "kimi":
        cfg = with_capped_timeout(load_kimi_config(), QUESTION_REF_TEST_TIMEOUT_S)
        return LlmConfig(
            base_url=cfg.base_url.strip(),
            api_key=cfg.api_key.strip(),
            model=model_name.strip(),
            timeout_s=float(cfg.timeout_s),
        )
    if provider_key == "qwen":
        cfg = with_capped_timeout(load_qwen_config(), QUESTION_REF_TEST_TIMEOUT_S)
        return LlmConfig(
            base_url=cfg.base_url.strip(),
            api_key=cfg.api_key.strip(),
            model=model_name.strip(),
            timeout_s=float(cfg.timeout_s),
        )
    cfg = with_capped_timeout(load_deepseek_config(), QUESTION_REF_TEST_TIMEOUT_S)
    return LlmConfig(
        base_url=cfg.base_url.strip(),
        api_key=cfg.api_key.strip(),
        model=model_name.strip(),
        timeout_s=float(cfg.timeout_s),
    )


def _question_ref_provider_ready(provider: str) -> bool:
    provider_key = str(provider or "").strip().lower()
    if provider_key == "kimi":
        return load_kimi_config().is_ready()
    if provider_key == "qwen":
        return load_qwen_config().is_ready()
    return load_deepseek_config().is_ready()
