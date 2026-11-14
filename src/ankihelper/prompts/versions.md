A learner is reviewing the Anki cards you made from one of their notes, and wants to see other ways the same knowledge could be asked, so they can pick the version that will stick best.

Propose 3 or 4 alternative VERSIONS of the card below. Each version replaces just this one card, usually with one card (at most 3 when a strategy such as atomic facts needs them), and uses a different strategy. Do not duplicate the other cards the learner already has for this note. Choose the strategies that fit this material best, from these (drawn from Andy Matuschak's "How to write good prompts", Michael Nielsen's "Augmenting long-term memory" and Piotr Wozniak's "Twenty rules of formulating knowledge"):

- Why / explanation: ask why it is true, what problem it solves, what would break without it.
- Application / scenario: give a short realistic situation and ask what to use or do ("A team must audit every API call in their AWS account. Which service?").
- Compare and contrast: ask how it differs from the thing it is most often confused with.
- Reverse: give the description or symptom and ask for the name, command or concept.
- Cloze: one key term hidden in a precise statement, written as a real Anki cloze: {{c1::hidden term}} in "question", extra explanation in "answer" (may be empty). Never inside a fenced code block, never hiding text that contains "::".
- Generate an example: ask the learner to produce an example or instance.
- Atomic facts: one tiny card per fact, each with a context cue, for material that is a list.
- Interview: phrased the way an interviewer would ask it, answered the way a strong candidate would in one or two lines.

Every version still follows the card rules: focused, precise, consistent, tractable but effortful, short answers, context cues, no yes/no questions, no "list all N" questions unless asked, never invent facts. Write in {language}; never translate code or technical terms.

{answer_style}

Every card must make sense on its own, months later, with nothing else in view. When the knowledge is about code (how a method, class, keyword or command behaves), the front shows that code in a fenced code block, the setup only, with nothing that gives the answer away, and the question asks about it ("Given this code, what does `Microwave.new.describe` return?"). Never name a class, method or variable on the front that the front does not show or explain: write the code that defines it. The back gives the answer first, then explains why.

Use Bloom's taxonomy (remember, understand, apply, analyze, evaluate, create) to climb: at least two versions must work at a higher level than the card has now (for example turn a "which service" recall card into an apply scenario or an analyze "what breaks if" card). Label every card with its level in "bloom". Every card still needs one consistent answer.

For each version, write one short sentence on why this strategy could make the card easier to remember or more useful for this learner.

The learner's note:
{entry}

The card to make versions of:
{cards}

The learner's other cards for this note (do not repeat them):
{others}

Reply with ONLY a JSON object, no prose before or after:

{"versions": [{"style": "Application / scenario", "why": "...", "cards": [{"source_id": "<entry id>", "question": "...", "answer": "...", "tags": ["..."], "changed": true, "bloom": "apply"}]}]}
