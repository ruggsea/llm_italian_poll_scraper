# Validation-contract tests: strict LLM payload schema + structural row guards.
import pytest

from llm_poll_parser.favorability.validate import guard_rows, validate_llm_payload


def payload(rows=None, favorability=1, **overrides):
    data = {"rationale": "why", "favorability": favorability,
            "rows": rows if rows is not None else [
                {"entity": "Giorgia Meloni", "metric": "fiducia_pct", "value": 42,
                 "population": "national", "base": "full_sample"}]}
    data.update(overrides)
    return data


def test_valid_payload_is_normalized_and_new():
    data = payload()
    snapshot = {**data, "rows": [dict(row) for row in data["rows"]]}
    result = validate_llm_payload(data)
    assert data == snapshot                      # input not mutated
    assert result["rows"][0]["value"] == 42.0
    assert result["rows"][0]["value_negative"] is None


def test_non_favorability_needs_no_rows():
    result = validate_llm_payload(payload(rows=[], favorability=0))
    assert result["rows"] == []


@pytest.mark.parametrize("mutation, match", [
    ({"favorability": 2}, "favorability"),
    ({"rows": "not a list"}, "rows must be a list"),
    ({"rows": []}, "rows is empty"),
])
def test_fails_fast_on_malformed_top_level(mutation, match):
    with pytest.raises(ValueError, match=match):
        validate_llm_payload(payload(**mutation))


def test_fails_fast_on_missing_key():
    with pytest.raises(ValueError, match="missing required key"):
        validate_llm_payload({"rationale": "x", "rows": []})


@pytest.mark.parametrize("row, match", [
    ({"entity": "", "metric": "fiducia_pct", "value": 10, "population": "national"}, "entity"),
    ({"entity": "X", "metric": "indice_gradimento", "value": 10, "population": "national"}, "metric"),
    ({"entity": "X", "metric": "fiducia_pct", "value": 136, "population": "national"}, "range"),
    ({"entity": "X", "metric": "voto_medio_1_10", "value": 36, "population": "national"}, "range"),
    ({"entity": "X", "metric": "fiducia_pct", "value": 10, "population": "everyone"}, "population"),
    ({"entity": "X", "metric": "fiducia_pct", "value": None, "population": "national"}, "null"),
])
def test_fails_fast_on_malformed_rows(row, match):
    with pytest.raises(ValueError, match=match):
        validate_llm_payload(payload(rows=[row]))


# --- structural guards -------------------------------------------------------------

def rows_summing_to_100(metric, n=10):
    return [{"entity": f"Leader {i}", "metric": metric, "value": 10.0} for i in range(n)]


def test_ranking_guard_rejects_fiducia_rows_that_sum_to_100():
    accepted, review = guard_rows(rows_summing_to_100("fiducia_pct"), context="LAB21")
    assert accepted == []
    assert "ranking misparsed" in review[0]


def test_most_trusted_share_must_sum_to_100():
    rows = rows_summing_to_100("most_trusted_share")
    accepted, review = guard_rows(rows)
    assert len(accepted) == 10 and not review

    rows[0] = {**rows[0], "value": 60.0}
    accepted, review = guard_rows(rows)
    assert accepted == []
    assert "not 100" in review[0]


def test_battery_not_summing_to_100_passes():
    rows = [{"entity": f"L{i}", "metric": "fiducia_pct", "value": 30.0} for i in range(10)]
    accepted, review = guard_rows(rows)
    assert len(accepted) == 10 and not review


def test_small_scale_row_sets_are_untouched():
    rows = [{"entity": "Giorgia Meloni", "metric": "fiducia_pct", "value": 42.0},
            {"entity": "Governo", "metric": "fiducia_pct", "value": 58.0}]
    accepted, review = guard_rows(rows)
    assert len(accepted) == 2 and not review
