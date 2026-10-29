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
    assert (saved["field"], saved["mode"]) == ("question", "read"), "a picture with no typed question is read"
    assert QImage(str(config.media_dir() / saved["file"])).size() == image.size()


def test_picture_after_typed_question_is_shown_and_can_be_toggled(window):
    from PySide6.QtCore import QMimeData
    from PySide6.QtGui import QColor, QImage

    image = QImage(20, 20, QImage.Format.Format_RGB32)
    image.fill(QColor("teal"))
    mime = QMimeData()
    mime.setImageData(image)
    window.question.setPlainText("what does this diagram show")
    window.question.insertFromMimeData(mime)
    window.answer.insertFromMimeData(mime)
    assert window.strips["question"].images[0][1] == "show"
    assert window.strips["answer"].images[0][1] == "show"

    window.strips["question"]._toggle(0)
    QTest.keyClick(window.question, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)

    [entry] = inbox.read_all()
    assert [(i["field"], i["mode"]) for i in entry.images] == [("question", "read"), ("answer", "show")]


def test_language_override_is_saved_only_when_it_differs_from_the_default(window):
    window.question.setPlainText("ما هو الـ gem")
    window.language.setCurrentText("Arabic")
    QTest.keyClick(window.question, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    [entry] = inbox.read_all()
    assert entry.language == "Arabic"
    assert Config.load().last_language == "Arabic"


def test_save_in_preview_keeps_only_accepted_cards_and_returns_to_the_inbox(window):
    from ankihelper import batch, review

    main = window.window_
    entry = inbox.Entry.new("aws security", "", "DevOps::AWS")
    inbox.append(entry)
    page = main.review
    main.go("review")
    page.review = review.Review(entry, [review.Slot(batch.Card(entry.id, q, "a", [], False)) for q in ("one", "two", "three")])
    page.render()
    assert not page.keep_button.isEnabled(), "nothing accepted yet"

    page._set_status(0, review.ACCEPTED)
    page._set_status(2, review.REMOVED)
    assert page.keep_button.text().endswith("Save 1")
    page.keep_button.click()

    [saved] = inbox.read_all()
    assert [c["question"] for c in saved.cards] == ["one"]
    assert main.stack.currentWidget() is main.inbox
    assert "Saved 1 card" in main.inbox.notice.text()


def test_reopening_preview_shows_saved_cards_instead_of_regenerating(window, monkeypatch):
    from ankihelper import agents, review

    main = window.window_
    entry = inbox.Entry.new("aws security", "", "DevOps::AWS")
    inbox.append(entry)
    inbox.approve(entry.id, [{"source_id": entry.id, "question": "Saved?", "answer": "yes", "tags": [], "changed": False, "bloom": "apply"}])
    monkeypatch.setattr(agents, "ask", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not regenerate")))

    main._preview(inbox.read_all()[0])

    page = main.review
    assert not page.busy
    assert [(s.card.question, s.status, s.card.bloom) for s in page.review.slots] == [("Saved?", review.ACCEPTED, "apply")]


def test_rules_can_be_ticked_deleted_and_applied_together(window, monkeypatch):
    from PySide6.QtCore import Qt as QtCore

    from ankihelper import config, jobs, review

    for rule in ("Keep examples minimal.", "Ask why, not what.", "No create-level cards."):
        review.save_rule(rule)
    settings = window.window_.settings
    window.window_.go("settings")
    texts = [settings.rule_list.item(i).text() for i in range(settings.rule_list.count())]
    assert texts == ["Keep examples minimal.", "Ask why, not what.", "No create-level cards."]

    settings.rule_list.item(2).setCheckState(QtCore.CheckState.Checked)
    settings._delete_checked()
    assert config.personal_rules() == "- Keep examples minimal.\n- Ask why, not what."

    started = []
    monkeypatch.setattr(jobs, "start", lambda cfg, anki, rules, scope: started.append((rules, scope)) or {"queue": []})
    settings._check_all(True)
    settings._start_job()
    QTest.qWait(300)
    assert started == [(["Keep examples minimal.", "Ask why, not what."], "ankihelper")]
