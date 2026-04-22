from __future__ import annotations

from PyQt6.QtCore import QObject, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QLineEdit,
    QVBoxLayout,
)

from sj_generator.ai.client import LlmClient, LlmConfig
from sj_generator.config import load_deepseek_config, load_kimi_config, load_qwen_config, save_program_settings
from sj_generator.ui.state import (
    AI_CONCURRENCY_OPTIONS,
    WizardState,
    normalize_export_convertible_multi_mode,
    normalize_default_repo_parent_dir_text,
    normalize_ai_concurrency,
    normalize_analysis_model_name,
    normalize_analysis_provider,
    normalize_preferred_textbook_version,
    library_db_path_from_repo_parent_dir_text,
)
from sj_generator.io.sqlite_repo import load_all_questions

_ANALYSIS_TARGET_CANDIDATES = [
    "DeepSeek / deepseek-reasoner",
    "DeepSeek / deepseek-chat",
    "Kimi / kimi-k2-turbo-preview",
    "千问 / qwen-max",
]
SECTION_GENERAL = "general"
SECTION_IMPORT = "import"
SECTION_EXPORT = "export"


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


class _AnalysisTargetTestWorker(QObject):
    passed = pyqtSignal(str, str)
    failed = pyqtSignal(str)

    def __init__(self, *, provider_label: str, model_name: str, llm_config: LlmConfig) -> None:
        super().__init__()
        self._provider_label = provider_label
        self._model_name = model_name
        self._llm_config = llm_config

    def run(self) -> None:
        try:
            client = LlmClient(self._llm_config)
            text = client.chat_text(system="你是连通性测试助手。", user="请只返回 OK")
            if "OK" not in (text or "").upper():
                self.failed.emit(f"{self._provider_label} / {self._model_name} 测试未通过，返回：{text}")
                return
        except Exception as e:
            self.failed.emit(f"{self._provider_label} / {self._model_name} 测试失败：{e}")
            return
        self.passed.emit(self._provider_label, self._model_name)


