"""Preview an inbox entry's cards: redo them with feedback, press moves on them, and keep the ones the learner accepts."""

import json
from dataclasses import asdict, dataclass, field, replace

from . import agents, batch, config, moves
from .config import Config
from .inbox import Entry


PENDING, ACCEPTED, REMOVED = "pending", "accepted", "removed"


@dataclass
class Version:
    style: str
    why: str
    cards: list[batch.Card]
    added: bool = False
    """Its cards were already added next to the card, so it cannot be added or swapped in again."""
    move: str = ""
    """The move that produced it, so the learner's pick can teach that move."""


@dataclass
class Slot:
    """One card on the review canvas, with the learner's verdict and any alternative versions asked for."""

    card: batch.Card
    status: str = PENDING
    versions: list[Version] = field(default_factory=list)
    made_by: str = ""
    """The move whose result this card is; accepting it teaches that move an example."""
    before: dict | None = None
    """The card before that move, for the example."""
    teach: tuple[str, str] | None = None
    """(move id, the learner's correction) when they changed a move's result: offer to teach the move."""


@dataclass
class Review:
    entry: Entry
    slots: list[Slot] = field(default_factory=list)
    feedback: list[str] = field(default_factory=list)
    """Everything the learner asked for, in order."""
    history: list[list[dict]] = field(default_factory=list)
    """The cards as they were before each change."""

    @property
    def cards(self) -> list[batch.Card]:
        return [slot.card for slot in self.slots]

    def accepted(self) -> list[batch.Card]:
        """Accepted cards, each carrying the versions it was shown next to so Anki's History can offer them."""
        cards = []
        for slot in self.slots:
            if slot.status == ACCEPTED:
                slot.card.versions = [asdict(v) for v in slot.versions if not v.added]
                cards.append(slot.card)
        return cards

    def teach_moves(self) -> None:
        """Every accepted card that came from a move becomes one of that move's examples."""
        for slot in self.slots:
            if slot.status == ACCEPTED and slot.made_by and slot.before:
                try:
                    moves.record_example(slot.made_by, slot.before, {"question": slot.card.question, "answer": slot.card.answer})
                except KeyError:
                    continue

    def kept(self) -> list[batch.Card]:
        return [slot.card for slot in self.slots if slot.status != REMOVED]

    def _record(self, feedback: str) -> None:
        self.history.append([asdict(c) for c in self.cards])
        self.feedback.append(feedback)


def _own(review: Review, cards: list[batch.Card]) -> list[batch.Card]:
    for card in cards:
        card.source_id = review.entry.id
    return cards


def _entry_json(entry: Entry) -> str:
    return json.dumps(
        {"id": entry.id, "question": entry.question, "answer": entry.answer, "topic": entry.topic}, ensure_ascii=False
    )


def _read_images(entry: Entry) -> list[str]:
    return [str(config.media_dir() / name) for field in ("question", "answer") for name in entry.images_for(field, "read")]


def generate(cfg: Config, review: Review, feedback: str = "") -> list[batch.Card]:
    """First preview when feedback is empty; otherwise redo the whole set from the cards the learner kept."""
    revisions = None
    if feedback:
        revisions = {review.entry.id: {"previous_cards": [asdict(c) for c in review.kept()], "feedback": feedback}}
    cards, skipped = batch.clean(cfg.agent, [review.entry], cfg.language, revisions)
    if review.entry.id in skipped:
        raise agents.AgentError(f"The agent skipped this note: {skipped[review.entry.id]}")
    if not cards.get(review.entry.id):
        raise agents.AgentError("The agent returned no card for this note")
    if feedback:
        review._record(f"all cards: {feedback}")
    review.slots = [Slot(card) for card in cards[review.entry.id]]
    return review.cards


def revise(cfg: Config, review: Review, index: int, feedback: str) -> list[batch.Card]:
    """Rewrite one card from feedback; it may come back as up to 3 cards that take its place."""
    target = review.slots[index].card
    others = [asdict(c) for i, c in enumerate(review.cards) if i != index]
    text = agents.prompt(
        "card",
        language=review.entry.language or cfg.language,
        entry=_entry_json(review.entry),
        card=json.dumps(asdict(target), ensure_ascii=False),
        others=json.dumps(others, ensure_ascii=False),
        feedback=feedback,
    )
    reply = agents.extract_json(agents.ask(cfg.agent, text, images=_read_images(review.entry)))
    raw = reply.get("cards")
    if not isinstance(raw, list) or not raw:
        raise agents.AgentError("The agent returned no rewritten card")
    cards = _own(review, [batch.Card.parse(c) for c in raw[:3]])
    review._record(f"card {index + 1} ({target.question}): {feedback}")
    taught = review.slots[index].made_by
    review.slots[index : index + 1] = [Slot(card, teach=(taught, feedback) if taught else None) for card in cards]
    return cards


