from __future__ import annotations

import re
from datetime import date

from sj_generator.io.excel_repo import try_parse_options_json
from sj_generator.models import Question


_BR_RE = re.compile(r"<br\s*/?>", flags=re.IGNORECASE)


def export_questions_to_markdown(
    *,
    excel_file_name: str,
    export_date: date,
    questions: list[Question],
    convertible_multi_mode: str = "keep_combo",
    include_answers: bool = True,
    include_analysis: bool = True,
) -> str:
    lines: list[str] = []

    header = (
        f"# 所属部分：{excel_file_name}  "
        f"日期：{export_date.year:04d}年{export_date.month:02d}月{export_date.day:02d}日"
    )
    lines.append(header)
    lines.append("")

    normalized = _normalize_numbers(questions)
    for q in normalized:
        stem_lines = _split_lines(_normalize_breaks(q.stem))
        options_block = _format_options_block(q.options, convertible_multi_mode=convertible_multi_mode)
        if options_block:
            stem_lines = _ensure_choice_blank(stem_lines)

        first = stem_lines[0] if stem_lines else ""
        lines.append(f" {q.number}. {first}".rstrip())
        if len(stem_lines) > 1:
            lines.extend(stem_lines[1:])
        if options_block:
            lines.extend(options_block)

        lines.append("")

    if lines and lines[-1] == "":
        lines.pop()

    if include_answers or include_analysis:
        lines.append("")
        if include_answers and include_analysis:
            lines.append("## 答案与解析")
        elif include_answers:
            lines.append("## 答案")
        else:
            lines.append("## 解析")
        lines.append("")

        for q in normalized:
            row_parts: list[str] = [q.number.strip()]
            if include_answers:
                row_parts.append(q.answer.strip())
            header_text = ". ".join(part for part in row_parts if part).strip()
            if header_text:
                lines.append(f"**{header_text}**")
            if include_analysis:
                analysis_lines = [
                    s for s in _split_lines(_normalize_breaks(q.analysis)) if s.strip()
                ]
                lines.extend(analysis_lines)
            lines.append("")

        if lines and lines[-1] == "":
            lines.pop()

    return "\n".join(lines) + "\n"


def _normalize_numbers(questions: list[Question]) -> list[Question]:
    result: list[Question] = []
    used_numbers: set[int] = set()
    for q in questions:
        s = q.number.strip()
        if s.isdigit():
            used_numbers.add(int(s))
    next_no = (max(used_numbers) + 1) if used_numbers else 1
    for q in questions:
        number = q.number.strip()
        if not number.isdigit():
            while next_no in used_numbers:
                next_no += 1
            number = str(next_no)
            used_numbers.add(next_no)
            next_no += 1
        result.append(
            Question(
                number=number,
                stem=q.stem,
                options=q.options,
                answer=q.answer,
                analysis=q.analysis,
            )
        )
    return result


def _format_options_block(options: str, *, convertible_multi_mode: str = "keep_combo") -> list[str]:
    options = _normalize_breaks(options)
    parsed = try_parse_options_json(options)
    if parsed is not None:
        keys = sorted(parsed.keys(), key=_option_key_sort_key)
        return [f"{k}. {parsed[k]}".rstrip() for k in keys]

    options = _force_newline_before_markers(options)
    lines = _split_lines(options)
    lines = [line for line in lines if line.strip()]
    return _normalize_convertible_multi_option_lines(lines, convertible_multi_mode=convertible_multi_mode)


def _force_newline_before_markers(text: str) -> str:
    if not text.strip():
        return ""

    letter = r"(?<!^)(?=(?:[A-Z][\.、]))"
    circled = r"(?<!^)(?=(?:[\u2460-\u2473]))"
    out_lines: list[str] = []
    for raw_line in text.split("\n"):
        line = raw_line.rstrip()
        if not line:
            out_lines.append("")
            continue
        line = re.sub(letter, "\n", line)
        if not re.match(r"^\s*[A-Z][\.、．:：]", line):
            line = re.sub(circled, "\n", line)
        out_lines.extend(line.split("\n"))
    return "\n".join(out_lines)


def _normalize_breaks(text: str) -> str:
    text = _BR_RE.sub("\n", text)
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _split_lines(text: str) -> list[str]:
    if not text:
        return []
    return [line.rstrip() for line in text.split("\n")]


def _normalize_convertible_multi_option_lines(
    lines: list[str],
    *,
    convertible_multi_mode: str = "keep_combo",
) -> list[str]:
    if not lines:
        return []
    statement_lines = [line for line in lines if _is_circled_option_line(line)]
    combo_lines = sorted(
        [line for line in lines if _is_combo_mapping_line(line)],
        key=_combo_line_sort_key,
    )
    if statement_lines and combo_lines:
        other_lines = [line for line in lines if line not in statement_lines and line not in combo_lines]
        if convertible_multi_mode == "as_multi":
            return statement_lines + other_lines
        combo_line = "  ".join(line.strip() for line in combo_lines if line.strip())
        return statement_lines + other_lines + ([combo_line] if combo_line else [])
    return lines


def _is_circled_option_line(text: str) -> bool:
    return bool(re.match(r"^\s*[\u2460-\u2473][\.、．:：]?\s*", text))


def _is_combo_mapping_line(text: str) -> bool:
    return bool(re.match(r"^\s*[A-D][\.、．:：]\s*[\u2460-\u2473]+", text))


def _combo_line_sort_key(text: str) -> str:
    m = re.match(r"^\s*([A-D])", text)
    return m.group(1) if m else text


def _option_key_sort_key(key: str) -> tuple[int, str]:
    k = key.strip()
    if len(k) >= 1 and "A" <= k[0] <= "Z":
        return (0, k[0])
    return (1, k)


def _ensure_choice_blank(stem_lines: list[str]) -> list[str]:
    if not stem_lines:
        return stem_lines

    idx = None
    for i in range(len(stem_lines) - 1, -1, -1):
        if stem_lines[i].strip():
            idx = i
            break
    if idx is None:
        return stem_lines

    line = stem_lines[idx]
    if re.search(r"(（\s*）|\(\s*\))\s*$", line):
        return stem_lines

    m = re.search(r"([。？！；：\.])\s*$", line)
    if m:
        punc = m.group(1)
        body = line[: m.start(1)].rstrip()
        stem_lines[idx] = f"{body}（ ）{punc}"
    else:
        stem_lines[idx] = f"{line.rstrip()}（ ）"
    return stem_lines
