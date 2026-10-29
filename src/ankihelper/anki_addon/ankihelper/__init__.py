"""AnkiHelper inside Anki: fix the card you are studying, see where it came from, and teach AnkiHelper
from your edits and deletions.

This runs in Anki's own Python, which does not have AnkiHelper's dependencies, so every request goes to
the `ankihelper` command (`ankihelper anki <action>`, JSON on stdin and stdout) in a background thread.
"""

import json
import os
import re
import shutil
import subprocess
from html import unescape
from pathlib import Path

from anki import hooks
from aqt import gui_hooks, mw
from aqt.operations.note import update_note
from aqt.qt import (
    QAction,
    QCursor,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    Qt,
)
from aqt.utils import showWarning, tooltip

ADDON_DIR = Path(__file__).parent
CLOZE = 1
_writing: set[int] = set()
"""Notes AnkiHelper is saving right now, so the edit watcher does not report them as the learner's edits."""


def _command() -> list[str]:
    config_file = ADDON_DIR / "user_files" / "cli.json"
    if config_file.exists():
        return json.loads(config_file.read_text())["command"]
    found = shutil.which("ankihelper") or str(Path.home() / ".local" / "bin" / "ankihelper")
    return [found]


def _clean_env() -> dict[str, str]:
    """Anki's bundled Python and Qt leak into child processes through these and break AnkiHelper's own."""
    env = dict(os.environ)
    for key in list(env):
        if key in ("PYTHONPATH", "PYTHONHOME", "PYTHONSAFEPATH") or key.startswith("QT_") or key.startswith("QML"):
            env.pop(key)
    return env


NOT_INSTALLED = (
    "The AnkiHelper app is not installed or could not be found. "
    "Install it from https://github.com/da5ater/AnkiHelper and run `ankihelper install-addon`."
)


def _run(action: str, payload: dict) -> dict:
    try:
        done = _subprocess(action, payload)
    except FileNotFoundError:
        return {"error": NOT_INSTALLED}
    try:
        return json.loads(done.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"error": (done.stderr or done.stdout or f"ankihelper exited {done.returncode}").strip()[-500:]}


def _subprocess(action: str, payload: dict):
    return subprocess.run(
        [*_command(), "anki", action],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=900,
        env=_clean_env(),
    )


def call(action: str, payload: dict, on_done=None) -> None:
    def finished(future) -> None:
        try:
            reply = future.result()
        except Exception as error:  # a missing CLI or a timeout must not crash Anki
            reply = {"error": str(error)}
        if on_done:
            on_done(reply)

    mw.taskman.run_in_background(lambda: _run(action, payload), finished, uses_collection=False)


def text_of(fragment: str) -> str:
    fragment = re.sub(r"(?i)<br\s*/?>|</(p|div|li|pre|tr)>", "\n", fragment)
    return unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


def _sides(note) -> tuple[str, str] | None:
    """The question and answer fields of a note AnkiHelper may rewrite: exactly two fields and not cloze.
    Cloze and Image Occlusion keep their deletions and masks in the fields, and in a three-field note
    the second field may be audio or an image rather than the answer."""
    names = list(note.keys())
    if len(names) != 2 or note.note_type()["type"] == CLOZE:
        return None
    return names[0], names[1]


UNSUPPORTED = "AnkiHelper can only rewrite cards with exactly two fields (a question and an answer), not cloze or image occlusion cards."


def _describe(note) -> dict:
    sides = _sides(note)
    card_ids = note.card_ids()
    deck = mw.col.decks.name(mw.col.get_card(card_ids[0]).did) if card_ids else ""
    return {
        "note_id": note.id,
        "model": note.note_type()["name"],
        "deck": deck,
        "tags": list(note.tags),
        "question": text_of(note[sides[0]]) if sides else "",
        "answer": text_of(note[sides[1]]) if sides else "",
    }


def _current_note():
    if mw.state != "review" or not mw.reviewer.card:
        tooltip("Open a card in review first.")
        return None
    return mw.reviewer.card.note()


