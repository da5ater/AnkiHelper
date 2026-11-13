An Anki flashcard failed to import. Fix the card so the import succeeds, keeping its meaning.

The card is a JSON object whose "question" and "answer" use Obsidian-style Markdown (paragraphs, "- " and "1. " lists, **bold**, ==highlight==, inline `code`, fenced code blocks, links, | tables |, "> [!type] Title" callouts). It is rendered to HTML and sent to AnkiConnect's addNote as the Front and Back fields.

Card:
{card}

AnkiConnect error:
{error}

Reply with ONLY the corrected card as a JSON object with the same keys (source_id, question, answer, tags, changed). Tags must be lowercase with no spaces. No prose before or after.
