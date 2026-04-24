from __future__ import annotations

import ast
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import re
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable, Iterable

from sj_generator.ai.client import LlmClient
from sj_generator.ai.prompt_templates import get_import_prompt, render_import_prompt
from sj_generator.ai.task_runner import run_tasks_in_parallel
from sj_generator.models import Question


@dataclass(frozen=True)
class ImportResult:
    questions: list[Question]
    raw_items: list[dict[str, Any]]


_WS_RE = re.compile(r"\s+")
_CIRCLED_RE = re.compile(r"[\u2460-\u2473]")
_COMBO_RE = re.compile(r"([A-D])\s*[\.．、]\s*([\u2460-\u2473\s]+)")
_LETTER_ONLY_RE = re.compile(r"^[A-D]+$")
_LETTER_MARKER_RE = re.compile(r"(?<!\n)(?=(?:[A-D][\.、．]))")
_CIRCLED_MARKER_RE = re.compile(r"(?<!\n)(?=(?:[\u2460-\u2473][\.、．]?))")
_OPTION_KEYS = ("option_1", "option_2", "option_3", "option_4")
_STEM_NUMBER_PATTERNS = [
    re.compile(r"^\s*(\d+)\s*[\.\．、\):：]\s*(.+)$", re.S),
    re.compile(r"^\s*[\(（]\s*(\d+)\s*[\)）]\s*(.+)$", re.S),
    re.compile(r"^\s*第\s*(\d+)\s*题\s*[\.\．、:：]?\s*(.+)$", re.S),
]


def import_questions_from_sources(
    *,
    client: LlmClient,
    kimi_client: LlmClient | None = None,
    qwen_client: LlmClient | None = None,
    client_factory: Callable[[], LlmClient] | None = None,
    kimi_client_factory: Callable[[], LlmClient] | None = None,
    qwen_client_factory: Callable[[], LlmClient] | None = None,
    sources: list[tuple[Path, str]],
    max_chars_per_chunk: int = 6000,
    strategy: str = "per_question",
    max_question_workers: int = 1,
    progress_cb: Callable[[str], None] | None = None,
    question_cb: Callable[[Question], None] | None = None,
    compare_cb: Callable[[dict[str, Any]], None] | None = None,
    progress_count_cb: Callable[[int, int], None] | None = None,
    stop_cb: Callable[[], bool] | None = None,
) -> ImportResult:
    if strategy == "per_question":
        return _import_questions_per_question(
            client=client,
            kimi_client=kimi_client,
            qwen_client=qwen_client,
            client_factory=client_factory,
            kimi_client_factory=kimi_client_factory,
            qwen_client_factory=qwen_client_factory,
            sources=sources,
            max_chars_per_chunk=max_chars_per_chunk,
            max_question_workers=max_question_workers,
            progress_cb=progress_cb,
            question_cb=question_cb,
            compare_cb=compare_cb,
            progress_count_cb=progress_count_cb,
            stop_cb=stop_cb,
        )

    items: list[dict[str, Any]] = []
    for path, text in sources:
        text = text.strip()
        if not text:
            continue
        for chunk in _split_text(text, max_chars_per_chunk=max_chars_per_chunk):
            chunk_items = _extract_questions_with_fallback(
                client=client,
                source_name=path.name,
                chunk_text=chunk,
                depth=3,
            )
            items.extend(chunk_items)

    normalized: list[Question] = []
    seen: set[str] = set()
    for obj in items:
        q = _to_question(obj)
        key = _normalize_key(q.stem)
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        normalized.append(q)

    return ImportResult(questions=normalized, raw_items=items)

