"""
Archive crawler + per-question processing pipeline.

Reuses the v1 scraper primitives (website_getter) but drops v1's document-title
gate: EVERY archive document is opened and its question list is filtered with
the question-level relevance filter (taxonomy.is_relevant_question). This is
what recovers the EMG/TP/SWG/Youtrend favorability questions hidden inside
"Monitor Italia"-style omnibus deposits that v1 never opened.

The processing pipeline (process_question) is pure orchestration over the
deterministic modules — classify -> extract -> validate -> ledger — with the
LLM called ONLY for step-12 fallback tables and its verbatim payload persisted
in the raw ledger. The `reprocess` command replays those cached payloads, so a
re-parse needs neither selenium nor the API and is deterministic end to end.
"""

import logging
import os
import sys
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from .classify import LLM, REJECT, REVIEW, classify  # noqa: E402
from .derive import expressers_rate_row  # noqa: E402
from .extract import run_extractor  # noqa: E402
from .ledger import (  # noqa: E402
    RAW_FILENAME,
    REVIEW_FILENAME,
    ROWS_CSV_FILENAME,
    ROWS_JSONL_FILENAME,
    build_row,
    document_key,
    load_jsonl,
    merge_raw,
    merge_review,
    merge_rows,
    raw_record,
    review_item,
    write_jsonl_atomically,
    write_rows_atomically,
)
from .taxonomy import METRIC_FIDUCIA, is_relevant_question, normalize_pollster  # noqa: E402

logger = logging.getLogger("favorability")


# --- processing pipeline (no selenium, no file io) ---------------------------------


def process_question(meta, domanda, text, client=None, llm_enabled=True,
                     cached_llm_payload=None):
    """(meta, question title, verbatim text) -> (raw_record, rows, review_items).

    meta must carry the archive columns plus pollster_norm. Never raises on
    malformed LLM output: retry once, then the question lands in the review
    queue (v1's parse_question_with_retry semantics, but nothing is dropped).

    cached_llm_payload: the LLM payload persisted in the raw ledger for THIS
    question (raw_record.llm_payload). When present, fallback tables are
    replayed from it deterministically with NO API call — even if llm_enabled
    is False. The (fresh or cached) payload is persisted on the returned raw
    record so every subsequent replay is offline.
    """
    pollster = meta.get("pollster_norm") or normalize_pollster(meta.get("Realizzatore"))
    classification = classify(pollster, domanda, text, document_title=meta.get("Titolo"))

    if classification.action == REJECT:
        return raw_record(meta, domanda, text, classification, "rejected"), [], []

    if classification.action == REVIEW:
        item = review_item(meta, domanda, text, classification.reason)
        return raw_record(meta, domanda, text, classification, "review"), [], [item]

    cached_payload = cached_llm_payload if classification.action == LLM else None
    if classification.action == LLM and cached_payload is None and not llm_enabled:
        item = review_item(meta, domanda, text, "needs LLM fallback (LLM disabled)")
        return raw_record(meta, domanda, text, classification, "review"), [], [item]

    result, error = None, None
    for attempt in (1, 2):
        try:
            result = run_extractor(classification, pollster, domanda, text, client=client,
                                   cached_payload=cached_payload)
            break
        except ValueError as exc:  # malformed LLM output - retry once, then review
            error = str(exc)
            logger.warning("%s - %r: malformed LLM output (attempt %d): %s",
                           meta.get("Data Inserimento"), (domanda or "")[:60], attempt, exc)
            if cached_payload is not None:
                break   # a cached payload is deterministic: retrying cannot help
    if result is None:
        item = review_item(meta, domanda, text, f"malformed LLM output twice: {error}")
        return raw_record(meta, domanda, text, classification, "error", error=error,
                          llm_payload=cached_payload), [], [item]

    llm_payload = result.llm_payload
    if classification.action == LLM and not result.rows and not result.review:
        return raw_record(meta, domanda, text, classification, "rejected",
                          llm_payload=llm_payload), [], []  # LLM says not favorability

    from .validate import guard_rows

    accepted, guard_reasons = guard_rows(result.rows, context=f"{pollster} {domanda!r}")
    review_reasons = list(result.review) + guard_reasons

    rows = []
    for partial in accepted:
        partial = {**partial, "pollster": pollster}
        rows.append(build_row(meta, domanda, text, classification, partial))
        if classification.extractor == "scale" and partial["metric"] == METRIC_FIDUCIA:
            derived = expressers_rate_row(partial)
            if derived is not None:
                rows.append(build_row(meta, domanda, text, classification, derived))

    items = [review_item(meta, domanda, text, reason) for reason in review_reasons]
    status = "accepted" if rows else ("review" if items else "rejected")
    record = raw_record(meta, domanda, text, classification, status, n_rows=len(rows),
                        llm_payload=llm_payload)
    return record, rows, items


# --- ledger-backed state (resume + idempotent writes) --------------------------------


