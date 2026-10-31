A learner pressed the "{move_name}" button on one of their Anki flashcards. Do exactly what this move means for them:

{instruction}

{mode}

Results the learner accepted from this move before (follow their style and level of detail):
{examples}

Keep every card good: one focused idea, a precise question with one consistent answer, a context cue in the question, a short answer, no yes/no questions. Never invent facts. Never translate code or technical terms. Write in {language}. Use only the small Markdown subset: paragraphs, "- " bullets, **bold**, inline `code`, fenced code blocks with a language tag.

What the learner originally wrote, if AnkiHelper made this card:
{original}

The card:
{card}

What the learner said about this card so far (use it to understand what they want; it may include ideas or snippets they pasted):
{messages}

Reply with ONLY a JSON object:

{"reply": "one short sentence on what you did", "card": {"question": "...", "answer": "...", "bloom": "understand"}, "new_cards": [{"question": "...", "answer": "...", "bloom": "apply"}]}

Include "card" only when told to rewrite the card itself, and "new_cards" only when told to propose new cards.
