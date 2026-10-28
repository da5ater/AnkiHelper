"""Which Anki note came from which inbox entry, so the Anki add-on can show its history and versions."""

import json
from dataclasses import asdict

from filelock import FileLock

from . import config


def _path():
    return config.data_dir() / "notes.jsonl"


def record(note_id: int, entry, card) -> None:
    line = {"note_id": note_id, "entry": asdict(entry), "card": asdict(card)}
    line["entry"]["cards"] = None
    with FileLock(str(_path()) + ".lock"), _path().open("a") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")


def _all() -> list[dict]:
    path = _path()
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def find(note_id: int) -> dict | None:
    """The latest record for a note; later records (after a fix) win."""
    found = None
    for line in _all():
        if line["note_id"] == note_id:
            found = line
    return found


def siblings(entry_id: str) -> list[dict]:
    latest: dict[int, dict] = {}
    for line in _all():
        if line["entry"]["id"] == entry_id:
            latest[line["note_id"]] = line
    return list(latest.values())
