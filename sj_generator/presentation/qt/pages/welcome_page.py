from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHeaderView,
    QLabel,
    QMessageBox,
    QStackedLayout,
    QSplitter,
    QTableWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWizard,
    QWizardPage,
    QWidget,
)

from sj_generator.application.settings import load_welcome_tree_expanded_prefixes
from sj_generator.application.state import (
    ImportWizardSession,
    WizardState,
    library_db_path_from_repo_parent_dir_text,
)
from sj_generator.infrastructure.persistence.sqlite_repo import DbQuestionRecord
from sj_generator.presentation.qt.program_settings_dialog import (
    SECTION_EXPORT,
    SECTION_GENERAL,
    SECTION_IMPORT,
)
from sj_generator.presentation.qt.constants import PAGE_AI_SELECT
from sj_generator.presentation.qt.message_box import show_message_box
from sj_generator.presentation.qt.styles import rounded_panel_stylesheet
from sj_generator.presentation.qt.table_copy import CopyableTableWidget
from sj_generator.presentation.qt.pages.welcome_export_actions import (
    export_current_level_markdown,
    export_current_level_pdf,
    export_current_level_xlsx,
    export_db_table_xlsx,
)
from sj_generator.presentation.qt.pages.welcome_import import (
    effective_import_source_dir,
    open_import_flow_states,
    open_import_flow_windows,
    show_import_flow_window,
)
from sj_generator.presentation.qt.pages.welcome_menu import build_welcome_menu_bar
from sj_generator.presentation.qt.pages.welcome_page_actions import (
    import_from_table_file,
    open_api_config,
    open_program_settings,
)
from sj_generator.presentation.qt.pages.welcome_question_actions import (
    add_question_manually,
    edit_question_record,
    selected_tree_level_path_for_create,
)
from sj_generator.presentation.qt.pages.welcome_table import populate_db_records_table
from sj_generator.presentation.qt.pages.welcome_table_view import (
    adjust_table_font_size,
    apply_table_font_size,
    apply_table_row_resize,
    apply_table_row_resize_followup,
    load_column_visibility,
    load_table_font_point_size,
    persist_table_font_point_size,
    rebalance_visible_columns,
    refresh_table_layout_after_column_change,
    schedule_table_row_resize,
    set_column_visible,
)
from sj_generator.presentation.qt.pages.welcome_tree_actions import (
    delete_level_subtree,
    handle_level_selection_changed,
    refresh_level_tree,
    show_folder_tree_context_menu,
    sync_expanded_level_prefixes_from_tree,
)

LAST_COLUMN_MIN_WIDTH = 140
TABLE_FONT_POINT_SIZE_MIN = 8
TABLE_FONT_POINT_SIZE_MAX = 28
TREE_ROLE_LEVEL_PATH = Qt.ItemDataRole.UserRole
TREE_ROLE_LEVEL_PREFIX = int(Qt.ItemDataRole.UserRole) + 1
TREE_ROLE_LEVEL_DEPTH = int(Qt.ItemDataRole.UserRole) + 2
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


class _ZoomableTableWidget(CopyableTableWidget):
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


