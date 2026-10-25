from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QVBoxLayout, QWidget

from . import theme


def label(text: str, name: str = "", wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    if name:
        widget.setObjectName(name)
    widget.setWordWrap(wrap)
    return widget


def pill(text: str, color: str) -> QLabel:
    widget = QLabel(text)
    widget.setStyleSheet(theme.pill_style(color))
    return widget


def card() -> QFrame:
    frame = QFrame()
    frame.setObjectName("card")
    return frame


def restyle(widget: QWidget) -> None:
    """Re-apply the stylesheet after a dynamic property used by a selector changed."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class Page(QWidget):
    def __init__(self, title: str, subtitle: str, color: str):
        super().__init__()
        self.setObjectName("page")
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(36, 30, 36, 28)
        self.layout_.setSpacing(14)
        header = QHBoxLayout()
        bar = QFrame()
        bar.setFixedSize(6, 46)
        bar.setStyleSheet(f"background: {color}; border-radius: 3px;")
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(label(title, "title"))
        self.subtitle = label(subtitle, "subtitle", wrap=True)
        titles.addWidget(self.subtitle)
        header.addWidget(bar)
        header.addSpacing(8)
        header.addLayout(titles, 1)
        self.header = header
        self.layout_.addLayout(header)
        self.layout_.addSpacing(6)

    def shown(self) -> None:
        """Called each time the page becomes visible."""


class TextBox(QPlainTextEdit):
    def __init__(self, placeholder: str, accent: str):
        super().__init__()
        self.setPlaceholderText(placeholder)
        self.setTabChangesFocus(True)
        self.setProperty("accent", accent)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
