import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Callable

from .platforms import current as platform


class AgentError(Exception):
    pass


def _add_dirs(images: list[str]) -> list[str]:
    return [arg for folder in sorted({os.path.dirname(i) for i in images}) for arg in ("--add-dir", folder)]


def _include_dirs(images: list[str]) -> list[str]:
    return [arg for folder in sorted({os.path.dirname(i) for i in images}) for arg in ("--include-directories", folder)]


def _codex_models() -> list[tuple[str, str]]:
    """The models Codex lists in its own picker, from the catalog it caches after signing in."""
    try:
        catalog = json.loads((Path.home() / ".codex" / "models_cache.json").read_text())
    except (OSError, ValueError):
        return []
    return [(m["slug"], m.get("display_name") or m["slug"]) for m in catalog.get("models", []) if m.get("visibility") == "list" and m.get("slug")]


def _opencode_models() -> list[tuple[str, str]]:
    """Every provider/model OpenCode can use with the providers you set up."""
    try:
        done = subprocess.run(resolved(["opencode", "models"]), capture_output=True, text=True, timeout=30, creationflags=platform.NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [(line, line) for line in done.stdout.split() if "/" in line]


NO_TOOLS_OPENCODE = json.dumps({"permission": {"edit": "deny", "bash": "deny", "webfetch": "deny"}})
WEB_ONLY_OPENCODE = json.dumps({"permission": {"edit": "deny", "bash": "deny", "webfetch": "allow"}})
CLAUDE_WEB = ["WebSearch", "WebFetch"]


def _claude_text(images: list[str], web: bool) -> list[str]:
    tools = (["Read"] if images else []) + (CLAUDE_WEB if web else [])
    if not tools:
        return ["claude", "-p", "--tools", ""]
    return ["claude", "-p", "--tools", ",".join(tools), "--allowedTools", ",".join(tools), *_add_dirs(images)]


@dataclass(frozen=True)
class Agent:
    name: str
    binary: str
    text: Callable[[list[str], bool], list[str]]
    """Reads the prompt on stdin and answers with text. It may read the given image files and, when asked,
    search and read the web; nothing is writable and it cannot run commands."""
    fix: Callable[[str], list[str]]
    """Command that may run shell commands without asking (setup fixes)."""
    text_env: Callable[[bool], dict[str, str]] = lambda web: {}
    model_at: int = 1
    """Where "--model <name>" goes in the command, after any subcommand such as `exec` or `run`."""
    models: Callable[[], list[tuple[str, str]]] = lambda: []
    """The models this agent offers, as (name passed to --model, label), read from the CLI when it can tell us."""

    def with_model(self, command: list[str], model: str) -> list[str]:
        return command[: self.model_at] + ["--model", model] + command[self.model_at :] if model else command


AGENTS: dict[str, Agent] = {
    a.name: a
    for a in [
        Agent(
            "claude",
            "claude",
            text=_claude_text,
            fix=lambda p: ["claude", "-p", "--dangerously-skip-permissions", p],
            models=lambda: [("opus", "Opus"), ("sonnet", "Sonnet"), ("haiku", "Haiku")],
        ),
        Agent(
            "codex",
            "codex",
            text=lambda images, web: [
                "codex",
                "exec",
                *(["--search"] if web else []),
                *[arg for image in images for arg in ("--image", image)],
                "--skip-git-repo-check",
                "--sandbox",
                "read-only",
                "-",
            ],
            fix=lambda p: ["codex", "exec", "--skip-git-repo-check", "--dangerously-bypass-approvals-and-sandbox", p],
            model_at=2,
            models=lambda: _codex_models(),
        ),
        Agent(
            "gemini",
            "gemini",
            text=lambda images, web: ["gemini", "--approval-mode", "default", *_include_dirs(images), "-p", ""],
            fix=lambda p: ["gemini", "--yolo", "-p", p],
            models=lambda: [("auto", "Auto"), ("pro", "Pro"), ("flash", "Flash"), ("flash-lite", "Flash Lite")],
        ),
        Agent(
            "opencode",
            "opencode",
            text=lambda images, web: ["opencode", "run", *[arg for image in images for arg in ("-f", image)]],
            fix=lambda p: ["opencode", "run", p],
            text_env=lambda web: {"OPENCODE_CONFIG_CONTENT": WEB_ONLY_OPENCODE if web else NO_TOOLS_OPENCODE},
            model_at=2,
            models=lambda: _opencode_models(),
        ),
    ]
}


def get(name: str) -> Agent:
    if name not in AGENTS:
        raise AgentError(f"Unknown agent {name!r}; choose one of {', '.join(AGENTS)}")
    return AGENTS[name]


def installed(name: str) -> bool:
    return shutil.which(get(name).binary) is not None


def resolved(command: list[str]) -> list[str]:
    """The command with its program as a full path, which Windows needs to start an npm `.cmd` shim."""
    return [shutil.which(command[0]) or command[0], *command[1:]]


def prompt(name: str, **values: str) -> str:
    text = resources.files("ankihelper.prompts").joinpath(f"{name}.md").read_text()
    pattern = re.compile("|".join(re.escape("{" + key + "}") for key in values))
    return pattern.sub(lambda m: values[m.group(0)[1:-1]], text)


def chosen_model(name: str) -> str:
    """The model picked for this agent in Settings; empty means the CLI's own default."""
    from .config import Config

    return Config.load().models.get(name, "")


def ask(name: str, prompt_text: str, timeout: float = 600, images: list[str] | None = None, web: bool = False) -> str:
    """`web` lets the agent search and read web pages (Gemini always can), still with no shell and no writes."""
    agent = get(name)
    if not installed(name):
        raise AgentError(f"{agent.binary} is not installed")
    try:
        done = subprocess.run(
            resolved(agent.with_model(agent.text(images or [], web), chosen_model(name))),
            input=prompt_text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env={**os.environ, **agent.text_env(web)},
            creationflags=platform.NO_WINDOW,
        )
    except subprocess.TimeoutExpired as e:
        raise AgentError(f"{name} did not answer within {timeout:.0f}s") from e
    if done.returncode != 0:
        tail = [line for line in (done.stderr or done.stdout).splitlines() if line.strip()][-3:]
        raise AgentError(f"{name} exited {done.returncode}: " + " | ".join(tail))
    return done.stdout


def extract_json(output: str) -> dict:
    """Pull the first JSON object out of an agent reply that may wrap it in prose or a code fence."""
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", output):
        try:
            value, _ = decoder.raw_decode(output, match.start())
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    raise AgentError(f"Agent reply had no JSON object: {output.strip()[:300]!r}")
