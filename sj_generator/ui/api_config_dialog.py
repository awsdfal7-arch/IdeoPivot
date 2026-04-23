from __future__ import annotations

from typing import Callable

from sj_generator.ai.balance import describe_deepseek_balance, describe_kimi_balance, describe_qwen_balance
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from sj_generator.ai.client import LlmClient
from sj_generator.config import (
    DeepSeekConfig,
    KimiConfig,
    QwenConfig,
    load_deepseek_config,
    load_kimi_config,
    load_qwen_config,
    save_deepseek_config,
    save_kimi_config,
    save_qwen_config,
    set_user_environment_variable,
    to_kimi_llm_config,
    to_llm_config,
    to_qwen_llm_config,
)

BUTTON_MIN_WIDTH = 96
BUTTON_MIN_HEIGHT = 36


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
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("API 配置")
        self.resize(560, 320)

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

        tabs = QTabWidget()
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
        self._model_edit = QComboBox()
        self._model_edit.setEditable(True)
        self._model_edit.addItems(_model_candidates(title))
        self._model_edit.setCurrentText(cfg.model)
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
        form.addRow("Model：", self._model_edit)
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
        self._model_edit.currentTextChanged.connect(self._reset_tested)
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
            model=self._model_edit.currentText().strip(),
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
        if not cfg.base_url or not cfg.model:
            raise _ConfigValidationError(f"{self._title} 的 Base URL 和 Model 不能为空。")
        return cfg

    def _save_env_values(self, cfg) -> None:
        set_user_environment_variable(_api_key_env_name(self._title), cfg.api_key.strip())
        if isinstance(cfg, QwenConfig):
            set_user_environment_variable("QWEN_ACCOUNT_ACCESS_KEY_ID", cfg.account_access_key_id.strip())
            set_user_environment_variable("QWEN_ACCOUNT_ACCESS_KEY_SECRET", cfg.account_access_key_secret.strip())
            # Keep the ali-cloud aliases in sync for current-user usage.
            set_user_environment_variable("ALIBABA_CLOUD_ACCESS_KEY_ID", cfg.account_access_key_id.strip())
            set_user_environment_variable("ALIBABA_CLOUD_ACCESS_KEY_SECRET", cfg.account_access_key_secret.strip())

    def _on_test_api(self) -> None:
        try:
            cfg = self._collect_cfg()
            client = LlmClient(self._to_llm_fn(cfg))
            text = client.chat_text(system="你是连通性测试助手。", user="请只返回 OK")
            if "OK" not in (text or "").upper():
                _show_message_box(
                    self,
                    title="测试失败",
                    text=f"{self._title} API 测试未通过，返回：{text}",
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
        self._status.setText(f"{self._title} API 测试通过。")
        self._balance_label.setText(f"余额：{self._query_balance_text(cfg)}")
        _show_message_box(
            self,
            title="测试通过",
            text=f"{self._title} API 可用性测试通过。",
            icon=QMessageBox.Icon.Information,
        )

    def _cfg_key(self, cfg) -> str:
        parts = [cfg.base_url.strip(), cfg.api_key.strip(), cfg.model.strip()]
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
            "kimi-k2-turbo-preview",
            "moonshot-v1-32k",
            "moonshot-v1-8k",
            "moonshot-v1-128k",
        ]
    if title == "千问":
        return [
            "qwen-max",
            "qwen3.5-plus",
            "qwen-plus",
            "qwen-turbo",
        ]
    return []


def _api_key_env_name(title: str) -> str:
    if title == "DeepSeek":
        return "DEEPSEEK_API_KEY"
    if title == "Kimi":
        return "KIMI_API_KEY"
    return "QWEN_API_KEY"


def _masked_env_status(exists: bool, env_name: str) -> str:
    if exists:
        return f"已从环境变量 {env_name} 读取"
    return f"未设置环境变量 {env_name}"
