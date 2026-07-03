"""
Long-format ledgers: load, merge (idempotent, existing wins), atomic write,
review-queue append.

Three files, all at the repo root like v1:
- favorability_raw.jsonl: one record per document-question, verbatim text +
  classification (audit + resume; includes rejected stubs and empty documents).
- favorability_polls.jsonl / .csv: accepted long rows only (one row per
  (poll, entity, metric)).
- favorability_review_queue.jsonl: unclassifiable/contract-violating tables
  for human triage — NEVER silently ingested.

Writes are temp file + os.replace (atomic); merges are keyed and idempotent
(existing rows win, so reruns change nothing when nothing is new). Source
data (italian_polls.*) is never touched.
"""

import hashlib
import json
import os
from datetime import datetime

RAW_FILENAME = "favorability_raw.jsonl"
ROWS_JSONL_FILENAME = "favorability_polls.jsonl"
ROWS_CSV_FILENAME = "favorability_polls.csv"
REVIEW_FILENAME = "favorability_review_queue.jsonl"

ROW_COLUMNS = [
    "row_key", "document_key", "question_key",
    "pollster", "pollster_raw", "committente",
    "deposit_date", "fieldwork_start", "fieldwork_end", "sample_size",
    "entity", "entity_in_roster", "metric", "value",
    "value_negative", "value_dontknow",
    "population", "base", "table_kind",
    "derived", "derivation", "extraction", "scale_note",
    "source_title", "domanda", "raw_text_sha1",
]


def sha1(text):
    return hashlib.sha1(str(text).encode("utf-8")).hexdigest()


def document_key(meta):
    return f"{meta.get('Data Inserimento')}|{meta.get('Realizzatore')}|{meta.get('Titolo')}"


def question_key(meta, domanda):
    return f"{document_key(meta)}|{domanda}"


def row_key(document_k, question_k, entity, metric, derived=False):
    suffix = "|derived" if derived else ""
    return sha1(f"{document_k}|{question_k}|{entity}|{metric}{suffix}")


def uniqueness_key(row):
    """At most one row per (pollster, deposit_date, entity, metric, population,
    derived) — the structural kill-switch for double-counted deposits."""
    return (row["pollster"], row["deposit_date"], row["entity"], row["metric"],
            row["population"], bool(row.get("derived")))


def build_row(meta, domanda, text, classification, partial):
    """Assemble one full long-format row (new dict, fixed column order)."""
    doc_k = document_key(meta)
    q_k = question_key(meta, domanda)
    source = {
        "document_key": doc_k,
        "question_key": q_k,
        "pollster": partial.get("pollster") or meta.get("pollster_norm"),
        "pollster_raw": meta.get("Realizzatore"),
        "committente": meta.get("Committente"),
        "deposit_date": meta.get("Data Inserimento"),
        "fieldwork_start": meta.get("fieldwork_start"),
        "fieldwork_end": meta.get("fieldwork_end"),
        "sample_size": meta.get("sample_size"),
        "population": classification.population,
        "table_kind": classification.table_kind,
        "source_title": meta.get("Titolo"),
        "domanda": domanda,
        "raw_text_sha1": sha1(text or ""),
        **partial,
    }
    source["row_key"] = row_key(doc_k, q_k, source["entity"], source["metric"],
                                source.get("derived", False))
    return {column: source.get(column) for column in ROW_COLUMNS}


# --- generic jsonl io -------------------------------------------------------------


def load_jsonl(filename):
    if not os.path.exists(filename):
        return []
    with open(filename, "r") as file:
        return [json.loads(line) for line in file if line.strip()]


def write_jsonl_atomically(records, filename):
    temp = f"{filename}.tmp"
    with open(temp, "w") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
    os.replace(temp, filename)


def _by_date_newest_first(records, date_field):
    def sort_key(record):
        try:
            return datetime.strptime(record.get(date_field) or "01/01/1900", "%d/%m/%Y")
        except ValueError:
            return datetime(1900, 1, 1)
    return sorted(records, key=sort_key, reverse=True)


