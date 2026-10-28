from pathlib import Path

from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

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


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}


def image_from(mime: QMimeData) -> QImage | None:
    """A picture copied from a browser or screenshot tool, or an image file copied in a file manager."""
    if mime.hasImage():
        image = QImage(mime.imageData())
        if not image.isNull():
            return image
    for url in mime.urls():
        if url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() in IMAGE_SUFFIXES:
            image = QImage(url.toLocalFile())
            if not image.isNull():
                return image
    return None


class TextBox(QPlainTextEdit):
    image_pasted = Signal(QImage)

    def __init__(self, placeholder: str, accent: str):
        super().__init__()
        self.setPlaceholderText(placeholder)
        self.setTabChangesFocus(True)
        self.setProperty("accent", accent)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)

    def canInsertFromMimeData(self, source: QMimeData) -> bool:
        return image_from(source) is not None or super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source: QMimeData) -> None:
        image = image_from(source)
        if image is not None:
            self.image_pasted.emit(image)
        else:
            super().insertFromMimeData(source)


class ImageStrip(QWidget):
    """Thumbnails of the pictures pasted into one field, each with a remove button."""

    THUMB_HEIGHT = 72

    def __init__(self):
        super().__init__()
        self.images: list[QImage] = []
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(8)
        self.hide()

    def add(self, image: QImage) -> None:
        self.images.append(image)
        self._render()

    def clear(self) -> None:
        self.images.clear()
        self._render()

    def _remove(self, index: int) -> None:
        del self.images[index]
        self._render()

    def _render(self) -> None:
        while self.row.count():
            item = self.row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for index, image in enumerate(self.images):
            frame = QFrame()
            frame.setObjectName("thumb")
            layout = QHBoxLayout(frame)
            layout.setContentsMargins(4, 4, 4, 4)
            layout.setSpacing(2)
            picture = QLabel()
            picture.setPixmap(
                QPixmap.fromImage(image).scaledToHeight(self.THUMB_HEIGHT, Qt.TransformationMode.SmoothTransformation)
            )
            picture.setToolTip(f"{image.width()}×{image.height()}")
            remove = QPushButton("✕")
            remove.setObjectName("danger")
            remove.setToolTip("Remove picture")
            remove.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            remove.clicked.connect(lambda _=False, index=index: self._remove(index))
            layout.addWidget(picture)
            layout.addWidget(remove, 0, Qt.AlignmentFlag.AlignTop)
            self.row.addWidget(frame)
        self.row.addStretch()
        self.setVisible(bool(self.images))
