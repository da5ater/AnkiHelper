import json
import os
import shlex
import shutil
import subprocess
import sys

NAME = "Linux"
CAPTURE_KEYS = "SUPER + ALT + A"
BATCH_KEYS = "SUPER + ALT + B"


def _detached(cmd: list[str]) -> None:
    subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def anki_installed() -> bool:
    return shutil.which("anki") is not None


def launch_anki() -> None:
    _detached(["anki"])


def notify(title: str, body: str, offer_setup: bool = False) -> None:
    if not shutil.which("notify-send"):
        print(f"{title}: {body}", file=sys.stderr)
        return
    if not offer_setup:
        _detached(["notify-send", "-a", "AnkiHelper", title, body])
        return
    setup = shlex.join([sys.executable, "-m", "ankihelper", "setup"])
    send = shlex.join(["notify-send", "-a", "AnkiHelper", "-u", "critical", "-A", "setup=Open setup", title, body])
    _detached(["sh", "-c", f'[ "$({send})" = setup ] && exec {setup}'])


def dictation_status() -> tuple[bool, str]:
    if shutil.which("voxtype"):
        return True, "voxtype found"
    return False, "voxtype is not installed (https://github.com/peteonrails/voxtype)"


def keybind_status() -> tuple[bool, str]:
    if not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return False, "Not running under Hyprland; bind `ankihelper capture` and `ankihelper batch` in your desktop's shortcut settings"
    try:
        binds = json.loads(subprocess.run(["hyprctl", "binds", "-j"], capture_output=True, text=True, timeout=5).stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired) as e:
        return False, f"Could not read Hyprland binds: {e}"
    # Lua binds report a callback id as `arg`, so the description is the only place the command shows.
    texts = [f"{b.get('arg', '')} {b.get('description', '')}".lower() for b in binds]
    missing = [cmd for cmd in ("ankihelper capture", "ankihelper batch") if not any(cmd in t for t in texts)]
    if missing:
        return False, "No Hyprland binding runs: " + ", ".join(missing)
    return True, "capture and batch are bound"


def keybind_fix_hint() -> str:
    return (
        "On Hyprland (this machine uses the Lua config in ~/.config/hypr/, personal bindings go in "
        "~/.config/hypr/bindings.lua using o.bind(keys, description, command)): bind "
        f"{CAPTURE_KEYS} to `ankihelper capture` with description \"AnkiHelper capture\" and {BATCH_KEYS} to "
        "`ankihelper batch` with description \"AnkiHelper batch\". "
        "Also add a window rule so windows with class `ankihelper` float, are centered and about 720x520. "
        "Check the keys are free with `hyprctl binds -j` first; reload with `hyprctl reload` and confirm "
        "the binds appear in `hyprctl binds -j`."
    )
