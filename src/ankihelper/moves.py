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

from . import agents, config, learning, screenshots
from .config import Config

CHANGE, ADD = "change", "add"
EXAMPLES_KEPT = 3
NUDGE_EVERY = timedelta(days=1)
NUDGE_MIN_CONVERSATIONS = 3

ANSWER_STYLE = (
    "Shape every answer so the learner remembers the most important thing and could say it in an interview: "
    "lead with the main point, and when the answer has more than one point, write \"- \" bullets that each start "
    "with their key term in **bold**, followed by a short plain explanation, for example "
    "\"- **Stop guessing capacity**: scale with demand instead of provisioning for a guessed peak.\" "
    "Bold only that key term, never whole sentences. A one-fact answer stays one line with its key phrase in **bold**. "
    "Keep code in inline `code` or fenced blocks."
)


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
    web: bool = False
    """The agent may search and read the web (never write or run anything) to ground the result in real sources."""


SCENARIO = (
    "Turn this card into one practice task built from real code and written like a LeetCode problem: one clear "
    "goal, only the context needed to solve it, and examples that pin down the expected behavior, so the learner "
    "focuses on writing the answer. Search the web, GitHub first, for a well-known open-source project that uses "
    "exactly this technique (for Rails: Discourse, GitLab, Mastodon or Forem; for front-end: a real design system "
    "or site), open the actual file, and build the task from it. "
    "The task must make the learner use the technique the way the real code does. When the card compares several "
    "things (find, find_by and where), the task needs every one of them. Never make the TODO a one-word fill-in "
    "such as writing `.all` or `.find_each`: the learner writes the working code the real file has, for example "
    "loading records in batches and updating each one. "
    "The front must hold everything needed to write the answer, nothing the learner has to guess. In this order, "
    "with a blank line between parts: "
    "(1) one or two sentences naming the project, the feature and what is needed, with file, class and method "
    "names in inline code; "
    "(2) the requirements as \"- \" bullets, one behavior each, with LeetCode-style examples using →, such as "
    "`GET /api/v1/accounts/999` → `404`; "
    "(3) the real surrounding code in ONE fenced code block, trimmed but with the project's real names, the part to "
    "write replaced by `# TODO:` comments that say what goes there; "
    "(4) keep the project's own scopes, helpers and concerns that the real code uses (such as "
    "`without_unapproved`); never strip them out to make the task simpler. Show each one, and any column or "
    "association the learner cannot know, in a \"> [!info] Already in the project\" callout: its real definition "
    "in a fenced code block and one plain line on what it does; "
    "(5) one instruction, such as \"Write the code that replaces the TODOs.\" "
    "The back: the code that fills the TODOs in one fenced code block; then one bold-signaled bullet per technique "
    "on why it is the right one here and what it returns or raises, in inline code with → "
    "(`find` → `ActiveRecord::RecordNotFound` → `404`); then the link to the file you read as "
    "`[project: path](url)`. "
    "For a front-end card about CSS or layout, also give the card \"screens\": a \"Now\" page that reproduces "
    "the broken or current look and a \"Target\" page with the look to reach, each a small self-contained HTML "
    "page with its CSS inline. The front shows the current CSS in a code block and asks what to change to reach "
    "the target; the back has the changed CSS. "
    "If you cannot find a real use, base the task on typical production code, say so in your reply, and leave out "
    "the link."
)

