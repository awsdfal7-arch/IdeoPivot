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
    choice_1: str
    choice_2: str
    choice_3: str
    choice_4: str
    answer: str
    analysis: str
    question_type: str
    textbook_version: str
    source: str
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
        _create_table(conn)
        rows = conn.execute(
            f"""
            SELECT
                id,
                stem,
                option_1,
                option_2,
                option_3,
                option_4,
                choice_1,
                choice_2,
                choice_3,
                choice_4,
                answer,
                analysis,
                question_type,
                textbook_version,
                source,
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
        _create_table(conn)
        rows = conn.execute(
            f"""
            SELECT
                id,
                stem,
                option_1,
                option_2,
                option_3,
                option_4,
                choice_1,
                choice_2,
                choice_3,
                choice_4,
                answer,
                analysis,
                question_type,
                textbook_version,
                source,
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
        _create_table(conn)
        conn.execute(
            f"""
            UPDATE {TABLE_NAME}
            SET
                stem = ?,
                option_1 = ?,
                option_2 = ?,
                option_3 = ?,
                option_4 = ?,
                choice_1 = ?,
                choice_2 = ?,
                choice_3 = ?,
                choice_4 = ?,
                answer = ?,
                analysis = ?,
                question_type = ?,
                textbook_version = ?,
                source = ?,
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
                question.choice_1,
                question.choice_2,
                question.choice_3,
                question.choice_4,
                question.answer,
                question.analysis,
                question.question_type,
                question.textbook_version,
                question.source,
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


def delete_question_by_id(path: Path, question_id: str) -> int:
    if not path.exists():
        return 0
    normalized_question_id = str(question_id or "").strip()
    if not normalized_question_id:
        return 0
    with sqlite3.connect(path) as conn:
        _create_table(conn)
        cur = conn.execute(
            f"DELETE FROM {TABLE_NAME} WHERE id = ?",
            (normalized_question_id,),
        )
        conn.commit()
        return int(cur.rowcount or 0)


def delete_questions_by_level_path(path: Path, level_path: str) -> int:
    if not path.exists():
        return 0
    normalized_level_path = str(level_path or "").strip()
    if not normalized_level_path:
        return 0
    with sqlite3.connect(path) as conn:
        _create_table(conn)
        cur = conn.execute(
            f"DELETE FROM {TABLE_NAME} WHERE level_path = ?",
            (normalized_level_path,),
        )
        conn.commit()
        return int(cur.rowcount or 0)


def count_questions_by_level_prefix(path: Path, level_prefix: str) -> int:
    if not path.exists():
        return 0
    normalized_level_prefix = str(level_prefix or "").strip()
    if not normalized_level_prefix:
        return 0
    like_pattern = normalized_level_prefix + ".%"
    with sqlite3.connect(path) as conn:
        _create_table(conn)
        row = conn.execute(
            f"""
            SELECT COUNT(*)
            FROM {TABLE_NAME}
            WHERE level_path = ? OR level_path LIKE ?
            """,
            (normalized_level_prefix, like_pattern),
        ).fetchone()
    return int(row[0] or 0) if row else 0


def delete_questions_by_level_prefix(path: Path, level_prefix: str) -> int:
    if not path.exists():
        return 0
    normalized_level_prefix = str(level_prefix or "").strip()
    if not normalized_level_prefix:
        return 0
    like_pattern = normalized_level_prefix + ".%"
    with sqlite3.connect(path) as conn:
        _create_table(conn)
        cur = conn.execute(
            f"""
            DELETE FROM {TABLE_NAME}
            WHERE level_path = ? OR level_path LIKE ?
            """,
            (normalized_level_prefix, like_pattern),
        )
        conn.commit()
        return int(cur.rowcount or 0)


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
        _insert_questions(conn, questions)
        conn.commit()


def append_questions(path: Path, questions: Iterable[DbQuestionRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        _create_table(conn)
        _insert_questions(conn, questions)
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
            choice_1 TEXT NOT NULL DEFAULT '',
            choice_2 TEXT NOT NULL DEFAULT '',
            choice_3 TEXT NOT NULL DEFAULT '',
            choice_4 TEXT NOT NULL DEFAULT '',
            answer TEXT NOT NULL DEFAULT '',
            analysis TEXT NOT NULL DEFAULT '',
            question_type TEXT NOT NULL DEFAULT '',
            textbook_version TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT '',
            level_path TEXT NOT NULL DEFAULT '',
            difficulty_score INTEGER,
            knowledge_points TEXT NOT NULL DEFAULT '',
            abilities TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    existing_columns = {
        str(row[1]).strip()
        for row in conn.execute(f"PRAGMA table_info({TABLE_NAME})").fetchall()
        if len(row) > 1 and str(row[1]).strip()
    }
    for column_name in ("choice_1", "choice_2", "choice_3", "choice_4"):
        if column_name in existing_columns:
            continue
        conn.execute(
            f"ALTER TABLE {TABLE_NAME} ADD COLUMN {column_name} TEXT NOT NULL DEFAULT ''"
        )
    if "source" not in existing_columns:
        conn.execute(
            f"ALTER TABLE {TABLE_NAME} ADD COLUMN source TEXT NOT NULL DEFAULT ''"
        )
        existing_columns.add("source")
    if "source_filename" in existing_columns:
        conn.execute(
            f"""
            UPDATE {TABLE_NAME}
            SET source = source_filename
            WHERE TRIM(COALESCE(source, '')) = '' AND TRIM(COALESCE(source_filename, '')) <> ''
            """
        )


def _insert_questions(conn: sqlite3.Connection, questions: Iterable[DbQuestionRecord]) -> None:
    rows = [
        (
            q.id,
            q.stem,
            q.option_1,
            q.option_2,
            q.option_3,
            q.option_4,
            q.choice_1,
            q.choice_2,
            q.choice_3,
            q.choice_4,
            q.answer,
            q.analysis,
            q.question_type,
            q.textbook_version,
            q.source,
            q.level_path,
            q.difficulty_score,
            q.knowledge_points,
            q.abilities,
            q.created_at,
            q.updated_at,
        )
        for q in questions
    ]
    if not rows:
        return
    conn.executemany(
        f"""
        INSERT INTO {TABLE_NAME} (
            id,
            stem,
            option_1,
            option_2,
            option_3,
            option_4,
            choice_1,
            choice_2,
            choice_3,
            choice_4,
            answer,
            analysis,
            question_type,
            textbook_version,
            source,
            level_path,
            difficulty_score,
            knowledge_points,
            abilities,
            created_at,
            updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def _row_to_record(row: tuple[object, ...]) -> DbQuestionRecord:
    return DbQuestionRecord(
        id=str(row[0] or ""),
        stem=str(row[1] or ""),
        option_1=str(row[2] or ""),
        option_2=str(row[3] or ""),
        option_3=str(row[4] or ""),
        option_4=str(row[5] or ""),
        choice_1=str(row[6] or ""),
        choice_2=str(row[7] or ""),
        choice_3=str(row[8] or ""),
        choice_4=str(row[9] or ""),
        answer=str(row[10] or ""),
        analysis=str(row[11] or ""),
        question_type=str(row[12] or ""),
        textbook_version=str(row[13] or ""),
        source=str(row[14] or ""),
        level_path=str(row[15] or ""),
        difficulty_score=int(row[16]) if row[16] is not None else None,
        knowledge_points=str(row[17] or ""),
        abilities=str(row[18] or ""),
        created_at=str(row[19] or ""),
        updated_at=str(row[20] or ""),
    )
