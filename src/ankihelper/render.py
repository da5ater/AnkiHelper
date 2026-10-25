"""Turn the agent's small Markdown subset into Anki HTML.

Supported: fenced code blocks (```lang), inline `code`, **bold**, "- " bullet lists, paragraphs.
Code is highlighted with Pygments inline styles so it renders the same on desktop and AnkiDroid.
"""

import html
import re

from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import TextLexer, get_lexer_by_name
from pygments.util import ClassNotFound

FENCE = re.compile(r"```[ \t]*([\w+#.-]*)[ \t]*\n(.*?)(?:\n)?```", re.S)
CODE_BOX = (
    "background: #272822; padding: 0.7rem 0.8rem; border-radius: 8px; overflow-x: auto; "
    "line-height: 1.4; font-size: 0.8em; text-align: left;"
)
QUESTION_BOX = "font-weight:600; line-height:1.35"
_formatter = HtmlFormatter(style="monokai", noclasses=True, nowrap=True)


def _inline(text: str) -> str:
    parts = re.split(r"(`[^`\n]+`)", text)
    out = []
    for part in parts:
        if part.startswith("`") and part.endswith("`") and len(part) > 1:
            out.append(f"<code>{html.escape(part[1:-1])}</code>")
        else:
            escaped = html.escape(part)
            out.append(re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped))
    return "".join(out)


def _prose(text: str) -> str:
    out = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [line for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        if all(re.match(r"\s*[-*] ", line) for line in lines):
            items = "".join("<li>" + _inline(re.sub(r"^\s*[-*] ", "", line)) + "</li>" for line in lines)
            out.append(f"<ul>{items}</ul>")
        else:
            out.append("<p>" + "<br>".join(_inline(line) for line in lines) + "</p>")
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
