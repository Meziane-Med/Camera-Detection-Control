import sys

from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QListWidget,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from peripheral_control.ui import PeripheralPanel
from shared.theme import apply_theme
from shared.widgets import label

from . import __version__
from .page import CameraPage


class MainWindow(QMainWindow):
    """Application shell: a sidebar that switches between the pages."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Device Control")
        self.resize(1120, 720)
        self.setMinimumSize(860, 560)

        self._camera_page = CameraPage()
        self._peripheral_page = PeripheralPanel()
        pages = QStackedWidget()
        nav = QListWidget()
        nav.setObjectName("nav")
        for title, page in (("Camera", self._camera_page), ("Peripherals", self._peripheral_page)):
            nav.addItem(title)
            pages.addWidget(page)
        nav.currentRowChanged.connect(pages.setCurrentIndex)
        nav.setCurrentRow(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(210)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(16, 22, 16, 16)
        side.setSpacing(2)
        side.addWidget(label("Device Control", "brand"))
        side.addWidget(label("Camera & peripherals", "brandCaption"))
        side.addSpacing(18)
        side.addWidget(nav, 1)
        side.addWidget(label(f"v{__version__}", "brandCaption"))

        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(sidebar)
        layout.addWidget(pages, 1)
        self.setCentralWidget(root)

    def closeEvent(self, event: object) -> None:
        self._camera_page.shutdown()
        self._peripheral_page.shutdown()
        event.accept()


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    apply_theme(app)
    window = MainWindow()
    window.show()
    app.exec()
