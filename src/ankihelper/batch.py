import json
from dataclasses import asdict, dataclass, field

from . import agents, inbox, render
from .anki import AnkiConnect, AnkiError, AnkiUnreachable, DuplicateNote
from .config import Config
from .inbox import Entry

REPAIR_ATTEMPTS = 2
SOURCE_TAG = "manual_voice"


@dataclass
class Card:
    source_id: str
    question: str
    answer: str
    tags: list[str]
    changed: bool

    @classmethod
    def parse(cls, raw: dict) -> "Card":
        question, answer = raw.get("question"), raw.get("answer")
        if not isinstance(question, str) or not question.strip():
            raise agents.AgentError(f"card without a question: {raw!r}")
        if not isinstance(answer, str):
            raise agents.AgentError(f"card without an answer: {raw!r}")
        tags = [str(t).strip().lower().replace(" ", "-") for t in raw.get("tags") or [] if str(t).strip()]
        return cls(str(raw.get("source_id", "")), question, answer, tags, bool(raw.get("changed")))


@dataclass
class Summary:
    imported: int = 0
    changed: int = 0
    duplicates: int = 0
    skipped: int = 0
    failed: dict[str, str] = field(default_factory=dict)
    sync_error: str | None = None

    def message(self) -> str:
        parts = [f"{self.imported} imported"]
        if self.changed:
            parts.append(f"{self.changed} changed by the agent")
        if self.duplicates:
            parts.append(f"{self.duplicates} already in Anki")
        if self.skipped:
            parts.append(f"{self.skipped} skipped as unusable")
        if self.failed:
            parts.append(f"{len(self.failed)} failed (kept in inbox)")
        text = ", ".join(parts)
        if self.sync_error:
            text += f". Sync failed: {self.sync_error}"
        return text


def deck_for(cfg: Config, topic: str) -> str:
    topic = topic.strip().strip(":")
    return f"{cfg.root_deck}::{topic}" if topic else cfg.root_deck


def clean(agent: str, entries: list[Entry]) -> tuple[dict[str, list[Card]], dict[str, str]]:
    payload = "\n".join(
        json.dumps({"id": e.id, "question": e.question, "answer": e.answer, "topic": e.topic}) for e in entries
    )
    reply = agents.ask_json(agent, agents.prompt("process", entries=payload))
    ids = {e.id for e in entries}
    cards: dict[str, list[Card]] = {}
    for raw in reply.get("cards") or []:
        card = Card.parse(raw)
        if card.source_id in ids:
            cards.setdefault(card.source_id, []).append(card)
    skipped = {
        str(s.get("source_id")): str(s.get("reason", "unusable"))
        for s in reply.get("skipped") or []
        if s.get("source_id") in ids and s.get("source_id") not in cards
    }
    return cards, skipped


def _add(anki: AnkiConnect, cfg: Config, deck: str, card: Card) -> None:
    tags = [*card.tags, SOURCE_TAG, *(["changed"] if card.changed else [])]
    anki.add_note(deck, cfg.note_type, render.question_html(card.question), render.to_html(card.answer), tags)


def import_card(anki: AnkiConnect, cfg: Config, agent: str, deck: str, card: Card) -> tuple[str, Card]:
    """Returns ("imported" | "duplicate", final card). Raises AnkiError once repairs are exhausted."""
    for attempt in range(REPAIR_ATTEMPTS + 1):
        try:
            _add(anki, cfg, deck, card)
            return "imported", card
        except DuplicateNote:
            return "duplicate", card
        except AnkiError as error:
            if attempt == REPAIR_ATTEMPTS:
                raise
            reply = agents.ask_json(agent, agents.prompt("repair", card=json.dumps(asdict(card)), error=str(error)))
            card = Card.parse(reply.get("card", reply))
    raise AssertionError("unreachable")


def run(cfg: Config, anki: AnkiConnect, agent: str | None = None) -> Summary:
    agent = agent or cfg.agent
    entries = inbox.read_all()
    summary = Summary()
    if not entries:
        return summary

    anki.ensure_running()
    fields = anki.field_names(cfg.note_type)
    if fields[:2] != ["Front", "Back"]:
        raise AnkiUnreachable(f"Note type {cfg.note_type!r} must have fields Front, Back (has {fields})")

    cards, skipped = clean(agent, entries)
    done: set[str] = set()
    archived: list[dict] = []
    known_decks = set(anki.deck_names())

    for entry in entries:
        if entry.id in skipped:
            summary.skipped += 1
            done.add(entry.id)
            archived.append({"entry": asdict(entry), "skipped": skipped[entry.id]})
            continue
        if entry.id not in cards:
            summary.failed[entry.id] = "the agent returned no card for this entry"
            continue
        deck = deck_for(cfg, entry.topic)
        if deck not in known_decks:
            anki.create_deck(deck)
            known_decks.add(deck)
        results = []
        try:
            for card in cards[entry.id]:
                outcome, final = import_card(anki, cfg, agent, deck, card)
                results.append({"outcome": outcome, "card": asdict(final)})
        except (AnkiError, agents.AgentError) as error:
            summary.failed[entry.id] = str(error)
            if not results:
                continue
        for result in results:
            if result["outcome"] == "imported":
                summary.imported += 1
                summary.changed += result["card"]["changed"]
            else:
                summary.duplicates += 1
        if entry.id not in summary.failed:
            done.add(entry.id)
        archived.append({"entry": asdict(entry), "deck": deck, "cards": results})

    inbox.finish(done, summary.failed)
    inbox.archive(archived)
    try:
        anki.sync()
    except (AnkiError, AnkiUnreachable) as error:
        summary.sync_error = str(error)
    return summary
