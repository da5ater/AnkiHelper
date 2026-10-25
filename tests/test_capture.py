import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from ankihelper import gui, inbox  # noqa: E402
from ankihelper.config import Config  # noqa: E402


@pytest.fixture
def window():
    gui.make_app()
    cfg = Config(anki_url="http://127.0.0.1:9", known_topics=["ruby", "node::mosh"], last_topic="ruby")
    w = gui.CaptureWindow(cfg)
    w.show()
    w.activateWindow()
    assert QTest.qWaitForWindowActive(w)
    yield w
    w.close()


def test_ctrl_enter_saves_long_dictation_to_inbox(window):
    long_answer = "rails generate controller home index " * 40
    QTest.keyClicks(window.question, "how to generate a controller")
    QTest.keyClick(window.question, Qt.Key.Key_Tab)
    assert window.answer.hasFocus(), "Tab moves to the answer instead of inserting a tab"
    window.answer.setPlainText(long_answer)
    QTest.keyClick(window.answer, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)

    [entry] = inbox.read_all()
    assert entry.question == "how to generate a controller"
    assert entry.answer == long_answer.strip()
    assert entry.topic == "ruby", "last topic is preselected"
    assert not window.isVisible()
    assert Config.load().last_topic == "ruby"


def test_empty_question_is_not_saved(window):
    QTest.keyClick(window.question, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    assert inbox.read_all() == []
    assert window.isVisible()
    assert "question" in window.status.text().lower()


def test_topic_autocompletes_from_known_subdecks(window):
    items = [window.topic.itemText(i) for i in range(window.topic.count())]
    assert items == ["ruby", "node::mosh"]
