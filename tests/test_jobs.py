import json

from ankihelper import agents, batch, bridge, config, inbox, jobs, review
from ankihelper.anki import AnkiConnect
from ankihelper.config import Config


def make_cards(fake_anki, count):
    anki = AnkiConnect(fake_anki.url)
    fake_anki.decks.add("other")
    for n in range(count):
        anki.add_note("other", "Basic+", f"<p>Question {n}?</p>", f"<p>A very long example {n}</p>", [])
    return anki


def changes_every_other_card(name, text, timeout=600, images=None):
    cards = [json.loads(line) for line in text.split("Cards (JSON lines):\n", 1)[1].split("\n\nReply", 1)[0].splitlines()]
    return json.dumps({"cards": [
        {"note_id": c["note_id"], "changed": c["note_id"] % 2 == 0, "question": c["question"], "answer": "Minimal."} for c in cards
    ]})


def test_a_rule_job_works_through_cards_one_batch_at_a_time_and_resumes(fake_anki, monkeypatch):
    anki = make_cards(fake_anki, 23)
    monkeypatch.setattr(agents, "ask", changes_every_other_card)
    cfg = Config(anki_url=fake_anki.url, rule_batch_size=10)
    job = jobs.start(cfg, anki, "Keep examples minimal.", "all")
    assert len(job["queue"]) == 23

    first = jobs.run_batch(cfg, anki)
    assert (first["checked"], first["changed"]) == (10, 5)
    assert jobs.all_jobs()[0]["next"] == 10, "progress is saved after every batch"
    jobs.run_batch(cfg, anki)
    jobs.run_batch(cfg, anki)

    [done] = jobs.all_jobs()
    assert done["status"] == jobs.DONE and done["next"] == 23
    assert len(done["changed"]) == 11
    assert "Minimal." in fake_anki.notes[1]["fields"]["Back"], "note 2 was changed"
    assert "very long example 0" in fake_anki.notes[0]["fields"]["Back"], "note 1 was left alone"
    assert f"ah::rule::{job['id']}" in fake_anki.notes[1]["tags"]
    assert jobs.run_batch(cfg, anki) is None


def test_undo_puts_back_every_card_a_job_changed(fake_anki, monkeypatch):
    anki = make_cards(fake_anki, 4)
    monkeypatch.setattr(agents, "ask", changes_every_other_card)
    cfg = Config(anki_url=fake_anki.url)
    job = jobs.start(cfg, anki, "Keep examples minimal.", "all")
    jobs.run_batch(cfg, anki)

    assert jobs.undo(cfg, anki, job["id"]) == 2
    assert all("very long example" in n["fields"]["Back"] for n in fake_anki.notes)
    assert not any(t.startswith("ah::rule::") for n in fake_anki.notes for t in n["tags"])


def test_pushing_back_on_an_updated_card_rewords_the_rule_and_rechecks_updated_cards(fake_anki, monkeypatch):
    anki = make_cards(fake_anki, 4)
    review.save_rule("Keep examples minimal.")
    monkeypatch.setattr(agents, "ask", changes_every_other_card)
    cfg = Config(anki_url=fake_anki.url)
    job = jobs.start(cfg, anki, "Keep examples minimal.", "all")
    jobs.run_batch(cfg, anki)
    assert jobs.all_jobs()[0]["status"] == jobs.DONE

    def agent(name, text, timeout=600, images=None):
        if "Reword the rules" in text:
            return json.dumps({"rules": ["Keep examples minimal, except for commands: show the full command."]})
        return json.dumps({"question": "Q?", "answer": "A full command example", "bloom": "apply"})

    monkeypatch.setattr(agents, "ask", agent)
    reply = bridge.rewrite(cfg, 2, "<p>Question 1?</p>", "<p>Minimal.</p>", "no, for commands I need the full command", [f"ah::rule::{job['id']}"])

    assert reply["rule_updated"].startswith("Keep examples minimal, except for commands")
    [updated] = jobs.all_jobs()
    assert jobs.rules_of(updated) == ["Keep examples minimal, except for commands: show the full command."]
    assert updated["version"] == 2 and updated["status"] == jobs.RUNNING
    assert updated["queue"][updated["next"]:] == [2, 4], "cards changed under the old wording are rechecked"
    assert "except for commands" in config.personal_rules() and "- Keep examples minimal.\n" not in config.personal_rules() + "\n"


def test_optimizing_an_existing_card_keeps_it_unless_asked_to_replace(fake_anki, monkeypatch):
    anki = make_cards(fake_anki, 1)
    cfg = Config(anki_url=fake_anki.url)
    entry = bridge.optimize(cfg, 1, "<p>Question 0?</p>", "<p>A very long example 0</p>", "other")
    assert (entry.deck, entry.source_note) == ("other", 1)
    cards = [
        {"source_id": entry.id, "question": "Cleaned question?", "answer": "Short.", "group": "main"},
        {"source_id": entry.id, "question": "Why does it matter?", "answer": "Because.", "group": "optimized"},
    ]

    inbox.approve(entry.id, cards, replace_source=True)
    batch.run(cfg, anki)

    assert len(fake_anki.notes) == 2, "the first card rewrote the original in place; one card was added"
    assert "Cleaned question?" in fake_anki.notes[0]["fields"]["Front"]
    assert fake_anki.notes[1]["deckName"] == "other"


def test_default_batch_is_fifty_cards(fake_anki, monkeypatch):
    anki = make_cards(fake_anki, 60)
    monkeypatch.setattr(agents, "ask", changes_every_other_card)
    cfg = Config(anki_url=fake_anki.url)
    jobs.start(cfg, anki, "Keep examples minimal.", "all")
    assert jobs.run_batch(cfg, anki)["checked"] == 50


