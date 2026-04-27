from __future__ import annotations

from PyQt6.QtWidgets import QMessageBox, QWidget

from sj_generator.application.importing import commit_questions_to_db
from sj_generator.application.state import ImportWizardSession, library_db_path_from_repo_parent_dir_text
from sj_generator.presentation.qt.import_costs import freeze_import_cost_result
from sj_generator.presentation.qt.message_box import show_message_box


def commit_draft_questions_to_db(parent: QWidget | None, state: ImportWizardSession) -> bool:
    if state.execution.db_import_completed:
        return True
    freeze_import_cost_result(state)

    questions = list(state.draft.questions)
    if not questions:
        show_message_box(parent, title="无法导入数据库", text="当前草稿为空，无法写入数据库。", icon=QMessageBox.Icon.Warning)
        return False

    level_path = state.source.import_level_path.strip()
    if not level_path:
        show_message_box(parent, title="无法导入数据库", text="未填写层级归属，无法写入数据库。", icon=QMessageBox.Icon.Warning)
        return False

    try:
        count = commit_questions_to_db(
            db_path=library_db_path_from_repo_parent_dir_text(state.default_repo_parent_dir_text),
            questions=questions,
            level_path=level_path,
            source_files=state.source.files or [],
            textbook_version=state.preferred_textbook_version,
        )
    except Exception as e:
        state.execution.db_import_error = str(e)
        show_message_box(parent, title="导入数据库失败", text=str(e), icon=QMessageBox.Icon.Critical)
        return False

    state.execution.mark_db_import_completed(count)
    return True
