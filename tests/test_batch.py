import json

import pytest

from ankihelper import agents, batch, config, inbox
from ankihelper.anki import AnkiConnect, AnkiUnreachable, SetupProblem
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
        self.images: list[list[str]] = []
        self.process_replies: list[str] = []

    def __call__(self, name, prompt_text, timeout=600, images=None):
        self.calls.append(prompt_text)
        self.images.append(images or [])
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
            if "split" in e["question"]:
                cards += [
                    {"source_id": e["id"], "question": f"part {n} of {e['question']}", "answer": "x", "tags": [], "changed": False}
                    for n in (1, 2, 3)
                ]
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


def test_anki_dying_mid_batch_keeps_what_was_already_imported(setup, fake_anki, agent, monkeypatch):
    cfg, anki = setup
    capture("what is a gem", "a ruby library", "ruby")
    capture("what is rack", "a webserver interface", "ruby")
    original = anki.add_note
    calls = []

    def add_then_die(*args):
        calls.append(args)
        if len(calls) == 2:
            raise AnkiUnreachable("connection reset")
        return original(*args)

    monkeypatch.setattr(anki, "add_note", add_then_die)
    with pytest.raises(AnkiUnreachable):
        batch.run(cfg, anki)

    [left] = inbox.read_all()
    assert left.question == "what is rack"
    assert left.cards and left.cards[0]["question"] == "What is rack?", "cleaned card is kept for the retry"
    assert len(fake_anki.notes) == 1


def test_split_entry_retries_only_the_cards_that_failed_without_asking_the_agent_again(setup, fake_anki, agent):
    cfg, anki = setup
    fake_anki.reject_fronts_containing = "part 2"
    capture("split what are the three ruby scopes", "local global instance", "ruby")

    first = batch.run(cfg, anki)
    assert first.imported == 1 and len(first.failed) == 1
    [left] = inbox.read_all()
    assert [c["question"] for c in left.cards] == ["part 2 of split what are the three ruby scopes", "part 3 of split what are the three ruby scopes"]

    fake_anki.reject_fronts_containing = "never matches"
    cleaning_calls = sum("Entries (JSON lines" in c for c in agent.calls)
    second = batch.run(cfg, anki)

    assert (second.imported, second.duplicates) == (2, 0)
    assert sum("Entries (JSON lines" in c for c in agent.calls) == cleaning_calls
    assert len(fake_anki.notes) == 3
    assert inbox.read_all() == []


def test_second_batch_while_one_runs_is_refused(setup, agent):
    from filelock import FileLock

    cfg, anki = setup
    capture("what is a gem", "a ruby library", "ruby")
    with FileLock(str(config.data_dir() / "batch.lock")):
        with pytest.raises(batch.BatchRunning):
            batch.run(cfg, anki)
    assert len(inbox.read_all()) == 1


def test_reply_with_wrong_shape_is_retried(setup, agent):
    cfg, anki = setup
    agent.process_replies = ['{"cards": [1, 2]}']
    capture("what is a gem", "a ruby library", "ruby")

    assert batch.run(cfg, anki).imported == 1


def test_missing_note_type_is_a_setup_problem(fake_anki, agent):
    capture("what is a gem", "a ruby library", "ruby")
    cfg = Config(anki_url=fake_anki.url, note_type="Nope")

    with pytest.raises(SetupProblem):
        batch.run(cfg, AnkiConnect(fake_anki.url))
    assert agent.calls == []


def test_large_inbox_is_sent_in_chunks_over_stdin(setup, fake_anki, agent):
    cfg, anki = setup
    for n in range(45):
        capture(f"question number {n} " + "padding " * 400, "answer", "ruby")

    summary = batch.run(cfg, anki)

    assert summary.imported == 45
    assert sum("Entries (JSON lines" in c for c in agent.calls) == 3


def test_pasted_pictures_are_uploaded_and_shown_under_question_and_answer(setup, fake_anki, agent):
    cfg, anki = setup
    entry = inbox.Entry.new("what does this diagram show", "the rails request cycle", "ruby")
    entry.images = [{"file": "ankihelper-q.png", "field": "question"}, {"file": "ankihelper-a.png", "field": "answer"}]
    for image in entry.images:
        (config.media_dir() / image["file"]).write_bytes(b"png-bytes")
    inbox.append(entry)

    summary = batch.run(cfg, anki)

    assert summary.imported == 1
    assert set(fake_anki.media) == {"ankihelper-q.png", "ankihelper-a.png"}
    note = fake_anki.notes[0]
    assert '<img src="ankihelper-q.png"' in note["fields"]["Front"]
    assert '<img src="ankihelper-a.png"' in note["fields"]["Back"]
    assert '"question_images": 1' in agent.calls[0]


def test_read_pictures_go_to_the_agent_and_end_up_as_source(setup, fake_anki, agent):
    cfg, anki = setup
    entry = inbox.Entry.new("", "", "ruby")
    entry.images = [{"file": "ankihelper-quiz.png", "field": "question", "mode": "read"}]
    (config.media_dir() / "ankihelper-quiz.png").write_bytes(b"png-bytes")
    inbox.append(entry)
    agent.process_replies = [
        json.dumps({"cards": [{"source_id": entry.id, "question": "Which status code means moved permanently?", "answer": "301", "tags": ["http"], "changed": True}]})
    ]

    assert batch.run(cfg, anki).imported == 1

    [sent] = agent.images
    assert sent == [str(config.media_dir() / "ankihelper-quiz.png")]
    assert str(config.media_dir() / "ankihelper-quiz.png") in agent.calls[0]
    note = fake_anki.notes[0]
    assert "<img" not in note["fields"]["Front"], "a read picture is not repeated on the front"
    assert "Source" in note["fields"]["Back"] and 'src="ankihelper-quiz.png"' in note["fields"]["Back"]
    assert "ankihelper-quiz.png" in fake_anki.media


def test_show_pictures_are_never_sent_to_the_agent(setup, agent):
    cfg, anki = setup
    entry = inbox.Entry.new("what does this diagram show", "the request cycle", "ruby")
    entry.images = [{"file": "ankihelper-d.png", "field": "question", "mode": "show"}]
    (config.media_dir() / "ankihelper-d.png").write_bytes(b"png-bytes")
    inbox.append(entry)

    batch.run(cfg, anki)

    assert agent.images == [[]]
