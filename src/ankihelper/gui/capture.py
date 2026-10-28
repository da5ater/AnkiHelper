from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QComboBox, QCompleter, QHBoxLayout, QPushButton, QVBoxLayout

from .. import config, dictation, inbox
from ..anki import AnkiConnect, AnkiError, AnkiUnreachable
from ..config import Config
from . import theme
from .common import ImageStrip, Page, TextBox, label, restyle

MIC_ICONS = {"idle": "🎙", "recording": "⏺", "transcribing": "✍"}


def topics(cfg: Config) -> list[str]:
    """Subdecks of the root deck, relative to it. Cached so capture works with Anki closed."""
    anki = AnkiConnect(cfg.anki_url)
    if anki.is_up(timeout=0.3):
        try:
            prefix = cfg.root_deck + "::"
            decks = anki.invoke("deckNames", timeout=1)
            cfg.known_topics = sorted(d[len(prefix) :] for d in decks if d.startswith(prefix))
            cfg.save()
        except (AnkiError, AnkiUnreachable):
            pass
    return cfg.known_topics


class CapturePage(Page):
    saved = Signal(str)
    close_requested = Signal()

    def __init__(self, cfg: Config, close_after_save: bool):
        super().__init__("New card", "Say it, don't polish it. The agent cleans it up when you run a batch.", theme.PINK)
        self.cfg = cfg
        self.close_after_save = close_after_save

        self.question = TextBox("What do you want to remember?   Ctrl+V pastes a picture", "violet")
        self.answer = TextBox("The answer, a command, a snippet… or a picture", "cyan")
        self.strips = {"question": ImageStrip(), "answer": ImageStrip()}
        self.question.image_pasted.connect(
            lambda image: self.strips["question"].add(image, "show" if self.question.toPlainText().strip() else "read")
        )
        self.answer.image_pasted.connect(lambda image: self.strips["answer"].add(image, "show"))
        self.topic = QComboBox()
        self.topic.setEditable(True)
        self.topic.addItems(topics(cfg))
        self.topic.setCurrentText(cfg.last_topic)
        self.topic.lineEdit().setPlaceholderText("ruby::rails")
        completer = QCompleter(self.topic.model(), self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.topic.setCompleter(completer)
        self.deck_hint = label("", "faint")
        self.topic.currentTextChanged.connect(self._update_deck_hint)
        self._update_deck_hint(self.topic.currentText())

        self.mic = QPushButton(MIC_ICONS["idle"])
        self.mic.setObjectName("mic")
        self.mic.setToolTip("Start or stop Voxtype")
        self.mic.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.mic.clicked.connect(self._toggle_mic)
        self.status = label("Ctrl+Enter save   ·   Tab next field   ·   Esc close", "faint")
        self.save_button = QPushButton("Save card  ⏎")
        self.save_button.setObjectName("primary")
        self.save_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.save_button.clicked.connect(self.save)

        for title, field, widget, stretch in (
            ("QUESTION", "question", self.question, 2),
            ("ANSWER", "answer", self.answer, 3),
        ):
            self.layout_.addWidget(label(title, "fieldLabel"))
            self.layout_.addWidget(widget, stretch)
            self.layout_.addWidget(self.strips[field])
        self.layout_.addWidget(label("TOPIC", "fieldLabel"))
        topic_row = QVBoxLayout()
        topic_row.setSpacing(4)
        topic_row.addWidget(self.topic)
        topic_row.addWidget(self.deck_hint)
        self.layout_.addLayout(topic_row)

        bottom = QHBoxLayout()
        bottom.addWidget(self.mic)
        bottom.addSpacing(8)
        bottom.addWidget(self.status, 1)
        bottom.addWidget(self.save_button)
        self.layout_.addSpacing(4)
        self.layout_.addLayout(bottom)

        for keys in ("Ctrl+Return", "Ctrl+Enter"):
            QShortcut(QKeySequence(keys), self, activated=self.save)

        self.mic_timer = QTimer(self)
        self.mic_timer.timeout.connect(self._poll_mic)
        self.refresh_dictation()

    def shown(self) -> None:
        self.question.setFocus()

    def refresh_dictation(self) -> None:
        voxtype = self.cfg.dictation == "voxtype"
        self.mic.setVisible(voxtype)
        if voxtype:
            self.mic_timer.start(600)
            self._poll_mic()
        else:
            self.mic_timer.stop()

    def _toggle_mic(self) -> None:
        dictation.toggle_voxtype()
        QTimer.singleShot(150, self._poll_mic)

    def _poll_mic(self) -> None:
        state = dictation.voxtype_state()
        self.mic.setEnabled(state is not None)
        self.mic.setToolTip("Voxtype daemon is not running" if state is None else f"Voxtype is {state}. Click to toggle.")
        state = state or "idle"
        if self.mic.property("state") != state:
            self.mic.setProperty("state", state)
            self.mic.setText(MIC_ICONS[state])
            restyle(self.mic)

    def _update_deck_hint(self, topic: str) -> None:
        topic = topic.strip().strip(":")
        new = topic and topic not in self.cfg.known_topics
        deck = f"{self.cfg.root_deck}::{topic}" if topic else self.cfg.root_deck
        self.deck_hint.setText(f"→ {deck}" + ("   (new deck)" if new else ""))

    def save(self) -> None:
        question, topic = self.question.toPlainText().strip(), self.topic.currentText().strip()
        if not question and not self.strips["question"].images:
            return self._flash("Say a question first.", theme.RED, self.question)
        if not topic:
            return self._flash("Pick a topic.", theme.RED, self.topic)
        entry = inbox.Entry.new(question, self.answer.toPlainText(), topic)
        entry.images = self._save_images(entry.id) or None
        inbox.append(entry)
        self.cfg.last_topic = topic
        self.cfg.save()
        self.saved.emit(entry.id)
        if self.close_after_save:
            self.close_requested.emit()
            return
        self.question.clear()
        self.answer.clear()
        for strip in self.strips.values():
            strip.clear()
        self._flash("✓ Saved to your inbox", theme.GREEN, self.question)

    def _save_images(self, entry_id: str) -> list[dict]:
        saved = []
        for field, strip in self.strips.items():
            for image, mode in strip.images:
                name = f"ankihelper-{entry_id}-{len(saved) + 1}.png"
                if not image.save(str(config.media_dir() / name), "PNG"):
                    raise OSError(f"could not save pasted picture {name}")
                saved.append({"file": name, "field": field, "mode": mode})
        return saved

    def _flash(self, message: str, color: str, focus) -> None:
        self.status.setText(message)
        self.status.setStyleSheet(f"color: {color}; font-weight: 700;")
        focus.setFocus()
