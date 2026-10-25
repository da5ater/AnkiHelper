import shutil
import subprocess
from pathlib import Path

SYSTEM_DICTATION: str | None = "macOS Dictation: press the Fn key twice in a text field"
NAME = "macOS"


def anki_installed() -> bool:
    return Path("/Applications/Anki.app").exists()


def launch_anki() -> None:
    subprocess.Popen(["open", "-a", "Anki"])


def notify(title: str, body: str, offer_setup: bool = False) -> None:
    script = "on run argv\ndisplay notification (item 2 of argv) with title (item 1 of argv)\nend run"
    subprocess.Popen(["osascript", "-e", script, title, body])




def keybind_status() -> tuple[bool, str]:
    if shutil.which("skhd"):
        return False, "Not verified; check your skhd config binds `ankihelper capture` and `ankihelper batch`"
    return False, "Not verified on macOS yet"


def keybind_fix_hint() -> str:
    return (
        "On macOS: create two Shortcuts.app shortcuts (or skhd bindings) that run "
        "`ankihelper capture` and `ankihelper batch`, bound to Option+Cmd+A and Option+Cmd+B."
    )
