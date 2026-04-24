from __future__ import annotations

import json
from typing import TYPE_CHECKING
from typing import Callable

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction
from sj_generator.ai.balance import describe_deepseek_balance, describe_kimi_balance, describe_qwen_balance
from sj_generator.ai.client import LlmConfig
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from sj_generator.ai.client import LlmClient
from sj_generator.config import (
    DeepSeekConfig,
    KimiConfig,
    QwenConfig,
    default_project_parse_model_rows,
    load_deepseek_config,
    load_kimi_config,
    load_project_parse_model_rows,
    load_program_settings,
    load_qwen_config,
    save_deepseek_config,
    save_kimi_config,
    save_program_analysis_target,
    save_project_parse_model_rows,
    save_qwen_config,
    sync_deepseek_runtime_env,
    sync_kimi_runtime_env,
    sync_qwen_runtime_env,
    to_kimi_question_number_llm_config,
    to_kimi_llm_config,
    to_question_number_llm_config,
    to_llm_config,
    to_qwen_question_number_llm_config,
    to_qwen_llm_config,
)
from sj_generator.ui.state import normalize_analysis_model_name, normalize_analysis_provider

if TYPE_CHECKING:
    from sj_generator.ui.state import WizardState

BUTTON_MIN_WIDTH = 96
BUTTON_MIN_HEIGHT = 36
_ANALYSIS_TARGET_CANDIDATES = [
    "DeepSeek / deepseek-reasoner",
    "DeepSeek / deepseek-chat",
    "Kimi / kimi-k2.6",
    "千问 / qwen-max",
]


def _style_dialog_button(button: QPushButton | None, text: str | None = None) -> None:
    if button is None:
        return
    if text:
        button.setText(text)
    button.setMinimumSize(BUTTON_MIN_WIDTH, BUTTON_MIN_HEIGHT)


def _style_message_box_buttons(box: QMessageBox) -> None:
    for button_type, text in (
        (QMessageBox.StandardButton.Ok, "确定"),
        (QMessageBox.StandardButton.Cancel, "取消"),
        (QMessageBox.StandardButton.Yes, "是"),
        (QMessageBox.StandardButton.No, "否"),
    ):
        _style_dialog_button(box.button(button_type), text)