def _import_questions_per_question(
    *,
    client: LlmClient,
    kimi_client: LlmClient | None,
    qwen_client: LlmClient | None,
    client_factory: Callable[[], LlmClient] | None,
    kimi_client_factory: Callable[[], LlmClient] | None,
    qwen_client_factory: Callable[[], LlmClient] | None,
    sources: list[tuple[Path, str]],
    max_chars_per_chunk: int,
    max_question_workers: int,
    progress_cb: Callable[[str], None] | None,
    question_cb: Callable[[Question], None] | None,
    compare_cb: Callable[[dict[str, Any]], None] | None,
    progress_count_cb: Callable[[int, int], None] | None,
    stop_cb: Callable[[], bool] | None,
) -> ImportResult:
    items: list[dict[str, Any]] = []
    normalized: list[Question] = []
    seen: set[str] = set()
    for path, text in sources:
        if stop_cb and stop_cb():
            break
        text = text.strip()
        if not text:
            continue
        if progress_cb:
            progress_cb(f"{path.name}：统计题数…")
        question_refs = _normalize_question_ref_list(
            _get_question_number_list_verified(
            client=client,
            kimi_client=kimi_client,
            qwen_client=qwen_client,
            source_name=path.name,
            chunk_text=text,
            depth=3,
            )
        )
        if not question_refs:
            continue
        total_steps = len(question_refs)
        step = 0
        if progress_count_cb:
            progress_count_cb(0, total_steps)
        worker_count = max(1, int(max_question_workers))
        if worker_count <= 1:
            for i, question_ref in enumerate(question_refs, start=1):
                if stop_cb and stop_cb():
                    break
                question_number = _as_str(question_ref.get("number", ""))
                obj, err, meta = _process_one_question(
                    client=client,
                    kimi_client=kimi_client,
                    qwen_client=qwen_client,
                    source_name=path.name,
                    chunk_text=text,
                    index=i,
                    total=total_steps,
                    requested_number=question_number,
                    progress_cb=progress_cb,
                    compare_cb=compare_cb,
                    stop_cb=stop_cb,
                )
                step += 1
                if progress_count_cb:
                    progress_count_cb(step, total_steps)
                _collect_question_result(
                    index=i,
                    obj=obj,
                    err=err,
                    meta=meta,
                    progress_cb=progress_cb,
                    source_name=path.name,
                    items=items,
                    normalized=normalized,
                    seen=seen,
                    question_cb=question_cb,
                )
            continue

        if client_factory is None or kimi_client_factory is None or qwen_client_factory is None:
            raise ValueError("题级并发需要提供三模型客户端工厂。")

        task_items = [
            (i, _as_str(question_ref.get("number", "")), path.name, text)
            for i, question_ref in enumerate(question_refs, start=1)
        ]
        results_by_index: dict[int, tuple[dict[str, Any], bool, dict[str, Any]]] = {}

        def on_task_start(_current: int, _total_count: int, _task: tuple[int, str, str, str]) -> None:
            return

        def on_task_done(task: tuple[int, str, str, str], result: tuple[dict[str, Any], bool, dict[str, Any]]) -> None:
            nonlocal step
            index, _question_number, _source_name, _chunk_text = task
            results_by_index[index] = result
            step += 1
            if progress_count_cb:
                progress_count_cb(step, total_steps)

        def on_task_failed(task: tuple[int, str, str, str], exc: Exception) -> None:
            nonlocal step
            index, question_number, _source_name, _chunk_text = task
            results_by_index[index] = ({}, True, {"index": index, "accepted": False, "reason": str(exc)})
            results_by_index[index][2]["requested_number"] = question_number
            step += 1
            if progress_count_cb:
                progress_count_cb(step, total_steps)

        def run_one(task: tuple[int, str, str, str]) -> tuple[dict[str, Any], bool, dict[str, Any]]:
            index, question_number, source_name, chunk_text = task
            return _process_one_question(
                client=client_factory(),
                kimi_client=kimi_client_factory(),
                qwen_client=qwen_client_factory(),
                source_name=source_name,
                chunk_text=chunk_text,
                index=index,
                total=total_steps,
                requested_number=question_number,
                progress_cb=progress_cb,
                compare_cb=compare_cb,
                stop_cb=stop_cb,
            )

        run_tasks_in_parallel(
            tasks=task_items,
            max_workers=min(worker_count, total_steps),
            stop_cb=(stop_cb or (lambda: False)),
            on_task_start=on_task_start,
            on_task_done=on_task_done,
            on_task_failed=on_task_failed,
            run_one=run_one,
        )

        for i in sorted(results_by_index.keys()):
            obj, err, meta = results_by_index[i]
            _collect_question_result(
                index=i,
                obj=obj,
                err=err,
                meta=meta,
                progress_cb=progress_cb,
                source_name=path.name,
                items=items,
                normalized=normalized,
                seen=seen,
                question_cb=question_cb,
            )

    return ImportResult(questions=normalized, raw_items=items)


def _process_one_question(
    *,
    client: LlmClient,
    kimi_client: LlmClient | None,
    qwen_client: LlmClient | None,
    source_name: str,
    chunk_text: str,
    index: int,
    total: int,
    requested_number: str,
    progress_cb: Callable[[str], None] | None,
    compare_cb: Callable[[dict[str, Any]], None] | None,
    stop_cb: Callable[[], bool] | None,
) -> tuple[dict[str, Any], bool, dict[str, Any]]:
    def bump(model_name: str, round_no: int, check_no: int) -> None:
        if progress_cb:
            progress_cb(f"{source_name}：第 {index}/{total} 题（题号 {requested_number}，第 {round_no}/3 轮，{model_name}）…")

    def mark_round(round_no: int, status: str) -> None:
        if not progress_cb:
            return
        if status == "start":
            progress_cb(f"{source_name}：第 {index}/{total} 题（题号 {requested_number}，第 {round_no}/3 轮，三模型并行请求中）")
        elif status == "consistent":
            progress_cb(f"{source_name}：第 {index}/{total} 题（题号 {requested_number}，第 {round_no}/3 轮，达到一致阈值）")
        elif status == "inconsistent":
            progress_cb(f"{source_name}：第 {index}/{total} 题（题号 {requested_number}，第 {round_no}/3 轮，未达到一致阈值）")

    return _get_question_n_verified(
        client=client,
        kimi_client=kimi_client,
        qwen_client=qwen_client,
        source_name=source_name,
        chunk_text=chunk_text,
        index=index,
        requested_number=requested_number,
        depth=2,
        attempt_cb=bump,
        round_cb=mark_round,
        compare_cb=compare_cb,
        stop_cb=stop_cb,
    )


