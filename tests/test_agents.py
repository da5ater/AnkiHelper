import subprocess

from ankihelper import agents
from ankihelper.config import Config


def commands_run(monkeypatch) -> list[list[str]]:
    seen = []

    def run(command, **_):
        seen.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr(agents, "installed", lambda name: True)
    monkeypatch.setattr(subprocess, "run", run)
    return seen


def test_the_model_picked_in_settings_reaches_every_agent(monkeypatch):
    cfg = Config(models={"claude": "sonnet", "codex": "gpt-5", "gemini": "gemini-2.5-flash", "opencode": "anthropic/claude-sonnet-4-5"})
    cfg.save()
    seen = commands_run(monkeypatch)

    for name in agents.AGENTS:
        agents.ask(name, "hi")

    claude, codex, gemini, opencode = seen
    assert claude[:3] == ["claude", "--model", "sonnet"]
    assert codex[:4] == ["codex", "exec", "--model", "gpt-5"] and codex[-1] == "-"
    assert gemini[:3] == ["gemini", "--model", "gemini-2.5-flash"] and gemini[-2:] == ["-p", ""]
    assert opencode[:4] == ["opencode", "run", "--model", "anthropic/claude-sonnet-4-5"]


def test_no_model_picked_leaves_the_agents_own_default(monkeypatch):
    seen = commands_run(monkeypatch)

    agents.ask("claude", "hi")

    assert "--model" not in seen[0]
