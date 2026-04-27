from __future__ import annotations

import json
from decimal import Decimal
from typing import TYPE_CHECKING
from typing import Callable

from PyQt6.QtCore import QObject, QThread, Qt, pyqtSignal
from PyQt6.QtGui import QAction
from sj_generator.infrastructure.llm.balance import (
    describe_deepseek_balance,
    describe_kimi_balance,
    describe_qwen_balance,
    query_deepseek_balance_snapshot,
    query_kimi_balance_snapshot,
    query_qwen_balance_snapshot,
)
from sj_generator.infrastructure.llm.client import LlmConfig
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from sj_generator.infrastructure.llm.client import LlmClient
from sj_generator.application.settings import (
    DeepSeekConfig,
    KimiConfig,
    QwenConfig,
    default_project_parse_model_rows,
    load_available_models,
    load_deepseek_config,
    load_kimi_config,
    load_project_parse_model_rows,
    load_program_settings,
    load_qwen_config,
    save_deepseek_config,
    save_kimi_config,
    save_available_models,
    save_program_analysis_target,
    save_program_settings_merged,
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
    with_capped_timeout,
)
from sj_generator.application.settings.import_cost_history import append_balance_history_for_provider_results
from sj_generator.application.state import (
    AI_CONCURRENCY_OPTIONS,
    normalize_ai_concurrency,
    normalize_analysis_model_name,
    normalize_analysis_provider,
)
from sj_generator.infrastructure.llm.task_runner import run_callables_in_parallel_fail_fast
from sj_generator.presentation.qt.import_cost_history_dialog import ImportCostHistoryDialog
from sj_generator.presentation.qt.table_copy import CopyableTableWidget

if TYPE_CHECKING:
    from sj_generator.application.state import WizardState

