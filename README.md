# AnkiHelper

Make Anki cards while you study without leaving what you're doing. Press a shortcut, dictate a question and an answer, pick a topic, and go back to work. At the end of the session, run a batch: an AI agent (Claude Code, Codex, Gemini CLI or OpenCode) cleans up each card and AnkiHelper imports them into Anki through AnkiConnect. The agent fixes dictation mistakes, wording and code, and corrects wrong answers.

## How it works

Everything lives in one window with four pages (Ctrl+1 to Ctrl+4): Capture, Inbox (with Preview), Setup and Settings.

1. **Capture.** `Super+Alt+A` runs `ankihelper capture`, which opens the window on the Capture page: Question, Answer and Topic. Dictate with the mic button (it starts and stops Voxtype), your OS dictation, or paste. Ctrl+V or drag-and-drop a picture (a screenshot, an image copied from a browser, or an image file) into Question or Answer. Each thumbnail has a toggle: **🖼 Show** puts the picture on the card as a visual, **📖 Read** means the picture *is* the content (say a quiz question screenshotted from an article) and the agent reads it and writes the card from it. A picture pasted into an empty Question defaults to Read; everything else defaults to Show. Tab moves between fields, Ctrl+Enter saves and closes, Esc closes. Topic autocompletes from the subdecks of your `manual` deck and shows the deck the card will land in. Each card is one line in `~/.local/share/ankihelper/inbox.jsonl`. Run `ankihelper capture --stay` to keep the window open between cards.
2. **Inbox and batch.** The Inbox page lists waiting cards, lets you delete one, and has a **Process batch** button. `Super+Alt+B` runs `ankihelper batch` without opening the window. It opens Anki if needed and sends the inbox to your agent on stdin, 20 entries per call. The agent returns cleaned cards as JSON. It runs without write access: Claude with no tools, Codex in its read-only sandbox, OpenCode with edit, bash and web access denied, and Gemini in default approval mode, which refuses tools that need confirmation. AnkiHelper then renders the cards (code highlighted with Pygments, monokai) and adds them to `manual::<topic>` with the `Basic+` note type, tagged `manual_voice` plus topic tags. Show pictures are uploaded to Anki's media folder and shown under the question or answer; the agent is told they exist but never sees them. Read pictures are handed to the agent as read-only files (Claude gets only its Read tool, Codex and OpenCode get them attached, Gemini gets read access to the media folder), and the original is kept small under "Source" at the bottom of the answer. It syncs to AnkiWeb and sends a notification with the result.
3. **Preview canvas.** Every Inbox card has a **👁 Preview** button. It opens a scrollable canvas: your note at the top, and each card the agent writes hanging off it as its own node with a clear **FRONT** and **BACK**. On each card:
   - **✓ Accept** marks it good, **✕ Remove** leaves it out (with Undo).
   - **✎ Change** rewrites just that card from your instruction ("add bold signaling and why for each one").
   - **✨ Versions** hangs 3 or 4 alternative versions off that card, each using a different strategy from Matuschak, Nielsen and SuperMemo (scenario, compare and contrast, reverse, cloze, generate an example, atomic facts, interview) with one line on why it may stick better. **Use instead** swaps the card and keeps the other versions (your old card becomes an *Original* version with **Switch back**), **Add as new card** keeps both and marks that version as added, so you can keep comparing.
   - **↻ Redo all** on your note regenerates every card from one piece of feedback.

   Reopening Preview shows the cards you saved instead of writing new ones. Only accepted cards are saved: **Accept all** accepts every card you haven't removed, **Save N** locks in the accepted cards so the batch imports exactly those and takes you back to the Inbox, and **Import** sends them to Anki immediately. **Make this a rule** turns what you asked for into one general rule you can edit. **Save rule** adds it to your personal rules (`~/.local/share/ankihelper/rules.md`, editable in Settings), which every future card follows. **Save + propose as PR** also has your agent build the rule into AnkiHelper's own instructions in a separate git worktree, run the tests, and open a pull request on this repo as the `github_account` in config (default `da5ater`), using that account's `gh` token without changing your active `gh` login.
4. **Setup.** `ankihelper setup` opens the window on the Setup page, a checklist: Anki, AnkiConnect, the root deck, the note type, dictation, the CLI on PATH, the agent and the shortcuts. Fix a problem yourself and press **Recheck**, or press **Fix with agent** to let the selected agent fix it headlessly; the window shows its log and rechecks when it finishes. `ankihelper doctor` prints the same checklist in a terminal.
5. **Settings.** Pick the agent (Claude, Codex, Gemini, OpenCode) and the dictation method (Voxtype, system dictation, keyboard only), and set the root deck, note type and AnkiConnect URL. Changes save immediately.

### What the agent does to a card

You give it a seed, not a finished card. The agent first decides what kind of entry it is:

