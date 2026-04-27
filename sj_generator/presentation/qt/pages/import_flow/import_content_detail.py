from __future__ import annotations

import json

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import QHeaderView, QTableWidget, QTableWidgetItem

from sj_generator.infrastructure.llm.import_questions import _fingerprint_question_obj, question_content_model_specs
from sj_generator.presentation.qt.compare_highlight import compare_highlight_model_styles
from sj_generator.application.state import normalize_ai_concurrency


def format_json_cell(value: object) -> str:
    if value is None:
        return ""
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return str(value)


def question_ref_total_count(value: dict[str, list[dict[str, str]]] | None) -> int:
    if not isinstance(value, dict):
        return 0
    total = 0
    for items in value.values():
        if isinstance(items, list):
            total += len(items)
    return total


def question_content_active_model_specs() -> list[dict[str, str]]:
    return [item for item in question_content_model_specs() if isinstance(item, dict)]


def effective_content_question_workers(total_budget: int, model_count: int) -> int:
    normalized_budget = normalize_ai_concurrency(total_budget)
    _ = model_count
    return max(1, normalized_budget)


def question_content_payload_model_specs(
    payload: dict[str, object],
    fallback_specs: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    raw = payload.get("model_specs")
    if isinstance(raw, list) and raw:
        return [item for item in raw if isinstance(item, dict)]
    return [item for item in (fallback_specs or question_content_active_model_specs()) if isinstance(item, dict)]


def question_content_model_signature(model_specs: list[dict[str, str]] | None = None) -> str:
    specs = [item for item in (model_specs or question_content_active_model_specs()) if isinstance(item, dict)]
    try:
        return json.dumps(specs, ensure_ascii=False, sort_keys=True)
    except Exception:
        return str(specs)


def question_content_detail_headers(model_specs: list[dict[str, str]] | None = None) -> list[str]:
    specs = [item for item in (model_specs or question_content_active_model_specs()) if isinstance(item, dict)]
    headers: list[str] = ["题号"]
    for spec in specs:
        label = str(spec.get("label") or "模型")
        headers.append(f"{label}\n耗时")
    for spec in specs:
        label = str(spec.get("label") or "模型")
        headers.append(f"{label}\nJSON结果")
    headers.append("一致性结论")
    return headers


def has_question_content_payload(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, dict):
        return any(str(item or "").strip() for item in value.values())
    if isinstance(value, list):
        return len(value) > 0
    return bool(str(value).strip())


def sec_int(sec_value: object, ms_value: object) -> int | None:
    if isinstance(sec_value, (int, float)):
        return int(round(float(sec_value)))
    if isinstance(ms_value, (int, float)):
        return int(round(float(ms_value) / 1000.0))
    return None


def record_round_sec(
    compare_secs: dict[int, dict[str, dict[int, int]]],
    *,
    idx: int,
    round_no: int,
    model_key: str,
    sec_value: object,
    ms_value: object,
) -> None:
    if idx <= 0 or round_no <= 0:
        return
    sec_value_int = sec_int(sec_value, ms_value)
    if sec_value_int is None:
        return
    compare_secs.setdefault(idx, {}).setdefault(model_key, {})[round_no] = sec_value_int


def format_round_secs(compare_secs: dict[int, dict[str, dict[int, int]]], *, idx: int, model_key: str) -> str:
    model_rounds = compare_secs.get(idx, {}).get(model_key, {})
    if not model_rounds:
        return ""
    parts = [str(model_rounds[round_no]) for round_no in sorted(model_rounds.keys())]
    return "+".join(parts)


def content_detail_width_signature(model_specs: list[dict[str, str]]) -> str:
    keys = [str(item.get("key") or "") for item in model_specs if isinstance(item, dict)]
    return "|".join(keys)


def calculate_content_detail_column_widths(*, column_count: int, available_width: int, model_count: int) -> list[int]:
    weights = [1] + ([2] * model_count) + ([8] * model_count) + [2]
    if len(weights) != column_count:
        weights = [1] * column_count
    total_weight = max(1, sum(weights))
    min_widths = [80] + ([120] * model_count) + ([320] * model_count) + [160]
    if len(min_widths) != column_count:
        min_widths = [80] * column_count
    widths: list[int] = []
    for weight, min_width in zip(weights, min_widths):
        target_width = max(min_width, int(round(max(1, available_width) * weight / total_weight)))
        widths.append(target_width)
    return widths


def apply_content_detail_column_widths(table: QTableWidget, model_specs: list[dict[str, str]]) -> None:
    if table.columnCount() <= 0:
        return
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    widths = calculate_content_detail_column_widths(
        column_count=table.columnCount(),
        available_width=table.viewport().width(),
        model_count=len([item for item in model_specs if isinstance(item, dict)]),
    )
    for column, width in enumerate(widths):
        table.setColumnWidth(column, width)


def set_content_detail_item(table: QTableWidget, row: int, col: int, text: str, *, is_json: bool = False) -> None:
    item = QTableWidgetItem(text)
    if is_json:
        item.setTextAlignment(int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter))
    else:
        item.setTextAlignment(int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter))
    table.setItem(row, col, item)


