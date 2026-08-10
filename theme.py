ACCENT_STYLESHEET = """
QGroupBox {
    border: 1px solid #3a3a3a;
    border-radius: 6px;
    margin-top: 10px;
    padding-top: 8px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
}
QTabWidget::pane {
    border: 1px solid #3a3a3a;
    border-radius: 4px;
    top: -1px;
}
QTabBar::tab {
    padding: 6px 10px;
    margin-right: 2px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    min-width: 48px;
}
QTabBar::scroller {
    width: 20px;
}
QMainWindow, QWidget#centralRoot {
    background-color: #1e1e1e;
}
QPushButton#btnPrimary {
    background-color: #2e7d32;
    color: white;
    font-weight: bold;
    border: none;
    border-radius: 4px;
    padding: 10px;
}
QPushButton#btnPrimary:hover {
    background-color: #388e3c;
}
QPushButton#btnDanger {
    background-color: #c62828;
    color: white;
}
QPushButton#btnGhost {
    background-color: #424242;
}
QLabel#statusActive {
    color: #69f0ae;
    font-size: 15px;
    font-weight: bold;
}
QLabel#statusPaused {
    color: #ff5252;
    font-size: 15px;
    font-weight: bold;
}
QLabel#dirtyBanner {
    color: #ffb74d;
    background: #2a2418;
    border: 1px solid #5d4a2a;
    border-radius: 4px;
    padding: 6px 8px;
    font-size: 11px;
}
QTextEdit#logPanel {
    background: #1a1a1a;
    border: 1px solid #333;
    border-radius: 4px;
    font-family: Consolas, monospace;
    font-size: 11px;
}
"""

VIEWPORT_WATER_BORDER = "#2e7d32"
VIEWPORT_BAR_BORDER = "#0288d1"
WINDOW_WIDTH = 540
WINDOW_HEIGHT = 1080
VIEWPORT_W = 240
VIEWPORT_H = 150


def apply_app_theme(app):
    try:
        import qdarktheme
        qdarktheme.setup_theme("dark")
    except Exception:
        try:
            import qdarktheme
            app.setStyleSheet(qdarktheme.load_stylesheet())
        except Exception:
            app.setStyle("Fusion")
    app.setStyleSheet(app.styleSheet() + ACCENT_STYLESHEET)


def dock_window_left(window, width: int = WINDOW_WIDTH, preferred_height: int = WINDOW_HEIGHT) -> None:
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    screen = app.primaryScreen() if app else None
    if screen is None:
        window.resize(width, preferred_height)
        window.move(0, 0)
        return
    geo = screen.availableGeometry()
    height = min(preferred_height, geo.height())
    window.resize(width, height)
    window.move(geo.x(), geo.y())
