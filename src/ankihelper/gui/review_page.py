import re
from dataclasses import asdict

from PySide6.QtCore import QPoint, QProcess, QProcessEnvironment, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .. import batch, config, inbox, review
from ..anki import AnkiConnect
from ..config import Config
from . import theme
from .common import Page, card, label, pill
from .worker import run_async

PR_URL = re.compile(r"https://github\.com/\S+/pull/\d+")
INDENT = 46
STUB_Y = 26
"""Height on a node where its connector line meets it (the middle of its header row)."""


def _rich(html: str) -> QLabel:
    media = str(config.media_dir())
    widget = QLabel(re.sub(r'src="(?!/|https?:)', f'src="{media}/', html))
    widget.setTextFormat(Qt.TextFormat.RichText)
    widget.setWordWrap(True)
    widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return widget


def _side(title: str, color: str, html: str) -> QWidget:
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    tag = label(title)
    tag.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: 800; letter-spacing: 1.5px;")
    layout.addWidget(tag)
    layout.addWidget(_rich(html))
    return box


def _small_button(text: str, tip: str, kind: str = "") -> QPushButton:
    button = QPushButton(text)
    button.setObjectName("nodeAction")
    if kind:
        button.setProperty("kind", kind)
    button.setToolTip(tip)
    return button


class SourceNode(QFrame):
    redo_all = Signal(str)

    def __init__(self, entry: inbox.Entry, cfg: Config, busy: bool):
        super().__init__()
        self.setObjectName("node")
        self.setProperty("kind", "source")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(6)
        header = QHBoxLayout()
        header.addWidget(pill("YOUR NOTE", theme.AMBER))
        header.addWidget(pill(f"{cfg.root_deck}::{entry.topic}", theme.PINK))
        header.addStretch()
        self.redo_button = _small_button("↻ Redo all", "Regenerate every card with one piece of feedback")
        self.redo_button.setEnabled(not busy)
        header.addWidget(self.redo_button)
        layout.addLayout(header)
        question = label(entry.question or "(the question is in a picture)", wrap=True)
        question.setStyleSheet("font-weight: 700; font-size: 15px;")
        layout.addWidget(question)
        if entry.answer:
            layout.addWidget(label(entry.answer, "muted", wrap=True))
        if entry.images:
            names = ", ".join(f"{'📖' if i.get('mode') == 'read' else '🖼'} {i['field']}" for i in entry.images)
            layout.addWidget(label(f"Pictures: {names}", "faint"))

        self.box = QWidget()
        box_layout = QHBoxLayout(self.box)
        box_layout.setContentsMargins(0, 4, 0, 0)
        self.text = QLineEdit()
        self.text.setPlaceholderText("Feedback for all cards, e.g. ask why, not what")
        self.text.returnPressed.connect(self._send)
        send = _small_button("Redo", "Regenerate all cards", "go")
        send.clicked.connect(self._send)
        box_layout.addWidget(self.text, 1)
        box_layout.addWidget(send)
        self.box.hide()
        layout.addWidget(self.box)
        self.redo_button.clicked.connect(lambda: (self.box.setVisible(not self.box.isVisible()), self.text.setFocus()))

    def _send(self) -> None:
        if self.text.text().strip():
            self.redo_all.emit(self.text.text().strip())


