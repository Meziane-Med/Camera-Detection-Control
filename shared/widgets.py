from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


def button(text: str, kind: str = "secondary", enabled: bool = True) -> QPushButton:
    """Create a button styled by its ``kind``: primary, secondary, danger or icon."""

    widget = QPushButton(text)
    widget.setProperty("kind", kind)
    widget.setEnabled(enabled)
    return widget


def label(text: str, name: str | None = None, wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    if name:
        widget.setObjectName(name)
    widget.setWordWrap(wrap)
    return widget


def card(layout: QVBoxLayout | QHBoxLayout | None = None, margin: int = 16) -> QFrame:
    frame = QFrame()
    frame.setObjectName("card")
    layout = layout or QVBoxLayout()
    layout.setContentsMargins(margin, margin, margin, margin)
    frame.setLayout(layout)
    return frame


def page_header(title: str, subtitle: str, *actions: QWidget) -> QHBoxLayout:
    """Title and subtitle on the left, the page's main actions on the right."""

    copy = QVBoxLayout()
    copy.setSpacing(2)
    copy.addWidget(label(title, "pageTitle"))
    copy.addWidget(label(subtitle, "pageSubtitle", wrap=True))
    header = QHBoxLayout()
    header.setSpacing(8)
    header.addLayout(copy, 1)
    for action in actions:
        header.addWidget(action)
    return header
