import json
from dataclasses import asdict, dataclass, field

from filelock import FileLock, Timeout

from . import agents, config, inbox, render
from .anki import AnkiConnect, AnkiError, AnkiUnreachable, DuplicateNote, SetupProblem
from .config import Config
from .inbox import Entry

REPAIR_ATTEMPTS = 2
CLEAN_ATTEMPTS = 2
ENTRIES_PER_AGENT_CALL = 20
SOURCE_TAG = "manual_voice"


@dataclass
class Card:
    source_id: str
    question: str
    answer: str
    tags: list[str]
    changed: bool

    @classmethod
    def parse(cls, raw) -> "Card":
        if not isinstance(raw, dict):
            raise agents.AgentError(f"card is not an object: {raw!r}")
        question, answer = raw.get("question"), raw.get("answer")
        if not isinstance(question, str) or not question.strip():
            raise agents.AgentError(f"card without a question: {raw!r}")
        if not isinstance(answer, str):
            raise agents.AgentError(f"card without an answer: {raw!r}")
        tags = [str(t).strip().lower().replace(" ", "-") for t in raw.get("tags") or [] if str(t).strip()]
        return cls(str(raw.get("source_id", "")), question, answer, tags, bool(raw.get("changed")))


class BatchRunning(Exception):
    pass


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


def _parse_reply(reply: dict, ids: set[str]) -> tuple[dict[str, list[Card]], dict[str, str]]:
    raw_cards, raw_skipped = reply.get("cards") or [], reply.get("skipped") or []
    if not isinstance(raw_cards, list) or not isinstance(raw_skipped, list):
        raise agents.AgentError(f"reply has the wrong shape: {str(reply)[:300]}")
    cards: dict[str, list[Card]] = {}
    for raw in raw_cards:
        card = Card.parse(raw)
        if card.source_id in ids:
            cards.setdefault(card.source_id, []).append(card)
    skipped = {}
    for raw in raw_skipped:
        if not isinstance(raw, dict):
            raise agents.AgentError(f"skipped item is not an object: {raw!r}")
        source_id = str(raw.get("source_id"))
        if source_id in ids and source_id not in cards:
            skipped[source_id] = str(raw.get("reason", "unusable"))
    return cards, skipped


def _media_paths(files: list[str]) -> list[str]:
    return [str(config.media_dir() / name) for name in files]


def clean(agent: str, entries: list[Entry]) -> tuple[dict[str, list[Card]], dict[str, str]]:
    rows = []
    to_read: list[str] = []
    for e in entries:
        read = {field: _media_paths(e.images_for(field, "read")) for field in ("question", "answer")}
        to_read += read["question"] + read["answer"]
        rows.append(
            json.dumps(
                {
                    "id": e.id,
                    "question": e.question,
                    "answer": e.answer,
                    "topic": e.topic,
                    "question_images": len(e.images_for("question", "show")),
                    "answer_images": len(e.images_for("answer", "show")),
                    "question_read_images": read["question"],
                    "answer_read_images": read["answer"],
                }
            )
        )
    text = agents.prompt("process", entries="\n".join(rows))
    for attempt in range(CLEAN_ATTEMPTS):
        try:
            reply = agents.ask(agent, text, images=to_read)
            return _parse_reply(agents.extract_json(reply), {e.id for e in entries})
        except agents.AgentError:
            if attempt == CLEAN_ATTEMPTS - 1:
                raise
    raise AssertionError("unreachable")


def _add(anki: AnkiConnect, cfg: Config, deck: str, card: Card, entry: Entry) -> None:
    tags = [*card.tags, SOURCE_TAG, *(["changed"] if card.changed else [])]
    front = render.question_html(card.question) + render.images_html(entry.images_for("question", "show"))
    back = (
        render.to_html(card.answer)
        + render.images_html(entry.images_for("answer", "show"))
        + render.source_html(entry.images_for("question", "read") + entry.images_for("answer", "read"))
    )
    anki.add_note(deck, cfg.note_type, front, back, tags)


def _store_images(anki: AnkiConnect, entry: Entry) -> None:
    for image in entry.images or []:
        anki.store_media(image["file"], str(config.media_dir() / image["file"]))