class ProgramSettingsDialog(QDialog):
    def __init__(self, state: WizardState, parent=None, *, section: str = SECTION_GENERAL) -> None:
        super().__init__(parent)
        self._state = state
        self._section = section if section in {SECTION_GENERAL, SECTION_IMPORT, SECTION_EXPORT} else SECTION_GENERAL
        self.setWindowTitle(self._dialog_title())
        self.resize(500, 260)
        self._analysis_test_thread: QThread | None = None
        self._analysis_test_worker: _AnalysisTargetTestWorker | None = None
        self._analysis_testing = False

        self._concurrency_combo = QComboBox()
        for value in AI_CONCURRENCY_OPTIONS:
            self._concurrency_combo.addItem(str(value), value)
        idx = self._concurrency_combo.findData(normalize_ai_concurrency(self._state.ai_concurrency))
        if idx >= 0:
            self._concurrency_combo.setCurrentIndex(idx)

        self._analysis_target_combo = QComboBox()
        self._analysis_target_combo.setEditable(True)
        self._analysis_target_combo.addItems(_ANALYSIS_TARGET_CANDIDATES)
        self._analysis_target_combo.setCurrentText(
            _analysis_target_text(self._state.analysis_provider, self._state.analysis_model_name)
        )
        self._analysis_test_btn = QPushButton("测试解析模型")
        self._analysis_test_btn.clicked.connect(self._on_test_analysis_target)
        self._analysis_status = QLabel("未测试")
        self._analysis_status.setWordWrap(True)
        self._analysis_tested_key = self._analysis_target_key(
            normalize_analysis_provider(self._state.analysis_provider),
            normalize_analysis_model_name(self._state.analysis_model_name),
        )

        self._dedupe_checkbox = QCheckBox("导入流程默认执行库内查重")
        self._dedupe_checkbox.setChecked(bool(self._state.dedupe_enabled))

        self._import_analysis_combo = QComboBox()
        self._import_analysis_combo.addItem("自动生成", True)
        self._import_analysis_combo.addItem("不生成", False)
        analysis_idx = self._import_analysis_combo.findData(bool(self._state.analysis_enabled))
        if analysis_idx >= 0:
            self._import_analysis_combo.setCurrentIndex(analysis_idx)

        self._convertible_multi_export_combo = QComboBox()
        self._convertible_multi_export_combo.addItem("保留组合映射", "keep_combo")
        self._convertible_multi_export_combo.addItem("按新多选输出", "as_multi")
        export_idx = self._convertible_multi_export_combo.findData(
            normalize_export_convertible_multi_mode(self._state.export_convertible_multi_mode)
        )
        if export_idx >= 0:
            self._convertible_multi_export_combo.setCurrentIndex(export_idx)

        self._default_repo_parent_dir_edit = QLineEdit()
        self._default_repo_parent_dir_edit.setText(
            normalize_default_repo_parent_dir_text(self._state.default_repo_parent_dir_text)
        )
        self._default_repo_parent_dir_edit.setPlaceholderText("例如：C:/Users/你的用户名/Desktop/思政题库")
        self._default_repo_parent_dir_browse_btn = QPushButton("选择…")
        self._default_repo_parent_dir_browse_btn.clicked.connect(self._browse_default_repo_parent_dir)
        self._preferred_textbook_version_combo = QComboBox()
        self._preferred_textbook_version_combo.setEditable(True)
        self._preferred_textbook_version_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        for version in self._collect_textbook_version_options():
            self._preferred_textbook_version_combo.addItem(version)
        self._preferred_textbook_version_combo.setCurrentText(
            normalize_preferred_textbook_version(self._state.preferred_textbook_version)
        )

        analysis_row = QHBoxLayout()
        analysis_row.addWidget(self._analysis_target_combo, 1)
        analysis_row.addWidget(self._analysis_test_btn)

        default_repo_row = QHBoxLayout()
        default_repo_row.addWidget(self._default_repo_parent_dir_edit, 1)
        default_repo_row.addWidget(self._default_repo_parent_dir_browse_btn)

        form = QFormLayout()
        if self._section == SECTION_GENERAL:
            form.addRow("默认题库保存位置：", default_repo_row)
            form.addRow("题目版本首选项：", self._preferred_textbook_version_combo)
        elif self._section == SECTION_IMPORT:
            form.addRow("统一并发数：", self._concurrency_combo)
            form.addRow("导入文档时解析生成：", self._import_analysis_combo)
            form.addRow("", self._dedupe_checkbox)
            form.addRow("解析生成模型：", analysis_row)
            form.addRow("", self._analysis_status)
        else:
            form.addRow("可转多选 Markdown 导出：", self._convertible_multi_export_combo)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        self._buttons = buttons

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.setLayout(layout)

        self._analysis_target_combo.currentTextChanged.connect(self._reset_analysis_tested)
        if self._section == SECTION_IMPORT and self._analysis_tested_key:
            self._analysis_status.setText("当前解析生成模型配置已就绪。")

    def _on_accept(self) -> None:
        if self._section == SECTION_IMPORT and self._analysis_testing:
            QMessageBox.information(self, "测试中", "解析生成模型正在测试，请等待测试完成后再保存。")
            return
        if self._section == SECTION_GENERAL:
            self._state.default_repo_parent_dir_text = normalize_default_repo_parent_dir_text(
                self._default_repo_parent_dir_edit.text()
            )
            self._state.preferred_textbook_version = normalize_preferred_textbook_version(
                self._preferred_textbook_version_combo.currentText()
            )
        elif self._section == SECTION_IMPORT:
            provider, model_name = self._current_analysis_target()
            if self._analysis_target_key(provider, model_name) != self._analysis_tested_key:
                QMessageBox.warning(self, "配置未完成", "解析生成模型已修改，请先点击“测试解析模型”并通过。")
                return
            self._state.ai_concurrency = normalize_ai_concurrency(self._concurrency_combo.currentData())
            self._state.analysis_enabled = bool(self._import_analysis_combo.currentData())
            self._state.dedupe_enabled = self._dedupe_checkbox.isChecked()
            self._state.analysis_provider = provider
            self._state.analysis_model_name = model_name
            if not self._state.dedupe_enabled:
                self._state.dedupe_hits = None
        else:
            self._state.export_convertible_multi_mode = normalize_export_convertible_multi_mode(
                self._convertible_multi_export_combo.currentData()
            )
        self._save_program_settings()
        self.accept()

    def _dialog_title(self) -> str:
        if self._section == SECTION_IMPORT:
            return "导入设定"
        if self._section == SECTION_EXPORT:
            return "导出设定"
        return "常规设定"

    def _save_program_settings(self) -> None:
        save_program_settings(
            {
                "default_repo_parent_dir_text": normalize_default_repo_parent_dir_text(
                    self._state.default_repo_parent_dir_text
                ),
                "ai_concurrency": normalize_ai_concurrency(self._state.ai_concurrency),
                "analysis_enabled": bool(self._state.analysis_enabled),
                "dedupe_enabled": bool(self._state.dedupe_enabled),
                "analysis_provider": normalize_analysis_provider(self._state.analysis_provider),
                "analysis_model_name": normalize_analysis_model_name(self._state.analysis_model_name),
                "export_convertible_multi_mode": normalize_export_convertible_multi_mode(
                    self._state.export_convertible_multi_mode
                ),
                "preferred_textbook_version": normalize_preferred_textbook_version(
                    self._state.preferred_textbook_version
                ),
            }
        )

    def _collect_textbook_version_options(self) -> list[str]:
        versions: list[str] = []
        seen: set[str] = set()

        def add_version(value: str) -> None:
            normalized = str(value or "").strip()
            if not normalized or normalized in seen:
                return
            seen.add(normalized)
            versions.append(normalized)

        add_version(self._state.preferred_textbook_version)
        db_path = library_db_path_from_repo_parent_dir_text(self._state.default_repo_parent_dir_text)
        if db_path.exists():
            for record in load_all_questions(db_path):
                add_version(record.textbook_version)
        return versions

    def _current_analysis_target(self) -> tuple[str, str]:
        return _parse_analysis_target_text(self._analysis_target_combo.currentText())

    def _analysis_target_key(self, provider: str, model_name: str) -> str:
        return f"{normalize_analysis_provider(provider)}|{normalize_analysis_model_name(model_name)}"

    def _reset_analysis_tested(self, *_args) -> None:
        if self._analysis_testing:
            return
        self._analysis_tested_key = ""
        if self._section == SECTION_IMPORT:
            self._analysis_status.setText("解析生成模型已变更，需重新测试。")

    def _on_test_analysis_target(self) -> None:
        provider, model_name = self._current_analysis_target()
        provider_label, llm_config = _build_analysis_llm_config(provider, model_name)
        if provider_label is None or llm_config is None:
            provider_label = _analysis_provider_label(provider)
            QMessageBox.warning(self, "未配置", f"请先完成 {provider_label} 的 API 配置。")
            self._analysis_status.setText("最近一次测试失败。")
            return
        self._set_analysis_testing(True, f"正在测试：{provider_label} / {model_name}")
        thread = QThread(self)
        worker = _AnalysisTargetTestWorker(
            provider_label=provider_label,
            model_name=model_name,
            llm_config=llm_config,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.passed.connect(self._on_analysis_test_passed)
        worker.failed.connect(self._on_analysis_test_failed)
        worker.passed.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_analysis_test_finished)
        self._analysis_test_thread = thread
        self._analysis_test_worker = worker
        thread.start()

    def _set_analysis_testing(self, testing: bool, status_text: str | None = None) -> None:
        self._analysis_testing = testing
        self._analysis_target_combo.setEnabled(not testing)
        self._analysis_test_btn.setEnabled(not testing)
        ok_button = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_button is not None:
            ok_button.setEnabled(not testing)
        if status_text is not None:
            self._analysis_status.setText(status_text)

    def _browse_default_repo_parent_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "选择默认题库保存位置",
            normalize_default_repo_parent_dir_text(self._default_repo_parent_dir_edit.text()),
        )
        if folder:
            self._default_repo_parent_dir_edit.setText(folder)

    def _on_analysis_test_passed(self, provider_label: str, model_name: str) -> None:
        provider, normalized_model = _parse_analysis_target_text(f"{provider_label} / {model_name}")
        self._analysis_target_combo.setCurrentText(_analysis_target_text(provider, normalized_model))
        self._analysis_tested_key = self._analysis_target_key(provider, normalized_model)
        self._analysis_status.setText(f"解析生成模型测试通过：{provider_label} / {normalized_model}")
        QMessageBox.information(self, "测试通过", f"{provider_label} / {normalized_model} 可用于解析生成。")

    def _on_analysis_test_failed(self, message: str) -> None:
        self._analysis_status.setText("最近一次测试失败。")
        QMessageBox.critical(self, "测试失败", message)

    def _on_analysis_test_finished(self) -> None:
        self._set_analysis_testing(False)
        self._analysis_test_thread = None
        self._analysis_test_worker = None

    def reject(self) -> None:
        if self._analysis_testing:
            QMessageBox.information(self, "测试中", "解析生成模型正在测试，请等待测试完成后再关闭窗口。")
            return
        super().reject()