def _save(note_id: int, fields: dict[str, str], add_tags: list[str], message: str) -> None:
    """Write only these fields and tags onto the note as it is now, so edits made meanwhile survive."""
    try:
        note = mw.col.get_note(note_id)
    except Exception:  # deleted while AnkiHelper was working
        tooltip("That card was deleted, so the rewrite was not saved.")
        return
    for name, value in fields.items():
        note[name] = value
    for tag in add_tags:
        note.add_tag(tag)
    _writing.add(note.id)

    def saved(_changes) -> None:
        _writing.discard(note.id)
        if _review_snapshot.get("note_id") == note.id:
            _review_snapshot["before"] = _snapshot(mw.col.get_note(note.id))
        tooltip(message)

    def failed(error) -> None:
        _writing.discard(note.id)
        showWarning(f"AnkiHelper could not save the card: {error}")

    update_note(parent=mw, note=note).success(saved).failure(failed).run_in_background()


class FixDialog(QDialog):
    """Talk with AnkiHelper about the card in front of you: ask why, disagree, try other examples. The card
    preview updates as you go; OK saves the latest version and keeps the conversation so AnkiHelper learns
    what you meant, not just what changed."""

    def __init__(self, note):
        super().__init__(mw)
        self.note = note
        self.cancelled = False
        self.sides = _sides(note)
        self.before = {"question": note[self.sides[0]], "answer": note[self.sides[1]]} if self.sides else {}
        self.messages: list[dict] = []
        self.draft: dict | None = None
        self.draft_html: tuple[str, str] | None = None
        self.setWindowTitle("AnkiHelper · this card")
        self.resize(680, 720)
        layout = QVBoxLayout(self)
        self.card_label = QLabel("<b>The card</b>")
        layout.addWidget(self.card_label)
        self.preview = QTextBrowser()
        self.preview.setSearchPaths([mw.col.media.dir()])
        layout.addWidget(self.preview, 3)
        layout.addWidget(QLabel("<b>Conversation</b>"))
        self.chat = QTextBrowser()
        layout.addWidget(self.chat, 2)
        row = QHBoxLayout()
        self.text = QLineEdit()
        self.text.setPlaceholderText("Ask or tell it anything: why this example? · make me write it instead · shorter")
        self.text.returnPressed.connect(self.send)
        self.send_button = QPushButton("Send")
        self.send_button.clicked.connect(self.send)
        row.addWidget(self.text, 1)
        row.addWidget(self.send_button)
        layout.addLayout(row)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        close = QPushButton("Close")
        close.setToolTip("Leave the card as it was")
        close.clicked.connect(self.reject)
        self.ok = QPushButton("OK, keep this card")
        self.ok.setToolTip("Save the latest version and let AnkiHelper learn from this conversation")
        self.ok.clicked.connect(self.finish)
        buttons.addStretch()
        buttons.addWidget(close)
        buttons.addWidget(self.ok)
        layout.addLayout(buttons)
        self._show_card()
        if not self.sides:
            self.status.setText(UNSUPPORTED)
            self.send_button.setEnabled(False)
            self.ok.setEnabled(False)
        self.text.setFocus()

    def _show_card(self) -> None:
        front, back = self.draft_html or (self.before.get("question", ""), self.before.get("answer", ""))
        self.card_label.setText("<b>New version</b> (not saved until you press OK)" if self.draft_html else "<b>The card</b>")
        self.preview.setHtml(f"{front}<hr>{back}")

    def _show_chat(self) -> None:
        lines = []
        for m in self.messages:
            who = "You" if m["role"] == "learner" else "AnkiHelper"
            text = m["text"].replace("&", "&amp;").replace("<", "&lt;").replace("\n", "<br>")
            lines.append(f"<p><b>{who}:</b> {text}</p>")
        self.chat.setHtml("".join(lines))
        self.chat.verticalScrollBar().setValue(self.chat.verticalScrollBar().maximum())

    def send(self) -> None:
        said = self.text.text().strip()
        if not said or not self.sides or not self.send_button.isEnabled():
            return
        self.text.clear()
        self.messages.append({"role": "learner", "text": said})
        self._show_chat()
        self.send_button.setEnabled(False)
        self.status.setText("⏳ AnkiHelper is thinking…")
        payload = {
            "note_id": self.note.id,
            "question_html": self.before["question"],
            "answer_html": self.before["answer"],
            "messages": self.messages,
            "draft": self.draft,
        }
        call("chat", payload, self._answered)

    def reject(self) -> None:
        self.cancelled = True
        super().reject()

    def _answered(self, reply: dict) -> None:
        if self.cancelled:
            return
        self.send_button.setEnabled(True)
        if "error" in reply:
            self.status.setText(f"⚠ {reply['error']}")
            return
        self.status.setText("")
        self.messages.append({"role": "agent", "text": reply["reply"]})
        if reply.get("card"):
            self.draft = reply["card"]
            self.draft_html = (reply["front"], reply["back"])
            self._show_card()
        self._show_chat()
        self.text.setFocus()

    def finish(self) -> None:
        if self.draft_html:
            _save(self.note.id, {self.sides[0]: self.draft_html[0], self.sides[1]: self.draft_html[1]}, ["ah::fixed"], "Saved the new version. Edit → Undo brings the old one back.")
        if self.messages:
            payload = {"note_id": self.note.id, "before": self.before, "draft": self.draft, "messages": self.messages, "tags": list(self.note.tags)}
            call("chat-done", payload, lambda r: tooltip(f"Rule updated from your reasoning: {r['rule_updated']}") if r.get("rule_updated") else None)
        self.accept()


