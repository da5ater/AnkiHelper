import re
from dataclasses import asdict

from PySide6.QtCore import QProcess, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QPlainTextEdit, QPushButton, QTextBrowser, QVBoxLayout

from .. import batch, config, inbox, review
from ..anki import AnkiConnect
from ..config import Config
from . import theme
from .common import Page, TextBox, card, label
from .worker import run_async

PR_URL = re.compile(r"https://github\.com/\S+/pull/\d+")


class ReviewPage(Page):
    back = Signal()
    changed = Signal()

    def __init__(self, cfg: Config):
        super().__init__("Preview", "See the cards before they reach Anki. Redo them with feedback until they're right.", theme.VIOLET)
        self.cfg = cfg
        self.review: review.Review | None = None
        self.busy = False
        self.process: QProcess | None = None
        self.worktree = None

        back = QPushButton("←  Inbox")
        back.clicked.connect(self.back.emit)
        self.header.insertWidget(0, back, 0, Qt.AlignmentFlag.AlignVCenter)
        self.header.insertSpacing(1, 10)

        self.note = label("", "muted", wrap=True)
        self.layout_.addWidget(self.note)

        self.preview = QTextBrowser()
        self.preview.setObjectName("preview")
        self.preview.setOpenExternalLinks(True)
        self.preview.setSearchPaths([str(config.media_dir())])
        self.layout_.addWidget(self.preview, 1)

        self.status = label("", "faint", wrap=True)
        self.layout_.addWidget(self.status)

        self.feedback = TextBox("What should change?  e.g. ask why, not what · shorter answers · use the bullets", "violet")
        self.feedback.setMaximumHeight(70)
        self.layout_.addWidget(self.feedback)

        actions = QHBoxLayout()
        self.redo_button = QPushButton("↻  Redo with feedback")
        self.redo_button.clicked.connect(self.redo)
        self.rule_button = QPushButton("📌  Make this a rule")
        self.rule_button.clicked.connect(self.suggest_rule)
        self.import_button = QPushButton("⬆  Import now")
        self.import_button.clicked.connect(self.import_now)
        self.keep_button = QPushButton("✓  Keep these cards")
        self.keep_button.setObjectName("primary")
        self.keep_button.clicked.connect(self.keep)
        for button in (self.redo_button, self.rule_button):
            actions.addWidget(button)
        actions.addStretch()
        actions.addWidget(self.import_button)
        actions.addWidget(self.keep_button)
        self.layout_.addLayout(actions)

        self.rule_panel = card()
        rule_layout = QVBoxLayout(self.rule_panel)
        rule_layout.setContentsMargins(14, 12, 14, 12)
        rule_layout.addWidget(label("PERSONAL RULE", "fieldLabel"))
        self.rule_text = QLineEdit()
        rule_layout.addWidget(self.rule_text)
        rule_buttons = QHBoxLayout()
        self.save_rule_button = QPushButton("Save rule")
        self.save_rule_button.clicked.connect(lambda: self.save_rule(propose=False))
        self.propose_button = QPushButton("Save + propose as PR")
        self.propose_button.setToolTip(f"Also asks the agent to build the rule into AnkiHelper itself and open a PR on {review.REPO}")
        self.propose_button.clicked.connect(lambda: self.save_rule(propose=True))
        rule_buttons.addWidget(label("Applies to every future card. Edit it first if you like.", "faint"), 1)
        rule_buttons.addWidget(self.save_rule_button)
        rule_buttons.addWidget(self.propose_button)
        rule_layout.addLayout(rule_buttons)
        self.rule_panel.hide()
        self.layout_.addWidget(self.rule_panel)

        self.log = QPlainTextEdit()
        self.log.setObjectName("log")
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(110)
        self.log.hide()
        self.layout_.addWidget(self.log)

    def open(self, entry: inbox.Entry) -> None:
        self.review = review.Review(entry)
        self.note.setText(f"<b>{entry.question or '(picture)'}</b><br>{entry.answer[:200]}")
        self.feedback.clear()
        self.rule_panel.hide()
        self.log.hide()
        self.preview.clear()
        self._run(lambda: review.generate(self.cfg, self.review), "Asking the agent for cards…")

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self.busy = busy
        has_cards = bool(self.review and self.review.cards)
        for button in (self.redo_button, self.keep_button, self.import_button):
            button.setEnabled(not busy and has_cards)
        self.rule_button.setEnabled(not busy and bool(self.review and len(self.review.rounds) > 1))
        self.status.setText(message)
        self.status.setStyleSheet("")

    def _run(self, fn, message: str, on_done=None) -> None:
        self._set_busy(True, "⏳ " + message)
        run_async(fn, on_done or (lambda _: self._show_cards()), self._failed)

    def _failed(self, error: str) -> None:
        self._set_busy(False)
        self.status.setText(f"⚠ {error}")
        self.status.setStyleSheet(f"color: {theme.RED};")

    def _show_cards(self) -> None:
        parts = []
        cards = self.review.cards
        for n, c in enumerate(cards, start=1):
            front, back = batch.card_html(c, self.review.entry)
            parts.append(
                f'<p style="color:{theme.FAINT}; font-size:11px; font-weight:700;">CARD {n} OF {len(cards)}'
                f'{" · CHANGED" if c.changed else ""} · {" ".join(c.tags)}</p>'
                f'<table width="100%" cellpadding="14" cellspacing="0" style="background:{theme.SURFACE_HI}; color:{theme.TEXT};">'
                f'<tr><td>{front}</td></tr>'
                f'<tr><td style="border-top:1px solid {theme.BORDER};">{back}</td></tr></table><br>'
            )
        self.preview.setHtml("".join(parts))
        rounds = len(self.review.rounds)
        self._set_busy(False, f"{len(cards)} card(s)" + (f" · round {rounds}" if rounds > 1 else "") + ". Keep them, or say what to change.")

    def redo(self) -> None:
        feedback = self.feedback.toPlainText().strip()
        if not feedback:
            self.status.setText("Write what should change first.")
            self.feedback.setFocus()
            return
        self.feedback.clear()
        self._run(lambda: review.generate(self.cfg, self.review, feedback), "Redoing with your feedback…")

    def keep(self) -> None:
        inbox.approve(self.review.entry.id, [asdict(c) for c in self.review.cards])
        self.changed.emit()
        self._set_busy(False, "✓ Kept. The next batch imports exactly these cards.")
        self.status.setStyleSheet(f"color: {theme.GREEN}; font-weight: 700;")

    def import_now(self) -> None:
        inbox.approve(self.review.entry.id, [asdict(c) for c in self.review.cards])
        entry_id = self.review.entry.id

        def done(summary) -> None:
            self.changed.emit()
            self._set_busy(False, f"✓ {summary.message()}")
            self.status.setStyleSheet(f"color: {theme.GREEN}; font-weight: 700;")

        self._run(lambda: batch.run(self.cfg, AnkiConnect(self.cfg.anki_url), only={entry_id}), "Importing into Anki…", done)

    def suggest_rule(self) -> None:
        def done(rule) -> None:
            self._set_busy(False)
            if rule is None:
                self.status.setText("Your feedback was about this card only, so there's no general rule to save.")
                return
            self.rule_text.setText(rule)
            self.rule_panel.show()
            self.rule_text.setFocus()

        self._run(lambda: review.suggest_rule(self.cfg, self.review), "Turning your feedback into a rule…", done)

    def save_rule(self, propose: bool) -> None:
        rule = self.rule_text.text().strip()
        if not rule:
            return
        review.save_rule(rule)
        self.rule_panel.hide()
        self.changed.emit()
        self.status.setText("📌 Rule saved. Every future card follows it (see Settings → Personal rules).")
        self.status.setStyleSheet(f"color: {theme.GREEN}; font-weight: 700;")
        if propose:
            self._propose(rule)

    def _propose(self, rule: str) -> None:
        try:
            cmd, self.worktree = review.pr_command(self.cfg, rule)
        except Exception as error:
            return self._failed(str(error))
        self.log.clear()
        self.log.show()
        self.log.appendPlainText(f"{self.cfg.agent} is building the rule into AnkiHelper in {self.worktree} …")
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.setWorkingDirectory(str(self.worktree))
        self.process.readyReadStandardOutput.connect(
            lambda: self.log.appendPlainText(bytes(self.process.readAllStandardOutput()).decode(errors="replace").rstrip())
        )
        self.process.finished.connect(self._proposed)
        self.process.start(cmd[0], cmd[1:])

    def _proposed(self, code: int, _status) -> None:
        url = PR_URL.findall(self.log.toPlainText())
        self.process = None
        review.remove_worktree(self.worktree)
        if url:
            self.status.setText(f'🚀 PR opened: <a href="{url[-1]}" style="color:{theme.CYAN}">{url[-1]}</a>')
            self.status.setOpenExternalLinks(True)
        else:
            self.status.setText(f"⚠ The agent finished (exit {code}) without opening a PR. The log above says why.")