BUTTON_MIN_WIDTH = 96
BUTTON_MIN_HEIGHT = 36
FAST_TEST_TIMEOUT_S = 12.0
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
        self._deepseek_tab.modelListChanged.connect(self._project_tab.refresh_model_candidates)
        self._kimi_tab.modelListChanged.connect(self._project_tab.refresh_model_candidates)
        self._qwen_tab.modelListChanged.connect(self._project_tab.refresh_model_candidates)
        self._test_thread: QThread | None = None
        self._test_worker: _AsyncCallWorker | None = None
        self._testing_api_keys: list[str] = []
        self._testing_project = False

        tabs = QTabWidget()
        tabs.addTab(self._project_tab, "项目配置")
        tabs.addTab(self._deepseek_tab, "DeepSeek")
        tabs.addTab(self._kimi_tab, "Kimi")
        tabs.addTab(self._qwen_tab, "千问")

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self._test_all_btn = QPushButton("统一测试")
        self._view_cost_history_btn = QPushButton("查看余额日志")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        self._test_all_btn.clicked.connect(self._on_test_all)
        self._view_cost_history_btn.clicked.connect(self._open_import_cost_history_dialog)
        _style_dialog_button(self._test_all_btn, "统一测试")
        _style_dialog_button(self._view_cost_history_btn, "查看余额日志")
        _style_dialog_button(buttons.button(QDialogButtonBox.StandardButton.Ok), "确定")
        _style_dialog_button(buttons.button(QDialogButtonBox.StandardButton.Cancel), "取消")

        layout = QVBoxLayout()
        layout.addWidget(tabs)
        button_row = QHBoxLayout()
        button_row.addWidget(self._view_cost_history_btn)
        button_row.addStretch(1)
        button_row.addWidget(self._test_all_btn)
        button_row.addWidget(buttons)
        layout.addLayout(button_row)
        self.setLayout(layout)

    def _on_accept(self) -> None:
        if self._is_testing():
            _show_message_box(self, title="测试进行中", text="模型测试仍在进行中，请等待完成后再保存。", icon=QMessageBox.Icon.Warning)
            return
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

    def reject(self) -> None:
        if self._is_testing():
            _show_message_box(self, title="测试进行中", text="模型测试仍在进行中，请等待完成后再关闭。", icon=QMessageBox.Icon.Warning)
            return
        super().reject()

    def _is_testing(self) -> bool:
        return (
            (self._test_thread is not None and self._test_thread.isRunning())
            or self._project_tab.is_testing()
            or self._deepseek_tab.is_testing()
            or self._kimi_tab.is_testing()
            or self._qwen_tab.is_testing()
        )

    def _on_test_all(self) -> None:
        if self._is_testing():
            _show_message_box(self, title="测试进行中", text="模型测试仍在进行中，请等待完成。", icon=QMessageBox.Icon.Warning)
            return
        try:
            api_targets: list[tuple[_ApiConfigTab, object]] = []
            api_tabs_with_cfgs: list[tuple[_ApiConfigTab, object]] = []
            override_cfgs: dict[str, object] = {}
            for tab in (self._deepseek_tab, self._kimi_tab, self._qwen_tab):
                cfg = tab.collect_cfg_for_test()
                api_tabs_with_cfgs.append((tab, cfg))
                override_cfgs[tab.provider_key()] = cfg
                if tab.needs_test(cfg):
                    api_targets.append((tab, cfg))
            project_payload = self._project_tab.collect_test_payload()
            project_needs_test = self._project_tab.needs_test(project_payload)
        except _ConfigValidationError as e:
            _show_message_box(self, title="参数不合法", text=str(e), icon=QMessageBox.Icon.Warning)
            return

        for tab, _cfg in api_tabs_with_cfgs:
            tab.set_balance_querying()
        for tab, _cfg in api_targets:
            tab.set_status_text(f"正在统一测试 {tab.title_text()} API，请稍候…")
        if project_needs_test:
            self._project_tab.set_status_text("正在统一测试项目配置模型，请稍候…")
        self._testing_api_keys = [tab.provider_key() for tab, _cfg in api_targets]
        self._testing_project = project_needs_test
        self._test_all_btn.setEnabled(False)

        def run_all() -> dict[str, object]:
            api_results: list[tuple[str, dict[str, object]]] = []
            api_test_provider_keys = {tab.provider_key() for tab, _cfg in api_targets}
            for tab, cfg in api_tabs_with_cfgs:
                if tab.provider_key() in api_test_provider_keys:
                    result = _run_api_connectivity_test(tab.title_text(), cfg, tab.to_llm_fn())
                else:
                    result = _run_api_balance_refresh(cfg)
                api_results.append(
                    (
                        tab.provider_key(),
                        result,
                    )
                )
            project_result = None
            if project_needs_test:
                project_result = _run_project_model_test(
                    provider=str(project_payload["provider"]),
                    model_name=str(project_payload["model_name"]),
                    parse_model_rows=list(project_payload["parse_model_rows"]),
                    override_cfgs=override_cfgs,
                )
            return {
                "api_results": api_results,
                "project_result": project_result,
                "api_keys": list(self._testing_api_keys),
                "project_tested": self._testing_project,
            }

        thread = QThread(self)
        worker = _AsyncCallWorker(run_all)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_test_all_success)
        worker.failed.connect(self._on_test_all_error)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_test_all_finished)
        self._test_thread = thread
        self._test_worker = worker
        thread.start()

    def _on_test_all_success(self, payload: object) -> None:
        data = payload if isinstance(payload, dict) else {}
        provider_map = {
            "deepseek": self._deepseek_tab,
            "kimi": self._kimi_tab,
            "qwen": self._qwen_tab,
        }
        tested_labels: list[str] = []
        for provider_key, result in data.get("api_results") or []:
            tab = provider_map.get(str(provider_key))
            if tab is None:
                continue
            if bool((result or {}).get("connectivity_tested")):
                tab.apply_test_success(result, show_message=False)
                tested_labels.append(f"{tab.title_text()} API")
            else:
                tab.apply_balance_refresh(result)
        if data.get("project_tested"):
            self._project_tab.apply_test_success(data.get("project_result"), show_message=False)
            tested_labels.append("项目配置模型")
        append_balance_history_for_provider_results(data.get("api_results") or [], source_label="统一测试")
        if tested_labels:
            summary = "、".join(tested_labels)
            message = f"{summary} 测试通过，余额已刷新。"
        else:
            message = "余额已刷新，当前没有需要重测的配置。"
        _show_message_box(self, title="测试通过", text=message, icon=QMessageBox.Icon.Information)

    def _on_test_all_error(self, message: str) -> None:
        provider_map = {
            "deepseek": self._deepseek_tab,
            "kimi": self._kimi_tab,
            "qwen": self._qwen_tab,
        }
        for provider_key in self._testing_api_keys:
            tab = provider_map.get(provider_key)
            if tab is not None:
                tab.reset_runtime_status_after_failure()
        if self._testing_project:
            self._project_tab.reset_runtime_status_after_failure()
        _show_message_box(self, title="测试失败", text=message, icon=QMessageBox.Icon.Critical)

    def _on_test_all_finished(self) -> None:
        self._test_all_btn.setEnabled(True)
        self._test_thread = None
        self._test_worker = None
        self._testing_api_keys = []
        self._testing_project = False

    def _open_import_cost_history_dialog(self) -> None:
        ImportCostHistoryDialog(self).exec()


