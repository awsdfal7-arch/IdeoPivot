from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenuBar, QWidget


@dataclass
class WelcomeMenuBundle:
    menu_bar: QMenuBar
    column_actions: dict[int, QAction]
    doc_import_action: QAction
    table_import_action: QAction
    export_md_action: QAction
    export_pdf_action: QAction
    export_current_level_xlsx_action: QAction
    export_db_table_xlsx_action: QAction
    add_question_action: QAction
    general_settings_action: QAction
    import_settings_action: QAction
    export_settings_action: QAction
    api_settings_action: QAction


def build_welcome_menu_bar(
    *,
    parent: QWidget,
    column_defs: list[tuple[str, str, bool]],
    column_visibility: dict[str, bool],
    on_doc_import,
    on_table_import,
    on_export_markdown,
    on_export_pdf,
    on_export_current_xlsx,
    on_export_db_xlsx,
    on_add_question,
    on_open_general_settings,
    on_open_import_settings,
    on_open_export_settings,
    on_open_api_config,
    on_toggle_column,
) -> WelcomeMenuBundle:
    menu_bar = QMenuBar(parent)
    file_menu = menu_bar.addMenu("文件")
    import_menu = file_menu.addMenu("导入")
    doc_import_action = import_menu.addAction("从文档文件解析导入")
    doc_import_action.triggered.connect(on_doc_import)
    table_import_action = import_menu.addAction("从表格文件直接导入")
    table_import_action.triggered.connect(on_table_import)

    export_menu = file_menu.addMenu("导出")
    export_md_action = export_menu.addAction("导出当前页面为 Markdown")
    export_md_action.triggered.connect(on_export_markdown)
    export_pdf_action = export_menu.addAction("导出当前页面为 PDF")
    export_pdf_action.triggered.connect(on_export_pdf)
    export_xlsx_menu = export_menu.addMenu("导出为 xlsx")
    export_current_level_xlsx_action = export_xlsx_menu.addAction("当前页面题目")
    export_current_level_xlsx_action.triggered.connect(on_export_current_xlsx)
    export_db_table_xlsx_action = export_xlsx_menu.addAction("所有题目")
    export_db_table_xlsx_action.triggered.connect(on_export_db_xlsx)

    edit_menu = menu_bar.addMenu("编辑")
    add_question_action = edit_menu.addAction("新增题目")
    add_question_action.triggered.connect(on_add_question)

    view_menu = menu_bar.addMenu("视图")
    column_menu = view_menu.addMenu("表格列显示")
    column_actions: dict[int, QAction] = {}
    for idx, (key, title, _visible) in enumerate(column_defs):
        visible = column_visibility.get(key, False)
        action = column_menu.addAction(title)
        action.setCheckable(True)
        action.setChecked(visible)
        action.toggled.connect(lambda checked, col=idx: on_toggle_column(col, checked))
        column_actions[idx] = action

    settings_menu = menu_bar.addMenu("设置")
    general_settings_action = settings_menu.addAction("常规设定")
    general_settings_action.triggered.connect(on_open_general_settings)
    import_settings_action = settings_menu.addAction("导入设定")
    import_settings_action.triggered.connect(on_open_import_settings)
    export_settings_action = settings_menu.addAction("导出设定")
    export_settings_action.triggered.connect(on_open_export_settings)
    api_settings_action = settings_menu.addAction("API 配置")
    api_settings_action.triggered.connect(on_open_api_config)

    return WelcomeMenuBundle(
        menu_bar=menu_bar,
        column_actions=column_actions,
        doc_import_action=doc_import_action,
        table_import_action=table_import_action,
        export_md_action=export_md_action,
        export_pdf_action=export_pdf_action,
        export_current_level_xlsx_action=export_current_level_xlsx_action,
        export_db_table_xlsx_action=export_db_table_xlsx_action,
        add_question_action=add_question_action,
        general_settings_action=general_settings_action,
        import_settings_action=import_settings_action,
        export_settings_action=export_settings_action,
        api_settings_action=api_settings_action,
    )
