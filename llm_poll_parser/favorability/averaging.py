"""
Per-(entity, metric) averaging — NEVER pools across metrics (different scales)
and never normalizes to 100 (approval numbers are not shares).

- Series key = (entity, metric); population=national, published (non-derived)
  rows only; roster entities only for the cross-pollster layer.
- Supermedia rule: one poll per pollster per 14-day window (most recent wave
  wins) before averaging.
- Cross-pollster average decays in CALENDAR TIME, not poll index: each point
  is the weighted mean of all prior points, weight = 0.5 ** (age_days /
  halflife), so a slow pollster's months-old wave cannot carry the same weight
  as this week's wave. Waves older than RECENCY_CUTOFF_DAYS before the anchor
  date get zero weight (they still count toward provenance: n_polls,
  n_pollsters, latest_per_pollster).
- Every summary row carries n_pollsters and the cross-pollster line is
  suppressed where n_pollsters < 2 (sparse series stay per-pollster only).
"""

import pandas as pd

AVERAGES_CSV_FILENAME = "favorability_averages.csv"
PLOT_FILENAME = "favorability_plot.png"
DEDUP_WINDOW_DAYS = 14
EWMA_HALFLIFE_DAYS = 14.0
RECENCY_CUTOFF_DAYS = 60


def load_rows(jsonl_filename="favorability_polls.jsonl"):
    """Long rows -> dataframe restricted to the averageable universe."""
    df = pd.read_json(jsonl_filename, lines=True, convert_dates=False)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["deposit_date"], format="%d/%m/%Y")
    mask = (df["population"] == "national") & (~df["derived"].astype(bool))
    return df[mask].sort_values("date").reset_index(drop=True)


def dedup_pollster_waves(df, window_days=DEDUP_WINDOW_DAYS):
    """One poll per (pollster, entity, metric) per window; most recent wave wins.

    Walking each series newest-first, a wave is dropped when a KEPT newer wave
    of the same pollster is less than `window_days` days ahead of it.
    """
    kept_indices = []
    for _, group in df.groupby(["pollster", "entity", "metric"], sort=False):
        last_kept_date = None
        for index, row in group.sort_values("date", ascending=False).iterrows():
            if last_kept_date is None or (last_kept_date - row["date"]).days >= window_days:
                kept_indices.append(index)
                last_kept_date = row["date"]
    return df.loc[sorted(kept_indices)].sort_values("date").reset_index(drop=True)


def ewma_series(df, halflife_days=EWMA_HALFLIFE_DAYS, cutoff_days=RECENCY_CUTOFF_DAYS):
    """Calendar-time-decayed cross-pollster average per (entity, metric).

    Each point's moving_average is the weighted mean of the series' points up
    to that date, weight = 0.5 ** (age_days / halflife_days); points older
    than cutoff_days before the anchor date get zero weight. Returns a NEW
    dataframe with a moving_average column (input untouched).
    """
    averaged = df.sort_values("date").copy()
    averaged["moving_average"] = pd.NA
    for _, group in averaged.groupby(["entity", "metric"], sort=False):
        dates, values = group["date"], group["value"]
        moving = []
        for anchor in dates:
            age_days = (anchor - dates).dt.days
            weights = (0.5 ** (age_days / halflife_days)).where(
                (age_days >= 0) & (age_days <= cutoff_days), 0.0
            )
            moving.append((values * weights).sum() / weights.sum())
        averaged.loc[group.index, "moving_average"] = moving
    averaged["moving_average"] = averaged["moving_average"].astype(float)
    return averaged


def summarize(df, halflife_days=EWMA_HALFLIFE_DAYS, window_days=DEDUP_WINDOW_DAYS):
    """One summary row per (entity, metric): latest average + provenance.

    average is blank when n_pollsters < 2 (single-pollster series are published
    per-pollster only, never as a cross-pollster line).
    """
    if df.empty:
        return pd.DataFrame()
    deduped = dedup_pollster_waves(df, window_days=window_days)
    averaged = ewma_series(deduped, halflife_days=halflife_days)
    summaries = []
    for (entity, metric), group in averaged.groupby(["entity", "metric"]):
        group = group.sort_values("date")
        pollsters = sorted(group["pollster"].unique())
        latest_per_pollster = {
            pollster: f"{sub.iloc[-1]['value']:g} ({sub.iloc[-1]['date']:%d/%m/%Y})"
            for pollster, sub in group.groupby("pollster")
        }
        summaries.append({
            "entity": entity,
            "metric": metric,
            "entity_in_roster": bool(group.iloc[-1]["entity_in_roster"]),
            "n_polls": len(group),
            "n_pollsters": len(pollsters),
            "pollsters": "; ".join(pollsters),
            "first_date": f"{group.iloc[0]['date']:%d/%m/%Y}",
            "last_date": f"{group.iloc[-1]['date']:%d/%m/%Y}",
            "latest_value": group.iloc[-1]["value"],
            "cross_pollster_average": (
                round(group.iloc[-1]["moving_average"], 1) if len(pollsters) >= 2 else None
            ),
            "latest_per_pollster": "; ".join(
                f"{pollster} {value}" for pollster, value in sorted(latest_per_pollster.items())
            ),
        })
    summary = pd.DataFrame(summaries)
    return summary.sort_values(
        ["entity_in_roster", "n_polls"], ascending=[False, False]
    ).reset_index(drop=True)


def write_summary(summary, filename=AVERAGES_CSV_FILENAME):
    import os

    temp = f"{filename}.tmp"
    summary.to_csv(temp, index=False)
    os.replace(temp, filename)


def make_plot(df, halflife_days=EWMA_HALFLIFE_DAYS, filename=PLOT_FILENAME):
    """Per-pollster points + cross-pollster average line (only where n>=2) for
    the roster (entity, metric) series with the most polls."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    deduped = dedup_pollster_waves(df)
    averaged = ewma_series(deduped, halflife_days=halflife_days)
    roster = averaged[averaged["entity_in_roster"].astype(bool)]
    top_series = (
        roster.groupby(["entity", "metric"]).size().sort_values(ascending=False).head(6).index
    )
    fig, axes = plt.subplots(len(top_series), 1, figsize=(12, 3 * len(top_series)), sharex=True)
    axes = [axes] if len(top_series) == 1 else list(axes)
    for ax, (entity, metric) in zip(axes, top_series):
        group = roster[(roster["entity"] == entity) & (roster["metric"] == metric)]
        for pollster, sub in group.groupby("pollster"):
            ax.plot(sub["date"], sub["value"], "o--", alpha=0.5, markersize=4, label=pollster)
        if group["pollster"].nunique() >= 2:
            ax.plot(group["date"], group["moving_average"], "k-", linewidth=2, label="media")
        ax.set_title(f"{entity} — {metric}")
        ax.legend(fontsize=7, ncol=3)
        ax.grid(True, linestyle="--", linewidth=0.4)
    fig.tight_layout()
    fig.savefig(filename, dpi=110)
    plt.close(fig)
