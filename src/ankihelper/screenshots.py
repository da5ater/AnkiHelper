"""Turns small HTML pages an agent writes (a UI as it looks now, and as it should look) into pictures for a card."""

import hashlib
import html
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import config
from .platforms import current as platform

SIZE = (900, 560)
NAMES = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge", "msedge", "chrome"]


def browser() -> str | None:
    """A Chromium-based browser that can take headless screenshots: Chrome, Chromium or Edge."""
    for name in NAMES:
        if found := shutil.which(name):
            return found
    if sys.platform == "win32":
        roots = [os.environ.get(v, "") for v in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
        tails = [Path("Google/Chrome/Application/chrome.exe"), Path("Microsoft/Edge/Application/msedge.exe")]
        candidates = [Path(root) / tail for tail in tails for root in roots if root]
    elif sys.platform == "darwin":
        candidates = [Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"), Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge")]
    else:
        candidates = []
    return next((str(p) for p in candidates if p.exists()), None)


def _labelled(page: str, label: str) -> str:
    tag = (
        '<div style="position:fixed;top:8px;right:10px;z-index:2147483647;padding:3px 10px;border-radius:999px;'
        "background:#111;color:#fff;font:600 13px/1.4 system-ui,sans-serif;opacity:.85\">"
        f"{html.escape(label)}</div>"
    )
    return page.replace("</body>", tag + "</body>") if "</body>" in page else page + tag


def shoot(page: str, label: str) -> str | None:
    """Render one page to a PNG in AnkiHelper's media folder and return its file name, or None without a browser."""
    found = browser()
    if not found:
        return None
    page = _labelled(page, label)
    name = f"ankihelper-screen-{hashlib.sha1(page.encode()).hexdigest()[:12]}.png"
    target = config.media_dir() / name
    if target.exists():
        return name
    with tempfile.TemporaryDirectory() as work:
        source = Path(work) / "page.html"
        source.write_text(page, encoding="utf-8")
        subprocess.run(
            [
                found,
                "--headless=new",
                "--disable-gpu",
                "--hide-scrollbars",
                "--no-first-run",
                "--no-default-browser-check",
                f"--user-data-dir={Path(work) / 'profile'}",
                f"--window-size={SIZE[0]},{SIZE[1]}",
                f"--screenshot={target}",
                source.as_uri(),
            ],
            capture_output=True,
            timeout=60,
            creationflags=platform.NO_WINDOW,
        )
    return name if target.exists() else None


def attach(reply: dict) -> None:
    """Replace each new card's "screens" with "pictures": file names of the rendered pages."""
    missing = False
    for card in reply.get("new_cards") or []:
        screens = card.pop("screens", None) if isinstance(card, dict) else None
        if not isinstance(screens, list):
            continue
        for screen in screens:
            if isinstance(screen, dict) and str(screen.get("html", "")).strip():
                name = shoot(str(screen["html"]), str(screen.get("label") or ""))
                if name:
                    card.setdefault("pictures", []).append(name)
                else:
                    missing = True
    if missing:
        reply["reply"] = (str(reply.get("reply") or "").rstrip() + " No Chrome, Chromium or Edge was found, so the card has no screenshots.").strip()
