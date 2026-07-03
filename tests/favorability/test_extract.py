# Extractor tests against the golden numbers from the v2 validation contract
# (exact matches unless noted). The LLM is mocked everywhere.
import json

import pytest

from llm_poll_parser.favorability.classify import classify
from llm_poll_parser.favorability.extract import run_extractor
from llm_poll_parser.favorability.taxonomy import normalize_pollster

from .conftest import FakeClient, load_fixture


def extract_fixture(name, client=None, cached_payload=None):
    fixture = load_fixture(name)
    pollster = normalize_pollster(fixture["pollster_raw"])
    classification = classify(pollster, fixture["domanda"], fixture["text"])
    assert classification.action in ("ACCEPT", "LLM"), classification
    return run_extractor(classification, pollster, fixture["domanda"], fixture["text"],
                         client=client, cached_payload=cached_payload)


def by_entity(result, metric=None):
    return {row["entity"]: row for row in result.rows
            if metric is None or row["metric"] == metric}


# --- golden: BiDiMedia 25/06 Meloni 36 (20+16) / Governo 35 (18+17), digit-exact ---

def test_bidimedia_meloni_golden():
    result = extract_fixture("bidimedia_meloni_fiducia")
    row = by_entity(result, "fiducia_pct")["Giorgia Meloni"]
    assert row["value"] == 36.0
    assert row["value_negative"] == 61.0  # 22 poca + 39 nessuna
    assert row["value_dontknow"] == 3.0
    assert row["base"] == "full_sample"
    assert "20" in row["scale_note"] and "16" in row["scale_note"]


def test_bidimedia_governo_golden():
    result = extract_fixture("bidimedia_governo_fiducia")
    row = by_entity(result, "fiducia_pct")["Governo"]
    assert row["value"] == 35.0


# --- golden: Piepoli June Meloni 42 (17+25), national row only ----------------------

def test_piepoli_june_meloni_golden():
    result = extract_fixture("piepoli_meloni_national_june")
    assert len(result.rows) == 1
    row = result.rows[0]
    assert row["entity"] == "Giorgia Meloni"
    assert row["metric"] == "fiducia_pct"
    assert row["value"] == 42.0
    assert row["scale_note"] == "molto 17 + abbastanza 25"


def test_piepoli_footer_variant_extracts_scale_not_footer():
    result = extract_fixture("piepoli_meloni_with_footer")
    assert result.rows[0]["value"] == 45.0  # 18+27, matching the printed footer


def test_piepoli_allegato_json_variant():
    result = extract_fixture("piepoli_meloni_allegato_json")
    assert result.rows[0]["value"] == 43.0  # 17+26
    assert result.rows[0]["extraction"] == "json_keys"


def test_piepoli_trump_kept_as_non_roster_row():
    result = extract_fixture("piepoli_trump_national")
    row = result.rows[0]
    assert row["entity"] == "Donald Trump"
    assert row["entity_in_roster"] is False
    assert row["value"] == 13.0


# --- golden: TP 22/06 Meloni 38.7 (25.3+13.4) ---------------------------------------

def test_tp_meloni_golden():
    result = extract_fixture("tp_meloni_fiducia")
    row = result.rows[0]
    assert row["entity"] == "Giorgia Meloni"
    assert row["value"] == pytest.approx(38.7)


# --- golden: EMG 25/06 Mattarella 82 -------------------------------------------------

def test_emg_battery_golden():
    result = extract_fixture("emg_leader_battery")
    rows = by_entity(result, "fiducia_pct")
    assert rows["Sergio Mattarella"]["value"] == 82.0
    assert rows["Giorgia Meloni"]["value"] == 41.0
    assert rows["Sergio Mattarella"]["entity_in_roster"] is True


# --- golden: Ipsos 03/06 Governo 40 / Meloni 42, raw leaders 30/27/24 ----------------

def test_ipsos_governo_indice_golden():
    result = extract_fixture("ipsos_governo_indice")
    index = by_entity(result, "gradimento_index")["Governo"]
    raw = by_entity(result, "giudizi_positivi_pct")["Governo"]
    assert index["value"] == 40.0
    assert index["base"] == "expressers"
    assert index["derivation"].startswith("deposited INDICE row")
    assert raw["value"] == 36.0
    assert raw["value_negative"] == 53.0
    assert raw["base"] == "full_sample"


