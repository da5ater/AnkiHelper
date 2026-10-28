import io
import json
import os

from ankihelper import addon, agents, batch, bridge, cli, config, inbox, learning, notes
from ankihelper.anki import AnkiConnect
from ankihelper.batch import Card
from ankihelper.config import Config


def fixed_reply(question="Shorter?", answer="Yes."):
    return lambda *a, **k: json.dumps({"question": question, "answer": answer, "bloom": "understand"})


def test_fixing_a_card_ankihelper_made_uses_its_original_note(monkeypatch):
    entry = inbox.Entry.new("what is rack", "web server interface", "ruby")
    notes.record(7, entry, Card(entry.id, "What is Rack?", "A long answer.", ["ruby"], False, group="atomic"))
    seen = []
    monkeypatch.setattr(agents, "ask", lambda name, text, timeout=600, images=None: seen.append(text) or fixed_reply()())

    reply = bridge.rewrite(Config(), 7, "<p>What is Rack?</p>", "<p>A long answer.</p>", "make it shorter")

    assert '"question": "what is rack"' in seen[0] and "make it shorter" in seen[0]
    assert "Shorter?" in reply["front"] and "Yes." in reply["back"]
    assert reply["add_tags"] == [bridge.FIXED_TAG]
    assert notes.find(7)["card"]["question"] == "Shorter?" and notes.find(7)["card"]["group"] == "atomic"
    [event] = learning.pending()
    assert event["kind"] == "fix" and event["before"]["answer"] == "A long answer."


def test_fixing_any_other_card_keeps_its_pictures(monkeypatch):
    monkeypatch.setattr(agents, "ask", fixed_reply())
    reply = bridge.rewrite(Config(), 99, "<div>Q?</div><img src='diagram.png'>", "<b>A</b>", "ask why")
    assert "<img src='diagram.png'>" in reply["front"]


def test_edits_made_by_ankihelper_itself_are_not_learned_from():
    bridge.note_written(5)
    bridge.report({"events": [{"kind": "edit", "note_id": 5}, {"kind": "edit", "note_id": 6}, {"kind": "delete", "note_id": 5}]})
    assert [(e["kind"], e["note_id"]) for e in learning.pending()] == [("edit", 6), ("delete", 5)]


def test_learning_turns_deletion_patterns_into_suggested_rules(monkeypatch):
    for n in range(4):
        learning.log({"kind": "delete", "note_id": n, "tags": ["ah::group::optimized", "ah::bloom::create"], "question": f"Design {n}?"})
    seen = []
    reply = {"rules": [{"rule": "Do not write create-level cards.", "evidence": "deleted 4 of 4 create cards"}]}
    monkeypatch.setattr(agents, "ask", lambda name, text, timeout=600, images=None: seen.append(text) or json.dumps(reply))

    [found] = learning.learn(Config())

    assert "ah::bloom::create" in seen[0]
    assert learning.pending() == [], "events are only learned from once"
    assert learning.learn(Config()) == []
    learning.accept(found["id"], "Never write create-level cards.")
    assert learning.suggestions() == []
    assert "- Never write create-level cards." in config.personal_rules()


def test_too_few_events_ask_nothing(monkeypatch):
    learning.log({"kind": "delete", "note_id": 1})
    monkeypatch.setattr(agents, "ask", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no agent call")))
    assert learning.learn(Config()) == []


def test_flagged_cards_are_fixed_by_the_next_batch(fake_anki, monkeypatch):
    anki = AnkiConnect(fake_anki.url)
    fake_anki.decks.add("other")
    anki.add_note("other", "Basic+", "<p>Old question?</p>", "<p>Old answer</p>", [])
    bridge.flag(1, "ask why instead")
    monkeypatch.setattr(agents, "ask", fixed_reply("Why does it matter?", "Because."))

    summary = batch.run(Config(anki_url=fake_anki.url), anki)

    assert summary.fixed == 1
    note = fake_anki.notes[0]
    assert "Why does it matter?" in note["fields"]["Front"] and bridge.FIXED_TAG in note["tags"]
    assert not bridge.has_flagged()
    assert "1 flagged card(s) fixed" in summary.message()


def test_history_offers_the_versions_shown_in_preview():
    entry = inbox.Entry.new("aws security", "", "DevOps::AWS")
    versions = [{"style": "Reverse", "why": "name from its job", "cards": [{"question": "Who audits API calls?", "answer": "CloudTrail"}]}]
    notes.record(3, entry, Card(entry.id, "Which service audits API calls?", "CloudTrail", [], False, versions=versions))
    notes.record(4, entry, Card(entry.id, "Which service encrypts?", "KMS", [], False, group="atomic"))

    history = bridge.history(3)

    assert history["known"] and history["entry"]["question"] == "aws security"
    assert history["siblings"] == [{"note_id": 4, "question": "Which service encrypts?", "group": "atomic"}]
    [version] = history["versions"]
    assert "Who audits API calls?" in version["cards"][0]["front"]
    assert bridge.history(404) == {"known": False}


def test_cli_speaks_json_to_the_addon(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"note_id": 12, "feedback": "too long"})))
    assert cli.main(["anki", "flag"]) == 0
    assert json.loads(capsys.readouterr().out) == {"ok": True}
    assert bridge.take_flagged()[0]["feedback"] == "too long"


def test_install_addon_links_it_into_anki_and_is_safe_to_rerun(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    first = addon.install()
    target = tmp_path / "share" / "Anki2" / "addons21" / "ankihelper"
    assert target.is_symlink() and (target / "__init__.py").exists()
    assert "Installed" in first and "Already installed" in addon.install()
    assert json.loads((target / "user_files" / "cli.json").read_text())["command"]