class _ConfigValidationError(Exception):
    pass


class _AsyncCallWorker(QObject):
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, fn: Callable[[], object]) -> None:
        super().__init__()
        self._fn = fn

    def run(self) -> None:
        try:
            self.finished.emit(self._fn())
        except Exception as e:
            self.failed.emit(str(e))


def _analysis_provider_label(provider: str) -> str:
    labels = {"deepseek": "DeepSeek", "kimi": "Kimi", "qwen": "千问"}
    return labels.get(normalize_analysis_provider(provider), "DeepSeek")


def _analysis_target_text(provider: str, model_name: str) -> str:
    return f"{_analysis_provider_label(provider)} / {normalize_analysis_model_name(model_name)}"


def _analysis_target_candidates() -> list[str]:
    candidates: list[str] = []
    for provider_key, provider_label, models in _project_model_menu_groups():
        if not models:
            continue
        for model_name in models:
            candidates.append(f"{provider_label} / {model_name}")
    return candidates


def _provider_key_from_title(title: str) -> str:
    mapping = {
        "DeepSeek": "deepseek",
        "Kimi": "kimi",
        "千问": "qwen",
    }
    return mapping.get(str(title or "").strip(), "deepseek")


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


def _to_fast_test_llm_config(cfg: LlmConfig) -> LlmConfig:
    return LlmConfig(
        base_url=cfg.base_url,
        api_key=cfg.api_key,
        model=cfg.model,
        timeout_s=min(float(cfg.timeout_s), FAST_TEST_TIMEOUT_S),
        max_retries=0,
        retry_backoff_s=0.0,
    )


def _query_balance_text_for_cfg(cfg) -> str:
    return _query_balance_result_for_cfg(cfg)["balance_text"]


def _format_balance_amount(currency: str, amount: Decimal) -> str:
    prefix = {"CNY": "¥", "USD": "$"}.get((currency or "").upper(), "")
    if prefix:
        return f"{prefix}{amount:.4f}"
    return f"{(currency or 'UNKNOWN').upper()} {amount:.4f}"


def _query_balance_result_for_cfg(cfg) -> dict[str, str]:
    cfg = with_capped_timeout(cfg, FAST_TEST_TIMEOUT_S)
    try:
        if isinstance(cfg, DeepSeekConfig):
            if not cfg.is_ready():
                return {"balance_text": "未配置", "balance_value": ""}
            snapshot = query_deepseek_balance_snapshot(cfg)
            if snapshot is None:
                return {"balance_text": "未配置", "balance_value": ""}
            return {
                "balance_text": snapshot.detail,
                "balance_value": _format_balance_amount(snapshot.currency, Decimal(str(snapshot.amount))),
            }
        if isinstance(cfg, KimiConfig):
            if not cfg.is_ready():
                return {"balance_text": "未配置", "balance_value": ""}
            snapshot = query_kimi_balance_snapshot(cfg)
            if snapshot is None:
                return {"balance_text": describe_kimi_balance(cfg), "balance_value": ""}
            return {
                "balance_text": snapshot.detail,
                "balance_value": _format_balance_amount(snapshot.currency, Decimal(str(snapshot.amount))),
            }
        if isinstance(cfg, QwenConfig):
            if not cfg.is_ready() and not cfg.has_account_balance_credentials():
                return {"balance_text": "未配置", "balance_value": ""}
            snapshot = query_qwen_balance_snapshot(cfg)
            if snapshot is None:
                return {"balance_text": describe_qwen_balance(cfg), "balance_value": ""}
            return {
                "balance_text": snapshot.detail,
                "balance_value": _format_balance_amount(snapshot.currency, Decimal(str(snapshot.amount))),
            }
    except Exception as e:
        return {"balance_text": f"查询失败：{e}", "balance_value": ""}
    return {"balance_text": "未配置", "balance_value": ""}