def test_ipsos_pm_indice_golden():
    result = extract_fixture("ipsos_pm_indice")
    assert by_entity(result, "gradimento_index")["Giorgia Meloni"]["value"] == 42.0
    assert by_entity(result, "giudizi_positivi_pct")["Giorgia Meloni"]["value"] == 37.0


def test_ipsos_indice_mismatch_goes_to_review():
    fixture = load_fixture("ipsos_governo_indice")
    tampered = fixture["text"].replace('"40"', '"45"')
    classification = classify("Ipsos", fixture["domanda"], tampered)
    result = run_extractor(classification, "Ipsos", fixture["domanda"], tampered)
    assert not result.rows
    assert "recompute" in result.review[0]


def test_ipsos_leader_battery_golden():
    result = extract_fixture("ipsos_leader_battery")
    rows = by_entity(result, "giudizi_positivi_pct")
    assert rows["Giuseppe Conte"]["value"] == 30.0
    assert rows["Antonio Tajani"]["value"] == 27.0
    assert rows["Elly Schlein"]["value"] == 24.0
    # must NOT be anywhere near the published expressers index (48/46/45)
    assert abs(rows["Giuseppe Conte"]["value"] - 48) > 5
    assert abs(rows["Antonio Tajani"]["value"] - 46) > 5
    assert abs(rows["Elly Schlein"]["value"] - 45) > 5
    # and none of them may claim the index metric
    assert not by_entity(result, "gradimento_index")


# --- golden: LAB21 24/06 TOP TEN sums to 100.0, Meloni 36.7, zero fiducia_pct rows ---

def test_lab21_top_ten_golden():
    result = extract_fixture("lab21_top_ten")
    shares = by_entity(result, "most_trusted_share")
    assert shares["Giorgia Meloni"]["value"] == 36.7
    assert sum(row["value"] for row in shares.values()) == pytest.approx(100.0)
    assert len(shares) == 10
    assert not by_entity(result, "fiducia_pct")
    assert shares["Cateno De Luca"]["entity_in_roster"] is False


def test_lab21_binary():
    result = extract_fixture("lab21_binary")
    row = result.rows[0]
    assert row["metric"] == "fiducia_binaria_pct"
    assert row["value"] == 42.3
    assert row["value_negative"] == 57.7


# --- batteries with awareness / two-column tables -------------------------------------

def test_bidimedia_battery_takes_post_colon_value():
    result = extract_fixture("bidimedia_leader_battery")
    rows = by_entity(result, "fiducia_pct")
    assert rows["Giorgia Meloni"]["value"] == 36.0   # NOT the 98 awareness
    assert rows["Giuseppe Conte"]["value"] == 31.0
    assert "conoscenza 98" in rows["Giorgia Meloni"]["scale_note"]


def test_bidimedia_awareness_defect_goes_to_review():
    result = extract_fixture("bidimedia_leader_battery_awareness_defect")
    assert not result.rows
    assert "awareness" in result.review[0]


def test_demospi_takes_first_column_only():
    result = extract_fixture("demospi_leader_battery")
    rows = by_entity(result, "giudizi_positivi_pct")
    assert rows["Giorgia Meloni"]["value"] == 44.0   # NOT the 2 'non conoscono'
    assert rows["Matteo Salvini"]["value"] == 28.0


def test_youtrend_buckets():
    result = extract_fixture("youtrend_giudizio_governo")
    row = result.rows[0]
    assert row["entity"] == "Governo"
    assert row["metric"] == "giudizi_positivi_pct"
    assert row["value"] == 38.0
    assert row["value_negative"] == 54.0


# --- LLM fallback (mocked) --------------------------------------------------------------

def llm_payload(rows, favorability=1):
    return json.dumps({"rationale": "test", "favorability": favorability, "rows": rows})


