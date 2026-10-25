import shutil
import subprocess
from pathlib import Path

NAME = "macOS"


def anki_installed() -> bool:
    return Path("/Applications/Anki.app").exists()


def launch_anki() -> None:
    subprocess.Popen(["open", "-a", "Anki"])


def notify(title: str, body: str, offer_setup: bool = False) -> None:
    script = f"display notification {body!r} with title {title!r}"
    subprocess.Popen(["osascript", "-e", script.replace("'", '"')])


def dictation_status() -> tuple[bool, str]:
    return True, "macOS Dictation (press the dictation key in any text field)"


def keybind_status() -> tuple[bool, str]:
    if shutil.which("skhd"):
        return False, "Not verified; check your skhd config binds `ankihelper capture` and `ankihelper batch`"
    return False, "Not verified on macOS yet"


def keybind_fix_hint() -> str:
    return (
        "On macOS: create two Shortcuts.app shortcuts (or skhd bindings) that run "
        "`ankihelper capture` and `ankihelper batch`, bound to Option+Cmd+A and Option+Cmd+B."
    )
