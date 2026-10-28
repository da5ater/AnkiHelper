# AnkiHelper

Make Anki cards while you study without leaving what you're doing. Press a shortcut, dictate a question and an answer, pick a topic, and go back to work. At the end of the session, run a batch: an AI agent (Claude Code, Codex, Gemini CLI or OpenCode) cleans up each card and AnkiHelper imports them into Anki through AnkiConnect. The agent fixes dictation mistakes, wording and code, and corrects wrong answers.

## How it works

Everything lives in one window with four pages (Ctrl+1 to Ctrl+4): Capture, Inbox, Setup and Settings.

1. **Capture.** `Super+Alt+A` runs `ankihelper capture`, which opens the window on the Capture page: Question, Answer and Topic. Dictate with the mic button (it starts and stops Voxtype), your OS dictation, or paste. Ctrl+V or drag-and-drop a picture (a screenshot, an image copied from a browser, or an image file) into Question or Answer. Each thumbnail has a toggle: **🖼 Show** puts the picture on the card as a visual, **📖 Read** means the picture *is* the content (say a quiz question screenshotted from an article) and the agent reads it and writes the card from it. A picture pasted into an empty Question defaults to Read; everything else defaults to Show. Tab moves between fields, Ctrl+Enter saves and closes, Esc closes. Topic autocompletes from the subdecks of your `manual` deck and shows the deck the card will land in. Each card is one line in `~/.local/share/ankihelper/inbox.jsonl`. Run `ankihelper capture --stay` to keep the window open between cards.
2. **Inbox and batch.** The Inbox page lists waiting cards, lets you delete one, and has a **Process batch** button. `Super+Alt+B` runs `ankihelper batch` without opening the window. It opens Anki if needed and sends the inbox to your agent on stdin, 20 entries per call. The agent returns cleaned cards as JSON. It runs without write access: Claude with no tools, Codex in its read-only sandbox, OpenCode with edit, bash and web access denied, and Gemini in default approval mode, which refuses tools that need confirmation. AnkiHelper then renders the cards (code highlighted with Pygments, monokai) and adds them to `manual::<topic>` with the `Basic+` note type, tagged `manual_voice` plus topic tags. Show pictures are uploaded to Anki's media folder and shown under the question or answer; the agent is told they exist but never sees them. Read pictures are handed to the agent as read-only files (Claude gets only its Read tool, Codex and OpenCode get them attached, Gemini gets read access to the media folder), and the original is kept small under "Source" at the bottom of the answer. It syncs to AnkiWeb and sends a notification with the result.
3. **Setup.** `ankihelper setup` opens the window on the Setup page, a checklist: Anki, AnkiConnect, the root deck, the note type, dictation, the CLI on PATH, the agent and the shortcuts. Fix a problem yourself and press **Recheck**, or press **Fix with agent** to let the selected agent fix it headlessly; the window shows its log and rechecks when it finishes. `ankihelper doctor` prints the same checklist in a terminal.
4. **Settings.** Pick the agent (Claude, Codex, Gemini, OpenCode) and the dictation method (Voxtype, system dictation, keyboard only), and set the root deck, note type and AnkiConnect URL. Changes save immediately.

### What the agent does to a card

It treats your dictation as an idea, not a transcript. The question is rewritten to be clear without changing what you asked, and code becomes real code in a fenced block. Answers stay as short as you said them. Say "explain" in a card to get up to three "why" bullets, and "split" to turn it into several atomic cards. When the agent corrects a wrong answer, writes a missing one, or changes the meaning of the question, the card gets the `changed` tag.

### When things fail

- **Anki or AnkiConnect is unreachable.** Nothing is imported, and the notification offers to open setup.
- **The agent fails or returns malformed JSON.** It is retried once. Entries it still can't clean stay in the inbox with the error attached.
- **Anki stops answering mid-batch.** The cards imported so far are saved and removed from the inbox. The rest stay, with their cleaned cards, for the next batch.
- **A second batch is started while one runs.** It is refused.
- **A card is rejected by AnkiConnect.** The agent gets the card and the exact error and repairs it, up to 2 times. Cards that still fail stay in the inbox with the error and the cleaned card attached, so the next batch retries the import without asking the agent to rewrite the card.
- **A card is already in Anki.** It is skipped, so rerunning a batch is safe.

Imported entries move to `~/.local/share/ankihelper/archive/<date>.jsonl`, raw dictation next to the cleaned cards, so an agent can look back at what you originally said.

## Install

Requires [uv](https://docs.astral.sh/uv/), Anki with the [AnkiConnect](https://ankiweb.net/shared/info/2055492159) add-on, and at least one agent CLI.

```bash
git clone https://github.com/da5ater/AnkiHelper.git
cd AnkiHelper
uv tool install --editable .
ankihelper setup
```

Setup tells you what's missing, and "Fix with agent" can install the shortcuts and create the deck or note type for you.

## Configuration

`~/.local/share/ankihelper/config.json` (also editable on the Settings page):

| Key | Default | Meaning |
| --- | --- | --- |
| `agent` | `claude` | `claude`, `codex`, `gemini` or `opencode`. `ankihelper batch --agent codex` overrides it for one run. |
| `dictation` | `voxtype` on Linux, `system` elsewhere | `voxtype`, `system` or `none` |
| `anki_url` | `http://127.0.0.1:8765` | AnkiConnect address |
| `root_deck` | `manual` | Cards go to `<root_deck>::<topic>` |
| `note_type` | `Basic+` | Must have the fields `Front` and `Back` |

## Platforms

Linux (Hyprland) is supported today. macOS and Windows have their own modules in `src/ankihelper/platforms/` for launching Anki, notifications, dictation and shortcuts. They are written but not yet tested.

## Development

```bash
uv sync
uv run pytest
```
