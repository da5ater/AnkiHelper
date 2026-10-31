"""What the Anki add-on asks AnkiHelper to do.

The add-on runs inside Anki's own Python, which lacks AnkiHelper's dependencies, so it calls
`ankihelper anki <command>` with a JSON request on stdin and reads a JSON reply on stdout.
"""

import html
import json
import re
from dataclasses import asdict
from datetime import datetime

from filelock import FileLock

from . import agents, config, learning, moves, notes, render
from .batch import Card, card_html
from .config import Config
from .inbox import Entry

FIXED_TAG = "ah::fixed"
RECENT_WRITE_SECONDS = 120

SOURCE_BLOCK = re.compile(r"Source<br>((?:<img\b[^>]*>)+)")
"""The "Source" caption AnkiHelper puts above a read picture; the picture stays, the caption is not card text."""


def text_of(fragment: str) -> str:
    fragment = SOURCE_BLOCK.sub("", fragment)
    fragment = re.sub(r"(?i)<br\s*/?>|</(p|div|li|pre|tr)>", "\n", fragment)
    return html.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


def _images_in(fragment: str) -> str:
    return "".join(re.findall(r"<img\b[^>]*>", fragment))


def _context(cfg: Config, note_id: int) -> tuple[dict | None, Entry | None, str]:
    record = notes.find(note_id)
    entry = Entry(**record["entry"]) if record else None
    language = entry.language if entry and entry.language else cfg.language
    return record, entry, language


def _messages_text(messages: list[dict]) -> str:
    return "\n".join(
        f"{m['role']}: {m['text']}" + (f" [attached pictures, read them: {', '.join(m['images'])}]" if m.get("images") else "")
        for m in messages[-30:]
    )


def _pictures(messages: list[dict]) -> list[str]:
    return [path for m in messages[-30:] for path in m.get("images") or []]


def _render_reply(reply: dict, record: dict | None, entry: Entry | None, question_html: str, answer_html: str, group: str) -> dict:
    """Turn an agent's {"reply", "card", "new_cards"} into what the add-on shows: text plus ready HTML."""
    said = str(reply.get("reply") or "").strip() or "Done."
    answer: dict = {"reply": said, "reply_html": render.to_html(said)}
    raw = reply.get("card")
    if isinstance(raw, dict) and raw.get("question") and raw.get("answer"):
        card = Card.parse({**(record["card"] if record else {}), **raw, "source_id": entry.id if entry else "", "changed": True})
        answer["card"] = {"question": card.question, "answer": card.answer, "bloom": card.bloom}
        answer["front"] = render.question_html(card.question) + _images_in(question_html)
        answer["back"] = render.to_html(card.answer) + _images_in(answer_html)
    new_cards = []
    for raw_new in (reply.get("new_cards") or [])[:4]:
        if isinstance(raw_new, dict) and raw_new.get("question") and raw_new.get("answer"):
            card = Card.parse({**raw_new, "source_id": entry.id if entry else "", "changed": True, "group": group})
            tags = [f"ah::group::{card.group}"] + ([f"ah::bloom::{card.bloom}"] if card.bloom else [])
            new_cards.append(
                {
                    "question": card.question,
                    "answer": card.answer,
                    "front": render.question_html(card.question),
                    "back": render.to_html(card.answer),
                    "tags": tags,
                }
            )
    if new_cards:
        answer["new_cards"] = new_cards
    return answer


def chat(cfg: Config, note_id: int, question_html: str, answer_html: str, messages: list[dict], draft: dict | None) -> dict:
    """One turn of the learner's conversation about a card: a short reply, and maybe a new draft or new cards."""
    record, entry, language = _context(cfg, note_id)
    text = agents.prompt(
        "chat_card",
        language=language,
        original=json.dumps({"question": entry.question, "answer": entry.answer} if entry else {}, ensure_ascii=False),
        card=json.dumps({"question": text_of(question_html), "answer": text_of(answer_html)}, ensure_ascii=False),
        draft=json.dumps(draft or {}, ensure_ascii=False),
        messages=_messages_text(messages),
    )
    reply = agents.extract_json(agents.ask(cfg.agent, text, images=_pictures(messages)))
    return _render_reply(reply, record, entry, question_html, answer_html, "chat")


def run_move(cfg: Config, note_id: int, move_id: str, question_html: str, answer_html: str, messages: list[dict], draft: dict | None) -> dict:
    """Press a move on a card in Anki. Works on the latest draft when the conversation already changed the card."""
    record, entry, language = _context(cfg, note_id)
    card = draft or {"question": text_of(question_html), "answer": text_of(answer_html)}
    original = {"question": entry.question, "answer": entry.answer} if entry else {}
    reply = moves.run(cfg, move_id, card, original, messages, _pictures(messages), language)
    return _render_reply(reply, record, entry, question_html, answer_html, move_id)


def draft_move(cfg: Config, question_html: str, answer_html: str, messages: list[dict]) -> dict:
    return moves.draft_from_conversation(cfg, {"question": text_of(question_html), "answer": text_of(answer_html)}, messages)