def _collect_question_result(
    *,
    index: int,
    obj: dict[str, Any],
    err: bool,
    meta: dict[str, Any],
    progress_cb: Callable[[str], None] | None,
    source_name: str,
    items: list[dict[str, Any]],
    normalized: list[Question],
    seen: set[str],
    question_cb: Callable[[Question], None] | None,
) -> None:
    if err:
        if str(meta.get("reason") or "").strip().lower() == "stopped":
            return
        if progress_cb:
            progress_cb(f"{source_name}：第 {index} 题解析有误，已跳过。")
        return
    if not obj:
        return
    items.append(obj)
    q = _to_question(obj)
    key = _normalize_key(q.stem)
    if key and key in seen:
        return
    if key:
        seen.add(key)
    normalized.append(q)
    if question_cb:
        question_cb(q)


def _question_extract_prompt_rules() -> str:
    return get_import_prompt("question_extract_system")


def _question_number_list_prompt_rules() -> str:
    return get_import_prompt("question_number_list_system")


def _normalize_question_ref_list(data: object) -> list[dict[str, str]]:
    if not isinstance(data, list):
        return []
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in data:
        if isinstance(item, dict):
            number = _as_str(item.get("number", ""))
            question_type = _normalize_question_type_text(_as_str(item.get("question_type", "")))
        else:
            number = _as_str(item)
            question_type = ""
        if not number or number in seen:
            continue
        seen.add(number)
        row = {"number": number}
        if question_type:
            row["question_type"] = question_type
        out.append(row)
    return out


def _normalize_question_type_text(value: str) -> str:
    text = _normalize_text(value)
    if "可转多选" in text:
        return "可转多选"
    if "多选" in text:
        return "多选"
    if "单选" in text:
        return "单选"
    return ""


def _get_question_numbers_in_chunk(
    *,
    client: LlmClient,
    source_name: str,
    chunk_text: str,
) -> list[dict[str, str]]:
    sys_prompt = _question_number_list_prompt_rules()
    user_prompt = render_import_prompt(
        "question_number_list_user",
        source_name=source_name,
        chunk_text=chunk_text,
    )
    data = client.chat_json(system=sys_prompt, user=user_prompt)
    return _normalize_question_ref_list(data)


