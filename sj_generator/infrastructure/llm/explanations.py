from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sj_generator.infrastructure.llm.client import LlmClient
from sj_generator.infrastructure.llm.prompt_templates import render_import_prompt
from sj_generator.shared.paths import common_mistakes_md_path


@dataclass(frozen=True)
class ExplanationInputs:
    question_text: str
    answer_text: str
    reference_md_paths: list[Path] | None = None
    include_common_mistakes: bool = True
    root_dir: Path | None = None


@dataclass(frozen=True)
class ExplanationResult:
    answer_text: str
    analysis_text: str


_NONEMPTY_LINE_RE = re.compile(r".*\S.*")


def generate_explanation(client: LlmClient, inp: ExplanationInputs) -> str:
    return generate_explanation_result(client, inp).analysis_text


def generate_explanation_result(client: LlmClient, inp: ExplanationInputs) -> ExplanationResult:
    reference_text = ""
    if inp.reference_md_paths:
        reference_text = _read_reference_md_text(inp.reference_md_paths)

    mistakes_text = ""
    if inp.include_common_mistakes and inp.root_dir is not None:
        md = common_mistakes_md_path(inp.root_dir)
        if md.exists():
            mistakes_text = _read_text_limited(md, max_chars=12000)

    system = render_import_prompt("explanation_system")
    answer_text = (inp.answer_text or "").strip()
    user = _build_user_prompt(
        question_text=inp.question_text,
        answer_text=answer_text,
        reference_md_paths=inp.reference_md_paths,
        reference_text=reference_text,
        mistakes_text=mistakes_text,
    )
    raw = client.chat_text(system=system, user=user)
    parsed_answer, analysis_body = _extract_answer_and_analysis(raw)
    final_answer = answer_text or _normalize_generated_answer_text(parsed_answer)
    final_analysis = postprocess_explanation(analysis_body or raw)
    return ExplanationResult(answer_text=final_answer, analysis_text=final_analysis)


def _build_user_prompt(
    *,
    question_text: str,
    answer_text: str,
    reference_md_paths: list[Path] | None,
    reference_text: str,
    mistakes_text: str,
) -> str:
    reference_block = ""
    if reference_text.strip():
        if reference_md_paths:
            names = "、".join([p.name for p in reference_md_paths])
            title = f"参考资料（{len(reference_md_paths)} 份：{names}）："
        else:
            title = "参考资料："
        reference_block = f"\n\n{title}\n{reference_text.strip()}"

    mistakes_block = ""
    if mistakes_text.strip():
        mistakes_block = (
            "\n\n常见错题归因与答题策略参考（md 原文）：\n"
            f"{mistakes_text.strip()}"
        )

    prompt = render_import_prompt(
        "explanation_user",
        question_text=question_text.strip(),
        answer_text=answer_text.strip(),
        reference_block=reference_block,
        mistakes_block=mistakes_block,
    ).strip()
    if answer_text.strip():
        return prompt
    return (
        prompt
        + "\n\n补充要求：当前“答案文本”为空。请你先判断最可能的正确答案，"
        + "并在第一行单独输出“答案：答案标识”；从第二行开始再输出逐项解析。"
    ).strip()


def _read_reference_md_text(paths: list[Path]) -> str:
    max_chars = 100000
    blocks: list[str] = []
    used = 0
    for p in paths:
        try:
            if not p.exists():
                continue
            text = p.read_text(encoding="utf-8", errors="ignore").strip()
        except Exception:
            continue
        if not text:
            continue
        head = f"[文件：{p.name}]"
        block = head + "\n" + text
        if used + len(block) + 2 > max_chars:
            remain = max_chars - used
            if remain <= len(head) + 1:
                break
            block = head + "\n" + block[len(head) + 1 : len(head) + 1 + remain - len(head) - 1].rstrip() + "\n…"
            blocks.append(block)
            break
        blocks.append(block)
        used += len(block) + 2
    return "\n\n".join(blocks).strip()


