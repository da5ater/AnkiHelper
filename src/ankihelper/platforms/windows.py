import os
import subprocess
from pathlib import Path

NAME = "Windows"


def _anki_exe() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Anki" / "anki.exe"


def anki_installed() -> bool:
    return _anki_exe().exists()


def launch_anki() -> None:
    subprocess.Popen([str(_anki_exe())], creationflags=subprocess.DETACHED_PROCESS)


def notify(title: str, body: str, offer_setup: bool = False) -> None:
    script = (
        "[reflection.assembly]::loadwithpartialname('System.Windows.Forms') | Out-Null;"
        "$n = New-Object System.Windows.Forms.NotifyIcon; $n.Icon = [System.Drawing.SystemIcons]::Information;"
        f"$n.Visible = $true; $n.ShowBalloonTip(8000, '{title}', '{body}', 'Info'); Start-Sleep 9"
    )
    subprocess.Popen(["powershell", "-NoProfile", "-Command", script], creationflags=subprocess.DETACHED_PROCESS)


def dictation_status() -> tuple[bool, str]:
    return True, "Windows voice typing (Win+H in any text field)"


def keybind_status() -> tuple[bool, str]:
    return False, "Not verified on Windows yet"


def keybind_fix_hint() -> str:
    return (
        "On Windows: create Start-menu shortcuts that run `ankihelper capture` and `ankihelper batch` "
        "with shortcut keys Ctrl+Alt+A and Ctrl+Alt+B (or an AutoHotkey script)."
    )
