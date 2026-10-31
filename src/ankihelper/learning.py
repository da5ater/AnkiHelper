"""What the learner did to cards in Anki: conversations, hand edits and deletions, kept in one log.

History reads it per card, and the moves nudge reads the conversations to spot requests the learner keeps
making.
"""

import json
from datetime import datetime

from filelock import FileLock

from . import config


def _events_path():
    return config.data_dir() / "events.jsonl"


def _lock() -> FileLock:
    return FileLock(str(config.data_dir() / "learning.lock"))


def log(event: dict) -> None:
    event = {**event, "time": datetime.now().isoformat(timespec="seconds")}
    with _lock(), _events_path().open("a") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def _events() -> list[dict]:
    path = _events_path()
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def events_for(note_id: int) -> list[dict]:
    with _lock():
        return [e for e in _events() if e.get("note_id") == note_id]


def events_since(index: int) -> list[dict]:
    with _lock():
        return _events()[index:]
