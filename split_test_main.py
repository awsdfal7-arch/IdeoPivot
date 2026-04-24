from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from PyQt6.QtCore import QObject, QThread, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from sj_generator.ai.client import LlmClient
from sj_generator.ai.import_questions import (
    _as_str,
    _get_question_numbers_with_fallback,
    _normalize_question_ref_list,
)
from sj_generator.config import (
    load_deepseek_config,
    load_kimi_config,
    load_qwen_config,
    to_kimi_question_number_llm_config,
    to_question_number_llm_config,
    to_qwen_question_number_llm_config,
)
from sj_generator.io.source_reader import read_source_text


def _question_ref_fingerprint(items: list[dict[str, str]]) -> str:
    normalized = _normalize_question_ref_list(items)
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _question_ref_numbers(items: list[dict[str, str]]) -> list[str]:
    return [_as_str(item.get("number", "")) for item in items if _as_str(item.get("number", ""))]


def _question_ref_type_map(items: list[dict[str, str]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in _normalize_question_ref_list(items):
        number = _as_str(item.get("number", ""))
        if not number:
            continue
        result[number] = _as_str(item.get("question_type", ""))
    return result


def _merged_question_ref_numbers(*groups: list[dict[str, str]]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for items in groups:
        for number in _question_ref_numbers(items):
            if number in seen:
                continue
            seen.add(number)
            ordered.append(number)
    return ordered


def _question_ref_header_labels() -> list[str]:
    deepseek_model = load_deepseek_config().number_model.strip() or "DeepSeek"
    kimi_model = load_kimi_config().number_model.strip() or "Kimi"
    qwen_model = load_qwen_config().number_model.strip() or "千问"
    return [
        "题号",
        f"DeepSeek\n{deepseek_model}",
        f"Kimi\n{kimi_model}",
        f"千问\n{qwen_model}",
        "最终",
        "一致性",
    ]


class _QuestionRefWorker(QObject):
    done = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, *, text: str, source_name: str) -> None:
        super().__init__()
        self._text = text
        self._source_name = source_name

    def run(self) -> None:
        try:
            deepseek_cfg = load_deepseek_config()
            kimi_cfg = load_kimi_config()
            qwen_cfg = load_qwen_config()
            if not deepseek_cfg.is_ready():
                raise RuntimeError("DeepSeek 未配置，无法识别题号。")
            if not kimi_cfg.is_ready():
                raise RuntimeError("Kimi 未配置，无法识别题号。")
            if not qwen_cfg.is_ready():
                raise RuntimeError("千问未配置，无法识别题号。")

            clients = {
                "DeepSeek": LlmClient(to_question_number_llm_config(deepseek_cfg)),
                "Kimi": LlmClient(to_kimi_question_number_llm_config(kimi_cfg)),
                "千问": LlmClient(to_qwen_question_number_llm_config(qwen_cfg)),
            }
            results: dict[str, list[dict[str, str]]] = {}
            with ThreadPoolExecutor(max_workers=3) as executor:
                future_map = {
                    executor.submit(
                        _get_question_numbers_with_fallback,
                        client=client,
                        source_name=self._source_name,
                        chunk_text=self._text,
                        depth=2,
                    ): model_name
                    for model_name, client in clients.items()
                }
                for future in as_completed(future_map):
                    model_name = future_map[future]
                    results[model_name] = _normalize_question_ref_list(future.result())

            deepseek_items = results.get("DeepSeek", [])
            kimi_items = results.get("Kimi", [])
            qwen_items = results.get("千问", [])
            accepted = (
                _question_ref_fingerprint(deepseek_items)
                == _question_ref_fingerprint(kimi_items)
                == _question_ref_fingerprint(qwen_items)
            )
            self.done.emit(
                {
                    "accepted": accepted,
                    "final_refs": deepseek_items if accepted else [],
                    "deepseek": deepseek_items,
                    "kimi": kimi_items,
                    "qwen": qwen_items,
                }
            )
        except Exception as exc:
            self.error.emit(str(exc))


class SplitFlowTestWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("思政智题云枢 - 题号与题型识别测试")
        self.resize(1220, 800)

        self._current_path: Path | None = None
        self._question_refs: list[dict[str, str]] = []
        self._ai_thread: QThread | None = None
        self._ai_worker: QObject | None = None

        self._path_edit = QLineEdit()
        self._path_edit.setReadOnly(True)
        self._path_edit.setPlaceholderText("请选择一个 docx 文件")

        self._pick_btn = QPushButton("选择文档")
        self._pick_btn.clicked.connect(self._pick_docx)

        self._ai_number_btn = QPushButton("AI识别题号")
        self._ai_number_btn.clicked.connect(self._run_ai_question_ref_scan)

        self._summary_label = QLabel("尚未开始")
        self._summary_label.setWordWrap(True)

        self._ai_status_label = QLabel("AI 状态：待命")
        self._ai_status_label.setWordWrap(True)

        self._source_text = QPlainTextEdit()
        self._source_text.setReadOnly(True)
        self._source_text.setPlaceholderText("这里显示 docx 提取后的纯文本")

        self._question_refs_table = QTableWidget(0, 6)
        self._question_refs_table.setHorizontalHeaderLabels(_question_ref_header_labels())
        self._question_refs_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._question_refs_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._question_refs_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._question_refs_table.verticalHeader().setVisible(False)
        header = self._question_refs_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("文档"))
        top_row.addWidget(self._path_edit, 1)
        top_row.addWidget(self._pick_btn)
        top_row.addWidget(self._ai_number_btn)

        left_panel = QWidget()
        left_layout = QVBoxLayout()
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("源文本"))
        left_layout.addWidget(self._source_text, 1)
        left_panel.setLayout(left_layout)

        right_panel = QWidget()
        right_layout = QVBoxLayout()
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(QLabel("AI 题号与题型列表"))
        right_layout.addWidget(self._question_refs_table, 1)
        right_panel.setLayout(right_layout)

        splitter = QSplitter()
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)

        layout = QVBoxLayout()
        layout.addLayout(top_row)
        layout.addWidget(self._summary_label)
        layout.addWidget(self._ai_status_label)
        layout.addWidget(splitter, 1)
        self.setLayout(layout)

    def _pick_docx(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 Word 文档",
            str(Path.home() / "Downloads"),
            "Word 文档 (*.docx)",
        )
        if not file_path:
            return
        self._current_path = Path(file_path)
        self._path_edit.setText(file_path)

    def _run_ai_question_ref_scan(self) -> None:
        if self._ai_thread is not None and self._ai_thread.isRunning():
            self._show_error("AI 任务仍在进行中，请稍候。")
            return
        self._question_refs_table.setHorizontalHeaderLabels(_question_ref_header_labels())
        try:
            path, text = self._load_source_text()
        except Exception as exc:
            self._show_error(str(exc))
            return

        self._current_path = path
        self._path_edit.setText(str(path))
        self._source_text.setPlainText(text)
        non_empty_lines = sum(1 for line in text.splitlines() if line.strip())
        self._summary_label.setText(
            f"文件：{path.name} | 提取字符数：{len(text)} | 非空行：{non_empty_lines}"
        )
        self._question_refs = []
        self._question_refs_table.setRowCount(0)
        self._ai_status_label.setText("AI 状态：正在识别题号与题型列表…")
        self._ai_number_btn.setEnabled(False)

        thread = QThread(self)
        worker = _QuestionRefWorker(text=text, source_name=path.name)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_ai_question_refs_done)
        worker.error.connect(self._on_ai_question_refs_error)
        worker.done.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._ai_thread = thread
        self._ai_worker = worker
        thread.start()

    def _load_source_text(self) -> tuple[Path, str]:
        path = self._current_path
        if path is None:
            raw = self._path_edit.text().strip()
            if raw:
                path = Path(raw)
        if path is None or not path.exists():
            raise RuntimeError("请先选择存在的 docx 文件。")
        if path.suffix.lower() != ".docx":
            raise RuntimeError("当前测试入口仅支持 docx 文件。")
        return path, read_source_text(path)

    def _on_ai_question_refs_done(self, result: object) -> None:
        payload = result if isinstance(result, dict) else {}
        deepseek_items = _normalize_question_ref_list(payload.get("deepseek", []))
        kimi_items = _normalize_question_ref_list(payload.get("kimi", []))
        qwen_items = _normalize_question_ref_list(payload.get("qwen", []))
        accepted = bool(payload.get("accepted"))
        final_refs = _normalize_question_ref_list(payload.get("final_refs", []))

        self._question_refs = final_refs if accepted else []
        deepseek_map = _question_ref_type_map(deepseek_items)
        kimi_map = _question_ref_type_map(kimi_items)
        qwen_map = _question_ref_type_map(qwen_items)
        final_map = _question_ref_type_map(self._question_refs)
        numbers = _merged_question_ref_numbers(deepseek_items, kimi_items, qwen_items, self._question_refs)

        self._question_refs_table.setRowCount(len(numbers))
        for row, number in enumerate(numbers):
            deepseek_type = deepseek_map.get(number, "")
            kimi_type = kimi_map.get(number, "")
            qwen_type = qwen_map.get(number, "")
            final_type = final_map.get(number, "")
            is_same = bool(deepseek_type and deepseek_type == kimi_type == qwen_type)
            cells = [
                number,
                deepseek_type,
                kimi_type,
                qwen_type,
                final_type,
                "一致" if is_same else "不一致",
            ]
            for col, value in enumerate(cells):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self._question_refs_table.setItem(row, col, item)

        if accepted:
            self._ai_status_label.setText(
                f"AI 状态：题号识别完成，共 {len(self._question_refs)} 个题号，三模型一致。"
            )
        else:
            self._ai_status_label.setText("AI 状态：三模型结果不一致，当前不可继续。")
        self._ai_number_btn.setEnabled(True)

        if self._question_refs:
            self._summary_label.setText(
                self._summary_label.text()
                + f" | 识别题号数：{len(self._question_refs)} | 题号：{', '.join(_question_ref_numbers(self._question_refs))}"
            )
        self._ai_thread = None
        self._ai_worker = None

    def _on_ai_question_refs_error(self, message: str) -> None:
        self._question_refs_table.setRowCount(0)
        self._ai_status_label.setText(f"AI 状态：题号识别失败：{message}")
        self._ai_number_btn.setEnabled(True)
        self._ai_thread = None
        self._ai_worker = None

    def _show_error(self, text: str) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("题号与题型识别测试")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(text)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.exec()


def main() -> None:
    app = QApplication(sys.argv)
    window = SplitFlowTestWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
