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


@dataclass
class Round:
    cards: list[batch.Card]
    feedback: str = ""


@dataclass
class Review:
    entry: Entry
    rounds: list[Round] = field(default_factory=list)

    @property
    def cards(self) -> list[batch.Card]:
        return self.rounds[-1].cards if self.rounds else []


def generate(cfg: Config, review: Review, feedback: str = "") -> list[batch.Card]:
    """First preview when feedback is empty; otherwise a redo of the latest cards."""
    revisions = None
    if feedback:
        review.rounds[-1].feedback = feedback
        revisions = {review.entry.id: {"previous_cards": [asdict(c) for c in review.cards], "feedback": feedback}}
    cards, skipped = batch.clean(cfg.agent, [review.entry], cfg.language, revisions)
    if review.entry.id in skipped:
        raise agents.AgentError(f"The agent skipped this note: {skipped[review.entry.id]}")
    if not cards.get(review.entry.id):
        raise agents.AgentError("The agent returned no card for this note")
    review.rounds.append(Round(cards[review.entry.id]))
    return review.cards


def suggest_rule(cfg: Config, review: Review) -> str | None:
    history = "\n\n".join(
        f"Round {n}:\n" + json.dumps([asdict(c) for c in r.cards], ensure_ascii=False) + (f"\nFeedback: {r.feedback}" if r.feedback else "")
        for n, r in enumerate(review.rounds, start=1)
    )
    entry = json.dumps({"question": review.entry.question, "answer": review.entry.answer}, ensure_ascii=False)
    reply = agents.ask(cfg.agent, agents.prompt("rule", entry=entry, history=history), timeout=300).strip()
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


def remove_worktree(worktree: Path) -> None:
    subprocess.run(["git", "-C", str(PROJECT_DIR), "worktree", "remove", "--force", str(worktree)], timeout=60)
