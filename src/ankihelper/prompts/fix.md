You are fixing the setup of AnkiHelper on this computer ({os}). AnkiHelper lets the user dictate Anki flashcards; it needs the things below to work. Some checks failed. Fix each failed check, then verify it yourself by running the check's command or an equivalent.

Failed checks:

{failures}

Context:
- AnkiHelper is installed from {project}. Its CLI is `ankihelper` (subcommands: capture, batch, setup, doctor). `ankihelper doctor` prints every check as PASS/FAIL; run it at the end to confirm.
- Anki's add-ons live in the Anki data folder (Linux: ~/.local/share/Anki2/addons21). AnkiConnect's add-on code is 2055492159; it can be installed by downloading https://ankiweb.net/shared/download/2055492159?v=2.1&p=2.1 into that folder, then restarting Anki.
- AnkiConnect listens on {anki_url} while Anki is open. You may use it to create decks or the note type.
- Cards go into the deck "{root_deck}" (and its subdecks) with the note type "{note_type}", which must have exactly the fields Front and Back.

Hard rules:
- Never modify, delete, move or reschedule existing Anki notes, cards, decks or the collection file. Creating a missing deck or note type is allowed.
- Never delete user files. Back up any config file before editing it (copy to <file>.bak.<timestamp>).
- Only change what a failed check needs.
- When done, print a short summary of what you changed and the final `ankihelper doctor` output.
