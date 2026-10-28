import json
import re
from dataclasses import asdict, dataclass, field

from filelock import FileLock, Timeout

from . import agents, config, inbox, notes, render
from .anki import AnkiConnect, AnkiError, AnkiUnreachable, DuplicateNote, SetupProblem
from .config import Config
from .inbox import Entry

REPAIR_ATTEMPTS = 2
CLEAN_ATTEMPTS = 2
ENTRIES_PER_AGENT_CALL = 20
MAX_CARDS_PER_ENTRY = 6
"""Cap on a note's cards outside the atomic group; a list's atomic split is capped separately."""
MAX_ATOMIC_CARDS = 15
GROUPS = ("main", "atomic", "optimized")
SOURCE_TAG = "manual_voice"


BLOOM_LEVELS = ("remember", "understand", "apply", "analyze", "evaluate", "create")


@dataclass
class Card:
    source_id: str
    question: str
    answer: str
    tags: list[str]
    changed: bool
    bloom: str = ""
    """Bloom's taxonomy level the card works at: one of BLOOM_LEVELS, or "" when unknown."""
    group: str = "main"
    """main: the learner's own question. atomic: a list split into one card per item plus one for the whole
    list. optimized: extra higher-level cards. Anything else: the strategy of a version the learner picked."""
    versions: list[dict] = field(default_factory=list)
    """Alternatives offered in Preview ({"style", "why", "cards"}), kept so History in Anki can switch to them."""

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
        bloom = str(raw.get("bloom") or "").strip().lower()
        group = re.sub(r"[^a-z0-9-]+", "-", str(raw.get("group") or "main").strip().lower()).strip("-") or "main"
        versions = raw.get("versions") if isinstance(raw.get("versions"), list) else []
        return cls(
            str(raw.get("source_id", "")),
            question,
            answer,
            tags,
            bool(raw.get("changed")),
            bloom if bloom in BLOOM_LEVELS else "",
            group,
            versions,
        )


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
    fixed: int = 0
    fix_errors: list[str] = field(default_factory=list)
    suggestions: int = 0

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
        if self.fixed:
            parts.append(f"{self.fixed} flagged card(s) fixed")
        if self.fix_errors:
            parts.append(f"{len(self.fix_errors)} flagged card(s) could not be fixed")
        if self.suggestions:
            parts.append(f"{self.suggestions} new rule suggestion(s) in Settings")
        text = ", ".join(parts)
        if self.sync_error:
            text += f". Sync failed: {self.sync_error}"
        return text


def deck_for(cfg: Config, topic: str) -> str:
    topic = topic.strip().strip(":")
    return f"{cfg.root_deck}::{topic}" if topic else cfg.root_deck


def capped(cards: list[Card]) -> list[Card]:
    atomic = [c for c in cards if c.group == "atomic"][:MAX_ATOMIC_CARDS]
    others = [c for c in cards if c.group != "atomic"][:MAX_CARDS_PER_ENTRY]
    keep = {id(c) for c in atomic + others}
    return [c for c in cards if id(c) in keep]


def anki_tags(card: Card, entry: Entry) -> list[str]:
    tags = [*card.tags, SOURCE_TAG, f"ah::seed::{entry.id}", f"ah::group::{card.group}"]
    if card.bloom:
        tags.append(f"ah::bloom::{card.bloom}")
    if card.changed:
        tags.append("changed")
    return tags


def _parse_reply(reply: dict, ids: set[str]) -> tuple[dict[str, list[Card]], dict[str, str]]:
    raw_cards, raw_skipped = reply.get("cards") or [], reply.get("skipped") or []
    if not isinstance(raw_cards, list) or not isinstance(raw_skipped, list):
        raise agents.AgentError(f"reply has the wrong shape: {str(reply)[:300]}")
    cards: dict[str, list[Card]] = {}
    for raw in raw_cards:
        card = Card.parse(raw)
        if card.source_id in ids:
            cards.setdefault(card.source_id, []).append(card)
    for source_id, entry_cards in cards.items():
        cards[source_id] = capped(entry_cards)
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


def clean(
    agent: str, entries: list[Entry], language: str, revisions: dict[str, dict] | None = None
) -> tuple[dict[str, list[Card]], dict[str, str]]:
    """revisions maps an entry id to {"previous_cards": [...], "feedback": "..."} when the learner asked for a redo."""
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
                    **({"language": e.language} if e.language else {}),
                    "question_images": len(e.images_for("question", "show")),
                    "answer_images": len(e.images_for("answer", "show")),
                    "question_read_images": read["question"],
                    "answer_read_images": read["answer"],
                    **({"revision": revisions[e.id]} if revisions and e.id in revisions else {}),
                }
            )
        )
    text = agents.prompt(
        "process",
        entries="\n".join(rows),
        language=language,
        rules=config.personal_rules() or "(none yet)",
    )
    for attempt in range(CLEAN_ATTEMPTS):
        try:
            reply = agents.ask(agent, text, images=to_read)
            return _parse_reply(agents.extract_json(reply), {e.id for e in entries})
        except agents.AgentError:
            if attempt == CLEAN_ATTEMPTS - 1:
                raise
    raise AssertionError("unreachable")


