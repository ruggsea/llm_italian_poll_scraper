# Pipeline and crawl-loop tests (offline: LLM mocked, selenium faked).
# Includes the INVERSION of v1's title-gate test: a document titled
# "Monitor Italia" IS opened and its favorability question is parsed.
import json
import os
import subprocess
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

import llm_poll_parser.favorability.averaging as averaging_module
import llm_poll_parser.favorability.crawler as crawler_module
from llm_poll_parser.favorability.crawler import (
    DAILY_LOOKBACK_DAYS,
    DEFAULT_FLOOR,
    LedgerState,
    crawl,
    daily_update,
    latest_seen_date,
    process_question,
    reprocess,
)

from .conftest import FakeClient, fixture_meta, load_fixture


def run_fixture(name, client=None, llm_enabled=True):
    fixture = load_fixture(name)
    return process_question(fixture_meta(fixture), fixture["domanda"], fixture["text"],
                            client=client, llm_enabled=llm_enabled)


# --- process_question: the four v1 defects end-to-end -------------------------------

def test_subgroup_question_yields_zero_rows():
    record, rows, items = run_fixture("piepoli_meloni_subgroup")
    assert record["status"] == "rejected"
    assert rows == [] and items == []   # golden: Meloni CENTRO-DESTRA 88 -> REJECTED, 0 rows


def test_lab21_top_ten_yields_only_most_trusted_share():
    record, rows, items = run_fixture("lab21_top_ten")
    assert record["status"] == "accepted"
    assert {row["metric"] for row in rows} == {"most_trusted_share"}
    assert sum(row["value"] for row in rows) == pytest.approx(100.0)
    assert not [row for row in rows if row["metric"] == "fiducia_pct"]


def test_ipsos_battery_rows_are_the_expressers_index():
    record, rows, items = run_fixture("ipsos_leader_battery")
    values = {row["entity"]: row["value"] for row in rows}
    assert values["Giuseppe Conte"] == 30.0
    assert all(row["metric"] == "gradimento_index" for row in rows)
    assert all(row["base"] == "expressers" for row in rows)


def test_scale_question_emits_published_plus_derived_row():
    record, rows, items = run_fixture("piepoli_meloni_national_june")
    assert record["status"] == "accepted"
    assert len(rows) == 2
    published, derived = rows
    assert published["metric"] == "fiducia_pct" and published["value"] == 42.0
    assert not published["derived"]
    assert derived["metric"] == "gradimento_index" and derived["derived"] is True
    assert derived["row_key"] != published["row_key"]
    assert derived["pollster"] == "Piepoli"


def test_llm_disabled_routes_fallback_to_review():
    record, rows, items = run_fixture("youtrend_imprenditori", llm_enabled=False)
    assert record["status"] == "review"
    assert rows == []
    assert "LLM disabled" in items[0]["reason"]


def test_malformed_llm_output_twice_lands_in_review_not_csv():
    record, rows, items = run_fixture("youtrend_imprenditori", client=FakeClient("garbage"))
    assert record["status"] == "error"
    assert rows == []
    assert "malformed LLM output twice" in items[0]["reason"]


def test_llm_says_not_favorability_becomes_rejected_stub():
    payload = json.dumps({"rationale": "vote shares", "favorability": 0, "rows": []})
    record, rows, items = run_fixture("youtrend_imprenditori", client=FakeClient(payload))
    assert record["status"] == "rejected"
    assert rows == [] and items == []


# --- LedgerState: resume + uniqueness through the write path --------------------------

def state_in(tmp_path):
    return LedgerState(str(tmp_path / "raw.jsonl"), str(tmp_path / "rows.jsonl"),
                       str(tmp_path / "rows.csv"), str(tmp_path / "review.jsonl"))


def test_ingest_is_idempotent_and_resumable(tmp_path):
    record, rows, items = run_fixture("bidimedia_meloni_fiducia")
    state = state_in(tmp_path)
    state.ingest([record], rows, items)
    n_rows = len(state.rows)

    resumed = state_in(tmp_path)   # reload from disk, like a rerun
    assert resumed.seen_documents() == {record["document_key"]}
    resumed.ingest([record], rows, items)
    assert len(resumed.rows) == n_rows


