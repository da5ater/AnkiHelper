import os
import subprocess
import sys
from pathlib import Path

SYSTEM_DICTATION: str | None = "Windows voice typing: press Win+H in a text field"
NAME = "Windows"
NO_WINDOW = subprocess.CREATE_NO_WINDOW
SHORTCUTS = {"capture": "Ctrl+Alt+A", "batch": "Ctrl+Alt+B"}


def ankihelper_command() -> list[str]:
    """Python itself rather than the ankihelper.exe launcher, which Windows Application Control blocks on
    managed machines. UTF-8 mode because Windows otherwise reads and writes text in the ANSI code page."""
    return [sys.executable, "-X", "utf8", "-m", "ankihelper"]


def _anki_exe() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Anki" / "anki.exe"


def anki_installed() -> bool:
    return _anki_exe().exists()


def launch_anki() -> None:
    subprocess.Popen([str(_anki_exe())], creationflags=subprocess.DETACHED_PROCESS)


def _ps_quote(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def notify(title: str, body: str, offer_setup: bool = False) -> None:
    script = (
        "[reflection.assembly]::loadwithpartialname('System.Windows.Forms') | Out-Null;"
        "$n = New-Object System.Windows.Forms.NotifyIcon; $n.Icon = [System.Drawing.SystemIcons]::Information;"
        f"$n.Visible = $true; $n.ShowBalloonTip(8000, {_ps_quote(title)}, {_ps_quote(body)}, 'Info'); Start-Sleep 9"
    )
    subprocess.Popen(["powershell", "-NoProfile", "-Command", script], creationflags=NO_WINDOW)


def _shortcut(action: str) -> Path:
    return Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "AnkiHelper" / f"AnkiHelper {action}.lnk"


def install_shortcuts() -> str:
    """Start-menu shortcuts carry a hotkey that works anywhere. They run pythonw so no console window opens."""
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    _shortcut("capture").parent.mkdir(parents=True, exist_ok=True)
    script = "$s = New-Object -ComObject WScript.Shell;" + "".join(
        f"$l = $s.CreateShortcut({_ps_quote(str(_shortcut(action)))}); $l.TargetPath = {_ps_quote(str(pythonw))};"
        f"$l.Arguments = {_ps_quote(f'-X utf8 -m ankihelper {action}')}; $l.Hotkey = {_ps_quote(keys.replace('Ctrl', 'CTRL').replace('Alt', 'ALT'))};"
        f"$l.WorkingDirectory = {_ps_quote(str(Path.home()))}; $l.Save();"
        for action, keys in SHORTCUTS.items()
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True, creationflags=NO_WINDOW)
    return "Added Start-menu shortcuts: " + ", ".join(f"{keys} runs {action}" for action, keys in SHORTCUTS.items())


def keybind_status() -> tuple[bool, str]:
    missing = [action for action in SHORTCUTS if not _shortcut(action).exists()]
    if missing:
        return False, "No Start-menu shortcut for: " + ", ".join(missing)
    return True, ", ".join(f"{keys} runs {action}" for action, keys in SHORTCUTS.items())


def keybind_fix_hint() -> str:
    return "Run `python -m ankihelper install-shortcuts` with AnkiHelper's Python; it adds Ctrl+Alt+A (capture) and Ctrl+Alt+B (batch)."