- **A note** is already one clear question ("how do I generate a Home controller with one action?"). The agent keeps your question, fixes dictation mistakes, wording and code, and corrects a wrong answer. You get one card.
- **A seed** is a topic or heading plus the material: a pasted paragraph, a list, a screenshot. The agent *questionizes* it, writing the questions a good teacher would put on the exam. It follows Andy Matuschak's [How to write good prompts](https://andymatuschak.org/prompts/), Michael Nielsen's [Augmenting long-term memory](http://augmentingcognition.com/ltm.html) and Piotr Wozniak's [Twenty rules of formulating knowledge](https://www.supermemo.com/en/blog/twenty-rules-of-formulating-knowledge). Each card asks for one thing and has one consistent answer, with the context in the question. A list always becomes one card per item instead of "list all six" (unless you ask for one card), and "why" and "what problem does it solve" questions win over trivia. Every card is labelled with its [Bloom's taxonomy](https://poorvucenter.yale.edu/teaching/teaching-resource-library/blooms-taxonomy) level (remember, understand, apply, analyze, evaluate, create) and tagged `bloom-<level>` in Anki; seeds get understand and apply cards on top of recall, and ✨ Versions deliberately climb to higher levels. A seed makes at most 8 cards, all sharing a `seed-<id>` tag.

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

## The Anki add-on

AnkiHelper also lives inside Anki, so you can fix cards at the moment you meet them while studying, and every fix teaches it.

- **✎ AnkiHelper** on the review screen, next to Anki's Edit button, opens a menu: fix this card now, fix it in the next batch, or see its history. **AnkiHelper** in Anki's top bar opens the app.
- **F** on the review screen opens "What should change in this card?". **Fix now** rewrites the card in place in about 10 seconds (Edit → Undo brings the old one back). **Shift+F**, or **Fix in next batch**, flags the card red and the next `ankihelper batch` rewrites it, so you keep studying. Both work on any card with a question and an answer field, not only the ones AnkiHelper made; cloze cards are not supported yet.
- **✨ Optimize this card** (in the ✎ AnkiHelper menu) sends a card you already have to AnkiHelper's Preview canvas: a cleaned version plus atomic and higher-level cards and versions, exactly as for a new note. Accepted cards are added next to the original in its own deck; tick **Replace the original card** to rewrite the original in place instead, which keeps its review history.
- **History of this card** (right-click on the review screen, or Tools → AnkiHelper) shows your original note and pictures, the other cards made from the same note, and the versions you were offered in Preview, with **Use this version** to switch.
- **It learns from what you do.** The add-on quietly records cards you edit by hand and cards you delete, across your whole collection. Every 10 events, and at the end of each batch, the agent looks for patterns ("deleted 5 of 7 create-level cards", "always shortens answers") and suggests a rule. Suggestions appear in Settings under Personal rules, where you add or dismiss them. Nothing becomes a rule without your OK.

### Applying a rule to cards you already have

Settings → **Rule updates** applies one of your rules to existing cards: the cards AnkiHelper made, everything in your root deck, or all cards. It runs in the background while Anki is open (the add-on takes one batch every 90 seconds), 10 cards per agent call, so the agent judges each card on its own instead of juggling hundreds. Only cards the rule actually applies to change, each change is backed up first, progress is saved after every batch so it resumes exactly where it stopped, and **Undo all** puts every card back. Changed cards are tagged `ah::rule::<job>`.

When you meet an updated card in Anki and push back with **F** ("no, for commands I need the full command, because…"), AnkiHelper rewords the rule from your reasoning, keeps going with the new wording, and rechecks the cards it already changed.

### Card groups and tags

Every card AnkiHelper makes is tagged so a whole note's cards stay findable together in Anki's browser:

| Tag | Meaning |
| --- | --- |
| `ah::seed::<id>` | All cards made from one note |
| `ah::group::main` | Your own question, cleaned up |
| `ah::group::atomic` | A list split into one card per item, plus one for the whole list. Not counted toward the cap |
| `ah::group::optimized` | Extra higher-level cards (at most 6 per note) |
| `ah::group::<strategy>` | A version you picked in Preview (scenario, reverse, ...) |
| `ah::bloom::<level>` | Bloom's taxonomy level |
| `ah::fixed` | Rewritten from your feedback in Anki |
| `ah::rule::<job>` | Updated by a rule applied to existing cards |

## Install

Requires [uv](https://docs.astral.sh/uv/), Anki with the [AnkiConnect](https://ankiweb.net/shared/info/2055492159) add-on, and at least one agent CLI.

```bash
git clone https://github.com/da5ater/AnkiHelper.git
cd AnkiHelper
uv tool install --editable .
ankihelper install-addon
ankihelper setup
```

`ankihelper install-addon` links the add-on into Anki's add-ons folder (`~/.local/share/Anki2/addons21/ankihelper` on Linux; it copies on Windows) and records where the `ankihelper` command lives, since Anki starts without your shell's PATH. Restart Anki afterwards; Tools → AnkiHelper confirms it loaded. Setup checks for it too, and tells you what else is missing; "Fix with agent" can install the shortcuts and create the deck or note type for you.

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
