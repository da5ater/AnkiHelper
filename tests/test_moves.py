import json

from ankihelper import agents, bridge, inbox, learning, moves, notes, review
from ankihelper.batch import Card
from ankihelper.config import Config


def agent_replying(reply: dict, seen: list | None = None):
    def ask(name, text, timeout=600, images=None):
        if seen is not None:
            seen.append({"text": text, "images": images})
        return json.dumps(reply)

    return ask


def test_the_five_starting_moves_are_ordered_by_use():
    assert [m.name for m in moves.ordered()] == ["Word it better", "Make it a scenario", "Make me write it", "Split this", "Versions"]
    moves._change("split", lambda m: setattr(m, "uses", 3))
    assert moves.ordered()[0].name == "Split this"


def test_a_changing_move_rewrites_the_card_and_counts_a_use(monkeypatch):
    seen = []
    monkeypatch.setattr(agents, "ask", agent_replying({"reply": "Sharper.", "card": {"question": "What does `has_one` declare?", "answer": "The other side holds the foreign key."}}, seen))

    turn = bridge.run_move(Config(), 5, "word", "<p>what does has one do</p>", "<p>other side has key</p>", [], None)

    assert "has_one" in turn["front"] and "new_cards" not in turn
    assert "Word it better" in seen[0]["text"] and "Rewrite the card itself" in seen[0]["text"]
    assert moves.get("word").uses == 1


def test_an_adding_move_proposes_new_cards_tagged_with_the_move(monkeypatch):
    monkeypatch.setattr(agents, "ask", agent_replying({"reply": "Two scenarios.", "new_cards": [{"question": "A blog needs X. Which?", "answer": "Y"}, {"question": "A shop needs Z?", "answer": "W"}]}))

    turn = bridge.run_move(Config(), 5, "scenario", "<p>Q?</p>", "<p>A</p>", [], None)

    assert "card" not in turn
    assert [c["question"] for c in turn["new_cards"]] == ["A blog needs X. Which?", "A shop needs Z?"]
    assert "ah::group::scenario" in turn["new_cards"][0]["tags"]


def test_a_move_runs_on_the_latest_draft_and_sees_the_conversation(monkeypatch):
    seen = []
    monkeypatch.setattr(agents, "ask", agent_replying({"reply": "ok", "new_cards": []}, seen))
    messages = [{"role": "learner", "text": "only the commands I actually type, with exact arguments"}]

    bridge.run_move(Config(), 5, "write", "<p>old?</p>", "<p>old</p>", messages, {"question": "Draft question?", "answer": "Draft answer"})

    assert "Draft question?" in seen[0]["text"] and "old?" not in seen[0]["text"]
    assert "only the commands I actually type" in seen[0]["text"]


def test_saving_a_move_from_a_conversation_reads_all_of_it(monkeypatch):
    seen = []
    reply = {"name": "Commands I type", "icon": "⌨", "mode": "add", "instruction": "Make cards only for the commands I would actually type, with exact arguments."}
    monkeypatch.setattr(agents, "ask", agent_replying(reply, seen))
    messages = [
        {"role": "learner", "text": "what are the steps"},
        {"role": "agent", "text": "1. understand MVC 2. generate controller 3. ..."},
        {"role": "learner", "text": "no, only the rails generate controller posts index part, the thing I type"},
    ]

    draft = bridge.draft_move(Config(), "<p>How does yield work in a layout?</p>", "<p>...</p>", messages)
    saved = moves.create(draft["name"], draft["icon"], draft["mode"], draft["instruction"])

    assert "what are the steps" in seen[0]["text"] and "the thing I type" in seen[0]["text"]
    assert saved.id == "commands-i-type" and moves.get("commands-i-type").mode == moves.ADD


def test_teaching_a_move_shows_the_change_and_can_be_undone(monkeypatch):
    monkeypatch.setattr(agents, "ask", lambda *a, **k: "Put the knowledge in a realistic blog or shop app, never abstract names.")
    old = moves.get("scenario").instruction

    new = moves.teach(Config(), "scenario", [{"role": "learner", "text": "use a real app like a blog, not Foo and Bar"}])
    moves.update_instruction("scenario", new)
    assert moves.get("scenario").instruction.startswith("Put the knowledge in a realistic blog")

    moves.undo("scenario")
    assert moves.get("scenario").instruction == old


def test_a_move_remembers_only_the_last_three_results_kept():
    for n in range(5):
        moves.record_example("write", {"question": f"q{n}"}, {"question": f"r{n}"})
    assert [e["result"]["question"] for e in moves.get("write").examples] == ["r2", "r3", "r4"]


