import sys

from PySide6.QtCore import QProcess, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QPlainTextEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget

from .. import inbox
from ..config import Config
from . import theme
from .common import Page, card, label, pill


class InboxPage(Page):
    changed = Signal()

    def __init__(self, cfg: Config):
        super().__init__("Inbox", "Cards waiting for the agent. Process them when you finish studying.", theme.AMBER)
        self.cfg = cfg
        self.process: QProcess | None = None

        self.run_button = QPushButton("✨  Process batch")
        self.run_button.setObjectName("primary")
        self.run_button.clicked.connect(self.run_batch)
        self.header.addWidget(self.run_button, 0, Qt.AlignmentFlag.AlignVCenter)

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

    def count(self) -> int:
        return len(inbox.read_all())

    def refresh(self) -> None:
        while self.list.count():
            item = self.list.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
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
        if entry.cards:
            tags.addWidget(pill(f"{len(entry.cards)} cleaned, retrying import", theme.CYAN))
        if entry.attempts:
            tags.addWidget(pill(f"failed {entry.attempts}×", theme.RED))
        tags.addStretch()
        text.addLayout(tags)
        if entry.error:
            text.addWidget(label(entry.error, "error", wrap=True))
        layout.addLayout(text, 1)
        delete = QPushButton("✕")
        delete.setObjectName("danger")
        delete.setToolTip("Delete this card")
        delete.clicked.connect(lambda: self._delete(entry.id))
        layout.addWidget(delete, 0, Qt.AlignmentFlag.AlignTop)
        return frame

    def _delete(self, entry_id: str) -> None:
        inbox.remove(entry_id)
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
