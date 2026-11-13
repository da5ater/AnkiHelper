A learner is reviewing the Anki cards you made from one of their notes and wants ONE card changed.

Rewrite that card so it does exactly what they ask, and keep everything they did not complain about. If they ask for something that needs more than one card (for example "split this"), return up to 3 cards; otherwise return one. Do not repeat the learner's other cards.

Every card must make sense on its own, months later, with nothing else in view. When the knowledge is about code (how a method, class, keyword or command behaves), the front shows that code in a fenced code block, the setup only, with nothing that gives the answer away, and the question asks about it ("Given this code, what does `Microwave.new.describe` return?"). Never name a class, method or variable on the front that the front does not show or explain: write the code that defines it. The back gives the answer first, then explains why.

Card rules still apply unless the learner's request overrides them: focused, precise, consistent, short answers, context cues, no yes/no questions, never invent facts. "Bold signaling" means each bullet starts with its key term in **bold**, then a short plain explanation. Write in {language}; never translate code or technical terms. Format in Markdown, Obsidian style, with a blank line between blocks: paragraphs; "- " and "1. " lists (indent two spaces to nest); **bold**; ==highlight== at most once, for the one phrase to remember; inline `code` for every class, method, scope, column, exception, command and HTTP status (for example `ActiveRecord::RecordNotFound`, `404`); fenced code blocks with a language tag, one block per piece of code, never split line by line; [links](https://...); a small | table | when comparing a few things side by side; "→" to show what leads to what (`User.find(999)` → `ActiveRecord::RecordNotFound`); and callouts, a "> [!info] Title" line followed by "> " lines, which may hold a fenced code block (types: note, info, tip, warning, example, question). No HTML.

The learner's note:
{entry}

The card to change:
{card}

What the learner wants changed:
{feedback}

The learner's other cards for this note:
{others}

Reply with ONLY a JSON object, no prose before or after:

{"cards": [{"source_id": "<entry id>", "question": "...", "answer": "...", "tags": ["..."], "changed": true, "bloom": "remember"}]}

Set "bloom" to the Bloom's taxonomy level the card works at: remember, understand, apply, analyze, evaluate or create.
