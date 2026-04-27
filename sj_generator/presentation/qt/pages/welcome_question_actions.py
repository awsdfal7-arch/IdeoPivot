from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from PyQt6.QtWidgets import QMessageBox, QTreeWidgetItem, QWidget

from sj_generator.infrastructure.persistence.sqlite_repo import (
    DbQuestionRecord,
    append_questions,
    delete_question_by_id,
    update_question,
)
from sj_generator.presentation.qt.message_box import show_message_box
from sj_generator.presentation.qt.question_edit_dialog import QuestionEditDialog


def selected_tree_level_path_for_create(
    current: QTreeWidgetItem | None,
    *,
    role_level_path: int,
    role_level_prefix: int,
) -> str:
    if current is None:
        return ""
    exact_level_path = str(current.data(0, role_level_path) or "").strip()
    if exact_level_path:
        return exact_level_path
    return str(current.data(0, role_level_prefix) or "").strip()


def build_new_question_record(*, preferred_textbook_version: str, default_level_path: str) -> DbQuestionRecord:
    now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return DbQuestionRecord(
        id=str(uuid4()),
        stem="",
        option_1="",
        option_2="",
        option_3="",
        option_4="",
        choice_1="",
        choice_2="",
        choice_3="",
        choice_4="",
        answer="",
        analysis="",
        question_type="单选",
        textbook_version=preferred_textbook_version,
        source="录入",
        level_path=default_level_path,
        difficulty_score=None,
        knowledge_points="",
        abilities="",
        created_at=now_text,
        updated_at=now_text,
    )


def add_question_manually(
    *,
    parent: QWidget,
    db_path,
    preferred_textbook_version: str,
    default_level_path: str,
) -> DbQuestionRecord | None:
    new_record = build_new_question_record(
        preferred_textbook_version=preferred_textbook_version,
        default_level_path=str(default_level_path or "").strip(),
    )
    dlg = QuestionEditDialog(new_record, parent, create_mode=True)
    if dlg.exec() != QuestionEditDialog.DialogCode.Accepted:
        return None
    created = dlg.updated_record()
    if not created.stem.strip():
        show_message_box(parent, title="无法新增", text="题目内容不能为空。", icon=QMessageBox.Icon.Warning)
        return None
    try:
        append_questions(db_path, [created])
    except Exception as exc:
        show_message_box(parent, title="新增失败", text=f"写入题目失败：{exc}", icon=QMessageBox.Icon.Critical)
        return None
    show_message_box(parent, title="新增完成", text="题目已新增。", icon=QMessageBox.Icon.Information)
    return created


@dataclass
class QuestionEditResult:
    action: str
    preferred_level_path: str = ""
    updated_record: DbQuestionRecord | None = None


def edit_question_record(
    *,
    parent: QWidget,
    db_path,
    record: DbQuestionRecord,
) -> QuestionEditResult:
    dlg = QuestionEditDialog(record, parent)
    result = dlg.exec()
    if result == QuestionEditDialog.DELETE_RESULT:
        deleted_count = delete_question_by_id(db_path, record.id)
        if deleted_count <= 0:
            show_message_box(parent, title="删除失败", text="未找到要删除的题目，可能已被移除。", icon=QMessageBox.Icon.Warning)
            return QuestionEditResult(action="missing")
        show_message_box(parent, title="删除完成", text="题目已删除。", icon=QMessageBox.Icon.Information)
        return QuestionEditResult(action="deleted", preferred_level_path=record.level_path)
    if result != QuestionEditDialog.DialogCode.Accepted:
        return QuestionEditResult(action="cancelled")
    updated = dlg.updated_record()
    try:
        update_question(db_path, updated)
    except Exception as exc:
        show_message_box(parent, title="保存失败", text=f"更新题目失败：{exc}", icon=QMessageBox.Icon.Critical)
        return QuestionEditResult(action="failed")
    return QuestionEditResult(action="updated", preferred_level_path=updated.level_path, updated_record=updated)
