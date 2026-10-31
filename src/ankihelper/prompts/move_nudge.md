A learner works on their Anki flashcards by talking to an AI about one card at a time. Below are their recent conversations. Find requests they keep making that are not yet one of their one-click "moves", and suggest those as new moves.

Read each conversation as a whole: what they asked for, what they rejected, what they pasted, what they finally accepted. Look for the same specific intent in at least 3 conversations (for example "show me the exact input and output and make me write the line"), not one-off requests about a single card's facts.

Moves they already have:
{moves}

Recent conversations (JSON, one per block):
{conversations}

For each suggestion:
- "name": 2 to 5 words, in the learner's own terms.
- "icon": one emoji.
- "mode": "change" if it rewrites the card itself, "add" if it proposes new cards next to it.
- "instruction": 1 to 3 sentences telling an AI exactly what to do to any card, with the specifics the learner insisted on.
- "evidence": one sentence on which conversations show it.

Suggest at most 3. If nothing repeats clearly, suggest none.

Reply with ONLY a JSON object: {"moves": [{"name": "...", "icon": "...", "mode": "add", "instruction": "...", "evidence": "..."}]}
