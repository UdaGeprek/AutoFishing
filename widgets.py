from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QWidget


class InfoIcon(QLabel):
    """Icon (i) kecil dengan tooltip saat kursor mendekat."""

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


def form_row(label_text: str, widget: QWidget, tip: str = "") -> QHBoxLayout:
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    lbl = QLabel(label_text)
    row.addWidget(lbl)
    if tip:
        row.addWidget(InfoIcon(tip))
    row.addStretch()
    row.addWidget(widget)
    return row


def group_title_with_tip(title: str, tip: str) -> str:
    return title
