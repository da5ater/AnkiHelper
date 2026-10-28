from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

BG = "#0f0c1d"
SIDEBAR = "#151129"
SURFACE = "#1c1734"
SURFACE_HI = "#251f45"
BORDER = "#2f2858"
TEXT = "#efeaff"
MUTED = "#9c94cc"
FAINT = "#6b6496"

VIOLET = "#8b5cf6"
PINK = "#ec4899"
CYAN = "#22d3ee"
GREEN = "#34d399"
AMBER = "#fbbf24"
RED = "#fb7185"
BLUE = "#60a5fa"

AGENT_COLORS = {"claude": "#f97316", "codex": GREEN, "gemini": BLUE, "opencode": "#e2e8f0"}
PAGE_COLORS = {"capture": PINK, "inbox": AMBER, "setup": GREEN, "settings": CYAN}

GRADIENT = f"qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {VIOLET}, stop:1 {PINK})"

STYLESHEET = f"""
* {{ font-size: 14px; color: {TEXT}; }}
QWidget#root {{ background: {BG}; }}
QWidget#page {{ background: {BG}; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}

QFrame#sidebar {{ background: {SIDEBAR}; border-right: 1px solid {BORDER}; }}
QLabel#brand {{ font-size: 21px; font-weight: 800; }}
QLabel#brandSub {{ color: {FAINT}; font-size: 12px; }}
QPushButton#nav {{
    text-align: left; padding: 11px 14px; border-radius: 12px; border: none;
    background: transparent; color: {MUTED}; font-size: 15px; font-weight: 600;
}}
QPushButton#nav:hover {{ background: {SURFACE}; color: {TEXT}; }}
QPushButton#nav:checked {{ background: {SURFACE_HI}; color: {TEXT}; }}

QLabel#title {{ font-size: 26px; font-weight: 800; }}
QLabel#subtitle {{ color: {MUTED}; font-size: 14px; }}
QLabel#fieldLabel {{ color: {MUTED}; font-size: 12px; font-weight: 700; letter-spacing: 1.5px; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#faint {{ color: {FAINT}; font-size: 12px; }}
QLabel#error {{ color: {RED}; font-size: 12px; }}
QLabel#sectionTitle {{ font-size: 16px; font-weight: 700; }}

QFrame#thumb {{ background: {SURFACE_HI}; border: 1px solid {BORDER}; border-radius: 10px; }}
QPushButton#modeToggle {{ padding: 4px 10px; border-radius: 9px; font-size: 12px; }}
QPushButton#modeToggle[mode="show"] {{ background: rgba(139, 92, 246, 0.18); border: 1px solid {VIOLET}; color: #c4b5fd; }}
QPushButton#modeToggle[mode="read"] {{ background: rgba(34, 211, 238, 0.16); border: 1px solid {CYAN}; color: {CYAN}; }}
QFrame#card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 16px; }}

QPlainTextEdit, QLineEdit, QComboBox {{
    background: {SURFACE}; border: 2px solid {BORDER}; border-radius: 14px;
    padding: 10px 12px; selection-background-color: {VIOLET};
}}
QPlainTextEdit {{ font-size: 16px; }}
QPlainTextEdit[accent="violet"]:focus {{ border-color: {VIOLET}; background: {SURFACE_HI}; }}
QPlainTextEdit[accent="cyan"]:focus {{ border-color: {CYAN}; background: {SURFACE_HI}; }}
QComboBox:focus, QComboBox:on, QLineEdit:focus {{ border-color: {PINK}; background: {SURFACE_HI}; }}
QComboBox::drop-down {{ border: none; width: 28px; }}
QComboBox QAbstractItemView {{
    background: {SURFACE_HI}; border: 1px solid {BORDER}; selection-background-color: {VIOLET}; padding: 4px;
}}
QTextBrowser#preview {{ background: {SURFACE}; border: 2px solid {BORDER}; border-radius: 14px; padding: 10px; }}
QPlainTextEdit#log {{
    font-family: "CaskaydiaMono Nerd Font", "JetBrains Mono", monospace; font-size: 12px;
    background: #0b0916; color: {MUTED}; border-radius: 12px;
}}

QPushButton {{
    background: {SURFACE_HI}; border: 1px solid {BORDER}; border-radius: 12px;
    padding: 10px 18px; font-weight: 700;
}}
QPushButton:hover {{ border-color: {VIOLET}; }}
QPushButton:disabled {{ color: {FAINT}; border-color: {SURFACE_HI}; }}
QPushButton#primary {{ background: {GRADIENT}; border: none; color: white; padding: 12px 26px; font-size: 15px; }}
QPushButton#primary:hover {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #9d74ff, stop:1 #f472b6); }}
QPushButton#primary:disabled {{ background: {SURFACE_HI}; color: {FAINT}; }}
QPushButton#danger {{ background: transparent; border: none; color: {FAINT}; padding: 6px 10px; font-size: 16px; }}
QPushButton#danger:hover {{ color: {RED}; }}

QPushButton#mic {{
    border-radius: 24px; min-width: 48px; min-height: 48px; max-width: 48px; max-height: 48px;
    padding: 0; font-size: 20px; background: {SURFACE_HI}; border: 2px solid {BORDER};
}}
QPushButton#mic:hover {{ border-color: {PINK}; }}
QPushButton#mic[state="recording"] {{ background: {RED}; border-color: #ffd1da; }}
QPushButton#mic[state="transcribing"] {{ background: {AMBER}; border-color: #fff1c2; }}

QPushButton#tile {{
    text-align: left; padding: 14px 16px; border-radius: 16px; border: 2px solid {BORDER};
    background: {SURFACE}; font-weight: 600;
}}
QPushButton#tile:hover {{ background: {SURFACE_HI}; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QToolTip {{ background: {SURFACE_HI}; color: {TEXT}; border: 1px solid {BORDER}; padding: 6px; }}
"""


def rgba(color: str, alpha: float) -> str:
    """Qt reads 8-digit hex as #AARRGGBB, so translucent colors go through rgba()."""
    r, g, b = (int(color[i : i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r}, {g}, {b}, {alpha})"


def pill_style(color: str) -> str:
    return (
        f"background: {rgba(color, 0.15)}; color: {color}; border: 1px solid {rgba(color, 0.45)}; border-radius: 10px;"
        "padding: 3px 10px; font-size: 12px; font-weight: 700;"
    )


def apply(app: QApplication) -> None:
    app.setStyle("Fusion")
    palette = QPalette()
    for role, color in (
        (QPalette.ColorRole.Window, BG),
        (QPalette.ColorRole.Base, SURFACE),
        (QPalette.ColorRole.AlternateBase, SURFACE_HI),
        (QPalette.ColorRole.Text, TEXT),
        (QPalette.ColorRole.WindowText, TEXT),
        (QPalette.ColorRole.ButtonText, TEXT),
        (QPalette.ColorRole.Button, SURFACE_HI),
        (QPalette.ColorRole.Highlight, VIOLET),
        (QPalette.ColorRole.HighlightedText, "#ffffff"),
        (QPalette.ColorRole.PlaceholderText, FAINT),
    ):
        palette.setColor(role, QColor(color))
    app.setPalette(palette)
    app.setStyleSheet(STYLESHEET)