class CardNode(QFrame):
    accept = Signal(int)
    remove = Signal(int)
    undo = Signal(int)
    change = Signal(int, str)
    versions = Signal(int)

    def __init__(self, index: int, total: int, slot: review.Slot, entry: inbox.Entry, busy_text: str, locked: bool):
        super().__init__()
        self.index = index
        self.setObjectName("node")
        self.setProperty("kind", "card")
        self.setProperty("state", slot.status)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.addWidget(pill(f"CARD {index + 1} / {total}", theme.VIOLET))
        if slot.status == review.ACCEPTED:
            header.addWidget(pill("✓ Accepted", theme.GREEN))
        elif slot.status == review.REMOVED:
            header.addWidget(pill("✕ Removed", theme.RED))
        header.addStretch()
        layout.addLayout(header)

        if slot.status == review.REMOVED:
            faded = label(slot.card.question, wrap=True)
            faded.setStyleSheet(f"color: {theme.FAINT}; text-decoration: line-through;")
            layout.addWidget(faded)
        else:
            front, back = batch.card_html(slot.card, entry)
            layout.addWidget(_side("FRONT", theme.PINK, front))
            divider = QFrame()
            divider.setFixedHeight(1)
            divider.setStyleSheet(f"background: {theme.BORDER};")
            layout.addWidget(divider)
            layout.addWidget(_side("BACK", theme.CYAN, back))

        if busy_text:
            working = label(f"⏳ {busy_text}", wrap=True)
            working.setStyleSheet(f"color: {theme.AMBER}; font-weight: 700;")
            layout.addWidget(working)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        buttons = []
        self.box = None
        if slot.status == review.REMOVED:
            undo = _small_button("↶ Undo", "Bring this card back")
            undo.clicked.connect(lambda: self.undo.emit(index))
            buttons.append(undo)
        else:
            accepted = slot.status == review.ACCEPTED
            accept = _small_button("✓ Accepted" if accepted else "✓ Accept", "Click again to un-accept" if accepted else "This card is good", "accept")
            accept.setProperty("on", accepted)
            accept.clicked.connect(lambda: (self.undo if accepted else self.accept).emit(index))
            change = _small_button("✎ Change", "Tell the agent what to change in this card")
            versions = _small_button("✨ Versions", "Other ways to ask this card")
            versions.clicked.connect(lambda: self.versions.emit(index))
            remove = _small_button("✕ Remove", "Leave this card out", "remove")
            remove.clicked.connect(lambda: self.remove.emit(index))
            buttons += [accept, change, versions, remove]
            self.box = QWidget()
            box_layout = QHBoxLayout(self.box)
            box_layout.setContentsMargins(0, 0, 0, 0)
            self.text = QLineEdit()
            self.text.setPlaceholderText("e.g. add bold signaling and why for each one")
            self.text.returnPressed.connect(self._send)
            send = _small_button("Apply", "Rewrite this card", "go")
            send.clicked.connect(self._send)
            cancel = _small_button("Cancel", "Close without changing")
            cancel.clicked.connect(self.box.hide)
            box_layout.addWidget(self.text, 1)
            box_layout.addWidget(send)
            box_layout.addWidget(cancel)
            self.box.hide()
            change.clicked.connect(lambda: (self.box.show(), self.text.setFocus()))
        for button in buttons:
            button.setEnabled(not locked)
            actions.addWidget(button)
        actions.addStretch()
        layout.addLayout(actions)
        if self.box is not None:
            layout.addWidget(self.box)

    def _send(self) -> None:
        if self.text.text().strip():
            self.change.emit(self.index, self.text.text().strip())


class VersionNode(QFrame):
    use = Signal(int, int)
    add = Signal(int, int)
    dismiss = Signal(int, int)

    def __init__(self, index: int, number: int, version: review.Version, entry: inbox.Entry, locked: bool):
        super().__init__()
        self.setObjectName("node")
        self.setProperty("kind", "version")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)
        title = label(f"✨ {version.style}")
        title.setStyleSheet(f"color: {theme.CYAN}; font-weight: 800;")
        layout.addWidget(title)
        if version.why:
            layout.addWidget(label(version.why, "muted", wrap=True))
        for n, c in enumerate(version.cards, start=1):
            front, back = batch.card_html(c, entry)
            if len(version.cards) > 1:
                layout.addWidget(label(f"card {n} of {len(version.cards)}", "faint"))
            layout.addWidget(_side("FRONT", theme.PINK, front))
            layout.addWidget(_side("BACK", theme.CYAN, back))
        actions = QHBoxLayout()
        use = _small_button("⇄ Use instead", f"Replace card {index + 1} with this version", "go")
        use.clicked.connect(lambda: self.use.emit(index, number))
        add = _small_button("＋ Add as new card", "Keep the card and add this version next to it")
        add.clicked.connect(lambda: self.add.emit(index, number))
        dismiss = _small_button("✕", "Dismiss this version")
        dismiss.clicked.connect(lambda: self.dismiss.emit(index, number))
        for button in (use, add, dismiss):
            button.setEnabled(not locked)
            actions.addWidget(button)
        actions.addStretch()
        layout.addLayout(actions)