# --- rows ledger -------------------------------------------------------------------


def merge_rows(existing_rows, new_rows):
    """Merge on row_key; existing rows win (idempotent). Enforces the uniqueness
    constraint: a NEW row that collides with a different existing row on
    (pollster, deposit_date, entity, metric, population, derived) is returned
    as a conflict for the review queue instead of being merged.

    Returns (merged_rows_newest_first, conflicts).
    """
    merged = {row["row_key"]: row for row in existing_rows}
    uniq = {uniqueness_key(row): row["row_key"] for row in existing_rows}
    conflicts = []
    for row in new_rows:
        if row["row_key"] in merged:
            continue
        uniq_key = uniqueness_key(row)
        if uniq_key in uniq:
            conflicts.append(row)
            continue
        merged[row["row_key"]] = row
        uniq[uniq_key] = row["row_key"]
    return _by_date_newest_first(merged.values(), "deposit_date"), conflicts


def write_rows_atomically(rows, jsonl_filename=ROWS_JSONL_FILENAME,
                          csv_filename=ROWS_CSV_FILENAME):
    """Write the accepted long rows: jsonl + a CSV view, temp file + os.replace."""
    import pandas as pd

    write_jsonl_atomically(rows, jsonl_filename)
    temp = f"{csv_filename}.tmp"
    pd.DataFrame(rows, columns=ROW_COLUMNS).to_csv(temp, index=False)
    os.replace(temp, csv_filename)


# --- raw ledger ----------------------------------------------------------------------


def raw_record(meta, domanda, text, classification, status, n_rows=0, error=None,
               llm_payload=None):
    """One audit record per document-question (or per empty document).

    llm_payload is the verbatim parsed JSON returned by the LLM fallback (None
    for mechanical extractors): persisting it here is what makes `reprocess`
    an OFFLINE, deterministic replay instead of a fresh nondeterministic API
    pass over every fallback table.
    """
    return {
        "record_key": sha1(question_key(meta, domanda)),
        "document_key": document_key(meta),
        "Data Inserimento": meta.get("Data Inserimento"),
        "Realizzatore": meta.get("Realizzatore"),
        "pollster": meta.get("pollster_norm"),
        "Committente": meta.get("Committente"),
        "Titolo": meta.get("Titolo"),
        "domanda": domanda,
        "text": text,
        "raw_text_sha1": sha1(text or ""),
        "classification": None if classification is None else {
            "action": classification.action,
            "table_kind": classification.table_kind,
            "metric": classification.metric,
            "population": classification.population,
            "extractor": classification.extractor,
            "reason": classification.reason,
            "crosscheck": classification.crosscheck,
        },
        "status": status,   # accepted | rejected | review | error | no_questions
        "n_rows": n_rows,
        "error": error,
        "llm_payload": llm_payload,
    }


def merge_raw(existing_records, new_records):
    """Merge on record_key; existing records win; newest deposit first."""
    merged = {record["record_key"]: record for record in new_records}
    merged.update({record["record_key"]: record for record in existing_records})
    return _by_date_newest_first(merged.values(), "Data Inserimento")


# --- review queue -----------------------------------------------------------------------


def review_item(meta, domanda, text, reason, payload=None):
    return {
        "review_key": sha1(f"{question_key(meta, domanda)}|{reason}"),
        "document_key": document_key(meta),
        "deposit_date": meta.get("Data Inserimento"),
        "pollster_raw": meta.get("Realizzatore"),
        "Titolo": meta.get("Titolo"),
        "domanda": domanda,
        "text": text,
        "reason": reason,
        "payload": payload,
    }


def merge_review(existing_items, new_items):
    merged = {item["review_key"]: item for item in new_items}
    merged.update({item["review_key"]: item for item in existing_items})
    return _by_date_newest_first(merged.values(), "deposit_date")
