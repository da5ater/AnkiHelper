"""Moves: the one-click things the learner keeps doing to a card ("word it better", "make it a scenario").

A move is a named instruction. It either changes the card itself or proposes new cards next to it; the
learner always sees the result and decides. Moves are born from the learner's own conversations, get
better when the learner teaches them a correction, and remember the last results the learner accepted
so the agent stays consistent.
"""

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

from filelock import FileLock

from . import agents, config, learning
from .config import Config

CHANGE, ADD = "change", "add"
EXAMPLES_KEPT = 3
NUDGE_EVERY = timedelta(days=1)
NUDGE_MIN_CONVERSATIONS = 3


@dataclass
class Move:
    id: str
    icon: str
    name: str
    mode: str
    """CHANGE rewrites the card in place; ADD proposes new cards and leaves the card alone."""
    instruction: str
    uses: int = 0
    examples: list[dict] = field(default_factory=list)
    """The last results the learner accepted, shown to the agent as examples of what they want."""
    history: list[dict] = field(default_factory=list)
    """Earlier instructions, newest last, so a change to the move can be undone."""
    builtin: bool = False


BUILTIN = [
    Move("word", "✍", "Word it better", CHANGE, "Rewrite the question and the answer so they are clear, precise and short. Keep exactly the same meaning, facts and examples; only fix wording, grammar and code formatting.", builtin=True),
    Move("scenario", "🎬", "Make it a scenario", ADD, "Write a new card that puts this knowledge in a short, realistic situation from an ordinary app and asks what the learner would use or do. The answer is one short, consistent line.", builtin=True),
    Move("write", "⌨", "Make me write it", ADD, "Write a new card that gives the learner a concrete input or surrounding context and asks them to write the exact code, command or output. The answer is exactly that code or output.", builtin=True),
    Move("split", "✂", "Split this", ADD, "Split this card into separate small cards, one per idea or list item, each with a context cue in its question so it makes sense on its own.", builtin=True),
    Move("versions", "✨", "Versions", ADD, "Write 3 or 4 alternative cards for the same knowledge, each using a different strategy (why, scenario, compare and contrast, reverse, interview) and climbing Bloom's taxonomy. Start each question with the strategy in brackets, for example [Scenario].", builtin=True),
]


def _path():
    return config.data_dir() / "moves.json"


def _suggestions_path():
    return config.data_dir() / "move_suggestions.json"


def _lock() -> FileLock:
    return FileLock(str(config.data_dir() / "moves.lock"))


def _load() -> list[Move]:
    path = _path()
    if not path.exists():
        return [Move(**asdict(m)) for m in BUILTIN]
    return [Move(**raw) for raw in json.loads(path.read_text())]


def _save(moves: list[Move]) -> None:
    tmp = _path().with_suffix(".tmp")
    tmp.write_text(json.dumps([asdict(m) for m in moves], indent=2, ensure_ascii=False))
    tmp.replace(_path())


def _change(move_id: str, edit) -> Move:
    with _lock():
        moves = _load()
        for move in moves:
            if move.id == move_id:
                edit(move)
                _save(moves)
                return move
    raise KeyError(f"no move {move_id!r}")


def ordered() -> list[Move]:
    """Most used first; ties keep their original order."""
    moves = _load()
    return sorted(moves, key=lambda m: -m.uses)


def get(move_id: str) -> Move:
    for move in _load():
        if move.id == move_id:
            return move
    raise KeyError(f"no move {move_id!r}")


def _slug(name: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:30] or "move"
    slug, n = base, 2
    while slug in taken:
        slug, n = f"{base}-{n}", n + 1
    return slug


def create(name: str, icon: str, mode: str, instruction: str) -> Move:
    with _lock():
        moves = _load()
        move = Move(_slug(name, {m.id for m in moves}), icon.strip() or "★", name.strip(), mode if mode in (CHANGE, ADD) else ADD, instruction.strip())
        _save(moves + [move])
        return move


def delete(move_id: str) -> None:
    with _lock():
        _save([m for m in _load() if m.id != move_id or m.builtin])


def update_instruction(move_id: str, instruction: str) -> Move:
    def edit(move: Move) -> None:
        if instruction.strip() and instruction.strip() != move.instruction:
            move.history.append({"instruction": move.instruction, "time": datetime.now().isoformat(timespec="seconds")})
            move.instruction = instruction.strip()

    return _change(move_id, edit)


def undo(move_id: str) -> Move:
    def edit(move: Move) -> None:
        if move.history:
            move.instruction = move.history.pop()["instruction"]

    return _change(move_id, edit)


def record_example(move_id: str, before: dict, result: dict) -> None:
    def edit(move: Move) -> None:
        move.examples = (move.examples + [{"before": before, "result": result}])[-EXAMPLES_KEPT:]

    _change(move_id, edit)


