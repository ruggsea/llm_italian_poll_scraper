# Decision-tree tests: one test per rule, with all four v1 defects as
# regression fixtures (metric-scale mismatch, ranking misparse, subgroup
# double-count, document-title gate).
import pytest

from llm_poll_parser.favorability.classify import (
    ACCEPT,
    LLM,
    REJECT,
    classify,
    get_pairs,
    parse_label_value_lines,
    to_number,
)
from llm_poll_parser.favorability.taxonomy import is_relevant_question

from .conftest import load_fixture


def classify_fixture(name):
    fixture = load_fixture(name)
    from llm_poll_parser.favorability.taxonomy import normalize_pollster

    return classify(normalize_pollster(fixture["pollster_raw"]),
                    fixture["domanda"], fixture["text"])


# --- helpers -------------------------------------------------------------------

def test_to_number_handles_decimal_comma_and_percent():
    assert to_number("36,7%") == 36.7
    assert to_number("42") == 42.0
    assert to_number("") is None
    assert to_number("CENTRO DESTRA") is None


def test_parse_label_value_lines_skips_multi_number_lines():
    # Youtrend multi-column rows must NOT be parsed mechanically
    assert parse_label_value_lines("John Elkann 14 59 27") == []
    assert parse_label_value_lines("- Molto 16%") == [("Molto", 16.0)]
    assert parse_label_value_lines("Molta: 20%") == [("Molta", 20.0)]


def test_get_pairs_reads_allegato_json():
    pairs, is_json = get_pairs(load_fixture("ipsos_governo_indice")["text"])
    assert is_json
    assert ("voti positivi (6-10)", 36.0) in pairs


# --- rule 1: question-level relevance (replaces the v1 document-title gate) -----

def test_voting_intentions_are_rejected():
    result = classify_fixture("voting_intentions_reject")
    assert result.action == REJECT
    assert result.table_kind == "not_favorability"


def test_question_filter_is_question_level_not_document_level():
    # "Monitor Italia" tells you nothing; the QUESTION titles decide.
    assert not is_relevant_question("Monitor Italia")
    assert is_relevant_question("LEI QUANTA FIDUCIA HA NEL GOVERNO?")
    assert is_relevant_question("Che giudizio dai al lavoro fatto dal Governo Meloni fino ad oggi?")
    assert is_relevant_question("Ha fiducia nel Presidente del Consiglio Giorgia Meloni?")


# --- rule 2: subnational/local reject -------------------------------------------

@pytest.mark.parametrize("name", ["lab21_local_voto_1_10", "lab21_regionale_piemonte",
                                  "emg_toscana_reject"])
def test_subnational_questions_are_rejected(name):
    result = classify_fixture(name)
    assert result.action == REJECT
    assert result.table_kind == "subnational"
    assert result.population == "subnational"


# --- rule 3: subgroup breakdown reject (v1 defect: Piepoli Meloni-88) ------------

@pytest.mark.parametrize("name", ["piepoli_meloni_subgroup", "piepoli_subgroup_allegato_json"])
def test_subgroup_breakdowns_are_rejected(name):
    result = classify_fixture(name)
    assert result.action == REJECT
    assert result.table_kind == "subgroup_breakdown"
    assert result.population == "subgroup"


def test_subgroup_footer_becomes_crosscheck():
    result = classify_fixture("piepoli_meloni_subgroup")
    assert result.crosscheck == {"national_value": 43.0}


# --- rule 4: single-choice ranking (v1 defect: LAB21 TOP TEN) --------------------

def test_lab21_top_ten_is_most_trusted_share():
    result = classify_fixture("lab21_top_ten")
    assert result.action == ACCEPT
    assert result.metric == "most_trusted_share"
    assert result.extractor == "ranking"


# --- rule 5: Ipsos gov/PM indice table -------------------------------------------

@pytest.mark.parametrize("name", ["ipsos_governo_indice", "ipsos_pm_indice"])
def test_ipsos_indice_tables(name):
    result = classify_fixture(name)
    assert result.action == ACCEPT
    assert result.table_kind == "ipsos_indice"
    assert result.extractor == "ipsos_indice"


# --- rule 6: Ipsos leader battery (v1 defect: metric-scale mismatch) -------------

