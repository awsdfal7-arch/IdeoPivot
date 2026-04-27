from __future__ import annotations

import re


def extract_question_ref_source_name(msg: str, current_source_name: str) -> str:
    text = str(msg or "")
    current = str(current_source_name or "").strip() or "-"
    by_colon = re.match(r"^([^：]+)：", text)
    if by_colon:
        return by_colon.group(1)
    by_phase = re.search(r"^(.+?)：题号与题型解析中", text)
    if by_phase:
        return by_phase.group(1)
    return current


def parse_content_progress_message(msg: str) -> dict[str, object]:
    text = str(msg or "")
    parsed: dict[str, object] = {
        "skipped_delta": 1 if "已跳过" in text else 0,
    }

    source_match = re.match(r"^([^：]+)：", text)
    if source_match:
        parsed["source_name"] = source_match.group(1)

    parallel_match = re.search(
        r"第\s*(\d+)\s*/\s*(\d+)\s*题（题号\s*([^，]+)，第\s*(\d+)\s*/\s*(\d+)\s*轮，多模型并行请求中）",
        text,
    )
    if parallel_match:
        question_index, total_count, _number, round_no, total_rounds = parallel_match.groups()
        parsed["question_no"] = question_index
        parsed["round_no"] = round_no
        parsed["parallel_text"] = f"并行状态：第 {round_no}/{total_rounds} 轮多模型并行请求中（题目 {question_index}/{total_count}）"
        return parsed

    accepted_match = re.search(
        r"第\s*(\d+)\s*/\s*(\d+)\s*题（题号\s*([^，]+)，第\s*(\d+)\s*/\s*(\d+)\s*轮，达到一致阈值）",
        text,
    )
    if accepted_match:
        question_index, total_count, _number, round_no, total_rounds = accepted_match.groups()
        parsed["consistency_text"] = f"一致性结论：第 {round_no}/{total_rounds} 轮一致（题目 {question_index}/{total_count}）"
        parsed["parallel_text"] = ""
        return parsed

    rejected_match = re.search(
        r"第\s*(\d+)\s*/\s*(\d+)\s*题（题号\s*([^，]+)，第\s*(\d+)\s*/\s*(\d+)\s*轮，未达到一致阈值）",
        text,
    )
    if rejected_match:
        question_index, total_count, _number, round_no, total_rounds = rejected_match.groups()
        parsed["consistency_text"] = f"一致性结论：第 {round_no}/{total_rounds} 轮不一致（题目 {question_index}/{total_count}）"
        return parsed

    detail_match = re.search(
        r"第\s*(\d+)\s*/\s*(\d+)\s*题（题号\s*([^，]+)，第\s*(\d+)\s*/\s*(\d+)\s*轮，([^）]+)）",
        text,
    )
    if detail_match:
        question_index, total_count, number, round_no, total_rounds, model_name = detail_match.groups()
        parsed["question_no"] = question_index
        parsed["round_no"] = round_no
        parsed["detail_text"] = (
            f"当前题：{question_index}/{total_count}；题号：{number}；"
            f"轮次：{round_no}/{total_rounds}；模型：{model_name}"
        )
    return parsed
