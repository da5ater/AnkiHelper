import json

from ankihelper import agents, batch, config, inbox, review
from ankihelper.anki import AnkiConnect
from ankihelper.config import Config


def reply_with(question: str, source_id: str) -> str:
    return json.dumps({"cards": [{"source_id": source_id, "question": question, "answer": "a", "tags": [], "changed": False}]})


def test_redo_all_sends_the_kept_cards_and_feedback(monkeypatch):
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
    assert session.feedback == ["all cards: ask why, not what"]


def _session_with(entry, *questions):
    return review.Review(entry, [review.Slot(review.batch.Card(entry.id, q, "a", [], False)) for q in questions])


def test_changing_one_card_rewrites_only_that_card(monkeypatch):
    entry = inbox.Entry.new("aws security services", "", "DevOps::AWS")
    session = _session_with(entry, "What are the five areas?", "Which services handle IAM?", "What is KMS?")
    session.slots[0].status = review.ACCEPTED
    seen = []
    reply = {"cards": [{"question": "Which services handle IAM, and why each?", "answer": "- **IAM**: who can do what", "tags": ["aws"]}]}
    monkeypatch.setattr(agents, "ask", lambda name, text, timeout=600, images=None: seen.append(text) or json.dumps(reply))

    review.revise(Config(), session, 1, "add bold signaling and why for each one")

    assert [s.card.question for s in session.slots] == ["What are the five areas?", "Which services handle IAM, and why each?", "What is KMS?"]
    assert session.slots[0].status == review.ACCEPTED, "other cards keep their verdict"
    assert session.slots[1].card.source_id == entry.id
    assert "add bold signaling and why for each one" in seen[0]
    assert "Which services handle IAM?" in seen[0] and "What is KMS?" in seen[0]
    assert session.feedback == ["card 2 (Which services handle IAM?): add bold signaling and why for each one"]


def test_only_accepted_cards_are_saved():
    entry = inbox.Entry.new("q", "a", "ruby")
    session = _session_with(entry, "one", "two", "three")
    session.slots[0].status = review.ACCEPTED
    session.slots[1].status = review.REMOVED
    assert [c.question for c in session.accepted()] == ["one"]


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
    session = _session_with(entry, "one")
    session._record("the year is wrong")
    monkeypatch.setattr(agents, "ask", lambda *a, **k: "NONE\n")
    assert review.suggest_rule(Config(), session) is None
    monkeypatch.setattr(agents, "ask", lambda *a, **k: "Prefer why questions.\n")
    assert review.suggest_rule(Config(), session) == "Prefer why questions."


def test_versions_belong_to_one_card_and_can_replace_it_or_be_added(monkeypatch):
    entry = inbox.Entry.new("aws security pillar services", "iam, cloudtrail", "DevOps::AWS")
    session = _session_with(entry, "Which service manages access?", "Which service logs API calls?")
    reply = {
        "versions": [
            {"style": "Application / scenario", "why": "ties it to a real situation", "cards": [{"question": "A Lambda must read one bucket. Which service?", "answer": "IAM"}]},
            {"style": "Reverse", "why": "recall the name from its job", "cards": [{"question": "Who decides who can do what?", "answer": "IAM"}]},
            "garbage",
        ]
    }
    seen = []
    monkeypatch.setattr(agents, "ask", lambda name, text, timeout=600, images=None: seen.append(text) or json.dumps(reply))

    found = review.versions(Config(), session, 0)

    assert [v.style for v in found] == ["Application / scenario", "Reverse"]
    assert session.slots[0].versions == found and session.slots[1].versions == []
    assert "Which service manages access?" in seen[0] and "Which service logs API calls?" in seen[0]
    review.use_version(session, 0, found[0], add=False)
    assert [s.card.question for s in session.slots] == ["A Lambda must read one bucket. Which service?", "Which service logs API calls?"]
    assert [v.style for v in session.slots[0].versions] == ["Original", "Reverse"], "other versions stay to keep choosing"
    assert session.slots[0].versions[0].cards[0].question == "Which service manages access?"
    review.use_version(session, 0, found[1], add=True)
    assert found[1].added and found[1] in session.slots[0].versions
    assert [s.card.question for s in session.slots] == [
        "A Lambda must read one bucket. Which service?",
        "Who decides who can do what?",
        "Which service logs API calls?",
    ]


def test_bloom_level_is_kept_validated_and_tagged(fake_anki, monkeypatch):
    entry = inbox.Entry.new("q", "a", "ruby")
    inbox.append(entry)
    reply = {"cards": [
        {"source_id": entry.id, "question": "Apply?", "answer": "a", "bloom": "Apply"},
        {"source_id": entry.id, "question": "Odd?", "answer": "a", "bloom": "memorize"},
    ]}
    monkeypatch.setattr(agents, "ask", lambda *a, **k: json.dumps(reply))

    batch.run(Config(anki_url=fake_anki.url), AnkiConnect(fake_anki.url))

    tags = {n["fields"]["Front"]: n["tags"] for n in fake_anki.notes}
    assert any("ah::bloom::apply" in t for t in tags.values())
    assert not any("memorize" in tag for t in tags.values() for tag in t)


def test_process_prompt_splits_lists_and_uses_bloom():
    text = agents.prompt("process", entries="", language="English", rules="")
    assert "Lists always split" in text and "## Bloom's taxonomy" in text
