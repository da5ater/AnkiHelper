import shutil
from dataclasses import dataclass
from typing import Callable

from . import agents, dictation
from .anki import AnkiConnect, AnkiError, AnkiUnreachable
from .config import Config
from .platforms import current as platform


@dataclass(frozen=True)
class Result:
    ok: bool
    detail: str


@dataclass(frozen=True)
class Check:
    id: str
    title: str
    run: Callable[[Config], Result]
    fix_hint: Callable[[Config], str]


def _anki_installed(cfg: Config) -> Result:
    if platform.anki_installed():
        return Result(True, "Anki is installed")
    return Result(False, "Anki is not installed")


def _ankiconnect(cfg: Config) -> Result:
    anki = AnkiConnect(cfg.anki_url)
    try:
        anki.ensure_running(wait=45)
        return Result(True, f"AnkiConnect v{anki.invoke('version')} at {cfg.anki_url}")
    except AnkiUnreachable as e:
        return Result(False, str(e))


def _root_deck(cfg: Config) -> Result:
    try:
        decks = AnkiConnect(cfg.anki_url).deck_names()
    except (AnkiError, AnkiUnreachable) as e:
        return Result(False, f"Needs AnkiConnect: {e}")
    if cfg.root_deck in decks:
        subdecks = sum(1 for d in decks if d.startswith(cfg.root_deck + "::"))
        return Result(True, f"'{cfg.root_deck}' with {subdecks} subdecks")
    return Result(False, f"Deck '{cfg.root_deck}' does not exist")


def _note_type(cfg: Config) -> Result:
    try:
        fields = AnkiConnect(cfg.anki_url).field_names(cfg.note_type)
    except AnkiUnreachable as e:
        return Result(False, f"Needs AnkiConnect: {e}")
    except AnkiError:
        return Result(False, f"Note type '{cfg.note_type}' does not exist")
    if fields[:2] == ["Front", "Back"]:
        return Result(True, f"'{cfg.note_type}' has Front and Back")
    return Result(False, f"'{cfg.note_type}' has fields {fields}, expected Front, Back")


def _dictation(cfg: Config) -> Result:
    return Result(*dictation.status(cfg.dictation))


def _on_path(cfg: Config) -> Result:
    path = shutil.which("ankihelper")
    if path:
        return Result(True, path)
    return Result(False, "`ankihelper` is not on PATH, so shortcuts cannot run it")


def _agent(cfg: Config) -> Result:
    if not agents.installed(cfg.agent):
        return Result(False, f"{cfg.agent} CLI is not installed")
    try:
        reply = agents.ask(cfg.agent, "Reply with exactly the word READY and nothing else.", timeout=120)
    except agents.AgentError as e:
        return Result(False, f"{cfg.agent} is installed but did not answer: {e}")
    if "READY" in reply.upper():
        return Result(True, f"{cfg.agent} answers")
    return Result(False, f"{cfg.agent} answered unexpectedly: {reply.strip()[:120]!r}")


def _keybinds(cfg: Config) -> Result:
    return Result(*platform.keybind_status())


def _hint(text: str) -> Callable[[Config], str]:
    return lambda cfg: text


CHECKS: list[Check] = [
    Check("anki", "Anki installed", _anki_installed, _hint("Install Anki from https://apps.ankiweb.net (or the distro package).")),
    Check("ankiconnect", "AnkiConnect reachable", _ankiconnect, lambda cfg: f"Install the AnkiConnect add-on (2055492159), make sure it listens on {cfg.anki_url}, and that Anki starts."),
    Check("deck", "Root deck exists", _root_deck, lambda cfg: f"Create the deck '{cfg.root_deck}' through AnkiConnect's createDeck."),
    Check("notetype", "Note type ready", _note_type, lambda cfg: f"Create a note type '{cfg.note_type}' with fields Front and Back and one card template (front {{{{Front}}}}, back {{{{FrontSide}}}}<hr id=answer>{{{{Back}}}}) via AnkiConnect's createModel."),
    Check("dictation", "Dictation available", _dictation, _hint("Install voxtype (https://voxtype.io), run `voxtype setup`, and start its daemon (`systemctl --user enable --now voxtype`). Or pick another dictation method in Settings.")),
    Check("path", "ankihelper on PATH", _on_path, _hint("Install the CLI with `uv tool install --editable <project dir>` so `ankihelper` lands in ~/.local/bin, and make sure that directory is on PATH.")),
    Check("agent", "Agent CLI works", _agent, lambda cfg: f"Make the `{cfg.agent}` CLI installed and logged in so it can answer a non-interactive prompt."),
    Check("keybinds", "Shortcuts installed", _keybinds, lambda cfg: platform.keybind_fix_hint()),
]


def run_all(cfg: Config) -> list[tuple[Check, Result]]:
    results = []
    for check in CHECKS:
        try:
            results.append((check, check.run(cfg)))
        except Exception as e:  # a crashing check is a failed check, not a crashed setup window
            results.append((check, Result(False, f"check crashed: {e}")))
    return results


def fix_command(cfg: Config, failed: list[tuple[Check, Result]], project: str) -> list[str]:
    lines = "\n".join(f"- {c.title}: {r.detail}\n  How to fix: {c.fix_hint(cfg)}" for c, r in failed)
    text = agents.prompt(
        "fix",
        os=platform.NAME,
        failures=lines,
        project=project,
        anki_url=cfg.anki_url,
        root_deck=cfg.root_deck,
        note_type=cfg.note_type,
    )
    return agents.get(cfg.agent).fix(text)