class LedgerState:
    """In-memory view of the three ledgers with atomic write-through."""

    def __init__(self, raw_filename=RAW_FILENAME, jsonl_filename=ROWS_JSONL_FILENAME,
                 csv_filename=ROWS_CSV_FILENAME, review_filename=REVIEW_FILENAME):
        self.filenames = (raw_filename, jsonl_filename, csv_filename, review_filename)
        self.raw = load_jsonl(raw_filename)
        self.rows = load_jsonl(jsonl_filename)
        self.review = load_jsonl(review_filename)

    def seen_documents(self):
        return {record["document_key"] for record in self.raw}

    def ingest(self, records, rows, review_items):
        """Merge new material (existing wins) and rewrite all files atomically.
        Uniqueness conflicts are appended to the review queue, never the CSV."""
        raw_filename, jsonl_filename, csv_filename, review_filename = self.filenames
        self.raw = merge_raw(self.raw, records)
        self.rows, conflicts = merge_rows(self.rows, rows)
        conflict_items = [
            review_item({"Data Inserimento": row["deposit_date"],
                         "Realizzatore": row["pollster_raw"],
                         "Titolo": row["source_title"]},
                        row["domanda"], None,
                        f"uniqueness conflict: second {row['metric']} value for "
                        f"{row['entity']} in the same wave", payload=row)
            for row in conflicts
        ]
        self.review = merge_review(self.review, review_items + conflict_items)
        write_jsonl_atomically(self.raw, raw_filename)
        write_rows_atomically(self.rows, jsonl_filename, csv_filename)
        write_jsonl_atomically(self.review, review_filename)
        return conflicts


# --- selenium crawl (ports v1 primitives) ---------------------------------------------


def scrape_document_questions(driver, rownumber):
    """Open one archive document, return [(domanda_title, text), ...] for every
    RELEVANT question (question-level filter, no document-title gate)."""
    from website_getter import (
        click_on_domande,
        click_on_row,
        get_lista_domande,
        get_risposta_or_allegato,
    )

    click_on_row(driver, rownumber)
    click_on_domande(driver)
    domande_infos = [
        (domanda.get_attribute("id"), domanda.get_attribute("title"))
        for domanda in get_lista_domande(driver)
    ]
    targets = [(id_, title) for id_, title in domande_infos if is_relevant_question(title)]

    questions = []
    for domanda_id, domanda_title in targets:
        # re-find by id: element handles go stale after each driver.back()
        driver.find_element("id", domanda_id).click()
        time.sleep(0.5)
        questions.append((domanda_title, get_risposta_or_allegato(driver)))
        driver.back()
        time.sleep(0.5)

    # from the domande list it is two steps back to the sondaggi table
    driver.back()
    driver.back()
    time.sleep(0.5)
    return questions


def resync_to_sondaggi_table(driver, max_steps=4):
    """Best-effort recovery after a failed document click: step back through
    the browser history until the sondaggi table is visible again."""
    from website_getter import find_sondaggi_table

    for _ in range(max_steps):
        try:
            return find_sondaggi_table(driver)
        except Exception:
            driver.back()
            time.sleep(1)
    return find_sondaggi_table(driver)


def crawl(min_date, max_pages=200, headless=True, client=None, llm_enabled=True,
          state=None):
    """Crawl the archive newest-first until min_date, opening EVERY document.

    Resumable: documents whose key is already in favorability_raw.jsonl are
    skipped. Writes all ledgers after each document (atomic), so a crash loses
    at most the document in flight. Logs one line per document and per parsed
    question so progress is always visible.
    """
    from website_getter import find_sondaggi_table, get_prossima_pagina, start_driver

    state = state or LedgerState()
    seen = state.seen_documents()
    failed = set()
    previous_signature = None

    driver = start_driver(headless=headless)
    logger.info("Driver started; %d documents already in the raw ledger", len(seen))
    try:
        for page in range(1, max_pages + 1):
            table = find_sondaggi_table(driver)
            page_dates = [datetime.strptime(row["Data Inserimento"], "%d/%m/%Y") for row in table]

            signature = [document_key(row) for row in table]
            if signature == previous_signature:
                logger.warning("Pagination stalled (same page twice), stopping")
                break
            previous_signature = signature

            for table_row in table:
                row_date = datetime.strptime(table_row["Data Inserimento"], "%d/%m/%Y")
                if row_date < min_date:
                    continue
                doc_key = document_key(table_row)
                if doc_key in seen or doc_key in failed:
                    continue

                meta = {**table_row, "pollster_norm": normalize_pollster(table_row.get("Realizzatore"))}
                try:
                    questions = scrape_document_questions(driver, table_row["Row"])
                except Exception as error:
                    logger.error("%s - %s: selenium error, will retry next run: %s",
                                 table_row["Data Inserimento"], table_row["Titolo"], error)
                    failed.add(doc_key)
                    resync_to_sondaggi_table(driver)
                    continue

                records, rows, items = [], [], []
                if not questions:
                    records.append(raw_record(meta, None, None, None, "no_questions"))
                for domanda_title, text in questions:
                    record, question_rows, question_items = process_question(
                        meta, domanda_title, text, client=client, llm_enabled=llm_enabled)
                    records.append(record)
                    rows.extend(question_rows)
                    items.extend(question_items)
                    logger.info("%s | %-20s | %-9s | %-24s | rows=%d | %.60s",
                                meta["Data Inserimento"], meta["pollster_norm"],
                                record["status"], record["classification"]["table_kind"]
                                if record["classification"] else "-",
                                len(question_rows), domanda_title.replace("\n", " "))

                state.ingest(records, rows, items)
                seen.add(doc_key)
                logger.info("%s | %-20s | document done (%d questions, %d rows) | %.50s",
                            meta["Data Inserimento"], meta["pollster_norm"],
                            len(questions), len(rows), meta["Titolo"])

            logger.info("Page %d done (%s) | rows total=%d | review=%d",
                        page, table[-1]["Data Inserimento"], len(state.rows), len(state.review))
            if page_dates and min(page_dates) < min_date:
                logger.info("Reached min_date, stopping")
                break
            get_prossima_pagina(driver)
    finally:
        driver.quit()
        logger.info("Driver quit")
    return state


