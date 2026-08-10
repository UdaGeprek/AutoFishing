from PyQt6.QtWidgets import QWidget, QRubberBand
from PyQt6.QtCore import Qt, QRect, QPoint, QSize, pyqtSignal


class RegionSelector(QWidget):
    region_selected = pyqtSignal(dict)
    selection_cancelled = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setWindowState(Qt.WindowState.WindowFullScreen)
        self.setWindowOpacity(0.35)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.rubber_band = QRubberBand(QRubberBand.Shape.Rectangle, self)
        self.origin = QPoint()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.origin = event.pos()
            self.rubber_band.setGeometry(QRect(self.origin, QSize()))
            self.rubber_band.show()

    def mouseMoveEvent(self, event):
        if not self.origin.isNull() and self.rubber_band.isVisible():
            self.rubber_band.setGeometry(QRect(self.origin, event.pos()).normalized())

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.rubber_band.hide()
            rect = QRect(self.origin, event.pos()).normalized()
            self.close()
            if rect.width() > 10 and rect.height() > 10:
                dpr = self.devicePixelRatio()
                region = {
                    "top": int(rect.top() * dpr),
                    "left": int(rect.left() * dpr),
                    "width": int(rect.width() * dpr),
                    "height": int(rect.height() * dpr),
                }
                self.region_selected.emit(region)
            else:
                self.selection_cancelled.emit()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            self.selection_cancelled.emit()
