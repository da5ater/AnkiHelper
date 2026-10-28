# AnkiHelper

Make Anki cards while you study without leaving what you're doing. Press a shortcut, dictate a question and an answer, pick a topic, and go back to work. At the end of the session, run a batch: an AI agent (Claude Code, Codex, Gemini CLI or OpenCode) cleans up each card and AnkiHelper imports them into Anki through AnkiConnect. The agent fixes dictation mistakes, wording and code, and corrects wrong answers.

## How it works

Everything lives in one window with four pages (Ctrl+1 to Ctrl+4): Capture, Inbox (with Preview), Setup and Settings.

1. **Capture.** `Super+Alt+A` runs `ankihelper capture`, which opens the window on the Capture page: Question, Answer and Topic. Dictate with the mic button (it starts and stops Voxtype), your OS dictation, or paste. Ctrl+V or drag-and-drop a picture (a screenshot, an image copied from a browser, or an image file) into Question or Answer. Each thumbnail has a toggle: **🖼 Show** puts the picture on the card as a visual, **📖 Read** means the picture *is* the content (say a quiz question screenshotted from an article) and the agent reads it and writes the card from it. A picture pasted into an empty Question defaults to Read; everything else defaults to Show. Tab moves between fields, Ctrl+Enter saves and closes, Esc closes. Topic autocompletes from the subdecks of your `manual` deck and shows the deck the card will land in. Each card is one line in `~/.local/share/ankihelper/inbox.jsonl`. Run `ankihelper capture --stay` to keep the window open between cards.
2. **Inbox and batch.** The Inbox page lists waiting cards, lets you delete one, and has a **Process batch** button. `Super+Alt+B` runs `ankihelper batch` without opening the window. It opens Anki if needed and sends the inbox to your agent on stdin, 20 entries per call. The agent returns cleaned cards as JSON. It runs without write access: Claude with no tools, Codex in its read-only sandbox, OpenCode with edit, bash and web access denied, and Gemini in default approval mode, which refuses tools that need confirmation. AnkiHelper then renders the cards (code highlighted with Pygments, monokai) and adds them to `manual::<topic>` with the `Basic+` note type, tagged `manual_voice` plus topic tags. Show pictures are uploaded to Anki's media folder and shown under the question or answer; the agent is told they exist but never sees them. Read pictures are handed to the agent as read-only files (Claude gets only its Read tool, Codex and OpenCode get them attached, Gemini gets read access to the media folder), and the original is kept small under "Source" at the bottom of the answer. It syncs to AnkiWeb and sends a notification with the result.
3. **Preview and feedback.** Every Inbox card has a **👁 Preview** button that shows the cards the agent would make, rendered like Anki. Type what should change ("ask why, not what") and press **Redo with feedback** as many times as you like. **✨ Other versions** shows 3 or 4 other ways to ask the same knowledge, each using a different strategy from the same sources (a scenario, compare and contrast, reverse, cloze, generate an example, atomic facts, interview) with one line on why it may stick better. Pick **Use this version** to replace your cards or **Add to my cards** to keep both. **Keep these cards** locks them in so the batch imports exactly those, and **Import now** sends them to Anki immediately. After a redo, **Make this a rule** turns your feedback into one general rule you can edit. **Save rule** adds it to your personal rules (`~/.local/share/ankihelper/rules.md`, editable in Settings), which every future card follows. **Save + propose as PR** also has your agent build the rule into AnkiHelper's own instructions in a separate git worktree, run the tests, and open a pull request on this repo. The PR is pushed and opened as the `github_account` in config (default `da5ater`) using that account's `gh` token, without changing your active `gh` login.
4. **Setup.** `ankihelper setup` opens the window on the Setup page, a checklist: Anki, AnkiConnect, the root deck, the note type, dictation, the CLI on PATH, the agent and the shortcuts. Fix a problem yourself and press **Recheck**, or press **Fix with agent** to let the selected agent fix it headlessly; the window shows its log and rechecks when it finishes. `ankihelper doctor` prints the same checklist in a terminal.
5. **Settings.** Pick the agent (Claude, Codex, Gemini, OpenCode) and the dictation method (Voxtype, system dictation, keyboard only), and set the root deck, note type and AnkiConnect URL. Changes save immediately.

### What the agent does to a card

You give it a seed, not a finished card. The agent first decides what kind of entry it is:

- **A note** is already one clear question ("how do I generate a Home controller with one action?"). The agent keeps your question, fixes dictation mistakes, wording and code, and corrects a wrong answer. You get one card.
- **A seed** is a topic or heading plus the material: a pasted paragraph, a list, a screenshot. The agent *questionizes* it, writing the questions a good teacher would put on the exam. It follows Andy Matuschak's [How to write good prompts](https://andymatuschak.org/prompts/), Michael Nielsen's [Augmenting long-term memory](http://augmentingcognition.com/ltm.html) and Piotr Wozniak's [Twenty rules of formulating knowledge](https://www.supermemo.com/en/blog/twenty-rules-of-formulating-knowledge). Each card asks for one thing and has one consistent answer, with the context in the question. A list becomes one card per item instead of "list all six", and "why" and "what problem does it solve" questions win over trivia. A seed makes at most 8 cards, all sharing a `seed-<id>` tag.

Cards are written in the **card language** (Settings, default English) whatever language you dictated or pasted in. The Capture page can override it for one card. Code, commands and technical terms are never translated.

You can also talk to the agent inside a field. Write "generate" (or "answer this", "I don't know, give an example") as the answer and it writes the answer for you; instructions are followed, never copied onto the card. An empty answer works the same way. Your instructions beat the agent's defaults: paste a screenshot of bullet points as 📖 Read and write "use these bullets, bold signaling, explain each briefly like in an interview", and you get one card with that list, each key term in bold and a one-line explanation, instead of one card per bullet.

Answers stay short. Say "explain" in a card to get up to three "why" bullets. When the agent corrects a wrong answer, writes a missing one, changes the meaning of the question, or questionizes a seed, the card gets the `changed` tag.

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
| `github_account` | `da5ater` | gh account that pushes and opens PRs for proposed rules |
| `language` | `English` | Language cards are written in; Capture can override it per card |
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
