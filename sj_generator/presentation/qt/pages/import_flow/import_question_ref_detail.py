from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import QComboBox, QTableWidget, QTableWidgetItem

from sj_generator.infrastructure.llm.question_ref_scan import (
    merged_question_ref_numbers,
    question_ref_model_specs,
    question_ref_type_map,
    row_consistency_text,
    special_marker_text,
)


def question_ref_row_background(verdict_text: str, *, is_manually_overridden: bool = False) -> QBrush | None:
    if is_manually_overridden:
        return QBrush(QColor("#fff3cd"))
    text = str(verdict_text or "").strip()
    if not text:
        return None
    if "不一致" in text:
        return QBrush(QColor("#fde2e1"))
    if "一致" in text:
        return QBrush(QColor("#e6f4ea"))
    return None


def question_ref_detail_headers(model_specs: list[dict[str, str]] | None = None) -> list[str]:
    specs = model_specs or question_ref_detail_model_specs()
    headers = ["资料名称"]
    duplicate_counts: dict[str, int] = {}
    for spec in specs:
        label = str(spec.get("label") or "").strip() or "模型"
        duplicate_counts[label] = duplicate_counts.get(label, 0) + 1
    duplicate_indexes: dict[str, int] = {}
    for index, spec in enumerate(specs, start=1):
        label = str(spec.get("label") or "").strip() or "模型"
        duplicate_indexes[label] = duplicate_indexes.get(label, 0) + 1
        display_label = label
        if duplicate_counts.get(label, 0) > 1:
            display_label = f"模型{index}\n{label}"
        headers.extend([f"{display_label}\n题号", f"{display_label}\n类型"])
    headers.append("对比结论")
    headers.append("题型")
    return headers


def question_ref_detail_model_specs(payloads: dict[str, dict[str, object]] | None = None) -> list[dict[str, str]]:
    payload_map = payloads if isinstance(payloads, dict) else {}
    specs: list[dict[str, str]] = []
    seen: set[str] = set()
    for payload in payload_map.values():
        if not isinstance(payload, dict):
            continue
        model_specs = payload.get("model_specs")
        if not isinstance(model_specs, list):
            continue
        for item in model_specs:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            specs.append(
                {
                    "key": key,
                    "label": str(item.get("label") or "").strip(),
                }
            )
    return specs or [
        {
            "key": str(item.get("key") or ""),
            "label": str(item.get("label") or "").strip(),
        }
        for item in question_ref_model_specs()
    ]


def question_ref_detail_model_values(
    payload: dict[str, object],
    *,
    model_specs: list[dict[str, str]],
) -> list[list[dict[str, str]]]:
    values: list[list[dict[str, str]]] = []
    results = payload.get("results") if isinstance(payload.get("results"), dict) else {}
    for spec in model_specs:
        key = str(spec.get("key") or "").strip()
        raw = results.get(key, []) if isinstance(results, dict) else []
        if isinstance(raw, list):
            normalized: list[dict[str, str]] = []
            for item in raw:
                if not isinstance(item, dict):
                    continue
                normalized.append(
                    {
                        "number": str(item.get("number") or "").strip(),
                        "question_type": str(item.get("question_type") or "").strip(),
                    }
                )
            values.append(normalized)
        else:
            values.append([])
    return values


def question_ref_number_order(model_refs: list[list[dict[str, str]]]) -> list[str]:
    return merged_question_ref_numbers(*model_refs)


def question_type_options() -> list[str]:
    return ["单选", "多选", "可转多选"]


def question_type_from_candidates(values: list[str]) -> str:
    options = question_type_options()
    normalized = [str(value or "").strip() for value in values if str(value or "").strip() in options]
    if not normalized:
        return options[0]
    counts: dict[str, int] = {}
    for value in normalized:
        counts[value] = counts.get(value, 0) + 1
    best_type = max(
        options,
        key=lambda item: (counts.get(item, 0), -options.index(item)),
    )
    return best_type if counts.get(best_type, 0) > 0 else normalized[0]


def question_type_conflicts(values: list[str]) -> bool:
    options = question_type_options()
    normalized = {str(value or "").strip() for value in values if str(value or "").strip() in options}
    return len(normalized) > 1


