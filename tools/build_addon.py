"""Build dist/ankihelper.ankiaddon, the file uploaded to AnkiWeb (https://ankiweb.net/shared/addons)."""

import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "ankihelper" / "anki_addon" / "ankihelper"
OUT = ROOT / "dist" / "ankihelper.ankiaddon"
SKIP = {"meta.json", "cli.json"}
"""Per-user files: Anki's saved settings and the local path to the ankihelper command."""


def build() -> Path:
    OUT.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(SOURCE.rglob("*")):
            if path.is_file() and path.name not in SKIP and "__pycache__" not in path.parts:
                archive.write(path, path.relative_to(SOURCE).as_posix())
    return OUT


if __name__ == "__main__":
    out = build()
    with zipfile.ZipFile(out) as archive:
        print(out, *archive.namelist(), sep="\n  ")
