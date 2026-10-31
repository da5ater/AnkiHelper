# AnkiHelper

Make Anki cards while you study without leaving what you're doing. Press a shortcut, dictate a question and an answer, pick a topic, and go back to work. At the end of the session, run a batch: an AI agent (Claude Code, Codex, Gemini CLI or OpenCode) cleans up each card and AnkiHelper imports them into Anki through AnkiConnect. The agent fixes dictation mistakes, wording and code, and corrects wrong answers.

## How it works

Everything lives in one window with four pages (Ctrl+1 to Ctrl+4): Capture, Inbox (with Preview), Setup and Settings.

1. **Capture.** `Super+Alt+A` runs `ankihelper capture`, which opens the window on the Capture page: Question, Answer and Topic. Dictate with the mic button (it starts and stops Voxtype), your OS dictation, or paste. Ctrl+V or drag-and-drop a picture (a screenshot, an image copied from a browser, or an image file) into Question or Answer. Each thumbnail has a toggle: **🖼 Show** puts the picture on the card as a visual, **📖 Read** means the picture *is* the content (say a quiz question screenshotted from an article) and the agent reads it and writes the card from it. A picture pasted into an empty Question defaults to Read; everything else defaults to Show. Tab moves between fields, Ctrl+Enter saves and closes, Esc closes. Topic autocompletes from the subdecks of your `manual` deck and shows the deck the card will land in. Each card is one line in `~/.local/share/ankihelper/inbox.jsonl`. Run `ankihelper capture --stay` to keep the window open between cards.
2. **Inbox and batch.** The Inbox page lists waiting cards, each with **👁 Preview** and **🗑 Remove** (Undo brings a removed entry back; Preview has the same Remove), and has a **Process batch** button. `Super+Alt+B` runs `ankihelper batch` without opening the window. It opens Anki if needed and sends the inbox to your agent on stdin, 20 entries per call. The agent returns cleaned cards as JSON. It runs without write access: Claude with no tools, Codex in its read-only sandbox, OpenCode with edit, bash and web access denied, and Gemini in default approval mode, which refuses tools that need confirmation. AnkiHelper then renders the cards (code highlighted with Pygments, monokai) and adds them to `manual::<topic>` with the `Basic+` note type, tagged `manual_voice` plus topic tags. Show pictures are uploaded to Anki's media folder and shown under the question or answer; the agent is told they exist but never sees them. Read pictures are handed to the agent as read-only files (Claude gets only its Read tool, Codex and OpenCode get them attached, Gemini gets read access to the media folder), and the original is kept small under "Source" at the bottom of the answer. It syncs to AnkiWeb and sends a notification with the result.
3. **Preview canvas.** Every Inbox card has a **👁 Preview** button. It opens a scrollable canvas: your note at the top, and each card the agent writes hanging off it as its own node with a clear **FRONT** and **BACK**. On each card:
   - **✓ Accept** marks it good, **✕ Remove** leaves it out (with Undo).
   - **Moves**: your three most used moves are one click away, the rest are under **More ▾** (see *Moves* below). **✎ Change it in my own words…** in that menu rewrites just that card from your instruction ("add bold signaling and why for each one").
   - **✨ Versions** (a built-in move) hangs 3 or 4 alternative versions off that card, each using a different strategy from Matuschak, Nielsen and SuperMemo (scenario, compare and contrast, reverse, cloze, generate an example, atomic facts, interview) with one line on why it may stick better. **Use instead** swaps the card and keeps the other versions (your old card becomes an *Original* version with **Switch back**), **Add as new card** keeps both and marks that version as added, so you can keep comparing.
   - **↻ Redo all** on your note regenerates every card from one piece of feedback.

   Reopening Preview shows the cards you saved instead of writing new ones. Only accepted cards are saved: **Accept all** accepts every card you haven't removed, **Save N** locks in the accepted cards so the batch imports exactly those and takes you back to the Inbox, and **Import** sends them to Anki immediately.
4. **Setup.** `ankihelper setup` opens the window on the Setup page, a checklist: Anki, AnkiConnect, the root deck, the note type, dictation, the CLI on PATH, the agent and the shortcuts. Fix a problem yourself and press **Recheck**, or press **Fix with agent** to let the selected agent fix it headlessly; the window shows its log and rechecks when it finishes. `ankihelper doctor` prints the same checklist in a terminal.
5. **Moves.** The Moves page lists every move, most used first, with how often you used it, its instruction (edit and **Save instruction**), the last results you kept, **↶ Undo last change**, and **🗑 Delete** for moves you made. Suggested moves appear at the top.
6. **Settings.** Pick the agent (Claude, Codex, Gemini, OpenCode), the dictation method (Voxtype, system dictation, keyboard only) and the card language, and set the root deck, note type and AnkiConnect URL. Changes save immediately.

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