LEETCODE = (
    "Find one real problem from LeetCode, Codeforces or NeetCode where the card's technique or code has a natural, "
    "useful role in a correct solution in the card's language. It need not be required by the best solution or "
    "named in the problem statement. For language API cards, look for the underlying operation (such as case "
    "conversion or capitalization checks), then use the API meaningfully in the solution. For cards comparing "
    "return values or exceptions, explain how that distinction affects the implementation, including an input "
    "that exposes the pitfall; do not claim the original problem asks about that language-specific behavior. "
    "Search the web: the sites themselves and well-known GitHub lists of frequently asked "
    "interview problems (Blind 75, NeetCode 150, LeetCode Top Interview 150, company-tagged lists). Prefer a "
    "well-known, frequently asked problem, and open it to read exactly what it asks. "
    "Write one new card laid out the way LeetCode shows a problem, so the learner only has to write the function. "
    "The front, with a blank line between parts: the problem's name and difficulty as a link, "
    "`[LeetCode 347: Top K Frequent Elements](url) · Medium`; the problem statement, faithful to the original; "
    "Example 1 and Example 2 in one fenced code block as Input / Output / Explanation lines; the constraints as "
    "\"- \" bullets; the starter function signature in a fenced code block in the card's language when the "
    "problem allows it; and one line asking to solve it with the card's technique, named. "
    "The back: the solution in a fenced code block, one bold-signaled bullet on where the technique does the "
    "work, and one on time and space complexity in inline code (`O(n log k)` time, `O(n)` space). "
    "Keep the original problem's requirements and examples distinct from any added practice requirement or "
    "language-specific pitfall. Do not force an unrelated technique into a solution or invent a catalog problem. "
    "Only return no new cards after searching for both the specific technique and its underlying operation and "
    "finding no meaningful fit, for example a framework-only database API such as Rails' find_each. In that case, "
    "say you did not find a suitable match, briefly explain why the candidates do not exercise the card, and "
    "suggest 🎬 Make it a scenario. Never claim the entire catalog has no match based on a limited search."
)

RETIRED = {"write"}
"""Built-in moves that were removed; the learner's saved copy is dropped unless they made it their own."""


BUILTIN = [
    Move("word", "✍", "Word it better", CHANGE, "Rewrite the question and the answer so they are clear, precise and short. Keep exactly the same meaning, facts and examples; only fix wording, grammar and code formatting.", builtin=True),
    Move("simple", "🗣", "Say it simply", CHANGE, "Rewrite the answer in plain, everyday words, the way one person explains it to another: short sentences, no jargon, and any technical term the learner needs explained in a few words the first time. Keep the question, every fact, code and example exactly as they are; the answer should not get longer than it needs to be.", builtin=True),
    Move("scenario", "🎬", "Make it a scenario", ADD, SCENARIO, builtin=True, web=True),
    Move("leetcode", "🧩", "LeetCode it", ADD, LEETCODE, builtin=True, web=True),
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
    saved = [Move(**raw) for raw in json.loads(path.read_text(encoding="utf-8"))]
    shipped = {m.id: m for m in BUILTIN}
    current = []
    for move in saved:
        if move.builtin and move.id in RETIRED and not move.history:
            continue
        if move.id in shipped:
            fresh = shipped[move.id]
            move.web = fresh.web
            if not move.history:
                move.icon, move.name, move.mode, move.instruction = fresh.icon, fresh.name, fresh.mode, fresh.instruction
        current.append(move)
    known = {m.id for m in current}
    return current + [Move(**asdict(m)) for m in BUILTIN if m.id not in known]


def _save(moves: list[Move]) -> None:
    tmp = _path().with_suffix(".tmp")
    tmp.write_text(json.dumps([asdict(m) for m in moves], indent=2, ensure_ascii=False), encoding="utf-8")
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


def run(
    cfg: Config, move_id: str, card: dict, original: dict, messages: list[dict], images: list[str], language: str, made_from: dict | None = None
) -> dict:
    """Do the move on one card. Returns {"reply", and "card" (CHANGE) or "new_cards" (ADD)}."""
    move = get(move_id)
    text = agents.prompt(
        "move_run",
        move_name=move.name,
        instruction=move.instruction,
        mode="Rewrite the card itself and return it in \"card\"." if move.mode == CHANGE else "Leave the card alone and return new cards in \"new_cards\" (at most 4).",
        sources="You may search and read the web for this move. Link only pages you actually opened during this task." if move.web else "Work from the card and what you know; you cannot browse.",
        examples="\n".join(json.dumps(e, ensure_ascii=False) for e in move.examples) or "(none yet)",
        language=language,
        answer_style=ANSWER_STYLE,
        original=json.dumps(original, ensure_ascii=False),
        card=json.dumps(card, ensure_ascii=False),
        made_from=json.dumps(made_from, ensure_ascii=False) if made_from else "(none: this is an original card)",
        messages="\n".join(f"{m['role']}: {m['text']}" for m in messages[-20:]) or "(none)",
    )
    reply = agents.extract_json(agents.ask(cfg.agent, text, timeout=900 if move.web else 600, images=images, web=move.web))
    screenshots.attach(reply)
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
