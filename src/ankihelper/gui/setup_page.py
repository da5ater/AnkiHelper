from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, Qt, QThread, Signal
from PySide6.QtWidgets import QHBoxLayout, QPlainTextEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget

from .. import agents, checks, config
from ..config import Config
from . import theme
from .common import Page, card, label, pill

PROJECT_DIR = str(Path(__file__).resolve().parents[3])


class CheckWorker(QObject):
    finished = Signal(list)

    def __init__(self, cfg: Config):
        super().__init__()
        self.cfg = cfg

    def run(self) -> None:
        self.finished.emit(checks.run_all(self.cfg))


class SetupPage(Page):
    idle = Signal()

    def __init__(self, cfg: Config):
        super().__init__("Setup", "Everything AnkiHelper needs. Fix a problem yourself and recheck, or let the agent do it.", theme.GREEN)
        self.cfg = cfg
        self.results: list = []
        self.thread: QThread | None = None
        self.process: QProcess | None = None
        self.log_file: Path | None = None
        self.checked_once = False

        self.recheck_button = QPushButton("↻  Recheck")
        self.recheck_button.clicked.connect(self.recheck)
        self.fix_button = QPushButton("🪄  Fix with agent")
        self.fix_button.setObjectName("primary")
        self.fix_button.clicked.connect(self.fix)
        self.header.addWidget(self.recheck_button, 0, Qt.AlignmentFlag.AlignVCenter)
        self.header.addWidget(self.fix_button, 0, Qt.AlignmentFlag.AlignVCenter)

        self.rows = QVBoxLayout()
        self.rows.setSpacing(8)
        self.rows.setContentsMargins(0, 0, 8, 0)
        holder = QWidget()
        holder.setLayout(self.rows)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(holder)
        self.layout_.addWidget(scroll, 1)
        self.status = label("", "muted")
        self.layout_.addWidget(self.status)
        self.log = QPlainTextEdit()
        self.log.setObjectName("log")
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("When the agent fixes something, its output streams here.")
        self.log.setFixedHeight(120)
        self.layout_.addWidget(self.log)
        self._busy(False)

    def shown(self) -> None:
        if not self.checked_once:
            self.recheck()

    def busy(self) -> bool:
        return self.thread is not None or self.process is not None

    def _busy(self, busy: bool, message: str = "") -> None:
        self.recheck_button.setEnabled(not busy)
        self.fix_button.setEnabled(not busy and any(not r.ok for _, r in self.results))
        if message:
            self.status.setText(message)

    def recheck(self) -> None:
        if self.thread is not None:
            return
        self.checked_once = True
        self._busy(True, "Checking…  (this can start Anki and ask the agent to say hi)")
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
        self.idle.emit()

    def _row(self, check, result) -> QWidget:
        frame = card()
        frame.setMinimumHeight(52)
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(14, 8, 14, 8)
        color = theme.GREEN if result.ok else theme.RED
        dot = label("●")
        dot.setStyleSheet(f"color: {color}; font-size: 18px;")
        name = label(check.title)
        name.setStyleSheet("font-weight: 700;")
        name.setMinimumWidth(190)
        detail = label(result.detail.replace("/", "/\u200b"), "muted", wrap=True)
        detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(dot)
        layout.addWidget(name)
        layout.addWidget(detail, 1)
        layout.addWidget(pill("OK" if result.ok else "FIX", color))
        return frame

    def _show(self, results: list) -> None:
        self.results = results
        while self.rows.count():
            item = self.rows.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for check, result in results:
            self.rows.addWidget(self._row(check, result))
        self.rows.addStretch()
        failed = sum(not r.ok for _, r in results)
        self._busy(False, "🎉 Everything works." if not failed else f"{failed} problem(s) to fix.")

    def fix(self) -> None:
        failed = [(c, r) for c, r in self.results if not r.ok]
        if not failed or self.process is not None:
            return
        if not agents.installed(self.cfg.agent):
            self.status.setText(f"{self.cfg.agent} is not installed. Pick another agent in Settings.")
            return
        cmd = checks.fix_command(self.cfg, failed, PROJECT_DIR)
        self.log_file = config.log_dir() / f"fix-{datetime.now():%Y%m%d-%H%M%S}.log"
        self.log.clear()
        self.log.appendPlainText(f"{self.cfg.agent} is fixing {len(failed)} problem(s). Log: {self.log_file}\n")
        self._busy(True, f"🪄 {self.cfg.agent} is working…")
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
            self.idle.emit()

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

    def stop_fix(self) -> None:
        if self.process is not None:
            self.process.finished.disconnect()
            self.process.kill()
            self.process.waitForFinished(3000)
            self.process = None