class Placeholder(QFrame):
    """Shaped like a card so the canvas shows where results will land while the agent works."""

    def __init__(self, text: str):
        super().__init__()
        self.setObjectName("node")
        self.setProperty("kind", "placeholder")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.addWidget(label(f"⏳ {text}", "muted"))
        for width in (0.8, 0.55):
            bar = QFrame()
            bar.setFixedHeight(10)
            bar.setMaximumWidth(int(420 * width))
            bar.setStyleSheet(f"background: {theme.BORDER}; border-radius: 5px;")
            layout.addWidget(bar)


class TreeCanvas(QWidget):
    """Nodes stacked vertically, with tree connectors drawn in the left gutter from each node to its children."""

    def __init__(self):
        super().__init__()
        self.column = QVBoxLayout(self)
        self.column.setContentsMargins(4, 4, 12, 16)
        self.column.setSpacing(14)
        self.nodes: list[tuple[QWidget, QWidget | None]] = []

    def clear(self) -> None:
        self.nodes = []
        while self.column.count():
            item = self.column.takeAt(0)
            row = item.layout()
            if row is not None:
                while row.count():
                    child = row.takeAt(0)
                    if child.widget():
                        child.widget().deleteLater()
                row.deleteLater()

    def add(self, node: QWidget, depth: int, parent: QWidget | None) -> None:
        row = QHBoxLayout()
        row.setContentsMargins(depth * INDENT, 0, 0, 0)
        row.addWidget(node)
        self.column.addLayout(row)
        self.nodes.append((node, parent))

    def finish(self) -> None:
        self.column.addStretch()
        QTimer.singleShot(0, self.update)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for parent in {id(p): p for _, p in self.nodes if p is not None}.values():
            kids = [node for node, p in self.nodes if p is parent]
            color = QColor(theme.CYAN if parent.property("kind") == "card" else theme.VIOLET)
            color.setAlpha(180)
            painter.setPen(QPen(color, 2))
            bottom = parent.mapTo(self, QPoint(0, parent.height()))
            x = bottom.x() + INDENT // 2
            for kid in kids:
                end = kid.mapTo(self, QPoint(0, STUB_Y))
                path = QPainterPath(QPoint(x, bottom.y()))
                path.lineTo(x, end.y() - 10)
                path.quadTo(x, end.y(), x + 10, end.y())
                path.lineTo(end.x(), end.y())
                painter.drawPath(path)
                painter.setBrush(color)
                painter.drawEllipse(end, 4, 4)
                painter.setBrush(Qt.BrushStyle.NoBrush)