def card_html(card: Card, entry: Entry) -> tuple[str, str]:
    front = render.question_html(card.question) + render.images_html(entry.images_for("question", "show"))
    back = (
        render.to_html(card.answer)
        + render.images_html(entry.images_for("answer", "show"))
        + render.source_html(entry.images_for("question", "read") + entry.images_for("answer", "read"))
    )
    return front, back


def _add(anki: AnkiConnect, cfg: Config, deck: str, card: Card, entry: Entry) -> int:
    return anki.add_note(deck, cfg.note_type, *card_html(card, entry), anki_tags(card, entry))


def _store_images(anki: AnkiConnect, entry: Entry) -> None:
    for image in entry.images or []:
        anki.store_media(image["file"], str(config.media_dir() / image["file"]))


def import_card(anki: AnkiConnect, cfg: Config, agent: str, entry: Entry, deck: str, card: Card) -> tuple[str, Card]:
    """Returns ("imported" | "duplicate", final card). Raises AnkiError once repairs are exhausted."""
    for attempt in range(REPAIR_ATTEMPTS + 1):
        try:
            note_id = _add(anki, cfg, deck, card, entry)
            notes.record(note_id, entry, card)
            return "imported", card
        except DuplicateNote:
            return "duplicate", card
        except AnkiError as error:
            if attempt == REPAIR_ATTEMPTS:
                raise
            reply = agents.extract_json(
                agents.ask(agent, agents.prompt("repair", card=json.dumps(asdict(card)), error=str(error)))
            )
            repaired = Card.parse(reply.get("card", reply))
            repaired.group, repaired.versions = card.group, card.versions
            card = repaired
    raise AssertionError("unreachable")


def run(cfg: Config, anki: AnkiConnect, agent: str | None = None, only: set[str] | None = None) -> Summary:
    lock = FileLock(str(config.data_dir() / "batch.lock"))
    try:
        lock.acquire(timeout=0)
    except Timeout:
        raise BatchRunning("A batch is already running") from None
    try:
        return _run(cfg, anki, agent or cfg.agent, only)
    finally:
        lock.release()


def _clean_all(agent: str, language: str, entries: list[Entry], summary: Summary) -> tuple[dict[str, list[Card]], dict[str, str]]:
    cards = {e.id: [Card.parse(c) for c in e.cards] for e in entries if e.cards}
    fresh = [e for e in entries if not e.cards]
    skipped: dict[str, str] = {}
    errors: list[agents.AgentError] = []
    for start in range(0, len(fresh), ENTRIES_PER_AGENT_CALL):
        chunk = fresh[start : start + ENTRIES_PER_AGENT_CALL]
        try:
            chunk_cards, chunk_skipped = clean(agent, chunk, language)
        except agents.AgentError as error:
            errors.append(error)
            summary.failed.update({e.id: str(error) for e in chunk})
            continue
        cards.update(chunk_cards)
        skipped.update(chunk_skipped)
    if errors and not cards and not skipped:
        raise errors[0]
    return cards, skipped


def _run(cfg: Config, anki: AnkiConnect, agent: str, only: set[str] | None = None) -> Summary:
    from . import bridge, learning

    entries = [e for e in inbox.read_all() if only is None or e.id in only]
    summary = Summary()
    has_flags = only is None and bridge.has_flagged()
    if not entries and not has_flags:
        return summary

    anki.ensure_running()
    try:
        fields = anki.field_names(cfg.note_type)
    except AnkiError as error:
        raise SetupProblem(f"Note type {cfg.note_type!r} is missing: {error}") from error
    if fields[:2] != ["Front", "Back"]:
        raise SetupProblem(f"Note type {cfg.note_type!r} must have fields Front, Back (has {fields})")

    cards, skipped = _clean_all(agent, cfg.language, entries, summary)
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
    if has_flags:
        summary.fixed, summary.fix_errors = bridge.fix_flagged(cfg, anki)
    if only is None:
        try:
            summary.suggestions = len(learning.learn(cfg))
        except agents.AgentError:
            pass
    try:
        anki.sync()
    except (AnkiError, AnkiUnreachable) as error:
        summary.sync_error = str(error)
    return summary
