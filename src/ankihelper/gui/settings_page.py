from PySide6.QtCore import Signal
from PySide6.QtWidgets import QButtonGroup, QFormLayout, QGridLayout, QLineEdit, QPlainTextEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget

from .. import agents, config, dictation
from ..config import Config
from . import theme
from .common import Page, label, language_box

AGENT_BLURBS = {
    "claude": "Claude Code",
    "codex": "OpenAI Codex CLI",
    "gemini": "Google Gemini CLI",
    "opencode": "OpenCode",
}
DICTATION_COLORS = {"voxtype": theme.PINK, "system": theme.BLUE, "none": theme.MUTED}


def tile(title: str, blurb: str, color: str) -> QPushButton:
    button = QPushButton(f"{title}\n{blurb}")
    button.setObjectName("tile")
    button.setCheckable(True)
    button.setMinimumHeight(70)
    button.setStyleSheet(
        f"QPushButton#tile:checked {{ border-color: {color}; background: {theme.rgba(color, 0.14)}; }}"
        f"QPushButton#tile:hover {{ border-color: {theme.rgba(color, 0.6)}; }}"
    )
    return button


class SettingsPage(Page):
    changed = Signal()

    def __init__(self, cfg: Config):
        super().__init__("Settings", "Pick your agent and how you dictate. Changes save right away.", theme.CYAN)
        self.cfg = cfg
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(12)

        layout.addWidget(label("Agent", "sectionTitle"))
        layout.addWidget(label("Cleans your cards in a batch and fixes setup problems.", "muted"))
        self.agent_group, agent_grid = self._tiles(
            [
                (name, name.capitalize(), f"{AGENT_BLURBS[name]} · {'installed' if agents.installed(name) else 'not installed'}", theme.AGENT_COLORS[name])
                for name in agents.AGENTS
            ],
            cfg.agent,
            self._set_agent,
        )
        layout.addLayout(agent_grid)

        layout.addSpacing(8)
        layout.addWidget(label("Dictation", "sectionTitle"))
        self.dictation_group, dictation_grid = self._tiles(
            [(m.id, m.title, m.blurb, DICTATION_COLORS[m.id]) for m in dictation.METHODS],
            cfg.dictation,
            self._set_dictation,
            columns=1,
        )
        layout.addLayout(dictation_grid)
        self.dictation_status = label("", "faint", wrap=True)
        layout.addWidget(self.dictation_status)
        self._update_dictation_status()

        layout.addSpacing(8)
        layout.addWidget(label("Card language", "sectionTitle"))
        layout.addWidget(label("Cards are written in this language whatever you dictate or paste. Capture can override it per card.", "muted", wrap=True))
        self.language = language_box(cfg.language)
        self.language.currentTextChanged.connect(lambda text: self._set_text("language", text))
        layout.addWidget(self.language)

        layout.addSpacing(8)
        layout.addWidget(label("Personal rules", "sectionTitle"))
        layout.addWidget(label("Your standing instructions for every card. Saved from Preview, or write your own, one per line.", "muted", wrap=True))
        self.rules = QPlainTextEdit()
        self.rules.setPlaceholderText("- Prefer why and when questions over definitions.")
        self.rules.setMinimumHeight(110)
        self.rules.textChanged.connect(self._save_rules)
        layout.addWidget(self.rules)
        self.reload_rules()

        layout.addSpacing(8)
        layout.addWidget(label("Anki", "sectionTitle"))
        form = QFormLayout()
        form.setVerticalSpacing(10)
        form.setHorizontalSpacing(16)
        for key, title in (("root_deck", "Root deck"), ("note_type", "Note type"), ("anki_url", "AnkiConnect URL")):
            field = QLineEdit(getattr(cfg, key))
            field.editingFinished.connect(lambda key=key, field=field: self._set_text(key, field.text()))
            form.addRow(label(title, "muted"), field)
        layout.addLayout(form)
        layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        self.layout_.addWidget(scroll, 1)

    def _tiles(self, items, current: str, on_pick, columns: int = 2):
        group = QButtonGroup(self)
        group.setExclusive(True)
        grid = QGridLayout()
        grid.setSpacing(10)
        for index, (key, title, blurb, color) in enumerate(items):
            button = tile(title, blurb, color)
            button.setChecked(key == current)
            button.clicked.connect(lambda _=False, key=key: on_pick(key))
            group.addButton(button)
            grid.addWidget(button, index // columns, index % columns)
        return group, grid

    def _set_agent(self, name: str) -> None:
        self.cfg.agent = name
        self.cfg.save()
        self.changed.emit()

    def _set_dictation(self, method: str) -> None:
        self.cfg.dictation = method
        self.cfg.save()
        self._update_dictation_status()
        self.changed.emit()

    def _update_dictation_status(self) -> None:
        ok, detail = dictation.status(self.cfg.dictation)
        self.dictation_status.setText(("✓ " if ok else "⚠ ") + detail)
        self.dictation_status.setStyleSheet(f"color: {theme.GREEN if ok else theme.AMBER};")

    def reload_rules(self) -> None:
        self.rules.blockSignals(True)
        self.rules.setPlainText(config.personal_rules())
        self.rules.blockSignals(False)

    def _save_rules(self) -> None:
        text = self.rules.toPlainText().strip()
        config.rules_path().write_text(text + "\n" if text else "")

    def _set_text(self, key: str, value: str) -> None:
        value = value.strip()
        if value and getattr(self.cfg, key) != value:
            setattr(self.cfg, key, value)
            self.cfg.save()
            self.changed.emit()
