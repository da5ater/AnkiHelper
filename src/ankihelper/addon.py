"""Installs the AnkiHelper add-on into Anki's add-ons folder."""

import json
import os
import shutil
import sys
from pathlib import Path

SOURCE = Path(__file__).parent / "anki_addon" / "ankihelper"
NAME = "ankihelper"


def addons_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Anki2" / "addons21"
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", "")) / "Anki2" / "addons21"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "Anki2" / "addons21"


def installed() -> bool:
    return (addons_dir() / NAME / "__init__.py").exists()


def _cli_command() -> list[str]:
    found = shutil.which("ankihelper")
    return [found] if found else [sys.executable, "-m", "ankihelper"]


def install() -> str:
    """Link (or on Windows copy) the add-on into Anki and tell it how to run AnkiHelper. Safe to run again."""
    target = addons_dir() / NAME
    target.parent.mkdir(parents=True, exist_ok=True)
    (SOURCE / "user_files").mkdir(exist_ok=True)
    (SOURCE / "user_files" / "cli.json").write_text(json.dumps({"command": _cli_command()}, indent=2))
    if target.is_symlink() or target.exists():
        if target.is_symlink() and target.resolve() == SOURCE.resolve():
            return f"Already installed at {target}. Restart Anki if it is open."
        backup = target.with_name(f"{NAME}.old")
        shutil.rmtree(backup, ignore_errors=True)
        target.rename(backup)
    if sys.platform == "win32":
        shutil.copytree(SOURCE, target)
    else:
        target.symlink_to(SOURCE, target_is_directory=True)
    return f"Installed the AnkiHelper add-on at {target}. Restart Anki to load it."