def test_ipsos_leader_battery_is_raw_positives_never_index():
    result = classify_fixture("ipsos_leader_battery")
    assert result.action == ACCEPT
    assert result.metric == "giudizi_positivi_pct"   # hard override of the header claim
    assert result.metric != "gradimento_index"


# --- rule 7: binary fiducia -------------------------------------------------------

def test_lab21_binary_fiducia():
    result = classify_fixture("lab21_binary")
    assert result.action == ACCEPT
    assert result.metric == "fiducia_binaria_pct"


# --- rule 8: 4/5-scale single-entity tables ---------------------------------------

@pytest.mark.parametrize("name", [
    "piepoli_meloni_national", "piepoli_meloni_national_june", "piepoli_trump_national",
    "piepoli_meloni_allegato_json", "piepoli_meloni_with_footer",
    "bidimedia_meloni_fiducia", "bidimedia_governo_fiducia",
    "emg_governo_fiducia", "tp_meloni_fiducia",
])
def test_scale_tables_are_fiducia_pct(name):
    result = classify_fixture(name)
    assert result.action == ACCEPT, result
    assert result.metric == "fiducia_pct"
    assert result.extractor == "scale"


def test_youtrend_judgment_buckets_are_giudizi_positivi():
    result = classify_fixture("youtrend_giudizio_governo")
    assert result.action == ACCEPT
    assert result.metric == "giudizi_positivi_pct"


# --- rules 9a/9b: leader batteries ------------------------------------------------

def test_bidimedia_battery_detected():
    result = classify_fixture("bidimedia_leader_battery")
    assert result.action == ACCEPT
    assert result.extractor == "bidimedia_battery"
    assert result.metric == "fiducia_pct"


def test_emg_leader_battery_detected():
    result = classify_fixture("emg_leader_battery")
    assert result.action == ACCEPT
    assert result.table_kind == "leader_battery"
    assert result.metric == "fiducia_pct"


# --- rule 10: Demos&Pi two-column table --------------------------------------------

def test_demospi_battery_detected():
    result = classify_fixture("demospi_leader_battery")
    assert result.action == ACCEPT
    assert result.extractor == "demospi"
    assert result.metric == "giudizi_positivi_pct"


# --- rule 12: LLM fallback -----------------------------------------------------------

def test_multi_column_table_falls_back_to_llm():
    result = classify_fixture("youtrend_imprenditori")
    assert result.action == LLM
    assert result.table_kind == "unclassified"


# --- live-shakedown regressions ----------------------------------------------------

def test_document_title_triggers_subnational_reject():
    # EMG Toscana: national-looking "fiducia nel Governo" question asked to a
    # Tuscany-only sample - only the DOCUMENT title says "toscane"
    fixture = load_fixture("emg_toscana_conoscenza")
    result = classify("EMG", "Lei quanta fiducia ha nel Governo Meloni?",
                      "Molta 12%\nAbbastanza 21%\nPoca 25%\nNessuna 39%\nNon saprei 3%",
                      document_title=fixture["titolo"])
    assert result.action == REJECT
    assert result.table_kind == "subnational"


def test_vertical_conoscenza_fiducia_layout_is_not_a_battery():
    fixture = load_fixture("emg_toscana_conoscenza")
    # even without the document title, the repeated Conoscenza/Fiducia labels
    # must never classify as a leader battery (they would create junk entities)
    result = classify("EMG", fixture["domanda"], fixture["text"])
    assert result.action == LLM
    assert result.table_kind == "unclassified"


def test_real_demospi_atlante_is_giudizi_positivi_not_fiducia():
    # live-shakedown regression: the JSON battery must hit the demospi rule,
    # never the generic leader-battery rule (metric-scale mismatch)
    result = classify_fixture("demospi_atlante_real")
    assert result.action == ACCEPT
    assert result.extractor == "demospi"
    assert result.metric == "giudizi_positivi_pct"


def test_al_netto_series_is_expressers_base_not_fiducia_pct():
    # Demos&Pi Capo dello Stato: value is net of non-responses -> expressers
    # base -> gradimento_index family, never pooled with full-sample fiducia
    result = classify_fixture("demospi_capo_stato_al_netto")
    assert result.action == ACCEPT
    assert result.extractor == "expressers_single"
    assert result.metric == "gradimento_index"
