from __future__ import annotations

import hashlib
from pathlib import Path
import shutil

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QMessageBox, QWidget, QWizard

from sj_generator.application.state import ImportWizardSession, WizardState
from sj_generator.presentation.qt.message_box import show_message_box


def effective_import_source_dir(configured_dir: str) -> str:
    configured = Path(configured_dir).expanduser()
    if configured.exists() and configured.is_dir():
        return str(configured)
    return str(Path.home() / "Downloads")


def backup_import_source_files(db_path: Path, paths: list[Path]) -> list[Path]:
    if not paths:
        return []
    target_dir = db_path.parent / "doc"
    target_dir.mkdir(parents=True, exist_ok=True)
    known_hash_paths = build_doc_hash_index(target_dir)
    copied_paths: list[Path] = []
    seen_targets: set[Path] = set()
    for src in paths:
        if not src.exists() or not src.is_file():
            raise FileNotFoundError(src)
        file_hash = file_sha256(src)
        target_path = known_hash_paths.get(file_hash)
        if target_path is None:
            target_path = next_doc_backup_path(target_dir, src.name)
            shutil.copy2(src, target_path)
            known_hash_paths[file_hash] = target_path
        resolved_target = target_path.resolve()
        if resolved_target in seen_targets:
            continue
        seen_targets.add(resolved_target)
        copied_paths.append(target_path)
    return copied_paths


def build_doc_hash_index(target_dir: Path) -> dict[str, Path]:
    hash_index: dict[str, Path] = {}
    for path in sorted(target_dir.glob("*.docx"), key=lambda item: item.name.lower()):
        if not path.is_file():
            continue
        try:
            current_hash = file_sha256(path)
        except Exception:
            continue
        hash_index.setdefault(current_hash, path)
    return hash_index


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def next_doc_backup_path(target_dir: Path, file_name: str) -> Path:
    candidate = target_dir / file_name
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    index = 2
    while True:
        numbered = target_dir / f"{stem}_{index}{suffix}"
        if not numbered.exists():
            return numbered
        index += 1


def open_import_flow_windows(
    *,
    base_state: WizardState,
    db_path: Path,
    paths: list[Path],
    message_parent: QWidget,
    launcher,
    owner,
    import_flow_windows: list[QWizard],
    start_page_id: int,
    on_state_finished,
    on_window_forget,
) -> bool:
    selected_paths = [Path(path) for path in paths if str(path).strip()]
    if not selected_paths:
        return False
    base_state.import_source_dir_text = str(selected_paths[0].parent)
    try:
        copied_paths = backup_import_source_files(db_path, selected_paths)
    except Exception as exc:
        show_message_box(
            message_parent,
            title="备份失败",
            text=f"复制资料到 doc 目录失败：{exc}",
            icon=QMessageBox.Icon.Critical,
        )
        return False
    if not copied_paths:
        return False
    shared_state = base_state.build_import_session(source_files=copied_paths)
    return open_import_flow_states(
        launcher=launcher,
        owner=owner,
        import_flow_windows=import_flow_windows,
        states=[shared_state],
        start_page_id=start_page_id,
        on_state_finished=on_state_finished,
        on_window_forget=on_window_forget,
    )


def open_import_flow_states(
    *,
    launcher,
    owner,
    import_flow_windows: list[QWizard],
    states: list[ImportWizardSession],
    start_page_id: int,
    on_state_finished,
    on_window_forget,
) -> bool:
    window_states = [state for state in states if isinstance(state, ImportWizardSession)]
    if not window_states:
        return False

    from sj_generator.presentation.qt.import_flow import ImportFlowWizard

    opened_windows: list[QWizard] = []
    for window_state in window_states:
        dlg = ImportFlowWizard(window_state, owner, launcher=launcher, start_page_id=start_page_id)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dlg.finished.connect(lambda _result, state=window_state: on_state_finished(state))
        dlg.destroyed.connect(lambda _obj=None, wizard=dlg: on_window_forget(wizard))
        import_flow_windows.append(dlg)
        opened_windows.append(dlg)
    for index, dlg in enumerate(opened_windows):
        should_activate = index == (len(opened_windows) - 1)
        QTimer.singleShot(
            0,
            lambda wizard=dlg, activate=should_activate: show_import_flow_window(
                import_flow_windows,
                wizard,
                activate=activate,
            ),
        )
    return True


def show_import_flow_window(import_flow_windows: list[QWizard], wizard: QWizard, *, activate: bool) -> None:
    if wizard not in import_flow_windows:
        return
    wizard.show()
    if activate:
        wizard.raise_()
        wizard.activateWindow()
