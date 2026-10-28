You are improving AnkiHelper, a tool that turns a learner's notes into Anki flashcards. The current directory is a fresh git worktree of its repository on the branch {branch}.

A learner found a rule for writing better cards and wants it built into AnkiHelper for everyone:

{rule}

Do this:
1. Read src/ankihelper/prompts/process.md, the instructions the card-writing agent follows. Integrate the rule where it belongs, in the same style: merge it into an existing rule if one covers the topic, or add a new item. Keep the wording short and general. Do not change anything unrelated.
2. Add an assertion to tests/test_render.py that the key phrase of the rule is in `prompt("process", entries="", language="English", rules="")`.
3. Run `uv run pytest -q` and make sure everything passes.
4. Commit with a short message that says what the rule changes for the learner. Do not add any AI attribution or Co-Authored-By lines.
5. {push_step}

Never touch files outside this worktree. Print a two-line summary at the end; the last line is {last_line}.