def postprocess_explanation(text: str) -> str:
    lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    lines = [ln for ln in lines if _NONEMPTY_LINE_RE.fullmatch(ln)]
    cleaned: list[str] = []
    for ln in lines:
        s = ln.lstrip()
        if s.startswith("- "):
            s = s[2:]
        elif s.startswith("-"):
            s = s[1:].lstrip()
        cleaned.append(s)
    return "\n".join(cleaned).strip()


def _extract_answer_and_analysis(text: str) -> tuple[str, str]:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    first_nonempty_index = -1
    for idx, line in enumerate(lines):
        if line.strip():
            first_nonempty_index = idx
            break
    if first_nonempty_index < 0:
        return "", ""
    first_line = lines[first_nonempty_index].strip()
    first_line = re.sub(r"^[\-\*\d\.\)\s]+", "", first_line)
    first_line = first_line.replace("**", "").strip()
    match = re.match(r"^(?:答案|参考答案|正确答案)\s*[：:]?\s*(.+?)\s*$", first_line)
    if not match:
        return "", text
    answer_text = _normalize_generated_answer_text(match.group(1))
    remaining = lines[:first_nonempty_index] + lines[first_nonempty_index + 1 :]
    return answer_text, "\n".join(remaining).strip()


def _as_str(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_generated_answer_text(text: str) -> str:
    raw = _as_str(text).upper()
    if not raw:
        return ""
    for old, new in (("，", ","), ("；", ","), (";", ","), ("、", ","), ("/", ","), (" ", "")):
        raw = raw.replace(old, new)
    if "," in raw:
        raw = "".join(part.strip() for part in raw.split(",") if part.strip())
    return raw

def _read_common_mistakes_md(path: Path) -> list[tuple[str, str]]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    lines = [ln.strip() for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    rows = [ln for ln in lines if ln.startswith("|") and ln.count("|") >= 4]
    out: list[tuple[str, str]] = []
    for ln in rows:
        if ":---" in ln or ":--" in ln:
            continue
        parts = [p.strip() for p in ln.strip("|").split("|")]
        if len(parts) < 2:
            continue
        a_raw = parts[0]
        b_raw = parts[1] if len(parts) > 1 else ""
        a = _strip_md_inline(a_raw)
        b = _strip_md_inline(b_raw)
        a = a.replace("\n", " ").strip()
        b = b.replace("\n", " ").strip()
        if not a:
            continue
        if a in ("错题表现 (常见错误现象)", "错题表现", "表现"):
            continue
        title, detail = _extract_type_and_detail(a)
        if title and detail:
            out.append((title, detail))
        elif title:
            out.append((title, b))
        else:
            out.append((a, b))
    return out


def _strip_md_inline(text: str) -> str:
    s = (text or "").strip()
    s = re.sub(r"<br\\s*/?>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"\\*\\*(.*?)\\*\\*", r"\\1", s)
    s = re.sub(r"\\*(.*?)\\*", r"\\1", s)
    s = re.sub(r"`([^`]*)`", r"\\1", s)
    return s.strip()


def _extract_type_and_detail(text: str) -> tuple[str, str]:
    s = (text or "").strip()
    if not s:
        return "", ""
    m = re.search(r"(?:^|\\s)([\\u4e00-\\u9fffA-Za-z0-9]+型)(?:\\s|$)", s)
    title = ""
    if m:
        title = m.group(1).strip()
    if "\n" in s:
        first, rest = s.split("\n", 1)
    else:
        first, rest = s, ""
    if not title:
        title = first.strip()
    detail = (rest or "").strip()
    detail = re.sub(r"\\s+", " ", detail)
    if len(detail) > 220:
        detail = detail[:220].rstrip() + "…"
    return title, detail


def _read_text_limited(path: Path, *, max_chars: int) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore").strip()
    except Exception:
        return ""
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n…"