def test_double_deposit_conflict_goes_to_review_queue(tmp_path):
    fixture = load_fixture("piepoli_meloni_national_june")
    _, rows_a, _ = run_fixture("piepoli_meloni_national_june")
    meta_b = {**fixture_meta(fixture), "Titolo": "FIDUCIA IN GIORGIA MELONI (bis)"}
    record_b, rows_b, items_b = process_question(meta_b, fixture["domanda"],
                                                 fixture["text"].replace("17%", "18%")
                                                 .replace("31%", "30%"))
    state = state_in(tmp_path)
    state.ingest([], rows_a, [])
    conflicts = state.ingest([record_b], rows_b, items_b)
    assert conflicts, "second same-wave value must not merge"
    assert any("uniqueness conflict" in item["reason"] for item in state.review)
    values = [row["value"] for row in state.rows if row["metric"] == "fiducia_pct"]
    assert values == [42.0]   # exactly one Piepoli row per wave


# --- crawl loop with a fake driver: the Monitor Italia inversion ----------------------

class FakeElement:
    def __init__(self, element_id, title):
        self._attrs = {"id": element_id, "title": title}

    def get_attribute(self, name):
        return self._attrs[name]

    def click(self):
        pass


class FakeDriver:
    def back(self):
        pass

    def quit(self):
        pass

    def find_element(self, by, value):
        return FakeElement(value, "")


def install_fake_website_getter(monkeypatch, table, domande, texts):
    import website_getter

    monkeypatch.setattr(website_getter, "start_driver", lambda headless=True: FakeDriver())
    monkeypatch.setattr(website_getter, "find_sondaggi_table", lambda driver: [dict(r) for r in table])
    monkeypatch.setattr(website_getter, "click_on_row", lambda driver, row: None)
    monkeypatch.setattr(website_getter, "click_on_domande", lambda driver: None)
    monkeypatch.setattr(website_getter, "get_lista_domande",
                        lambda driver: [FakeElement(i, t) for i, t in domande])
    texts_iter = iter(texts)
    monkeypatch.setattr(website_getter, "get_risposta_or_allegato", lambda driver: next(texts_iter))
    monkeypatch.setattr(website_getter, "get_prossima_pagina", lambda driver: None)


def test_crawl_opens_monitor_italia_documents(tmp_path, monkeypatch):
    # v1's title gate skipped "Monitor Italia" wholesale (the inverted test):
    # v2 must open it and parse the EMG fiducia question hidden inside.
    monkeypatch.setattr(crawler_module.time, "sleep", lambda seconds: None)
    emg = load_fixture("emg_governo_fiducia")
    table = [{"Row": 1, "Data Inserimento": "25/06/2026", "Realizzatore": "Emg srl",
              "Committente": "x", "Titolo": "Monitor Italia"}]
    domande = [("Row1_Domanda", emg["domanda"]),
               ("Row2_Domanda", "Se oggi si votasse per la Camera, a chi andrebbe il suo voto?")]
    install_fake_website_getter(monkeypatch, table, domande, [emg["text"]])

    state = crawl(datetime(2026, 6, 1), max_pages=3, state=state_in(tmp_path))

    governo = [row for row in state.rows if row["entity"] == "Governo"
               and row["metric"] == "fiducia_pct"]
    assert governo and governo[0]["value"] == 41.0        # molta 15 + abbastanza 26
    assert governo[0]["source_title"] == "Monitor Italia"
    # the voting-intention question was never clicked (question-level filter)
    assert all(record["domanda"] != domande[1][1] for record in state.raw)