def import_card(anki: AnkiConnect, cfg: Config, agent: str, entry: Entry, deck: str, card: Card) -> tuple[str, Card]:
    """Returns ("imported" | "duplicate", final card). Raises AnkiError once repairs are exhausted."""
    for attempt in range(REPAIR_ATTEMPTS + 1):
        try:
            _add(anki, cfg, deck, card, entry)
            return "imported", card
        except DuplicateNote:
            return "duplicate", card
        except AnkiError as error:
            if attempt == REPAIR_ATTEMPTS:
                raise
            reply = agents.extract_json(
                agents.ask(agent, agents.prompt("repair", card=json.dumps(asdict(card)), error=str(error)))
            )
            card = Card.parse(reply.get("card", reply))
    raise AssertionError("unreachable")


def run(cfg: Config, anki: AnkiConnect, agent: str | None = None) -> Summary:
    lock = FileLock(str(config.data_dir() / "batch.lock"))
    try:
        lock.acquire(timeout=0)
    except Timeout:
        raise BatchRunning("A batch is already running") from None
    try:
        return _run(cfg, anki, agent or cfg.agent)
    finally:
        lock.release()


def _clean_all(agent: str, entries: list[Entry], summary: Summary) -> tuple[dict[str, list[Card]], dict[str, str]]:
    cards = {e.id: [Card.parse(c) for c in e.cards] for e in entries if e.cards}
    fresh = [e for e in entries if not e.cards]
    skipped: dict[str, str] = {}
    errors: list[agents.AgentError] = []
    for start in range(0, len(fresh), ENTRIES_PER_AGENT_CALL):
        chunk = fresh[start : start + ENTRIES_PER_AGENT_CALL]
        try:
            chunk_cards, chunk_skipped = clean(agent, chunk)
        except agents.AgentError as error:
            errors.append(error)
            summary.failed.update({e.id: str(error) for e in chunk})
            continue
        cards.update(chunk_cards)
        skipped.update(chunk_skipped)
    if errors and not cards and not skipped:
        raise errors[0]
    return cards, skipped


def _run(cfg: Config, anki: AnkiConnect, agent: str) -> Summary:
    entries = inbox.read_all()
    summary = Summary()
    if not entries:
        return summary

    anki.ensure_running()
    try:
        fields = anki.field_names(cfg.note_type)
    except AnkiError as error:
        raise SetupProblem(f"Note type {cfg.note_type!r} is missing: {error}") from error
    if fields[:2] != ["Front", "Back"]:
        raise SetupProblem(f"Note type {cfg.note_type!r} must have fields Front, Back (has {fields})")

    cards, skipped = _clean_all(agent, entries, summary)
    done: set[str] = set()
    archived: list[dict] = []
    leftovers: dict[str, list[dict]] = {}
    known_decks = set(anki.deck_names())
    stopped: AnkiUnreachable | None = None

    try:
        for entry in entries:
            if entry.id in summary.failed:
                continue
            if entry.id in skipped:
                summary.skipped += 1
                done.add(entry.id)
                archived.append({"entry": asdict(entry), "skipped": skipped[entry.id]})
                continue
            if entry.id not in cards:
                summary.failed[entry.id] = "the agent returned no card for this entry"
                continue
            deck = deck_for(cfg, entry.topic)
            entry_cards = cards[entry.id]
            results = []
            try:
                if deck not in known_decks:
                    anki.create_deck(deck)
                    known_decks.add(deck)
                _store_images(anki, entry)
                for card in entry_cards:
                    outcome, final = import_card(anki, cfg, agent, entry, deck, card)
                    results.append({"outcome": outcome, "card": asdict(final)})
            except (AnkiError, agents.AgentError, AnkiUnreachable) as error:
                summary.failed[entry.id] = str(error)
                leftovers[entry.id] = [asdict(c) for c in entry_cards[len(results) :]]
                if isinstance(error, AnkiUnreachable):
                    stopped = error
            for result in results:
                if result["outcome"] == "imported":
                    summary.imported += 1
                    summary.changed += result["card"]["changed"]
                else:
                    summary.duplicates += 1
            if entry.id not in summary.failed:
                done.add(entry.id)
            if results:
                archived.append({"entry": asdict(entry), "deck": deck, "cards": results})
            if stopped:
                break
    finally:
        inbox.archive(archived)
        inbox.finish(done, summary.failed, leftovers)

    if stopped:
        raise stopped
    try:
        anki.sync()
    except (AnkiError, AnkiUnreachable) as error:
        summary.sync_error = str(error)
    return summary