def test_a_successful_fix_now_clears_its_saved_request():
    bridge.flag(5, "shorter")
    bridge.flag(6, "ask why")
    bridge.unflag_note(5)
    assert [i["note_id"] for i in bridge.list_flagged()] == [6]


def test_several_rules_are_applied_in_one_pass(fake_anki, monkeypatch):
    anki = make_cards(fake_anki, 3)
    seen = []
    monkeypatch.setattr(agents, "ask", lambda name, text, timeout=600, images=None: seen.append(text) or changes_every_other_card(name, text))
    cfg = Config(anki_url=fake_anki.url)
    job = jobs.start(cfg, anki, ["Keep examples minimal.", "Ask why, not what."], "all")
    jobs.run_batch(cfg, anki)
    assert "- Keep examples minimal.\n- Ask why, not what." in seen[0]
    assert jobs.rules_of(job) == ["Keep examples minimal.", "Ask why, not what."]


def test_a_conversation_is_kept_as_learning_material(monkeypatch):
    from ankihelper import learning

    entry = inbox.Entry.new("what is a controller", "", "ruby::rails")
    from ankihelper import notes
    from ankihelper.batch import Card

    notes.record(9, entry, Card(entry.id, "What is a controller?", "A class.", [], False))
    monkeypatch.setattr(agents, "ask", lambda *a, **k: json.dumps({"reply": "Here is a smaller one.", "card": {"question": "Write a minimal Rails controller with an index action.", "answer": "```ruby\nclass HomeController < ApplicationController\n  def index; end\nend\n```"}}))
    messages = [{"role": "learner", "text": "make me write a controller instead"}, {"role": "agent", "text": "Here is a full one"}, {"role": "learner", "text": "too much, shorten the controller part"}]

    turn = bridge.chat(Config(), 9, "<p>What is a controller?</p>", "<p>A class.</p>", messages, None)
    assert turn["reply"] == "Here is a smaller one." and "HomeController" in turn["back"]

    bridge.finish_chat(Config(), 9, {"question": "<p>What is a controller?</p>", "answer": "<p>A class.</p>"}, turn["card"], messages, [])
    [event] = learning.pending()
    assert event["kind"] == "conversation" and "too much, shorten the controller part" in event["transcript"][-1]
    assert notes.find(9)["card"]["question"].startswith("Write a minimal Rails controller")


def test_the_tutor_can_propose_new_cards_and_they_are_remembered(monkeypatch):
    from ankihelper import learning

    reply = {
        "reply": "Service discovery is how services **find each other** at runtime.",
        "new_cards": [{"question": "In microservices, what problem does a service registry solve?", "answer": "Lets services find each other's current addresses.", "bloom": "understand"}],
    }
    monkeypatch.setattr(agents, "ask", lambda *a, **k: json.dumps(reply))
    turn = bridge.chat(Config(), 11, "<p>What is service discovery?</p>", "<p>?</p>", [{"role": "learner", "text": "teach me this"}], None)

    assert "<strong>find each other</strong>" in turn["reply_html"]
    assert "card" not in turn, "teaching alone does not change the card"
    [card] = turn["new_cards"]
    assert "service registry" in card["front"] and "ah::chat" in card["tags"]

    bridge.finish_chat(Config(), 11, {"question": "<p>What is service discovery?</p>", "answer": "<p>?</p>"}, None, [{"role": "learner", "text": "teach me this"}], [], [card])
    [event] = learning.pending()
    assert event["added_cards"][0]["question"].startswith("In microservices")


def test_a_reason_given_after_an_edit_reaches_learning():
    from ankihelper import learning

    bridge.report({"events": [{"kind": "edit", "note_id": 3, "before": {"question": "q", "answer": "a"}, "after": {"question": "q", "answer": "b"}, "why": "learned it from ChatGPT"}]})
    [event] = learning.pending()
    assert learning._describe(event)["why"] == "learned it from ChatGPT"


def test_pictures_in_the_chat_are_handed_to_the_agent_to_read(monkeypatch):
    seen = {}

    def agent(name, text, timeout=600, images=None):
        seen["text"], seen["images"] = text, images
        return json.dumps({"reply": "That diagram shows a load balancer."})

    monkeypatch.setattr(agents, "ask", agent)
    messages = [{"role": "learner", "text": "what is this?\nsecond line", "images": ["/media/ankihelper-chat-1.png"]}]
    bridge.chat(Config(), 12, "<p>Q?</p>", "<p>A</p>", messages, None)

    assert seen["images"] == ["/media/ankihelper-chat-1.png"]
    assert "attached pictures, read them: /media/ankihelper-chat-1.png" in seen["text"]
    assert "second line" in seen["text"]


def test_progress_shows_time_left_and_the_latest_changes(fake_anki, monkeypatch):
    anki = make_cards(fake_anki, 30)
    monkeypatch.setattr(agents, "ask", changes_every_other_card)
    cfg = Config(anki_url=fake_anki.url, rule_batch_size=10)
    job = jobs.start(cfg, anki, "Keep examples minimal.", "all")
    jobs.run_batch(cfg, anki)

    [current] = jobs.all_jobs()
    assert jobs.time_left(current, 10) == "about 3 min left", "2 batches left at one batch every 90 seconds"
    recent = jobs.recent_changes(job["id"])
    assert len(recent) == 5 and recent[0]["note_id"] == 10, "newest first"
    assert "very long example" in list(recent[0]["fields"].values())[1]