def build_question_ref_detail_rows(
    *,
    payloads: dict[str, dict[str, object]],
    model_specs: list[dict[str, str]],
    resolve_manual_type,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for source_key, payload in payloads.items():
        source_name = str(payload.get("source_name") or Path(source_key).name or source_key)
        model_refs = question_ref_detail_model_values(payload, model_specs=model_specs)
        number_order = question_ref_number_order(model_refs)
        type_maps = [question_ref_type_map(refs) for refs in model_refs]
        marker_map = payload.get("markers") if isinstance(payload.get("markers"), dict) else {}
        elapsed_map = payload.get("elapsed_s_by_model") if isinstance(payload.get("elapsed_s_by_model"), dict) else {}
        marker_values = [
            special_marker_text(marker_map.get(str(spec.get("key") or "")))
            for spec in model_specs
        ]
        if not number_order:
            marker_summary = "；".join(text for text in marker_values if text)
            if marker_summary:
                rows.append(
                    {
                        "cells": [source_name] + [""] * max(0, len(question_ref_detail_headers(model_specs)) - 3) + [f"异常：{marker_summary}", ""],
                        "source_key": source_key,
                        "number": "",
                        "manual_type": "",
                    }
                )
            else:
                rows.append(
                    {
                        "cells": [source_name] + [""] * max(0, len(question_ref_detail_headers(model_specs)) - 3) + ["未识别到题号", ""],
                        "source_key": source_key,
                        "number": "",
                        "manual_type": "",
                    }
                )
            continue
        for number in number_order:
            row_values = [source_name]
            for model_index, refs in enumerate(model_refs):
                model_key = str(model_specs[model_index].get("key") or "")
                type_map = type_maps[model_index]
                row_values.append(number if number in type_map else "")
                question_type = type_map.get(number, "")
                elapsed_s = str(elapsed_map.get(model_key) or "").strip()
                type_text = question_type
                if elapsed_s:
                    type_text = f"{question_type}\n{elapsed_s}s" if question_type else f"{elapsed_s}s"
                row_values.append(type_text)
            types = [type_map.get(number, "").strip() for type_map in type_maps]
            suggested_type = question_type_from_candidates(types) if types else ""
            manual_type = str(
                resolve_manual_type(
                    source_key=source_key,
                    number=number,
                    payload=payload,
                    model_types=types,
                )
                or ""
            ).strip()
            row_values.append(row_consistency_text(types))
            row_values.append(manual_type)
            rows.append(
                {
                    "cells": row_values,
                    "source_key": source_key,
                    "number": number,
                    "manual_type": manual_type,
                    "suggested_type": suggested_type,
                }
            )
    return rows


def build_manual_type_combo(
    *,
    table: QTableWidget,
    current_type: str,
    background: QBrush | None,
    on_changed,
) -> QComboBox:
    combo = QComboBox(table)
    options = [""] + question_type_options()
    combo.addItems(options)
    combo.setEditable(True)
    selected = current_type if current_type in options else ""
    combo.setCurrentText(selected)
    line_edit = combo.lineEdit()
    if line_edit is not None:
        line_edit.setReadOnly(True)
        line_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
    combo.currentTextChanged.connect(on_changed)
    if background is not None:
        combo.setStyleSheet(f"QComboBox {{ background-color: {background.color().name()}; }}")
    return combo


def populate_question_ref_detail_table(
    *,
    table: QTableWidget,
    rows: list[dict[str, object]],
    build_combo,
    manual_col: int,
    overridden_pairs: set[tuple[str, str]],
) -> None:
    table.setRowCount(len(rows))
    for row_index, row_data in enumerate(rows):
        row_values = list(row_data.get("cells", [])) if isinstance(row_data, dict) else []
        source_key = str(row_data.get("source_key") or "") if isinstance(row_data, dict) else ""
        number = str(row_data.get("number") or "") if isinstance(row_data, dict) else ""
        verdict_text = ""
        if 0 <= (manual_col - 1) < len(row_values):
            verdict_text = str(row_values[manual_col - 1] or "").strip()
        is_manually_overridden = bool(source_key and number and (source_key, number) in overridden_pairs)
        background = question_ref_row_background(
            verdict_text,
            is_manually_overridden=is_manually_overridden,
        )
        for col_index, value in enumerate(row_values):
            if col_index == manual_col:
                continue
            item = QTableWidgetItem(str(value or ""))
            if col_index == 0:
                item.setData(Qt.ItemDataRole.UserRole, source_key)
                item.setData(Qt.ItemDataRole.UserRole + 1, number)
            if background is not None:
                item.setBackground(background)
            table.setItem(row_index, col_index, item)
        manual_type = str(row_data.get("manual_type") or "") if isinstance(row_data, dict) else ""
        suggested_type = str(row_data.get("suggested_type") or "") if isinstance(row_data, dict) else ""
        if source_key and number and ("不一致" in verdict_text):
            table.setCellWidget(
                row_index,
                manual_col,
                build_combo(
                    source_key=source_key,
                    number=number,
                    current_type=manual_type or suggested_type,
                    background=background,
                ),
            )
        else:
            manual_item = QTableWidgetItem(manual_type)
            manual_item.setTextAlignment(int(Qt.AlignmentFlag.AlignCenter))
            if background is not None:
                manual_item.setBackground(background)
            table.setItem(row_index, manual_col, manual_item)
