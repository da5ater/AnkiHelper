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

from . import agents, config, jobs, learning, notes, render
from .batch import Card, card_html
from .config import Config
from .inbox import Entry

FIXED_TAG = "ah::fixed"
RECENT_WRITE_SECONDS = 120
CLOZE = 1


SOURCE_BLOCK = re.compile(r"Source<br>((?:<img\b[^>]*>)+)")
"""The "Source" caption AnkiHelper puts above a read picture; the picture stays, the caption is not card text."""


def text_of(fragment: str) -> str:
    fragment = SOURCE_BLOCK.sub("", fragment)
    fragment = re.sub(r"(?i)<br\s*/?>|</(p|div|li|pre|tr)>", "\n", fragment)
    return html.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


def _images_in(fragment: str) -> str:
    return "".join(re.findall(r"<img\b[^>]*>", fragment))


def rewrite(cfg: Config, note_id: int, question_html: str, answer_html: str, feedback: str, tags: list[str] | None = None) -> dict:
    """New question and answer HTML for a note, from the learner's feedback.

    The card as it is in Anki now is what gets rewritten, so hand edits and added pictures survive;
    AnkiHelper's own record only supplies the learner's original note as context."""
    record = notes.find(note_id)
    entry = Entry(**record["entry"]) if record else None
    current = {"question": text_of(question_html), "answer": text_of(answer_html)}
    original = {"question": entry.question, "answer": entry.answer} if entry else {}
    text = agents.prompt(
        "fix_note",
        language=(entry.language if entry and entry.language else cfg.language),
        rules=config.personal_rules() or "(none yet)",
        original=json.dumps(original, ensure_ascii=False),
        card=json.dumps(current, ensure_ascii=False),
        feedback=feedback,
    )
    reply = agents.extract_json(agents.ask(cfg.agent, text))
    base = record["card"] if record else {}
    card = Card.parse({**base, **reply, "source_id": entry.id if entry else "", "changed": True})
    front = render.question_html(card.question) + _images_in(question_html)
    back = render.to_html(card.answer) + _images_in(answer_html)
    if entry:
        notes.record(note_id, entry, card)
    learning.log(
        {
            "kind": "fix",
            "note_id": note_id,
            "feedback": feedback,
            "before": current,
            "after": {"question": card.question, "answer": card.answer},
        }
    )
    reply = {"front": front, "back": back, "add_tags": [FIXED_TAG], "bloom": card.bloom}
    job = jobs.job_for_note(tags or [])
    if job:
        before = _before_job(note_id, job["id"])
        new_rule = jobs.refine(cfg, job, before or current, current, feedback)
        if new_rule:
            reply["rule_updated"] = new_rule
    return reply


def _before_job(note_id: int, job_id: str) -> dict | None:
    path = config.data_dir() / "backups.jsonl"
    if not path.exists():
        return None
    for line in path.read_text().splitlines():
        item = json.loads(line) if line.strip() else {}
        if item.get("note_id") == note_id and item.get("job") == job_id:
            values = list(item["fields"].values())
            return {"question": text_of(values[0]), "answer": text_of(values[1])}
    return None


def optimize(cfg: Config, note_id: int, question_html: str, answer_html: str, deck: str) -> Entry:
    """Turn an existing Anki card into an inbox entry so Preview can offer optimized versions of it."""
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


def report(request: dict) -> bool:
    """Record the edits and deletions the add-on saw ({"events": [...]}). Returns whether it is time to look for patterns."""
    with _writes_lock():
        writes = _recent_writes()
    now = datetime.now().timestamp()
    for event in request.get("events") or [request]:
        written = writes.get(str(event.get("note_id")))
        if event.get("kind") == "edit" and written and now - written < RECENT_WRITE_SECONDS:
            continue
        learning.log(event)
    return learning.due()


def _rewritable(anki, info: dict) -> bool:
    """Same rule as the add-on: exactly two fields and not a cloze (or image occlusion) note type."""
    if len(info.get("fields") or {}) != 2:
        return False
    [model] = anki.invoke("findModelsByName", modelNames=[info["modelName"]])
    return model.get("type") != CLOZE


def fix_flagged(cfg: Config, anki) -> tuple[int, list[str]]:
    """Rewrite the cards the learner flagged in Anki, one at a time. Returns (fixed count, errors).

    Each flag leaves the list as soon as it is handled, so a batch that dies midway loses nothing;
    flags that fail for a reason a retry could fix stay for the next batch."""
    fixed, errors = 0, []
    for item in list_flagged():
        note_id = item["note_id"]
        try:
            [info] = anki.notes_info([note_id])
            if not info:
                errors.append(f"note {note_id} was deleted; flag dropped")
                unflag(item)
                continue
            if not _rewritable(anki, info):
                errors.append(f"note {note_id} is not a two-field question/answer card; flag dropped")
                unflag(item)
                continue
            (q_name, q), (a_name, a) = sorted(info["fields"].items(), key=lambda kv: kv[1]["order"])
            result = rewrite(cfg, note_id, q["value"], a["value"], item["feedback"], info.get("tags"))
            note_written(note_id)
            anki.update_fields(note_id, {q_name: result["front"], a_name: result["back"]})
            anki.add_tags([note_id], result["add_tags"])
            _clear_red_flag(anki, note_id)
            unflag(item)
            fixed += 1
        except Exception as error:  # one bad flag must not stop the others; it stays flagged
            errors.append(f"note {note_id}: {error}")
    return fixed, errors


def _clear_red_flag(anki, note_id: int) -> None:
    try:
        for card_id in anki.invoke("findCards", query=f"nid:{note_id} flag:1"):
            anki.invoke("setSpecificValueOfCard", card=card_id, keys=["flags"], newValues=[0])
    except Exception:  # the flag is only a visual hint
        pass


def _flagged_path():
    return config.data_dir() / "flagged.jsonl"


def _flags_lock() -> FileLock:
    return FileLock(str(_flagged_path()) + ".lock")


def flag(note_id: int, feedback: str) -> None:
    item = {"note_id": note_id, "feedback": feedback, "time": datetime.now().isoformat(timespec="seconds")}
    with _flags_lock(), _flagged_path().open("a") as f:
        f.write(json.dumps(item) + "\n")
    learning.log({"kind": "flag", "note_id": note_id, "feedback": feedback})


def list_flagged() -> list[dict]:
    with _flags_lock():
        path = _flagged_path()
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def has_flagged() -> bool:
    return bool(list_flagged())


def unflag(item: dict) -> None:
    with _flags_lock():
        path = _flagged_path()
        keep = [line for line in path.read_text().splitlines() if line.strip() and json.loads(line) != item]
        path.write_text("".join(line + "\n" for line in keep))


def unflag_note(note_id: int) -> None:
    """The immediate fix worked, so the next batch has nothing left to do for this note."""
    for item in list_flagged():
        if item["note_id"] == note_id:
            unflag(item)


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