def _get_question_numbers_with_fallback(
    *,
    client: LlmClient,
    source_name: str,
    chunk_text: str,
    depth: int,
) -> list[dict[str, str]]:
    try:
        return _get_question_numbers_in_chunk(client=client, source_name=source_name, chunk_text=chunk_text)
    except Exception as e:
        msg = str(e).lower()
        if depth <= 0 or len(chunk_text) < 1500:
            raise
        if "timed out" not in msg and "超时" not in msg:
            raise
        out: list[dict[str, str]] = []
        seen: set[str] = set()
        for sub in _split_text(chunk_text, max_chars_per_chunk=max(800, len(chunk_text) // 2)):
            for question_ref in _get_question_numbers_with_fallback(
                client=client,
                source_name=source_name,
                chunk_text=sub,
                depth=depth - 1,
            ):
                number = _as_str(question_ref.get("number", ""))
                if number in seen:
                    continue
                seen.add(number)
                out.append(question_ref)
        return out


def _get_question_number_list_verified(
    *,
    client: LlmClient,
    kimi_client: LlmClient | None,
    qwen_client: LlmClient | None,
    source_name: str,
    chunk_text: str,
    depth: int,
) -> list[dict[str, str]]:
    if kimi_client is None or qwen_client is None:
        raise RuntimeError("缺少 Kimi 或千问客户端，无法校验题号列表。")
    results: dict[str, list[dict[str, str]]] = {}
    with ThreadPoolExecutor(max_workers=3) as ex:
        future_map = {
            ex.submit(
                _get_question_numbers_with_fallback,
                client=client,
                source_name=source_name,
                chunk_text=chunk_text,
                depth=depth,
            ): "DeepSeek",
            ex.submit(
                _get_question_numbers_with_fallback,
                client=kimi_client,
                source_name=source_name,
                chunk_text=chunk_text,
                depth=depth,
            ): "Kimi",
            ex.submit(
                _get_question_numbers_with_fallback,
                client=qwen_client,
                source_name=source_name,
                chunk_text=chunk_text,
                depth=depth,
            ): "千问",
        }
        for future in as_completed(future_map):
            model_name = future_map[future]
            results[model_name] = future.result()
    deepseek_numbers = results.get("DeepSeek", [])
    kimi_numbers = results.get("Kimi", [])
    qwen_numbers = results.get("千问", [])
    if deepseek_numbers == kimi_numbers == qwen_numbers:
        return deepseek_numbers
    raise RuntimeError(
        f"{source_name}：三模型识别出的选择题题号列表不一致，无法继续导入。"
        f" DeepSeek={deepseek_numbers}；Kimi={kimi_numbers}；千问={qwen_numbers}"
    )


def _extract_questions_from_chunk(
    *,
    client: LlmClient,
    source_name: str,
    chunk_text: str,
) -> list[dict[str, Any]]:
    sys_prompt = (
        _question_extract_prompt_rules()
        +
        "输出格式：JSON 数组，每项为对象：\n"
        "{\n"
        '  "question_type": "题型(单选/多选/可转多选；可转多选示例：可转多选)",\n'
        '  "number": "编号(可为空)",\n'
        '  "stem": "题干(普通题示例：我国社会主义民主政治的本质特征是什么？；可转多选题示例：阅读材料，贯彻绿色发展理念需要坚持哪些做法？)",\n'
        '  "option_1": "第1个选项正文；单选/多选通常对应A项，可转多选对应①项；不要包含选项标识",\n'
        '  "option_2": "第2个选项正文；单选/多选通常对应B项，可转多选对应②项；不要包含选项标识",\n'
        '  "option_3": "第3个选项正文；单选/多选通常对应C项，可转多选对应③项；不要包含选项标识",\n'
        '  "option_4": "第4个选项正文；单选/多选通常对应D项，可转多选对应④项；不要包含选项标识",\n'
        '  "choice_1": "可转多选时 A 对应的数字映射，例如 12；非可转多选留空",\n'
        '  "choice_2": "可转多选时 B 对应的数字映射，例如 14；非可转多选留空",\n'
        '  "choice_3": "可转多选时 C 对应的数字映射，例如 23；非可转多选留空",\n'
        '  "choice_4": "可转多选时 D 对应的数字映射，例如 24；非可转多选留空",\n'
        '  "answer": "答案(单选示例：A；多选示例：ACD；可转多选示例：B)"\n'
        "}\n"
        "如果某一题无法稳定识别，请不要输出半截对象，也不要输出无意义字段。\n"
    )

    user_prompt = (
        f"来源文件：{source_name}\n"
        f"导入日期：{date.today().isoformat()}\n"
        "资料文本如下：\n"
        "-----\n"
        f"{chunk_text}\n"
        "-----\n"
        "请输出严格 JSON 数组。"
    )

    data = client.chat_json(system=sys_prompt, user=user_prompt)
    if isinstance(data, list):
        out: list[dict[str, Any]] = []
        for it in data:
            if isinstance(it, dict):
                out.append(_normalize_question_obj_for_view(it))
        return out
    return []

def _extract_questions_with_fallback(
    *,
    client: LlmClient,
    source_name: str,
    chunk_text: str,
    depth: int,
) -> list[dict[str, Any]]:
    try:
        return _extract_questions_from_chunk(client=client, source_name=source_name, chunk_text=chunk_text)
    except Exception as e:
        msg = str(e)
        if depth <= 0 or len(chunk_text) < 1500:
            raise
        if "timed out" not in msg.lower() and "超时" not in msg:
            raise

        sub_items: list[dict[str, Any]] = []
        for sub in _split_text(chunk_text, max_chars_per_chunk=max(800, len(chunk_text) // 2)):
            sub_items.extend(
                _extract_questions_with_fallback(
                    client=client,
                    source_name=source_name,
                    chunk_text=sub,
                    depth=depth - 1,
                )
            )
        return sub_items

def _get_question_by_number_in_chunk(
    *,
    client: LlmClient,
    source_name: str,
    chunk_text: str,
    requested_number: str,
) -> dict[str, Any]:
    sys_prompt = _question_extract_prompt_rules()
    user_prompt = render_import_prompt(
        "question_extract_user",
        source_name=source_name,
        requested_number=requested_number,
        chunk_text=chunk_text,
    )
    data = client.chat_json(system=sys_prompt, user=user_prompt)
    return _normalize_question_obj_for_view(data) if isinstance(data, dict) else {}


def _get_question_by_number_with_fallback(
    *,
    client: LlmClient,
    source_name: str,
    chunk_text: str,
    requested_number: str,
    depth: int,
) -> dict[str, Any]:
    try:
        return _get_question_by_number_in_chunk(
            client=client,
            source_name=source_name,
            chunk_text=chunk_text,
            requested_number=requested_number,
        )
    except Exception as e:
        msg = str(e).lower()
        if depth <= 0 or len(chunk_text) < 1500:
            raise
        if "timed out" not in msg and "超时" not in msg:
            raise
        for sub in _split_text(chunk_text, max_chars_per_chunk=max(800, len(chunk_text) // 2)):
            obj = _get_question_by_number_with_fallback(
                client=client,
                source_name=source_name,
                chunk_text=sub,
                requested_number=requested_number,
                depth=depth - 1,
            )
            if obj:
                return obj
        return {}


def _get_question_n_verified(
    *,
    client: LlmClient,
    kimi_client: LlmClient | None,
    qwen_client: LlmClient | None,
    source_name: str,
    chunk_text: str,
    index: int,
    requested_number: str,
    depth: int,
    attempt_cb: Callable[[str, int, int], None] | None = None,
    round_cb: Callable[[int, str], None] | None = None,
    compare_cb: Callable[[dict[str, Any]], None] | None = None,
    stop_cb: Callable[[], bool] | None = None,
) -> tuple[dict[str, Any], bool, dict[str, Any]]:
    if kimi_client is None or qwen_client is None:
        return {}, True, {"index": index, "accepted": False, "reason": "missing_clients"}

    last_meta: dict[str, Any] = {"index": index, "accepted": False, "reason": "inconsistent"}
    cumulative_valid_objs: list[dict[str, Any]] = []
    for round_no in range(1, 4):
        if stop_cb and stop_cb():
            return {}, True, {"index": index, "accepted": False, "reason": "stopped"}
        if round_cb:
            round_cb(round_no, "start")
        results: dict[str, dict[str, Any]] = {"DeepSeek": {}, "Kimi": {}, "千问": {}}
        costs_sec: dict[str, float] = {"DeepSeek": 0.0, "Kimi": 0.0, "千问": 0.0}
        with ThreadPoolExecutor(max_workers=3) as ex:
            starts: dict[str, float] = {
                "DeepSeek": time.perf_counter(),
                "Kimi": time.perf_counter(),
                "千问": time.perf_counter(),
            }
            fut_map = {
                ex.submit(
                    _safe_get_question_by_number_with_fallback,
                    client=client,
                    source_name=source_name,
                    chunk_text=chunk_text,
                    requested_number=requested_number,
                    depth=depth,
                ): ("DeepSeek", 1),
                ex.submit(
                    _safe_get_question_by_number_with_fallback,
                    client=kimi_client,
                    source_name=source_name,
                    chunk_text=chunk_text,
                    requested_number=requested_number,
                    depth=depth,
                ): ("Kimi", 2),
                ex.submit(
                    _safe_get_question_by_number_with_fallback,
                    client=qwen_client,
                    source_name=source_name,
                    chunk_text=chunk_text,
                    requested_number=requested_number,
                    depth=depth,
                ): ("千问", 3),
            }
            for fut in as_completed(fut_map):
                model_name, check_no = fut_map[fut]
                costs_sec[model_name] = round(time.perf_counter() - starts[model_name], 3)
                if attempt_cb:
                    attempt_cb(model_name, round_no, check_no)
                try:
                    results[model_name] = fut.result() or {}
                except Exception:
                    results[model_name] = {}

        obj_a = results["DeepSeek"]
        obj_b = results["Kimi"]
        obj_c = results["千问"]
        round_valid_objs = [obj for obj in [obj_a, obj_b, obj_c] if _is_valid_question_obj(obj)]
        _, round_matched_count = _pick_consensus_obj(round_valid_objs, 1)
        cumulative_valid_objs.extend(round_valid_objs)
        required_count = round_no + 1
        accepted_obj, matched_count = _pick_consensus_obj(cumulative_valid_objs, required_count)
        last_meta = {
            "index": index,
            "requested_number": requested_number,
            "round": round_no,
            "deepseek": _normalize_question_obj_for_view(obj_a),
            "kimi": _normalize_question_obj_for_view(obj_b),
            "qwen": _normalize_question_obj_for_view(obj_c),
            "deepseek_sec": costs_sec["DeepSeek"],
            "kimi_sec": costs_sec["Kimi"],
            "qwen_sec": costs_sec["千问"],
            "round_matched_count": round_matched_count,
            "round_valid_count": len(round_valid_objs),
            "required_count": required_count,
            "matched_count": matched_count,
            "valid_count": len(cumulative_valid_objs),
            "accepted": False,
            "reason": "inconsistent",
        }
        if compare_cb is not None:
            compare_cb(last_meta)
        if accepted_obj:
            if round_cb:
                round_cb(round_no, "consistent")
            accepted_obj = _normalize_question_obj_for_view(accepted_obj)
            last_meta["accepted"] = True
            last_meta["reason"] = "consistent"
            last_meta["accepted_obj"] = accepted_obj
            if compare_cb is not None:
                compare_cb(last_meta)
            return accepted_obj, False, last_meta
        if round_cb:
            round_cb(round_no, "inconsistent")
    return {}, True, last_meta


def _safe_get_question_by_number_with_fallback(
    *,
    client: LlmClient,
    source_name: str,
    chunk_text: str,
    requested_number: str,
    depth: int,
) -> dict[str, Any]:
    try:
        return _get_question_by_number_with_fallback(
            client=client,
            source_name=source_name,
            chunk_text=chunk_text,
            requested_number=requested_number,
            depth=depth,
        )
    except Exception:
        return {}


def _to_question(obj: dict[str, Any]) -> Question:
    number = _as_str(obj.get("number", ""))
    stem = _as_str(obj.get("stem", ""))
    number, stem = _split_number_and_stem(number, stem)
    question_type = _normalize_question_type_value(obj)
    option_values = _option_values_from_obj(obj, question_type=question_type)
    options_str = _build_options_string(option_values, question_type=question_type)
    answer = _as_str(obj.get("answer", ""))
    analysis = _original_analysis_text(obj)
    q = Question(
        number=number,
        stem=stem,
        options=options_str,
        answer=answer,
        analysis=analysis,
        question_type=question_type,
        choice_1=_normalize_choice_digits(_as_str(obj.get("choice_1", ""))),
        choice_2=_normalize_choice_digits(_as_str(obj.get("choice_2", ""))),
        choice_3=_normalize_choice_digits(_as_str(obj.get("choice_3", ""))),
        choice_4=_normalize_choice_digits(_as_str(obj.get("choice_4", ""))),
    )
    return _normalize_combination_question(q)


def _normalize_combination_question(q: Question) -> Question:
    combined = "\n".join([q.stem or "", q.options or ""]).strip()
    if not combined and not _question_choice_map(q):
        return q

    statements = _extract_circled_statements(combined)
    combos = _question_choice_map(q) or _extract_combo_map(combined)
    is_convertible = q.question_type == "可转多选" or bool(combos)
    if not is_convertible:
        return q

    if len(statements) < 2 and q.options.strip():
        statements = _split_circled_option_lines(q.options)
    if len(statements) < 2:
        return q

    answer = (q.answer or "").strip().replace(" ", "")
    answer = _normalize_convertible_answer(answer, combos)

    new_options = "\n".join(statements).strip()
    new_stem = q.stem
    first = _CIRCLED_RE.search(new_stem or "")
    if first is not None:
        prefix = (new_stem or "")[: first.start()].strip()
        if prefix:
            new_stem = prefix

    return Question(
        number=q.number,
        stem=new_stem,
        options=new_options,
        answer=answer,
        analysis=q.analysis,
        question_type="可转多选",
        choice_1=combos.get("A", ""),
        choice_2=combos.get("B", ""),
        choice_3=combos.get("C", ""),
        choice_4=combos.get("D", ""),
    )


def _extract_combo_map(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in _COMBO_RE.finditer(text):
        letter = m.group(1)
        digits = _normalize_choice_digits("".join(_CIRCLED_RE.findall(m.group(2))))
        if digits:
            out[letter] = digits
    return out


def _split_circled_option_lines(text: str) -> list[str]:
    return [line.strip() for line in _normalize_text(text).split("\n") if line.strip() and _CIRCLED_RE.match(line.strip())]


def _question_choice_map(q: Question) -> dict[str, str]:
    return {
        letter: value
        for letter, value in (
            ("A", _normalize_choice_digits(q.choice_1)),
            ("B", _normalize_choice_digits(q.choice_2)),
            ("C", _normalize_choice_digits(q.choice_3)),
            ("D", _normalize_choice_digits(q.choice_4)),
        )
        if value
    }


def _normalize_choice_digits(text: str) -> str:
    if not text:
        return ""
    circled_chars = _CIRCLED_RE.findall(text)
    if circled_chars:
        return "".join(str(ord(ch) - 0x245F) for ch in circled_chars)
    return "".join(re.findall(r"\d+", text))


def _normalize_convertible_answer(answer: str, combo_map: dict[str, str]) -> str:
    upper = _as_str(answer).replace(" ", "").upper()
    if not upper:
        return ""
    if _LETTER_ONLY_RE.fullmatch(upper):
        return upper
    digits = _normalize_choice_digits(upper)
    if digits:
        mapped = _choice_digits_to_letter(digits, combo_map)
        return mapped or digits
    return upper


def _choice_digits_to_letter(digits: str, combo_map: dict[str, str]) -> str:
    normalized = _normalize_choice_digits(digits)
    if not normalized:
        return ""
    for letter in ("A", "B", "C", "D"):
        if _normalize_choice_digits(combo_map.get(letter, "")) == normalized:
            return letter
    return ""


def _extract_circled_statements(text: str) -> list[str]:
    circled = list(_CIRCLED_RE.finditer(text))
    if not circled:
        return []

    first_combo = _COMBO_RE.search(text)
    combo_start = first_combo.start() if first_combo is not None else len(text)

    out: list[str] = []
    for i, m in enumerate(circled):
        start = m.start()
        if start >= combo_start:
            break
        end = combo_start
        if i + 1 < len(circled):
            end = min(end, circled[i + 1].start())
        seg = text[m.end() : end].strip()
        if seg:
            out.append(f"{m.group(0)}{seg}")
    return out


def _sort_circled(text: str) -> str:
    order = [chr(c) for c in range(0x2460, 0x2474)]
    present = set(_CIRCLED_RE.findall(text))
    return "".join([c for c in order if c in present])


def _split_text(text: str, *, max_chars_per_chunk: int) -> Iterable[str]:
    if len(text) <= max_chars_per_chunk:
        yield text
        return

    lines = text.splitlines()
    buf: list[str] = []
    size = 0
    for line in lines:
        ln = line.rstrip()
        if not ln:
            if buf:
                buf.append("")
                size += 1
            continue
        if size + len(ln) + 1 > max_chars_per_chunk and buf:
            yield "\n".join(buf).strip() + "\n"
            buf = []
            size = 0
        buf.append(ln)
        size += len(ln) + 1
    if buf:
        yield "\n".join(buf).strip() + "\n"


def _normalize_key(stem: str) -> str:
    s = stem.strip()
    s = s.replace("\r", "\n")
    s = _WS_RE.sub(" ", s)
    return s.strip().lower()


def _as_str(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    return str(v).strip()


def _all_same(objs: list[dict[str, Any]]) -> bool:
    if not objs:
        return False
    fp0 = _fingerprint_question_obj(objs[0])
    return all(_fingerprint_question_obj(o) == fp0 for o in objs[1:])


def _pick_consensus_obj(objs: list[dict[str, Any]], min_count: int) -> tuple[dict[str, Any], int]:
    if min_count <= 0:
        return {}, 0
    counter: dict[str, tuple[int, dict[str, Any]]] = {}
    for obj in objs:
        fp = _fingerprint_question_obj(obj)
        if not fp:
            continue
        if fp not in counter:
            counter[fp] = (1, obj)
            continue
        count, sample = counter[fp]
        counter[fp] = (count + 1, sample)
    best_obj: dict[str, Any] = {}
    best_count = 0
    for count, sample in counter.values():
        if count > best_count:
            best_count = count
            best_obj = sample
    if best_count >= min_count:
        return best_obj, best_count
    return {}, best_count


def _is_valid_question_obj(obj: dict[str, Any]) -> bool:
    if not isinstance(obj, dict) or not obj:
        return False
    stem = _normalize_text(_as_str(obj.get("stem", "")))
    answer = _as_str(obj.get("answer", "")).replace(" ", "").upper()
    question_type = _normalize_question_type_value(obj)
    opt_text = _normalize_text(_canonical_options_text(obj, question_type=question_type))
    has_choice_fields = _has_choice_fields_obj(obj)
    if _has_circled_only_options(opt_text) and _has_letter_only_answer(answer) and not has_choice_fields:
        return False
    if question_type == "可转多选" and not has_choice_fields and not _extract_combo_map("\n".join([stem, opt_text])):
        return False
    return bool(stem and opt_text and question_type)


def _has_circled_only_options(options_text: str) -> bool:
    text = _normalize_text(options_text)
    if not text:
        return False
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if len(lines) < 2:
        return False
    circled_lines = 0
    letter_lines = 0
    for line in lines:
        if line and _CIRCLED_RE.match(line):
            circled_lines += 1
        if re.match(r"^[A-D][\.．、]", line):
            letter_lines += 1
    return circled_lines >= 2 and letter_lines == 0


def _has_letter_only_answer(answer: str) -> bool:
    return bool(answer) and bool(_LETTER_ONLY_RE.fullmatch(answer))


def _normalize_options_dict(d: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in d.items():
        ks = _as_str(k)
        vs = _normalize_text(_as_str(v))
        if ks and vs:
            out[ks] = vs
    return out


def _has_option_fields_obj(obj: dict[str, Any]) -> bool:
    return any(_as_str(obj.get(key, "")) for key in _OPTION_KEYS)


def _option_values_from_obj(obj: dict[str, Any], *, question_type: str) -> list[str]:
    option_values = [_normalize_option_value(_as_str(obj.get(key, ""))) for key in _OPTION_KEYS]
    if any(option_values):
        return option_values
    return _legacy_option_values(obj.get("options", ""), question_type=question_type)


def _legacy_option_values(options: Any, *, question_type: str) -> list[str]:
    if isinstance(options, dict):
        values = [
            _normalize_option_value(value)
            for _key, value in sorted(_normalize_options_dict(options).items(), key=lambda item: item[0])
        ]
        return (values + ["", "", "", ""])[:4]
    text = _normalize_text(_options_to_string(options))
    if not text:
        return ["", "", "", ""]
    normalized = _force_newline_before_option_markers(text)
    lines = [line.strip() for line in normalized.split("\n") if line.strip()]
    values: list[str] = []
    current_parts: list[str] = []
    for line in lines:
        if _starts_with_option_marker(line):
            if current_parts:
                values.append(_normalize_option_value(" ".join(current_parts)))
            current_parts = [_strip_option_marker(line)]
            continue
        if current_parts:
            current_parts.append(line)
        else:
            current_parts = [_strip_option_marker(line)]
    if current_parts:
        values.append(_normalize_option_value(" ".join(current_parts)))
    values = [value for value in values if value]
    return (values + ["", "", "", ""])[:4]


def _canonical_options_text(obj: dict[str, Any], *, question_type: str) -> str:
    if _has_option_fields_obj(obj):
        return _build_options_string(_option_values_from_obj(obj, question_type=question_type), question_type=question_type)
    options = obj.get("options", "")
    if isinstance(options, dict):
        return json.dumps(_normalize_options_dict(options), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _normalize_text(_options_to_string(options))


def _build_options_string(option_values: list[str], *, question_type: str) -> str:
    qtype = question_type if question_type in ("单选", "多选", "可转多选") else "单选"
    markers = ["①", "②", "③", "④"] if qtype == "可转多选" else ["A", "B", "C", "D"]
    lines = [
        f"{marker}. {value}".rstrip()
        for marker, value in zip(markers, option_values)
        if _normalize_option_value(value)
    ]
    return "\n".join(lines).strip()


def _force_newline_before_option_markers(text: str) -> str:
    out = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    out = _LETTER_MARKER_RE.sub("\n", out)
    out = _CIRCLED_MARKER_RE.sub("\n", out)
    return out.strip()


def _starts_with_option_marker(text: str) -> bool:
    s = text.strip()
    return bool(re.match(r"^[A-D][\.\u3001\uFF0E:：]", s) or re.match(r"^[\u2460-\u2473][\.\u3001\uFF0E:：]?", s))


def _strip_option_marker(text: str) -> str:
    s = _normalize_text(text)
    s = re.sub(r"^\s*[A-D][\.\u3001\uFF0E:：]\s*", "", s)
    s = re.sub(r"^\s*[\u2460-\u2473][\.\u3001\uFF0E:：]?\s*", "", s)
    return s.strip()


def _normalize_option_value(text: str) -> str:
    return _strip_option_marker(text)


def _options_to_string(v: Any) -> str:
    if isinstance(v, list):
        lines = [_as_str(it) for it in v]
        return "\n".join([ln for ln in lines if ln]).strip()
    if isinstance(v, tuple):
        lines = [_as_str(it) for it in v]
        return "\n".join([ln for ln in lines if ln]).strip()
    if isinstance(v, str):
        parsed = _parse_options_list_text(v)
        if parsed is not None:
            return _options_to_string(parsed)
    return _as_str(v)


def _parse_options_list_text(text: str) -> list[Any] | None:
    s = _as_str(text)
    if not (s.startswith("[") and s.endswith("]")):
        return None
    try:
        data = json.loads(s)
        if isinstance(data, list):
            return data
    except Exception:
        pass
    try:
        data = ast.literal_eval(s)
        if isinstance(data, list):
            return data
    except Exception:
        return None
    return None


def _split_number_and_stem(number: str, stem: str) -> tuple[str, str]:
    num = _as_str(number)
    s = _as_str(stem)
    if not s:
        return num, s
    for pat in _STEM_NUMBER_PATTERNS:
        m = pat.match(s)
        if not m:
            continue
        candidate_num = _as_str(m.group(1))
        candidate_stem = _as_str(m.group(2))
        if not candidate_stem:
            continue
        if not num:
            return candidate_num, candidate_stem
        if num == candidate_num:
            return num, candidate_stem
    return num, s


def _normalize_question_obj_for_view(obj: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(obj, dict) or not obj:
        return {}
    out = dict(obj)
    q = _to_question(out)
    option_values = _option_values_from_obj(out, question_type=q.question_type)
    out["number"] = q.number
    out["stem"] = q.stem
    out["answer"] = q.answer
    out["question_type"] = q.question_type or _normalize_question_type_value(out)
    for idx, value in enumerate(option_values, start=1):
        out[f"option_{idx}"] = value
    out.pop("options", None)
    out["choice_1"] = q.choice_1
    out["choice_2"] = q.choice_2
    out["choice_3"] = q.choice_3
    out["choice_4"] = q.choice_4
    out["original_analysis"] = q.analysis
    return out


def _normalize_text(text: str) -> str:
    s = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln.strip() for ln in s.split("\n")]
    s = "\n".join([ln for ln in lines if ln])
    s = _WS_RE.sub(" ", s)
    return s.strip()


def _fingerprint_question_obj(obj: dict[str, Any]) -> str:
    if not isinstance(obj, dict):
        return ""
    question_type = _normalize_question_type_value(obj)
    stem = _normalize_text(_as_str(obj.get("stem", "")))
    answer = _as_str(obj.get("answer", "")).replace(" ", "").upper()
    option_values = _option_values_from_obj(obj, question_type=question_type)
    payload = {
        "question_type": question_type,
        "stem": stem,
        "option_1": option_values[0],
        "option_2": option_values[1],
        "option_3": option_values[2],
        "option_4": option_values[3],
        "answer": answer,
        "choice_1": _normalize_choice_digits(_as_str(obj.get("choice_1", ""))),
        "choice_2": _normalize_choice_digits(_as_str(obj.get("choice_2", ""))),
        "choice_3": _normalize_choice_digits(_as_str(obj.get("choice_3", ""))),
        "choice_4": _normalize_choice_digits(_as_str(obj.get("choice_4", ""))),
        "original_analysis": _normalize_text(_original_analysis_text(obj)),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _original_analysis_text(obj: dict[str, Any]) -> str:
    return _as_str(obj.get("original_analysis", "")) or _as_str(obj.get("analysis", ""))


def _normalize_question_type_value(obj: dict[str, Any]) -> str:
    raw = _as_str(obj.get("question_type", ""))
    if raw in ("单选", "多选", "可转多选"):
        return raw
    if _has_choice_fields_obj(obj):
        return "可转多选"
    options_text = _normalize_text(_canonical_options_text(obj, question_type=raw))
    answer = _as_str(obj.get("answer", "")).replace(" ", "").upper()
    if _has_circled_only_options(options_text):
        return "可转多选"
    if _has_multi_answer(answer):
        return "多选"
    return "单选"


def _has_choice_fields_obj(obj: dict[str, Any]) -> bool:
    return any(
        _normalize_choice_digits(_as_str(obj.get(key, "")))
        for key in ("choice_1", "choice_2", "choice_3", "choice_4")
    )


def _has_multi_answer(answer: str) -> bool:
    if not answer:
        return False
    if "," in answer:
        return len([part.strip() for part in answer.split(",") if part.strip()]) > 1
    if _LETTER_ONLY_RE.fullmatch(answer):
        return len(answer) > 1
    circled_chars = _CIRCLED_RE.findall(answer)
    return len(circled_chars) > 1