def test_crawl_resumes_by_skipping_seen_documents(tmp_path, monkeypatch):
    monkeypatch.setattr(crawler_module.time, "sleep", lambda seconds: None)
    emg = load_fixture("emg_governo_fiducia")
    table = [{"Row": 1, "Data Inserimento": "25/06/2026", "Realizzatore": "Emg srl",
              "Committente": "x", "Titolo": "Monitor Italia"}]
    install_fake_website_getter(monkeypatch, table, [("Row1_Domanda", emg["domanda"])],
                                [emg["text"], "SHOULD NEVER BE FETCHED"])
    state = crawl(datetime(2026, 6, 1), max_pages=2, state=state_in(tmp_path))
    rows_before = list(state.rows)

    # rerun on the same ledger: the document is skipped, texts iterator untouched
    rerun_state = crawl(datetime(2026, 6, 1), max_pages=2, state=state_in(tmp_path))
    assert rerun_state.rows == rows_before


# --- reprocess: deterministic replay from the raw ledger -------------------------------

def test_reprocess_rebuilds_rows_from_raw_ledger(tmp_path):
    state = state_in(tmp_path)
    for name in ["bidimedia_meloni_fiducia", "ipsos_governo_indice", "lab21_top_ten",
                 "piepoli_meloni_subgroup"]:
        record, rows, items = run_fixture(name)
        state.ingest([record], rows, items)
    rows_before = list(state.rows)
    assert rows_before

    rebuilt = reprocess(llm_enabled=False, state=state_in(tmp_path))
    assert rebuilt.rows == rows_before
    assert {record["status"] for record in rebuilt.raw} == {"accepted", "rejected"}


# --- reprocess is OFFLINE (round-1 blocker regression) ---------------------------------
# The documented replay command must never re-call the API: LLM tables replay
# the payload persisted in their raw record, and running it N times == once.

class ExplodingClient:
    """Fails the test on any completion call: replay must be offline."""

    def __init__(self):
        def create(**kwargs):
            raise AssertionError("reprocess must NOT call the LLM API")

        self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))


def canned_llm_payload():
    return {"rationale": "test", "favorability": 1, "rows": [
        {"entity": "GIOVANNI FERRERO", "metric": "fiducia_binaria_pct", "value": 55,
         "value_negative": 12, "value_dontknow": 33, "population": "national",
         "base": "full_sample", "scale_note": "hanno fiducia"},
    ]}


def test_llm_payload_is_persisted_and_reprocess_replays_it_offline(tmp_path):
    record, rows, items = run_fixture("youtrend_imprenditori",
                                      client=FakeClient(json.dumps(canned_llm_payload())))
    assert record["status"] == "accepted"
    assert record["llm_payload"] == canned_llm_payload()   # verbatim payload in the ledger
    state = state_in(tmp_path)
    state.ingest([record], rows, items)

    # default reprocess: llm_enabled=False AND a client that explodes on contact
    rebuilt = reprocess(client=ExplodingClient(), state=state_in(tmp_path))
    assert rebuilt.rows == state.rows                       # identical rows, zero API calls
    assert rebuilt.raw[0]["llm_payload"] == canned_llm_payload()
    assert rebuilt.review == []

    # replaying the replay changes nothing (idempotent)
    again = reprocess(client=ExplodingClient(), state=state_in(tmp_path))
    assert again.rows == rebuilt.rows
    assert again.raw == rebuilt.raw


def test_reprocess_routes_uncached_llm_tables_to_review_not_api(tmp_path):
    # a record produced with the LLM disabled has no cached payload
    record, rows, items = run_fixture("youtrend_imprenditori", llm_enabled=False)
    assert record.get("llm_payload") is None
    state = state_in(tmp_path)
    state.ingest([record], rows, items)

    rebuilt = reprocess(client=ExplodingClient(), state=state_in(tmp_path))   # default offline
    assert rebuilt.rows == []
    assert any("LLM disabled" in item["reason"] for item in rebuilt.review)

    # explicit --llm opt-in is the only path that fetches the missing payload
    refetched = reprocess(client=FakeClient(json.dumps(canned_llm_payload())),
                          llm_enabled=True, state=state_in(tmp_path))
    assert len(refetched.rows) == 1
    assert refetched.raw[0]["llm_payload"] == canned_llm_payload()


