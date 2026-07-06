# Derived-metric tests: Ipsos index recompute (half-up rounding!) and the
# derived expressers-rate rows.
from llm_poll_parser.favorability.extract import (
    expressers_rate_row,
    half_up,
    ipsos_index_matches,
    recompute_gradimento_index,
)


def test_half_up_rounds_away_from_banker():
    assert half_up(42.5) == 43     # Ipsos 22/12/2025: 37/(37+50) -> 42.53 -> 43
    assert half_up(40.4) == 40
    assert half_up(42.04) == 42


def test_recompute_matches_every_real_ipsos_wave():
    # (positives, negatives, deposited INDICE) from the real archive deposits
    waves = [
        (36, 53, 40), (37, 51, 42),          # 03/06/2026 gov / PM
        (36, 52, 41), (37, 52, 42),          # 04/05/2026
        (36, 54, 40),                        # 30/03/2026
        (38, 49, 44),                        # 02/03/2026
        (37, 50, 43),                        # 22/12/2025
        (37, 52, 42),                        # 01/12/2025
    ]
    for positives, negatives, deposited in waves:
        assert recompute_gradimento_index(positives, negatives) == deposited
        assert ipsos_index_matches(deposited, positives, negatives)


def test_mismatch_is_flagged():
    assert not ipsos_index_matches(45, 36, 53)   # recompute says 40


def test_expressers_rate_row_is_derived_and_new():
    base = {"entity": "Giorgia Meloni", "metric": "fiducia_pct", "value": 42.0,
            "value_negative": 54.0, "base": "full_sample", "derived": False,
            "derivation": None, "extraction": "regex"}
    snapshot = dict(base)
    derived = expressers_rate_row(base)
    assert base == snapshot                       # no mutation
    assert derived["derived"] is True
    assert derived["metric"] == "gradimento_index"
    assert derived["value"] == 44.0               # 42/(42+54) -> 43.75 -> 44
    assert derived["base"] == "expressers"
    assert "positives=42" in derived["derivation"]


def test_expressers_rate_row_needs_a_negative_share():
    assert expressers_rate_row({"value": 42.0, "value_negative": None}) is None
