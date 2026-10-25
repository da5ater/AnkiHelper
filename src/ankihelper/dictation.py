import shutil
import subprocess
from dataclasses import dataclass

from .platforms import current as platform


@dataclass(frozen=True)
class Method:
    id: str
    title: str
    blurb: str


METHODS = [
    Method("voxtype", "Voxtype", "Local speech-to-text on Linux. The mic button in the capture window starts and stops it."),
    Method("system", "System dictation", platform.SYSTEM_DICTATION or "Your OS has no built-in dictation AnkiHelper knows about."),
    Method("none", "Keyboard only", "Type or paste. No dictation."),
]


def status(method: str) -> tuple[bool, str]:
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
        return False, f"{platform.NAME} has no built-in dictation; pick Voxtype or Keyboard only"
    if method == "none":
        return True, "keyboard only"
    return False, f"unknown dictation method {method!r}"


def voxtype_state() -> str | None:
    """"idle", "recording" or "transcribing"; None when the daemon is not answering."""
    try:
        done = subprocess.run(["voxtype", "status"], capture_output=True, text=True, timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        return None
    state = done.stdout.strip()
    return state if done.returncode == 0 and state in {"idle", "recording", "transcribing"} else None


def toggle_voxtype() -> None:
    subprocess.Popen(["voxtype", "record", "toggle"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
