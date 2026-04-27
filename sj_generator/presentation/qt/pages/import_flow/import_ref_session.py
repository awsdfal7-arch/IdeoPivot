from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sj_generator.infrastructure.llm.question_ref_scan import question_ref_model_specs, question_ref_type_map
from .import_progress import extract_question_ref_source_name
from .import_question_ref_detail import (
    question_ref_detail_model_values,
    question_ref_number_order,
    question_type_conflicts,
    question_type_from_candidates,
    question_type_options,
)


@dataclass
class QuestionRefRuntimeState:
    question_refs_by_source: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    question_ref_payloads: dict[str, dict[str, object]] = field(default_factory=dict)
    manual_question_type_overrides: dict[tuple[str, str], str] = field(default_factory=dict)
    progress_cur: int = 0
    progress_total: int = 0
    accepted_count: int = 0
    cur_source_name: str = "-"
    waiting_source_key: str = ""
    waiting_source_name: str = ""
    waiting_model_specs: list[dict[str, str]] = field(default_factory=list)
    waiting_model_state: dict[str, dict[str, object]] = field(default_factory=dict)
    wait_elapsed_s: int = 0
    wait_round: int = 0

    def reset(self, *, source_name: str = "-") -> None:
        self.question_refs_by_source = {}
        self.question_ref_payloads = {}
        self.manual_question_type_overrides = {}
        self.cur_source_name = source_name or "-"
        self.reset_progress()
        self.stop_waiting_feedback()

    def reset_progress(self) -> None:
        self.progress_cur = 0
        self.progress_total = 0
        self.accepted_count = 0

    def update_progress(self, cur: int, total: int) -> None:
        self.progress_cur = max(0, int(cur))
        self.progress_total = max(0, int(total))

    def update_source_from_progress(self, msg: str) -> None:
        self.cur_source_name = extract_question_ref_source_name(msg, self.cur_source_name)

    def status_text(self) -> str:
        return (
            f"资料：{self.cur_source_name}；"
            f"{self.question_progress_text()}；"
            f"已识别题号 {self.accepted_count} 个"
        )

    def question_progress_text(self) -> str:
        total = self.progress_total
        if total > 0:
            cur = min(max(self.progress_cur, 0), total)
            return f"资料 {cur}/{total}个"
        return "资料 统计中"

    def apply_compare_payload(self, payload: dict[str, object]) -> str:
        source_key = str(payload.get("source_path") or payload.get("source_name") or "").strip()
        if not source_key:
            return ""
        source_name = str(payload.get("source_name") or Path(source_key).name or source_key)
        self.clear_waiting_source(source_key)
        self.question_ref_payloads[source_key] = dict(payload)
        self.cur_source_name = source_name
        if bool(payload.get("accepted")):
            self.question_refs_by_source[source_key] = self.build_question_refs_for_source(source_key)
            self.apply_manual_type_overrides_for_source(source_key)
            self.refresh_accepted_count()
        return source_name

    def apply_done_payload(self, result: object) -> None:
        payload = result if isinstance(result, dict) else {}
        refs_by_source = payload.get("refs_by_source", {})
        payloads_by_source = payload.get("payloads_by_source", {})
        if isinstance(refs_by_source, dict):
            self.question_refs_by_source = {
                str(key): value for key, value in refs_by_source.items() if isinstance(value, list)
            }
            self.apply_all_manual_type_overrides()
        if isinstance(payloads_by_source, dict):
            self.question_ref_payloads = {
                str(key): value for key, value in payloads_by_source.items() if isinstance(value, dict)
            }
            self.apply_all_manual_type_overrides()
        self.refresh_accepted_count()

    def set_manual_question_type(self, source_key: str, number: str, value: str) -> None:
        normalized = str(value or "").strip()
        if not source_key or not number:
            return
        if not normalized:
            self.manual_question_type_overrides.pop((source_key, number), None)
            self.ensure_source_available_after_manual_override(source_key)
            self.refresh_accepted_count()
            return
        if normalized not in question_type_options():
            return
        self.manual_question_type_overrides[(source_key, number)] = normalized
        updated = self.apply_manual_type_override(source_key, number, normalized)
        if (not updated) and source_key not in self.question_refs_by_source:
            payload = self.question_ref_payloads.get(source_key, {})
            final_refs = payload.get("final_refs")
            if isinstance(final_refs, list):
                cloned = []
                for item in final_refs:
                    if not isinstance(item, dict):
                        continue
                    new_item = dict(item)
                    if str(new_item.get("number") or "").strip() == number:
                        new_item["question_type"] = normalized
                    cloned.append(new_item)
                payload["final_refs"] = cloned
        self.ensure_source_available_after_manual_override(source_key)
        self.refresh_accepted_count()

    def resolve_manual_question_type(
        self,
        *,
        source_key: str,
        number: str,
        payload: dict[str, object],
        model_types: list[str],
    ) -> str:
        override = self.manual_question_type_overrides.get((source_key, number), "").strip()
        if override:
            return override
        if question_type_conflicts(model_types):
            return ""
        question_refs = self.question_refs_by_source.get(source_key, [])
        for item in question_refs:
            if not isinstance(item, dict):
                continue
            if str(item.get("number") or "").strip() == number:
                existing = str(item.get("question_type") or "").strip()
                if existing:
                    return existing
        final_refs = payload.get("final_refs")
        if isinstance(final_refs, list):
            for item in final_refs:
                if not isinstance(item, dict):
                    continue
                if str(item.get("number") or "").strip() == number:
                    existing = str(item.get("question_type") or "").strip()
                    if existing:
                        return existing
        return question_type_from_candidates(model_types)

    def build_question_refs_for_source(self, source_key: str) -> list[dict[str, str]]:
        payload = self.question_ref_payloads.get(source_key, {})
        if not isinstance(payload, dict):
            return []
        model_specs = payload.get("model_specs")
        if not isinstance(model_specs, list) or not model_specs:
            model_specs = question_ref_model_specs()
        normalized_specs = [item for item in model_specs if isinstance(item, dict)]
        model_refs = question_ref_detail_model_values(payload, model_specs=normalized_specs)
        number_order = question_ref_number_order(model_refs)
        final_refs = payload.get("final_refs")
        if isinstance(final_refs, list):
            for item in final_refs:
                if not isinstance(item, dict):
                    continue
                number = str(item.get("number") or "").strip()
                if number and number not in number_order:
                    number_order.append(number)
        type_maps = [question_ref_type_map(refs) for refs in model_refs]
        built: list[dict[str, str]] = []
        for number in number_order:
            types = [type_map.get(number, "").strip() for type_map in type_maps]
            has_conflict = question_type_conflicts(types)
            question_type = self.resolve_manual_question_type(
                source_key=source_key,
                number=number,
                payload=payload,
                model_types=types,
            )
            if (not question_type) and (not has_conflict):
                question_type = question_type_from_candidates(types)
            if (not question_type) and (not has_conflict):
                question_type = question_type_options()[0]
            built.append({"number": number, "question_type": question_type})
        return built

    def has_unresolved_manual_types(self) -> bool:
        for source_key, payload in self.question_ref_payloads.items():
            if not isinstance(payload, dict):
                continue
            model_specs = payload.get("model_specs")
            if not isinstance(model_specs, list) or not model_specs:
                model_specs = question_ref_model_specs()
            normalized_specs = [item for item in model_specs if isinstance(item, dict)]
            model_refs = question_ref_detail_model_values(payload, model_specs=normalized_specs)
            number_order = question_ref_number_order(model_refs)
            type_maps = [question_ref_type_map(refs) for refs in model_refs]
            for number in number_order:
                types = [type_map.get(number, "").strip() for type_map in type_maps]
                if not question_type_conflicts(types):
                    continue
                if self.manual_question_type_overrides.get((source_key, number), "").strip():
                    continue
                return True
        return False

    def apply_all_manual_type_overrides(self) -> None:
        for (source_key, number), question_type in self.manual_question_type_overrides.items():
            self.apply_manual_type_override(source_key, number, question_type)

    def apply_manual_type_overrides_for_source(self, source_key: str) -> None:
        for (override_source, number), question_type in self.manual_question_type_overrides.items():
            if override_source != source_key:
                continue
            self.apply_manual_type_override(source_key, number, question_type)

    def apply_manual_type_override(self, source_key: str, number: str, question_type: str) -> bool:
        refs = self.question_refs_by_source.get(source_key)
        updated = False
        if isinstance(refs, list):
            for item in refs:
                if not isinstance(item, dict):
                    continue
                if str(item.get("number") or "").strip() == number:
                    item["question_type"] = question_type
                    updated = True
        payload = self.question_ref_payloads.get(source_key)
        if isinstance(payload, dict):
            final_refs = payload.get("final_refs")
            if isinstance(final_refs, list):
                for item in final_refs:
                    if not isinstance(item, dict):
                        continue
                    if str(item.get("number") or "").strip() == number:
                        item["question_type"] = question_type
        return updated

    def ensure_source_available_after_manual_override(self, source_key: str) -> None:
        if not source_key:
            return
        refs = self.build_question_refs_for_source(source_key)
        if not refs:
            return
        self.question_refs_by_source[source_key] = refs
        payload = self.question_ref_payloads.get(source_key)
        if isinstance(payload, dict):
            payload["accepted"] = True

    def refresh_accepted_count(self) -> None:
        self.accepted_count = sum(len(items) for items in self.question_refs_by_source.values())

    def handle_scan_progress(self, payload: object) -> str:
        data = payload if isinstance(payload, dict) else {}
        event = str(data.get("event") or "").strip()
        if event == "source_started":
            self.waiting_source_key = str(data.get("source_path") or data.get("source_name") or "").strip()
            self.waiting_source_name = str(data.get("source_name") or self.waiting_source_key or "").strip()
            return ""
        if event == "round_started":
            source_key = str(data.get("source_path") or data.get("source_name") or "").strip()
            self.waiting_source_key = source_key or self.waiting_source_key
            self.waiting_source_name = str(data.get("source_name") or self.waiting_source_name or self.waiting_source_key).strip()
            model_specs = data.get("model_specs")
            if isinstance(model_specs, list) and model_specs:
                self.waiting_model_specs = [item for item in model_specs if isinstance(item, dict)]
            self.wait_round = max(1, int(data.get("round") or 1))
            self.start_waiting_feedback()
            return "start_waiting"
        if event != "model_finished":
            return ""
        model_key = str(data.get("model_key") or "").strip()
        if not model_key:
            return ""
        state = self.waiting_model_state.setdefault(
            model_key,
            {"done": False, "elapsed_s": 0, "marker": "", "item_count": 0},
        )
        state["done"] = True
        state["elapsed_s"] = int(data.get("elapsed_s") or 0)
        state["marker"] = str(data.get("marker") or "")
        state["item_count"] = int(data.get("item_count") or 0)
        return "refresh_waiting"

    def start_waiting_feedback(self) -> None:
        self.wait_elapsed_s = 0
        self.wait_round = max(1, self.wait_round or 1)
        self.waiting_model_state = {
            str(spec.get("key") or ""): {"done": False, "elapsed_s": 0, "marker": "", "item_count": 0}
            for spec in self.waiting_model_specs
        }

    def stop_waiting_feedback(self) -> None:
        self.waiting_source_key = ""
        self.waiting_source_name = ""
        self.waiting_model_specs = []
        self.waiting_model_state = {}
        self.wait_elapsed_s = 0
        self.wait_round = 0

    def clear_waiting_source(self, source_key: str) -> bool:
        if source_key and source_key == self.waiting_source_key:
            self.stop_waiting_feedback()
            return True
        return False

    def build_waiting_detail_rows(self, model_specs: list[dict[str, str]]) -> list[dict[str, object]]:
        if not self.waiting_model_specs:
            return []
        if self.waiting_source_key and self.waiting_source_key in self.question_ref_payloads:
            return []
        display_specs = model_specs or self.waiting_model_specs
        waiting_map = {str(spec.get("key") or ""): spec for spec in self.waiting_model_specs}
        finished_count = 0
        row_values = [self.waiting_source_name or "处理中"]
        for spec in display_specs:
            model_key = str(spec.get("key") or "")
            if model_key in waiting_map:
                state = self.waiting_model_state.get(model_key, {})
                if bool(state.get("done")):
                    finished_count += 1
                    elapsed_s = int(state.get("elapsed_s") or 0)
                    marker = str(state.get("marker") or "").strip()
                    status_text = f"异常 {elapsed_s}s" if marker else f"完成 {elapsed_s}s"
                else:
                    status_text = f"等待 {self.wait_elapsed_s}s"
                row_values.extend([status_text, status_text])
            else:
                row_values.extend(["", ""])
        row_values.append(f"第{max(1, self.wait_round)}轮，已返回 {finished_count}/{len(self.waiting_model_specs)}")
        row_values.append("")
        return [{"cells": row_values, "source_key": "", "number": "", "manual_type": ""}]

    def tick_waiting_feedback(self) -> None:
        self.wait_elapsed_s += 1
