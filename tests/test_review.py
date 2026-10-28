import json

from ankihelper import agents, batch, config, inbox, review
from ankihelper.anki import AnkiConnect
from ankihelper.config import Config


def reply_with(question: str, source_id: str) -> str:
    return json.dumps({"cards": [{"source_id": source_id, "question": question, "answer": "a", "tags": [], "changed": False}]})


def test_redo_sends_previous_cards_and_feedback(monkeypatch):
    entry = inbox.Entry.new("what is rack", "web server interface", "ruby")
    prompts = []

    def fake_ask(name, prompt_text, timeout=600, images=None):
        prompts.append(prompt_text)
        return reply_with(f"version {len(prompts)}", entry.id)

    monkeypatch.setattr(agents, "ask", fake_ask)
    session = review.Review(entry)
    cfg = Config()

    assert review.generate(cfg, session)[0].question == "version 1"
    assert review.generate(cfg, session, "ask why, not what")[0].question == "version 2"

    assert '"revision": {' not in prompts[0]
    assert '"feedback": "ask why, not what"' in prompts[1]
    assert '"question": "version 1"' in prompts[1]
    assert session.rounds[0].feedback == "ask why, not what"


def test_kept_cards_are_imported_as_approved_without_asking_the_agent(fake_anki, monkeypatch):
    entry = inbox.Entry.new("what is rack", "web server interface", "ruby")
    inbox.append(entry)
    other = inbox.Entry.new("what is a gem", "a library", "ruby")
    inbox.append(other)
    inbox.approve(entry.id, [{"source_id": entry.id, "question": "Approved?", "answer": "yes", "tags": [], "changed": False}])

    def no_agent(*args, **kwargs):
        raise AssertionError("approved cards must not be re-cleaned")

    monkeypatch.setattr(agents, "ask", no_agent)
    summary = batch.run(Config(anki_url=fake_anki.url), AnkiConnect(fake_anki.url), only={entry.id})

    assert summary.imported == 1
    assert "Approved?" in fake_anki.notes[0]["fields"]["Front"]
    assert [e.id for e in inbox.read_all()] == [other.id], "Import now leaves the other notes waiting"


def test_saved_rules_reach_the_card_writing_prompt(monkeypatch):
    review.save_rule("Prefer why questions over definitions.")
    review.save_rule("Keep answers to one line.")
    seen = []
    entry = inbox.Entry.new("q", "a", "ruby")
    monkeypatch.setattr(agents, "ask", lambda name, text, timeout=600, images=None: seen.append(text) or reply_with("Q", entry.id))

    batch.clean("claude", [entry], "English")

    assert config.rules_path().read_text() == "- Prefer why questions over definitions.\n- Keep answers to one line.\n"
    assert "- Prefer why questions over definitions.\n- Keep answers to one line." in seen[0]


def test_card_specific_feedback_gives_no_rule(monkeypatch):
    entry = inbox.Entry.new("q", "a", "ruby")
    session = review.Review(entry, [review.Round([], "the year is wrong")])
    monkeypatch.setattr(agents, "ask", lambda *a, **k: "NONE\n")
    assert review.suggest_rule(Config(), session) is None
    monkeypatch.setattr(agents, "ask", lambda *a, **k: "Prefer why questions.\n")
    assert review.suggest_rule(Config(), session) == "Prefer why questions."
