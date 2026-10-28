"""Learn the learner's taste from what they do in Anki: edits, deletions and fixes become suggested rules."""

import json
import uuid
from datetime import datetime

from filelock import FileLock, Timeout

from . import agents, config
from .config import Config

LEARN_EVERY = 10
"""Events to collect before the add-on asks for suggestions in the background."""
MIN_EVENTS = 3
"""A pattern needs at least this many events behind it."""
MAX_EVENTS = 150
"""Most recent events sent in one prompt; older pending ones are skipped so a backlog cannot grow forever."""


def _events_path():
    return config.data_dir() / "events.jsonl"


def _state_path():
    return config.data_dir() / "learn.json"


def _suggested_path():
    return config.data_dir() / "suggested_rules.json"


def _lock() -> FileLock:
    return FileLock(str(config.data_dir() / "learning.lock"))


def log(event: dict) -> None:
    event = {**event, "time": datetime.now().isoformat(timespec="seconds")}
    with _lock(), _events_path().open("a") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def _events() -> list[dict]:
    path = _events_path()
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def _seen() -> int:
    path = _state_path()
    return json.loads(path.read_text()).get("seen", 0) if path.exists() else 0


def pending() -> list[dict]:
    with _lock():
        return _events()[_seen() :]


def due() -> bool:
    return len(pending()) >= LEARN_EVERY


def suggestions() -> list[dict]:
    path = _suggested_path()
    return json.loads(path.read_text()) if path.exists() else []


def _save_suggestions(items: list[dict]) -> None:
    _suggested_path().write_text(json.dumps(items, indent=2, ensure_ascii=False))


def _short(text: str, limit: int = 300) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _describe(event: dict) -> dict:
    keep = {k: v for k, v in event.items() if k not in ("before", "after", "question", "answer")}
    for side in ("before", "after"):
        if isinstance(event.get(side), dict):
            keep[side] = {k: _short(str(v)) for k, v in event[side].items()}
    for key in ("question", "answer"):
        if key in event:
            keep[key] = _short(str(event[key]))
    if isinstance(event.get("sample"), list):
        keep["sample"] = [_describe(e) for e in event["sample"]]
    return keep


def learn(cfg: Config) -> list[dict]:
    """Ask the agent for rules that explain the pending events; returns the new suggestions."""
    running = FileLock(str(config.data_dir() / "learn-running.lock"))
    try:
        running.acquire(timeout=0)
    except Timeout:
        return []
    try:
        return _learn(cfg)
    finally:
        running.release()


def _learn(cfg: Config) -> list[dict]:
    with _lock():
        events = _events()
        start = _seen()
    fresh = events[start:][-MAX_EVENTS:]
    if len(fresh) < MIN_EVENTS:
        return []
    text = agents.prompt(
        "learn",
        rules=config.personal_rules() or "(none yet)",
        events="\n".join(json.dumps(_describe(e), ensure_ascii=False) for e in fresh),
    )
    try:
        reply = agents.extract_json(agents.ask(cfg.agent, text, timeout=300))
    finally:
        with _lock():
            _state_path().write_text(json.dumps({"seen": len(events)}))
    found = []
    for raw in reply.get("rules") or []:
        if isinstance(raw, dict) and str(raw.get("rule", "")).strip():
            found.append(
                {"id": uuid.uuid4().hex[:8], "rule": str(raw["rule"]).strip(), "evidence": str(raw.get("evidence", "")).strip()}
            )
    with _lock():
        _save_suggestions(suggestions() + found)
    return found


def accept(suggestion_id: str, rule: str | None = None) -> None:
    from . import review

    items = suggestions()
    for item in items:
        if item["id"] == suggestion_id:
            review.save_rule(rule or item["rule"])
    _save_suggestions([i for i in items if i["id"] != suggestion_id])


def dismiss(suggestion_id: str) -> None:
    _save_suggestions([i for i in suggestions() if i["id"] != suggestion_id])
