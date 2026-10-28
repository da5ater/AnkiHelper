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

from . import agents, config, learning, notes, render
from .batch import Card, card_html
from .config import Config
from .inbox import Entry

FIXED_TAG = "ah::fixed"


def text_of(fragment: str) -> str:
    fragment = re.sub(r"(?i)<br\s*/?>|</(p|div|li|pre|tr)>", "\n", fragment)
    return html.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


def _images_in(fragment: str) -> str:
    return "".join(re.findall(r"<img\b[^>]*>", fragment))


def rewrite(cfg: Config, note_id: int, question_html: str, answer_html: str, feedback: str) -> dict:
    """New question and answer HTML for a note, from the learner's feedback. Works for any note in Anki."""
    record = notes.find(note_id)
    entry = Entry(**record["entry"]) if record else None
    current = record["card"] if record else {"question": text_of(question_html), "answer": text_of(answer_html)}
    original = {"question": entry.question, "answer": entry.answer} if entry else {}
    text = agents.prompt(
        "fix_note",
        language=(entry.language if entry and entry.language else cfg.language),
        rules=config.personal_rules() or "(none yet)",
        original=json.dumps(original, ensure_ascii=False),
        card=json.dumps({"question": current["question"], "answer": current["answer"]}, ensure_ascii=False),
        feedback=feedback,
    )
    reply = agents.extract_json(agents.ask(cfg.agent, text))
    card = Card.parse({**(record["card"] if record else {}), **reply, "source_id": entry.id if entry else "", "changed": True})
    if entry:
        front, back = card_html(card, entry)
        notes.record(note_id, entry, card)
    else:
        front = render.question_html(card.question) + _images_in(question_html)
        back = render.to_html(card.answer) + _images_in(answer_html)
    learning.log(
        {
            "kind": "fix",
            "note_id": note_id,
            "feedback": feedback,
            "before": {"question": current["question"], "answer": current["answer"]},
            "after": {"question": card.question, "answer": card.answer},
        }
    )
    return {"front": front, "back": back, "add_tags": [FIXED_TAG], "bloom": card.bloom}


RECENT_WRITE_SECONDS = 120


def _writes_path():
    return config.data_dir() / "recent_writes.json"


def note_written(note_id: int) -> None:
    """Remember that AnkiHelper itself just changed this note, so the add-on's edit report is not taken as the learner's."""
    path = _writes_path()
    writes = json.loads(path.read_text()) if path.exists() else {}
    now = datetime.now().timestamp()
    writes = {k: t for k, t in writes.items() if now - t < RECENT_WRITE_SECONDS}
    writes[str(note_id)] = now
    path.write_text(json.dumps(writes))


def report(request: dict) -> bool:
    """Record the edits and deletions the add-on saw ({"events": [...]}). Returns whether it is time to look for patterns."""
    path = _writes_path()
    writes = json.loads(path.read_text()) if path.exists() else {}
    now = datetime.now().timestamp()
    for event in request.get("events") or [request]:
        written = writes.get(str(event.get("note_id")))
        if event.get("kind") == "edit" and written and now - written < RECENT_WRITE_SECONDS:
            continue
        learning.log(event)
    return learning.due()


def fix_flagged(cfg: Config, anki) -> tuple[int, list[str]]:
    """Rewrite the cards the learner flagged in Anki. Returns (fixed count, errors); failures stay flagged."""
    items, fixed, errors, retry = take_flagged(), 0, [], []
    for item in items:
        try:
            [info] = anki.notes_info([item["note_id"]])
            fields = sorted(info["fields"].items(), key=lambda kv: kv[1]["order"])
            if len(fields) < 2:
                raise ValueError("the note has fewer than two fields")
            (q_name, q), (a_name, a) = fields[0], fields[1]
            result = rewrite(cfg, item["note_id"], q["value"], a["value"], item["feedback"])
            note_written(item["note_id"])
            anki.update_fields(item["note_id"], {q_name: result["front"], a_name: result["back"]})
            anki.add_tags([item["note_id"]], result["add_tags"])
            fixed += 1
        except Exception as error:  # one bad flag must not stop the others; it stays flagged
            errors.append(f"note {item['note_id']}: {error}")
            retry.append(item)
    return_flagged(retry)
    return fixed, errors


def _flagged_path():
    return config.data_dir() / "flagged.jsonl"


def flag(note_id: int, feedback: str) -> None:
    with FileLock(str(_flagged_path()) + ".lock"), _flagged_path().open("a") as f:
        f.write(json.dumps({"note_id": note_id, "feedback": feedback, "time": datetime.now().isoformat(timespec="seconds")}) + "\n")
    learning.log({"kind": "flag", "note_id": note_id, "feedback": feedback})


def has_flagged() -> bool:
    path = _flagged_path()
    return path.exists() and bool(path.read_text().strip())


def take_flagged() -> list[dict]:
    with FileLock(str(_flagged_path()) + ".lock"):
        path = _flagged_path()
        if not path.exists():
            return []
        items = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        path.write_text("")
        return items


def return_flagged(items: list[dict]) -> None:
    with FileLock(str(_flagged_path()) + ".lock"), _flagged_path().open("a") as f:
        for item in items:
            f.write(json.dumps(item) + "\n")


def history(note_id: int) -> dict:
    """Where a note came from: the learner's original note, its sibling cards and the versions it was offered."""
    record = notes.find(note_id)
    if not record:
        return {"known": False}
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
