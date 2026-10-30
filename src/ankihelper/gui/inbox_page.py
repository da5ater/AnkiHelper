import sys

from PySide6.QtCore import QProcess, Qt, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QPlainTextEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget

from .. import inbox
from ..config import Config
from . import theme
from .common import Page, card, label, pill


class InboxPage(Page):
    changed = Signal()
    preview_requested = Signal(object)

    def __init__(self, cfg: Config):
        super().__init__("Inbox", "Cards waiting for the agent. Process them when you finish studying.", theme.AMBER)
        self.cfg = cfg
        self.process: QProcess | None = None

        self.run_button = QPushButton("✨  Process batch")
        self.run_button.setObjectName("primary")
        self.run_button.clicked.connect(self.run_batch)
        self.header.addWidget(self.run_button, 0, Qt.AlignmentFlag.AlignVCenter)

        self.notice = label("", wrap=True)
        self.notice.hide()
        self.layout_.addWidget(self.notice)
        self.removed: inbox.Entry | None = None
        self.undo_bar = QWidget()
        undo_row = QHBoxLayout(self.undo_bar)
        undo_row.setContentsMargins(14, 8, 8, 8)
        self.undo_label = label("", "muted", wrap=True)
        undo = QPushButton("↶ Undo")
        undo.clicked.connect(self.undo_remove)
        undo_row.addWidget(self.undo_label, 1)
        undo_row.addWidget(undo)
        self.undo_bar.setStyleSheet(f"background: {theme.SURFACE_HI}; border-radius: 12px;")
        self.undo_bar.hide()
        self.layout_.addWidget(self.undo_bar)

        self.list = QVBoxLayout()
        self.list.setSpacing(10)
        holder = QWidget()
        holder.setLayout(self.list)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(holder)
        self.layout_.addWidget(scroll, 1)

        self.log = QPlainTextEdit()
        self.log.setObjectName("log")
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(130)
        self.log.hide()
        self.layout_.addWidget(self.log)
        self.refresh()

    def shown(self) -> None:
        self.refresh()

    def flash(self, text: str) -> None:
        self.notice.setText(text)
        self.notice.setStyleSheet(
            f"background: {theme.rgba(theme.GREEN, 0.14)}; color: {theme.GREEN}; border: 1px solid {theme.GREEN};"
            "border-radius: 12px; padding: 10px 14px; font-weight: 700;"
        )
        self.notice.show()
        QTimer.singleShot(6000, self.notice.hide)

    def count(self) -> int:
        return len(inbox.read_all())

    def refresh(self) -> None:
        while self.list.count():
            item = self.list.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        entries = inbox.read_all()
        self.run_button.setEnabled(bool(entries) and self.process is None)
        if not entries:
            empty = label("Nothing waiting. Press Super+Alt+A while you study to add a card.", "muted", wrap=True)
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.list.addWidget(empty)
        for entry in entries:
            self.list.addWidget(self._entry_card(entry))
        self.list.addStretch()

    def _entry_card(self, entry: inbox.Entry) -> QWidget:
        frame = card()
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(16, 12, 8, 12)
        text = QVBoxLayout()
        text.setSpacing(4)
        question = label(entry.question, wrap=True)
        question.setStyleSheet("font-weight: 700; font-size: 15px;")
        text.addWidget(question)
        if entry.answer:
            answer = entry.answer if len(entry.answer) < 160 else entry.answer[:157] + "…"
            text.addWidget(label(answer, "muted", wrap=True))
        tags = QHBoxLayout()
        tags.addWidget(pill(f"{self.cfg.root_deck}::{entry.topic}", theme.PINK))
        shown = sum(image.get("mode", "show") == "show" for image in entry.images or [])
        if shown:
            tags.addWidget(pill(f"🖼 {shown}", theme.VIOLET))
        if len(entry.images or []) - shown:
            tags.addWidget(pill(f"📖 {len(entry.images) - shown} to read", theme.CYAN))
        if entry.cards and not entry.error:
            tags.addWidget(pill(f"✓ {len(entry.cards)} card(s) approved", theme.GREEN))
        elif entry.cards:
            tags.addWidget(pill(f"{len(entry.cards)} cleaned, retrying import", theme.CYAN))
        if entry.attempts:
            tags.addWidget(pill(f"failed {entry.attempts}×", theme.RED))
        tags.addStretch()
        text.addLayout(tags)
        if entry.error:
            text.addWidget(label(entry.error, "error", wrap=True))
        layout.addLayout(text, 1)
        preview = QPushButton("👁  Preview")
        preview.setToolTip("See the cards the agent would make, and redo them with feedback")
        preview.clicked.connect(lambda: self.preview_requested.emit(entry))
        layout.addWidget(preview, 0, Qt.AlignmentFlag.AlignVCenter)
        remove = QPushButton("🗑  Remove")
        remove.setToolTip("Take this entry out of the inbox; it won't be turned into cards (Undo brings it back)")
        remove.clicked.connect(lambda: self.remove(entry))
        layout.addWidget(remove, 0, Qt.AlignmentFlag.AlignVCenter)
        return frame

    def remove(self, entry: inbox.Entry) -> None:
        inbox.remove(entry.id)
        self.removed = entry
        title = entry.question or "the picture-only entry"
        self.undo_label.setText(f"Removed “{title[:80]}” from the inbox.")
        self.undo_bar.show()
        QTimer.singleShot(10000, lambda: self._hide_undo(entry))
        self.refresh()
        self.changed.emit()

    def _hide_undo(self, entry: inbox.Entry) -> None:
        if self.removed is entry:
            self.undo_bar.hide()
            self.removed = None

    def undo_remove(self) -> None:
        if self.removed is None:
            return
        inbox.append(self.removed)
        self.removed = None
        self.undo_bar.hide()
        self.refresh()
        self.changed.emit()

    def run_batch(self) -> None:
        if self.process is not None:
            return
        self.log.clear()
        self.log.show()
        self.log.appendPlainText(f"Running the batch with {self.cfg.agent}…")
        self.run_button.setEnabled(False)
        self.run_button.setText("⏳  Processing…")
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(
            lambda: self.log.appendPlainText(bytes(self.process.readAllStandardOutput()).decode(errors="replace").rstrip())
        )
        self.process.finished.connect(self._batch_done)
        self.process.start(sys.executable, ["-m", "ankihelper", "batch"])

    def _batch_done(self, code: int, _status) -> None:
        self.log.appendPlainText("Done." if code == 0 else f"Finished with problems (exit {code}).")
        self.process = None
        self.run_button.setText("✨  Process batch")
        self.refresh()
        self.changed.emit()
