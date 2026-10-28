import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from platformdirs import user_data_dir


def data_dir() -> Path:
    override = os.environ.get("ANKIHELPER_HOME")
    path = Path(override) if override else Path(user_data_dir("ankihelper", appauthor=False))
    path.mkdir(parents=True, exist_ok=True)
    return path


def inbox_path() -> Path:
    return data_dir() / "inbox.jsonl"


def archive_dir() -> Path:
    path = data_dir() / "archive"
    path.mkdir(exist_ok=True)
    return path


def media_dir() -> Path:
    path = data_dir() / "media"
    path.mkdir(exist_ok=True)
    return path


def log_dir() -> Path:
    path = data_dir() / "logs"
    path.mkdir(exist_ok=True)
    return path


@dataclass
class Config:
    agent: str = "claude"
    dictation: str = field(default_factory=lambda: "voxtype" if sys.platform.startswith("linux") else "system")
    anki_url: str = "http://127.0.0.1:8765"
    root_deck: str = "manual"
    note_type: str = "Basic+"
    last_topic: str = ""
    known_topics: list[str] = field(default_factory=list)

    @classmethod
    def load(cls) -> "Config":
        path = data_dir() / "config.json"
        if not path.exists():
            return cls()
        stored = json.loads(path.read_text())
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in stored.items() if k in known})

    def save(self) -> None:
        (data_dir() / "config.json").write_text(json.dumps(asdict(self), indent=2))
