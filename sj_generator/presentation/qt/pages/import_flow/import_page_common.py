from __future__ import annotations

from pathlib import Path
import re

from PyQt6.QtCore import QRegularExpression
from PyQt6.QtGui import QDropEvent, QRegularExpressionValidator
from PyQt6.QtWidgets import QLineEdit, QProgressBar, QPushButton, QStyle, QStyledItemDelegate, QStyleOptionViewItem

from sj_generator.application.state import ImportWizardSession

BUTTON_MIN_WIDTH = 96
BUTTON_MIN_HEIGHT = 36

LEVEL_PATH_RE = re.compile(r"^\d+\.\d+\.\d+$")
LEVEL_PATH_EDIT_RE = QRegularExpression(r"\d*(?:\.\d*(?:\.\d*)?)?")


def style_dialog_button(button: QPushButton | None, text: str | None = None) -> None:
    if button is None:
        return
    if text:
        button.setText(text)
    button.setMinimumSize(BUTTON_MIN_WIDTH, BUTTON_MIN_HEIGHT)


def style_busy_progress(progress: QProgressBar) -> None:
    progress.setTextVisible(False)
    progress.setStyleSheet(
        """
        QProgressBar {
            min-height: 14px;
            max-height: 14px;
            border: 1px solid #cfd6e4;
            border-radius: 7px;
            background: #eef2f8;
        }
        QProgressBar::chunk {
            width: 36px;
            margin: 0px;
            border-radius: 7px;
            background-color: #5b8def;
        }
        """
    )


def sanitize_filename(name: str) -> str:
    text = (name or "").strip()
    text = re.sub(r'[<>:"/\\\\|?*]+', "_", text)
    text = text.replace("\n", " ").replace("\r", " ").replace("\t", " ")
    text = text.strip(" .")
    return text


def unique_child_dir(parent: Path, base_name: str) -> Path:
    candidate = parent / base_name
    if not candidate.exists():
        return candidate
    index = 2
    while True:
        numbered = parent / f"{base_name}_{index}"
        if not numbered.exists():
            return numbered
        index += 1


def rename_project(state: ImportWizardSession, *, new_name: str) -> bool:
    project_dir = state.project_dir
    repo_path = state.repo_path
    if project_dir is None or repo_path is None:
        return False
    safe = sanitize_filename(new_name)
    if not safe:
        return False

    parent = project_dir.parent
    target_dir = unique_child_dir(parent, safe)
    target_name = target_dir.name
    target_repo = target_dir / f"{target_name}.xlsx"

    state.project_dir = target_dir
    state.repo_path = target_repo
    state.project_name_is_placeholder = False
    return True


def extract_paths_from_drop_event(event: QDropEvent) -> list[Path]:
    md = event.mimeData()
    if not md.hasUrls():
        return []
    out: list[Path] = []
    for url in md.urls():
        if not url.isLocalFile():
            continue
        path = Path(url.toLocalFile())
        if path.exists():
            out.append(path)
    return out


def merge_paths_text(existing_text: str, paths: list[Path]) -> str:
    existing = [p.strip() for p in (existing_text or "").split(";") if p.strip()]
    seen: set[str] = set()
    merged: list[str] = []
    for value in existing:
        if value not in seen:
            merged.append(value)
            seen.add(value)
    for path in paths:
        value = str(path)
        if value not in seen:
            merged.append(value)
            seen.add(value)
    return "; ".join(merged)


def is_valid_level_path(value: str) -> bool:
    return bool(LEVEL_PATH_RE.fullmatch((value or "").strip()))


class LevelPathItemDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        opt.state &= ~QStyle.StateFlag.State_Selected
        super().paint(painter, opt, index)

    def createEditor(self, parent, option, index):
        editor = QLineEdit(parent)
        editor.setPlaceholderText("例如：3.2.2")
        editor.setValidator(QRegularExpressionValidator(LEVEL_PATH_EDIT_RE, editor))
        return editor


class PreserveCellBackgroundDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        opt.state &= ~QStyle.StateFlag.State_Selected
        super().paint(painter, opt, index)