def fix_card() -> None:
    note = _current_note()
    if note:
        FixDialog(note).exec()


class HistoryDialog(QDialog):
    """Where the card came from: the learner's own note, the other cards made from it, and its versions."""

    def __init__(self, note):
        super().__init__(mw)
        self.note = note
        self.setWindowTitle("AnkiHelper · history of this card")
        self.resize(680, 620)
        layout = QVBoxLayout(self)
        self.view = QTextBrowser()
        self.view.setOpenLinks(False)
        self.view.anchorClicked.connect(self._clicked)
        self.view.setHtml("<p>Loading…</p>")
        layout.addWidget(self.view)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)
        self.reply: dict = {}
        call("history", {"note_id": note.id}, self._show)

    def _show(self, reply: dict) -> None:
        self.reply = reply
        if "error" in reply:
            self.view.setHtml(f"<p>⚠ {reply['error']}</p>")
            return
        if not reply.get("known"):
            self.view.setHtml("<p>This card was not made by AnkiHelper, so there is no history for it.</p>")
            return
        entry, media = reply["entry"], reply["media_dir"]
        parts = [
            "<h3>Your note</h3>",
            f"<p><b>{entry['question'] or '(the question was a picture)'}</b><br>{entry['answer']}</p>",
            f"<p style='color:gray'>{entry['topic']} · {entry['created']}</p>",
        ]
        for image in entry["images"]:
            parts.append(f"<p><img src='{media}/{image['file']}' width='260'></p>")
        card = reply["card"]
        parts.append(f"<p style='color:gray'>This card: group <b>{card.get('group', 'main')}</b>, Bloom <b>{card.get('bloom') or '?'}</b></p>")
        siblings = [s for s in reply["siblings"] if _exists(s["note_id"])]
        if siblings:
            parts.append("<h3>Other cards from the same note</h3><ul>")
            parts += [f"<li>[{s['group']}] {s['question']}</li>" for s in siblings]
            parts.append("</ul>")
        if reply["versions"]:
            parts.append("<h3>Versions you were offered</h3>")
            for v_index, version in enumerate(reply["versions"]):
                parts.append(f"<p><b>✨ {version['style']}</b><br><span style='color:gray'>{version['why']}</span></p>")
                for c_index, item in enumerate(version["cards"]):
                    parts.append(
                        f"<div style='border:1px solid #888; padding:8px'>{item['front']}<hr>{item['back']}</div>"
                        f"<p><a href='use:{v_index}:{c_index}'>Use this version</a></p>"
                    )
        self.view.setHtml("".join(parts))

    def _clicked(self, url) -> None:
        action, _, rest = url.toString().partition(":")
        if action != "use":
            return
        v_index, c_index = (int(x) for x in rest.split(":"))
        item = self.reply["versions"][v_index]["cards"][c_index]
        call("use-version", {"note_id": self.note.id, "card": item["card"]}, self._used)

    def _used(self, reply: dict) -> None:
        if "error" in reply:
            showWarning(reply["error"])
            return
        sides = _sides(self.note)
        if not sides:
            showWarning(UNSUPPORTED)
            return
        _save(self.note.id, {sides[0]: reply["front"], sides[1]: reply["back"]}, [], "Switched to that version.")
        self.accept()


