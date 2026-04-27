from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem

from sj_generator.infrastructure.persistence.sqlite_repo import DbQuestionRecord, load_all_questions


def delete_action_text(depth: int) -> str:
    if depth == 0:
        return "删除整本书"
    if depth == 1:
        return "删除这一课"
    if depth == 2:
        return "删除这一框"
    return "删除当前层级"


def delete_scope_text(depth: int) -> str:
    if depth == 0:
        return "整本书 "
    if depth == 1:
        return "这一课 "
    if depth == 2:
        return "这一框 "
    return "当前层级 "


def parse_level_parts(level_path: str) -> list[str]:
    return [part.strip() for part in str(level_path).split(".") if part.strip()]


def display_level_parts(level_path: str) -> list[str]:
    raw_parts = parse_level_parts(level_path)
    display_parts: list[str] = []
    for idx, part in enumerate(raw_parts):
        if idx == 0 and part == "0":
            return ["0"]
        if idx > 0 and part == "0":
            return display_parts
        display_parts.append(part)
    return display_parts


def tree_level_key_for_path(level_path: str | None) -> str:
    return ".".join(display_level_parts(level_path or ""))


def load_questions_for_tree_level(db_path: Path, level_key: str) -> list[DbQuestionRecord]:
    normalized_level_key = str(level_key or "").strip()
    if not normalized_level_key:
        return []
    return [
        record
        for record in load_all_questions(db_path)
        if tree_level_key_for_path(record.level_path) == normalized_level_key
    ]


def format_level_label(depth: int, part: str) -> str:
    if not part.isdigit():
        return part
    if depth == 0:
        if part == "0":
            return "高中阶段"
        return f"必修{to_chinese_number(int(part))}"
    if depth == 1:
        return f"第{to_chinese_number(int(part))}课"
    if depth == 2:
        return f"第{to_chinese_number(int(part))}框"
    return part


def expand_item_ancestors(item: QTreeWidgetItem) -> None:
    current: QTreeWidgetItem | None = item
    while current is not None:
        current.setExpanded(True)
        current = current.parent()


def collect_expanded_level_prefixes(tree_widget: QTreeWidget, role_level_prefix: int) -> set[str]:
    expanded: set[str] = set()

    def visit(item: QTreeWidgetItem) -> None:
        prefix = str(item.data(0, role_level_prefix) or "").strip()
        if prefix and item.isExpanded():
            expanded.add(prefix)
        for index in range(item.childCount()):
            visit(item.child(index))

    for index in range(tree_widget.topLevelItemCount()):
        visit(tree_widget.topLevelItem(index))
    return expanded


def build_level_tree(
    *,
    tree_widget: QTreeWidget,
    level_paths: list[str],
    expanded_prefixes: set[str],
    current_prefix: str,
    preferred_level_key: str,
    role_level_prefix: int,
    role_level_depth: int,
    role_level_path: int,
) -> tuple[QTreeWidgetItem | None, QTreeWidgetItem | None]:
    item_map: dict[tuple[str, ...], QTreeWidgetItem] = {}
    preferred_item: QTreeWidgetItem | None = None
    selected_prefix_item: QTreeWidgetItem | None = None

    for level_path in level_paths:
        parts = display_level_parts(level_path)
        if not parts:
            continue
        parent_item: QTreeWidgetItem | None = None
        path_parts: list[str] = []
        for idx, part in enumerate(parts):
            path_parts.append(part)
            prefix_path = ".".join(path_parts)
            key = tuple(path_parts)
            item = item_map.get(key)
            if item is None:
                item = QTreeWidgetItem([format_level_label(idx, part)])
                item.setToolTip(0, prefix_path)
                item.setData(0, role_level_prefix, prefix_path)
                item.setData(0, role_level_depth, idx)
                item.setData(0, role_level_path, prefix_path)
                if parent_item is None:
                    tree_widget.addTopLevelItem(item)
                else:
                    parent_item.addChild(item)
                item_map[key] = item
            if prefix_path in expanded_prefixes:
                item.setExpanded(True)
            if current_prefix and prefix_path == current_prefix:
                selected_prefix_item = item
            if idx == len(parts) - 1 and preferred_level_key and prefix_path == preferred_level_key:
                preferred_item = item
            parent_item = item
    return preferred_item, selected_prefix_item


def to_chinese_number(value: int) -> str:
    digits = {
        0: "零",
        1: "一",
        2: "二",
        3: "三",
        4: "四",
        5: "五",
        6: "六",
        7: "七",
        8: "八",
        9: "九",
        10: "十",
    }
    if value <= 10:
        return digits[value]
    if value < 20:
        return "十" + digits[value - 10]
    tens, ones = divmod(value, 10)
    if ones == 0:
        return digits[tens] + "十"
    return digits[tens] + "十" + digits[ones]
