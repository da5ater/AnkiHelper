import json

import pytest

from ankihelper import agents, batch, config, inbox
from ankihelper.anki import AnkiConnect, AnkiUnreachable
from ankihelper.config import Config


def capture(question, answer, topic):
    entry = inbox.Entry.new(question, answer, topic)
    inbox.append(entry)
    return entry


def entries_in_prompt(prompt_text: str) -> list[dict]:
    block = prompt_text.split("Entries (JSON lines", 1)[1].split("\n\n", 1)[1]
    return [json.loads(line) for line in block.strip().splitlines()]


class ScriptedAgent:
    """Stands in for the agent CLI: turns each entry into a card, with hooks to misbehave."""

    def __init__(self):
        self.calls: list[str] = []
        self.process_replies: list[str] = []

    def __call__(self, name, prompt_text, timeout=600):
        self.calls.append(prompt_text)
        if "failed to import" in prompt_text:
            card = json.loads(prompt_text.split("Card:\n", 1)[1].split("\n\nAnkiConnect error:", 1)[0])
            card["question"] = card["question"].replace("Rejectme", "").strip()
            return json.dumps(card)
        if self.process_replies:
            return self.process_replies.pop(0)
        cards, skipped = [], []
        for e in entries_in_prompt(prompt_text):
            if e["question"] == "uh":
                skipped.append({"source_id": e["id"], "reason": "unintelligible"})
                continue
            cards.append(
                {
                    "source_id": e["id"],
                    "question": e["question"].capitalize() + "?",
                    "answer": f"```bash\n{e['answer']}\n```" if e["answer"].startswith("rails") else e["answer"],
                    "tags": ["Rails Basics"],
                    "changed": e["answer"] == "",
                }
            )
        return "Here you go:\n```json\n" + json.dumps({"cards": cards, "skipped": skipped}) + "\n```"


@pytest.fixture
def agent(monkeypatch):
    scripted = ScriptedAgent()
    monkeypatch.setattr(agents, "ask", scripted)
    return scripted


@pytest.fixture
def setup(fake_anki):
    cfg = Config(anki_url=fake_anki.url)
    return cfg, AnkiConnect(fake_anki.url)


def test_batch_imports_cleaned_cards_into_topic_deck(setup, fake_anki, agent):
    cfg, anki = setup
    capture("how to generate a controller home with index", "rails generate controller Home index", "ruby")
    capture("what does git stash do", "", "git")

    summary = batch.run(cfg, anki)

    assert (summary.imported, summary.changed, summary.failed) == (2, 1, {})
    rails, git = fake_anki.notes
    assert rails["deckName"] == "manual::ruby"
    assert git["deckName"] == "manual::git", "new topic creates its deck"
    assert rails["modelName"] == "Basic+"
    assert "background: #272822" in rails["fields"]["Back"], "code is highlighted"
    assert rails["fields"]["Front"].startswith('<div style="font-weight:600')
    assert set(rails["tags"]) == {"rails-basics", "manual_voice"}
    assert "changed" in git["tags"]
    assert inbox.read_all() == [], "imported entries leave the inbox"
    assert fake_anki.synced == 1


def test_archive_keeps_raw_dictation_next_to_cleaned_card(setup, agent):
    cfg, anki = setup
    entry = capture("how to generate a controller", "rails generate controller Home", "ruby")

    batch.run(cfg, anki)

    [archive_file] = config.archive_dir().iterdir()
    record = json.loads(archive_file.read_text())
    assert record["entry"]["question"] == entry.question
    assert record["cards"][0]["card"]["question"] == "How to generate a controller?"


def test_rerunning_a_batch_skips_cards_already_in_anki(setup, fake_anki, agent):
    cfg, anki = setup
    capture("what is a gem", "a ruby library", "ruby")
    batch.run(cfg, anki)
    capture("what is a gem", "a ruby library", "ruby")

    summary = batch.run(cfg, anki)

    assert (summary.imported, summary.duplicates) == (0, 1)
    assert len(fake_anki.notes) == 1
    assert inbox.read_all() == []


def test_rejected_card_is_repaired_by_the_agent(setup, fake_anki, agent):
    cfg, anki = setup
    capture("REJECTME what is rack", "a webserver interface", "ruby")

    summary = batch.run(cfg, anki)

    assert summary.imported == 1
    assert "rejectme" not in fake_anki.notes[0]["fields"]["Front"].lower()
    assert sum("failed to import" in c for c in agent.calls) == 1


def test_card_that_stays_broken_is_kept_in_inbox_with_its_error(setup, fake_anki, agent):
    cfg, anki = setup
    fake_anki.reject_fronts_containing = "rack"
    capture("what is rack", "a webserver interface", "ruby")
    capture("what is a gem", "a ruby library", "ruby")

    summary = batch.run(cfg, anki)

    assert summary.imported == 1
    assert sum("failed to import" in c for c in agent.calls) == batch.REPAIR_ATTEMPTS
    [left] = inbox.read_all()
    assert left.question == "what is rack"
    assert left.attempts == 1 and "forbidden marker" in left.error


def test_unusable_dictation_is_skipped_not_imported(setup, fake_anki, agent):
    cfg, anki = setup
    capture("uh", "", "ruby")

    summary = batch.run(cfg, anki)

    assert (summary.imported, summary.skipped) == (0, 1)
    assert inbox.read_all() == []


def test_malformed_agent_reply_leaves_inbox_untouched(setup, fake_anki, agent):
    cfg, anki = setup
    agent.process_replies = ["sorry, I can't", "still not json"]
    capture("what is a gem", "a ruby library", "ruby")

    with pytest.raises(agents.AgentError):
        batch.run(cfg, anki)

    assert len(inbox.read_all()) == 1
    assert fake_anki.notes == []


def test_malformed_reply_is_retried_once(setup, fake_anki, agent):
    cfg, anki = setup
    agent.process_replies = ["not json"]
    capture("what is a gem", "a ruby library", "ruby")

    assert batch.run(cfg, anki).imported == 1


def test_anki_unreachable_is_reported_before_calling_the_agent(agent, monkeypatch):
    from ankihelper.platforms import current

    monkeypatch.setattr(current, "anki_installed", lambda: False)
    capture("what is a gem", "a ruby library", "ruby")

    with pytest.raises(AnkiUnreachable):
        batch.run(Config(anki_url="http://127.0.0.1:9"), AnkiConnect("http://127.0.0.1:9"))

    assert agent.calls == []
    assert len(inbox.read_all()) == 1


def test_capture_during_batch_is_not_lost(setup, agent, monkeypatch):
    cfg, anki = setup
    capture("what is a gem", "a ruby library", "ruby")
    original = batch.clean

    def clean_while_user_captures(*args):
        result = original(*args)
        capture("captured mid-batch", "yes", "ruby")
        return result

    monkeypatch.setattr(batch, "clean", clean_while_user_captures)
    batch.run(cfg, anki)

    assert [e.question for e in inbox.read_all()] == ["captured mid-batch"]
