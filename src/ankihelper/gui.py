import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, Qt, QThread, Signal
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QCompleter,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import agents, checks, config, inbox
from .anki import AnkiConnect, AnkiError, AnkiUnreachable
from .config import Config

APP_ID = "ankihelper"
PROJECT_DIR = str(Path(__file__).resolve().parents[2])


def make_app() -> QApplication:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("AnkiHelper")
    app.setDesktopFileName(APP_ID)
    return app


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


class TextBox(QPlainTextEdit):
    def __init__(self, placeholder: str):
        super().__init__()
        self.setPlaceholderText(placeholder)
        self.setTabChangesFocus(True)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)


class CaptureWindow(QWidget):
    saved = Signal(str)

    def __init__(self, cfg: Config):
        super().__init__()
        self.cfg = cfg
        self.setWindowTitle("AnkiHelper - new card")
        self.resize(720, 520)

        self.question = TextBox("Question")
        self.answer = TextBox("Answer")
        self.topic = QComboBox()
        self.topic.setEditable(True)
        self.topic.addItems(topics(cfg))
        self.topic.setCurrentText(cfg.last_topic)
        self.topic.lineEdit().setPlaceholderText(f"Topic (deck under '{cfg.root_deck}')")
        completer = QCompleter(self.topic.model(), self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.topic.setCompleter(completer)
        self.status = QLabel("Ctrl+Enter saves  ·  Tab moves  ·  Esc cancels")
        self.status.setStyleSheet("color: gray")

        layout = QVBoxLayout(self)
        for label, widget, stretch in (("Question", self.question, 2), ("Answer", self.answer, 3), ("Topic", self.topic, 0)):
            title = QLabel(label)
            title.setFont(QFont(title.font().family(), weight=QFont.Weight.DemiBold))
            layout.addWidget(title)
            layout.addWidget(widget, stretch)
        layout.addWidget(self.status)

        for keys in ("Ctrl+Return", "Ctrl+Enter"):
            QShortcut(QKeySequence(keys), self, activated=self.save)
        QShortcut(QKeySequence("Escape"), self, activated=self.close)
        self.question.setFocus()

    def save(self) -> None:
        question, topic = self.question.toPlainText().strip(), self.topic.currentText().strip()
        if not question:
            return self._error("Say a question first.", self.question)
        if not topic:
            return self._error("Pick a topic.", self.topic)
        entry = inbox.Entry.new(question, self.answer.toPlainText(), topic)
        inbox.append(entry)
        self.cfg.last_topic = topic
        self.cfg.save()
        self.saved.emit(entry.id)
        self.close()

    def _error(self, message: str, widget: QWidget) -> None:
        self.status.setText(message)
        self.status.setStyleSheet("color: #d33")
        widget.setFocus()


class CheckWorker(QObject):
    finished = Signal(list)

    def __init__(self, cfg: Config):
        super().__init__()
        self.cfg = cfg

    def run(self) -> None:
        self.finished.emit(checks.run_all(self.cfg))


class SetupWindow(QWidget):
    def __init__(self, cfg: Config):
        super().__init__()
        self.cfg = cfg
        self.results: list = []
        self.thread: QThread | None = None
        self.process: QProcess | None = None
        self.log_file: Path | None = None
        self.closing = False
        self.setWindowTitle("AnkiHelper - setup")
        self.resize(820, 640)

        self.agent = QComboBox()
        self.agent.addItems(list(agents.AGENTS))
        self.agent.setCurrentText(cfg.agent)
        self.agent.currentTextChanged.connect(self._agent_changed)

        self.grid = QGridLayout()
        self.recheck_button = QPushButton("Recheck")
        self.recheck_button.clicked.connect(self.recheck)
        self.fix_button = QPushButton("Fix with agent")
        self.fix_button.clicked.connect(self.fix)
        self.status = QLabel()
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFont("monospace"))
        self.log.setPlaceholderText("The agent's output appears here while it fixes things.")

        top = QHBoxLayout()
        top.addWidget(QLabel("Agent"))
        top.addWidget(self.agent)
        top.addStretch()
        top.addWidget(self.recheck_button)
        top.addWidget(self.fix_button)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addLayout(self.grid)
        layout.addWidget(self.status)
        layout.addWidget(self.log, 1)
        self.recheck()

    def _agent_changed(self, name: str) -> None:
        self.cfg.agent = name
        self.cfg.save()
        self.recheck()

    def _busy(self, busy: bool, message: str = "") -> None:
        self.recheck_button.setEnabled(not busy)
        self.fix_button.setEnabled(not busy and any(not r.ok for _, r in self.results))
        self.agent.setEnabled(not busy)
        self.status.setText(message)

    def recheck(self) -> None:
        if self.thread is not None:
            return
        self._busy(True, "Checking...")
        self.thread = QThread()
        self.worker = CheckWorker(self.cfg)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self._show)
        self.worker.finished.connect(self.thread.quit)
        self.thread.finished.connect(self._thread_done)
        self.thread.start()

    def _thread_done(self) -> None:
        self.thread.wait()
        self.thread = None
        if self.closing:
            QApplication.quit()

    def closeEvent(self, event) -> None:
        if self.process is not None:
            answer = QMessageBox.question(
                self, "Agent is still fixing", "Stopping now may leave a config file half edited. Stop the agent?"
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.process.finished.disconnect()
            self.process.kill()
            self.process.waitForFinished(3000)
        if self.thread is not None:
            self.closing = True
            self.hide()
            event.ignore()
            return
        event.accept()

    def _show(self, results: list) -> None:
        self.results = results
        while self.grid.count():
            self.grid.takeAt(0).widget().deleteLater()
        for row, (check, result) in enumerate(results):
            mark = QLabel("✅" if result.ok else "❌")
            name = QLabel(check.title)
            name.setFont(QFont(name.font().family(), weight=QFont.Weight.DemiBold))
            detail = QLabel(result.detail)
            detail.setWordWrap(True)
            detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.grid.addWidget(mark, row, 0)
            self.grid.addWidget(name, row, 1)
            self.grid.addWidget(detail, row, 2)
        self.grid.setColumnStretch(2, 1)
        failed = sum(not r.ok for _, r in results)
        self._busy(False, "Everything works." if not failed else f"{failed} problem(s). Fix them yourself and Recheck, or let the agent fix them.")

    def fix(self) -> None:
        failed = [(c, r) for c, r in self.results if not r.ok]
        if not failed or self.process is not None:
            return
        if not agents.installed(self.cfg.agent):
            self.status.setText(f"{self.cfg.agent} is not installed; pick another agent or install it.")
            return
        cmd = checks.fix_command(self.cfg, failed, PROJECT_DIR)
        self.log_file = config.log_dir() / f"fix-{datetime.now():%Y%m%d-%H%M%S}.log"
        self.log.clear()
        self.log.appendPlainText(f"$ {cmd[0]} ... (fixing {len(failed)} problem(s); log: {self.log_file})\n")
        self._busy(True, f"{self.cfg.agent} is fixing {len(failed)} problem(s)...")
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.setWorkingDirectory(PROJECT_DIR)
        self.process.readyReadStandardOutput.connect(self._read_output)
        self.process.finished.connect(self._fix_done)
        self.process.errorOccurred.connect(self._fix_failed_to_start)
        self.process.start(cmd[0], cmd[1:])

    def _fix_failed_to_start(self, error) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self.log.appendPlainText(f"Could not start {self.cfg.agent}: {self.process.errorString()}")
            self.process = None
            self._busy(False, "The agent did not start.")

    def _read_output(self) -> None:
        text = bytes(self.process.readAllStandardOutput()).decode(errors="replace")
        self.log.moveCursor(self.log.textCursor().MoveOperation.End)
        self.log.insertPlainText(text)
        with self.log_file.open("a") as f:
            f.write(text)

    def _fix_done(self, code: int, _status) -> None:
        self.log.appendPlainText(f"\n[agent exited with code {code}; rechecking]")
        self.process = None
        self.recheck()


def run_capture() -> int:
    app = make_app()
    window = CaptureWindow(Config.load())
    window.show()
    window.raise_()
    window.activateWindow()
    return app.exec()


def run_setup() -> int:
    app = make_app()
    window = SetupWindow(Config.load())
    window.show()
    return app.exec()
