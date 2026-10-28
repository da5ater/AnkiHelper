import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..config import Config
from . import theme
from .capture import CapturePage
from .common import label, pill
from .inbox_page import InboxPage
from .review_page import ReviewPage
from .settings_page import SettingsPage
from .setup_page import SetupPage

APP_ID = "ankihelper"
NAV = [("capture", "✍   Capture"), ("inbox", "📥   Inbox"), ("setup", "🩺   Setup"), ("settings", "⚙   Settings")]


def make_app() -> QApplication:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("AnkiHelper")
    app.setDesktopFileName(APP_ID)
    theme.apply(app)
    return app


class MainWindow(QWidget):
    def __init__(self, cfg: Config, page: str = "capture", close_after_save: bool = False):
        super().__init__()
        self.cfg = cfg
        self.closing = False
        self.setObjectName("root")
        self.setWindowTitle("AnkiHelper")
        self.resize(940, 640)

        self.capture = CapturePage(cfg, close_after_save)
        self.inbox = InboxPage(cfg)
        self.setup = SetupPage(cfg)
        self.settings = SettingsPage(cfg)
        self.review = ReviewPage(cfg)
        self.pages = {
            "capture": self.capture,
            "inbox": self.inbox,
            "setup": self.setup,
            "settings": self.settings,
            "review": self.review,
        }
        self.stack = QStackedWidget()
        for widget in self.pages.values():
            self.stack.addWidget(widget)

        self.capture.saved.connect(self._refresh_badges)
        self.capture.close_requested.connect(self.close)
        self.inbox.changed.connect(self._refresh_badges)
        self.inbox.preview_requested.connect(self._preview)
        self.review.back.connect(lambda: self.go("inbox"))
        self.review.changed.connect(self._refresh_badges)
        self.review.changed.connect(self.settings.reload_rules)
        self.settings.changed.connect(self._settings_changed)
        self.setup.idle.connect(self._maybe_quit)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._sidebar())
        layout.addWidget(self.stack, 1)

        QShortcut(QKeySequence("Escape"), self, activated=self.close)
        for index, (name, _) in enumerate(NAV, start=1):
            QShortcut(QKeySequence(f"Ctrl+{index}"), self, activated=lambda name=name: self.go(name))
        self.go(page)

    def _sidebar(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("sidebar")
        frame.setFixedWidth(210)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 22, 14, 18)
        layout.setSpacing(6)
        brand = label("AnkiHelper", "brand")
        brand.setStyleSheet(f"color: {theme.PINK};")
        layout.addWidget(brand)
        layout.addWidget(label("speak it · study it", "brandSub"))
        layout.addSpacing(18)

        self.nav = QButtonGroup(self)
        self.nav_buttons: dict[str, QPushButton] = {}
        for index, (name, text) in enumerate(NAV, start=1):
            button = QPushButton(text)
            button.setObjectName("nav")
            button.setCheckable(True)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setToolTip(f"Ctrl+{index}")
            button.clicked.connect(lambda _=False, name=name: self.go(name))
            color = theme.PAGE_COLORS[name]
            button.setStyleSheet(f"QPushButton#nav:checked {{ border-left: 3px solid {color}; color: {color}; }}")
            self.nav.addButton(button)
            self.nav_buttons[name] = button
            layout.addWidget(button)
        layout.addStretch()

        self.agent_pill = pill("", theme.VIOLET)
        self.inbox_pill = pill("", theme.AMBER)
        layout.addWidget(label("AGENT", "fieldLabel"))
        layout.addWidget(self.agent_pill, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addSpacing(6)
        layout.addWidget(label("INBOX", "fieldLabel"))
        layout.addWidget(self.inbox_pill, 0, Qt.AlignmentFlag.AlignLeft)
        self._settings_changed()
        self._refresh_badges()
        return frame

    def _preview(self, entry) -> None:
        self.go("review")
        self.review.open(entry)

    def go(self, name: str) -> None:
        self.nav_buttons["inbox" if name == "review" else name].setChecked(True)
        self.stack.setCurrentWidget(self.pages[name])
        self.pages[name].shown()

    def _refresh_badges(self) -> None:
        count = self.inbox.count()
        self.inbox_pill.setText(f"{count} waiting" if count else "empty")
        self.nav_buttons["inbox"].setText(f"📥   Inbox  ({count})" if count else "📥   Inbox")
        if self.stack.currentWidget() is self.inbox:
            self.inbox.refresh()

    def _settings_changed(self) -> None:
        color = theme.AGENT_COLORS.get(self.cfg.agent, theme.VIOLET)
        self.agent_pill.setText(f"● {self.cfg.agent}")
        self.agent_pill.setStyleSheet(theme.pill_style(color))
        self.capture.refresh_dictation()
        self.setup.checked_once = False

    def _maybe_quit(self) -> None:
        if self.closing:
            QApplication.quit()

    def closeEvent(self, event) -> None:
        if self.setup.process is not None:
            answer = QMessageBox.question(
                self, "Agent is still fixing", "Stopping now may leave a config file half edited. Stop the agent?"
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.setup.stop_fix()
        if self.setup.thread is not None:
            self.closing = True
            self.hide()
            event.ignore()
            return
        event.accept()


def run(page: str, close_after_save: bool = False) -> int:
    app = make_app()
    window = MainWindow(Config.load(), page, close_after_save)
    window.show()
    window.raise_()
    window.activateWindow()
    return app.exec()