def _run_api_connectivity_test(title: str, cfg, to_llm_fn: Callable[[object], object]) -> dict[str, object]:
    number_cfg = _to_fast_test_llm_config(_number_llm_config_for_cfg(cfg))
    unit_cfg = _to_fast_test_llm_config(to_llm_fn(cfg))
    config_map = {
        f"{number_cfg.base_url}|{number_cfg.model}": number_cfg,
        f"{unit_cfg.base_url}|{unit_cfg.model}": unit_cfg,
    }

    def check_one(llm_cfg: LlmConfig) -> None:
        text = LlmClient(llm_cfg).chat_text(system="你是连通性测试助手。", user="请只返回 OK")
        if "OK" not in (text or "").upper():
            raise RuntimeError(f"{title} API 测试未通过，返回：{text}")

    run_callables_in_parallel_fail_fast(
        callables=[lambda llm_cfg=llm_cfg: check_one(llm_cfg) for llm_cfg in config_map.values()],
        max_workers=min(2, len(config_map)),
    )
    balance_result = _query_balance_result_for_cfg(cfg)
    return {
        "cfg": cfg,
        "balance_text": balance_result["balance_text"],
        "balance_value": balance_result["balance_value"],
        "connectivity_tested": True,
    }


def _run_api_balance_refresh(cfg) -> dict[str, object]:
    balance_result = _query_balance_result_for_cfg(cfg)
    return {
        "cfg": cfg,
        "balance_text": balance_result["balance_text"],
        "balance_value": balance_result["balance_value"],
        "connectivity_tested": False,
    }




def _build_analysis_llm_config(
    provider: str,
    model_name: str,
    *,
    override_cfgs: dict[str, object] | None = None,
) -> tuple[str, LlmConfig] | tuple[None, None]:
    provider = normalize_analysis_provider(provider)
    provider_label = _analysis_provider_label(provider)
    cfg = (override_cfgs or {}).get(provider)
    if cfg is None:
        if provider == "kimi":
            cfg = load_kimi_config()
        elif provider == "qwen":
            cfg = load_qwen_config()
        else:
            cfg = load_deepseek_config()
    if provider == "kimi":
        if not cfg.is_ready():
            return None, None
        return provider_label, LlmConfig(
            base_url=cfg.base_url.strip(),
            api_key=cfg.api_key.strip(),
            model=model_name,
            timeout_s=float(cfg.timeout_s),
        )
    if provider == "qwen":
        if not cfg.is_ready():
            return None, None
        return provider_label, LlmConfig(
            base_url=cfg.base_url.strip(),
            api_key=cfg.api_key.strip(),
            model=model_name,
            timeout_s=float(cfg.timeout_s),
        )
    if not cfg.is_ready():
        return None, None
    return provider_label, LlmConfig(
        base_url=cfg.base_url.strip(),
        api_key=cfg.api_key.strip(),
        model=model_name,
        timeout_s=float(cfg.timeout_s),
    )


