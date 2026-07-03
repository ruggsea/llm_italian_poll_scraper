# Ledger tests: idempotent merges (existing wins), the uniqueness constraint
# that structurally kills double-counted deposits, and atomic writes.
import json
import os

import pandas as pd

from llm_poll_parser.favorability.classify import Classification
from llm_poll_parser.favorability.ledger import (
    ROW_COLUMNS,
    build_row,
    merge_raw,
    merge_review,
    merge_rows,
    raw_record,
    review_item,
    write_jsonl_atomically,
    write_rows_atomically,
)


def meta(**overrides):
    base = {"Data Inserimento": "22/06/2026", "Realizzatore": "Istituto Piepoli",
            "Committente": "committente", "Titolo": "FIDUCIA IN GIORGIA MELONI",
            "pollster_norm": "Piepoli"}
    base.update(overrides)
    return base


def partial(**overrides):
    base = {"entity": "Giorgia Meloni", "entity_in_roster": True, "metric": "fiducia_pct",
            "value": 42.0, "value_negative": 54.0, "value_dontknow": 4.0,
            "base": "full_sample", "scale_note": "molto 17 + abbastanza 25",
            "derived": False, "derivation": None, "extraction": "regex",
            "pollster": "Piepoli"}
    base.update(overrides)
    return base


def classification():
    return Classification("ACCEPT", "piepoli_national_fiducia", "fiducia_pct",
                          extractor="scale")


def make_row(domanda="QUANTO HA FIDUCIA...?", m=None, **partial_overrides):
    return build_row(m or meta(), domanda, "text", classification(), partial(**partial_overrides))


def test_build_row_has_schema_columns_in_order():
    row = make_row()
    assert list(row.keys()) == ROW_COLUMNS
    assert row["pollster"] == "Piepoli"
    assert row["deposit_date"] == "22/06/2026"
    assert row["population"] == "national"
    assert len(row["row_key"]) == 40
    assert len(row["raw_text_sha1"]) == 40


def test_merge_rows_is_idempotent_and_existing_wins():
    existing = make_row()
    rescraped = make_row(value=41.0)          # same row_key (same doc/question/entity/metric)
    other = make_row(m=meta(**{"Data Inserimento": "23/06/2026"}))

    merged, conflicts = merge_rows([existing], [rescraped, other])
    assert len(merged) == 2 and not conflicts
    assert merged[0]["deposit_date"] == "23/06/2026"          # newest first
    assert merged[1]["value"] == 42.0                          # existing row wins

    remerged, conflicts = merge_rows(merged, [rescraped, other])
    assert remerged == merged and not conflicts                # rerun changes nothing


def test_uniqueness_constraint_kills_double_deposits():
    # Piepoli deposits the same wave twice (two documents, same date): the
    # second candidate must go to review, never into the rows (v1 defect 3).
    first = make_row(m=meta(Titolo="FIDUCIA IN GIORGIA MELONI"))
    second = make_row(m=meta(Titolo="FIDUCIA IN GIORGIA MELONI (secondo deposito)"),
                      value=43.0)
    assert first["row_key"] != second["row_key"]

    merged, conflicts = merge_rows([first], [second])
    assert len(merged) == 1
    assert conflicts == [second]


def test_derived_rows_do_not_conflict_with_published_rows():
    published = make_row()
    derived = make_row(metric="gradimento_index", value=44.0, derived=True,
                       derivation="pos/(pos+neg)", base="expressers")
    merged, conflicts = merge_rows([], [published, derived])
    assert len(merged) == 2 and not conflicts


def test_write_rows_atomically(tmp_path):
    jsonl = tmp_path / "rows.jsonl"
    csv = tmp_path / "rows.csv"
    write_rows_atomically([make_row()], str(jsonl), str(csv))

    assert not os.path.exists(str(jsonl) + ".tmp")
    assert not os.path.exists(str(csv) + ".tmp")
    reloaded = [json.loads(line) for line in jsonl.read_text().splitlines()]
    assert reloaded[0]["value"] == 42.0
    df = pd.read_csv(csv)
    assert list(df.columns) == ROW_COLUMNS
    assert df.iloc[0]["entity"] == "Giorgia Meloni"


def test_write_jsonl_is_atomic_over_existing_file(tmp_path):
    target = tmp_path / "ledger.jsonl"
    write_jsonl_atomically([{"a": 1}], str(target))
    write_jsonl_atomically([{"a": 1}, {"a": 2}], str(target))
    assert len(target.read_text().splitlines()) == 2


def test_merge_raw_and_review_are_idempotent():
    record = raw_record(meta(), "domanda", "text", classification(), "accepted", n_rows=1)
    stub = raw_record(meta(Titolo="empty doc"), None, None, None, "no_questions")
    merged = merge_raw([record], [record, stub])
    assert len(merged) == 2
    assert merge_raw(merged, [record, stub]) == merged

    item = review_item(meta(), "domanda", "text", "reason A")
    assert len(merge_review([item], [item])) == 1
    assert merge_review([item], [review_item(meta(), "domanda", "text", "reason B")])[0]


def test_raw_record_keeps_verbatim_text_and_classification():
    record = raw_record(meta(), "domanda", "verbatim text", classification(), "accepted", n_rows=2)
    assert record["text"] == "verbatim text"
    assert record["classification"]["table_kind"] == "piepoli_national_fiducia"
    assert record["status"] == "accepted"
    assert record["n_rows"] == 2
