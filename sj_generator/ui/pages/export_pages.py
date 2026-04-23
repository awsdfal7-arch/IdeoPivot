from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWizard, QWizardPage

from sj_generator.ui.state import WizardState


class ImportSuccessPage(QWizardPage):
    def __init__(self, state: WizardState) -> None:
        super().__init__()
        self._state = state
        self.setTitle("完成")
        self.setFinalPage(True)

        self._title = QLabel("导入数据库成功")
        self._title.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        self._title.setStyleSheet("font-size: 22px; font-weight: 600;")

        self._hint = QLabel("")
        self._hint.setWordWrap(True)
        self._hint.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)

        layout = QVBoxLayout()
        layout.addStretch(1)
        layout.addWidget(self._title)
        layout.addWidget(self._hint)
        layout.addStretch(1)
        self.setLayout(layout)

    def initializePage(self) -> None:
        w = self.wizard()
        if isinstance(w, QWizard):
            w.setButtonText(QWizard.WizardButton.FinishButton, "返回开始页")
            w.setButtonText(QWizard.WizardButton.CancelButton, "返回开始页")
        count = self._state.db_import_count
        self._title.setText("导入数据库成功")
        self._hint.setText(f"本次已写入当前总库 {count} 道题。Markdown 导出请在开始界面的菜单栏中操作。")

    def cleanupPage(self) -> None:
        w = self.wizard()
        if isinstance(w, QWizard):
            w.setButtonText(QWizard.WizardButton.FinishButton, "返回开始页")
            w.setButtonText(QWizard.WizardButton.CancelButton, "返回开始页")

    def nextId(self) -> int:
        return -1
