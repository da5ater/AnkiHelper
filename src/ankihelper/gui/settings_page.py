from PySide6.QtCore import Signal
from PySide6.QtWidgets import QButtonGroup, QComboBox, QFormLayout, QGridLayout, QLineEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget

from .. import agents, dictation
from ..config import Config
from . import theme
from .common import Page, label, language_box

AGENT_BLURBS = {
    "claude": "Claude Code",
    "codex": "OpenAI Codex CLI",
    "gemini": "Google Gemini CLI",
    "opencode": "OpenCode",
}
DICTATION_COLORS = {"hex": theme.GREEN, "voxtype": theme.PINK, "system": theme.BLUE, "none": theme.MUTED}


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
        layout.addWidget(label("Writes your cards in a batch, runs your moves and fixes setup problems.", "muted"))
        self.agent_group, agent_grid = self._tiles(
            [
                (name, name.capitalize(), f"{AGENT_BLURBS[name]} · {'installed' if agents.installed(name) else 'not installed'}", theme.AGENT_COLORS[name])
                for name in agents.AGENTS
            ],
            cfg.agent,
            self._set_agent,
        )
        layout.addLayout(agent_grid)
        model_row = QFormLayout()
        self.model = QComboBox()
        self.model.setMaxVisibleItems(15)
        self.model.activated.connect(lambda _: self._set_model(self.model.currentData()))
        self._model_lists: dict[str, list[tuple[str, str]]] = {}
        model_row.addRow(label("Model", "muted"), self.model)
        layout.addLayout(model_row)
        self.model_hint = label("", "faint", wrap=True)
        layout.addWidget(self.model_hint)
        self._show_model()

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
        self._show_model()
        self.changed.emit()

    def _show_model(self) -> None:
        agent = agents.get(self.cfg.agent)
        if agent.name not in self._model_lists:
            self._model_lists[agent.name] = agent.models() if agents.installed(agent.name) else []
        current = self.cfg.models.get(agent.name, "")
        choices = [("", f"Default ({agent.name.capitalize()}'s own setting)"), *self._model_lists[agent.name]]
        if current and current not in {name for name, _ in choices}:
            choices.append((current, current))
        self.model.blockSignals(True)
        self.model.clear()
        for name, title in choices:
            self.model.addItem(title if title == name or not name else f"{title}  ·  {name}", name)
        self.model.setCurrentIndex(self.model.findData(current))
        self.model.blockSignals(False)
        self.model_hint.setText(f"Used for everything {agent.name.capitalize()} does here: batches, moves and the F window in Anki.")

    def _set_model(self, model: str) -> None:
        model = model.strip()
        if self.cfg.models.get(self.cfg.agent, "") != model:
            self.cfg.models = {**self.cfg.models, self.cfg.agent: model}
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

    def _set_text(self, key: str, value: str) -> None:
        value = value.strip()
        if value and getattr(self.cfg, key) != value:
            setattr(self.cfg, key, value)
            self.cfg.save()
            self.changed.emit()