def compare_row_brush(payload: dict[str, object]) -> QBrush:
    if bool(payload.get("partial")):
        return QBrush()
    if bool(payload.get("accepted")):
        return QBrush(QColor("#e6f4ea"))
    return QBrush(QColor("#fde2e1"))


def apply_compare_row_background(table: QTableWidget, *, row: int, payload: dict[str, object]) -> None:
    brush = compare_row_brush(payload)
    for col in range(table.columnCount()):
        item = table.item(row, col)
        if item is not None:
            item.setBackground(brush)


def clear_compare_payload_background(
    table: QTableWidget,
    *,
    row: int,
    payload: dict[str, object],
    model_specs: list[dict[str, str]],
) -> None:
    payload_col_start = 1 + len(model_specs)
    payload_col_end = payload_col_start + len(model_specs)
    brush = compare_row_brush(payload)
    for col in range(payload_col_start, payload_col_end):
        item = table.item(row, col)
        if item is not None:
            item.setBackground(brush)


def highlight_sig_text(obj: object) -> str:
    if isinstance(obj, dict):
        return _fingerprint_question_obj(obj)
    if obj is None:
        return ""
    if isinstance(obj, str):
        return obj.strip()
    if isinstance(obj, list) and not obj:
        return ""
    return str(obj).strip()


def apply_partial_pass_highlight(
    table: QTableWidget,
    *,
    row: int,
    payload: dict[str, object],
    model_specs: list[dict[str, str]],
) -> None:
    clear_compare_payload_background(table, row=row, payload=payload, model_specs=model_specs)
    value_col_offset = 1 + len(model_specs)
    model_cols = [
        (str(spec.get("key") or ""), value_col_offset + index)
        for index, spec in enumerate(model_specs)
    ]
    results_by_model = payload.get("results_by_model") if isinstance(payload.get("results_by_model"), dict) else {}
    highlight_styles = compare_highlight_model_styles(
        model_sigs={key: highlight_sig_text(results_by_model.get(key)) for key, _ in model_cols},
        round_no=int(payload.get("round") or 0),
        round_matched_count=int(payload.get("round_matched_count") or 0),
    )
    if not highlight_styles:
        return
    fail_brush = QBrush(QColor(255, 199, 206))
    empty_brush = QBrush(QColor(255, 235, 156))
    for key, col in model_cols:
        style = highlight_styles.get(key)
        if not style:
            continue
        item = table.item(row, col)
        if item is None:
            continue
        value = results_by_model.get(key)
        if style == "yellow":
            item.setBackground(empty_brush)
        elif style == "red" and not has_question_content_payload(value):
            item.setBackground(fail_brush)


def build_compare_verdict(payload: dict[str, object]) -> str:
    round_no = int(payload.get("round") or 0)
    round_labels = {1: "一轮", 2: "二轮", 3: "三轮"}
    label = round_labels.get(round_no, f"第{round_no}轮")
    round_matched = int(payload.get("round_matched_count") or 0)
    matched = int(payload.get("matched_count") or 0)
    ratio_numerator = max(1, int(payload.get("ratio_numerator") or 1))
    ratio_denominator = max(1, int(payload.get("ratio_denominator") or 1))
    completed = int(payload.get("completed_model_count") or 0)
    total_models = int(payload.get("active_model_count") or 0)
    standard_required = max(1, ratio_numerator * max(1, round_no))
    standard_total = max(standard_required, ratio_denominator * max(1, round_no))
    round_standard_total = max(1, ratio_denominator)
    current_text = f"当前一致：{matched}/{standard_total}"
    round_text = f"本轮通过：{round_matched}/{round_standard_total}"
    if bool(payload.get("partial")):
        status_text = f"{label}进行中（已返回 {completed}/{total_models}）"
        return "\n".join(
            [
                status_text,
                current_text,
                round_text,
                f"通过标准：≥{standard_required}/{standard_total}",
            ]
        )
    accepted = bool(payload.get("accepted"))
    status_text = f"{label}结束（{'通过' if accepted else '未通过'}）"
    return "\n".join(
        [
            status_text,
            current_text,
            round_text,
            f"通过标准：≥{standard_required}/{standard_total}",
        ]
    )
