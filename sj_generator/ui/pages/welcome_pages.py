from __future__ import annotations

from dataclasses import replace
from datetime import date
from datetime import datetime
import hashlib
from pathlib import Path
import re
import shutil
from uuid import uuid4

from PyQt6.QtCore import QRegularExpression, Qt, QTimer
from PyQt6.QtGui import QColor, QKeyEvent, QRegularExpressionValidator, QWheelEvent
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMenuBar,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStackedLayout,
    QTextEdit,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWizard,
    QWizardPage,
    QWidget,
)

from sj_generator.config import (
    load_welcome_table_font_point_size,
    load_welcome_table_column_visibility,
    load_welcome_tree_expanded_prefixes,
    save_welcome_table_font_point_size,
    save_welcome_table_column_visibility,
    save_welcome_tree_expanded_prefixes,
)
from sj_generator.io.export_pdf import export_questions_to_pdf
from sj_generator.io.export_md import export_questions_to_markdown
from sj_generator.io.excel_repo import load_db_question_records, save_db_question_records
from sj_generator.io.sqlite_repo import (
    append_questions,
    DbQuestionRecord,
    count_questions_by_level_prefix,
    delete_question_by_id,
    delete_questions_by_level_prefix,
    list_level_paths,
    load_all_questions,
    load_questions_by_level_path,
    update_question,
)
from sj_generator.models import Question
from sj_generator.paths import app_paths
from sj_generator.ui.api_config_dialog import ApiConfigDialog
from sj_generator.ui.program_settings_dialog import (
    ProgramSettingsDialog,
    SECTION_EXPORT,
    SECTION_GENERAL,
    SECTION_IMPORT,
)
from sj_generator.ui.state import AiSourceFileItem, WizardState, library_db_path_from_repo_parent_dir_text
from sj_generator.ui.styles import rounded_panel_stylesheet

LAST_COLUMN_MIN_WIDTH = 140
TABLE_FONT_POINT_SIZE_MIN = 8
TABLE_FONT_POINT_SIZE_MAX = 28
TREE_ROLE_LEVEL_PATH = Qt.ItemDataRole.UserRole
TREE_ROLE_LEVEL_PREFIX = int(Qt.ItemDataRole.UserRole) + 1
TREE_ROLE_LEVEL_DEPTH = int(Qt.ItemDataRole.UserRole) + 2
MESSAGE_BOX_BUTTON_MIN_WIDTH = 96
MESSAGE_BOX_BUTTON_MIN_HEIGHT = 36
TABLE_COLUMNS = [
    ("stem", "题目", True),
    ("options", "选项", True),
    ("answer", "答案", True),
    ("analysis", "解析", True),
    ("id", "题目id", False),
    ("question_type", "类型", False),
    ("choice_1", "组合A", False),
    ("choice_2", "组合B", False),
    ("choice_3", "组合C", False),
    ("choice_4", "组合D", False),
    ("level_path", "所属层级", False),
    ("textbook_version", "教材版本", False),
    ("source", "来源", False),
    ("difficulty_score", "难度评级", False),
    ("knowledge_points", "考察知识点", False),
    ("abilities", "考察能力", False),
    ("created_at", "入库时间", False),
    ("updated_at", "最后修改时间", False),
]


def _style_message_box_buttons(box: QMessageBox) -> None:
    for button_type, text in (
        (QMessageBox.StandardButton.Ok, "确定"),
        (QMessageBox.StandardButton.Cancel, "取消"),
        (QMessageBox.StandardButton.Yes, "是"),
        (QMessageBox.StandardButton.No, "否"),
    ):
        button = box.button(button_type)
        if button is None:
            continue
        button.setText(text)
        button.setMinimumSize(MESSAGE_BOX_BUTTON_MIN_WIDTH, MESSAGE_BOX_BUTTON_MIN_HEIGHT)


def _show_message_box(
    parent: QWidget | None,
    *,
    title: str,
    text: str,
    icon: QMessageBox.Icon,
    buttons: QMessageBox.StandardButton = QMessageBox.StandardButton.Ok,
    default_button: QMessageBox.StandardButton = QMessageBox.StandardButton.NoButton,
) -> QMessageBox.StandardButton:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setIcon(icon)
    box.setStandardButtons(buttons)
    if default_button != QMessageBox.StandardButton.NoButton:
        box.setDefaultButton(default_button)
    _style_message_box_buttons(box)
    return QMessageBox.StandardButton(box.exec())


class _ZoomableTableWidget(QTableWidget):
    def __init__(self, *args, zoom_callback=None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._zoom_callback = zoom_callback

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if self._zoom_callback is not None:
                delta = event.angleDelta().y()
                if delta != 0:
                    self._zoom_callback(1 if delta > 0 else -1)
                    event.accept()
                    return
        super().wheelEvent(event)


class _LevelPathPartLineEdit(QLineEdit):
    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self._prev_edit: QLineEdit | None = None
        self._next_edit: QLineEdit | None = None

    def set_neighbors(self, prev_edit: QLineEdit | None, next_edit: QLineEdit | None) -> None:
        self._prev_edit = prev_edit
        self._next_edit = next_edit

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key == Qt.Key.Key_Left and self.cursorPosition() == 0 and self._prev_edit is not None:
            self._prev_edit.setFocus()
            self._prev_edit.setCursorPosition(len(self._prev_edit.text()))
            event.accept()
            return
        if key == Qt.Key.Key_Right and self.cursorPosition() == len(self.text()) and self._next_edit is not None:
            self._next_edit.setFocus()
            self._next_edit.setCursorPosition(0)
            event.accept()
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Tab):
            if self._next_edit is not None:
                self._next_edit.setFocus()
                self._next_edit.selectAll()
            else:
                self.focusNextPrevChild(True)
            event.accept()
            return
        if key == Qt.Key.Key_Backtab:
            if self._prev_edit is not None:
                self._prev_edit.setFocus()
                self._prev_edit.selectAll()
            else:
                self.focusNextPrevChild(False)
            event.accept()
            return
        super().keyPressEvent(event)


