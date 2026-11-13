A learner pressed the "{move_name}" button on one of their Anki flashcards. Do exactly what this move means for them:

{instruction}

{mode}

{sources}

Results the learner accepted from this move before (follow their style and level of detail):
{examples}

Keep every card good: one focused idea, a precise question with one consistent answer, a context cue in the question, a short answer, no yes/no questions. Every card must make sense on its own, months later, with nothing else in view. When the knowledge is about code (how a method, class, keyword or command behaves), the front shows that code in a fenced code block, the setup only, with nothing that gives the answer away, and the question asks about it ("Given this code, what does `Microwave.new.describe` return?"). Never name a class, method or variable on the front that the front does not show or explain: write the code that defines it. The back gives the answer first, then explains why. Never invent facts. Never translate code or technical terms. Write in {language}. {answer_style}

Format in Markdown, Obsidian style, with a blank line between blocks: paragraphs; "- " and "1. " lists (indent two spaces to nest); **bold**; ==highlight== at most once, for the one phrase to remember; inline `code` for every class, method, scope, column, exception, command and HTTP status (for example `ActiveRecord::RecordNotFound`, `404`); fenced code blocks with a language tag, one block per piece of code, never split line by line; [links](https://...); a small | table | when comparing a few things side by side; "→" to show what leads to what (`User.find(999)` → `ActiveRecord::RecordNotFound`); and callouts, a "> [!info] Title" line followed by "> " lines, which may hold a fenced code block (types: note, info, tip, warning, example, question). No HTML.

What the learner originally wrote, if AnkiHelper made this card:
{original}

The card this one was made from, when Versions or a move made it (go back to it for the context, code and meaning this card came from; the learner may ask about it):
{made_from}

The card:
{card}

What the learner said about this card so far (use it to understand what they want; it may include ideas or snippets they pasted):
{messages}

Reply with ONLY a JSON object:

{"reply": "one short sentence on what you did", "card": {"question": "...", "answer": "...", "bloom": "understand"}, "new_cards": [{"question": "...", "answer": "...", "bloom": "apply"}]}

Include "card" only when told to rewrite the card itself, and "new_cards" only when told to propose new cards. A new card may also carry "screens" when the move asks for them: [{"label": "Now", "html": "<!doctype html>..."}, {"label": "Target", "html": "..."}]. AnkiHelper renders each page to a picture and shows it on the front.