def test_finishing_a_conversation_teaches_the_moves_the_learner_kept():
    bridge.finish_chat(
        Config(),
        9,
        {"question": "<p>Q?</p>", "answer": "<p>A</p>"},
        {"question": "Better Q?", "answer": "A"},
        [{"role": "learner", "text": "[pressed the Word it better move]"}],
        [],
        [{"question": "Scenario?", "answer": "S"}],
        [{"move": "word", "result": {"question": "Better Q?", "answer": "A"}}, {"move": "scenario", "result": {"question": "Scenario?", "answer": "S"}}],
    )
    assert moves.get("word").examples[-1]["result"]["question"] == "Better Q?"
    assert moves.get("scenario").examples[-1]["before"]["question"] == "Q?"
    [event] = learning.events_since(0)
    assert event["kind"] == "conversation"


def test_the_nudge_waits_for_three_conversations_and_runs_once_a_day(monkeypatch):
    reply = {"moves": [{"name": "Input and output", "icon": "🔁", "mode": "add", "instruction": "Show the exact input and output and ask me to write the line.", "evidence": "3 conversations asked for input/output"}]}
    monkeypatch.setattr(agents, "ask", agent_replying(reply))
    for n in range(2):
        learning.log({"kind": "conversation", "note_id": n, "transcript": ["learner: give me input and output"]})
    assert not moves.nudge_due() and moves.nudge(Config()) == []

    learning.log({"kind": "conversation", "note_id": 3, "transcript": ["learner: input and output please"]})
    assert moves.nudge_due()
    [found] = moves.nudge(Config())
    assert found["name"] == "Input and output"
    assert not moves.nudge_due(), "at most once a day"

    created = moves.accept_suggestion(0, "Show the exact input and output, then ask me to write the one line.")
    assert moves.suggestions() == [] and moves.get(created.id).instruction.startswith("Show the exact input")


def _session(entry, *questions):
    return review.Review(entry, [review.Slot(Card(entry.id, q, "a", [], False)) for q in questions])


def test_in_preview_an_adding_move_hangs_its_cards_under_the_card(monkeypatch):
    entry = inbox.Entry.new("what is an enum", "", "ruby::rails")
    session = _session(entry, "What is an enum in Rails?")
    monkeypatch.setattr(agents, "ask", agent_replying({"reply": "ok", "new_cards": [{"question": "An orders table has status 0,1,2. Write the enum line.", "answer": "enum status: {...}"}]}))

    review.apply_move(Config(), session, 0, "write")

    [version] = session.slots[0].versions
    assert version.move == "write" and version.style == "⌨ Make me write it"
    assert session.slots[0].card.question == "What is an enum in Rails?", "the original card is untouched"
    review.use_version(session, 0, version, add=True)
    session.slots[1].status = review.ACCEPTED
    session.teach_moves()
    assert moves.get("write").examples[-1]["result"]["question"].startswith("An orders table")


def test_in_preview_a_changing_move_keeps_the_original_and_a_correction_offers_teaching(monkeypatch):
    entry = inbox.Entry.new("what is an enum", "", "ruby::rails")
    session = _session(entry, "what is enum")
    monkeypatch.setattr(agents, "ask", agent_replying({"reply": "ok", "card": {"question": "In Rails, what does `enum` give a model?", "answer": "Named values for an integer column."}}))

    review.apply_move(Config(), session, 0, "word")
    assert session.slots[0].card.question.startswith("In Rails")
    assert session.slots[0].versions[0].style == "Original"

    monkeypatch.setattr(agents, "ask", agent_replying({"cards": [{"question": "In Rails, what does `enum` give a model, with an example?", "answer": "Named values, e.g. `order.shipped!`."}]}))
    review.revise(Config(), session, 0, "always add one tiny example")
    assert session.slots[0].teach == ("word", "always add one tiny example")


def test_the_card_chat_no_longer_teaches_and_reads_pasted_pictures(monkeypatch):
    seen = []
    monkeypatch.setattr(agents, "ask", agent_replying({"reply": "Done."}, seen))
    messages = [{"role": "learner", "text": "use this idea for the card", "images": ["/media/ankihelper-chat-1.png"]}]

    bridge.chat(Config(), 12, "<p>Q?</p>", "<p>A</p>", messages, None)

    assert seen[0]["images"] == ["/media/ankihelper-chat-1.png"]
    assert "You do not teach" in seen[0]["text"] and "{rules}" not in seen[0]["text"]