# --- daily_update: depth-bounded, idempotent automation entrypoint --------------------
# Offline: selenium is short-circuited by monkeypatching crawl, and the LLM is
# never reached. Exercises the new floor/lookback logic and the no-op contract.

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_latest_seen_date_uses_newest_deposit():
    state = SimpleNamespace(raw=[
        {"Data Inserimento": "10/06/2025"},
        {"Data Inserimento": "25/06/2025"},
        {"Data Inserimento": "01/06/2025"},
        {"no_date": True},                       # rows without a date are ignored
    ])
    assert latest_seen_date(state) == datetime(2025, 6, 25)


def test_latest_seen_date_empty_ledger_falls_back_to_default_floor():
    state = SimpleNamespace(raw=[])
    assert latest_seen_date(state) == datetime.strptime(DEFAULT_FLOOR, "%d/%m/%Y")


def test_daily_update_floor_is_lookback_before_latest_seen(monkeypatch):
    # fake ledger with a known newest deposit; no real files touched
    fake_state = SimpleNamespace(
        raw=[{"Data Inserimento": "25/06/2026"}], rows=[], review=[])
    monkeypatch.setattr(crawler_module, "LedgerState", lambda: fake_state)

    captured = {}

    def fake_crawl(min_date, **kwargs):
        captured["min_date"] = min_date
        captured["kwargs"] = kwargs
        return fake_state

    monkeypatch.setattr(crawler_module, "crawl", fake_crawl)

    invoked = []
    monkeypatch.setattr(averaging_module, "load_rows", lambda: "ROWS")
    monkeypatch.setattr(averaging_module, "summarize",
                        lambda rows: invoked.append(("summarize", rows)) or "SUMMARY")
    monkeypatch.setattr(averaging_module, "write_summary",
                        lambda summary: invoked.append(("write_summary", summary)))
    monkeypatch.setattr(averaging_module, "make_plot",
                        lambda rows: invoked.append(("make_plot", rows)))

    daily_update(max_pages=10)

    assert captured["min_date"] == datetime(2026, 6, 25) - timedelta(days=DAILY_LOOKBACK_DAYS)
    # depth-bounded: does not rescan the whole archive (max_pages forwarded)
    assert captured["kwargs"]["max_pages"] == 10
    # averages + plot rebuilt from load_rows() output
    assert ("summarize", "ROWS") in invoked
    assert ("write_summary", "SUMMARY") in invoked
    assert ("make_plot", "ROWS") in invoked


def test_daily_update_noop_leaves_csvs_byte_identical(monkeypatch):
    # a no-new-deposit run: crawl adds nothing, so re-deriving averages from the
    # unchanged rows ledger must leave the committed CSV/JSONL byte-identical.
    golden = ["favorability_polls.csv", "favorability_polls.jsonl",
              "favorability_raw.jsonl", "favorability_averages.csv"]
    if not all(os.path.exists(os.path.join(REPO_ROOT, f)) for f in golden):
        pytest.skip("committed golden files not present in this checkout")

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.chdir(REPO_ROOT)
    # crawl is a no-op that returns the ledger untouched (simulates no new deposits)
    monkeypatch.setattr(crawler_module, "crawl",
                        lambda min_date, state=None, **kwargs: state)

    daily_update(max_pages=1)

    diff = subprocess.run(["git", "diff", "--", *golden],
                          cwd=REPO_ROOT, capture_output=True, text=True).stdout
    assert diff == "", "no-op daily_update perturbed the golden files:\n" + diff[:4000]


def test_replayed_entity_casing_is_normalized_code_side(tmp_path):
    # blocker regression: "GIOVANNI FERRERO" from the LLM must land as
    # "Giovanni Ferrero" both on first pass and on offline replay, so the
    # series key never depends on LLM casing.
    record, rows, _ = run_fixture("youtrend_imprenditori",
                                  client=FakeClient(json.dumps(canned_llm_payload())))
    assert rows[0]["entity"] == "Giovanni Ferrero"
    state = state_in(tmp_path)
    state.ingest([record], rows, [])
    rebuilt = reprocess(client=ExplodingClient(), state=state_in(tmp_path))
    assert [row["entity"] for row in rebuilt.rows] == ["Giovanni Ferrero"]
