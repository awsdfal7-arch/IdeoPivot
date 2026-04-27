from __future__ import annotations

from pathlib import Path
import time

from PyQt6.QtWidgets import QTableWidget


def safe_mtime_ns(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except Exception:
        return 0


def word_lock_path(path: Path) -> Path:
    return path.with_name(f"~${path.name}")


def build_opened_doc_session(path: Path) -> dict[str, object]:
    return {
        "path": path,
        "initial_mtime_ns": safe_mtime_ns(path),
        "lock_seen": word_lock_path(path).exists(),
        "opened_at": time.monotonic(),
    }


def poll_opened_doc_sessions(opened_doc_sessions: dict[str, dict[str, object]]) -> list[Path]:
    closed_paths: list[Path] = []
    for key, session in list(opened_doc_sessions.items()):
        path = session.get("path")
        if not isinstance(path, Path):
            opened_doc_sessions.pop(key, None)
            continue
        lock_exists = word_lock_path(path).exists()
        lock_seen = bool(session.get("lock_seen"))
        if lock_exists:
            session["lock_seen"] = True
            continue
        initial_mtime_ns = int(session.get("initial_mtime_ns") or 0)
        modified = safe_mtime_ns(path) != initial_mtime_ns
        elapsed = max(0.0, time.monotonic() - float(session.get("opened_at") or 0.0))
        if lock_seen or (modified and elapsed >= 1.0):
            closed_paths.append(path)
            opened_doc_sessions.pop(key, None)
    return closed_paths


def select_first_changed_row(table: QTableWidget, changed_paths: list[Path]) -> None:
    if not changed_paths:
        return
    changed_resolved = {path.resolve() for path in changed_paths if path.exists()}
    for row in range(table.rowCount()):
        item = table.item(row, 0)
        if item is None:
            continue
        raw_path = str(item.data(0x0100) or "").strip()
        if not raw_path:
            continue
        try:
            candidate = Path(raw_path).resolve()
        except Exception:
            continue
        if candidate in changed_resolved:
            table.selectRow(row)
            break