def _exists(note_id: int) -> bool:
    try:
        mw.col.get_note(note_id)
        return True
    except Exception:  # deleted since it was made
        return False


def optimize_card() -> None:
    note = _current_note()
    if not note:
        return
    sides = _sides(note)
    if not sides:
        tooltip(UNSUPPORTED)
        return
    card_ids = note.card_ids()
    deck = mw.col.decks.name(mw.col.get_card(card_ids[0]).did) if card_ids else ""
    payload = {"note_id": note.id, "question_html": note[sides[0]], "answer_html": note[sides[1]], "deck": deck}
    tooltip("Opening AnkiHelper's preview with optimized versions of this card…")
    call("optimize", payload, lambda reply: showWarning(reply["error"]) if "error" in reply else None)


def show_history() -> None:
    note = _current_note()
    if note:
        HistoryDialog(note).exec()


BULK = 20
"""Edits or deletions of more notes than this at once are bulk tools, not taste: summarized or skipped."""
EDIT_QUIET_MS = 20_000
"""Editors save on every keystroke; an edit is reported once the note has been left alone this long."""
_pending: dict[int, dict] = {}
"""note id -> the note as it was before the learner started editing it."""
_review_snapshot: dict = {}
_flush_timer = None


def _snapshot(note) -> dict | None:
    sides = _sides(note)
    if not sides:
        return None
    return {"question": text_of(note[sides[0]]), "answer": text_of(note[sides[1]])}


def _report_edits(befores: dict[int, dict]) -> None:
    events = []
    for note_id, before in befores.items():
        if note_id in _writing:
            continue
        try:
            note = mw.col.get_note(note_id)
        except Exception:  # deleted meanwhile; the deletion is reported on its own
            continue
        after = _snapshot(note)
        if after and after != before:
            info = _describe(note)
            events.append({"kind": "edit", "note_id": note_id, "model": info["model"], "deck": info["deck"], "tags": info["tags"], "before": before, "after": after})
    if events:
        call("event", {"events": events})


def _flush_pending() -> None:
    befores = dict(_pending)
    _pending.clear()
    _report_edits(befores)


def _schedule_flush() -> None:
    global _flush_timer
    from aqt.qt import QTimer

    if _flush_timer is None:
        _flush_timer = QTimer(mw)
        _flush_timer.setSingleShot(True)
        _flush_timer.timeout.connect(_flush_pending)
    _flush_timer.start(EDIT_QUIET_MS)


def _watch_edits(col) -> None:
    """Notice hand edits made through col.update_notes (the Browser, AnkiConnect, other add-ons)."""
    original = col.update_notes

    def update_notes(notes, skip_undo_entry: bool = False):
        try:
            if len(notes) <= BULK:
                for note in notes:
                    if note.id and note.id not in _writing and note.id not in _pending:
                        before = _snapshot(col.get_note(note.id))
                        if before:
                            _pending[note.id] = before
                if _pending:
                    mw.taskman.run_on_main(_schedule_flush)
        except Exception:  # learning is optional; the learner's save must always go through
            pass
        return original(notes, skip_undo_entry=skip_undo_entry)

    col.update_notes = update_notes


def _on_question(card) -> None:
    """The review screen's own editor saves around update_notes, so compare each card when moving on."""
    try:
        previous = dict(_review_snapshot)
        if previous and previous["note_id"] not in _pending:
            _report_edits({previous["note_id"]: previous["before"]})
        note = card.note()
        before = _snapshot(note)
        _review_snapshot.clear()
        if before:
            _review_snapshot.update({"note_id": note.id, "before": before})
    except Exception:  # never get in the way of studying
        pass


def _report_deletions(col, note_ids) -> None:
    try:
        if len(note_ids) > BULK:
            sample = [{"kind": "delete", **_describe(col.get_note(n))} for n in list(note_ids)[:5]]
            events = [{"kind": "bulk-delete", "count": len(note_ids), "sample": sample}]
        else:
            events = [{"kind": "delete", **_describe(col.get_note(n))} for n in note_ids]
    except Exception:  # deletion must never be blocked by reporting
        return
    _review_snapshot.clear()
    for note_id in note_ids:
        _pending.pop(note_id, None)
    if events:
        mw.taskman.run_on_main(lambda: call("event", {"events": events}))