def versions(cfg: Config, review: Review, index: int) -> list[Version]:
    """Alternative ways to ask one card, each built on a different prompt-writing strategy."""
    slot = review.slots[index]
    text = agents.prompt(
        "versions",
        language=review.entry.language or cfg.language,
        entry=_entry_json(review.entry),
        cards=json.dumps([asdict(slot.card)], ensure_ascii=False),
        others=json.dumps([asdict(c) for i, c in enumerate(review.cards) if i != index], ensure_ascii=False),
    )
    reply = agents.extract_json(agents.ask(cfg.agent, text, images=_read_images(review.entry)))
    raw_versions = reply.get("versions")
    if not isinstance(raw_versions, list) or not raw_versions:
        raise agents.AgentError("The agent returned no versions")
    found = []
    for raw in raw_versions:
        if not isinstance(raw, dict) or not isinstance(raw.get("cards"), list):
            continue
        style = str(raw.get("style", "Alternative"))
        cards = _own(review, [batch.Card.parse({**c, "group": style}) for c in raw["cards"][:3]])
        if cards:
            found.append(Version(style, str(raw.get("why", "")), cards))
    if not found:
        raise agents.AgentError("The agent's versions had no usable cards")
    slot.versions = found
    return found


def use_version(review: Review, index: int, version: Version, add: bool) -> None:
    """Swap a card for one of its versions, or add the version's cards right after it.

    The other versions stay attached so the learner can keep comparing, and a swapped-out card
    becomes an "Original" version so the swap can be undone."""
    slot = review.slots[index]
    review._record(f"card {index + 1} ({slot.card.question}): picked the {version.style} version" + (" in addition" if add else ""))
    before = {"question": slot.card.question, "answer": slot.card.answer}
    if add:
        version.added = True
        review.slots[index + 1 : index + 1] = [Slot(card, made_by=version.move, before=before) for card in version.cards]
    else:
        others = [v for v in slot.versions if v is not version]
        original = Version("Original", "The card you had before this swap.", [replace(slot.card, versions=[])])
        new = [Slot(card, made_by=version.move, before=before) for card in version.cards]
        new[0].versions = [original, *others]
        review.slots[index : index + 1] = new


def apply_move(cfg: Config, review: Review, index: int, move_id: str) -> None:
    """Press a move on one card of the canvas. A changing move swaps the card (the old one stays as
    "Original"); an adding move hangs its new cards under the card for the learner to pick."""
    if move_id == "versions":
        versions(cfg, review, index)
        for version in review.slots[index].versions:
            version.move = move_id
        moves._change(move_id, lambda m: setattr(m, "uses", m.uses + 1))
        return
    slot = review.slots[index]
    move = moves.get(move_id)
    before = {"question": slot.card.question, "answer": slot.card.answer}
    entry = review.entry
    reply = moves.run(
        cfg,
        move_id,
        before,
        {"question": entry.question, "answer": entry.answer},
        [],
        _read_images(entry),
        entry.language or cfg.language,
    )
    review._record(f"card {index + 1} ({slot.card.question}): used the {move.name} move")
    raw_card = reply.get("card")
    if move.mode == moves.CHANGE and isinstance(raw_card, dict) and raw_card.get("question") and raw_card.get("answer"):
        card = batch.Card.parse({**asdict(slot.card), **raw_card, "versions": [], "changed": True})
        original = Version("Original", "The card before this move.", [replace(slot.card, versions=[])])
        review.slots[index] = Slot(card, versions=[original, *slot.versions], made_by=move_id, before=before)
        return
    new = [
        batch.Card.parse({**raw, "source_id": entry.id, "changed": True, "group": move_id})
        for raw in (reply.get("new_cards") or [])[:4]
        if isinstance(raw, dict) and raw.get("question") and raw.get("answer")
    ]
    if not new:
        raise agents.AgentError(f"The {move.name} move returned nothing usable for this card")
    slot.versions = [Version(f"{move.icon} {move.name}", str(reply.get("reply") or ""), [card], move=move_id) for card in new] + slot.versions


def teach_move(cfg: Config, slot: Slot) -> tuple[str, str]:
    """Propose the move's instruction with the learner's correction folded in: (old, new)."""
    move_id, feedback = slot.teach
    return moves.get(move_id).instruction, moves.teach(cfg, move_id, [{"role": "learner", "text": feedback}])