def _run_project_model_test(
    *,
    provider: str,
    model_name: str,
    parse_model_rows: list[dict],
    override_cfgs: dict[str, object] | None = None,
) -> dict[str, object]:
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(current_provider: str, current_model_name: str) -> None:
        normalized_provider = normalize_analysis_provider(current_provider)
        normalized_model = str(current_model_name or "").strip()
        if not normalized_provider or not normalized_model:
            return
        key = f"{normalized_provider}|{normalized_model}"
        if key in seen:
            return
        seen.add(key)
        pairs.append((normalized_provider, normalized_model))

    add(provider, model_name)
    for row in parse_model_rows:
        for item in row.get("models") or []:
            add(str(item.get("provider") or ""), str(item.get("model_name") or ""))

    normalized_provider, normalized_model = _parse_analysis_target_text(
        f"{_analysis_provider_label(provider)} / {model_name}"
    )

    def check_one(current_provider: str, current_model_name: str) -> None:
        provider_label, llm_config = _build_analysis_llm_config(
            current_provider,
            current_model_name,
            override_cfgs=override_cfgs,
        )
        if provider_label is None or llm_config is None:
            raise RuntimeError(f"请先完成 {_analysis_provider_label(current_provider)} 的 API 配置。")
        client = LlmClient(_to_fast_test_llm_config(llm_config))
        text = client.chat_text(system="你是连通性测试助手。", user="请只返回 OK")
        if "OK" not in (text or "").upper():
            raise RuntimeError(f"{provider_label} / {current_model_name} 测试未通过，返回：{text}")

    run_callables_in_parallel_fail_fast(
        callables=[
            lambda p=current_provider, m=current_model_name: check_one(p, m)
            for current_provider, current_model_name in pairs
        ],
        max_workers=max(1, len(pairs)),
    )
    return {
        "provider": normalized_provider,
        "model_name": normalized_model,
        "parse_model_rows": parse_model_rows,
    }


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

    def reload_candidates(self) -> None:
        provider = self._provider
        model_name = self._model_name
        self._rebuild_menu()
        self._provider = provider
        self._model_name = model_name
        self._refresh_text()

    def _refresh_text(self) -> None:
        if self._provider and self._model_name:
            label = _analysis_provider_label(self._provider)
            text = f"{label}\n{self._model_name}"
            tooltip = f"{label} / {self._model_name}"
        else:
            text = "选择模型"
            tooltip = text
        self.setText(text)
        self.setToolTip(tooltip)


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
        legacy_ai_concurrency = normalize_ai_concurrency(data.get("ai_concurrency", getattr(state, "ai_concurrency", 3)))
        initial_question_content_concurrency = normalize_ai_concurrency(
            data.get(
                "question_content_concurrency",
                getattr(state, "question_content_concurrency", legacy_ai_concurrency),
            )
        )
        initial_analysis_generation_concurrency = normalize_ai_concurrency(
            data.get(
                "analysis_generation_concurrency",
                getattr(state, "analysis_generation_concurrency", legacy_ai_concurrency),
            )
        )

        self._analysis_target_combo = QComboBox()
        self._analysis_target_combo.setEditable(True)
        self._analysis_target_combo.addItems(_analysis_target_candidates())
        self._analysis_target_combo.setCurrentText(_analysis_target_text(initial_provider, initial_model_name))
        self._question_content_concurrency_combo = QComboBox()
        self._analysis_generation_concurrency_combo = QComboBox()
        self._question_content_concurrency_combo.setMinimumWidth(120)
        self._analysis_generation_concurrency_combo.setMinimumWidth(120)
        for value in AI_CONCURRENCY_OPTIONS:
            self._question_content_concurrency_combo.addItem(str(value), value)
            self._analysis_generation_concurrency_combo.addItem(str(value), value)
        question_content_index = self._question_content_concurrency_combo.findData(initial_question_content_concurrency)
        if question_content_index >= 0:
            self._question_content_concurrency_combo.setCurrentIndex(question_content_index)
        analysis_generation_index = self._analysis_generation_concurrency_combo.findData(
            initial_analysis_generation_concurrency
        )
        if analysis_generation_index >= 0:
            self._analysis_generation_concurrency_combo.setCurrentIndex(analysis_generation_index)
        concurrency_row = QWidget()
        concurrency_layout = QHBoxLayout()
        concurrency_layout.setContentsMargins(0, 0, 0, 0)
        concurrency_layout.addWidget(QLabel("题目内容解析"))
        concurrency_layout.addWidget(self._question_content_concurrency_combo)
        concurrency_layout.addSpacing(20)
        concurrency_layout.addWidget(QLabel("答案解析生成"))
        concurrency_layout.addWidget(self._analysis_generation_concurrency_combo)
        concurrency_layout.addStretch(1)
        concurrency_row.setLayout(concurrency_layout)
        self._status = QLabel("未测试")
        self._status.setWordWrap(True)
        self._tested_key = self._project_config_key(initial_provider, initial_model_name, self._parse_model_rows)
        if self._tested_key:
            self._status.setText("当前已加载解析生成模型配置。")
        self._parse_result_table = self._build_parse_result_table()
        self._refresh_parse_result_model_columns()

        form = QFormLayout()
        form.addRow("解析生成模型：", self._analysis_target_combo)
        form.addRow("并发数：", concurrency_row)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(QLabel("解析结果阈值预留"))
        layout.addWidget(self._parse_result_table)
        layout.addWidget(self._status)
        layout.addStretch(1)
        self.setLayout(layout)

        self._analysis_target_combo.currentTextChanged.connect(self._reset_tested)

    def save_if_needed(self) -> None:
        if self.is_testing():
            raise _ConfigValidationError("项目配置模型测试仍在进行中，请等待完成。")
        provider, model_name = self._current_analysis_target()
        parse_model_rows = self._collect_parse_model_rows()
        if self._project_config_key(provider, model_name, parse_model_rows) != self._tested_key:
            raise _ConfigValidationError("项目配置已修改，请先点击“统一测试”并通过。")
        save_program_analysis_target(
            provider=normalize_analysis_provider(provider),
            model_name=normalize_analysis_model_name(model_name),
        )
        self._parse_model_rows = save_project_parse_model_rows(parse_model_rows)["project_parse_model_rows"]
        question_content_concurrency = normalize_ai_concurrency(
            self._question_content_concurrency_combo.currentData()
        )
        analysis_generation_concurrency = normalize_ai_concurrency(
            self._analysis_generation_concurrency_combo.currentData()
        )
        save_program_settings_merged(
            {
                "question_content_concurrency": question_content_concurrency,
                "analysis_generation_concurrency": analysis_generation_concurrency,
            }
        )
        if self._state is not None:
            self._state.analysis_provider = normalize_analysis_provider(provider)
            self._state.analysis_model_name = normalize_analysis_model_name(model_name)
            self._state.question_content_concurrency = question_content_concurrency
            self._state.analysis_generation_concurrency = analysis_generation_concurrency

    def _current_analysis_target(self) -> tuple[str, str]:
        return _parse_analysis_target_text(self._analysis_target_combo.currentText())

    def collect_test_payload(self) -> dict[str, object]:
        provider, model_name = self._current_analysis_target()
        return {
            "provider": provider,
            "model_name": model_name,
            "parse_model_rows": self._collect_parse_model_rows(),
        }

    def needs_test(self, payload: dict[str, object] | None = None) -> bool:
        data = payload or self.collect_test_payload()
        return self._project_config_key(
            str(data.get("provider") or ""),
            str(data.get("model_name") or ""),
            list(data.get("parse_model_rows") or []),
        ) != self._tested_key

    def set_status_text(self, text: str) -> None:
        self._status.setText(str(text or ""))

    def apply_test_success(self, payload: object, *, show_message: bool = True) -> None:
        data = payload if isinstance(payload, dict) else {}
        provider = str(data.get("provider") or "deepseek")
        normalized_model = str(data.get("model_name") or "").strip()
        parse_model_rows = data.get("parse_model_rows") if isinstance(data.get("parse_model_rows"), list) else []
        self._analysis_target_combo.setCurrentText(_analysis_target_text(provider, normalized_model))
        self._tested_key = self._project_config_key(provider, normalized_model, parse_model_rows)
        self._status.setText("项目配置模型测试通过。")
        if show_message:
            _show_message_box(
                self,
                title="测试通过",
                text="当前项目配置中的模型可正常使用。",
                icon=QMessageBox.Icon.Information,
            )

    def reset_runtime_status_after_failure(self) -> None:
        self._status.setText("最近一次测试失败。")

    def refresh_model_candidates(self) -> None:
        current_text = self._analysis_target_combo.currentText()
        self._analysis_target_combo.blockSignals(True)
        self._analysis_target_combo.clear()
        self._analysis_target_combo.addItems(_analysis_target_candidates())
        self._analysis_target_combo.setCurrentText(current_text)
        self._analysis_target_combo.blockSignals(False)
        table = self._parse_result_table
        for row in range(table.rowCount()):
            for col in range(2, table.columnCount()):
                selector = table.cellWidget(row, col)
                if isinstance(selector, _GroupedModelSelector):
                    selector.reload_candidates()

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

    def is_testing(self) -> bool:
        return False

    def _build_parse_result_table(self) -> QTableWidget:
        table = CopyableTableWidget(2, 6, self)
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
            combo.addItems(["1", "2", "3", "4", "5", "6", "7", "8"])
            combo.setEditable(True)
            combo.lineEdit().setReadOnly(True)
            combo.lineEdit().setAlignment(Qt.AlignmentFlag.AlignCenter)
            combo.setCurrentText("1" if row == 0 else str(row_cfg.get("round") or (row + 1)))
            if row == 0:
                combo.setEnabled(False)
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
                    "round": "1" if row_index == 0 else (combo.currentText().strip() or "1"),
                    "ratio": ratio_edit.text().strip() or "1/4",
                    "models": models,
                }
            )
        return rows


