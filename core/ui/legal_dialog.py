from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from core.app_paths import SETTINGS_FILE
from core.legal import (
    PRIVACY_VERSION,
    TERMS_VERSION,
    read_privacy_text,
    read_terms_text,
    save_legal_acceptance,
)


class LegalAcceptanceDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle("1SalemBOT Terms and Privacy")
        self.setMinimumSize(760, 620)
        self.setObjectName("legalAcceptanceDialog")

        self.terms_text = read_terms_text()
        self.privacy_text = read_privacy_text()

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 22, 22, 22)
        root.setSpacing(14)

        title = QLabel("1SalemBOT Terms of Use and Privacy Policy\nشروط الاستخدام وسياسة الخصوصية")
        title.setObjectName("legalTitle")
        title.setAlignment(Qt.AlignCenter)
        title.setWordWrap(True)
        root.addWidget(title)

        version_label = QLabel(f"Terms Version: {TERMS_VERSION}    Privacy Version: {PRIVACY_VERSION}")
        version_label.setObjectName("legalVersion")
        version_label.setAlignment(Qt.AlignCenter)
        root.addWidget(version_label)

        button_row = QHBoxLayout()
        button_row.setSpacing(10)
        self.view_terms_button = QPushButton("View Terms of Use\nعرض شروط الاستخدام")
        self.view_terms_button.setObjectName("viewTermsButton")
        self.view_privacy_button = QPushButton("View Privacy Policy\nعرض سياسة الخصوصية")
        self.view_privacy_button.setObjectName("viewPrivacyButton")
        button_row.addWidget(self.view_terms_button)
        button_row.addWidget(self.view_privacy_button)
        root.addLayout(button_row)

        self.viewer = QTextBrowser()
        self.viewer.setObjectName("legalDocumentViewer")
        self.viewer.setOpenExternalLinks(False)
        self.viewer.setLayoutDirection(Qt.LeftToRight)
        root.addWidget(self.viewer, 1)

        checks_frame = QFrame()
        checks_frame.setObjectName("legalChecksFrame")
        checks_layout = QVBoxLayout(checks_frame)
        checks_layout.setContentsMargins(14, 12, 14, 12)
        checks_layout.setSpacing(8)

        self.terms_checkbox = QCheckBox("I agree to the Terms of Use / أوافق على شروط الاستخدام")
        self.terms_checkbox.setObjectName("termsCheckbox")
        self.privacy_checkbox = QCheckBox("I agree to the Privacy Policy / أوافق على سياسة الخصوصية")
        self.privacy_checkbox.setObjectName("privacyCheckbox")
        checks_layout.addWidget(self.terms_checkbox)
        checks_layout.addWidget(self.privacy_checkbox)
        root.addWidget(checks_frame)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.exit_button = QPushButton("Exit\nخروج")
        self.exit_button.setObjectName("legalExitButton")
        self.continue_button = QPushButton("Continue\nمتابعة")
        self.continue_button.setObjectName("legalContinueButton")
        self.continue_button.setEnabled(False)
        actions.addWidget(self.exit_button)
        actions.addWidget(self.continue_button)
        root.addLayout(actions)

        self.view_terms_button.clicked.connect(self.show_terms)
        self.view_privacy_button.clicked.connect(self.show_privacy)
        self.terms_checkbox.toggled.connect(self.update_continue_state)
        self.privacy_checkbox.toggled.connect(self.update_continue_state)
        self.exit_button.clicked.connect(self.reject)
        self.continue_button.clicked.connect(self.accept)

        self.setStyleSheet(
            """
            QDialog#legalAcceptanceDialog {
                background: #0b1220;
                color: #e5edf7;
            }
            QLabel#legalTitle {
                color: #f8fbff;
                font-size: 20px;
                font-weight: 700;
            }
            QLabel#legalVersion {
                color: #8ea4bd;
                font-size: 12px;
            }
            QTextBrowser#legalDocumentViewer {
                background: #111827;
                border: 1px solid #263449;
                border-radius: 8px;
                color: #e5edf7;
                padding: 12px;
                selection-background-color: #7c3aed;
            }
            QFrame#legalChecksFrame {
                background: rgba(17, 24, 39, 0.82);
                border: 1px solid #263449;
                border-radius: 8px;
            }
            QCheckBox {
                color: #e5edf7;
                font-size: 13px;
                spacing: 10px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border: 1px solid #41516b;
                border-radius: 5px;
                background: #0f172a;
            }
            QCheckBox::indicator:checked {
                background: #7c3aed;
                border-color: #a78bfa;
            }
            QPushButton {
                background: #1f2a3d;
                color: #f8fbff;
                border: 1px solid #34445e;
                border-radius: 8px;
                padding: 9px 16px;
                min-height: 34px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #283850;
            }
            QPushButton#legalContinueButton {
                background: #7c3aed;
                border-color: #a78bfa;
            }
            QPushButton#legalContinueButton:disabled {
                background: #263044;
                border-color: #34445e;
                color: #7b8798;
            }
            """
        )
        self.show_terms()

    def update_continue_state(self):
        self.continue_button.setEnabled(self.terms_checkbox.isChecked() and self.privacy_checkbox.isChecked())

    def show_terms(self):
        self.viewer.setMarkdown(self.terms_text)
        self.viewer.verticalScrollBar().setValue(0)

    def show_privacy(self):
        self.viewer.setMarkdown(self.privacy_text)
        self.viewer.verticalScrollBar().setValue(0)


def request_legal_acceptance(settings_file=SETTINGS_FILE, parent=None):
    dialog = LegalAcceptanceDialog(parent=parent)
    if dialog.exec() != QDialog.Accepted:
        return False
    if not (dialog.terms_checkbox.isChecked() and dialog.privacy_checkbox.isChecked()):
        return False
    save_legal_acceptance(settings_file)
    return True
