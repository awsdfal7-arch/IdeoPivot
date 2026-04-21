from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWizard, QWizardPage

from sj_generator.ui.state import WizardState


class ImportSuccessPage(QWizardPage):
    def __init__(self, state: WizardState) -> None:
        super().__init__()
        self._state = state
        self.setTitle("完成")
        self.setFinalPage(True)

        title = QLabel("导入数据库成功")
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        title.setStyleSheet("font-size: 22px; font-weight: 600;")

        hint = QLabel("当前流程已完成。Markdown 导出请在开始界面的菜单栏中操作。")
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)

        layout = QVBoxLayout()
        layout.addStretch(1)
        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addStretch(1)
        self.setLayout(layout)

    def initializePage(self) -> None:
        w = self.wizard()
        if isinstance(w, QWizard):
            w.setButtonText(QWizard.WizardButton.FinishButton, "完成")

    def cleanupPage(self) -> None:
        w = self.wizard()
        if isinstance(w, QWizard):
            w.setButtonText(QWizard.WizardButton.FinishButton, "完成")

    def nextId(self) -> int:
        return -1
