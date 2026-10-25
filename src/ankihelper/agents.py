import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from importlib import resources
from typing import Callable


class AgentError(Exception):
    pass


@dataclass(frozen=True)
class Agent:
    name: str
    binary: str
    text: Callable[[str], list[str]]
    """Command that answers a prompt with text and no tools that change anything."""
    fix: Callable[[str], list[str]]
    """Command that may run shell commands without asking (setup fixes)."""


AGENTS: dict[str, Agent] = {
    a.name: a
    for a in [
        Agent(
            "claude",
            "claude",
            text=lambda p: ["claude", "-p", p, "--tools", ""],
            fix=lambda p: ["claude", "-p", "--dangerously-skip-permissions", p],
        ),
        Agent(
            "codex",
            "codex",
            text=lambda p: ["codex", "exec", "--skip-git-repo-check", "--sandbox", "read-only", p],
            fix=lambda p: ["codex", "exec", "--skip-git-repo-check", "--dangerously-bypass-approvals-and-sandbox", p],
        ),
        Agent(
            "gemini",
            "gemini",
            text=lambda p: ["gemini", "-p", p],
            fix=lambda p: ["gemini", "--yolo", "-p", p],
        ),
        Agent(
            "opencode",
            "opencode",
            text=lambda p: ["opencode", "run", p],
            fix=lambda p: ["opencode", "run", p],
        ),
    ]
}


def get(name: str) -> Agent:
    if name not in AGENTS:
        raise AgentError(f"Unknown agent {name!r}; choose one of {', '.join(AGENTS)}")
    return AGENTS[name]


def installed(name: str) -> bool:
    return shutil.which(get(name).binary) is not None


def prompt(name: str, **values: str) -> str:
    text = resources.files("ankihelper.prompts").joinpath(f"{name}.md").read_text()
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    return text


def ask(name: str, prompt_text: str, timeout: float = 600) -> str:
    agent = get(name)
    if not installed(name):
        raise AgentError(f"{agent.binary} is not installed")
    try:
        done = subprocess.run(
            agent.text(prompt_text), capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL
        )
    except subprocess.TimeoutExpired as e:
        raise AgentError(f"{name} did not answer within {timeout:.0f}s") from e
    if done.returncode != 0:
        raise AgentError(f"{name} exited {done.returncode}: {(done.stderr or done.stdout).strip()[-800:]}")
    return done.stdout


def extract_json(output: str) -> dict:
    """Pull the JSON object out of an agent reply that may wrap it in prose or a code fence."""
    candidates = [output.strip()]
    candidates += re.findall(r"```(?:json)?\s*\n(.*?)\n```", output, re.S)
    start, end = output.find("{"), output.rfind("}")
    if start != -1 and end > start:
        candidates.append(output[start : end + 1])
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    raise AgentError(f"Agent reply had no JSON object: {output.strip()[:300]!r}")


def ask_json(name: str, prompt_text: str, attempts: int = 2) -> dict:
    last: AgentError | None = None
    for _ in range(attempts):
        try:
            return extract_json(ask(name, prompt_text))
        except AgentError as e:
            last = e
    assert last is not None
    raise last
