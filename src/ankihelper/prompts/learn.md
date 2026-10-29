A learner uses an AI to turn their notes into Anki flashcards. Below is what they did to cards while studying in Anki: cards they edited by hand (before and after), cards they deleted, cards they asked the AI to fix, and whole conversations they had with the AI about a card (with the card before and after).

Find PATTERNS that say how they want their cards, and turn each into one short general rule for writing future cards.

Look for MEANING, not surface measurements. "Answers got 20 characters shorter" is weak; "they replace abstract examples with everyday ones from their own work", "they want to write the code themselves, but only a few lines", "they ask why until the card explains the reason, so cards should state the why" are the kind of preferences that matter. Conversations are the richest evidence: read what they objected to, what they asked about, and what they finally accepted.

- A pattern needs at least 3 events behind it. One-off changes about a single card's facts are not patterns.
- Deletions matter: if they keep deleting a kind of card (a group such as "optimized", a Bloom level such as "ah::bloom::create", a strategy such as "cloze", very long answers, trivia about one topic), the rule should say not to write that kind, or to write it differently.
- Edits matter: if they keep shortening answers, rewording questions the same way, adding examples, removing bullets, the rule should say to do that from the start.
- Each rule is one imperative sentence that says what to do, for example "Keep answers to one line; move details into a separate why card." or "Do not write create-level cards."
- Do not repeat a rule the learner already has.
- If there is no clear pattern, return no rules.

The learner's current rules:
{rules}

Events (JSON lines; "kind" is edit, delete, fix, flag or conversation; tags starting with ah:: show how AnkiHelper made the card: ah::group::<group>, ah::bloom::<level>):
{events}

Reply with ONLY a JSON object:

{"rules": [{"rule": "...", "evidence": "one sentence: which events show this, e.g. deleted 5 of 7 optimized apply cards"}]}
