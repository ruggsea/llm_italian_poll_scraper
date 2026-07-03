# tests/test_backfill_futuro_nazionale.py
# Offline unit tests for the Futuro Nazionale backfill migration helpers.
from llm_poll_parser.backfill_futuro_nazionale import backfill_share, insert_party_key


def make_poll(futuro_nazionale, altri, text=""):
    return {
        "Data Inserimento": "23/06/2026",
        "Titolo": "Intenzioni di voto",
        "text": text,
        "Partito Democratico": 21.8,
        "Forza Italia": 7.4,
        "Fratelli d'Italia": 27.7,
        "Alleanza Verdi Sinistra": 6.6,
        "Lega": 5.4,
        "Movimento 5 Stelle": 13.2,
        "+Europa": 1.6,
        "Azione": 3.7,
        "Italia Viva": 2.5,
        "Futuro Nazionale": futuro_nazionale,
        "Altri": altri,
    }


def test_insert_party_key_places_futuro_nazionale_before_altri():
    poll = {"Partito Democratico": 20.0, "Altri": 3.0}
    migrated = insert_party_key(poll)
    assert list(migrated.keys()) == ["Partito Democratico", "Futuro Nazionale", "Altri"]
    assert migrated["Futuro Nazionale"] is None


def test_backfill_share_skips_rows_without_a_mention():
    # No "Futuro Nazionale" in the raw text: the row is out of scope and must
    # be returned unchanged, without any LLM call
    poll = make_poll(futuro_nazionale=None, altri=4.8, text="Intenzioni di voto: PD 21,8%")
    assert backfill_share(poll) == poll


def test_backfill_share_is_idempotent_on_filled_rows():
    # An already-backfilled row is returned unchanged, without any LLM call
    poll = make_poll(futuro_nazionale=5.3, altri=14.9, text="Futuro Nazionale 5,3%")
    assert backfill_share(poll) == poll
