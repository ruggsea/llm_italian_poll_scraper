"""
Command-line entrypoints for the favorability v2 pipeline.

Run from the repo root:
    uv run python -m llm_poll_parser.favorability.cli crawl --min-date 01/07/2025
    uv run python -m llm_poll_parser.favorability.cli reprocess
    uv run python -m llm_poll_parser.favorability.cli average
    uv run python -m llm_poll_parser.favorability.cli plot
"""

import argparse
import logging
from datetime import datetime


def _add_common(parser):
    parser.add_argument("--no-llm", action="store_true",
                        help="never call the LLM; fallback tables go to the review queue")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    crawl_parser = subparsers.add_parser("crawl", help="crawl the archive (resumable)")
    crawl_parser.add_argument("--min-date", default="01/07/2025",
                              help="crawl back to this deposit date (dd/mm/yyyy)")
    crawl_parser.add_argument("--max-pages", type=int, default=200)
    crawl_parser.add_argument("--no-headless", action="store_true")
    _add_common(crawl_parser)

    reprocess_parser = subparsers.add_parser(
        "reprocess",
        help="offline deterministic replay of favorability_raw.jsonl "
             "(no selenium, no API: LLM tables reuse their ledger-cached payload)")
    reprocess_parser.add_argument(
        "--llm", action="store_true",
        help="ALSO call the LLM live for fallback tables that have no cached "
             "payload in the raw ledger (default: they go to the review queue)")

    subparsers.add_parser(
        "average", help="write favorability_averages.csv from the rows ledger")

    subparsers.add_parser("plot", help="write favorability_plot.png")

    daily_parser = subparsers.add_parser(
        "daily", help="crawl only NEW deposits since last run, then rewrite "
                      "averages+plot (idempotent, depth-bounded; for CI/cron)")
    daily_parser.add_argument("--max-pages", type=int, default=10)
    daily_parser.add_argument("--no-headless", action="store_true")
    _add_common(daily_parser)   # --no-llm

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    if args.command == "crawl":
        from .crawler import crawl

        min_date = datetime.strptime(args.min_date, "%d/%m/%Y")
        state = crawl(min_date, max_pages=args.max_pages, headless=not args.no_headless,
                      llm_enabled=not args.no_llm)
        print(f"raw records: {len(state.raw)}, rows: {len(state.rows)}, "
              f"review queue: {len(state.review)}")

    elif args.command == "reprocess":
        from .crawler import reprocess

        state = reprocess(llm_enabled=args.llm)
        print(f"raw records: {len(state.raw)}, rows: {len(state.rows)}, "
              f"review queue: {len(state.review)}")

    elif args.command == "average":
        from .averaging import load_rows, summarize, write_summary

        summary = summarize(load_rows())
        write_summary(summary)
        with_average = summary[summary["cross_pollster_average"].notna()] if not summary.empty else summary
        print(summary.to_string(index=False, max_colwidth=40))
        print(f"\n{len(summary)} (entity, metric) series, "
              f"{len(with_average)} with a cross-pollster average")

    elif args.command == "plot":
        from .averaging import load_rows, make_plot

        make_plot(load_rows())
        print("wrote favorability_plot.png")

    elif args.command == "daily":
        from .crawler import daily_update

        state = daily_update(max_pages=args.max_pages, headless=not args.no_headless,
                             llm_enabled=not args.no_llm)
        print(f"rows: {len(state.rows)}, review queue: {len(state.review)}")


if __name__ == "__main__":
    main()
