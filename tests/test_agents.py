import subprocess

from ankihelper import agents
from ankihelper.config import Config


def commands_run(monkeypatch) -> list[list[str]]:
    seen = []

    def run(command, **_):
        seen.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr(agents, "installed", lambda name: True)
    monkeypatch.setattr(agents.shutil, "which", lambda name: None)
    monkeypatch.setattr(subprocess, "run", run)
    return seen


def test_agents_start_from_their_full_path_so_windows_runs_npm_shims(monkeypatch):
    seen = commands_run(monkeypatch)
    monkeypatch.setattr(agents.shutil, "which", lambda name: rf"C:\npm\{name}.cmd")

    agents.ask("codex", "hi")

    assert seen[0][:2] == [r"C:\npm\codex.cmd", "exec"]


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


def test_each_agent_offers_a_list_of_models(monkeypatch, tmp_path):
    monkeypatch.setattr(agents.Path, "home", lambda: tmp_path)
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex" / "models_cache.json").write_text(
        '{"models": [{"slug": "gpt-a", "display_name": "GPT A", "visibility": "list"}, {"slug": "hidden", "visibility": "hide"}]}'
    )
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="opencode/free\nanthropic/sonnet\n", stderr=""))

    assert [n for n, _ in agents.get("claude").models()] == ["opus", "sonnet", "haiku"]
    assert agents.get("codex").models() == [("gpt-a", "GPT A")]
    assert [n for n, _ in agents.get("opencode").models()] == ["opencode/free", "anthropic/sonnet"]