def _show_message_box(
    parent,
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


class ApiConfigDialog(QDialog):
    def __init__(self, parent=None, *, state: WizardState | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("API 配置")
        self.resize(560, 320)
        self._state = state

        self._deepseek_tab = _ApiConfigTab(
            title="DeepSeek",
            cfg=load_deepseek_config(),
            save_fn=save_deepseek_config,
            to_llm_fn=to_llm_config,
            cfg_type=DeepSeekConfig,
        )
        self._kimi_tab = _ApiConfigTab(
            title="Kimi",
            cfg=load_kimi_config(),
            save_fn=save_kimi_config,
            to_llm_fn=to_kimi_llm_config,
            cfg_type=KimiConfig,
        )
        self._qwen_tab = _ApiConfigTab(
            title="千问",
            cfg=load_qwen_config(),
            save_fn=save_qwen_config,
            to_llm_fn=to_qwen_llm_config,
            cfg_type=QwenConfig,
        )
        self._project_tab = _ProjectConfigTab(state=self._state)

        tabs = QTabWidget()
        tabs.addTab(self._project_tab, "项目配置")
        tabs.addTab(self._deepseek_tab, "DeepSeek")
        tabs.addTab(self._kimi_tab, "Kimi")
        tabs.addTab(self._qwen_tab, "千问")

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        _style_dialog_button(buttons.button(QDialogButtonBox.StandardButton.Ok), "确定")
        _style_dialog_button(buttons.button(QDialogButtonBox.StandardButton.Cancel), "取消")

        layout = QVBoxLayout()
        layout.addWidget(tabs)
        layout.addWidget(buttons)
        self.setLayout(layout)

    def _on_accept(self) -> None:
        try:
            self._project_tab.save_if_needed()
            self._deepseek_tab.save_if_needed()
            self._kimi_tab.save_if_needed()
            self._qwen_tab.save_if_needed()
        except _ConfigValidationError as e:
            _show_message_box(self, title="配置未完成", text=str(e), icon=QMessageBox.Icon.Warning)
            return
        except Exception as e:
            _show_message_box(self, title="保存失败", text=str(e), icon=QMessageBox.Icon.Critical)
            return
        self.accept()


class _ConfigValidationError(Exception):
    pass


def _analysis_provider_label(provider: str) -> str:
    labels = {"deepseek": "DeepSeek", "kimi": "Kimi", "qwen": "千问"}
    return labels.get(normalize_analysis_provider(provider), "DeepSeek")


def _analysis_target_text(provider: str, model_name: str) -> str:
    return f"{_analysis_provider_label(provider)} / {normalize_analysis_model_name(model_name)}"


def _parse_analysis_target_text(text: str) -> tuple[str, str]:
    raw = (text or "").strip()
    if not raw:
        return "deepseek", normalize_analysis_model_name("")
    left, sep, right = raw.partition("/")
    if not sep:
        left, sep, right = raw.partition("：")
    if not sep:
        left, sep, right = raw.partition(":")
    if not sep:
        return "deepseek", normalize_analysis_model_name(raw)
    provider_text = left.strip().lower()
    aliases = {
        "deepseek": "deepseek",
        "deep seek": "deepseek",
        "kimi": "kimi",
        "moonshot": "kimi",
        "qwen": "qwen",
        "千问": "qwen",
    }
    provider = aliases.get(provider_text, normalize_analysis_provider(provider_text))
    model_name = normalize_analysis_model_name(right.strip())
    return provider, model_name


def _build_analysis_llm_config(provider: str, model_name: str) -> tuple[str, LlmConfig] | tuple[None, None]:
    provider = normalize_analysis_provider(provider)
    provider_label = _analysis_provider_label(provider)
    if provider == "kimi":
        cfg = load_kimi_config()
        if not cfg.is_ready():
            return None, None
        return provider_label, LlmConfig(
            base_url=cfg.base_url.strip(),
            api_key=cfg.api_key.strip(),
            model=model_name,
            timeout_s=float(cfg.timeout_s),
        )
    if provider == "qwen":
        cfg = load_qwen_config()
        if not cfg.is_ready():
            return None, None
        return provider_label, LlmConfig(
            base_url=cfg.base_url.strip(),
            api_key=cfg.api_key.strip(),
            model=model_name,
            timeout_s=float(cfg.timeout_s),
        )
    cfg = load_deepseek_config()
    if not cfg.is_ready():
        return None, None
    return provider_label, LlmConfig(
        base_url=cfg.base_url.strip(),
        api_key=cfg.api_key.strip(),
        model=model_name,
        timeout_s=float(cfg.timeout_s),
    )


def _project_model_menu_groups() -> list[tuple[str, str, list[str]]]:
    return [
        ("deepseek", "DeepSeek", _model_candidates("DeepSeek")),
        ("kimi", "Kimi", _model_candidates("Kimi")),
        ("qwen", "千问", _model_candidates("千问")),
    ]


class _GroupedModelSelector(QToolButton):
    valueChanged = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._provider = ""
        self._model_name = ""
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.setText("选择模型")
        self.setToolTip("请选择预设模型")
        self._rebuild_menu()

    def current_value(self) -> tuple[str, str]:
        return self._provider, self._model_name

    def set_current_value(self, provider: str, model_name: str) -> None:
        next_provider = normalize_analysis_provider(provider) if str(provider or "").strip() else ""
        next_model_name = str(model_name or "").strip()
        if self._provider == next_provider and self._model_name == next_model_name:
            return
        self._provider = next_provider
        self._model_name = next_model_name
        self._refresh_text()
        self.valueChanged.emit()

    def _rebuild_menu(self) -> None:
        root_menu = QMenu(self)
        clear_action = QAction("清空", self)
        clear_action.triggered.connect(lambda: self.set_current_value("", ""))
        root_menu.addAction(clear_action)
        root_menu.addSeparator()

        for provider_key, provider_label, models in _project_model_menu_groups():
            provider_menu = root_menu.addMenu(provider_label)
            for model_name in models:
                action = QAction(model_name, self)
                action.triggered.connect(
                    lambda _checked=False, p=provider_key, m=model_name: self.set_current_value(p, m)
                )
                provider_menu.addAction(action)

        self.setMenu(root_menu)

    def _refresh_text(self) -> None:
        if self._provider and self._model_name:
            label = _analysis_provider_label(self._provider)
            text = f"{label} / {self._model_name}"
        else:
            text = "选择模型"
        self.setText(text)
        self.setToolTip(text)


class _ProjectConfigTab(QWidget):
    def __init__(self, *, state: WizardState | None) -> None:
        super().__init__()
        self._state = state
        self._parse_model_rows = load_project_parse_model_rows()
        self._parse_round_combos: list[QComboBox] = []
        self._parse_ratio_edits: list[QLineEdit] = []
        data = load_program_settings()
        initial_provider = normalize_analysis_provider(
            data.get("analysis_provider", getattr(state, "analysis_provider", "deepseek"))
        )
        initial_model_name = normalize_analysis_model_name(
            data.get("analysis_model_name", getattr(state, "analysis_model_name", ""))
        )

        self._analysis_target_combo = QComboBox()
        self._analysis_target_combo.setEditable(True)
        self._analysis_target_combo.addItems(_ANALYSIS_TARGET_CANDIDATES)
        self._analysis_target_combo.setCurrentText(_analysis_target_text(initial_provider, initial_model_name))
        self._analysis_test_btn = QPushButton("测试模型")
        self._analysis_test_btn.setMinimumSize(BUTTON_MIN_WIDTH, BUTTON_MIN_HEIGHT)
        self._analysis_test_btn.clicked.connect(self._on_test_analysis_target)
        self._status = QLabel("未测试")
        self._status.setWordWrap(True)
        self._tested_key = self._project_config_key(initial_provider, initial_model_name, self._parse_model_rows)
        if self._tested_key:
            self._status.setText("当前已加载解析生成模型配置。")
        self._parse_result_table = self._build_parse_result_table()
        self._refresh_parse_result_model_columns()

        form = QFormLayout()
        form.addRow("解析生成模型：", self._analysis_target_combo)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(QLabel("解析结果阈值预留"))
        layout.addWidget(self._parse_result_table)
        layout.addWidget(self._status)
        layout.addWidget(self._analysis_test_btn)
        layout.addStretch(1)
        self.setLayout(layout)

        self._analysis_target_combo.currentTextChanged.connect(self._reset_tested)

    def save_if_needed(self) -> None:
        provider, model_name = self._current_analysis_target()
        parse_model_rows = self._collect_parse_model_rows()
        if self._project_config_key(provider, model_name, parse_model_rows) != self._tested_key:
            raise _ConfigValidationError("项目配置已修改，请先点击“测试模型”并通过。")
        save_program_analysis_target(
            provider=normalize_analysis_provider(provider),
            model_name=normalize_analysis_model_name(model_name),
        )
        self._parse_model_rows = save_project_parse_model_rows(parse_model_rows)["project_parse_model_rows"]
        if self._state is not None:
            self._state.analysis_provider = normalize_analysis_provider(provider)
            self._state.analysis_model_name = normalize_analysis_model_name(model_name)

    def _current_analysis_target(self) -> tuple[str, str]:
        return _parse_analysis_target_text(self._analysis_target_combo.currentText())

    def _analysis_target_key(self, provider: str, model_name: str) -> str:
        return f"{normalize_analysis_provider(provider)}|{normalize_analysis_model_name(model_name)}"

    def _project_config_key(self, provider: str, model_name: str, parse_model_rows: list[dict]) -> str:
        payload = {
            "analysis_target": self._analysis_target_key(provider, model_name),
            "parse_model_rows": parse_model_rows,
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    def _reset_tested(self, *_args) -> None:
        self._tested_key = ""
        self._status.setText("项目配置已变更，需重新测试。")

    def _on_test_analysis_target(self) -> None:
        provider, model_name = self._current_analysis_target()
        parse_model_rows = self._collect_parse_model_rows()
        models_to_test = self._project_models_to_test(provider, model_name, parse_model_rows)
        try:
            for current_provider, current_model_name in models_to_test:
                provider_label, llm_config = _build_analysis_llm_config(current_provider, current_model_name)
                if provider_label is None or llm_config is None:
                    provider_label = _analysis_provider_label(current_provider)
                    _show_message_box(
                        self,
                        title="未配置",
                        text=f"请先完成 {provider_label} 的 API 配置。",
                        icon=QMessageBox.Icon.Warning,
                    )
                    self._status.setText("最近一次测试失败。")
                    return
                client = LlmClient(llm_config)
                text = client.chat_text(system="你是连通性测试助手。", user="请只返回 OK")
                if "OK" not in (text or "").upper():
                    raise RuntimeError(f"{provider_label} / {current_model_name} 测试未通过，返回：{text}")
        except Exception as e:
            self._status.setText("最近一次测试失败。")
            _show_message_box(self, title="测试失败", text=str(e), icon=QMessageBox.Icon.Critical)
            return
        provider, normalized_model = _parse_analysis_target_text(f"{_analysis_provider_label(provider)} / {model_name}")
        self._analysis_target_combo.setCurrentText(_analysis_target_text(provider, normalized_model))
        self._tested_key = self._project_config_key(provider, normalized_model, parse_model_rows)
        self._status.setText("项目配置模型测试通过。")
        _show_message_box(
            self,
            title="测试通过",
            text="当前项目配置中的模型可正常使用。",
            icon=QMessageBox.Icon.Information,
        )

    def _build_parse_result_table(self) -> QTableWidget:
        table = QTableWidget(2, 6, self)
        table.setVerticalHeaderLabels(["序号题型解析", "题目内容解析"])
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.setMinimumHeight(120)
        self._parse_round_combos = []
        self._parse_ratio_edits = []

        for row in range(table.rowCount()):
            row_cfg = self._parse_model_row(row)
            combo = QComboBox(table)
            combo.addItems(["1", "2", "3", "4", "5"])
            combo.setCurrentText(str(row_cfg.get("round") or (row + 1)))
            combo.currentTextChanged.connect(self._reset_tested)
            table.setCellWidget(row, 0, combo)
            self._parse_round_combos.append(combo)

            ratio_edit = QLineEdit(table)
            ratio_edit.setPlaceholderText("例如 2/4")
            ratio_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ratio_edit.setText(str(row_cfg.get("ratio") or "1/4"))
            ratio_edit.textChanged.connect(self._refresh_parse_result_model_columns)
            ratio_edit.textChanged.connect(self._reset_tested)
            table.setCellWidget(row, 1, ratio_edit)
            self._parse_ratio_edits.append(ratio_edit)

        return table

    def _refresh_parse_result_model_columns(self, *_args) -> None:
        table = self._parse_result_table
        model_count = self._parse_result_model_count()
        table.setColumnCount(2 + model_count)
        table.setHorizontalHeaderLabels(
            ["轮次", "通过比例"] + [f"模型{i}" for i in range(1, model_count + 1)]
        )
        for row in range(table.rowCount()):
            for col in range(2, table.columnCount()):
                if not isinstance(table.cellWidget(row, col), _GroupedModelSelector):
                    selector = _GroupedModelSelector(table)
                    provider, model_name = self._parse_model_value(row, col - 2)
                    if provider and model_name:
                        selector.set_current_value(provider, model_name)
                    selector.valueChanged.connect(self._reset_tested)
                    table.setCellWidget(row, col, selector)

    def _parse_result_model_count(self) -> int:
        counts = [self._model_count_from_ratio(edit.text()) for edit in self._parse_ratio_edits]
        return max([1, *counts])

    def _model_count_from_ratio(self, text: str) -> int:
        raw = (text or "").strip()
        if "/" not in raw:
            return 1
        _numerator, _sep, denominator_text = raw.partition("/")
        try:
            denominator = int(denominator_text.strip())
        except Exception:
            return 1
        return min(8, max(1, denominator))

    def _parse_model_row(self, row_index: int) -> dict:
        defaults = default_project_parse_model_rows()
        if 0 <= row_index < len(self._parse_model_rows):
            return self._parse_model_rows[row_index]
        return defaults[row_index]

    def _parse_model_value(self, row_index: int, model_index: int) -> tuple[str, str]:
        row_cfg = self._parse_model_row(row_index)
        models = row_cfg.get("models") or []
        if 0 <= model_index < len(models):
            item = models[model_index]
            return str(item.get("provider") or "").strip(), str(item.get("model_name") or "").strip()
        return "", ""

    def _collect_parse_model_rows(self) -> list[dict]:
        rows: list[dict] = []
        row_keys = [row["key"] for row in default_project_parse_model_rows()]
        table = self._parse_result_table
        for row_index, row_key in enumerate(row_keys):
            combo = self._parse_round_combos[row_index]
            ratio_edit = self._parse_ratio_edits[row_index]
            visible_count = self._model_count_from_ratio(ratio_edit.text())
            models: list[dict] = []
            for model_index in range(visible_count):
                selector = table.cellWidget(row_index, 2 + model_index)
                if not isinstance(selector, _GroupedModelSelector):
                    continue
                provider, model_name = selector.current_value()
                if not provider or not model_name:
                    continue
                models.append({"provider": provider, "model_name": model_name})
            rows.append(
                {
                    "key": row_key,
                    "round": combo.currentText().strip() or "1",
                    "ratio": ratio_edit.text().strip() or "1/4",
                    "models": models,
                }
            )
        return rows

    def _project_models_to_test(
        self,
        analysis_provider: str,
        analysis_model_name: str,
        parse_model_rows: list[dict],
    ) -> list[tuple[str, str]]:
        pairs: list[tuple[str, str]] = []
        seen: set[str] = set()

        def add(provider: str, model_name: str) -> None:
            normalized_provider = normalize_analysis_provider(provider)
            normalized_model = str(model_name or "").strip()
            if not normalized_provider or not normalized_model:
                return
            key = f"{normalized_provider}|{normalized_model}"
            if key in seen:
                return
            seen.add(key)
            pairs.append((normalized_provider, normalized_model))

        add(analysis_provider, analysis_model_name)
        for row in parse_model_rows:
            for item in row.get("models") or []:
                add(str(item.get("provider") or ""), str(item.get("model_name") or ""))
        return pairs


class _ApiConfigTab(QWidget):
    def __init__(
        self,
        *,
        title: str,
        cfg,
        save_fn: Callable[[object], None],
        to_llm_fn: Callable[[object], object],
        cfg_type,
    ) -> None:
        super().__init__()
        self._title = title
        self._cfg = cfg
        self._save_fn = save_fn
        self._to_llm_fn = to_llm_fn
        self._cfg_type = cfg_type
        self._env_api_key = cfg.api_key.strip()
        self._env_account_access_key_id = getattr(cfg, "account_access_key_id", "").strip()
        self._env_account_access_key_secret = getattr(cfg, "account_access_key_secret", "").strip()

        self._base_url_edit = QLineEdit(cfg.base_url)
        self._api_key_edit = QLineEdit(self._env_api_key)
        self._api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key_edit.setPlaceholderText("请输入 API Key")
        self._account_access_key_id_edit: QLineEdit | None = None
        self._account_access_key_secret_edit: QLineEdit | None = None
        if isinstance(cfg, QwenConfig):
            self._account_access_key_id_edit = QLineEdit(self._env_account_access_key_id)
            self._account_access_key_id_edit.setPlaceholderText("请输入阿里云 AccessKey ID（非必填）")
            self._account_access_key_secret_edit = QLineEdit(self._env_account_access_key_secret)
            self._account_access_key_secret_edit.setEchoMode(QLineEdit.EchoMode.Password)
            self._account_access_key_secret_edit.setPlaceholderText("请输入阿里云 AccessKey Secret（非必填）")
        self._timeout_edit = QLineEdit(str(cfg.timeout_s))
        self._save_checkbox = QCheckBox("保存到本机配置")
        self._save_checkbox.setChecked(True)
        self._test_btn = QPushButton("测试 API")
        self._test_btn.setMinimumSize(BUTTON_MIN_WIDTH, BUTTON_MIN_HEIGHT)
        self._test_btn.clicked.connect(self._on_test_api)
        self._balance_label = QLabel(self._initial_balance_text(cfg))
        self._balance_label.setWordWrap(True)
        self._status = QLabel("未测试")
        self._status.setWordWrap(True)
        self._tested_key = self._cfg_key(cfg) if getattr(cfg, "is_ready", lambda: False)() else ""

        form = QFormLayout()
        form.addRow("Base URL：", self._base_url_edit)
        form.addRow("API Key：", self._api_key_edit)
        if self._account_access_key_id_edit is not None and self._account_access_key_secret_edit is not None:
            form.addRow("阿里云 AccessKey ID：", self._account_access_key_id_edit)
            form.addRow("阿里云 AccessKey Secret：", self._account_access_key_secret_edit)
        form.addRow("超时(秒)：", self._timeout_edit)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(self._test_btn)
        layout.addWidget(self._balance_label)
        layout.addWidget(self._save_checkbox)
        layout.addWidget(self._status)
        layout.addStretch(1)
        self.setLayout(layout)

        self._base_url_edit.textChanged.connect(self._reset_tested)
        self._api_key_edit.textChanged.connect(self._reset_tested)
        self._timeout_edit.textChanged.connect(self._reset_tested)
        if self._account_access_key_id_edit is not None:
            self._account_access_key_id_edit.textChanged.connect(self._reset_tested)
        if self._account_access_key_secret_edit is not None:
            self._account_access_key_secret_edit.textChanged.connect(self._reset_tested)

        if self._tested_key:
            self._status.setText("当前已加载可用配置。")

    def save_if_needed(self) -> None:
        cfg = self._collect_cfg()
        cfg_key = self._cfg_key(cfg)
        if cfg.is_ready() and cfg_key != self._tested_key:
            raise _ConfigValidationError(f"{self._title} 配置已修改，请先点击“测试 API”并通过。")
        self._cfg = cfg
        self._save_env_values(cfg)
        if self._save_checkbox.isChecked():
            self._save_fn(cfg)

    def _collect_cfg(self):
        try:
            timeout_s = float(self._timeout_edit.text().strip() or "0")
        except Exception as e:
            raise _ConfigValidationError(f"{self._title} 的超时(秒)需要是数字。") from e
        if timeout_s <= 0:
            raise _ConfigValidationError(f"{self._title} 的超时(秒)必须大于 0。")
        kwargs = dict(
            base_url=self._base_url_edit.text().strip(),
            api_key=self._api_key_edit.text().strip(),
            number_model=getattr(self._cfg, "number_model", "").strip(),
            model=self._cfg.model.strip(),
            timeout_s=timeout_s,
        )
        if isinstance(self._cfg, QwenConfig):
            kwargs["account_access_key_id"] = (
                self._account_access_key_id_edit.text().strip() if self._account_access_key_id_edit else ""
            )
            kwargs["account_access_key_secret"] = (
                self._account_access_key_secret_edit.text().strip() if self._account_access_key_secret_edit else ""
            )
        if isinstance(self._cfg, DeepSeekConfig):
            kwargs["analysis_model"] = self._cfg.analysis_model.strip()
        cfg = self._cfg_type(**kwargs)
        if not cfg.base_url or not cfg.number_model or not cfg.model:
            raise _ConfigValidationError(f"{self._title} 的 Base URL 不能为空，项目配置中的模型选择也不能为空。")
        return cfg

    def _save_env_values(self, cfg) -> None:
        if isinstance(cfg, DeepSeekConfig):
            sync_deepseek_runtime_env(cfg)
            return
        if isinstance(cfg, KimiConfig):
            sync_kimi_runtime_env(cfg)
            return
        if isinstance(cfg, QwenConfig):
            sync_qwen_runtime_env(cfg)

    def _on_test_api(self) -> None:
        try:
            cfg = self._collect_cfg()
            number_client = LlmClient(_number_llm_config_for_cfg(cfg))
            number_text = number_client.chat_text(system="你是连通性测试助手。", user="请只返回 OK")
            if "OK" not in (number_text or "").upper():
                _show_message_box(
                    self,
                    title="测试失败",
                    text=f"{self._title} 的项目配置模型测试未通过，返回：{number_text}",
                    icon=QMessageBox.Icon.Warning,
                )
                self._status.setText("最近一次测试失败。")
                self._balance_label.setText(self._initial_balance_text(cfg))
                return
            unit_client = LlmClient(self._to_llm_fn(cfg))
            unit_text = unit_client.chat_text(system="你是连通性测试助手。", user="请只返回 OK")
            if "OK" not in (unit_text or "").upper():
                _show_message_box(
                    self,
                    title="测试失败",
                    text=f"{self._title} 的项目配置模型测试未通过，返回：{unit_text}",
                    icon=QMessageBox.Icon.Warning,
                )
                self._status.setText("最近一次测试失败。")
                self._balance_label.setText(self._initial_balance_text(cfg))
                return
        except _ConfigValidationError as e:
            _show_message_box(self, title="参数不合法", text=str(e), icon=QMessageBox.Icon.Warning)
            return
        except Exception as e:
            _show_message_box(
                self,
                title="测试失败",
                text=f"{self._title} API 测试失败：{e}",
                icon=QMessageBox.Icon.Critical,
            )
            self._status.setText("最近一次测试失败。")
            self._balance_label.setText(self._initial_balance_text(cfg) if "cfg" in locals() else "余额：未查询")
            return
        self._tested_key = self._cfg_key(cfg)
        self._status.setText(f"{self._title} 的 API 连通性测试通过。")
        self._balance_label.setText(f"余额：{self._query_balance_text(cfg)}")
        _show_message_box(
            self,
            title="测试通过",
            text=f"{self._title} API 可用性测试通过。",
            icon=QMessageBox.Icon.Information,
        )

    def _cfg_key(self, cfg) -> str:
        parts = [cfg.base_url.strip(), cfg.api_key.strip(), getattr(cfg, "number_model", "").strip(), cfg.model.strip()]
        if hasattr(cfg, "analysis_model"):
            parts.append(getattr(cfg, "analysis_model").strip())
        parts.append(str(float(cfg.timeout_s)))
        return "|".join(parts)

    def _reset_tested(self, *_args) -> None:
        self._tested_key = ""
        self._status.setText("配置已变更，需重新测试。")
        try:
            cfg = self._collect_cfg()
        except Exception:
            self._balance_label.setText("余额：未查询")
            return
        self._balance_label.setText(self._initial_balance_text(cfg))

    def _initial_balance_text(self, cfg) -> str:
        if isinstance(cfg, QwenConfig):
            if cfg.has_account_balance_credentials():
                return "余额：待查询"
            if cfg.is_ready():
                return "余额：未配置阿里云 AccessKey，暂无法查询"
            return "余额：未配置"
        if cfg.is_ready():
            return "余额：待查询"
        return "余额：未配置"

    def _query_balance_text(self, cfg) -> str:
        try:
            if isinstance(cfg, DeepSeekConfig):
                return describe_deepseek_balance(cfg)
            if isinstance(cfg, KimiConfig):
                return describe_kimi_balance(cfg)
            if isinstance(cfg, QwenConfig):
                return describe_qwen_balance(cfg)
        except Exception as e:
            return f"查询失败：{e}"
        return "未配置"


def _model_candidates(title: str) -> list[str]:
    if title == "DeepSeek":
        return [
            "deepseek-chat",
            "deepseek-reasoner",
        ]
    if title == "Kimi":
        return [
            "kimi-k2.6",
            "kimi-k2.5",
            "kimi-k2-thinking",
            "kimi-k2-thinking-turbo",
            "kimi-k2-0905-preview",
            "kimi-k2-0711-preview",
            "kimi-k2-turbo-preview",
            "moonshot-v1-32k",
            "moonshot-v1-8k",
            "moonshot-v1-128k",
        ]
    if title == "千问":
        return [
            "qwen-max",
            "qwen-max-latest",
            "qwen3.5-plus",
            "qwen-plus",
            "qwen-turbo",
            "qwen-long",
            "qwen-deep-research",
            "qwen-ocr",
            "gui-plus",
        ]
    return []


def _number_llm_config_for_cfg(cfg):
    if isinstance(cfg, DeepSeekConfig):
        return to_question_number_llm_config(cfg)
    if isinstance(cfg, KimiConfig):
        return to_kimi_question_number_llm_config(cfg)
    return to_qwen_question_number_llm_config(cfg)


def _masked_env_status(exists: bool, env_name: str) -> str:
    if exists:
        return f"已从环境变量 {env_name} 读取"
    return f"未设置环境变量 {env_name}"