class WelcomePage(QWizardPage):
    def __init__(self, state: WizardState) -> None:
        super().__init__()
        self._state = state
        self._db_path = self._current_db_path()
        self._current_db_records: list[DbQuestionRecord] = []
        self._row_resize_pending = False
        self._row_resize_followup_pending = False
        self._column_defs = TABLE_COLUMNS
        self._column_visibility = self._load_column_visibility()
        self._table_font_point_size = self._load_table_font_point_size()
        loaded_expanded_prefixes = load_welcome_tree_expanded_prefixes()
        self._expanded_level_prefixes = set(loaded_expanded_prefixes or [])
        self._has_saved_tree_state = loaded_expanded_prefixes is not None
        self._syncing_tree_expand_state = False
        self.setTitle("开始")

        menu_bar = QMenuBar(self)
        file_menu = menu_bar.addMenu("文件")
        import_menu = file_menu.addMenu("导入")
        self._doc_import_action = import_menu.addAction("从文档文件解析导入")
        self._doc_import_action.triggered.connect(self._enter_main_flow)
        self._table_import_action = import_menu.addAction("从表格文件直接导入")
        self._table_import_action.triggered.connect(self._import_from_table_file)
        export_menu = file_menu.addMenu("导出")
        self._export_md_action = export_menu.addAction("导出当前页面为 Markdown")
        self._export_md_action.triggered.connect(self._export_current_level_to_markdown)
        self._export_pdf_action = export_menu.addAction("导出当前页面为 PDF")
        self._export_pdf_action.triggered.connect(self._export_current_level_to_pdf)
        export_xlsx_menu = export_menu.addMenu("导出为 xlsx")
        self._export_current_level_xlsx_action = export_xlsx_menu.addAction("当前页面题目")
        self._export_current_level_xlsx_action.triggered.connect(self._export_current_level_to_xlsx)
        self._export_db_table_xlsx_action = export_xlsx_menu.addAction("所有题目")
        self._export_db_table_xlsx_action.triggered.connect(self._export_db_table_to_xlsx)
        edit_menu = menu_bar.addMenu("编辑")
        self._add_question_action = edit_menu.addAction("新增题目")
        self._add_question_action.triggered.connect(self._add_question_manually)
        view_menu = menu_bar.addMenu("视图")
        column_menu = view_menu.addMenu("表格列显示")
        settings_menu = menu_bar.addMenu("设置")
        self._general_settings_action = settings_menu.addAction("常规设定")
        self._general_settings_action.triggered.connect(self._open_general_settings)
        self._import_settings_action = settings_menu.addAction("导入设定")
        self._import_settings_action.triggered.connect(self._open_import_settings)
        self._export_settings_action = settings_menu.addAction("导出设定")
        self._export_settings_action.triggered.connect(self._open_export_settings)
        self._api_settings_action = settings_menu.addAction("API 配置")
        self._api_settings_action.triggered.connect(self._open_api_cfg)

        self._folder_tree = QTreeWidget()
        self._folder_tree.setHeaderHidden(True)
        self._folder_tree.setAlternatingRowColors(True)
        self._folder_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._folder_tree.currentItemChanged.connect(self._on_level_selection_changed)
        self._folder_tree.customContextMenuRequested.connect(self._show_folder_tree_context_menu)
        self._folder_tree.itemExpanded.connect(self._on_tree_item_expanded)
        self._folder_tree.itemCollapsed.connect(self._on_tree_item_collapsed)

        left_layout = QVBoxLayout()
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self._folder_tree, 1)
        left_panel = QWidget()
        left_panel.setStyleSheet(rounded_panel_stylesheet(background="#ffffff"))
        left_panel.setLayout(left_layout)

        self._table = _ZoomableTableWidget(0, len(self._column_defs), zoom_callback=self._adjust_table_font_size)
        self._table.setHorizontalHeaderLabels([title for _key, title, _visible in self._column_defs])
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setWordWrap(True)
        self._table.setStyleSheet(
            "QTableWidget {"
            "border: 1px solid #000000; border-radius: 10px; background: #ffffff; gridline-color: #000000; outline: none;"
            "}"
            "QTableWidget > QWidget {"
            "background: #ffffff; border-radius: 10px;"
            "}"
            "QHeaderView {"
            "background: transparent; border: none;"
            "}"
            "QHeaderView::section {"
            "background: #ffffff; border: none; border-right: 1px solid #000000; border-bottom: 1px solid #000000;"
            "padding: 4px 6px; font-weight: 600;"
            "}"
            "QHeaderView::section:first {"
            "border-top-left-radius: 10px;"
            "}"
            "QHeaderView::section:last {"
            "border-right: none; border-top-right-radius: 10px;"
            "}"
        )
        self._table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        self._table.horizontalHeader().sectionResized.connect(self._schedule_table_row_resize)
        self._table.cellDoubleClicked.connect(self._on_table_cell_double_clicked)
        self._column_actions: dict[int, object] = {}
        for idx, (key, title, _visible) in enumerate(self._column_defs):
            visible = self._column_visibility.get(key, False)
            action = column_menu.addAction(title)
            action.setCheckable(True)
            action.setChecked(visible)
            action.toggled.connect(lambda checked, col=idx: self._set_column_visible(col, checked))
            self._column_actions[idx] = action
            self._table.setColumnHidden(idx, not visible)
        self._rebalance_visible_columns()

        self._table_placeholder = QLabel("请先从左侧层级中选择，以显示题目信息")
        self._table_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._table_placeholder.setWordWrap(True)
        self._apply_table_font_size()

        right_layout = QVBoxLayout()
        right_layout.setContentsMargins(0, 0, 0, 0)
        self._table_stack = QStackedLayout()
        self._table_stack.addWidget(self._table_placeholder)
        self._table_stack.addWidget(self._table)
        right_layout.addLayout(self._table_stack, 1)
        right_panel = QWidget()
        right_panel.setStyleSheet(rounded_panel_stylesheet(background="#ffffff"))
        right_panel.setLayout(right_layout)

        self._content_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._content_splitter.addWidget(left_panel)
        self._content_splitter.addWidget(right_panel)
        self._content_splitter.setChildrenCollapsible(False)
        self._content_splitter.setHandleWidth(6)
        self._content_splitter.setStyleSheet("QSplitter::handle { background-color: transparent; }")
        self._content_splitter.setStretchFactor(0, 1)
        self._content_splitter.setStretchFactor(1, 4)
        self._content_splitter.setSizes([180, 720])
        self._content_splitter.splitterMoved.connect(self._schedule_table_row_resize)

        layout = QVBoxLayout()
        layout.setMenuBar(menu_bar)
        layout.addWidget(self._content_splitter, 1)
        self.setLayout(layout)
        self._set_table_placeholder_visible(True)

    def initializePage(self) -> None:
        self._db_path = self._current_db_path()
        self._refresh_level_tree()
        if self._folder_tree.currentItem() is None:
            self._current_db_records = []
            self._table.setRowCount(0)
            self._schedule_table_row_resize()
            self._set_table_placeholder_visible(True)

    def _enter_main_flow(self) -> None:
        self._state.start_mode = "wizard"
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "选择资料文件",
            self._effective_import_source_dir(),
            "Word (*.docx);;All Files (*)",
        )
        if not files:
            return
        selected_paths = [Path(p) for p in files]
        try:
            copied_paths = self._backup_import_source_files(selected_paths)
        except Exception as e:
            _show_message_box(
                self,
                title="备份失败",
                text=f"复制资料到 doc 目录失败：{e}",
                icon=QMessageBox.Icon.Critical,
            )
            return
        self._state.ai_source_files = copied_paths
        self._state.ai_source_files_text = "; ".join(str(p) for p in copied_paths)
        self._state.ai_source_file_items = [AiSourceFileItem(path=str(p)) for p in copied_paths]
        from sj_generator.ui.import_flow_wizard import ImportFlowWizard

        dlg = ImportFlowWizard(self._state, self)
        if dlg.exec():
            self._refresh_level_tree(preferred_level_path=self._state.ai_import_level_path)

    def _effective_import_source_dir(self) -> str:
        configured = Path(self._state.import_source_dir_text).expanduser()
        if configured.exists() and configured.is_dir():
            return str(configured)
        return str(Path.home() / "Downloads")

    def _backup_import_source_files(self, paths: list[Path]) -> list[Path]:
        if not paths:
            return []
        target_dir = self._db_path.parent / "doc"
        target_dir.mkdir(parents=True, exist_ok=True)
        known_hash_paths = self._build_doc_hash_index(target_dir)
        copied_paths: list[Path] = []
        seen_targets: set[Path] = set()
        for src in paths:
            if not src.exists() or not src.is_file():
                raise FileNotFoundError(src)
            file_hash = self._file_sha256(src)
            target_path = known_hash_paths.get(file_hash)
            if target_path is None:
                target_path = self._next_doc_backup_path(target_dir, src.name)
                shutil.copy2(src, target_path)
                known_hash_paths[file_hash] = target_path
            resolved_target = target_path.resolve()
            if resolved_target in seen_targets:
                continue
            seen_targets.add(resolved_target)
            copied_paths.append(target_path)
        return copied_paths

    def _build_doc_hash_index(self, target_dir: Path) -> dict[str, Path]:
        hash_index: dict[str, Path] = {}
        for path in sorted(target_dir.glob("*.docx"), key=lambda item: item.name.lower()):
            if not path.is_file():
                continue
            try:
                file_hash = self._file_sha256(path)
            except Exception:
                continue
            hash_index.setdefault(file_hash, path)
        return hash_index

    def _file_sha256(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()

    def _next_doc_backup_path(self, target_dir: Path, file_name: str) -> Path:
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

    def _open_api_cfg(self) -> None:
        dlg = ApiConfigDialog(self, state=self._state)
        dlg.exec()

    def _open_program_settings(self) -> None:
        dlg = ProgramSettingsDialog(self._state, self, section=SECTION_GENERAL)
        if dlg.exec():
            self._db_path = self._current_db_path()
            self._refresh_level_tree()

    def _open_general_settings(self) -> None:
        self._open_program_settings()

    def _open_import_settings(self) -> None:
        dlg = ProgramSettingsDialog(self._state, self, section=SECTION_IMPORT)
        dlg.exec()

    def _open_export_settings(self) -> None:
        dlg = ProgramSettingsDialog(self._state, self, section=SECTION_EXPORT)
        dlg.exec()

    def _import_from_table_file(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(self, "选择表格文件", "", "Excel (*.xlsx);;All Files (*)")
        if not file_path:
            return
        path = Path(file_path)
        try:
            records = load_db_question_records(path)
        except Exception as e:
            _show_message_box(self, title="导入失败", text=f"读取表格文件失败：{e}", icon=QMessageBox.Icon.Critical)
            return
        if not records:
            _show_message_box(self, title="无法导入", text="当前 xlsx 中没有可写入数据库的记录。", icon=QMessageBox.Icon.Warning)
            return
        try:
            append_questions(self._db_path, records)
        except Exception as e:
            _show_message_box(self, title="导入失败", text=f"写入数据库失败：{e}", icon=QMessageBox.Icon.Critical)
            return
        preferred_level_path = next((record.level_path for record in records if record.level_path.strip()), "")
        self._refresh_level_tree(preferred_level_path=preferred_level_path)
        _show_message_box(self, title="导入完成", text=f"已从数据库字段表 xlsx 导入 {len(records)} 道题。", icon=QMessageBox.Icon.Information)

    def _export_current_level_to_markdown(self) -> None:
        if not self._current_db_records:
            _show_message_box(self, title="无法导出", text="当前页面没有可导出的题目。", icon=QMessageBox.Icon.Warning)
            return

        current = self._folder_tree.currentItem()
        if current is None:
            _show_message_box(self, title="无法导出", text="请先选择要导出的层级。", icon=QMessageBox.Icon.Warning)
            return

        level_path = str(current.data(0, TREE_ROLE_LEVEL_PATH) or "").strip()
        if not level_path:
            _show_message_box(self, title="无法导出", text="当前页面无效，无法导出。", icon=QMessageBox.Icon.Warning)
            return

        safe_level_name = self._sanitize_export_name(self._display_export_level_name(level_path))
        suggested = str(self._db_path.parent / f"{safe_level_name}.md")
        file_path, _ = QFileDialog.getSaveFileName(self, "导出 Markdown", suggested, "Markdown (*.md)")
        if not file_path:
            return

        questions = [self._db_record_to_question(record) for record in self._current_db_records]
        md_text = export_questions_to_markdown(
            excel_file_name=level_path,
            export_date=date.today(),
            questions=questions,
            convertible_multi_mode=self._state.export_convertible_multi_mode,
            include_answers=self._state.export_include_answers,
            include_analysis=self._state.export_include_analysis,
        )
        md_path = Path(file_path)
        try:
            md_path.parent.mkdir(parents=True, exist_ok=True)
            md_path.write_text(md_text, encoding="utf-8")
        except Exception as e:
            _show_message_box(self, title="导出失败", text=f"写入 Markdown 失败：{e}", icon=QMessageBox.Icon.Critical)
            return

        self._state.last_export_dir = md_path.parent
        _show_message_box(self, title="导出完成", text=f"已导出 Markdown：\n{md_path}", icon=QMessageBox.Icon.Information)

    def _export_current_level_to_pdf(self) -> None:
        if not self._current_db_records:
            _show_message_box(self, title="无法导出", text="当前页面没有可导出的题目。", icon=QMessageBox.Icon.Warning)
            return

        current = self._folder_tree.currentItem()
        if current is None:
            _show_message_box(self, title="无法导出", text="请先选择要导出的层级。", icon=QMessageBox.Icon.Warning)
            return

        level_path = str(current.data(0, TREE_ROLE_LEVEL_PATH) or "").strip()
        if not level_path:
            _show_message_box(self, title="无法导出", text="当前页面无效，无法导出。", icon=QMessageBox.Icon.Warning)
            return

        safe_level_name = self._sanitize_export_name(self._display_export_level_name(level_path))
        suggested = str(self._default_export_dir() / f"{safe_level_name}.pdf")
        file_path, _ = QFileDialog.getSaveFileName(self, "导出 PDF", suggested, "PDF (*.pdf)")
        if not file_path:
            return

        target_path = Path(file_path)
        questions = [self._db_record_to_question(record) for record in self._current_db_records]
        try:
            export_questions_to_pdf(
                excel_file_name=level_path,
                export_date=date.today(),
                questions=questions,
                target_path=target_path,
                convertible_multi_mode=self._state.export_convertible_multi_mode,
                include_answers=self._state.export_include_answers,
                include_analysis=self._state.export_include_analysis,
            )
        except Exception as e:
            _show_message_box(self, title="导出失败", text=f"写入 PDF 失败：{e}", icon=QMessageBox.Icon.Critical)
            return

        self._state.last_export_dir = target_path.parent
        _show_message_box(self, title="导出完成", text=f"已导出 PDF：\n{target_path}", icon=QMessageBox.Icon.Information)

    def _export_current_level_to_xlsx(self) -> None:
        if not self._current_db_records:
            _show_message_box(self, title="无法导出", text="当前页面没有可导出的题目。", icon=QMessageBox.Icon.Warning)
            return
        current = self._folder_tree.currentItem()
        if current is None:
            _show_message_box(self, title="无法导出", text="请先选择要导出的层级。", icon=QMessageBox.Icon.Warning)
            return
        level_path = str(current.data(0, TREE_ROLE_LEVEL_PATH) or "").strip()
        if not level_path:
            _show_message_box(self, title="无法导出", text="当前页面无效，无法导出。", icon=QMessageBox.Icon.Warning)
            return
        safe_level_name = self._sanitize_export_name(self._display_export_level_name(level_path))
        suggested = str(self._default_export_dir() / f"{safe_level_name}.xlsx")
        file_path, _ = QFileDialog.getSaveFileName(self, "导出当前页面 xlsx", suggested, "Excel (*.xlsx)")
        if not file_path:
            return
        target_path = Path(file_path)
        try:
            save_db_question_records(target_path, list(self._current_db_records))
        except Exception as e:
            _show_message_box(self, title="导出失败", text=f"写入 xlsx 失败：{e}", icon=QMessageBox.Icon.Critical)
            return
        self._state.last_export_dir = target_path.parent
        _show_message_box(self, title="导出完成", text=f"已导出当前页面 xlsx：\n{target_path}", icon=QMessageBox.Icon.Information)

    def _export_db_table_to_xlsx(self) -> None:
        if not self._db_path.exists():
            _show_message_box(self, title="无法导出", text="当前数据库文件不存在。", icon=QMessageBox.Icon.Warning)
            return
        records = load_all_questions(self._db_path)
        if not records:
            _show_message_box(self, title="无法导出", text="当前数据库表没有可导出的题目。", icon=QMessageBox.Icon.Warning)
            return
        suggested_name = f"{self._sanitize_export_name(self._db_path.stem)}_整体数据库表.xlsx"
        suggested = str(self._default_export_dir() / suggested_name)
        file_path, _ = QFileDialog.getSaveFileName(self, "导出整体数据库表 xlsx", suggested, "Excel (*.xlsx)")
        if not file_path:
            return
        target_path = Path(file_path)
        try:
            save_db_question_records(target_path, records)
        except Exception as e:
            _show_message_box(self, title="导出失败", text=f"写入 xlsx 失败：{e}", icon=QMessageBox.Icon.Critical)
            return
        self._state.last_export_dir = target_path.parent
        _show_message_box(self, title="导出完成", text=f"已导出整体数据库表 xlsx：\n{target_path}", icon=QMessageBox.Icon.Information)

    def _selected_tree_level_path_for_create(self) -> str:
        current = self._folder_tree.currentItem()
        if current is None:
            return ""
        exact_level_path = str(current.data(0, TREE_ROLE_LEVEL_PATH) or "").strip()
        if exact_level_path:
            return exact_level_path
        return str(current.data(0, TREE_ROLE_LEVEL_PREFIX) or "").strip()

    def _add_question_manually(self, *, default_level_path: str | None = None) -> None:
        if default_level_path is None:
            default_level_path = self._selected_tree_level_path_for_create()
        default_level_path = str(default_level_path or "").strip()
        now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        new_record = DbQuestionRecord(
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
            textbook_version=self._state.preferred_textbook_version,
            source="录入",
            level_path=default_level_path,
            difficulty_score=None,
            knowledge_points="",
            abilities="",
            created_at=now_text,
            updated_at=now_text,
        )
        dlg = _QuestionEditDialog(new_record, self, create_mode=True)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        created = dlg.updated_record()
        if not created.stem.strip():
            _show_message_box(self, title="无法新增", text="题目内容不能为空。", icon=QMessageBox.Icon.Warning)
            return
        try:
            append_questions(self._db_path, [created])
        except Exception as e:
            _show_message_box(self, title="新增失败", text=f"写入题目失败：{e}", icon=QMessageBox.Icon.Critical)
            return
        self._refresh_level_tree(preferred_level_path=created.level_path)
        _show_message_box(self, title="新增完成", text="题目已新增。", icon=QMessageBox.Icon.Information)

    def _refresh_level_tree(self, preferred_level_path: str | None = None) -> None:
        current_item = self._folder_tree.currentItem()
        current_prefix = ""
        if current_item is not None:
            current_prefix = str(current_item.data(0, TREE_ROLE_LEVEL_PREFIX) or "").strip()
        if self._folder_tree.topLevelItemCount() > 0:
            self._expanded_level_prefixes = self._collect_expanded_level_prefixes()
        self._folder_tree.clear()
        if not self._db_path.exists():
            return

        self._syncing_tree_expand_state = True
        item_map: dict[tuple[str, ...], QTreeWidgetItem] = {}
        preferred_item: QTreeWidgetItem | None = None
        selected_prefix_item: QTreeWidgetItem | None = None
        preferred_level_key = self._tree_level_key_for_path(preferred_level_path)
        for level_path in list_level_paths(self._db_path):
            parts = self._display_level_parts(level_path)
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
                    item = QTreeWidgetItem([self._format_level_label(idx, part)])
                    item.setToolTip(0, prefix_path)
                    item.setData(0, TREE_ROLE_LEVEL_PREFIX, prefix_path)
                    item.setData(0, TREE_ROLE_LEVEL_DEPTH, idx)
                    item.setData(0, TREE_ROLE_LEVEL_PATH, prefix_path)
                    if parent_item is None:
                        self._folder_tree.addTopLevelItem(item)
                    else:
                        parent_item.addChild(item)
                    item_map[key] = item
                if prefix_path in self._expanded_level_prefixes:
                    item.setExpanded(True)
                if current_prefix and prefix_path == current_prefix:
                    selected_prefix_item = item
                if idx == len(parts) - 1:
                    if preferred_level_key and prefix_path == preferred_level_key:
                        preferred_item = item
                parent_item = item

        self._syncing_tree_expand_state = False
        selected_item = preferred_item or selected_prefix_item
        if selected_item is not None:
            self._folder_tree.setCurrentItem(selected_item)
            if preferred_item is not None:
                self._expand_item_ancestors(selected_item)
        else:
            self._folder_tree.setCurrentItem(None)
            self._folder_tree.clearSelection()
            self._table.setRowCount(0)
            self._current_db_records = []
            self._schedule_table_row_resize()
            self._set_table_placeholder_visible(True)
        self._sync_expanded_level_prefixes_from_tree()

    def _on_level_selection_changed(self, current: QTreeWidgetItem | None, _previous: QTreeWidgetItem | None) -> None:
        if current is None:
            self._current_db_records = []
            self._table.setRowCount(0)
            self._set_table_placeholder_visible(True)
            return
        level_key = str(current.data(0, TREE_ROLE_LEVEL_PATH) or "").strip()
        if not level_key:
            self._current_db_records = []
            self._table.setRowCount(0)
            self._set_table_placeholder_visible(True)
            return
        records = self._load_questions_for_tree_level(level_key)
        self._current_db_records = records
        self._populate_db_records_table(records)

    def _show_folder_tree_context_menu(self, pos) -> None:
        item = self._folder_tree.itemAt(pos)
        if item is None:
            return
        level_prefix = str(item.data(0, TREE_ROLE_LEVEL_PREFIX) or "").strip()
        if not level_prefix:
            return
        depth = int(item.data(0, TREE_ROLE_LEVEL_DEPTH) or 0)
        self._folder_tree.setCurrentItem(item)
        menu = QMenu(self)
        add_action = menu.addAction("新增题目")
        delete_action = menu.addAction(self._delete_action_text(depth))
        chosen = menu.exec(self._folder_tree.viewport().mapToGlobal(pos))
        if chosen == add_action:
            self._add_question_manually(default_level_path=str(item.data(0, TREE_ROLE_LEVEL_PATH) or item.data(0, TREE_ROLE_LEVEL_PREFIX) or "").strip())
            return
        if chosen == delete_action:
            self._delete_level_subtree(
                level_prefix=level_prefix,
                depth=depth,
                display_label=item.text(0).strip() or level_prefix,
            )

    def _on_tree_item_expanded(self, _item: QTreeWidgetItem) -> None:
        if self._syncing_tree_expand_state:
            return
        self._sync_expanded_level_prefixes_from_tree()

    def _on_tree_item_collapsed(self, _item: QTreeWidgetItem) -> None:
        if self._syncing_tree_expand_state:
            return
        self._sync_expanded_level_prefixes_from_tree()

    def _delete_level_subtree(self, *, level_prefix: str, depth: int, display_label: str) -> None:
        level_prefix = (level_prefix or "").strip()
        if not level_prefix:
            return
        total = count_questions_by_level_prefix(self._db_path, level_prefix)
        if total <= 0:
            _show_message_box(self, title="无需删除", text="当前节点下没有可删除的题目。", icon=QMessageBox.Icon.Information)
            self._refresh_level_tree()
            return
        scope_text = self._delete_scope_text(depth)
        answer = _show_message_box(
            self,
            title="确认删除",
            text=f"确定删除{scope_text}{display_label}（层级 {level_prefix}）下的 {total} 道题吗？此操作不可撤销。",
            icon=QMessageBox.Icon.Warning,
            buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            default_button=QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        deleted_count = delete_questions_by_level_prefix(self._db_path, level_prefix)
        self._current_db_records = []
        self._table.setRowCount(0)
        self._schedule_table_row_resize()
        self._refresh_level_tree()
        _show_message_box(
            self,
            title="删除完成",
            text=f"已删除{scope_text}{display_label}下的 {deleted_count} 道题。",
            icon=QMessageBox.Icon.Information,
        )

    def _delete_action_text(self, depth: int) -> str:
        if depth == 0:
            return "删除整本书"
        if depth == 1:
            return "删除这一课"
        if depth == 2:
            return "删除这一框"
        return "删除当前层级"

    def _delete_scope_text(self, depth: int) -> str:
        if depth == 0:
            return "整本书 "
        if depth == 1:
            return "这一课 "
        if depth == 2:
            return "这一框 "
        return "当前层级 "

    def _parse_level_parts(self, level_path: str) -> list[str]:
        return [part.strip() for part in str(level_path).split(".") if part.strip()]

    def _display_level_parts(self, level_path: str) -> list[str]:
        raw_parts = self._parse_level_parts(level_path)
        display_parts: list[str] = []
        for idx, part in enumerate(raw_parts):
            if idx == 0 and part == "0":
                return ["0"]
            if idx > 0 and part == "0":
                return display_parts
            display_parts.append(part)
        return display_parts

    def _tree_level_key_for_path(self, level_path: str | None) -> str:
        return ".".join(self._display_level_parts(level_path or ""))

    def _load_questions_for_tree_level(self, level_key: str) -> list[DbQuestionRecord]:
        normalized_level_key = str(level_key or "").strip()
        if not normalized_level_key:
            return []
        return [
            record
            for record in load_all_questions(self._db_path)
            if self._tree_level_key_for_path(record.level_path) == normalized_level_key
        ]

    def _format_level_label(self, depth: int, part: str) -> str:
        if not part.isdigit():
            return part
        if depth == 0:
            if part == "0":
                return "高中阶段"
            return f"必修{self._to_chinese_number(int(part))}"
        if depth == 1:
            return f"第{self._to_chinese_number(int(part))}课"
        if depth == 2:
            return f"第{self._to_chinese_number(int(part))}框"
        return part

    def _expand_item_ancestors(self, item: QTreeWidgetItem) -> None:
        current: QTreeWidgetItem | None = item
        while current is not None:
            current.setExpanded(True)
            current = current.parent()

    def _collect_expanded_level_prefixes(self) -> set[str]:
        expanded: set[str] = set()

        def visit(item: QTreeWidgetItem) -> None:
            prefix = str(item.data(0, TREE_ROLE_LEVEL_PREFIX) or "").strip()
            if prefix and item.isExpanded():
                expanded.add(prefix)
            for index in range(item.childCount()):
                visit(item.child(index))

        for index in range(self._folder_tree.topLevelItemCount()):
            visit(self._folder_tree.topLevelItem(index))
        return expanded

    def _sync_expanded_level_prefixes_from_tree(self) -> None:
        self._expanded_level_prefixes = self._collect_expanded_level_prefixes()
        self._has_saved_tree_state = True
        save_welcome_tree_expanded_prefixes(sorted(self._expanded_level_prefixes))

    def _to_chinese_number(self, value: int) -> str:
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

    def _populate_questions_table(self, questions: list[Question]) -> None:
        self._current_db_records = []
        self._table.setRowCount(len(questions))
        for row, question in enumerate(questions):
            values = self._build_question_row_values(row + 1, question)
            self._populate_row_by_values(row, values)
        self._schedule_table_row_resize()
        self._set_table_placeholder_visible(False)

    def _populate_db_records_table(self, records: list[DbQuestionRecord]) -> None:
        self._table.setRowCount(len(records))
        for row, record in enumerate(records):
            values = self._build_db_row_values(row + 1, record)
            self._populate_row_by_values(row, values)
        self._schedule_table_row_resize()
        self._set_table_placeholder_visible(False)

    def _set_table_placeholder_visible(self, visible: bool) -> None:
        self._table_stack.setCurrentWidget(self._table_placeholder if visible else self._table)

    def _build_question_row_values(self, sequence: int, question: Question) -> dict[str, str]:
        return {
            "stem": self._format_stem_with_sequence(sequence, question.stem),
            "options": question.options,
            "answer": question.answer,
            "analysis": self._format_table_analysis(question.analysis),
            "id": "",
            "question_type": question.question_type,
            "choice_1": question.choice_1,
            "choice_2": question.choice_2,
            "choice_3": question.choice_3,
            "choice_4": question.choice_4,
            "textbook_version": "",
            "source": "",
            "level_path": "",
            "difficulty_score": "",
            "knowledge_points": "",
            "abilities": "",
            "created_at": "",
            "updated_at": "",
        }

    def _build_db_row_values(self, sequence: int, record: DbQuestionRecord) -> dict[str, str]:
        return {
            "stem": self._format_stem_with_sequence(sequence, record.stem),
            "options": self._format_db_options(record),
            "answer": self._format_db_answer(record),
            "analysis": self._format_table_analysis(record.analysis),
            "id": record.id,
            "question_type": record.question_type,
            "choice_1": record.choice_1,
            "choice_2": record.choice_2,
            "choice_3": record.choice_3,
            "choice_4": record.choice_4,
            "textbook_version": record.textbook_version,
            "source": record.source,
            "level_path": record.level_path,
            "difficulty_score": "" if record.difficulty_score is None else str(record.difficulty_score),
            "knowledge_points": record.knowledge_points,
            "abilities": record.abilities,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }

    def _db_record_to_question(self, record: DbQuestionRecord) -> Question:
        return Question(
            number=record.id,
            stem=record.stem,
            options=self._format_db_options(record),
            answer=self._format_db_answer(record),
            analysis=record.analysis,
            question_type=record.question_type,
            choice_1=record.choice_1,
            choice_2=record.choice_2,
            choice_3=record.choice_3,
            choice_4=record.choice_4,
        )

    def _populate_row_by_values(self, row: int, values: dict[str, str]) -> None:
        highlight_missing = any(
            not str(values.get(key, "") or "").strip() for key in ("stem", "options", "answer", "analysis")
        )
        for col, (key, _title, _visible) in enumerate(self._column_defs):
            alignment = Qt.AlignmentFlag.AlignCenter if key == "answer" else Qt.AlignmentFlag.AlignLeft
            self._set_table_item(
                row,
                col,
                values.get(key, ""),
                alignment,
                background=QColor("#ffd9d9") if highlight_missing else None,
            )

    def _format_db_options(self, record: DbQuestionRecord) -> str:
        options = [record.option_1, record.option_2, record.option_3, record.option_4]
        if record.question_type == "可转多选":
            lines = [
                f"{marker}. {text.strip()}".rstrip()
                for marker, text in zip(["①", "②", "③", "④"], options)
                if text.strip()
            ]
            choice_lines = [
                self._format_choice_mapping(letter, value)
                for letter, value in (
                    ("A", record.choice_1),
                    ("B", record.choice_2),
                    ("C", record.choice_3),
                    ("D", record.choice_4),
                )
                if value.strip()
            ]
            if choice_lines and lines:
                lines.append("")
            lines.extend(choice_lines)
            return "\n".join(lines)
        if record.question_type == "多选":
            markers = ["①", "②", "③", "④"]
        else:
            markers = ["A", "B", "C", "D"]
        lines = [
            f"{markers[idx - 1]}. {text.strip()}".rstrip()
            for idx, text in enumerate(options, start=1)
            if text.strip()
        ]
        return "\n".join(lines)

    def _format_db_answer(self, record: DbQuestionRecord) -> str:
        answer = (record.answer or "").strip()
        if record.question_type == "可转多选":
            if any(value.strip() for value in (record.choice_1, record.choice_2, record.choice_3, record.choice_4)):
                return answer
        if record.question_type != "多选" and record.question_type != "可转多选":
            return answer
        marker_map = {
            "1": "①",
            "2": "②",
            "3": "③",
            "4": "④",
            "5": "⑤",
            "6": "⑥",
            "7": "⑦",
            "8": "⑧",
            "9": "⑨",
            "10": "⑩",
        }
        tokens = [token.strip() for token in answer.replace("，", ",").split(",") if token.strip()]
        if not tokens:
            return answer
        return "".join(marker_map.get(token, token) for token in tokens)

    def _format_choice_mapping(self, letter: str, value: str) -> str:
        circled = "".join(self._digit_to_circled(ch) for ch in (value or "").strip() if ch.isdigit())
        if circled:
            return f"{letter}. {circled}"
        return f"{letter}. {(value or '').strip()}".rstrip()

    def _digit_to_circled(self, digit: str) -> str:
        return {
            "1": "①",
            "2": "②",
            "3": "③",
            "4": "④",
            "5": "⑤",
            "6": "⑥",
            "7": "⑦",
            "8": "⑧",
            "9": "⑨",
            "0": "⑩",
        }.get(digit, digit)

    def _format_stem_with_sequence(self, sequence: int, stem: str) -> str:
        return f"{sequence}. {stem or ''}".strip()

    def _format_table_analysis(self, analysis: str) -> str:
        return (analysis or "").replace("**", "")

    def _sanitize_export_name(self, name: str) -> str:
        cleaned = re.sub(r'[<>:"/\\\\|?*]+', "_", (name or "").strip())
        cleaned = cleaned.strip(" .")
        return cleaned or "导出结果"

    def _display_export_level_name(self, level_path: str) -> str:
        normalized_level_path = str(level_path or "").strip()
        if normalized_level_path == "0":
            return "高中阶段"
        return normalized_level_path

    def _default_export_dir(self) -> Path:
        return self._state.last_export_dir or self._db_path.parent

    def _current_db_path(self) -> Path:
        return library_db_path_from_repo_parent_dir_text(self._state.default_repo_parent_dir_text)

    def _set_table_item(
        self,
        row: int,
        col: int,
        text: str,
        alignment: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft,
        background: QColor | None = None,
    ) -> None:
        item = QTableWidgetItem(text or "")
        item.setTextAlignment(
            int(alignment | Qt.AlignmentFlag.AlignVCenter)
        )
        if background is not None:
            item.setBackground(background)
        self._table.setItem(row, col, item)

    def _set_column_visible(self, column: int, visible: bool) -> None:
        if visible:
            self._table.setColumnHidden(column, False)
            self._save_column_visibility()
            self._refresh_table_layout_after_column_change()
            return

        visible_columns = [idx for idx in range(self._table.columnCount()) if not self._table.isColumnHidden(idx)]
        if len(visible_columns) <= 1:
            action = self._column_actions.get(column)
            if action is not None:
                action.blockSignals(True)
                action.setChecked(True)
                action.blockSignals(False)
            return

        self._table.setColumnHidden(column, True)
        self._save_column_visibility()
        self._refresh_table_layout_after_column_change()

    def _schedule_table_row_resize(self, *_args) -> None:
        if self._row_resize_pending:
            return
        self._row_resize_pending = True
        QTimer.singleShot(0, self._apply_table_row_resize)

    def _apply_table_row_resize(self) -> None:
        self._row_resize_pending = False
        if self._table.rowCount() == 0:
            return
        self._table.doItemsLayout()
        self._table.resizeRowsToContents()
        if not self._row_resize_followup_pending:
            self._row_resize_followup_pending = True
            QTimer.singleShot(30, self._apply_table_row_resize_followup)

    def _apply_table_row_resize_followup(self) -> None:
        self._row_resize_followup_pending = False
        if self._table.rowCount() == 0:
            return
        self._table.doItemsLayout()
        self._table.viewport().update()
        self._table.resizeRowsToContents()

    def _refresh_table_layout_after_column_change(self) -> None:
        self._rebalance_visible_columns()
        self._table.doItemsLayout()
        self._table.viewport().update()
        self._schedule_table_row_resize()

    def _rebalance_visible_columns(self) -> None:
        visible_columns = [idx for idx in range(self._table.columnCount()) if not self._table.isColumnHidden(idx)]
        if not visible_columns:
            return
        available_width = max(1, self._table.viewport().width())
        if len(visible_columns) == 1:
            self._table.setColumnWidth(visible_columns[0], available_width)
            return
        fixed_columns = visible_columns[:-1]
        reserved_last_width = min(available_width, LAST_COLUMN_MIN_WIDTH)
        distributable_width = max(len(fixed_columns), available_width - reserved_last_width)
        base_width = max(1, distributable_width // len(fixed_columns))
        consumed_width = 0
        for column in fixed_columns:
            self._table.setColumnWidth(column, base_width)
            consumed_width += base_width
        self._table.setColumnWidth(visible_columns[-1], max(1, available_width - consumed_width))

    def _load_column_visibility(self) -> dict[str, bool]:
        saved = load_welcome_table_column_visibility()
        defaults = {key: visible for key, _title, visible in self._column_defs}
        merged = defaults | {key: value for key, value in saved.items() if key in defaults}
        if not any(merged.values()):
            first_key = self._column_defs[0][0]
            merged[first_key] = True
        return merged

    def _save_column_visibility(self) -> None:
        visibility = {
            key: (not self._table.isColumnHidden(idx))
            for idx, (key, _title, _visible) in enumerate(self._column_defs)
        }
        save_welcome_table_column_visibility(visibility)

    def _load_table_font_point_size(self) -> int:
        saved = load_welcome_table_font_point_size()
        default_size = self.font().pointSize()
        if default_size <= 0:
            default_size = 10
        if saved is None:
            return default_size
        return max(TABLE_FONT_POINT_SIZE_MIN, min(TABLE_FONT_POINT_SIZE_MAX, saved))

    def _apply_table_font_size(self) -> None:
        font = self._table.font()
        font.setPointSize(self._table_font_point_size)
        self._table.setFont(font)
        self._table.horizontalHeader().setFont(font)
        self._table_placeholder.setFont(font)
        self._table.doItemsLayout()
        self._table.viewport().update()
        self._table.horizontalHeader().viewport().update()
        self._schedule_table_row_resize()

    def _adjust_table_font_size(self, step: int) -> None:
        new_size = max(
            TABLE_FONT_POINT_SIZE_MIN,
            min(TABLE_FONT_POINT_SIZE_MAX, self._table_font_point_size + int(step)),
        )
        if new_size == self._table_font_point_size:
            return
        self._table_font_point_size = new_size
        self._apply_table_font_size()
        save_welcome_table_font_point_size(self._table_font_point_size)

    def _on_table_cell_double_clicked(self, row: int, _column: int) -> None:
        if row < 0 or row >= len(self._current_db_records):
            return
        record = self._current_db_records[row]
        dlg = _QuestionEditDialog(record, self)
        result = dlg.exec()
        if result == _QuestionEditDialog.DELETE_RESULT:
            deleted_count = delete_question_by_id(self._db_path, record.id)
            if deleted_count <= 0:
                _show_message_box(self, title="删除失败", text="未找到要删除的题目，可能已被移除。", icon=QMessageBox.Icon.Warning)
                self._refresh_level_tree()
                return
            self._current_db_records = []
            self._table.setRowCount(0)
            self._schedule_table_row_resize()
            current = self._folder_tree.currentItem()
            preferred_level_path = ""
            if current is not None:
                preferred_level_path = str(current.data(0, TREE_ROLE_LEVEL_PATH) or "").strip()
            self._refresh_level_tree(preferred_level_path=preferred_level_path)
            _show_message_box(self, title="删除完成", text="题目已删除。", icon=QMessageBox.Icon.Information)
            return
        if result != QDialog.DialogCode.Accepted:
            return
        updated = dlg.updated_record()
        try:
            update_question(self._db_path, updated)
        except Exception as e:
            _show_message_box(self, title="保存失败", text=f"更新题目失败：{e}", icon=QMessageBox.Icon.Critical)
            return
        self._current_db_records[row] = updated
        self._refresh_level_tree(preferred_level_path=updated.level_path)


class _QuestionEditDialog(QDialog):
    DELETE_RESULT = 2

    def __init__(self, record: DbQuestionRecord, parent=None, *, create_mode: bool = False) -> None:
        super().__init__(parent)
        self._record = record
        self._create_mode = create_mode
        self.setWindowTitle("新增题目" if create_mode else "编辑条目")
        self.resize(760, 484)

        self._type_combo = QComboBox()
        self._type_combo.addItems(["单选", "多选", "可转多选"])
        self._type_combo.setCurrentText(record.question_type or "单选")

        self._stem_edit = QTextEdit()
        self._stem_edit.setPlainText(record.stem)
        self._stem_edit.setPlaceholderText("题目内容")
        self._option_1_edit = QLineEdit(record.option_1)
        self._option_2_edit = QLineEdit(record.option_2)
        self._option_3_edit = QLineEdit(record.option_3)
        self._option_4_edit = QLineEdit(record.option_4)
        self._choice_1_edit = QLineEdit(record.choice_1)
        self._choice_2_edit = QLineEdit(record.choice_2)
        self._choice_3_edit = QLineEdit(record.choice_3)
        self._choice_4_edit = QLineEdit(record.choice_4)
        self._answer_line_edit = QLineEdit(record.answer)
        self._answer_line_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._answer_combo = QComboBox()
        self._answer_combo.addItems(["", "A", "B", "C", "D"])
        self._answer_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        combo_answer = (record.answer or "").strip().upper()
        combo_idx = self._answer_combo.findText(combo_answer)
        self._answer_combo.setCurrentIndex(combo_idx if combo_idx >= 0 else 0)
        answer_parts = self._split_multi_answer(record.answer)
        self._answer_part_1_edit = self._create_answer_part_edit(answer_parts[0])
        self._answer_part_2_edit = self._create_answer_part_edit(answer_parts[1])
        self._answer_part_3_edit = self._create_answer_part_edit(answer_parts[2])
        self._answer_part_4_edit = self._create_answer_part_edit(answer_parts[3])
        self._answer_part_1_edit.set_neighbors(None, self._answer_part_2_edit)
        self._answer_part_2_edit.set_neighbors(self._answer_part_1_edit, self._answer_part_3_edit)
        self._answer_part_3_edit.set_neighbors(self._answer_part_2_edit, self._answer_part_4_edit)
        self._answer_part_4_edit.set_neighbors(self._answer_part_3_edit, None)
        self._analysis_edit = QTextEdit()
        self._analysis_edit.setPlainText(record.analysis)
        self._analysis_edit.setPlaceholderText("解析内容")

        self._source_value = QLineEdit(self._format_source_display(record.source))
        self._source_value.setReadOnly(True)
        self._source_value.setPlaceholderText("题目来源：")
        level_parts = self._split_level_path(record.level_path)
        self._level_prefix_label = QLabel("所属层级：")
        self._level_part_1_edit = self._create_level_part_edit(level_parts[0])
        self._level_part_2_edit = self._create_level_part_edit(level_parts[1])
        self._level_part_3_edit = self._create_level_part_edit(level_parts[2])
        self._level_part_1_edit.set_neighbors(None, self._level_part_2_edit)
        self._level_part_2_edit.set_neighbors(self._level_part_1_edit, self._level_part_3_edit)
        self._level_part_3_edit.set_neighbors(self._level_part_2_edit, None)
        self._version_edit = QComboBox()
        self._version_edit.setEditable(True)
        self._version_edit.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        for version in self._collect_textbook_version_options(record.textbook_version):
            self._version_edit.addItem(self._format_prefixed_display("教材版本：", version))
        self._version_edit.setCurrentText(self._format_prefixed_display("教材版本：", record.textbook_version))
        if self._version_edit.lineEdit() is not None:
            self._version_edit.lineEdit().setPlaceholderText("教材版本：")
        if self._version_edit.lineEdit() is not None:
            self._bind_locked_prefix(self._version_edit.lineEdit(), "教材版本：")
        self._option_1_label = QLabel("A：")
        self._option_2_label = QLabel("B：")
        self._option_3_label = QLabel("C：")
        self._option_4_label = QLabel("D：")
        self._choice_1_label = QLabel("A：")
        self._choice_2_label = QLabel("B：")
        self._choice_3_label = QLabel("C：")
        self._choice_4_label = QLabel("D：")
        self._stem_edit.setMinimumHeight(180)
        self._analysis_edit.setMinimumHeight(140)

        def _wrap_panel(title: str, body_layout: QGridLayout | QVBoxLayout | QHBoxLayout) -> QWidget:
            panel = QWidget()
            layout = QVBoxLayout(panel)
            layout.setContentsMargins(2, 2, 2, 2)
            layout.setSpacing(8)
            if title:
                title_label = QLabel(title)
                title_label.setStyleSheet("font-weight: 600;")
                layout.addWidget(title_label)
            layout.addLayout(body_layout)
            return panel

        def _make_label_panel(text: str) -> QWidget:
            panel = QWidget()
            layout = QVBoxLayout(panel)
            layout.setContentsMargins(2, 2, 2, 2)
            label = QLabel(text)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet("font-weight: 600;")
            layout.addStretch(1)
            layout.addWidget(label)
            layout.addStretch(1)
            return panel

        stem_layout = QVBoxLayout()
        stem_layout.setContentsMargins(0, 0, 0, 0)
        stem_layout.addWidget(self._stem_edit)
        stem_panel = _wrap_panel("", stem_layout)

        option_fields_layout = QGridLayout()
        option_fields_layout.setContentsMargins(0, 0, 0, 0)
        option_fields_layout.setHorizontalSpacing(8)
        option_fields_layout.setVerticalSpacing(8)
        option_fields_layout.addWidget(self._option_1_label, 0, 0)
        option_fields_layout.addWidget(self._option_1_edit, 0, 1)
        option_fields_layout.addWidget(self._option_2_label, 1, 0)
        option_fields_layout.addWidget(self._option_2_edit, 1, 1)
        option_fields_layout.addWidget(self._option_3_label, 2, 0)
        option_fields_layout.addWidget(self._option_3_edit, 2, 1)
        option_fields_layout.addWidget(self._option_4_label, 3, 0)
        option_fields_layout.addWidget(self._option_4_edit, 3, 1)
        option_fields_layout.setColumnStretch(1, 1)

        choice_fields_layout = QGridLayout()
        choice_fields_layout.setContentsMargins(0, 0, 0, 0)
        choice_fields_layout.setHorizontalSpacing(8)
        choice_fields_layout.setVerticalSpacing(8)
        choice_fields_layout.addWidget(self._choice_1_label, 0, 0)
        choice_fields_layout.addWidget(self._choice_1_edit, 0, 1)
        choice_fields_layout.addWidget(self._choice_2_label, 1, 0)
        choice_fields_layout.addWidget(self._choice_2_edit, 1, 1)
        choice_fields_layout.addWidget(self._choice_3_label, 2, 0)
        choice_fields_layout.addWidget(self._choice_3_edit, 2, 1)
        choice_fields_layout.addWidget(self._choice_4_label, 3, 0)
        choice_fields_layout.addWidget(self._choice_4_edit, 3, 1)
        choice_fields_layout.setColumnStretch(1, 1)

        option_fields_widget = QWidget()
        option_fields_widget.setLayout(option_fields_layout)
        self._choice_fields_widget = QWidget()
        self._choice_fields_widget.setLayout(choice_fields_layout)

        options_layout = QHBoxLayout()
        options_layout.setContentsMargins(0, 0, 0, 0)
        options_layout.setSpacing(12)
        options_layout.addWidget(option_fields_widget, 3)
        options_layout.addWidget(self._choice_fields_widget, 2)
        options_panel_layout = QVBoxLayout()
        options_panel_layout.setContentsMargins(0, 0, 0, 0)
        options_panel_layout.setSpacing(8)
        options_panel_layout.addLayout(options_layout)
        options_panel = _wrap_panel("", options_panel_layout)

        answer_layout = QGridLayout()
        answer_layout.setContentsMargins(0, 0, 0, 0)
        answer_layout.setHorizontalSpacing(8)
        answer_layout.setVerticalSpacing(8)
        self._answer_stack = QStackedLayout()
        self._answer_stack.setContentsMargins(0, 0, 0, 0)
        answer_stack_widget = QWidget()
        answer_stack_widget.setLayout(self._answer_stack)
        answer_stack_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._answer_stack.addWidget(self._answer_line_edit)
        self._answer_stack.addWidget(self._answer_combo)
        answer_multi_row = QHBoxLayout()
        answer_multi_row.setContentsMargins(0, 0, 0, 0)
        answer_multi_row.setSpacing(6)
        answer_multi_row.addWidget(self._answer_part_1_edit)
        answer_multi_row.addWidget(self._answer_part_2_edit)
        answer_multi_row.addWidget(self._answer_part_3_edit)
        answer_multi_row.addWidget(self._answer_part_4_edit)
        answer_multi_row.addStretch(1)
        answer_multi_widget = QWidget()
        answer_multi_widget.setLayout(answer_multi_row)
        answer_multi_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._answer_stack.addWidget(answer_multi_widget)
        answer_layout.addWidget(QLabel("答案："), 0, 0)
        answer_layout.addWidget(answer_stack_widget, 0, 1)
        answer_layout.addWidget(QLabel("题型："), 1, 0)
        answer_layout.addWidget(self._type_combo, 1, 1)
        answer_layout.setColumnStretch(1, 1)
        answer_panel = _wrap_panel("", answer_layout)

        analysis_layout = QVBoxLayout()
        analysis_layout.setContentsMargins(0, 0, 0, 0)
        analysis_layout.addWidget(self._analysis_edit)
        analysis_panel = _wrap_panel("", analysis_layout)

        source_content_layout = QVBoxLayout()
        source_content_layout.setContentsMargins(0, 0, 0, 0)
        source_content_layout.addWidget(self._source_value)
        source_content_panel = _wrap_panel("", source_content_layout)

        level_content_layout = QVBoxLayout()
        level_content_layout.setContentsMargins(0, 0, 0, 0)
        level_row = QHBoxLayout()
        level_row.setContentsMargins(0, 0, 0, 0)
        level_row.setSpacing(6)
        level_row.addWidget(self._level_prefix_label)
        level_row.addWidget(self._level_part_1_edit)
        level_row.addWidget(QLabel("."))
        level_row.addWidget(self._level_part_2_edit)
        level_row.addWidget(QLabel("."))
        level_row.addWidget(self._level_part_3_edit)
        level_row.addStretch(1)
        level_content_layout.addLayout(level_row)
        level_content_panel = _wrap_panel("", level_content_layout)

        version_content_layout = QVBoxLayout()
        version_content_layout.setContentsMargins(0, 0, 0, 0)
        version_content_layout.addWidget(self._version_edit)
        version_content_panel = _wrap_panel("", version_content_layout)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_button is not None:
            ok_button.setText("确定")
            ok_button.setMinimumSize(96, 36)
        cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_button is not None:
            cancel_button.setText("取消")
            cancel_button.setMinimumSize(96, 36)

        button_row = QHBoxLayout()
        self._delete_btn = QPushButton("删除题目")
        self._delete_btn.setMinimumSize(96, 36)
        self._delete_btn.setStyleSheet("border: 1px solid #c00000;")
        self._delete_btn.clicked.connect(self._on_delete_clicked)
        if not self._create_mode:
            button_row.addWidget(self._delete_btn)
        button_row.addStretch(1)
        button_row.addWidget(buttons)

        content_grid = QGridLayout()
        content_grid.setContentsMargins(0, 0, 0, 0)
        content_grid.setHorizontalSpacing(10)
        content_grid.setVerticalSpacing(10)
        content_grid.addWidget(stem_panel, 0, 0, 5, 2)
        content_grid.addWidget(answer_panel, 0, 2, 1, 2)
        content_grid.addWidget(options_panel, 1, 2, 4, 2)
        content_grid.addWidget(analysis_panel, 5, 0, 2, 4)
        content_grid.addWidget(level_content_panel, 7, 0, 1, 4)
        content_grid.addWidget(version_content_panel, 8, 0, 1, 4)
        content_grid.addWidget(source_content_panel, 9, 0, 1, 4)
        for col in range(4):
            content_grid.setColumnStretch(col, 1)
        for row in range(10):
            content_grid.setRowStretch(row, 0)
        content_grid.setRowStretch(5, 1)
        content_grid.setRowStretch(6, 1)

        layout = QVBoxLayout()
        layout.addLayout(content_grid)
        layout.addLayout(button_row)
        self.setLayout(layout)
        self._type_combo.currentTextChanged.connect(self._sync_choice_fields_visibility)
        self._sync_choice_fields_visibility(self._type_combo.currentText())

    def accept(self) -> None:
        level_parts = [
            self._level_part_1_edit.text().strip(),
            self._level_part_2_edit.text().strip(),
            self._level_part_3_edit.text().strip(),
        ]
        if any(level_parts) and not all(level_parts):
            _show_message_box(
                self,
                title="所属层级不完整",
                text="所属层级需要按“数字.数字.数字”完整填写。",
                icon=QMessageBox.Icon.Warning,
            )
            return
        super().accept()

    def updated_record(self) -> DbQuestionRecord:
        return replace(
            self._record,
            stem=self._stem_edit.toPlainText().strip(),
            option_1=self._option_1_edit.text().strip(),
            option_2=self._option_2_edit.text().strip(),
            option_3=self._option_3_edit.text().strip(),
            option_4=self._option_4_edit.text().strip(),
            choice_1=self._choice_1_edit.text().strip(),
            choice_2=self._choice_2_edit.text().strip(),
            choice_3=self._choice_3_edit.text().strip(),
            choice_4=self._choice_4_edit.text().strip(),
            answer=self._current_answer_text(),
            analysis=self._analysis_edit.toPlainText().strip(),
            question_type=self._type_combo.currentText().strip(),
            source=self._parse_source_display(self._source_value.text()),
            level_path=self._compose_level_path(),
            textbook_version=self._parse_prefixed_display("教材版本：", self._version_edit.currentText()),
            updated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )

    def _format_source_display(self, source: str) -> str:
        return self._format_prefixed_display("题目来源：", source)

    def _parse_source_display(self, text: str) -> str:
        return self._parse_prefixed_display("题目来源：", text)

    def _bind_locked_prefix(self, edit: QLineEdit, prefix: str) -> None:
        edit.textEdited.connect(
            lambda _text, target=edit, locked_prefix=prefix: self._ensure_locked_prefix(target, locked_prefix)
        )
        edit.cursorPositionChanged.connect(
            lambda _old, new, target=edit, locked_prefix=prefix: self._clamp_prefix_cursor(
                target, locked_prefix, new
            )
        )
        self._ensure_locked_prefix(edit, prefix)

    def _create_level_part_edit(self, value: str) -> _LevelPathPartLineEdit:
        edit = _LevelPathPartLineEdit((value or "").strip()[:1])
        edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        edit.setMaxLength(1)
        edit.setFixedWidth(36)
        edit.setPlaceholderText("0")
        edit.setValidator(QRegularExpressionValidator(QRegularExpression(r"^\d?$"), edit))
        return edit

    def _split_level_path(self, value: str) -> tuple[str, str, str]:
        parts = [part.strip() for part in str(value or "").split(".")]
        return (
            parts[0][:1] if len(parts) > 0 else "",
            parts[1][:1] if len(parts) > 1 else "",
            parts[2][:1] if len(parts) > 2 else "",
        )

    def _compose_level_path(self) -> str:
        parts = [
            self._level_part_1_edit.text().strip(),
            self._level_part_2_edit.text().strip(),
            self._level_part_3_edit.text().strip(),
        ]
        if not any(parts):
            return ""
        if all(parts):
            return ".".join(parts)
        return ""

    def _current_answer_text(self) -> str:
        answer_mode = self._answer_input_mode(self._type_combo.currentText())
        if answer_mode == "combo":
            return self._answer_combo.currentText().strip()
        if answer_mode == "multi_parts":
            digits = [
                self._circled_to_digit(self._answer_part_1_edit.text()),
                self._circled_to_digit(self._answer_part_2_edit.text()),
                self._circled_to_digit(self._answer_part_3_edit.text()),
                self._circled_to_digit(self._answer_part_4_edit.text()),
            ]
            return ",".join(digit for digit in digits if digit)
        return self._answer_line_edit.text().strip()

    def _set_answer_text(self, value: str, *, mode: str) -> None:
        normalized = (value or "").strip()
        if mode == "combo":
            combo_value = normalized.upper()
            combo_idx = self._answer_combo.findText(combo_value)
            self._answer_combo.setCurrentIndex(combo_idx if combo_idx >= 0 else 0)
            return
        if mode == "multi_parts":
            parts = self._split_multi_answer(normalized)
            self._answer_part_1_edit.setText(parts[0])
            self._answer_part_2_edit.setText(parts[1])
            self._answer_part_3_edit.setText(parts[2])
            self._answer_part_4_edit.setText(parts[3])
            return
        self._answer_line_edit.setText(normalized)

    def _answer_input_mode(self, question_type: str) -> str:
        normalized_type = (question_type or "").strip()
        if normalized_type in ("单选", "可转多选"):
            return "combo"
        if normalized_type == "多选":
            return "multi_parts"
        return "line"

    def _create_answer_part_edit(self, value: str) -> _LevelPathPartLineEdit:
        edit = _LevelPathPartLineEdit((value or "").strip()[:1])
        edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        edit.setMaxLength(1)
        edit.setFixedWidth(36)
        edit.setPlaceholderText("")
        edit.setValidator(QRegularExpressionValidator(QRegularExpression(r"^[①②③④1-4]?$"), edit))
        edit.textEdited.connect(
            lambda _text, target=edit: target.setText(self._normalize_multi_answer_part(target.text()))
        )
        return edit

    def _split_multi_answer(self, value: str) -> tuple[str, str, str, str]:
        chars = [
            self._normalize_multi_answer_part(ch)
            for ch in str(value or "")
            if self._normalize_multi_answer_part(ch)
        ]
        return (
            chars[0] if len(chars) > 0 else "",
            chars[1] if len(chars) > 1 else "",
            chars[2] if len(chars) > 2 else "",
            chars[3] if len(chars) > 3 else "",
        )

    def _normalize_multi_answer_part(self, value: str) -> str:
        text = (value or "").strip()
        if not text:
            return ""
        return {
            "1": "①",
            "2": "②",
            "3": "③",
            "4": "④",
            "①": "①",
            "②": "②",
            "③": "③",
            "④": "④",
        }.get(text[:1], "")

    def _circled_to_digit(self, value: str) -> str:
        text = (value or "").strip()
        return {
            "①": "1",
            "②": "2",
            "③": "3",
            "④": "4",
            "1": "1",
            "2": "2",
            "3": "3",
            "4": "4",
        }.get(text[:1], "")

    def _collect_textbook_version_options(self, current_value: str) -> list[str]:
        versions: list[str] = []
        seen: set[str] = set()

        def add_version(value: str) -> None:
            normalized = str(value or "").strip()
            if not normalized or normalized in seen:
                return
            seen.add(normalized)
            versions.append(normalized)

        add_version(current_value)
        parent = self.parent()
        current_records = getattr(parent, "_current_db_records", None)
        if isinstance(current_records, list):
            for record in current_records:
                add_version(getattr(record, "textbook_version", ""))
        return versions

    def _ensure_locked_prefix(self, edit: QLineEdit, prefix: str) -> None:
        min_pos = len(prefix)
        normalized_text = self._format_prefixed_display(prefix, self._parse_prefixed_display(prefix, edit.text()))
        if edit.text() != normalized_text:
            current_pos = max(min_pos, edit.cursorPosition())
            edit.setText(normalized_text)
            edit.setCursorPosition(min(current_pos, len(normalized_text)))
            return
        if edit.cursorPosition() < min_pos:
            edit.setCursorPosition(min_pos)

    def _clamp_prefix_cursor(self, edit: QLineEdit, prefix: str, new_position: int) -> None:
        min_pos = len(prefix)
        if new_position < min_pos:
            edit.setCursorPosition(min_pos)

    def _format_prefixed_display(self, prefix: str, value: str) -> str:
        normalized_prefix = str(prefix or "").strip()
        normalized_value = (value or "").strip()
        if not normalized_prefix:
            return normalized_value
        if not normalized_value:
            return normalized_prefix
        if normalized_value.startswith(normalized_prefix):
            return normalized_value
        return f"{normalized_prefix}{normalized_value}"

    def _parse_prefixed_display(self, prefix: str, text: str) -> str:
        normalized_prefix = str(prefix or "").strip()
        normalized_value = (text or "").strip()
        if normalized_prefix and normalized_value.startswith(normalized_prefix):
            return normalized_value[len(normalized_prefix):].strip()
        return normalized_value

    def _on_delete_clicked(self) -> None:
        answer = _show_message_box(
            self,
            title="确认删除",
            text="确定删除这道题目吗？此操作不可撤销。",
            icon=QMessageBox.Icon.Warning,
            buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            default_button=QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.done(self.DELETE_RESULT)

    def _sync_choice_fields_visibility(self, question_type: str) -> None:
        normalized_type = (question_type or "").strip()
        current_answer = self._current_answer_text()
        answer_mode = self._answer_input_mode(normalized_type)
        self._answer_stack.setCurrentIndex({"line": 0, "combo": 1, "multi_parts": 2}.get(answer_mode, 0))
        self._set_answer_text(current_answer, mode=answer_mode)
        option_labels = (
            ("①：", "②：", "③：", "④：")
            if normalized_type in ("多选", "可转多选")
            else ("A：", "B：", "C：", "D：")
        )
        for widget, text in (
            (self._option_1_label, option_labels[0]),
            (self._option_2_label, option_labels[1]),
            (self._option_3_label, option_labels[2]),
            (self._option_4_label, option_labels[3]),
        ):
            widget.setText(text)
        visible = normalized_type == "可转多选"
        self._choice_fields_widget.setVisible(visible)
        for widget in (
            self._choice_1_label,
            self._choice_1_edit,
            self._choice_2_label,
            self._choice_2_edit,
            self._choice_3_label,
            self._choice_3_edit,
            self._choice_4_label,
            self._choice_4_edit,
        ):
            widget.setVisible(visible)
