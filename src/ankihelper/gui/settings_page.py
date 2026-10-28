from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .. import agents, config, dictation, jobs, learning
from ..config import Config
from . import theme
from .common import Page, card, label, language_box

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
        self.suggested = QVBoxLayout()
        self.suggested.setSpacing(8)
        layout.addLayout(self.suggested)
        self.reload_rules()

        layout.addSpacing(8)
        layout.addWidget(label("Rule updates", "sectionTitle"))
        layout.addWidget(label(
            "Apply a rule to cards you already have. It runs in the background while Anki is open, 10 cards at a time, "
            "and only changes cards the rule applies to. Every change can be undone, and when you push back on an updated "
            "card in Anki (F), the rule is reworded and the cards already updated are rechecked.",
            "muted", wrap=True,
        ))
        start_row = QHBoxLayout()
        self.job_rule = QComboBox()
        self.job_rule.setEditable(True)
        self.job_scope = QComboBox()
        for key, (title, _query) in jobs.SCOPES.items():
            self.job_scope.addItem(title, key)
        self.job_start = QPushButton("▶ Apply to existing cards")
        self.job_start.clicked.connect(self._start_job)
        start_row.addWidget(self.job_rule, 3)
        start_row.addWidget(self.job_scope, 2)
        start_row.addWidget(self.job_start)
        layout.addLayout(start_row)
        self.job_status = label("", "faint", wrap=True)
        layout.addWidget(self.job_status)
        self.job_list = QVBoxLayout()
        self.job_list.setSpacing(8)
        layout.addLayout(self.job_list)
        self.reload_jobs()

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
        while self.suggested.count():
            item = self.suggested.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        items = learning.suggestions()
        if items:
            self.suggested.addWidget(label("SUGGESTED FROM HOW YOU EDIT AND DELETE CARDS IN ANKI", "fieldLabel"))
        for item in items:
            self.suggested.addWidget(self._suggestion(item))

    def _accept_suggestion(self, suggestion_id: str, rule: str) -> None:
        learning.accept(suggestion_id, rule)
        self.reload_rules()
        self.prefill_rule(rule)
        self.job_status.setText("Rule added. Apply it to your existing cards with ▶ below, or leave it for new cards only.")

    def prefill_rule(self, rule: str) -> None:
        self.reload_jobs()
        self.job_rule.setCurrentText(rule)

    def reload_jobs(self) -> None:
        rules = [line.lstrip("- ").strip() for line in config.personal_rules().splitlines() if line.strip()]
        current = self.job_rule.currentText()
        self.job_rule.clear()
        self.job_rule.addItems(rules)
        if current:
            self.job_rule.setCurrentText(current)
        while self.job_list.count():
            item = self.job_list.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        for job in reversed(jobs.all_jobs()):
            self.job_list.addWidget(self._job_row(job))

    def _job_row(self, job: dict) -> QWidget:
        frame = card()
        row = QHBoxLayout(frame)
        row.setContentsMargins(14, 10, 10, 10)
        text = QVBoxLayout()
        title = label(job["rule"], wrap=True)
        title.setStyleSheet("font-weight: 700;")
        text.addWidget(title)
        total, done = len(job["queue"]), min(job["next"], len(job["queue"]))
        state = "undone" if job.get("undone") else job["status"]
        text.addWidget(label(
            f"{jobs.SCOPES[job['scope']][0]} · {done}/{total} checked · {len(job['changed'])} updated · {state}"
            + (f" · rule v{job['version']}" if job["version"] > 1 else ""),
            "faint",
        ))
        row.addLayout(text, 1)
        if job["status"] == jobs.RUNNING:
            pause = QPushButton("⏸ Pause")
            pause.clicked.connect(lambda: (jobs.pause(job["id"]), self.reload_jobs()))
            row.addWidget(pause)
        elif job["status"] == jobs.PAUSED:
            go = QPushButton("▶ Resume")
            go.clicked.connect(lambda: (jobs.resume(job["id"]), self.reload_jobs()))
            row.addWidget(go)
        if job["changed"] and not job.get("undone"):
            undo = QPushButton("↶ Undo all")
            undo.setToolTip("Put back every card this rule changed")
            undo.clicked.connect(lambda: self._undo_job(job["id"]))
            row.addWidget(undo)
        return frame

    def _start_job(self) -> None:
        from ..anki import AnkiConnect
        from .worker import run_async

        rule, scope = self.job_rule.currentText().strip(), self.job_scope.currentData()
        if not rule:
            self.job_status.setText("Pick or type a rule first.")
            return
        self.job_start.setEnabled(False)
        self.job_status.setText("Finding the cards it could apply to…")

        def done(job) -> None:
            self.job_start.setEnabled(True)
            self.job_status.setText(f"Queued {len(job['queue'])} cards. The Anki add-on works through them in the background while Anki is open.")
            self.reload_jobs()

        def failed(error: str) -> None:
            self.job_start.setEnabled(True)
            self.job_status.setText(f"⚠ {error} (Anki needs to be open)")

        run_async(lambda: jobs.start(self.cfg, AnkiConnect(self.cfg.anki_url), rule, scope), done, failed)

    def _undo_job(self, job_id: str) -> None:
        from ..anki import AnkiConnect
        from .worker import run_async

        self.job_status.setText("Putting the cards back…")
        run_async(
            lambda: jobs.undo(self.cfg, AnkiConnect(self.cfg.anki_url), job_id),
            lambda count: (self.job_status.setText(f"Put back {count} cards."), self.reload_jobs()),
            lambda error: self.job_status.setText(f"⚠ {error} (Anki needs to be open)"),
        )

    def _suggestion(self, item: dict) -> QWidget:
        frame = card()
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(14, 10, 10, 10)
        text = QVBoxLayout()
        rule = QPlainTextEdit(item["rule"])
        rule.setFixedHeight(80)
        text.addWidget(rule)
        if item.get("evidence"):
            text.addWidget(label(item["evidence"], "faint", wrap=True))
        layout.addLayout(text, 1)
        add = QPushButton("＋ Add rule")
        add.clicked.connect(lambda: self._accept_suggestion(item["id"], rule.toPlainText().strip()))
        dismiss = QPushButton("✕")
        dismiss.setObjectName("danger")
        dismiss.setToolTip("Dismiss this suggestion")
        dismiss.clicked.connect(lambda: (learning.dismiss(item["id"]), self.reload_rules()))
        layout.addWidget(add)
        layout.addWidget(dismiss)
        return frame

    def _save_rules(self) -> None:
        text = self.rules.toPlainText().strip()
        config.rules_path().write_text(text + "\n" if text else "")

    def _set_text(self, key: str, value: str) -> None:
        value = value.strip()
        if value and getattr(self.cfg, key) != value:
            setattr(self.cfg, key, value)
            self.cfg.save()
            self.changed.emit()