class ReviewPage(Page):
    back = Signal()
    changed = Signal()

    def __init__(self, cfg: Config):
        super().__init__("Preview", "Your note and the cards it becomes. Accept, change or remove each one.", theme.VIOLET)
        self.cfg = cfg
        self.review: review.Review | None = None
        self.busy = False
        self.busy_target: int | None = None
        self.busy_text = ""
        self.process: QProcess | None = None
        self.worktree = None

        back = QPushButton("←  Inbox")
        back.clicked.connect(self.back.emit)
        self.header.insertWidget(0, back, 0, Qt.AlignmentFlag.AlignVCenter)
        self.header.insertSpacing(1, 10)

        self.canvas = TreeCanvas()
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(self.canvas)
        self.scroll.verticalScrollBar().valueChanged.connect(self.canvas.update)
        self.layout_.addWidget(self.scroll, 1)

        self.rule_panel = card()
        rule_layout = QVBoxLayout(self.rule_panel)
        rule_layout.setContentsMargins(14, 12, 14, 12)
        rule_layout.addWidget(label("PERSONAL RULE", "fieldLabel"))
        self.rule_text = QLineEdit()
        rule_layout.addWidget(self.rule_text)
        rule_buttons = QHBoxLayout()
        save = QPushButton("Save rule")
        save.clicked.connect(lambda: self.save_rule(propose=False))
        propose = QPushButton("Save + propose as PR")
        propose.setToolTip(f"Also asks the agent to build the rule into AnkiHelper itself and open a PR on {review.REPO}")
        propose.clicked.connect(lambda: self.save_rule(propose=True))
        rule_buttons.addWidget(label("Applies to every future card. Edit it first if you like.", "faint"), 1)
        rule_buttons.addWidget(save)
        rule_buttons.addWidget(propose)
        rule_layout.addLayout(rule_buttons)
        self.rule_panel.hide()
        self.layout_.addWidget(self.rule_panel)

        self.log = QPlainTextEdit()
        self.log.setObjectName("log")
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(110)
        self.log.hide()
        self.layout_.addWidget(self.log)

        bar = QHBoxLayout()
        self.status = label("", "muted", wrap=True)
        self.status.setOpenExternalLinks(True)
        self.status.setMinimumWidth(180)
        self.rule_button = QPushButton("📌  Make this a rule")
        self.rule_button.setToolTip("Turn what you asked for into a rule every future card follows")
        self.rule_button.clicked.connect(self.suggest_rule)
        self.import_button = QPushButton("⬆  Import now")
        self.import_button.clicked.connect(self.import_now)
        self.keep_button = QPushButton("✓  Keep cards")
        self.keep_button.setObjectName("primary")
        self.keep_button.clicked.connect(self.keep)
        bar.addWidget(self.status, 1)
        bar.addWidget(self.rule_button)
        bar.addWidget(self.import_button)
        bar.addWidget(self.keep_button)
        self.layout_.addLayout(bar)

    def open(self, entry: inbox.Entry) -> None:
        self.review = review.Review(entry)
        self.rule_panel.hide()
        self.log.hide()
        self._work(None, "Reading your note and writing cards…", lambda: review.generate(self.cfg, self.review))

    def _work(self, target: int | None, text: str, fn, on_done=None) -> None:
        """Run one agent call at a time; target is the card it concerns, None for the whole set, -1 for none."""
        self.busy, self.busy_target, self.busy_text = True, target, text
        self.render()

        def finish(result) -> None:
            self.busy, self.busy_target = False, None
            self.render()
            if on_done:
                on_done(result)

        def failed(error: str) -> None:
            self.busy, self.busy_target = False, None
            self.render()
            self._say(f"⚠ {error}", theme.RED)

        run_async(fn, finish, failed)

    def _say(self, text: str, color: str = "") -> None:
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {color}; font-weight: 700;" if color else "")

    def render(self) -> None:
        position = self.scroll.verticalScrollBar().value()
        self.canvas.clear()
        entry = self.review.entry
        source = SourceNode(entry, self.cfg, self.busy)
        source.redo_all.connect(self.redo_all)
        self.canvas.add(source, 0, None)
        if self.busy and self.busy_target is None:
            for _ in range(3):
                self.canvas.add(Placeholder(self.busy_text), 1, source)
        else:
            total = len(self.review.slots)
            for index, slot in enumerate(self.review.slots):
                busy_text = self.busy_text if self.busy and self.busy_target == index else ""
                node = CardNode(index, total, slot, entry, busy_text, self.busy)
                node.accept.connect(lambda i: self._set_status(i, review.ACCEPTED))
                node.remove.connect(lambda i: self._set_status(i, review.REMOVED))
                node.undo.connect(lambda i: self._set_status(i, review.PENDING))
                node.change.connect(self.change)
                node.versions.connect(self.show_versions)
                self.canvas.add(node, 1, source)
                for number, version in enumerate(slot.versions):
                    child = VersionNode(index, number, version, entry, self.busy)
                    child.use.connect(lambda i, n: self._use(i, n, add=False))
                    child.add.connect(lambda i, n: self._use(i, n, add=True))
                    child.dismiss.connect(self._dismiss)
                    self.canvas.add(child, 2, node)
        self.canvas.finish()
        QTimer.singleShot(0, lambda: self.scroll.verticalScrollBar().setValue(position))
        self._update_bar()

    def _update_bar(self) -> None:
        slots = self.review.slots
        kept = sum(s.status != review.REMOVED for s in slots)
        accepted = sum(s.status == review.ACCEPTED for s in slots)
        self.keep_button.setText(f"✓  Keep {kept} card{'s' if kept != 1 else ''}")
        for button in (self.keep_button, self.import_button):
            button.setEnabled(not self.busy and kept > 0)
        self.rule_button.setEnabled(not self.busy and bool(self.review.feedback))
        if self.busy:
            self._say(f"⏳ {self.busy_text}")
        elif slots:
            removed = len(slots) - kept
            self._say(f"{len(slots)} card{'s' if len(slots) != 1 else ''} · {kept - accepted} to review")

    def _set_status(self, index: int, status: str) -> None:
        self.review.slots[index].status = status
        self.render()

    def redo_all(self, feedback: str) -> None:
        self._work(None, "Rewriting every card with your feedback…", lambda: review.generate(self.cfg, self.review, feedback))

    def change(self, index: int, feedback: str) -> None:
        self._work(index, f"Rewriting this card: “{feedback}”", lambda: review.revise(self.cfg, self.review, index, feedback))

    def show_versions(self, index: int) -> None:
        self._work(index, "Writing other versions of this card…", lambda: review.versions(self.cfg, self.review, index))

    def _use(self, index: int, number: int, add: bool) -> None:
        review.use_version(self.review, index, self.review.slots[index].versions[number], add)
        self.render()

    def _dismiss(self, index: int, number: int) -> None:
        del self.review.slots[index].versions[number]
        self.render()

    def keep(self) -> None:
        cards = self.review.kept()
        inbox.approve(self.review.entry.id, [asdict(c) for c in cards])
        self.changed.emit()
        self._say(f"✓ Kept {len(cards)} card(s). The next batch imports exactly these.", theme.GREEN)

    def import_now(self) -> None:
        inbox.approve(self.review.entry.id, [asdict(c) for c in self.review.kept()])
        entry_id = self.review.entry.id

        def done(summary) -> None:
            self.changed.emit()
            self._say(f"✓ {summary.message()}", theme.GREEN)

        self._work(-1, "Importing into Anki…", lambda: batch.run(self.cfg, AnkiConnect(self.cfg.anki_url), only={entry_id}), done)

    def suggest_rule(self) -> None:
        def done(rule) -> None:
            if rule is None:
                self._say("Your feedback was about these cards only, so there's no general rule to save.")
                return
            self.rule_text.setText(rule)
            self.rule_panel.show()
            self.rule_text.setFocus()

        self._work(-1, "Turning your feedback into a rule…", lambda: review.suggest_rule(self.cfg, self.review), done)

    def save_rule(self, propose: bool) -> None:
        rule = self.rule_text.text().strip()
        if not rule:
            return
        review.save_rule(rule)
        self.rule_panel.hide()
        self.changed.emit()
        self._say("📌 Rule saved. Every future card follows it (Settings → Personal rules).", theme.GREEN)
        if propose:
            self._propose(rule)

    def _propose(self, rule: str) -> None:
        try:
            env = review.github_env(self.cfg)
            cmd, self.worktree = review.pr_command(self.cfg, rule)
        except Exception as error:
            return self._say(f"⚠ {error}", theme.RED)
        self.log.clear()
        self.log.show()
        self.log.appendPlainText(
            f"{self.cfg.agent} is building the rule into AnkiHelper in {self.worktree}; the PR is opened as {self.cfg.github_account} …"
        )
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.setWorkingDirectory(str(self.worktree))
        environment = QProcessEnvironment.systemEnvironment()
        for key, value in env.items():
            environment.insert(key, value)
        self.process.setProcessEnvironment(environment)
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
            self._say(f'🚀 PR opened: <a href="{url[-1]}" style="color:{theme.CYAN}">{url[-1]}</a>', theme.GREEN)
        else:
            self._say(f"⚠ The agent finished (exit {code}) without opening a PR. The log above says why.", theme.RED)
