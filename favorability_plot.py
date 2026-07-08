# favorability_plot.py — aggregator-style trend for the headline favorability series.
# At each date, the line = mean of each pollster's most-recent value as of that date
# (how Youtrend/Termometro Politico build the consensus). Matches the repo's plain style.
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

HEADLINE = ["Giorgia Meloni", "Governo"]
COLORS = {"Giorgia Meloni": "#1f77b4", "Governo": "#d62728"}


def _latest_per_pollster_average(group, anchor):
    # mean of each pollster's most-recent value at or before `anchor`
    sub = group[group["date"] <= anchor]
    if sub.empty:
        return None
    return sub.sort_values("date").groupby("pollster")["value"].last().mean()


def make_favorability_plot(jsonl="favorability_polls.jsonl",
                           out="favorability_plot.png", metric="fiducia_pct"):
    df = pd.read_json(jsonl, lines=True)
    df["date"] = pd.to_datetime(df["deposit_date"], format="%d/%m/%Y")
    sub = df[(df["metric"] == metric) & (df["entity"].isin(HEADLINE))].sort_values("date")

    fig, ax = plt.subplots(figsize=(11, 6.5))
    for entity, grp in sub.groupby("entity"):
        grp = grp.sort_values("date")
        ax.scatter(grp["date"], grp["value"], s=16, color=COLORS.get(entity, "k"), alpha=0.3)
        # aggregator consensus: at each poll date, mean of every pollster's latest-as-of-then
        anchors = grp["date"].drop_duplicates().sort_values()
        consensus = anchors.map(lambda a: _latest_per_pollster_average(grp, a))
        ax.plot(anchors, consensus, lw=2.2, color=COLORS.get(entity, "k"),
                label=f"{entity} (consenso, {grp['pollster'].nunique()} istituti)")
    # mark the final latest_average for each entity
    for entity, grp in sub.groupby("entity"):
        grp = grp.sort_values("date")
        last = grp["date"].max()
        val = _latest_per_pollster_average(grp, last)
        if val is not None:
            ax.annotate(f"{val:.1f}", (last, val), textcoords="offset points",
                        xytext=(6, 4), color=COLORS.get(entity, "k"), fontsize=9, fontweight="bold")

    ax.set_title("Fiducia nel Governo e nel Presidente del Consiglio\n"
                 "(consenso corretto per house-effect: bias di ciascun istituto rimosso)")
    ax.set_ylabel(f"{metric}  (molta+abbastanza, %)")
    ax.set_xlabel("Data")
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%y"))
    ax.legend(loc="lower left", fontsize=9, framealpha=0.9)
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    print(f"wrote {out}")


if __name__ == "__main__":
    make_favorability_plot()
