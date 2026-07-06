# CLAUDE.md — how to work in this repo

This is a small, spartan Python scraper: it pulls Italian poll data from an
archive, has an LLM turn each poll's text into party percentages, and keeps a
CSV + a moving-average plot up to date via a daily GitHub Action. That's it.

Match the code that's already here. It is deliberately plain, and changes
should stay plain. When in doubt, prefer the smallest edit that works over the
"correct" or "robust" one.

## Philosophy

- **Simple, spartan Python.** Plain functions, lists and dicts. No classes,
  dataclasses, type-heavy signatures, config layers, or frameworks unless the
  task genuinely cannot be done without them. The existing files leave debug
  `print`s in and use magic numbers — that's fine, don't "clean it up".
- **Small diffs.** A feature should touch a few lines in the files that already
  exist, not add new modules. If your change adds a new file or a script, stop
  and ask whether the same thing can be done by editing existing behavior.
- **Change general behavior, not special cases.** Don't write one-off migration
  or backfill scripts, per-party helpers, or bespoke fix-ups. Change the thing
  that runs every day so the right behavior happens from now on.
- **The data is append-only, maintained by the daily job.** New polls are
  prepended by `daily_update.py`; the CSV is regenerated from the jsonl. Don't
  rewrite history. If a column didn't exist for old rows, old rows just have it
  empty — that's acceptable, the daily run fills it going forward.
- **Don't over-verify.** A couple of tests matching the existing style is
  enough. There is no coverage target here.

## The one common task: adding a party

This is the canonical example of "2 lines, not a script". To add a party
(e.g. "Futuro Nazionale"):

1. `llm_poll_parser/poll_parser.py` — add it in three places, mirroring any
   existing party: one bullet in the `system_prompt` list, one entry in
   `expected_keys` (before `"Altri"`), and one entry in `json_schema`
   (`properties` **and** the `required` list).
2. `llm_poll_parser/calculating_average.py` — add it to `parties_list` and give
   it a colour in `party_colors`.

That's the whole change. The daily scraper starts extracting it immediately;
old rows keep it empty. **Do not** write a backfill script, re-parse historical
polls, or "repair" the `Altri` column — that's exactly the kind of machinery
this repo avoids.

One caveat worth a single character: `load_and_process_data` drops polls with
too many missing party values via `thresh=len(parties_list) - 4`. Adding a
party that's null for all historical rows tightens that threshold, so bump the
constant (`- 4` → `- 5`) to keep the same rows. One edit, same spirit.

## What not to do

- No backfill/migration/one-off scripts. No new modules for a small feature.
- Don't rewrite existing data files by hand; let the daily job own them.
- Don't introduce abstractions, classes, or heavy typing to "improve" working
  plain code.
- Don't add elaborate test suites; match what `tests/` already does.

## Practical notes

- Python via `uv` (`uv run python ...`, `uv run pytest`). `OPENAI_API_KEY` lives
  in `.env`.
- The existing `test_poll_parser.py` makes a real OpenAI call and asserts exact
  dict equality — if you add a party, add its key (value `None`) to that test's
  `mock_response`, nothing more.
- Commit small and focused: one logical change per commit, plain message.
