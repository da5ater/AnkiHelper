A learner added a rule for how their Anki flashcards should be written. Apply it to their existing cards below, one card at a time.

The rule:
{rule}

For EACH card decide on its own:
- If the rule does not apply to this card, or the card already follows it, leave it alone: "changed": false.
- If it applies, rewrite the card so it follows the rule, changing nothing else. Keep the facts, the meaning of the question and the answer, and everything the rule does not mention.

Never invent facts. Never translate code or technical terms. Write in {language} only if the card is already in it; otherwise keep the card's language. Use the small Markdown subset only: paragraphs, "- " bullets, **bold**, inline `code`, fenced code blocks with a language tag.

The learner's other rules (keep following them):
{rules}

Cards (JSON lines):
{cards}

Reply with ONLY a JSON object with one entry per card, in the same order:

{"cards": [{"note_id": 123, "changed": false}, {"note_id": 456, "changed": true, "question": "...", "answer": "..."}]}
