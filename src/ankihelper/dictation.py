import json
import os
import shutil
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .platforms import current as platform

MicState = str
""""idle", "recording" or "transcribing"."""


@dataclass(frozen=True)
class Method:
    id: str
    title: str
    blurb: str
    state: Callable[[], MicState | None] | None = None
    """For engines the capture window's mic button drives; None when the engine is not answering."""
    toggle: Callable[[], None] | None = None


def voxtype_state() -> MicState | None:
    try:
        done = subprocess.run(["voxtype", "status"], capture_output=True, text=True, timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        return None
    state = done.stdout.strip()
    return state if done.returncode == 0 and state in {"idle", "recording", "transcribing"} else None


def toggle_voxtype() -> None:
    subprocess.Popen(["voxtype", "record", "toggle"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _hex_dir() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", "")) / "hex"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "hex"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "hex"


def hex_control(command: str, **fields) -> dict | None:
    """One command to the running Hex over its local API; None when Hex is not running or not answering."""
    try:
        api = json.loads((_hex_dir() / "local-api.json").read_text(encoding="utf-8"))
        request = urllib.request.Request(
            f"http://127.0.0.1:{api['port']}/control",
            data=json.dumps({"version": 4, "command": command, **fields}).encode(),
            headers={"Authorization": f"Bearer {api['token']}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=2) as reply:
            return json.loads(reply.read())
    except (OSError, ValueError, KeyError):
        return None


def hex_state() -> MicState | None:
    status = hex_control("status")
    if not status or not status.get("listener", {}).get("running"):
        return None
    capture = status.get("capture", {})
    if capture.get("state") == "recording":
        return "recording"
    return "transcribing" if capture.get("pending_jobs") else "idle"


def toggle_hex() -> None:
    hex_control("dictation", action="toggle")


METHODS = [
    Method(
        "hex",
        "Hex",
        "Local AI dictation from the OpenCode team, on Linux, macOS and Windows. Hold Ctrl+Space anywhere, or use the mic button.",
        hex_state,
        toggle_hex,
    ),
    Method("voxtype", "Voxtype", "Local speech-to-text on Linux. The mic button in the capture window starts and stops it.", voxtype_state, toggle_voxtype),
    Method("system", "System dictation", platform.SYSTEM_DICTATION or "Your OS has no built-in dictation AnkiHelper knows about."),
    Method("none", "Keyboard only", "Type or paste. No dictation."),
]


def get(method: str) -> Method | None:
    return next((m for m in METHODS if m.id == method), None)


def _hex_status() -> tuple[bool, str]:
    status = hex_control("status")
    if status is None:
        return False, "Hex is not running; install it from https://github.com/anomalyco/hex and open it"
    model = status.get("model", {})
    if not model.get("installed"):
        return False, f"Hex is downloading its speech model ({model.get('name', 'model')})"
    if not status.get("listener", {}).get("running"):
        return False, "Hex is running but its shortcut listener is off; finish setup in the Hex window"
    return True, f"Hex is ready with {model.get('name', 'its model')}"


def status(method: str) -> tuple[bool, str]:
    if method == "hex":
        return _hex_status()
    if method == "voxtype":
        if not shutil.which("voxtype"):
            return False, "voxtype is not installed"
        state = voxtype_state()
        if state is None:
            return False, "voxtype is installed but its daemon is not running"
        return True, f"voxtype is {state}"
    if method == "system":
        if platform.SYSTEM_DICTATION:
            return True, platform.SYSTEM_DICTATION
        return False, f"{platform.NAME} has no built-in dictation; pick Hex or Keyboard only"
    if method == "none":
        return True, "keyboard only"
    return False, f"unknown dictation method {method!r}"
