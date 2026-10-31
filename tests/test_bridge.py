import io
import json
import os

from ankihelper import addon, agents, batch, bridge, cli, config, inbox, learning, notes
from ankihelper.anki import AnkiConnect
from ankihelper.batch import Card
from ankihelper.config import Config


def test_edits_made_by_ankihelper_itself_are_not_learned_from():
    bridge.note_written(5)
    bridge.report({"events": [{"kind": "edit", "note_id": 5}, {"kind": "edit", "note_id": 6}, {"kind": "delete", "note_id": 5}]})
    assert [(e["kind"], e["note_id"]) for e in learning.events_since(0)] == [("edit", 6), ("delete", 5)]


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
    assert bridge.history(404) == {"known": False, "changes": []}


def test_cli_speaks_json_to_the_addon(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    assert cli.main(["anki", "moves"]) == 0
    reply = json.loads(capsys.readouterr().out)
    assert [m["name"] for m in reply["moves"]][:2] == ["Word it better", "Make it a scenario"]


def test_install_addon_links_it_into_anki_and_is_safe_to_rerun(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    first = addon.install()
    target = tmp_path / "share" / "Anki2" / "addons21" / "ankihelper"
    assert target.is_symlink() and (target / "__init__.py").exists()
    assert "Installed" in first and "Already installed" in addon.install()
    assert json.loads((target / "user_files" / "cli.json").read_text())["command"]


def test_history_shows_changes_to_a_card_ankihelper_did_not_make():
    before_html = {"question": "<p>What is the difference between has_one and belongs_to?</p>", "answer": "<p>Long answer</p>"}
    draft = {"question": "has_one vs belongs_to: which model holds the foreign key?", "answer": "The belongs_to side."}
    messages = [{"role": "learner", "text": "teach me this"}, {"role": "agent", "text": "..."}, {"role": "learner", "text": "add the foreign key part to the card"}]

    bridge.finish_chat(Config(), 77, before_html, draft, messages, ["agent"])

    history = bridge.history(77)
    assert history["known"] is False
    [change] = history["changes"]
    assert change["kind"] == "Conversation with AnkiHelper"
    assert change["said"] == "teach me this / add the foreign key part to the card"
    assert change["after"]["question"].startswith("has_one vs belongs_to")
    assert change["restore"] == before_html, "the earlier version can be put back"
