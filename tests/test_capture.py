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
    main = gui.MainWindow(cfg, "capture", close_after_save=True)
    main.show()
    w = main.capture
    main.activateWindow()
    assert QTest.qWaitForWindowActive(main)
    w.window_ = main
    yield w
    main.close()


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
    assert not window.window_.isVisible()
    assert Config.load().last_topic == "ruby"


def test_empty_question_is_not_saved(window):
    QTest.keyClick(window.question, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    assert inbox.read_all() == []
    assert window.window_.isVisible()
    assert "question" in window.status.text().lower()


def test_topic_autocompletes_from_known_subdecks(window):
    items = [window.topic.itemText(i) for i in range(window.topic.count())]
    assert items == ["ruby", "node::mosh"]


def test_pasting_a_picture_attaches_it_instead_of_text(window):
    from PySide6.QtCore import QMimeData
    from PySide6.QtGui import QColor, QImage

    from ankihelper import config

    image = QImage(40, 30, QImage.Format.Format_RGB32)
    image.fill(QColor("orange"))
    mime = QMimeData()
    mime.setImageData(image)
    window.question.insertFromMimeData(mime)
    assert window.strips["question"].isVisible()
    assert window.question.toPlainText() == ""

    QTest.keyClick(window.question, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)

    [entry] = inbox.read_all()
    assert entry.question == "", "a picture alone is a valid question"
    [saved] = entry.images
    assert saved["field"] == "question"
    assert QImage(str(config.media_dir() / saved["file"])).size() == image.size()
