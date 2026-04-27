import os
from pathlib import Path

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QFileDialog,
    QHeaderView,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

from sj_generator.application.state import AiSourceFileItem, ImportWizardSession
from sj_generator.presentation.qt.constants import PAGE_AI_IMPORT
from .import_page_common import (
    LevelPathItemDelegate,
    PreserveCellBackgroundDelegate,
    extract_paths_from_drop_event,
    is_valid_level_path,
    merge_paths_text,
    rename_project,
)
from .import_select_session import (
    build_opened_doc_session,
    poll_opened_doc_sessions,
)
from sj_generator.presentation.qt.message_box import show_message_box
from .select_support import (
    build_split_import_states_for_paths,
    collect_table_items,
    find_invalid_level_paths,
    rebuild_selected_paths_table,
    refresh_after_external_doc_edit,
    reminder_doc_path,
    remove_file_row,
    serialize_selected_paths,
    update_import_reminder,
)
from sj_generator.presentation.qt.table_copy import CopyableTableWidget


class AiSelectFilesPage(QWizardPage):
    def __init__(self, state: ImportWizardSession) -> None:
        super().__init__()
        self._state = state
        self.setTitle("确认导入资料")
        self.setAcceptDrops(True)

        self._files_table = CopyableTableWidget()
        self._files_table.setColumnCount(6)
        self._files_table.setHorizontalHeaderLabels(["名称", "版本", "层级", "图片", "表格", "操作"])
        header = self._files_table.horizontalHeader()
        for column in range(5):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self._files_table.setColumnWidth(5, 220)
        self._files_table.verticalHeader().setVisible(False)
        self._files_table.setShowGrid(True)
        self._files_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._files_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._files_table.setStyleSheet(
            """
            QTableWidget {
                gridline-color: black;
                selection-background-color: rgba(0, 0, 0, 0);
                selection-color: black;
            }
            """
        )
        self._files_table.setEditTriggers(
            QTableWidget.EditTrigger.DoubleClicked | QTableWidget.EditTrigger.EditKeyPressed
        )
        self._files_table.setItemDelegate(PreserveCellBackgroundDelegate(self._files_table))
        self._files_table.setItemDelegateForColumn(2, LevelPathItemDelegate(self._files_table))
        self._files_table.itemChanged.connect(self._handle_file_table_item_changed)
        self._opened_doc_sessions: dict[str, dict[str, object]] = {}
        self._doc_refresh_timer = QTimer(self)
        self._doc_refresh_timer.setInterval(1000)
        self._doc_refresh_timer.timeout.connect(self._poll_opened_docs)

        layout = QVBoxLayout()
        layout.addWidget(self._files_table, 1)
        self.setLayout(layout)

    def initializePage(self) -> None:
        self._sync_wizard_buttons()
        if self._state.source.files_text:
            paths = self._state.source.files or [
                Path(part.strip()) for part in self._state.source.files_text.split(";") if part.strip()
            ]
            self._set_selected_paths(paths)
            self._update_import_reminder(paths)
        else:
            self._set_selected_paths([])
            self._update_import_reminder([])

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = extract_paths_from_drop_event(event)
        paths = [path for path in paths if path.suffix.lower() == ".docx"]
        if paths:
            merged = merge_paths_text(self._serialize_paths_text(), paths)
            merged_paths = [Path(part.strip()) for part in merged.split(";") if part.strip()]
            self._set_selected_paths(merged_paths, selected_path=paths[0])
            self._update_import_reminder(merged_paths)
            event.acceptProposedAction()
        else:
            event.ignore()

    def validatePage(self) -> bool:
        raw = self._serialize_paths_text()
        if not raw:
            show_message_box(self, title="未选择文件", text="请选择待处理的资料文件。", icon=QMessageBox.Icon.Warning)
            return False
        paths = [Path(part.strip()) for part in raw.split(";") if part.strip()]
        paths = [path for path in paths if path.exists()]
        if not paths:
            show_message_box(self, title="文件不存在", text="请选择存在的资料文件。", icon=QMessageBox.Icon.Warning)
            return False
        invalid_levels = self._find_invalid_level_paths()
        if invalid_levels:
            names = "、".join(invalid_levels)
            show_message_box(
                self,
                title="层级格式无效",
                text=f"以下文件的层级不是三级数字格式：{names}\n请输入如 3.2.2 的形式。",
                icon=QMessageBox.Icon.Warning,
            )
            return False
        items = self._collect_table_items()
        level_paths = [item.level_path.strip() for item in items if item.level_path.strip()]
        if not level_paths:
            show_message_box(self, title="未填写层级", text="请在“确认导入资料”页填写层级。", icon=QMessageBox.Icon.Warning)
            return False
        self._state.source.files = list(paths)
        self._state.source.files_text = raw
        self._state.source.file_items = items
        self._state.source.import_level_path = level_paths[0] if len(set(level_paths)) == 1 else ""
        if len(paths) > 1:
            split_states = self._build_split_import_states(paths=paths, items=items)
            wizard = self.wizard()
            open_split = getattr(wizard, "open_split_import_flow_windows", None)
            if not callable(open_split) or (not open_split(split_states, start_page_id=PAGE_AI_IMPORT)):
                show_message_box(
                    self,
                    title="打开窗口失败",
                    text="无法打开拆分后的导入窗口。",
                    icon=QMessageBox.Icon.Warning,
                )
                return False
            if isinstance(wizard, QWizard):
                QTimer.singleShot(0, wizard.close)
            return False
        if self._state.project_name_is_placeholder and self._state.project_dir is not None:
            rename_project(self._state, new_name=paths[0].stem)
        return True

    def nextId(self) -> int:
        return PAGE_AI_IMPORT

    def _sync_wizard_buttons(self) -> None:
        wizard = self.wizard()
        if not isinstance(wizard, QWizard):
            return
        back_button = wizard.button(QWizard.WizardButton.BackButton)
        if back_button is not None:
            back_button.setVisible(False)
        wizard.setButtonText(QWizard.WizardButton.NextButton, "开始导题")

    def _sync_custom_wizard_button(self) -> None:
        wizard = self.wizard()
        if not isinstance(wizard, QWizard):
            return
        add_button = wizard.button(QWizard.WizardButton.CustomButton1)
        if add_button is None:
            return
        add_button.setText("添加文档")
        add_button.setVisible(True)
        try:
            add_button.clicked.disconnect()
        except TypeError:
            pass
        add_button.clicked.connect(self._choose_and_add_docs)

    def _choose_and_add_docs(self) -> None:
        start_dir = (self._state.import_source_dir_text or "").strip()
        if not start_dir:
            start_dir = os.getcwd()
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "选择资料文档",
            start_dir,
            "Word 文档 (*.docx)",
        )
        if not files:
            return
        paths = [Path(value) for value in files if value]
        if not paths:
            return
        merged = merge_paths_text(self._serialize_paths_text(), paths)
        merged_paths = [Path(part.strip()) for part in merged.split(";") if part.strip()]
        self._state.import_source_dir_text = str(paths[0].parent)
        self._set_selected_paths(merged_paths, selected_path=paths[0])
        self._update_import_reminder(merged_paths)

    def _serialize_paths_text(self) -> str:
        return serialize_selected_paths(self._files_table)

    def _set_selected_paths(self, paths: list[Path], *, selected_path: Path | None = None) -> None:
        rebuild_selected_paths_table(
            table=self._files_table,
            state=self._state,
            paths=paths,
            selected_path=selected_path,
            on_open_row=self._open_saved_doc_for_row,
            on_remove_row=self._remove_file_row,
        )

    def _handle_file_table_item_changed(self, item: QTableWidgetItem) -> None:
        row = item.row()
        path_item = self._files_table.item(row, 0)
        if path_item is None:
            return
        raw_path = str(path_item.data(Qt.ItemDataRole.UserRole) or "").strip()
        if not raw_path:
            return
        version_item = self._files_table.item(row, 1)
        level_item = self._files_table.item(row, 2)
        version = (version_item.text() if version_item else "").strip() or self._state.preferred_textbook_version
        if version_item is not None and version_item.text().strip() != version:
            self._files_table.blockSignals(True)
            version_item.setText(version)
            self._files_table.blockSignals(False)
        level_path = (level_item.text() if level_item else "").strip()
        if item.column() == 2 and level_path and not self._is_valid_level_path(level_path):
            self._files_table.blockSignals(True)
            item.setText("")
            self._files_table.blockSignals(False)
            show_message_box(
                self,
                title="层级格式无效",
                text="层级只允许输入三级点连接的数字形式，例如 3.2.2。",
                icon=QMessageBox.Icon.Warning,
            )
            level_path = ""
        self._upsert_source_file_item(raw_path, version=version, level_path=level_path)

    def _collect_table_items(self) -> list[AiSourceFileItem]:
        return collect_table_items(self._files_table, self._state.preferred_textbook_version)

    def _upsert_source_file_item(self, raw_path: str, *, version: str, level_path: str) -> None:
        updated = False
        for item in self._state.source.file_items:
            if item.path == raw_path:
                item.version = version
                item.level_path = level_path
                updated = True
                break
        if not updated:
            self._state.source.file_items.append(
                AiSourceFileItem(path=raw_path, version=version, level_path=level_path)
            )

    def _find_invalid_level_paths(self) -> list[str]:
        return find_invalid_level_paths(self._files_table, self._is_valid_level_path)

    def _is_valid_level_path(self, value: str) -> bool:
        return is_valid_level_path(value)

    def _build_split_import_states(
        self,
        *,
        paths: list[Path],
        items: list[AiSourceFileItem],
    ) -> list[ImportWizardSession]:
        return build_split_import_states_for_paths(
            base_state=self._state,
            paths=paths,
            items=items,
            rename_project=rename_project,
        )

    def _update_import_reminder(self, paths: list[Path]) -> None:
        update_import_reminder(self._files_table, paths, image_col=3, table_col=4)

    def _open_saved_doc_for_row(self, row: int) -> None:
        path = self._reminder_doc_path(row)
        if path is None:
            return
        if not path.exists():
            show_message_box(self, title="文件不存在", text=f"未找到文档：{path}", icon=QMessageBox.Icon.Warning)
            return
        try:
            os.startfile(str(path))
        except Exception as exc:
            show_message_box(self, title="打开失败", text=f"无法打开 Word 文档：{exc}", icon=QMessageBox.Icon.Critical)
            return
        session = build_opened_doc_session(path)
        self._opened_doc_sessions[str(path.resolve())] = session
        if not self._doc_refresh_timer.isActive():
            self._doc_refresh_timer.start()

    def _remove_file_row(self, row: int) -> None:
        remaining_paths, removed_path = remove_file_row(self._files_table, row)
        if removed_path is None:
            return
        self._opened_doc_sessions.pop(str(removed_path.resolve()), None)
        next_selected = None
        if remaining_paths:
            next_selected = remaining_paths[min(row, len(remaining_paths) - 1)]
        self._set_selected_paths(remaining_paths, selected_path=next_selected)
        self._update_import_reminder(remaining_paths)

    def _reminder_doc_path(self, row: int) -> Path | None:
        return reminder_doc_path(self._files_table, row)

    def _poll_opened_docs(self) -> None:
        if not self._opened_doc_sessions:
            self._doc_refresh_timer.stop()
            return
        closed_paths = poll_opened_doc_sessions(self._opened_doc_sessions)
        if closed_paths:
            self._refresh_after_external_doc_edit(closed_paths)
        if not self._opened_doc_sessions:
            self._doc_refresh_timer.stop()

    def _refresh_after_external_doc_edit(self, changed_paths: list[Path]) -> None:
        refresh_after_external_doc_edit(
            table=self._files_table,
            items=self._collect_table_items(),
            changed_paths=changed_paths,
            image_col=3,
            table_col=4,
        )

__all__ = ["AiSelectFilesPage"]