# --- forever-automation: depth-bounded daily update ----------------------------------

# Steady-state floor for the daily job; a full historical backfill stays the
# manual `crawl --min-date` path. The daily job never rescans the whole archive.
DEFAULT_FLOOR = "01/07/2025"
# Re-scan a short window before the newest deposit so late/backdated
# "Data Inserimento" values are still picked up; already-seen documents are
# skipped by document_key, so the only cost is a few extra seen-skips.
DAILY_LOOKBACK_DAYS = 7


def latest_seen_date(state, default_floor=DEFAULT_FLOOR):
    """Newest deposit date already in the raw ledger, or DEFAULT_FLOOR on an
    empty ledger (first run). Never scans the network."""
    parsed = [datetime.strptime(record["Data Inserimento"], "%d/%m/%Y")
              for record in state.raw if record.get("Data Inserimento")]
    return max(parsed) if parsed else datetime.strptime(default_floor, "%d/%m/%Y")


def daily_update(max_pages=10, headless=True, client=None, llm_enabled=True):
    """Crawl ONLY new deposits since the last run, then rewrite averages+plot.

    Idempotent, resumable and depth-bounded: the crawl floor is the newest
    already-seen deposit minus DAILY_LOOKBACK_DAYS, so a no-new-deposit run
    reads only the newest one to three archive pages, adds nothing, and leaves
    both CSVs byte-identical (EWMA decays per-anchor, not wall-clock). Live LLM
    stays confined to genuinely-new fallback tables inside crawl; replay is
    offline. This is the CI/cron entrypoint.
    """
    state = LedgerState()
    floor = latest_seen_date(state) - timedelta(days=DAILY_LOOKBACK_DAYS)
    logger.info("Daily update: crawling new deposits back to %s (%d already seen)",
                floor.strftime("%d/%m/%Y"), len(state.raw))
    state = crawl(floor, max_pages=max_pages, headless=headless,
                  client=client, llm_enabled=llm_enabled, state=state)

    from .averaging import load_rows, make_plot, summarize, write_summary
    rows = load_rows()
    write_summary(summarize(rows))
    make_plot(rows)
    logger.info("Daily update done: %d rows, %d review items",
                len(state.rows), len(state.review))
    return state


def reprocess(client=None, llm_enabled=False, state=None):
    """Rebuild favorability_polls.* from the raw ledger (no selenium, and by
    default NO API calls).

    Deterministic OFFLINE replay of classify/extract/validate over the verbatim
    texts: LLM-fallback tables are replayed from the payload persisted in their
    raw record (raw_record.llm_payload), so reprocessing never re-rolls the
    dice on numbers that were already extracted and validated. Only with
    llm_enabled=True (cli --llm) are fallback tables that have NO cached
    payload sent to the API; otherwise they land in the review queue.
    """
    state = state or LedgerState()
    records, rows, items = [], [], []
    for old in state.raw:
        if old.get("status") == "no_questions" or old.get("domanda") is None:
            records.append(old)
            continue
        meta = {"Data Inserimento": old.get("Data Inserimento"),
                "Realizzatore": old.get("Realizzatore"),
                "Committente": old.get("Committente"),
                "Titolo": old.get("Titolo"),
                # re-derive from the verbatim Realizzatore so normalization fixes
                # apply on replay; the stored value only covers records without one
                "pollster_norm": normalize_pollster(old.get("Realizzatore")) or old.get("pollster")}
        record, question_rows, question_items = process_question(
            meta, old["domanda"], old["text"], client=client, llm_enabled=llm_enabled,
            cached_llm_payload=old.get("llm_payload"))
        records.append(record)
        rows.extend(question_rows)
        items.extend(question_items)
        logger.info("%s | %-20s | %-9s | rows=%d | %.60s",
                    meta["Data Inserimento"], meta["pollster_norm"], record["status"],
                    len(question_rows), (old["domanda"] or "").replace("\n", " "))
    state.raw = []
    state.rows = []
    state.review = []   # review items are derived from the raw ledger: rebuild them too
    state.ingest(records, rows, items)
    return state
