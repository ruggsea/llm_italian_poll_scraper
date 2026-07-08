import pandas as pd

# Per-(entity, metric) average. Never pools across metrics (different scales).
# One poll per pollster per 14-day window; the cross-pollster average decays in
# calendar time (a slow pollster's old wave should not weigh like this week's)
# and is left blank when fewer than 2 pollsters cover the series.
HALFLIFE_DAYS = 14.0
CUTOFF_DAYS = 60
DEDUP_DAYS = 14


def load_rows(filename="favorability_polls.jsonl"):
    df = pd.read_json(filename, lines=True)
    df["date"] = pd.to_datetime(df["deposit_date"], format="%d/%m/%Y")
    return df.sort_values("date").reset_index(drop=True)


def dedup_waves(df):
    # per (pollster, entity, metric), keep the newest wave in each 14-day window
    keep = []
    for _, group in df.groupby(["pollster", "entity", "metric"], sort=False):
        last = None
        for i, row in group.sort_values("date", ascending=False).iterrows():
            if last is None or (last - row["date"]).days >= DEDUP_DAYS:
                keep.append(i)
                last = row["date"]
    return df.loc[sorted(keep)].sort_values("date").reset_index(drop=True)


def decayed_average(dates, values):
    # weighted mean at the latest date; weight 0.5**(age/halflife), 0 past cutoff
    anchor = dates.max()
    age = (anchor - dates).dt.days
    weight = (0.5 ** (age / HALFLIFE_DAYS)).where((age >= 0) & (age <= CUTOFF_DAYS), 0.0)
    return (values * weight).sum() / weight.sum()


def correct_house_effects(df):
    # Subtract each pollster's persistent bias vs the (entity, metric) consensus.
    # Spartan version (one pass, no weighting/shrinkage): bias = pollster mean −
    # overall mean, computed per (entity, metric); corrected_value = value − bias.
    # This is how aggregators stop "Tecnè always reads high" / "BiDiMedia always
    # low" from biasing the cross-pollster average. Returns a copy with a
    # corrected 'value' column; rows for a single-poll pollster collapse to the
    # consensus (no information to estimate a real bias).
    out = df.copy()
    out["value_corr"] = out["value"]
    for (entity, metric), idx in df.groupby(["entity", "metric"]).groups.items():
        g = df.loc[idx]
        consensus = g["value"].mean()
        bias = g.groupby("pollster")["value"].mean() - consensus
        out.loc[idx, "value_corr"] = g["value"].values - bias[g["pollster"]].values
    out["value"] = out["value_corr"]
    return out.drop(columns="value_corr")


def summarize(df):
    df = dedup_waves(df)
    df = correct_house_effects(df)
    rows = []
    for (entity, metric), group in df.groupby(["entity", "metric"]):
        pollsters = sorted(group["pollster"].unique())
        # each pollster's most-recent value -> the aggregator-style (Youtrend) average
        latest_val = {p: sub.sort_values("date").iloc[-1]["value"]
                      for p, sub in group.groupby("pollster")}
        latest = {p: f"{latest_val[p]:g} ({sub.sort_values('date').iloc[-1]['date']:%d/%m/%Y})"
                  for p, sub in group.groupby("pollster")}
        rows.append({
            "entity": entity,
            "metric": metric,
            "n_polls": len(group),
            "n_pollsters": len(pollsters),
            "pollsters": "; ".join(pollsters),
            "last_date": f"{group['date'].max():%d/%m/%Y}",
            # headline number: mean of each pollster's latest (how Youtrend/TP publish it)
            "latest_average": (round(sum(latest_val.values()) / len(latest_val), 1)
                               if len(latest_val) >= 2 else None),
            "cross_pollster_average": (round(decayed_average(group["date"], group["value"]), 1)
                                       if len(pollsters) >= 2 else None),
            "latest_per_pollster": "; ".join(f"{p} {v}" for p, v in sorted(latest.items())),
        })
    out = pd.DataFrame(rows)
    # headline first: Governo + PM (Meloni) on fiducia_pct, then everything else by coverage
    headline = out["entity"].isin(["Governo", "Giorgia Meloni"]) & (out["metric"] == "fiducia_pct")
    out["_hl"] = headline.astype(int)
    return out.sort_values(["_hl", "n_polls"], ascending=[False, False]).drop(columns="_hl").reset_index(drop=True)


def write_averages(filename="favorability_polls.jsonl", out="favorability_averages.csv"):
    summarize(load_rows(filename)).to_csv(out, index=False)


if __name__ == "__main__":
    write_averages()
