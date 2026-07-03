# Averaging tests: per-(entity, metric) calendar-time-decayed average, the
# 14-day per-pollster dedup, the 60-day recency cutoff, and the n<2
# suppression rule for the cross-pollster line.
import pandas as pd
import pytest

from llm_poll_parser.favorability.averaging import (
    RECENCY_CUTOFF_DAYS,
    dedup_pollster_waves,
    ewma_series,
    summarize,
)


def frame(rows):
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df["entity_in_roster"] = df.get("entity_in_roster", True)
    return df.sort_values("date").reset_index(drop=True)


def poll(date, pollster, value, entity="Giorgia Meloni", metric="fiducia_pct"):
    return {"date": date, "pollster": pollster, "entity": entity, "metric": metric,
            "value": value, "entity_in_roster": True}


def test_dedup_keeps_most_recent_wave_per_14_days():
    df = frame([poll("2026-06-01", "Piepoli", 41.0),
                poll("2026-06-08", "Piepoli", 42.0),      # 7 days before the kept 15/06 -> dropped
                poll("2026-06-15", "Piepoli", 43.0)])
    deduped = dedup_pollster_waves(df)
    assert list(deduped["value"]) == [41.0, 43.0]


def test_dedup_is_per_pollster_and_per_metric():
    df = frame([poll("2026-06-10", "Piepoli", 42.0),
                poll("2026-06-12", "EMG", 41.0),                       # other pollster kept
                poll("2026-06-12", "Piepoli", 44.0, metric="gradimento_index")])
    assert len(dedup_pollster_waves(df)) == 3


def test_ewma_never_pools_across_metrics():
    # same entity, two metrics: the index series must not drag the fiducia one.
    # points 14 days apart with halflife 14 -> older point has weight 0.5
    df = frame([poll("2026-05-18", "Ipsos", 40.0, metric="gradimento_index"),
                poll("2026-06-01", "Ipsos", 44.0, metric="gradimento_index"),
                poll("2026-06-01", "TP", 36.0),
                poll("2026-06-15", "TP", 38.0)])
    averaged = ewma_series(df, halflife_days=14)
    index = averaged[averaged["metric"] == "gradimento_index"]
    fiducia = averaged[averaged["metric"] == "fiducia_pct"]
    assert index["moving_average"].iloc[-1] == pytest.approx((44.0 + 0.5 * 40.0) / 1.5)
    assert fiducia["moving_average"].iloc[-1] == pytest.approx((38.0 + 0.5 * 36.0) / 1.5)


def test_decay_is_calendar_time_not_poll_index():
    # Regression (validator blocker): two pollsters, same number of polls each,
    # but one pollster's wave is months old. An index-based EWMA would weight
    # the stale wave by its position in the series; calendar-time decay must
    # make a 56-day-old wave nearly irrelevant next to a same-week wave.
    df = frame([poll("2026-04-27", "BiDiMedia", 32.0, entity="Giuseppe Conte"),
                poll("2026-06-22", "EMG", 41.0, entity="Giuseppe Conte")])
    averaged = ewma_series(df, halflife_days=14)
    # weight of the 56-day-old point is 0.5**4 = 0.0625
    expected = (41.0 + 0.0625 * 32.0) / 1.0625
    assert averaged["moving_average"].iloc[-1] == pytest.approx(expected)
    assert averaged["moving_average"].iloc[-1] > 40.0  # stays near the current wave


def test_waves_older_than_recency_cutoff_are_excluded():
    # Regression (validator blocker): Piepoli/Ixe waves from Nov 2025 dragged
    # Mattarella's "current" average from 82 to 77.6. Waves older than the
    # recency cutoff must carry ZERO weight in the current average, while the
    # series still counts as cross-pollster (published, not suppressed).
    df = frame([poll("2025-11-21", "Piepoli", 61.0, entity="Sergio Mattarella"),
                poll("2025-11-27", "Ixè", 70.0, entity="Sergio Mattarella"),
                poll("2026-06-08", "EMG", 81.0, entity="Sergio Mattarella"),
                poll("2026-06-22", "EMG", 82.0, entity="Sergio Mattarella")])
    summary = summarize(df).set_index("entity")
    row = summary.loc["Sergio Mattarella"]
    assert row["n_pollsters"] == 3                     # provenance keeps all pollsters
    assert row["cross_pollster_average"] == pytest.approx(81.7, abs=0.05)
    assert abs(row["cross_pollster_average"] - 82.0) <= 2.0


def test_recency_cutoff_boundary():
    # a wave exactly at the cutoff is still included; one day beyond is not
    anchor = pd.Timestamp("2026-06-22")
    at_cutoff = (anchor - pd.Timedelta(days=RECENCY_CUTOFF_DAYS)).strftime("%Y-%m-%d")
    beyond = (anchor - pd.Timedelta(days=RECENCY_CUTOFF_DAYS + 1)).strftime("%Y-%m-%d")
    df_at = frame([poll(at_cutoff, "Piepoli", 20.0), poll("2026-06-22", "EMG", 40.0)])
    df_beyond = frame([poll(beyond, "Piepoli", 20.0), poll("2026-06-22", "EMG", 40.0)])
    assert ewma_series(df_at)["moving_average"].iloc[-1] < 40.0
    assert ewma_series(df_beyond)["moving_average"].iloc[-1] == pytest.approx(40.0)


def test_ewma_does_not_mutate_input():
    df = frame([poll("2026-05-01", "TP", 36.0), poll("2026-06-01", "TP", 38.0)])
    snapshot = df.copy(deep=True)
    ewma_series(df)
    pd.testing.assert_frame_equal(df, snapshot)


def test_summary_suppresses_cross_pollster_average_below_two_pollsters():
    df = frame([poll("2026-05-01", "EMG", 80.0, entity="Sergio Mattarella"),
                poll("2026-06-01", "EMG", 82.0, entity="Sergio Mattarella"),
                poll("2026-06-01", "BiDiMedia", 36.0),
                poll("2026-06-15", "TP", 38.0)])
    summary = summarize(df).set_index("entity")
    assert summary.loc["Sergio Mattarella", "n_pollsters"] == 1
    assert pd.isna(summary.loc["Sergio Mattarella", "cross_pollster_average"])
    assert summary.loc["Giorgia Meloni", "n_pollsters"] == 2
    assert not pd.isna(summary.loc["Giorgia Meloni", "cross_pollster_average"])


def test_summary_reports_provenance():
    df = frame([poll("2026-06-01", "BiDiMedia", 36.0), poll("2026-06-15", "TP", 38.0)])
    summary = summarize(df)
    row = summary.iloc[0]
    assert row["n_polls"] == 2
    assert row["pollsters"] == "BiDiMedia; TP"
    assert row["last_date"] == "15/06/2026"
    assert "TP 38" in row["latest_per_pollster"]
