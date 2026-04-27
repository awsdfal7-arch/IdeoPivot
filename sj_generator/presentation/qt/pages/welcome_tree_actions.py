from __future__ import annotations

from pathlib import Path
from typing import Callable

from PyQt6.QtWidgets import QMenu, QMessageBox, QTreeWidget, QTreeWidgetItem, QWidget

from sj_generator.application.settings import save_welcome_tree_expanded_prefixes
from sj_generator.infrastructure.persistence.sqlite_repo import (
    DbQuestionRecord,
    count_questions_by_level_prefix,
    delete_questions_by_level_prefix,
    list_level_paths,
)
from sj_generator.presentation.qt.message_box import show_message_box
from sj_generator.presentation.qt.pages.welcome_tree import (
    build_level_tree,
    collect_expanded_level_prefixes,
    delete_action_text,
    delete_scope_text,
    expand_item_ancestors,
    load_questions_for_tree_level,
    tree_level_key_for_path,
)


def refresh_level_tree(
    *,
    tree_widget: QTreeWidget,
    db_path: Path,
    expanded_level_prefixes: set[str],
    preferred_level_path: str | None,
    role_level_prefix: int,
    role_level_depth: int,
    role_level_path: int,
    on_no_selection: Callable[[], None],
) -> tuple[set[str], bool]:
    current_item = tree_widget.currentItem()
    current_prefix = ""
    if current_item is not None:
        current_prefix = str(current_item.data(0, role_level_prefix) or "").strip()
    next_expanded = set(expanded_level_prefixes)
    if tree_widget.topLevelItemCount() > 0:
        next_expanded = collect_expanded_level_prefixes(tree_widget, role_level_prefix)
    tree_widget.clear()
    if not db_path.exists():
        return next_expanded, False

    preferred_item, selected_prefix_item = build_level_tree(
        tree_widget=tree_widget,
        level_paths=list_level_paths(db_path),
        expanded_prefixes=next_expanded,
        current_prefix=current_prefix,
        preferred_level_key=tree_level_key_for_path(preferred_level_path),
        role_level_prefix=role_level_prefix,
        role_level_depth=role_level_depth,
        role_level_path=role_level_path,
    )
    selected_item = preferred_item or selected_prefix_item
    if selected_item is not None:
        tree_widget.setCurrentItem(selected_item)
        if preferred_item is not None:
            expand_item_ancestors(selected_item)
    else:
        tree_widget.setCurrentItem(None)
        tree_widget.clearSelection()
        on_no_selection()
    return next_expanded, True


def handle_level_selection_changed(
    *,
    current: QTreeWidgetItem | None,
    db_path: Path,
    role_level_path: int,
    on_empty_selection: Callable[[], None],
    on_records_loaded: Callable[[list[DbQuestionRecord]], None],
) -> list[DbQuestionRecord]:
    if current is None:
        on_empty_selection()
        return []
    level_key = str(current.data(0, role_level_path) or "").strip()
    if not level_key:
        on_empty_selection()
        return []
    records = load_questions_for_tree_level(db_path, level_key)
    on_records_loaded(records)
    return records


def show_folder_tree_context_menu(
    *,
    parent: QWidget,
    tree_widget: QTreeWidget,
    pos,
    role_level_prefix: int,
    role_level_depth: int,
    role_level_path: int,
    on_add_question: Callable[[str], None],
    on_delete_level_subtree: Callable[[str, int, str], None],
) -> None:
    item = tree_widget.itemAt(pos)
    if item is None:
        return
    level_prefix = str(item.data(0, role_level_prefix) or "").strip()
    if not level_prefix:
        return
    depth = int(item.data(0, role_level_depth) or 0)
    tree_widget.setCurrentItem(item)
    menu = QMenu(parent)
    add_action = menu.addAction("新增题目")
    delete_action = menu.addAction(delete_action_text(depth))
    chosen = menu.exec(tree_widget.viewport().mapToGlobal(pos))
    if chosen == add_action:
        on_add_question(str(item.data(0, role_level_path) or item.data(0, role_level_prefix) or "").strip())
        return
    if chosen == delete_action:
        on_delete_level_subtree(level_prefix, depth, item.text(0).strip() or level_prefix)


def sync_expanded_level_prefixes_from_tree(
    tree_widget: QTreeWidget,
    *,
    role_level_prefix: int,
) -> set[str]:
    expanded_level_prefixes = collect_expanded_level_prefixes(tree_widget, role_level_prefix)
    save_welcome_tree_expanded_prefixes(sorted(expanded_level_prefixes))
    return expanded_level_prefixes


def delete_level_subtree(
    *,
    parent: QWidget,
    db_path: Path,
    level_prefix: str,
    depth: int,
    display_label: str,
    on_deleted: Callable[[], None],
    on_no_data: Callable[[], None],
) -> int:
    level_prefix = (level_prefix or "").strip()
    if not level_prefix:
        return 0
    total = count_questions_by_level_prefix(db_path, level_prefix)
    if total <= 0:
        show_message_box(parent, title="无需删除", text="当前节点下没有可删除的题目。", icon=QMessageBox.Icon.Information)
        on_no_data()
        return 0
    scope_text = delete_scope_text(depth)
    answer = show_message_box(
        parent,
        title="确认删除",
        text=f"确定删除{scope_text}{display_label}（层级 {level_prefix}）下的 {total} 道题吗？此操作不可撤销。",
        icon=QMessageBox.Icon.Warning,
        buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        default_button=QMessageBox.StandardButton.No,
    )
    if answer != QMessageBox.StandardButton.Yes:
        return 0
    deleted_count = delete_questions_by_level_prefix(db_path, level_prefix)
    on_deleted()
    show_message_box(
        parent,
        title="删除完成",
        text=f"已删除{scope_text}{display_label}下的 {deleted_count} 道题。",
        icon=QMessageBox.Icon.Information,
    )
    return deleted_count