class _ApiConfigTab(QWidget):
    modelListChanged = pyqtSignal()

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
        self._provider_key = _provider_key_from_title(title)
        self._env_api_key = cfg.api_key.strip()
        self._env_account_access_key_id = getattr(cfg, "account_access_key_id", "").strip()
        self._env_account_access_key_secret = getattr(cfg, "account_access_key_secret", "").strip()
        self._available_models = load_available_models(self._provider_key)

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
        self._balance_label = QLabel(self._initial_balance_text(cfg))
        self._balance_label.setWordWrap(True)
        self._status = QLabel("未测试")
        self._status.setWordWrap(True)
        self._tested_key = self._cfg_key(cfg) if getattr(cfg, "is_ready", lambda: False)() else ""
        self._model_table = CopyableTableWidget(0, 1, self)
        self._model_table.setHorizontalHeaderLabels(["可用模型"])
        self._model_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._model_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._model_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._model_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._model_table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._model_table.itemDoubleClicked.connect(lambda *_args: self._on_edit_model())
        self._add_model_btn = QPushButton("增加模型")
        self._edit_model_btn = QPushButton("修改模型")
        self._add_model_btn.clicked.connect(self._on_add_model)
        self._edit_model_btn.clicked.connect(self._on_edit_model)
        self._refresh_model_table()

        form = QFormLayout()
        form.addRow("Base URL：", self._base_url_edit)
        form.addRow("API Key：", self._api_key_edit)
        if self._account_access_key_id_edit is not None and self._account_access_key_secret_edit is not None:
            form.addRow("阿里云 AccessKey ID：", self._account_access_key_id_edit)
            form.addRow("阿里云 AccessKey Secret：", self._account_access_key_secret_edit)
        form.addRow("超时(秒)：", self._timeout_edit)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(QLabel("可用模型列表"))
        layout.addWidget(self._model_table)
        model_btn_row = QHBoxLayout()
        model_btn_row.addWidget(self._add_model_btn)
        model_btn_row.addWidget(self._edit_model_btn)
        model_btn_row.addStretch(1)
        layout.addLayout(model_btn_row)
        layout.addWidget(self._balance_label)
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

    def provider_key(self) -> str:
        return self._provider_key

    def title_text(self) -> str:
        return self._title

    def to_llm_fn(self) -> Callable[[object], object]:
        return self._to_llm_fn

    def collect_cfg_for_test(self):
        return self._collect_cfg()

    def needs_test(self, cfg=None) -> bool:
        current_cfg = cfg if cfg is not None else self._collect_cfg()
        return bool(current_cfg.is_ready() and self._cfg_key(current_cfg) != self._tested_key)

    def set_status_text(self, text: str) -> None:
        self._status.setText(str(text or ""))

    def set_balance_querying(self) -> None:
        self._balance_label.setText("余额：查询中…")

    def apply_test_success(self, payload: object, *, show_message: bool = True) -> None:
        data = payload if isinstance(payload, dict) else {}
        cfg = data.get("cfg") if data.get("cfg") is not None else self._cfg
        self._tested_key = self._cfg_key(cfg)
        self._status.setText(f"{self._title} 的 API 连通性测试通过。")
        self._balance_label.setText(f"余额：{str(data.get('balance_text') or '未查询')}")
        if show_message:
            _show_message_box(
                self,
                title="测试通过",
                text=f"{self._title} API 可用性测试通过。",
                icon=QMessageBox.Icon.Information,
            )

    def apply_balance_refresh(self, payload: object) -> None:
        data = payload if isinstance(payload, dict) else {}
        self._balance_label.setText(f"余额：{str(data.get('balance_text') or '未查询')}")

    def reset_runtime_status_after_failure(self) -> None:
        self._status.setText("最近一次测试失败。")
        try:
            cfg = self._collect_cfg()
            self._balance_label.setText(self._initial_balance_text(cfg))
        except Exception:
            self._balance_label.setText("余额：未查询")

    def save_if_needed(self) -> None:
        if self.is_testing():
            raise _ConfigValidationError(f"{self._title} 测试仍在进行中，请等待完成。")
        cfg = self._collect_cfg()
        cfg_key = self._cfg_key(cfg)
        if cfg.is_ready() and cfg_key != self._tested_key:
            raise _ConfigValidationError(f"{self._title} 配置已修改，请先点击“统一测试”并通过。")
        self._cfg = cfg
        self._save_env_values(cfg)
        saved_models = save_available_models(self._provider_key, self._available_models)
        if saved_models != self._available_models:
            self._available_models = saved_models
            self._refresh_model_table()
        self._save_fn(cfg)
        self.modelListChanged.emit()

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

    def is_testing(self) -> bool:
        return False

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

    def _refresh_model_table(self) -> None:
        self._model_table.setRowCount(len(self._available_models))
        for row, model_name in enumerate(self._available_models):
            self._model_table.setItem(row, 0, QTableWidgetItem(model_name))

    def _selected_model_row(self) -> int:
        row = self._model_table.currentRow()
        if row >= 0:
            return row
        items = self._model_table.selectedItems()
        if items:
            return items[0].row()
        return -1

    def _prompt_model_name(self, *, title: str, initial_text: str = "") -> str | None:
        text, ok = QInputDialog.getText(self, title, "模型名：", text=initial_text)
        if not ok:
            return None
        model_name = str(text or "").strip()
        if not model_name:
            _show_message_box(self, title="模型名为空", text="模型名不能为空。", icon=QMessageBox.Icon.Warning)
            return None
        return model_name

    def _on_add_model(self) -> None:
        model_name = self._prompt_model_name(title=f"增加 {self._title} 模型")
        if model_name is None:
            return
        existing = {item.lower() for item in self._available_models}
        if model_name.lower() in existing:
            _show_message_box(self, title="模型已存在", text=f"{model_name} 已在可用模型列表中。", icon=QMessageBox.Icon.Warning)
            return
        self._available_models.append(model_name)
        self._refresh_model_table()
        self._model_table.selectRow(len(self._available_models) - 1)
        self.modelListChanged.emit()

    def _on_edit_model(self) -> None:
        row = self._selected_model_row()
        if row < 0 or row >= len(self._available_models):
            _show_message_box(self, title="未选择模型", text="请先在可用模型列表中选择一行。", icon=QMessageBox.Icon.Warning)
            return
        original = self._available_models[row]
        model_name = self._prompt_model_name(title=f"修改 {self._title} 模型", initial_text=original)
        if model_name is None:
            return
        existing = {
            item.lower()
            for index, item in enumerate(self._available_models)
            if index != row
        }
        if model_name.lower() in existing:
            _show_message_box(self, title="模型已存在", text=f"{model_name} 已在可用模型列表中。", icon=QMessageBox.Icon.Warning)
            return
        self._available_models[row] = model_name
        self._refresh_model_table()
        self._model_table.selectRow(row)
        self.modelListChanged.emit()


def _model_candidates(title: str) -> list[str]:
    return load_available_models(_provider_key_from_title(title))


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
