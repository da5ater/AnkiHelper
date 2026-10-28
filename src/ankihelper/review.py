"""Preview an inbox entry's cards, redo them with feedback, and turn feedback into lasting rules."""

import json
import re
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from . import agents, batch, config
from .config import Config
from .inbox import Entry

PROJECT_DIR = Path(__file__).resolve().parents[2]
REPO = "da5ater/AnkiHelper"


PENDING, ACCEPTED, REMOVED = "pending", "accepted", "removed"


@dataclass
class Version:
    style: str
    why: str
    cards: list[batch.Card]


@dataclass
class Slot:
    """One card on the review canvas, with the learner's verdict and any alternative versions asked for."""

    card: batch.Card
    status: str = PENDING
    versions: list[Version] = field(default_factory=list)


@dataclass
class Review:
    entry: Entry
    slots: list[Slot] = field(default_factory=list)
    feedback: list[str] = field(default_factory=list)
    """Everything the learner asked for, in order; the raw material for a personal rule."""
    history: list[list[dict]] = field(default_factory=list)
    """The cards as they were before each change."""

    @property
    def cards(self) -> list[batch.Card]:
        return [slot.card for slot in self.slots]

    def kept(self) -> list[batch.Card]:
        return [slot.card for slot in self.slots if slot.status != REMOVED]

    def _record(self, feedback: str) -> None:
        self.history.append([asdict(c) for c in self.cards])
        self.feedback.append(feedback)


def _own(review: Review, cards: list[batch.Card]) -> list[batch.Card]:
    for card in cards:
        card.source_id = review.entry.id
    return cards


def _retag(review: Review) -> None:
    tag = f"seed-{review.entry.id}"
    for card in review.cards:
        if len(review.slots) > 1 and tag not in card.tags:
            card.tags.append(tag)


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
        rules=config.personal_rules() or "(none yet)",
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
    review.slots[index : index + 1] = [Slot(card) for card in cards]
    _retag(review)
    return cards


def versions(cfg: Config, review: Review, index: int) -> list[Version]:
    """Alternative ways to ask one card, each built on a different prompt-writing strategy."""
    slot = review.slots[index]
    text = agents.prompt(
        "versions",
        language=review.entry.language or cfg.language,
        rules=config.personal_rules() or "(none yet)",
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
        cards = _own(review, [batch.Card.parse({**c, "source_id": review.entry.id}) for c in raw["cards"][:3]])
        if cards:
            found.append(Version(str(raw.get("style", "Alternative")), str(raw.get("why", "")), cards))
    if not found:
        raise agents.AgentError("The agent's versions had no usable cards")
    slot.versions = found
    return found


def use_version(review: Review, index: int, version: Version, add: bool) -> None:
    """Swap a card for one of its versions, or add the version's cards right after it."""
    slot = review.slots[index]
    review._record(f"card {index + 1} ({slot.card.question}): picked the {version.style} version" + (" in addition" if add else ""))
    slot.versions = []
    new = [Slot(card) for card in version.cards]
    if add:
        review.slots[index + 1 : index + 1] = new
    else:
        review.slots[index : index + 1] = new
    del review.slots[batch.MAX_CARDS_PER_ENTRY + 4 :]
    _retag(review)


def suggest_rule(cfg: Config, review: Review) -> str | None:
    history = "\n\n".join(
        f"Cards before change {n}:\n{json.dumps(cards, ensure_ascii=False)}\nThen the learner said: {said}"
        for n, (cards, said) in enumerate(zip(review.history, review.feedback), start=1)
    )
    history += "\n\nCards now:\n" + json.dumps([asdict(c) for c in review.kept()], ensure_ascii=False)
    reply = agents.ask(cfg.agent, agents.prompt("rule", entry=_entry_json(review.entry), history=history), timeout=300).strip()
    rule = reply.splitlines()[-1].strip().strip('"') if reply else ""
    return None if not rule or rule.upper() == "NONE" else rule


def save_rule(rule: str) -> None:
    path = config.rules_path()
    existing = path.read_text().rstrip() + "\n" if path.exists() and path.read_text().strip() else ""
    path.write_text(existing + f"- {rule.strip()}\n")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "rule"


def pr_command(cfg: Config, rule: str, push: bool = True) -> tuple[list[str], Path]:
    """Make a fresh worktree from origin/main and return the agent command that edits, tests and opens the PR there."""
    if not (PROJECT_DIR / ".git").exists():
        raise agents.AgentError(f"Proposing a PR needs the AnkiHelper git checkout; {PROJECT_DIR} is not one")
    branch = f"rule/{_slug(rule)}-{datetime.now():%m%d%H%M}"
    worktree = config.data_dir() / "worktrees" / branch.replace("/", "-")
    subprocess.run(["git", "-C", str(PROJECT_DIR), "fetch", "-q", "origin", "main"], check=True, timeout=60)
    subprocess.run(
        ["git", "-C", str(PROJECT_DIR), "worktree", "add", "-q", "-b", branch, str(worktree), "origin/main"],
        check=True,
        timeout=60,
    )
    push_step = (
        f"Push the branch with `git push -u origin {branch}` and open a pull request against {REPO} main with "
        "`gh pr create --fill`, adding a short body that quotes the rule and says why it makes cards easier to remember."
        if push
        else "Do not push and do not open a pull request; this is a dry run."
    )
    last_line = "the pull request URL" if push else "the commit hash"
    text = agents.prompt("pr", branch=branch, rule=rule, push_step=push_step, last_line=last_line)
    return agents.get(cfg.agent).fix(text), worktree


def github_env(cfg: Config) -> dict[str, str]:
    """GH_TOKEN for the configured account, so gh and git push act as it without changing the active gh login."""
    done = subprocess.run(
        ["gh", "auth", "token", "-h", "github.com", "-u", cfg.github_account], capture_output=True, text=True, timeout=15
    )
    token = done.stdout.strip()
    if done.returncode != 0 or not token:
        raise agents.AgentError(
            f"gh has no login for {cfg.github_account}; run `gh auth login` and add that account first"
        )
    return {"GH_TOKEN": token}


def remove_worktree(worktree: Path) -> None:
    subprocess.run(["git", "-C", str(PROJECT_DIR), "worktree", "remove", "--force", str(worktree)], timeout=60)
