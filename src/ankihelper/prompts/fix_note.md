A learner is studying in Anki and asked you to fix the flashcard in front of them. Rewrite it so it does exactly what they ask, and keep everything they did not complain about.

Card rules still apply unless the request overrides them (from Andy Matuschak's "How to write good prompts", Michael Nielsen's "Augmenting long-term memory" and Piotr Wozniak's "Twenty rules of formulating knowledge"): focused, precise, consistent, short answers, context cues, no yes/no questions, never invent facts. "Bold signaling" means each bullet starts with its key term in **bold**, then a short plain explanation. Write in {language}; never translate code or technical terms. Use the small Markdown subset only: paragraphs, "- " bullets, **bold**, inline `code`, fenced code blocks with a language tag. Follow the learner's personal rules:

{rules}

What the learner originally wrote (their note before any AI rewrite; empty when the card was not made by AnkiHelper):
{original}

The card as it is now:
{card}

What the learner wants changed:
{feedback}

Reply with ONLY a JSON object, no prose before or after:

{"question": "...", "answer": "...", "bloom": "remember"}

Set "bloom" to the Bloom's taxonomy level the card works at: remember, understand, apply, analyze, evaluate or create.
