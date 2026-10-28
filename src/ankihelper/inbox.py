import json
import os
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime

from filelock import FileLock

from . import config


@dataclass
class Entry:
    id: str
    created: str
    question: str
    answer: str
    topic: str
    attempts: int = 0
    error: str | None = None
    cards: list[dict] | None = None
    """Cleaned cards still waiting to be imported, so a retry does not ask the agent again."""
    language: str | None = None
    """Language the cards should be written in; None means the configured default."""
    images: list[dict] | None = None
    """Pasted pictures: {"file": name in config.media_dir(), "field": "question" | "answer", "mode": "show" | "read"}.
    "show" pictures go on the card as visuals; "read" pictures hold the text the agent turns into the card."""

    def images_for(self, field: str, mode: str) -> list[str]:
        return [
            image["file"]
            for image in self.images or []
            if image["field"] == field and image.get("mode", "show") == mode
        ]

    @classmethod
    def new(cls, question: str, answer: str, topic: str) -> "Entry":
        return cls(
            id=uuid.uuid4().hex[:12],
            created=datetime.now().isoformat(timespec="seconds"),
            question=question.strip(),
            answer=answer.strip(),
            topic=topic.strip(),
        )


def _lock() -> FileLock:
    return FileLock(str(config.inbox_path()) + ".lock")


def _read_unlocked() -> list[Entry]:
    path = config.inbox_path()
    if not path.exists():
        return []
    return [Entry(**json.loads(line)) for line in path.read_text().splitlines() if line.strip()]


def append(entry: Entry) -> None:
    with _lock(), config.inbox_path().open("a") as f:
        f.write(json.dumps(asdict(entry)) + "\n")


def read_all() -> list[Entry]:
    with _lock():
        return _read_unlocked()


def remove(entry_id: str) -> None:
    finish({entry_id}, {}, {})


def finish(done_ids: set[str], failures: dict[str, str], leftovers: dict[str, list[dict]]) -> None:
    """Drop imported entries and record errors, keeping anything captured while the batch ran."""
    with _lock():
        kept = []
        for entry in _read_unlocked():
            if entry.id in done_ids:
                continue
            if entry.id in failures:
                entry.attempts += 1
                entry.error = failures[entry.id]
                entry.cards = leftovers.get(entry.id)
            kept.append(entry)
        path = config.inbox_path()
        tmp = path.with_suffix(".tmp")
        with tmp.open("w") as f:
            f.write("".join(json.dumps(asdict(e)) + "\n" for e in kept))
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(path)


def archive(records: list[dict]) -> None:
    path = config.archive_dir() / f"{datetime.now():%Y-%m-%d}.jsonl"
    with path.open("a") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")
