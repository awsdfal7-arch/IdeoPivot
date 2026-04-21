from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

TABLE_NAME = "questions"


@dataclass(frozen=True)
class DbQuestionRecord:
    id: str
    stem: str
    option_1: str
    option_2: str
    option_3: str
    option_4: str
    answer: str
    analysis: str
    question_type: str
    textbook_version: str
    source_filename: str
    level_path: str
    difficulty_score: int | None
    knowledge_points: str
    abilities: str
    created_at: str
    updated_at: str


def list_level_paths(path: Path) -> list[str]:
    if not path.exists():
        return []
    with sqlite3.connect(path) as conn:
        rows = conn.execute(
            f"""
            SELECT DISTINCT level_path
            FROM {TABLE_NAME}
            WHERE TRIM(COALESCE(level_path, '')) <> ''
            ORDER BY level_path
            """
        ).fetchall()
    return [str(row[0]).strip() for row in rows if row and str(row[0]).strip()]


def load_questions_by_level_path(path: Path, level_path: str) -> list[DbQuestionRecord]:
    if not path.exists():
        return []
    with sqlite3.connect(path) as conn:
        rows = conn.execute(
            f"""
            SELECT
                id,
                stem,
                option_1,
                option_2,
                option_3,
                option_4,
                answer,
                analysis,
                question_type,
                textbook_version,
                source_filename,
                level_path,
                difficulty_score,
                knowledge_points,
                abilities,
                created_at,
                updated_at
            FROM {TABLE_NAME}
            WHERE level_path = ?
            ORDER BY created_at ASC, id ASC
            """,
            (level_path,),
        ).fetchall()
    return [_row_to_record(row) for row in rows]


def load_all_questions(path: Path) -> list[DbQuestionRecord]:
    if not path.exists():
        return []
    with sqlite3.connect(path) as conn:
        rows = conn.execute(
            f"""
            SELECT
                id,
                stem,
                option_1,
                option_2,
                option_3,
                option_4,
                answer,
                analysis,
                question_type,
                textbook_version,
                source_filename,
                level_path,
                difficulty_score,
                knowledge_points,
                abilities,
                created_at,
                updated_at
            FROM {TABLE_NAME}
            ORDER BY created_at ASC, id ASC
            """
        ).fetchall()
    return [_row_to_record(row) for row in rows]


def update_question(path: Path, question: DbQuestionRecord) -> None:
    if not path.exists():
        raise FileNotFoundError(path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            f"""
            UPDATE {TABLE_NAME}
            SET
                stem = ?,
                option_1 = ?,
                option_2 = ?,
                option_3 = ?,
                option_4 = ?,
                answer = ?,
                analysis = ?,
                question_type = ?,
                textbook_version = ?,
                source_filename = ?,
                level_path = ?,
                difficulty_score = ?,
                knowledge_points = ?,
                abilities = ?,
                created_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                question.stem,
                question.option_1,
                question.option_2,
                question.option_3,
                question.option_4,
                question.answer,
                question.analysis,
                question.question_type,
                question.textbook_version,
                question.source_filename,
                question.level_path,
                question.difficulty_score,
                question.knowledge_points,
                question.abilities,
                question.created_at,
                question.updated_at,
                question.id,
            ),
        )
        conn.commit()


def initialize_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        _create_table(conn)
        conn.commit()


def replace_questions(path: Path, questions: Iterable[DbQuestionRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(f"DROP TABLE IF EXISTS {TABLE_NAME}")
        _create_table(conn)
        conn.executemany(
            f"""
            INSERT INTO {TABLE_NAME} (
                id,
                stem,
                option_1,
                option_2,
                option_3,
                option_4,
                answer,
                analysis,
                question_type,
                textbook_version,
                source_filename,
                level_path,
                difficulty_score,
                knowledge_points,
                abilities,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    q.id,
                    q.stem,
                    q.option_1,
                    q.option_2,
                    q.option_3,
                    q.option_4,
                    q.answer,
                    q.analysis,
                    q.question_type,
                    q.textbook_version,
                    q.source_filename,
                    q.level_path,
                    q.difficulty_score,
                    q.knowledge_points,
                    q.abilities,
                    q.created_at,
                    q.updated_at,
                )
                for q in questions
            ],
        )
        conn.commit()


def _create_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
            id TEXT PRIMARY KEY,
            stem TEXT NOT NULL,
            option_1 TEXT NOT NULL DEFAULT '',
            option_2 TEXT NOT NULL DEFAULT '',
            option_3 TEXT NOT NULL DEFAULT '',
            option_4 TEXT NOT NULL DEFAULT '',
            answer TEXT NOT NULL DEFAULT '',
            analysis TEXT NOT NULL DEFAULT '',
            question_type TEXT NOT NULL DEFAULT '',
            textbook_version TEXT NOT NULL DEFAULT '',
            source_filename TEXT NOT NULL DEFAULT '',
            level_path TEXT NOT NULL DEFAULT '',
            difficulty_score INTEGER,
            knowledge_points TEXT NOT NULL DEFAULT '',
            abilities TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )


def _row_to_record(row: tuple[object, ...]) -> DbQuestionRecord:
    return DbQuestionRecord(
        id=str(row[0] or ""),
        stem=str(row[1] or ""),
        option_1=str(row[2] or ""),
        option_2=str(row[3] or ""),
        option_3=str(row[4] or ""),
        option_4=str(row[5] or ""),
        answer=str(row[6] or ""),
        analysis=str(row[7] or ""),
        question_type=str(row[8] or ""),
        textbook_version=str(row[9] or ""),
        source_filename=str(row[10] or ""),
        level_path=str(row[11] or ""),
        difficulty_score=int(row[12]) if row[12] is not None else None,
        knowledge_points=str(row[13] or ""),
        abilities=str(row[14] or ""),
        created_at=str(row[15] or ""),
        updated_at=str(row[16] or ""),
    )
