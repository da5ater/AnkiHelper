from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTextBrowser,
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


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")


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
            "Apply a rule to cards you already have. It runs in the background while Anki is open, one batch of cards at a time, "
            "and only changes cards the rule applies to. Every change can be undone, and when you push back on an updated "
            "card in Anki (F), the rule is reworded and the cards already updated are rechecked.",
            "muted", wrap=True,
        ))
        self.rule_picker = QDialog(self)
        self.rule_picker.setWindowTitle("Choose rules")
        self.rule_picker.resize(560, 460)
        picker = QVBoxLayout(self.rule_picker)
        picker.addWidget(label("Tick the rules to apply to your existing cards, or to delete.", "muted", wrap=True))
        self.rule_list = QListWidget()
        self.rule_list.setObjectName("ruleList")
        self.rule_list.setWordWrap(True)
        self.rule_list.itemChanged.connect(lambda _item: self._update_picker_button())
        picker.addWidget(self.rule_list, 1)
        list_buttons = QHBoxLayout()
        select_all = QPushButton("Select all")
        select_all.clicked.connect(lambda: self._check_all(True))
        clear = QPushButton("Select none")
        clear.clicked.connect(lambda: self._check_all(False))
        delete = QPushButton("🗑 Delete ticked")
        delete.clicked.connect(self._delete_checked)
        done = QPushButton("Done")
        done.setObjectName("primary")
        done.clicked.connect(self.rule_picker.accept)
        for button in (select_all, clear, delete):
            list_buttons.addWidget(button)
        list_buttons.addStretch()
        list_buttons.addWidget(done)
        picker.addLayout(list_buttons)
        self.picker_button = QPushButton("Choose rules ▾")
        self.picker_button.setToolTip("Open the list of your rules to tick, untick or delete them")
        self.picker_button.clicked.connect(self.rule_picker.exec)
        start_row = QHBoxLayout()
        self.job_scope = QComboBox()
        for key, (title, _query) in jobs.SCOPES.items():
            self.job_scope.addItem(title, key)
        self.job_start = QPushButton("▶ Apply to existing cards")
        self.job_start.clicked.connect(self._start_job)
        start_row.addWidget(self.picker_button, 2)
        start_row.addWidget(self.job_scope, 2)
        start_row.addWidget(self.job_start)
        layout.addLayout(start_row)
        size_row = QHBoxLayout()
        size_row.addWidget(label("Cards per batch", "muted"))
        self.batch_size = QSpinBox()
        self.batch_size.setRange(5, jobs.MAX_BATCH)
        self.batch_size.setSingleStep(5)
        self.batch_size.setValue(cfg.rule_batch_size)
        self.batch_size.setToolTip("How many cards the agent judges in one call. Smaller batches are slower but more careful.")
        self.batch_size.valueChanged.connect(self._set_batch_size)
        size_row.addWidget(self.batch_size)
        size_row.addStretch()
        layout.addLayout(size_row)
        self.job_status = label("", "faint", wrap=True)
        layout.addWidget(self.job_status)
        self.job_list = QVBoxLayout()
        self.job_list.setSpacing(8)
        layout.addLayout(self.job_list)
        self.reload_jobs()
        self._jobs_stamp = 0.0
        self.jobs_timer = QTimer(self)
        self.jobs_timer.timeout.connect(self._refresh_jobs_if_changed)
        self.jobs_timer.start(4000)

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
        self.job_status.setText("Rule added and ticked below. Apply it to your existing cards with ▶, or leave it for new cards only.")

    def _set_batch_size(self, value: int) -> None:
        self.cfg.rule_batch_size = value
        self.cfg.save()

    def prefill_rule(self, rule: str) -> None:
        self.reload_jobs()
        for i in range(self.rule_list.count()):
            item = self.rule_list.item(i)
            if item.text() == rule:
                item.setCheckState(Qt.CheckState.Checked)

    def _rules(self) -> list[str]:
        return [line.lstrip("- ").strip() for line in config.personal_rules().splitlines() if line.strip()]

    def _checked(self) -> list[str]:
        return [
            self.rule_list.item(i).text()
            for i in range(self.rule_list.count())
            if self.rule_list.item(i).checkState() == Qt.CheckState.Checked
        ]

    def _update_picker_button(self) -> None:
        ticked, total = len(self._checked()), len(self._rules())
        self.picker_button.setText(f"Rules: {ticked} of {total} ticked ▾" if total else "No rules yet ▾")

    def _check_all(self, on: bool) -> None:
        for i in range(self.rule_list.count()):
            self.rule_list.item(i).setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)

    def _delete_checked(self) -> None:
        doomed = set(self._checked())
        if not doomed:
            self.job_status.setText("Tick the rules to delete first.")
            return
        keep = [r for r in self._rules() if r not in doomed]
        config.rules_path().write_text("".join(f"- {r}\n" for r in keep))
        self.reload_rules()
        self.reload_jobs()
        self.job_status.setText(f"Deleted {len(doomed)} rule(s). Cards already changed by them stay as they are (use Undo all on a job to revert).")

    def reload_jobs(self) -> None:
        checked = set(self._checked()) if self.rule_list.count() else set()
        self.rule_list.clear()
        for rule in self._rules():
            item = QListWidgetItem(rule)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if rule in checked else Qt.CheckState.Unchecked)
            self.rule_list.addItem(item)
        if not self.rule_list.count():
            placeholder = QListWidgetItem("No rules yet. Save one from Preview, add a suggestion above, or type rules in Personal rules.")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self.rule_list.addItem(placeholder)
        self._update_picker_button()
        while self.job_list.count():
            item = self.job_list.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        for job in reversed(jobs.all_jobs()):
            self.job_list.addWidget(self._job_row(job))

    def _job_row(self, job: dict) -> QWidget:
        frame = card()
        outer = QVBoxLayout(frame)
        outer.setContentsMargins(14, 10, 10, 10)
        outer.setSpacing(6)
        rules = jobs.rules_of(job)
        title = label(rules[0] + (f"   +{len(rules) - 1} more" if len(rules) > 1 else ""), wrap=True)
        title.setStyleSheet("font-weight: 700;")
        title.setToolTip("\n".join(f"• {r}" for r in rules))
        outer.addWidget(title)
        total, done = len(job["queue"]), min(job["next"], len(job["queue"]))
        bar = QProgressBar()
        bar.setRange(0, max(1, total))
        bar.setValue(done)
        bar.setTextVisible(False)
        bar.setFixedHeight(6)
        outer.addWidget(bar)
        state = "undone" if job.get("undone") else {"running": "running", "paused": "paused", "done": "done"}[job["status"]]
        left = jobs.time_left(job, self.cfg.rule_batch_size)
        outer.addWidget(label(
            f"{done:,} / {total:,} checked · {len(job['changed']):,} changed · {state}"
            + (f" · {left}" if left else "")
            + (f" · rule v{job['version']}" if job["version"] > 1 else "")
            + f" · {jobs.SCOPES[job['scope']][0]}",
            "faint",
        ))
        row = QHBoxLayout()
        row.addStretch()
        if job["status"] == jobs.RUNNING:
            pause = QPushButton("⏸ Pause")
            pause.clicked.connect(lambda: (jobs.pause(job["id"]), self.reload_jobs()))
            row.addWidget(pause)
        elif job["status"] == jobs.PAUSED:
            go = QPushButton("▶ Resume")
            go.clicked.connect(lambda: (jobs.resume(job["id"]), self.reload_jobs()))
            row.addWidget(go)
        if job["changed"] and not job.get("undone"):
            see = QPushButton("👁 See changes")
            see.setToolTip("The latest cards this rule changed, before and after")
            see.clicked.connect(lambda: self._show_changes(job))
            row.addWidget(see)
            undo = QPushButton("↶ Undo all")
            undo.setToolTip("Put back every card this rule changed")
            undo.clicked.connect(lambda: self._undo_job(job["id"]))
            row.addWidget(undo)
        outer.addLayout(row)
        return frame

    def _refresh_jobs_if_changed(self) -> None:
        """Keep running jobs' progress current while Settings is on screen, without touching the rule list."""
        if not self.isVisible():
            return
        path = jobs._path()
        stamp = path.stat().st_mtime if path.exists() else 0
        if stamp == self._jobs_stamp:
            return
        self._jobs_stamp = stamp
        while self.job_list.count():
            item = self.job_list.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        for job in reversed(jobs.all_jobs()):
            self.job_list.addWidget(self._job_row(job))

    def _show_changes(self, job: dict) -> None:
        from ..anki import AnkiConnect
        from .worker import run_async

        recent = jobs.recent_changes(job["id"])
        dialog = QDialog(self)
        dialog.setWindowTitle("What this rule changed")
        dialog.resize(720, 620)
        layout = QVBoxLayout(dialog)
        layout.addWidget(label(f"The latest {len(recent)} of {len(job['changed']):,} cards this rule changed, newest first.", "muted", wrap=True))
        view = QTextBrowser()
        view.setObjectName("preview")
        view.setHtml("<p>Loading the cards from Anki…</p>")
        layout.addWidget(view, 1)
        buttons = QHBoxLayout()
        browse = QPushButton("Open all in Anki")
        browse.setToolTip("Show every card this rule changed in Anki's browser")
        anki = AnkiConnect(self.cfg.anki_url)
        browse.clicked.connect(lambda: run_async(lambda: anki.invoke("guiBrowse", query=f"tag:ah::rule::{job['id']}"), lambda _: None, lambda _: None))
        close = QPushButton("Close")
        close.clicked.connect(dialog.accept)
        buttons.addWidget(browse)
        buttons.addStretch()
        buttons.addWidget(close)
        layout.addLayout(buttons)

        def load():
            from .. import bridge

            infos = anki.notes_info([c["note_id"] for c in recent]) if recent else []
            parts = []
            for change, info in zip(recent, infos):
                before = list(change["fields"].values())
                after = sorted(info["fields"].items(), key=lambda kv: kv[1]["order"]) if info else []
                q_now = bridge.text_of(after[0][1]["value"]) if after else "(deleted)"
                a_now = bridge.text_of(after[1][1]["value"]) if len(after) > 1 else ""
                parts.append(
                    f"<p><b>{_escape(q_now)}</b><br><span style='color:{theme.FAINT}'>{change['time'].replace('T', ' ')}</span></p>"
                    f"<p><span style='color:{theme.RED}'>Before:</span> {_escape(bridge.text_of(before[1])[:400])}</p>"
                    f"<p><span style='color:{theme.GREEN}'>After:</span> {_escape(a_now[:400])}</p><hr>"
                )
            return "".join(parts) or "<p>No changed cards yet.</p>"

        run_async(load, view.setHtml, lambda error: view.setHtml(f"<p>⚠ {error} (Anki needs to be open)</p>"))
        dialog.exec()

    def _start_job(self) -> None:
        from ..anki import AnkiConnect
        from .worker import run_async

        rules, scope = self._checked(), self.job_scope.currentData()
        if not rules:
            self.job_status.setText("Tick at least one rule first (Choose rules ▾).")
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

        run_async(lambda: jobs.start(self.cfg, AnkiConnect(self.cfg.anki_url), rules, scope), done, failed)

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
        self.reload_jobs()

    def _set_text(self, key: str, value: str) -> None:
        value = value.strip()
        if value and getattr(self.cfg, key) != value:
            setattr(self.cfg, key, value)
            self.cfg.save()
            self.changed.emit()