def _shortcuts(state: str, shortcuts: list) -> None:
    if state == "review":
        shortcuts.append(("f", fix_card))


def _context_menu(reviewer, menu: QMenu) -> None:
    menu.addSeparator()
    menu.addAction("AnkiHelper: fix this card  (F)", fix_card)
    menu.addAction("AnkiHelper: optimize this card", optimize_card)
    menu.addAction("AnkiHelper: history of this card", show_history)


def _detached(*args: str) -> None:
    try:
        subprocess.Popen([*_command(), *args], env=_clean_env(), start_new_session=True)
    except FileNotFoundError:
        showWarning(NOT_INSTALLED)


def open_app() -> None:
    _detached("setup", "inbox")


def _toolbar(links: list, toolbar) -> None:
    links.append(toolbar.create_link("ankihelper", "AnkiHelper", open_app, tip="Open AnkiHelper: inbox, preview, settings", id="ankihelper"))


BUTTON_JS = """
(function () {
  if (document.getElementById("ankihelper-button")) return;
  var editCell = document.querySelector("#innertable td.stat");
  if (!editCell) return;
  var button = document.createElement("button");
  button.id = "ankihelper-button";
  button.title = "AnkiHelper: fix this card (F), optimize it, or see its history";
  button.textContent = "✎ AnkiHelper";
  button.onclick = function () { pycmd("ankihelper:menu"); };
  editCell.appendChild(button);
})();
"""


def _add_review_button(_card=None) -> None:
    mw.reviewer.bottom.web.eval(BUTTON_JS)


def _on_question_end() -> None:
    previous = dict(_review_snapshot)
    _review_snapshot.clear()
    if previous and previous["note_id"] not in _pending:
        _report_edits({previous["note_id"]: previous["before"]})
    _flush_pending()


def _question_shown(card) -> None:
    _on_question(card)
    _add_review_button()


def _review_menu() -> None:
    menu = QMenu(mw)
    menu.addAction("Fix this card  (F)", fix_card)
    menu.addAction("✨ Optimize this card", optimize_card)
    menu.addAction("History of this card", show_history)
    menu.exec(QCursor.pos())


def _on_js_message(handled: tuple, message: str, context) -> tuple:
    if message == "ankihelper:menu":
        _review_menu()
        return (True, None)
    return handled


def _menu() -> None:
    menu = QMenu("AnkiHelper", mw)
    for title, handler in (
        ("Fix current card  (F)", fix_card),
        ("Optimize current card", optimize_card),
        ("History of current card", show_history),
        ("Open AnkiHelper", open_app),
        ("Run a batch now", lambda: _detached("batch")),
    ):
        action = QAction(title, mw)
        action.triggered.connect(handler)
        menu.addAction(action)
    mw.form.menuTools.addMenu(menu)


WORK_EVERY_MS = 90_000
"""How often the background rule updates take their next batch of cards while Anki is open."""
_working = False


def _work() -> None:
    global _working
    if _working or not mw.col:
        return
    _working = True

    def finished(_reply) -> None:
        global _working
        _working = False

    call("work", {}, finished)


def _start_worker() -> None:
    from aqt.qt import QTimer

    timer = QTimer(mw)
    timer.timeout.connect(_work)
    timer.start(WORK_EVERY_MS)


gui_hooks.main_window_did_init.append(_menu)
gui_hooks.main_window_did_init.append(_start_worker)
gui_hooks.top_toolbar_did_init_links.append(_toolbar)
gui_hooks.reviewer_did_show_question.append(_question_shown)
gui_hooks.reviewer_will_end.append(lambda: _on_question_end())
gui_hooks.reviewer_did_show_answer.append(_add_review_button)
gui_hooks.webview_did_receive_js_message.append(_on_js_message)
gui_hooks.profile_did_open.append(lambda: _watch_edits(mw.col))
gui_hooks.state_shortcuts_will_change.append(_shortcuts)
gui_hooks.reviewer_will_show_context_menu.append(_context_menu)
hooks.notes_will_be_deleted.append(_report_deletions)
