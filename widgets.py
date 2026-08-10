from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel


class InfoIcon(QLabel):
    def __init__(self, tip: str, parent=None):
        super().__init__("i", parent)
        self.setObjectName("infoIcon")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setToolTip(tip)
        self.setCursor(Qt.CursorShape.WhatsThisCursor)
        self.setFixedSize(20, 20)
        self.setStyleSheet(
            "QLabel#infoIcon {"
            "  background: #333;"
            "  border: 1px solid #555;"
            "  border-radius: 9px;"
            "  color: #4fc3f7;"
            "  font-size: 11px;"
            "  font-weight: 800;"
            "}"
        )
