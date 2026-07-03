"""
One-time (but idempotent) migration for the "Futuro Nazionale" column.

1. Every row of italian_polls.jsonl gains a "Futuro Nazionale" key (null),
   inserted right before "Altri" so the CSV column order stays consistent
   with expected_keys in poll_parser.py.
2. Rows whose raw poll text mentions Futuro Nazionale are re-parsed with the
   existing LLM parser and ONLY their "Futuro Nazionale" cell is filled in.
   The LLM value is cross-checked against a regex extraction from the raw
   text; on mismatch the row is left null and a warning is logged. No other
   party value is ever modified.
3. The jsonl is written to a temp file and swapped in atomically, then the
   csv is regenerated from the jsonl.

Known limitation, deliberately NOT corrected here: rows whose
pre-Futuro-Nazionale parse folded the party into "Altri" now count it twice
(once in the new column, once inside "Altri"). "Altri" cannot be corrected
mechanically — its stored value is not always "true minors + Futuro
Nazionale" (some rows store undecided/abstention mass, others never folded
the party in), so any subtraction heuristic writes provably wrong values.
Fixing those rows requires re-deriving "Altri" from each poll's raw text,
which is a separate follow-up migration.

Run from the repo root: uv run python llm_poll_parser/backfill_futuro_nazionale.py
"""

import json
import logging
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from poll_parser import parse_poll_results

PARTY = "Futuro Nazionale"
JSONL_FILENAME = "italian_polls.jsonl"
CSV_FILENAME = "italian_polls.csv"

MENTION_PATTERN = re.compile(r"(?i)futuro\s+nazionale")
SHARE_PATTERN = re.compile(r"(?i)futuro\s+nazionale[^0-9]{0,40}?(\d{1,2}(?:[.,]\d{1,2})?)")


def insert_party_key(poll):
    # Return a new dict with the party key (null) inserted right before "Altri"
    if PARTY in poll:
        return dict(poll)
    new_poll = {}
    for key, value in poll.items():
        if key == "Altri":
            new_poll[PARTY] = None
        new_poll[key] = value
    if PARTY not in new_poll:
        new_poll[PARTY] = None
    return new_poll


def extract_share_with_regex(raw_text):
    match = SHARE_PATTERN.search(raw_text or "")
    if match is None:
        return None
    return float(match.group(1).replace(",", "."))


def backfill_share(poll):
    # Return a new dict where ONLY the Futuro Nazionale cell is (possibly) filled in
    raw_text = poll.get("text") or ""
    if poll.get(PARTY) is not None or not MENTION_PATTERN.search(raw_text):
        return poll

    regex_share = extract_share_with_regex(raw_text)
    if regex_share is None:
        logging.warning(f"{poll['Data Inserimento']} - {poll['Titolo']}: mention without a share, leaving null")
        return poll

    poll_with_domanda = f"{poll.get('domanda') or ''}\n{raw_text}"
    llm_share = parse_poll_results(poll_with_domanda).get(PARTY)

    if llm_share is None or abs(llm_share - regex_share) > 0.001:
        logging.warning(
            f"{poll['Data Inserimento']} - {poll['Titolo']}: LLM share {llm_share} does not match "
            f"regex share {regex_share}, leaving null"
        )
        return poll

    logging.info(f"{poll['Data Inserimento']} - {poll['Titolo']}: {PARTY} = {llm_share}")
    return {key: (llm_share if key == PARTY else value) for key, value in poll.items()}


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    with open(JSONL_FILENAME, "r") as file:
        polls = [json.loads(line) for line in file if line.strip()]

    migrated_polls = [insert_party_key(poll) for poll in polls]
    added_keys = sum(1 for old, new in zip(polls, migrated_polls) if PARTY not in old and PARTY in new)
    logging.info(f"Added a null '{PARTY}' key to {added_keys} of {len(polls)} rows")

    backfilled_polls = [backfill_share(poll) for poll in migrated_polls]
    filled = sum(1 for poll in backfilled_polls if poll.get(PARTY) is not None)
    logging.info(f"Rows with a non-null '{PARTY}' share: {filled}")

    temp_filename = f"{JSONL_FILENAME}.tmp"
    with open(temp_filename, "w") as file:
        for poll in backfilled_polls:
            file.write(json.dumps(poll) + "\n")
    os.replace(temp_filename, JSONL_FILENAME)
    logging.info(f"Atomically rewrote {JSONL_FILENAME}")

    import pandas as pd

    pd.read_json(JSONL_FILENAME, lines=True).to_csv(CSV_FILENAME, index=False)
    logging.info(f"Regenerated {CSV_FILENAME} from {JSONL_FILENAME}")


if __name__ == "__main__":
    main()
