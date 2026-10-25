# AnkiHelper

Make Anki cards while you study without leaving what you're doing. Press a shortcut, dictate a question and an answer, pick a topic, and go back to work. At the end of the session, run a batch: an AI agent (Claude Code, Codex, Gemini CLI or OpenCode) cleans up each card and AnkiHelper imports them into Anki through AnkiConnect. The agent fixes dictation mistakes, wording and code, and corrects wrong answers.

## How it works

1. **Capture.** `Super+Alt+A` runs `ankihelper capture`, a small window with Question, Answer and Topic. Dictate with any speech-to-text tool (Voxtype on Linux) or paste. Tab moves between fields, Ctrl+Enter saves, Esc cancels. Topic autocompletes from the subdecks of your `manual` deck. Each card is one line in `~/.local/share/ankihelper/inbox.jsonl`.
2. **Batch.** `Super+Alt+B` runs `ankihelper batch`. It opens Anki if needed and sends the inbox to your agent as text. The agent returns cleaned cards as JSON and has no tools, so it can't touch your files or collection. AnkiHelper then renders the cards (code highlighted with Pygments, monokai) and adds them to `manual::<topic>` with the `Basic+` note type, tagged `manual_voice` plus topic tags. It syncs to AnkiWeb and sends a notification with the result.
3. **Setup.** `ankihelper setup` opens a checklist: Anki, AnkiConnect, the root deck, the note type, dictation, the CLI on PATH, the agent and the shortcuts. Fix a problem yourself and press **Recheck**, or press **Fix with agent** to let the selected agent fix it headlessly; the window shows its log and rechecks when it finishes. `ankihelper doctor` prints the same checklist in a terminal.

### What the agent does to a card

It treats your dictation as an idea, not a transcript. The question is rewritten to be clear without changing what you asked, and code becomes real code in a fenced block. Answers stay as short as you said them. Say "explain" in a card to get up to three "why" bullets, and "split" to turn it into several atomic cards. When the agent corrects a wrong answer, writes a missing one, or changes the meaning of the question, the card gets the `changed` tag.

### When things fail

- **Anki or AnkiConnect is unreachable.** Nothing is imported, and the notification offers to open setup.
- **The agent fails or returns malformed JSON.** It is retried once, then nothing is imported and the inbox is left untouched.
- **A card is rejected by AnkiConnect.** The agent gets the card and the exact error and repairs it, up to 2 times. Cards that still fail stay in the inbox with the error attached.
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

`~/.local/share/ankihelper/config.json`:

| Key | Default | Meaning |
| --- | --- | --- |
| `agent` | `claude` | `claude`, `codex`, `gemini` or `opencode`. `ankihelper batch --agent codex` overrides it for one run. |
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
