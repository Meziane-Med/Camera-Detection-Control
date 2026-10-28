from PySide6.QtWidgets import QApplication, QWidget

# Design tokens: change the palette here, every page follows.
COLORS = {
    "bg": "#0f1115",
    "sidebar": "#0b0d11",
    "surface": "#171a21",
    "surface_hover": "#1f232c",
    "border": "#262b36",
    "border_strong": "#363c4a",
    "text": "#e6e8ee",
    "text_strong": "#ffffff",
    "muted": "#8b93a7",
    "accent": "#4f7cff",
    "accent_hover": "#6a90ff",
    "accent_soft": "#1d2a4d",
    "danger": "#ef4444",
    "danger_hover": "#f26161",
}

_STYLESHEET = """
QWidget {{ background: {bg}; color: {text};
           font-family: "Segoe UI Variable Text", "Segoe UI"; font-size: 10pt; }}
QToolTip {{ background: {surface}; color: {text}; border: 1px solid {border}; }}

QFrame#sidebar {{ background: {sidebar}; border-right: 1px solid {border}; }}
QFrame#sidebar QWidget {{ background: transparent; }}
QLabel#brand {{ color: {text_strong}; font-size: 13pt; font-weight: 600; }}
QLabel#brandCaption {{ color: {muted}; font-size: 9pt; }}
QListWidget#nav {{ border: 0; outline: none; }}
QListWidget#nav::item {{ padding: 10px 12px; margin: 2px 0; border-radius: 8px; color: {muted}; }}
QListWidget#nav::item:hover {{ background: {surface}; color: {text}; }}
QListWidget#nav::item:selected {{ background: {accent_soft}; color: {text_strong}; }}

QLabel#pageTitle {{ color: {text_strong}; font-size: 18pt; font-weight: 600; }}
QLabel#pageSubtitle, QLabel#muted {{ color: {muted}; }}
QLabel#status {{ color: {muted}; padding: 2px; }}
QLabel#fieldLabel {{ color: {muted}; }}

QFrame#card {{ background: {surface}; border: 1px solid {border}; border-radius: 12px; }}
QFrame#card QWidget {{ background: transparent; }}
QLabel#preview {{ background: #07080b; border-radius: 10px; color: {muted}; }}

QPushButton, QComboBox, QLineEdit {{
    min-height: 32px; padding: 0 14px; border-radius: 8px;
    background: {surface_hover}; color: {text}; border: 1px solid {border_strong};
}}
QPushButton:hover, QComboBox:hover {{ border-color: {muted}; }}
QPushButton:pressed {{ background: {surface}; }}
QPushButton:disabled, QComboBox:disabled {{ color: #565d6e; background: {surface}; border-color: {border}; }}
QPushButton[kind="primary"] {{ background: {accent}; border-color: {accent}; color: white; font-weight: 600; }}
QPushButton[kind="primary"]:hover {{ background: {accent_hover}; border-color: {accent_hover}; }}
QPushButton[kind="danger"] {{ background: {danger}; border-color: {danger}; color: white; font-weight: 600; }}
QPushButton[kind="danger"]:hover {{ background: {danger_hover}; border-color: {danger_hover}; }}
QPushButton[kind="primary"]:disabled, QPushButton[kind="danger"]:disabled {{
    background: {surface}; border-color: {border}; color: #565d6e; }}
QPushButton[kind="icon"] {{ min-width: 32px; max-width: 32px; padding: 0; }}
QLineEdit:focus, QComboBox:focus, QPushButton:focus {{ border-color: {accent}; }}
QComboBox::drop-down {{ width: 24px; border: 0; }}
QComboBox QAbstractItemView {{ background: {surface}; border: 1px solid {border};
                               selection-background-color: {accent_soft}; outline: none; }}

QCheckBox {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px;
                        border: 1px solid {border_strong}; background: {surface_hover}; }}
QCheckBox::indicator:checked {{ background: {accent}; border-color: {accent}; }}

QListWidget#deviceList {{ border: 0; outline: none; }}
QListWidget#deviceList::item {{ padding: 9px 10px; border-radius: 8px; }}
QListWidget#deviceList::item:hover {{ background: {surface_hover}; }}
QListWidget#deviceList::item:selected {{ background: {accent_soft}; color: {text_strong}; }}

QScrollArea {{ border: 0; }}
QScrollBar:vertical {{ width: 10px; background: transparent; }}
QScrollBar::handle:vertical {{ background: {border_strong}; border-radius: 5px; min-height: 30px; }}
QScrollBar:horizontal {{ height: 10px; background: transparent; }}
QScrollBar::handle:horizontal {{ background: {border_strong}; border-radius: 5px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QSplitter::handle {{ background: transparent; }}
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setStyleSheet(_STYLESHEET.format(**COLORS))


def repolish(widget: QWidget) -> None:
    """Re-apply the stylesheet after a dynamic property such as ``kind`` changes."""

    widget.style().unpolish(widget)
    widget.style().polish(widget)