def test_llm_fallback_extracts_and_validates():
    client = FakeClient(llm_payload([
        {"entity": "Giovanni Ferrero", "metric": "fiducia_binaria_pct", "value": 55,
         "value_negative": 12, "value_dontknow": 33, "population": "national",
         "base": "full_sample", "scale_note": "hanno fiducia"},
        {"entity": "John Elkann", "metric": "fiducia_binaria_pct", "value": 14,
         "value_negative": 59, "value_dontknow": 27, "population": "national",
         "base": "full_sample", "scale_note": "hanno fiducia"},
    ]))
    result = extract_fixture("youtrend_imprenditori", client=client)
    rows = {row["entity"]: row for row in result.rows}
    assert rows["Giovanni Ferrero"]["value"] == 55.0
    assert rows["Giovanni Ferrero"]["entity_in_roster"] is False
    assert rows["Giovanni Ferrero"]["extraction"] in ("llm", "llm_regex_agree")


def test_llm_fallback_drops_non_national_rows():
    client = FakeClient(llm_payload([
        {"entity": "Giorgia Meloni", "metric": "fiducia_pct", "value": 88,
         "population": "subgroup", "base": "full_sample"},
        {"entity": "Giorgia Meloni", "metric": "fiducia_pct", "value": 43,
         "population": "national", "base": "full_sample"},
    ]))
    result = extract_fixture("youtrend_imprenditori", client=client)
    assert len(result.rows) == 1
    assert result.rows[0]["value"] == 43.0


def test_llm_fallback_fails_fast_on_bad_metric():
    client = FakeClient(llm_payload([
        {"entity": "X", "metric": "percentuale_boh", "value": 10, "population": "national"},
    ]))
    with pytest.raises(ValueError, match="metric"):
        extract_fixture("youtrend_imprenditori", client=client)


def test_llm_fallback_fails_fast_on_non_json():
    with pytest.raises(ValueError, match="non-JSON"):
        extract_fixture("youtrend_imprenditori", client=FakeClient("sorry, no"))


# Regression (round-1 blocker): the fresh payload must be surfaced for the raw
# ledger, and a ledger-cached payload must be replayed with ZERO API calls.

def test_llm_fallback_surfaces_payload_for_the_ledger():
    payload_rows = [{"entity": "Giovanni Ferrero", "metric": "fiducia_binaria_pct",
                     "value": 55, "population": "national", "base": "full_sample"}]
    result = extract_fixture("youtrend_imprenditori", client=FakeClient(llm_payload(payload_rows)))
    assert result.llm_payload == json.loads(llm_payload(payload_rows))


def test_llm_extractor_replays_cached_payload_without_any_api_call():
    cached = json.loads(llm_payload([
        {"entity": "GIOVANNI FERRERO", "metric": "fiducia_binaria_pct", "value": 55,
         "value_negative": 12, "value_dontknow": 33, "population": "national",
         "base": "full_sample", "scale_note": "hanno fiducia"},
    ]))
    client = FakeClient("MUST NOT BE CALLED")
    result = extract_fixture("youtrend_imprenditori", client=client, cached_payload=cached)
    assert client.calls == []                       # replay is offline
    assert result.llm_payload == cached             # payload survives replay
    assert len(result.rows) == 1
    row = result.rows[0]
    assert row["value"] == 55.0
    assert row["entity"] == "Giovanni Ferrero"      # casing fixed code-side, not by the LLM


def test_leader_battery_with_repeated_labels_goes_to_review():
    from llm_poll_parser.favorability.classify import Classification
    from llm_poll_parser.favorability.extract import extract_leader_battery

    fixture = load_fixture("emg_toscana_conoscenza")
    classification = Classification("ACCEPT", "leader_battery", "fiducia_pct",
                                    extractor="leader_battery")
    result = extract_leader_battery(classification, "EMG", fixture["domanda"], fixture["text"])
    assert not result.rows
    assert "repeated labels" in result.review[0]


def test_real_demospi_atlante_golden():
    result = extract_fixture("demospi_atlante_real")
    rows = by_entity(result, "giudizi_positivi_pct")
    assert rows["Giorgia Meloni"]["value"] == 39.0
    assert rows["Giuseppe Conte"]["value"] == 35.0
    assert len(result.rows) == 10
    assert not by_entity(result, "fiducia_pct")


def test_demospi_capo_stato_expressers_row():
    result = extract_fixture("demospi_capo_stato_al_netto")
    assert len(result.rows) == 1
    row = result.rows[0]
    assert row["entity"] == "Sergio Mattarella"
    assert row["metric"] == "gradimento_index"
    assert row["value"] == 61.0
    assert row["base"] == "expressers"
