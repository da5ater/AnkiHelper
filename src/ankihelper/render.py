"""Turn the agent's Markdown into Anki HTML.

Supported, Obsidian style: fenced code blocks (```lang), inline `code`, **bold**, *italic*, ==highlight==,
~~strike~~, links, "- " and "1. " lists (nested by indentation), tables, headings, rules, blockquotes and
callouts ("> [!tip] Title"), which may hold code blocks of their own.
Code is highlighted with Pygments inline styles so it renders the same on desktop and AnkiDroid.
"""

import html
import re

from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import TextLexer, get_lexer_by_name
from pygments.util import ClassNotFound

FENCE = re.compile(r"^[ \t]*```[ \t]*([\w+#.-]*)[^\n]*\n(.*?)\n?^[ \t]*```[ \t]*$", re.S | re.M)
CODE_BOX = (
    "background: #272822; padding: 0.7rem 0.8rem; border-radius: 8px; overflow-x: auto; "
    "line-height: 1.4; font-size: 0.8em; text-align: left;"
)
QUESTION_BOX = "font-weight:600; line-height:1.35"
_formatter = HtmlFormatter(style="monokai", noclasses=True, nowrap=True)


CALLOUTS = {
    "note": ("#448aff", "✎"),
    "info": ("#448aff", "ℹ"),
    "todo": ("#448aff", "☐"),
    "abstract": ("#00b0ff", "📋"),
    "summary": ("#00b0ff", "📋"),
    "tldr": ("#00b0ff", "📋"),
    "tip": ("#00bfa5", "💡"),
    "hint": ("#00bfa5", "💡"),
    "important": ("#00bfa5", "❗"),
    "success": ("#00c853", "✓"),
    "check": ("#00c853", "✓"),
    "done": ("#00c853", "✓"),
    "question": ("#ec7500", "?"),
    "help": ("#ec7500", "?"),
    "faq": ("#ec7500", "?"),
    "warning": ("#ff9100", "⚠"),
    "caution": ("#ff9100", "⚠"),
    "attention": ("#ff9100", "⚠"),
    "failure": ("#ff5252", "✕"),
    "fail": ("#ff5252", "✕"),
    "missing": ("#ff5252", "✕"),
    "danger": ("#ff1744", "⚡"),
    "error": ("#ff1744", "⚡"),
    "bug": ("#f50057", "🐞"),
    "example": ("#7c4dff", "≡"),
    "quote": ("#9e9e9e", "❝"),
    "cite": ("#9e9e9e", "❝"),
}
CALLOUT_HEAD = re.compile(r"^\[!(\w+)\][+-]?[ \t]*(.*)$")
LIST_ITEM = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
RULE = re.compile(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$")
TABLE_DIVIDER = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
CELL = "border: 1px solid rgba(136, 136, 136, 0.4); padding: 0.3em 0.6em; text-align: left; vertical-align: top;"
MARK = "background: rgba(255, 208, 0, 0.4); color: inherit; padding: 0 2px; border-radius: 3px;"


def _rgb(color: str) -> str:
    return ", ".join(str(int(color[i : i + 2], 16)) for i in (1, 3, 5))


def _inline(text: str) -> str:
    """Inline Markdown, Obsidian style: `code`, **bold**, *italic*, ==highlight==, ~~strike~~ and [links](url).
    Code is set aside first so bold can wrap it (**`find`**) and nothing inside code is formatted."""
    codes: list[str] = []

    def keep(match: re.Match) -> str:
        codes.append(f"<code>{html.escape(match.group(1))}</code>")
        return f"\x00{len(codes) - 1}\x00"

    out = html.escape(re.sub(r"`([^`\n]+)`", keep, text))
    out = re.sub(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)", r'<a href="\2">\1</a>', out)
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"(?<![*\w])\*(?![\s*])(.+?)(?<![\s*])\*(?![*\w])", r"<em>\1</em>", out)
    out = re.sub(r"==(?!\s)(.+?)(?<!\s)==", rf'<mark style="{MARK}">\1</mark>', out)
    out = re.sub(r"~~(.+?)~~", r"<s>\1</s>", out)
    return re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], out)


def _callout(lines: list[str]) -> str:
    body = [re.sub(r"^\s*> ?", "", line) for line in lines]
    head = CALLOUT_HEAD.match(body[0])
    if not head:
        return f'<blockquote style="border-left: 3px solid rgba(136, 136, 136, 0.6); margin: 0.6em 0; padding: 0.1em 0.9em; opacity: 0.9; text-align: left;">{to_html(chr(10).join(body))}</blockquote>'
    kind = head.group(1).lower()
    color, icon = CALLOUTS.get(kind, CALLOUTS["note"])
    title = head.group(2).strip() or kind.capitalize()
    inner = to_html("\n".join(body[1:]))
    return (
        f'<div style="border-left: 4px solid {color}; background: rgba({_rgb(color)}, 0.1); border-radius: 6px; '
        f'padding: 0.5em 0.9em; margin: 0.6em 0; text-align: left;">'
        f'<div style="font-weight: 700; color: {color};">{icon} {_inline(title)}</div>{inner}</div>'
    )


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _table(lines: list[str]) -> str:
    head = "".join(f'<th style="{CELL}">{_inline(c)}</th>' for c in _cells(lines[0]))
    rows = "".join("<tr>" + "".join(f'<td style="{CELL}">{_inline(c)}</td>' for c in _cells(line)) + "</tr>" for line in lines[2:])
    return f'<table style="border-collapse: collapse; margin: 0.6em 0;"><tr>{head}</tr>{rows}</table>'