def run(cfg: Config, move_id: str, card: dict, original: dict, messages: list[dict], images: list[str], language: str) -> dict:
    """Do the move on one card. Returns {"reply", and "card" (CHANGE) or "new_cards" (ADD)}."""
    move = get(move_id)
    text = agents.prompt(
        "move_run",
        move_name=move.name,
        instruction=move.instruction,
        mode="Rewrite the card itself and return it in \"card\"." if move.mode == CHANGE else "Leave the card alone and return new cards in \"new_cards\" (at most 4).",
        examples="\n".join(json.dumps(e, ensure_ascii=False) for e in move.examples) or "(none yet)",
        language=language,
        original=json.dumps(original, ensure_ascii=False),
        card=json.dumps(card, ensure_ascii=False),
        messages="\n".join(f"{m['role']}: {m['text']}" for m in messages[-20:]) or "(none)",
    )
    reply = agents.extract_json(agents.ask(cfg.agent, text, images=images))
    _change(move_id, lambda m: setattr(m, "uses", m.uses + 1))
    return reply


def draft_from_conversation(cfg: Config, card: dict, messages: list[dict]) -> dict:
    """Read the whole conversation and write the move the learner seems to want: {name, icon, mode, instruction}."""
    text = agents.prompt(
        "move_from_chat",
        card=json.dumps(card, ensure_ascii=False),
        messages="\n".join(f"{m['role']}: {m['text']}" for m in messages[-30:]),
        moves="\n".join(f"- {m.name}: {m.instruction}" for m in _load()),
    )
    reply = agents.extract_json(agents.ask(cfg.agent, text, timeout=300))
    return {
        "name": str(reply.get("name") or "New move").strip(),
        "icon": str(reply.get("icon") or "★").strip()[:2],
        "mode": reply.get("mode") if reply.get("mode") in (CHANGE, ADD) else ADD,
        "instruction": str(reply.get("instruction") or "").strip(),
    }


def teach(cfg: Config, move_id: str, messages: list[dict]) -> str:
    """The learner corrected a move's result; propose the move's instruction with that correction folded in."""
    move = get(move_id)
    text = agents.prompt(
        "move_teach",
        move_name=move.name,
        instruction=move.instruction,
        messages="\n".join(f"{m['role']}: {m['text']}" for m in messages[-30:]),
    )
    return agents.ask(cfg.agent, text, timeout=300).strip().strip('"')


def suggestions() -> list[dict]:
    path = _suggestions_path()
    return json.loads(path.read_text()) if path.exists() else []


def _save_suggestions(items: list[dict]) -> None:
    _suggestions_path().write_text(json.dumps(items, indent=2, ensure_ascii=False))


def _nudge_state_path():
    return config.data_dir() / "nudge.json"


def nudge_due() -> bool:
    path = _nudge_state_path()
    state = json.loads(path.read_text()) if path.exists() else {}
    last = datetime.fromisoformat(state["time"]) if state.get("time") else None
    waiting = [e for e in learning.events_since(state.get("seen", 0)) if e.get("kind") == "conversation"]
    return len(waiting) >= NUDGE_MIN_CONVERSATIONS and (last is None or datetime.now() - last >= NUDGE_EVERY)


def nudge(cfg: Config) -> list[dict]:
    """Read recent conversations and suggest moves for requests the learner keeps making. At most once a day."""
    if not nudge_due():
        return []
    path = _nudge_state_path()
    state = json.loads(path.read_text()) if path.exists() else {}
    events = learning.events_since(state.get("seen", 0))
    conversations = [e for e in events if e.get("kind") == "conversation"]
    text = agents.prompt(
        "move_nudge",
        moves="\n".join(f"- {m.name}: {m.instruction}" for m in _load()),
        conversations="\n\n".join(
            json.dumps({"card_before": c.get("before"), "card_after": c.get("after"), "transcript": c.get("transcript", [])}, ensure_ascii=False)
            for c in conversations[-40:]
        ),
    )
    try:
        reply = agents.extract_json(agents.ask(cfg.agent, text, timeout=300))
    finally:
        path.write_text(json.dumps({"time": datetime.now().isoformat(timespec="seconds"), "seen": state.get("seen", 0) + len(events)}))
    found = []
    for raw in reply.get("moves") or []:
        if isinstance(raw, dict) and str(raw.get("instruction", "")).strip() and str(raw.get("name", "")).strip():
            found.append(
                {
                    "name": str(raw["name"]).strip(),
                    "icon": str(raw.get("icon") or "★").strip()[:2],
                    "mode": raw.get("mode") if raw.get("mode") in (CHANGE, ADD) else ADD,
                    "instruction": str(raw["instruction"]).strip(),
                    "evidence": str(raw.get("evidence", "")).strip(),
                }
            )
    _save_suggestions(suggestions() + found)
    return found


def accept_suggestion(index: int, instruction: str | None = None) -> Move:
    items = suggestions()
    item = items.pop(index)
    _save_suggestions(items)
    return create(item["name"], item["icon"], item["mode"], instruction or item["instruction"])


def dismiss_suggestion(index: int) -> None:
    items = suggestions()
    items.pop(index)
    _save_suggestions(items)
