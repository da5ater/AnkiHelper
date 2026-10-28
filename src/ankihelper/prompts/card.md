A learner is reviewing the Anki cards you made from one of their notes and wants ONE card changed.

Rewrite that card so it does exactly what they ask, and keep everything they did not complain about. If they ask for something that needs more than one card (for example "split this"), return up to 3 cards; otherwise return one. Do not repeat the learner's other cards.

Card rules still apply unless the learner's request overrides them: focused, precise, consistent, short answers, context cues, no yes/no questions, never invent facts. "Bold signaling" means each bullet starts with its key term in **bold**, then a short plain explanation. Write in {language}; never translate code or technical terms. Use the small Markdown subset only: paragraphs, "- " bullets, **bold**, inline `code`, fenced code blocks. Follow the learner's personal rules:

{rules}

The learner's note:
{entry}

The card to change:
{card}

What the learner wants changed:
{feedback}

The learner's other cards for this note:
{others}

Reply with ONLY a JSON object, no prose before or after:

{"cards": [{"source_id": "<entry id>", "question": "...", "answer": "...", "tags": ["..."], "changed": true}]}