def _list(items: list[tuple[int, str, str]]) -> str:
    """Bullet and numbered lists; deeper indentation nests a list inside the item above it."""
    out: list[str] = []
    stack: list[tuple[int, str]] = []
    for indent, tag, text in items:
        while stack and indent < stack[-1][0]:
            out.append(f"</li></{stack.pop()[1]}>")
        if stack and indent == stack[-1][0]:
            out.append("</li>")
        else:
            out.append(f"<{tag}>")
            stack.append((indent, tag))
        out.append("<li>" + text)
    while stack:
        out.append(f"</li></{stack.pop()[1]}>")
    return "".join(out)


def _starts_block(lines: list[str], i: int) -> bool:
    line = lines[i]
    return bool(
        line.lstrip().startswith(">")
        or LIST_ITEM.match(line)
        or HEADING.match(line)
        or RULE.match(line)
        or (line.lstrip().startswith("|") and i + 1 < len(lines) and TABLE_DIVIDER.match(lines[i + 1]))
    )


def _prose(text: str) -> str:
    lines = text.strip("\n").splitlines()
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
        elif line.lstrip().startswith(">"):
            j = i
            while j < len(lines) and lines[j].lstrip().startswith(">"):
                j += 1
            out.append(_callout(lines[i:j]))
            i = j
        elif line.lstrip().startswith("|") and i + 1 < len(lines) and TABLE_DIVIDER.match(lines[i + 1]):
            j = i + 2
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                j += 1
            out.append(_table(lines[i:j]))
            i = j
        elif heading := HEADING.match(line):
            size = {1: "1.2em", 2: "1.1em"}.get(len(heading.group(1)), "1em")
            out.append(f'<div style="font-weight: 700; font-size: {size}; margin: 0.6em 0 0.3em;">{_inline(heading.group(2))}</div>')
            i += 1
        elif RULE.match(line):
            out.append('<hr style="border: none; border-top: 1px solid rgba(136, 136, 136, 0.4);">')
            i += 1
        elif LIST_ITEM.match(line):
            items: list[tuple[int, str, str]] = []
            while i < len(lines) and lines[i].strip():
                item = LIST_ITEM.match(lines[i])
                if item:
                    tag = "ol" if item.group(2)[0].isdigit() else "ul"
                    items.append((len(item.group(1).expandtabs(4)), tag, _inline(item.group(3))))
                elif lines[i].startswith((" ", "\t")):
                    indent, tag, text = items[-1]
                    items[-1] = (indent, tag, text + "<br>" + _inline(lines[i].strip()))
                else:
                    break
                i += 1
            out.append(_list(items))
        else:
            j = i + 1
            while j < len(lines) and lines[j].strip() and not _starts_block(lines, j):
                j += 1
            out.append("<p>" + "<br>".join(_inline(part) for part in lines[i:j]) + "</p>")
            i = j
    return "".join(out)


def _code(lang: str, code: str) -> str:
    try:
        lexer = get_lexer_by_name(lang) if lang else TextLexer()
    except ClassNotFound:
        lexer = TextLexer()
    body = highlight(code, lexer, _formatter)
    return f'<div class="highlight" style="{CODE_BOX}"><pre style="line-height: 125%;">{body}</pre></div>'


def to_html(markdown: str) -> str:
    out, pos = [], 0
    for match in FENCE.finditer(markdown):
        out.append(_prose(markdown[pos : match.start()]))
        out.append(_code(match.group(1).lower(), match.group(2)))
        pos = match.end()
    out.append(_prose(markdown[pos:]))
    return "".join(out)


def question_html(markdown: str) -> str:
    return f'<div style="{QUESTION_BOX}">{to_html(markdown)}</div>'


def images_html(files: list[str]) -> str:
    return "".join(
        f'<div style="margin-top:0.6em"><img src="{html.escape(name)}" style="max-width:100%; border-radius:8px"></div>'
        for name in files
    )


def source_html(files: list[str]) -> str:
    if not files:
        return ""
    pictures = "".join(
        f'<img src="{html.escape(name)}" width="220" style="max-width:45%; border-radius:6px; margin-right:6px">'
        for name in files
    )
    return (
        '<div style="margin-top:1em; padding-top:0.5em; border-top:1px solid rgba(136, 136, 136, 0.33); font-size:0.65em; opacity:0.75">'
        f"Source<br>{pictures}</div>"
    )