def finish_chat(
    cfg: Config,
    note_id: int,
    before_html: dict,
    draft: dict | None,
    messages: list[dict],
    tags: list[str],
    added: list[dict] | None = None,
    moves_used: list[dict] | None = None,
) -> dict:
    """The learner pressed OK or closed the window: remember the conversation, and teach each move the
    result the learner kept from it."""
    before = {"question": text_of(before_html["question"]), "answer": text_of(before_html["answer"])}
    record = notes.find(note_id)
    if record and draft:
        entry = Entry(**record["entry"])
        notes.record(note_id, entry, Card.parse({**record["card"], **draft, "source_id": entry.id, "changed": True}))
    learning.log(
        {
            "kind": "conversation",
            "note_id": note_id,
            "tags": tags,
            "before": before,
            "after": draft or before,
            **({"before_html": before_html} if draft else {}),
            "transcript": [f"{m['role']}: {m['text']}" for m in messages[-30:]],
            "added_cards": [{"question": c["question"], "answer": c["answer"]} for c in added or []],
        }
    )
    for used in moves_used or []:
        try:
            moves.record_example(used["move"], before, used["result"])
        except KeyError:
            continue
    return {"ok": True, "add_tags": [FIXED_TAG] if draft else [], "nudge_now": moves.nudge_due()}


def optimize(cfg: Config, note_id: int, question_html: str, answer_html: str, deck: str) -> Entry:
    """Turn an existing Anki card into an inbox entry so Preview can work on it with moves."""
    root = cfg.root_deck + "::"
    topic = deck[len(root) :] if deck.startswith(root) else deck
    entry = Entry.new(text_of(question_html), text_of(answer_html), topic)
    entry.source_note, entry.deck = note_id, deck
    from . import inbox

    inbox.append(entry)
    return entry


def _writes_path():
    return config.data_dir() / "recent_writes.json"


def _writes_lock() -> FileLock:
    return FileLock(str(_writes_path()) + ".lock")


def _recent_writes() -> dict:
    path = _writes_path()
    return json.loads(path.read_text()) if path.exists() else {}


def note_written(note_id: int) -> None:
    """Remember that AnkiHelper itself just changed this note, so the add-on's edit report is not taken as the learner's."""
    with _writes_lock():
        now = datetime.now().timestamp()
        writes = {k: t for k, t in _recent_writes().items() if now - t < RECENT_WRITE_SECONDS}
        writes[str(note_id)] = now
        _writes_path().write_text(json.dumps(writes))


def report(request: dict) -> None:
    """Record the edits and deletions the add-on saw ({"events": [...]})."""
    with _writes_lock():
        writes = _recent_writes()
    now = datetime.now().timestamp()
    for event in request.get("events") or [request]:
        written = writes.get(str(event.get("note_id")))
        if event.get("kind") == "edit" and written and now - written < RECENT_WRITE_SECONDS:
            continue
        learning.log(event)


CHANGE_LABELS = {"conversation": "Conversation with AnkiHelper", "fix": "Fixed by AnkiHelper", "edit": "Your own edit"}


def changes(note_id: int) -> list[dict]:
    """Everything that happened to one note, oldest first, for any card in Anki: conversations, fixes and
    hand edits. Changes AnkiHelper made carry the earlier version so it can be restored."""
    found = []
    for event in learning.events_for(note_id):
        kind = event.get("kind")
        if kind not in CHANGE_LABELS:
            continue
        said = event.get("why") or event.get("feedback") or ""
        if kind == "conversation":
            said = " / ".join(line[len("learner: ") :] for line in event.get("transcript", []) if line.startswith("learner: "))
        found.append(
            {
                "time": event.get("time", ""),
                "kind": CHANGE_LABELS[kind],
                "said": said,
                "before": event.get("before") or {},
                "after": event.get("after") or {},
                "added_cards": event.get("added_cards") or [],
                "restore": event.get("before_html"),
            }
        )
    return sorted(found, key=lambda c: c["time"])


def history(note_id: int) -> dict:
    """Where a note came from and everything that happened to it since. Cards AnkiHelper made also show
    the learner's original note, their sibling cards and the versions offered in Preview."""
    record = notes.find(note_id)
    if not record:
        return {"known": False, "changes": changes(note_id)}
    entry = Entry(**record["entry"])
    versions = []
    for version in record["card"].get("versions") or []:
        rendered = []
        for raw in version.get("cards") or []:
            card = Card.parse({**raw, "source_id": entry.id})
            front, back = card_html(card, entry)
            rendered.append({"card": asdict(card), "front": front, "back": back})
        versions.append({"style": version.get("style", ""), "why": version.get("why", ""), "cards": rendered})
    return {
        "known": True,
        "entry": {"question": entry.question, "answer": entry.answer, "topic": entry.topic, "created": entry.created, "images": entry.images or []},
        "media_dir": str(config.media_dir()),
        "card": record["card"],
        "siblings": [
            {"note_id": s["note_id"], "question": s["card"]["question"], "group": s["card"].get("group", "main")}
            for s in notes.siblings(entry.id)
            if s["note_id"] != note_id
        ],
        "versions": versions,
        "changes": changes(note_id),
    }


def use_version(note_id: int, card: dict) -> dict:
    """The learner picked a version in History: record it and return its HTML."""
    record = notes.find(note_id)
    entry = Entry(**record["entry"])
    chosen = Card.parse({**card, "source_id": entry.id, "versions": record["card"].get("versions") or []})
    notes.record(note_id, entry, chosen)
    learning.log({"kind": "fix", "note_id": note_id, "feedback": f"switched to the {chosen.group} version"})
    front, back = card_html(chosen, entry)
    return {"front": front, "back": back}