AnkiHelper also lives inside Anki, so you can work on a card at the moment you meet it while studying.

- **✎ AnkiHelper** on the review screen, next to Anki's Edit button, opens a menu: talk about and fix this card, optimize it, or see its history. **AnkiHelper** in Anki's top bar opens the app.
- **F** on the review screen opens a window next to the card you're studying, with the card on top and a chat below. It works on the card only: your top three moves are one click away (the rest under **More ▾**), or just type what you want changed. The message box takes several lines (Enter for a new line, Ctrl+Enter to send) and pasted or dropped pictures, ideas or snippets, which the agent reads. New cards appear right in the chat, each with **＋ Add to Anki** (added at once to the same deck). **⭐ Save as move** has the agent read the whole conversation and draft a move (name, icon, whether it changes the card or adds new ones, and the instruction) for you to edit and save. After you correct a move's result, **🎓 Teach the move this?** shows the old and new instruction for your OK. **OK, keep this card** saves the latest version (Edit → Undo brings the old one back); **Close** leaves the card as it was. It works on any card with exactly two fields (a question and an answer); cloze and image occlusion cards are never rewritten.
- **✨ Optimize this card** (in the ✎ AnkiHelper menu) sends a card you already have to AnkiHelper's Preview canvas: a cleaned version plus atomic and higher-level cards and versions, exactly as for a new note. Accepted cards are added next to the original in its own deck; tick **Replace the original card** to rewrite the original in place instead, which keeps its review history.
- **History of this card** (✎ AnkiHelper menu, right-click on the review screen, or Tools → AnkiHelper) works for any card: it lists every change, newest first, your conversations (what you said), fixes, and your own edits, each with before and after, and **↩ Restore** for changes AnkiHelper made. For cards AnkiHelper created it also shows your original note and pictures, the other cards made from the same note, and the versions you were offered in Preview, with **Use this version** to switch.

### Moves

A move is a one-click thing you keep doing to a card. Five come built in: **✍ Word it better** (changes the card), and **🎬 Make it a scenario**, **⌨ Make me write it**, **✂ Split this** and **✨ Versions** (these add new cards next to the original). You always see the result and decide; nothing runs on many cards at once.

- Each move remembers the last 3 results you kept and shows them to the agent as examples, so it stays consistent with your taste.
- Make your own with **⭐ Save as move** in the F window, or teach an existing one with **🎓 Teach the move this?** after you correct its result. Every change to a move can be undone on the Moves page.
- Once a day, when you've had at least 3 conversations about cards, the agent reads them in the background and suggests moves for requests you keep making. Suggestions wait at the top of the Moves page, with no popups; add or dismiss them there.

### Card groups and tags

Every card AnkiHelper makes is tagged so a whole note's cards stay findable together in Anki's browser:

| Tag | Meaning |
| --- | --- |
| `ah::seed::<id>` | All cards made from one note |
| `ah::group::main` | Your own question, cleaned up |
| `ah::group::atomic` | A list split into one card per item, plus one for the whole list. Not counted toward the cap |
| `ah::group::optimized` | Extra higher-level cards (at most 6 per note) |
| `ah::group::<strategy or move>` | A version or a move's card you picked (scenario, reverse, ...) |
| `ah::bloom::<level>` | Bloom's taxonomy level |
| `ah::fixed` | Rewritten from your feedback in Anki |

## Install

Requires [uv](https://docs.astral.sh/uv/), Anki with the [AnkiConnect](https://ankiweb.net/shared/info/2055492159) add-on, and at least one agent CLI.

```bash
git clone https://github.com/da5ater/AnkiHelper.git
cd AnkiHelper
uv tool install --editable .
ankihelper install-addon
ankihelper setup
```

The add-on is also on AnkiWeb: [ankiweb.net/shared/info/1704420850](https://ankiweb.net/shared/info/1704420850). In Anki, Tools → Add-ons → Get Add-ons, code `1704420850`. Install it from there **or** with `ankihelper install-addon`, not both.

`ankihelper install-addon` links the add-on into Anki's add-ons folder (`~/.local/share/Anki2/addons21/ankihelper` on Linux; it copies on Windows) and records where the `ankihelper` command lives, since Anki starts without your shell's PATH. Restart Anki afterwards; Tools → AnkiHelper confirms it loaded. Setup checks for it too, and tells you what else is missing; "Fix with agent" can install the shortcuts and create the deck or note type for you.

## Configuration

`~/.local/share/ankihelper/config.json` (also editable on the Settings page):

| Key | Default | Meaning |
| --- | --- | --- |
| `agent` | `claude` | `claude`, `codex`, `gemini` or `opencode`. `ankihelper batch --agent codex` overrides it for one run. |
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
