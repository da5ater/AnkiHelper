"""OS-specific pieces. Each module exposes the same functions; `current` picks one."""

import sys

if sys.platform.startswith("linux"):
    from . import linux as current
elif sys.platform == "darwin":
    from . import macos as current
elif sys.platform == "win32":
    from . import windows as current
else:
    raise RuntimeError(f"Unsupported platform: {sys.platform}")

__all__ = ["current"]
