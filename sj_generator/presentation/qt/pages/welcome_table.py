from __future__ import annotations

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QTableWidget, QTableWidgetItem

from sj_generator.domain.entities import Question
from sj_generator.infrastructure.persistence.sqlite_repo import DbQuestionRecord
from sj_generator.presentation.qt.pages.welcome_export import format_db_answer, format_db_options


def populate_questions_table(
    table: QTableWidget,
    questions: list[Question],
    column_defs: list[tuple[str, str, bool]],
) -> None:
    table.setRowCount(len(questions))
    for row, question in enumerate(questions):
        values = build_question_row_values(row + 1, question)
        populate_row_by_values(table, row, values, column_defs)


def populate_db_records_table(
    table: QTableWidget,
    records: list[DbQuestionRecord],
    column_defs: list[tuple[str, str, bool]],
) -> None:
    table.setRowCount(len(records))
    for row, record in enumerate(records):
        values = build_db_row_values(row + 1, record)
        populate_row_by_values(table, row, values, column_defs)


def build_question_row_values(sequence: int, question: Question) -> dict[str, str]:
    return {
        "stem": format_stem_with_sequence(sequence, question.stem),
        "options": question.options,
        "answer": question.answer,
        "analysis": format_table_analysis(question.analysis),
        "id": "",
        "question_type": question.question_type,
        "choice_1": question.choice_1,
        "choice_2": question.choice_2,
        "choice_3": question.choice_3,
        "choice_4": question.choice_4,
        "textbook_version": "",
        "source": "",
        "level_path": "",
        "difficulty_score": "",
        "knowledge_points": "",
        "abilities": "",
        "created_at": "",
        "updated_at": "",
    }


def build_db_row_values(sequence: int, record: DbQuestionRecord) -> dict[str, str]:
    return {
        "stem": format_stem_with_sequence(sequence, record.stem),
        "options": format_db_options(record),
        "answer": format_db_answer(record),
        "analysis": format_table_analysis(record.analysis),
        "id": record.id,
        "question_type": record.question_type,
        "choice_1": record.choice_1,
        "choice_2": record.choice_2,
        "choice_3": record.choice_3,
        "choice_4": record.choice_4,
        "textbook_version": record.textbook_version,
        "source": record.source,
        "level_path": record.level_path,
        "difficulty_score": "" if record.difficulty_score is None else str(record.difficulty_score),
        "knowledge_points": record.knowledge_points,
        "abilities": record.abilities,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def populate_row_by_values(
    table: QTableWidget,
    row: int,
    values: dict[str, str],
    column_defs: list[tuple[str, str, bool]],
) -> None:
    highlight_missing = any(
        not str(values.get(key, "") or "").strip() for key in ("stem", "options", "answer", "analysis")
    )
    for col, (key, _title, _visible) in enumerate(column_defs):
        alignment = int(QtAlign.center if key == "answer" else QtAlign.left)
        set_table_item(
            table,
            row,
            col,
            values.get(key, ""),
            alignment=alignment,
            background=QColor("#ffd9d9") if highlight_missing else None,
        )


class QtAlign:
    left = 1 | 128
    center = 4 | 128


def format_stem_with_sequence(sequence: int, stem: str) -> str:
    return f"{sequence}. {stem or ''}".strip()


def format_table_analysis(analysis: str) -> str:
    return (analysis or "").replace("**", "")


def set_table_item(
    table: QTableWidget,
    row: int,
    col: int,
    text: str,
    *,
    alignment: int,
    background: QColor | None = None,
) -> None:
    item = QTableWidgetItem(text or "")
    item.setTextAlignment(alignment)
    if background is not None:
        item.setBackground(background)
    table.setItem(row, col, item)
