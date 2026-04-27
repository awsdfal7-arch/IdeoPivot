from __future__ import annotations

from datetime import date
from pathlib import Path
import re

from sj_generator.domain.entities import Question
from sj_generator.infrastructure.exporting.export_md import export_questions_to_markdown
from sj_generator.infrastructure.exporting.export_pdf import export_questions_to_pdf
from sj_generator.infrastructure.persistence.excel_repo import save_db_question_records
from sj_generator.infrastructure.persistence.sqlite_repo import DbQuestionRecord


def sanitize_export_name(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\\\|?*]+', "_", (name or "").strip())
    cleaned = cleaned.strip(" .")
    return cleaned or "导出结果"


def display_export_level_name(level_path: str) -> str:
    normalized_level_path = str(level_path or "").strip()
    if normalized_level_path == "0":
        return "高中阶段"
    return normalized_level_path


def default_export_dir(last_export_dir: Path | None, db_path: Path) -> Path:
    return last_export_dir or db_path.parent


def db_record_to_question(record: DbQuestionRecord) -> Question:
    return Question(
        number=record.id,
        stem=record.stem,
        options=format_db_options(record),
        answer=format_db_answer(record),
        analysis=record.analysis,
        question_type=record.question_type,
        choice_1=record.choice_1,
        choice_2=record.choice_2,
        choice_3=record.choice_3,
        choice_4=record.choice_4,
    )


def format_db_options(record: DbQuestionRecord) -> str:
    options = [record.option_1, record.option_2, record.option_3, record.option_4]
    if record.question_type == "可转多选":
        lines = [
            f"{marker}. {text.strip()}".rstrip()
            for marker, text in zip(["①", "②", "③", "④"], options)
            if text.strip()
        ]
        choice_lines = [
            format_choice_mapping(letter, value)
            for letter, value in (
                ("A", record.choice_1),
                ("B", record.choice_2),
                ("C", record.choice_3),
                ("D", record.choice_4),
            )
            if value.strip()
        ]
        if choice_lines and lines:
            lines.append("")
        lines.extend(choice_lines)
        return "\n".join(lines)
    if record.question_type == "多选":
        markers = ["①", "②", "③", "④"]
    else:
        markers = ["A", "B", "C", "D"]
    lines = [
        f"{markers[idx - 1]}. {text.strip()}".rstrip()
        for idx, text in enumerate(options, start=1)
        if text.strip()
    ]
    return "\n".join(lines)


def format_db_answer(record: DbQuestionRecord) -> str:
    answer = (record.answer or "").strip()
    if record.question_type == "可转多选":
        if any(value.strip() for value in (record.choice_1, record.choice_2, record.choice_3, record.choice_4)):
            return answer
    if record.question_type not in ("多选", "可转多选"):
        return answer
    marker_map = {
        "1": "①",
        "2": "②",
        "3": "③",
        "4": "④",
        "5": "⑤",
        "6": "⑥",
        "7": "⑦",
        "8": "⑧",
        "9": "⑨",
        "10": "⑩",
    }
    tokens = [token.strip() for token in answer.replace("，", ",").split(",") if token.strip()]
    if not tokens:
        return answer
    return "".join(marker_map.get(token, token) for token in tokens)


def format_choice_mapping(letter: str, value: str) -> str:
    circled = "".join(digit_to_circled(ch) for ch in (value or "").strip() if ch.isdigit())
    if circled:
        return f"{letter}. {circled}"
    return f"{letter}. {(value or '').strip()}".rstrip()


def digit_to_circled(digit: str) -> str:
    return {
        "1": "①",
        "2": "②",
        "3": "③",
        "4": "④",
        "5": "⑤",
        "6": "⑥",
        "7": "⑦",
        "8": "⑧",
        "9": "⑨",
        "0": "⑩",
    }.get(digit, digit)


def export_current_level_to_markdown(
    *,
    records: list[DbQuestionRecord],
    level_path: str,
    target_path: Path,
    convertible_multi_mode: str,
    include_answers: bool,
    include_analysis: bool,
) -> None:
    questions = [db_record_to_question(record) for record in records]
    md_text = export_questions_to_markdown(
        excel_file_name=level_path,
        export_date=date.today(),
        questions=questions,
        convertible_multi_mode=convertible_multi_mode,
        include_answers=include_answers,
        include_analysis=include_analysis,
    )
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(md_text, encoding="utf-8")


def export_current_level_to_pdf(
    *,
    records: list[DbQuestionRecord],
    level_path: str,
    target_path: Path,
    convertible_multi_mode: str,
    include_answers: bool,
    include_analysis: bool,
) -> None:
    questions = [db_record_to_question(record) for record in records]
    export_questions_to_pdf(
        excel_file_name=level_path,
        export_date=date.today(),
        questions=questions,
        target_path=target_path,
        convertible_multi_mode=convertible_multi_mode,
        include_answers=include_answers,
        include_analysis=include_analysis,
    )


def export_db_records_to_xlsx(*, records: list[DbQuestionRecord], target_path: Path) -> None:
    save_db_question_records(target_path, records)
