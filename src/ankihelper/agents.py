import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from importlib import resources
from typing import Callable


class AgentError(Exception):
    pass


def _add_dirs(images: list[str]) -> list[str]:
    return [arg for folder in sorted({os.path.dirname(i) for i in images}) for arg in ("--add-dir", folder)]


def _include_dirs(images: list[str]) -> list[str]:
    return [arg for folder in sorted({os.path.dirname(i) for i in images}) for arg in ("--include-directories", folder)]


NO_TOOLS_OPENCODE = json.dumps({"permission": {"edit": "deny", "bash": "deny", "webfetch": "deny"}})


@dataclass(frozen=True)
class Agent:
    name: str
    binary: str
    text: Callable[[list[str]], list[str]]
    """Reads the prompt on stdin and answers with text. It may read the given image files, nothing else
    is writable, and it cannot run commands."""
    fix: Callable[[str], list[str]]
    """Command that may run shell commands without asking (setup fixes)."""
    text_env: dict[str, str] = field(default_factory=dict)


AGENTS: dict[str, Agent] = {
    a.name: a
    for a in [
        Agent(
            "claude",
            "claude",
            text=lambda images: ["claude", "-p", "--tools", ""]
            if not images
            else ["claude", "-p", "--tools", "Read", "--allowedTools", "Read", *_add_dirs(images)],
            fix=lambda p: ["claude", "-p", "--dangerously-skip-permissions", p],
        ),
        Agent(
            "codex",
            "codex",
            text=lambda images: [
                "codex",
                "exec",
                *[arg for image in images for arg in ("--image", image)],
                "--skip-git-repo-check",
                "--sandbox",
                "read-only",
                "-",
            ],
            fix=lambda p: ["codex", "exec", "--skip-git-repo-check", "--dangerously-bypass-approvals-and-sandbox", p],
        ),
        Agent(
            "gemini",
            "gemini",
            text=lambda images: ["gemini", "--approval-mode", "default", *_include_dirs(images), "-p", ""],
            fix=lambda p: ["gemini", "--yolo", "-p", p],
        ),
        Agent(
            "opencode",
            "opencode",
            text=lambda images: ["opencode", "run", *[arg for image in images for arg in ("-f", image)]],
            fix=lambda p: ["opencode", "run", p],
            text_env={"OPENCODE_CONFIG_CONTENT": NO_TOOLS_OPENCODE},
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
    pattern = re.compile("|".join(re.escape("{" + key + "}") for key in values))
    return pattern.sub(lambda m: values[m.group(0)[1:-1]], text)


def ask(name: str, prompt_text: str, timeout: float = 600, images: list[str] | None = None) -> str:
    agent = get(name)
    if not installed(name):
        raise AgentError(f"{agent.binary} is not installed")
    try:
        done = subprocess.run(
            agent.text(images or []),
            input=prompt_text,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, **agent.text_env},
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