class WelcomePage(QWizardPage):
    def __init__(self, state: WizardState) -> None:
        super().__init__()
        self._state = state
        self._db_path = self._current_db_path()
        self._import_flow_windows: list[QWizard] = []
        self._current_db_records: list[DbQuestionRecord] = []
        self._row_resize_pending = False
        self._row_resize_followup_pending = False
        self._column_defs = TABLE_COLUMNS
        self._column_visibility = load_column_visibility(self._column_defs)
        self._table_font_point_size = load_table_font_point_size(
            self,
            min_size=TABLE_FONT_POINT_SIZE_MIN,
            max_size=TABLE_FONT_POINT_SIZE_MAX,
        )
        loaded_expanded_prefixes = load_welcome_tree_expanded_prefixes()
        self._expanded_level_prefixes = set(loaded_expanded_prefixes or [])
        self._has_saved_tree_state = loaded_expanded_prefixes is not None
        self._syncing_tree_expand_state = False
        self.setTitle("开始")

        menu_bundle = build_welcome_menu_bar(
            parent=self,
            column_defs=self._column_defs,
            column_visibility=self._column_visibility,
            on_doc_import=self._enter_main_flow,
            on_table_import=self._import_from_table_file,
            on_export_markdown=self._export_current_level_to_markdown,
            on_export_pdf=self._export_current_level_to_pdf,
            on_export_current_xlsx=self._export_current_level_to_xlsx,
            on_export_db_xlsx=self._export_db_table_to_xlsx,
            on_add_question=self._add_question_manually,
            on_open_general_settings=self._open_general_settings,
            on_open_import_settings=self._open_import_settings,
            on_open_export_settings=self._open_export_settings,
            on_open_api_config=self._open_api_cfg,
            on_toggle_column=self._set_column_visible,
        )
        menu_bar = menu_bundle.menu_bar
        self._doc_import_action = menu_bundle.doc_import_action
        self._table_import_action = menu_bundle.table_import_action
        self._export_md_action = menu_bundle.export_md_action
        self._export_pdf_action = menu_bundle.export_pdf_action
        self._export_current_level_xlsx_action = menu_bundle.export_current_level_xlsx_action
        self._export_db_table_xlsx_action = menu_bundle.export_db_table_xlsx_action
        self._add_question_action = menu_bundle.add_question_action
        self._general_settings_action = menu_bundle.general_settings_action
        self._import_settings_action = menu_bundle.import_settings_action
        self._export_settings_action = menu_bundle.export_settings_action
        self._api_settings_action = menu_bundle.api_settings_action

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
            "border: 1px solid #000000; border-radius: 0px; background: #ffffff; gridline-color: #000000; outline: none;"
            "}"
            "QTableWidget > QWidget {"
            "background: #ffffff; border: none;"
            "}"
            "QHeaderView {"
            "background: transparent; border: none;"
            "}"
            "QHeaderView::section {"
            "background: #ffffff; border: none; border-right: 1px solid #000000; border-bottom: 1px solid #000000;"
            "padding: 4px 6px; font-weight: 600;"
            "}"
        )
        self._table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        self._table.horizontalHeader().sectionResized.connect(self._schedule_table_row_resize)
        self._table.cellDoubleClicked.connect(self._on_table_cell_double_clicked)
        self._column_actions = menu_bundle.column_actions
        for idx, (key, _title, _visible) in enumerate(self._column_defs):
            visible = self._column_visibility.get(key, False)
            self._table.setColumnHidden(idx, not visible)
        rebalance_visible_columns(self._table, last_column_min_width=LAST_COLUMN_MIN_WIDTH)

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
            effective_import_source_dir(self._state.import_source_dir_text),
            "Word (*.docx);;All Files (*)",
        )
        if not files:
            return
        self._open_import_flow_windows([Path(value) for value in files], message_parent=self)

    def _open_import_flow_windows(self, paths: list[Path], *, message_parent: QWidget | None = None) -> bool:
        return open_import_flow_windows(
            base_state=self._state,
            db_path=self._db_path,
            paths=paths,
            message_parent=message_parent or self,
            launcher=self,
            owner=self.window(),
            import_flow_windows=self._import_flow_windows,
            start_page_id=PAGE_AI_SELECT,
            on_state_finished=self._handle_import_flow_window_finished,
            on_window_forget=self._forget_import_flow_window,
        )

    def _open_import_flow_states(self, states: list[ImportWizardSession], *, start_page_id: int) -> bool:
        return open_import_flow_states(
            launcher=self,
            owner=self.window(),
            import_flow_windows=self._import_flow_windows,
            states=states,
            start_page_id=start_page_id,
            on_state_finished=self._handle_import_flow_window_finished,
            on_window_forget=self._forget_import_flow_window,
        )

    def _handle_import_flow_window_finished(self, state: ImportWizardSession) -> None:
        if not state.execution.db_import_completed:
            return
        self._state.last_export_dir = state.last_export_dir
        self._refresh_level_tree(preferred_level_path=state.source.import_level_path)

    def _open_split_import_flow_windows(self, states: list[ImportWizardSession], *, start_page_id: int) -> bool:
        return self._open_import_flow_states(states, start_page_id=start_page_id)

    def _forget_import_flow_window(self, wizard: QWizard) -> None:
        self._import_flow_windows = [item for item in self._import_flow_windows if item is not wizard]

    def _show_import_flow_window(self, wizard: QWizard, *, activate: bool) -> None:
        show_import_flow_window(self._import_flow_windows, wizard, activate=activate)

    def _open_api_cfg(self) -> None:
        open_api_config(self, self._state)

    def _open_program_settings(self) -> None:
        if open_program_settings(self, self._state, section=SECTION_GENERAL):
            self._db_path = self._current_db_path()
            self._refresh_level_tree()

    def _open_general_settings(self) -> None:
        self._open_program_settings()

    def _open_import_settings(self) -> None:
        open_program_settings(self, self._state, section=SECTION_IMPORT)

    def _open_export_settings(self) -> None:
        open_program_settings(self, self._state, section=SECTION_EXPORT)

    def _import_from_table_file(self) -> None:
        result = import_from_table_file(self, self._db_path)
        if result is None:
            return
        self._refresh_level_tree(preferred_level_path=result.preferred_level_path)

    def _export_current_level_to_markdown(self) -> None:
        md_path = export_current_level_markdown(
            parent=self,
            current_item=self._folder_tree.currentItem(),
            current_records=self._current_db_records,
            db_path=self._db_path,
            state=self._state,
            role_level_path=TREE_ROLE_LEVEL_PATH,
        )
        if md_path is None:
            return
        self._state.last_export_dir = md_path.parent
        show_message_box(self, title="导出完成", text=f"已导出 Markdown：\n{md_path}", icon=QMessageBox.Icon.Information)

    def _export_current_level_to_pdf(self) -> None:
        target_path = export_current_level_pdf(
            parent=self,
            current_item=self._folder_tree.currentItem(),
            current_records=self._current_db_records,
            db_path=self._db_path,
            state=self._state,
            role_level_path=TREE_ROLE_LEVEL_PATH,
        )
        if target_path is None:
            return
        self._state.last_export_dir = target_path.parent
        show_message_box(self, title="导出完成", text=f"已导出 PDF：\n{target_path}", icon=QMessageBox.Icon.Information)

    def _export_current_level_to_xlsx(self) -> None:
        target_path = export_current_level_xlsx(
            parent=self,
            current_item=self._folder_tree.currentItem(),
            current_records=self._current_db_records,
            db_path=self._db_path,
            state=self._state,
            role_level_path=TREE_ROLE_LEVEL_PATH,
        )
        if target_path is None:
            return
        self._state.last_export_dir = target_path.parent
        show_message_box(self, title="导出完成", text=f"已导出当前页面 xlsx：\n{target_path}", icon=QMessageBox.Icon.Information)

    def _export_db_table_to_xlsx(self) -> None:
        target_path = export_db_table_xlsx(parent=self, db_path=self._db_path, last_export_dir=self._state.last_export_dir)
        if target_path is None:
            return
        self._state.last_export_dir = target_path.parent
        show_message_box(self, title="导出完成", text=f"已导出整体数据库表 xlsx：\n{target_path}", icon=QMessageBox.Icon.Information)

    def _selected_tree_level_path_for_create(self) -> str:
        return selected_tree_level_path_for_create(
            self._folder_tree.currentItem(),
            role_level_path=TREE_ROLE_LEVEL_PATH,
            role_level_prefix=TREE_ROLE_LEVEL_PREFIX,
        )

    def _add_question_manually(self, *, default_level_path: str | None = None) -> None:
        if default_level_path is None:
            default_level_path = self._selected_tree_level_path_for_create()
        created = add_question_manually(
            parent=self,
            db_path=self._db_path,
            preferred_textbook_version=self._state.preferred_textbook_version,
            default_level_path=str(default_level_path or "").strip(),
        )
        if created is None:
            return
        self._refresh_level_tree(preferred_level_path=created.level_path)

    def _refresh_level_tree(self, preferred_level_path: str | None = None) -> None:
        self._syncing_tree_expand_state = True
        self._expanded_level_prefixes, has_tree = refresh_level_tree(
            tree_widget=self._folder_tree,
            db_path=self._db_path,
            expanded_level_prefixes=self._expanded_level_prefixes,
            preferred_level_path=preferred_level_path,
            role_level_prefix=TREE_ROLE_LEVEL_PREFIX,
            role_level_depth=TREE_ROLE_LEVEL_DEPTH,
            role_level_path=TREE_ROLE_LEVEL_PATH,
            on_no_selection=self._clear_current_table_selection,
        )
        self._syncing_tree_expand_state = False
        if not has_tree:
            self._clear_current_table_selection()
        self._sync_expanded_level_prefixes_from_tree()

    def _on_level_selection_changed(self, current: QTreeWidgetItem | None, _previous: QTreeWidgetItem | None) -> None:
        self._current_db_records = handle_level_selection_changed(
            current=current,
            db_path=self._db_path,
            role_level_path=TREE_ROLE_LEVEL_PATH,
            on_empty_selection=self._clear_current_table_selection,
            on_records_loaded=self._populate_db_records_table,
        )

    def _show_folder_tree_context_menu(self, pos) -> None:
        show_folder_tree_context_menu(
            parent=self,
            tree_widget=self._folder_tree,
            pos=pos,
            role_level_prefix=TREE_ROLE_LEVEL_PREFIX,
            role_level_depth=TREE_ROLE_LEVEL_DEPTH,
            role_level_path=TREE_ROLE_LEVEL_PATH,
            on_add_question=lambda default_level_path: self._add_question_manually(default_level_path=default_level_path),
            on_delete_level_subtree=lambda level_prefix, depth, display_label: self._delete_level_subtree(
                level_prefix=level_prefix,
                depth=depth,
                display_label=display_label,
            ),
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
        delete_level_subtree(
            parent=self,
            db_path=self._db_path,
            level_prefix=level_prefix,
            depth=depth,
            display_label=display_label,
            on_deleted=self._clear_table_and_refresh_tree,
            on_no_data=self._refresh_level_tree,
        )

    def _sync_expanded_level_prefixes_from_tree(self) -> None:
        self._expanded_level_prefixes = sync_expanded_level_prefixes_from_tree(
            self._folder_tree,
            role_level_prefix=TREE_ROLE_LEVEL_PREFIX,
        )
        self._has_saved_tree_state = True

    def _populate_db_records_table(self, records: list[DbQuestionRecord]) -> None:
        populate_db_records_table(self._table, records, self._column_defs)
        self._schedule_table_row_resize()
        self._set_table_placeholder_visible(False)

    def _set_table_placeholder_visible(self, visible: bool) -> None:
        self._table_stack.setCurrentWidget(self._table_placeholder if visible else self._table)

    def _clear_current_table_selection(self) -> None:
        self._table.setRowCount(0)
        self._current_db_records = []
        self._schedule_table_row_resize()
        self._set_table_placeholder_visible(True)

    def _clear_table_and_refresh_tree(self) -> None:
        self._clear_current_table_selection()
        self._refresh_level_tree()

    def _current_db_path(self) -> Path:
        return library_db_path_from_repo_parent_dir_text(self._state.default_repo_parent_dir_text)

    def _set_column_visible(self, column: int, visible: bool) -> None:
        set_column_visible(
            table=self._table,
            column_actions=self._column_actions,
            column_defs=self._column_defs,
            column=column,
            visible=visible,
            last_column_min_width=LAST_COLUMN_MIN_WIDTH,
            schedule_table_row_resize=self._schedule_table_row_resize,
        )

    def _schedule_table_row_resize(self, *_args) -> None:
        self._row_resize_pending = schedule_table_row_resize(
            row_resize_pending=self._row_resize_pending,
            apply_cb=self._apply_table_row_resize,
        )

    def _apply_table_row_resize(self) -> None:
        self._row_resize_pending = False
        self._row_resize_followup_pending = apply_table_row_resize(
            table=self._table,
            row_resize_followup_pending=self._row_resize_followup_pending,
            followup_cb=self._apply_table_row_resize_followup,
        )

    def _apply_table_row_resize_followup(self) -> None:
        self._row_resize_followup_pending = False
        apply_table_row_resize_followup(self._table)

    def _refresh_table_layout_after_column_change(self) -> None:
        refresh_table_layout_after_column_change(
            table=self._table,
            last_column_min_width=LAST_COLUMN_MIN_WIDTH,
            schedule_table_row_resize=self._schedule_table_row_resize,
        )

    def _apply_table_font_size(self) -> None:
        apply_table_font_size(
            table=self._table,
            table_placeholder=self._table_placeholder,
            font_point_size=self._table_font_point_size,
            schedule_table_row_resize=self._schedule_table_row_resize,
        )

    def _adjust_table_font_size(self, step: int) -> None:
        new_size = adjust_table_font_size(
            self._table_font_point_size,
            step,
            min_size=TABLE_FONT_POINT_SIZE_MIN,
            max_size=TABLE_FONT_POINT_SIZE_MAX,
        )
        if new_size == self._table_font_point_size:
            return
        self._table_font_point_size = new_size
        self._apply_table_font_size()
        persist_table_font_point_size(self._table_font_point_size)

    def _on_table_cell_double_clicked(self, row: int, _column: int) -> None:
        if row < 0 or row >= len(self._current_db_records):
            return
        result = edit_question_record(
            parent=self,
            db_path=self._db_path,
            record=self._current_db_records[row],
        )
        if result.action in {"missing", "deleted"}:
            self._clear_current_table_selection()
            self._refresh_level_tree(preferred_level_path=result.preferred_level_path)
            return
        if result.action != "updated" or result.updated_record is None:
            return
        self._current_db_records[row] = result.updated_record
        self._refresh_level_tree(preferred_level_path=result.preferred_level_path)

__all__ = ["WelcomePage"]
