from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWizard, QWizardPage

from sj_generator.application.state import ImportWizardSession


class ImportSuccessPage(QWizardPage):
    def __init__(self, state: ImportWizardSession) -> None:
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
        wizard = self.wizard()
        if isinstance(wizard, QWizard):
            wizard.setButtonText(QWizard.WizardButton.FinishButton, "返回开始页")
            wizard.setButtonText(QWizard.WizardButton.CancelButton, "返回开始页")
        count = self._state.execution.db_import_count
        self._title.setText("导入数据库成功")
        lines = [f"本次已写入当前总库 {count} 道题。"]
        lines.append("Markdown 导出请在开始界面的菜单栏中操作。")
        self._hint.setText("\n".join(lines))

    def cleanupPage(self) -> None:
        wizard = self.wizard()
        if isinstance(wizard, QWizard):
            wizard.setButtonText(QWizard.WizardButton.FinishButton, "返回开始页")
            wizard.setButtonText(QWizard.WizardButton.CancelButton, "返回开始页")

    def nextId(self) -> int:
        return -1

__all__ = ["ImportSuccessPage"]
