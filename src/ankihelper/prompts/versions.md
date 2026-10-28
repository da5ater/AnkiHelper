A learner is reviewing the Anki cards you made from one of their notes, and wants to see other ways the same knowledge could be asked, so they can pick the version that will stick best.

Propose 3 or 4 alternative VERSIONS. Each version is a complete replacement for the current cards (one card, or a small set of at most 8 for a seed) and uses a different strategy. Choose the strategies that fit this material best, from these (drawn from Andy Matuschak's "How to write good prompts", Michael Nielsen's "Augmenting long-term memory" and Piotr Wozniak's "Twenty rules of formulating knowledge"):

- Why / explanation: ask why it is true, what problem it solves, what would break without it.
- Application / scenario: give a short realistic situation and ask what to use or do ("A team must audit every API call in their AWS account. Which service?").
- Compare and contrast: ask how it differs from the thing it is most often confused with.
- Reverse: give the description or symptom and ask for the name, command or concept.
- Cloze: one key term blanked out of a precise statement, as "... [...] ...".
- Generate an example: ask the learner to produce an example or instance.
- Atomic facts: one tiny card per fact, each with a context cue, for material that is a list.
- Interview: phrased the way an interviewer would ask it, answered the way a strong candidate would in one or two lines.

Every version still follows the card rules: focused, precise, consistent, tractable but effortful, short answers, context cues, no yes/no questions, no "list all N" questions unless asked, never invent facts. Write in {language}; never translate code or technical terms. Follow the learner's personal rules:

{rules}

For each version, write one short sentence on why this strategy could make the card easier to remember or more useful for this learner.

The learner's note:
{entry}

The current cards:
{cards}

Reply with ONLY a JSON object, no prose before or after:

{"versions": [{"style": "Application / scenario", "why": "...", "cards": [{"source_id": "<entry id>", "question": "...", "answer": "...", "tags": ["..."], "changed": true}]}]}
