import json
import logging
import re
from website_getter import (start_driver, find_sondaggi_table, get_prossima_pagina,
                            click_on_row, click_on_domande, get_lista_domande,
                            get_risposta_or_allegato, go_back_to_sondaggi)
from favorability_parser import parse_favorability
from favorability_average import write_averages

FILENAME = "favorability_polls.jsonl"

# a question is worth parsing if its title mentions approval/trust
RELEVANT = re.compile(r"(?i)gradiment|fiducia|giudizi|apprezzament|indice")

# messy Realizzatore strings -> one canonical pollster name, so a series is one
POLLSTERS = [("ipsos", "Ipsos"), ("emg", "EMG"), ("piepoli", "Piepoli"),
             ("termome", "Termometro Politico"), ("lab", "LAB21"), ("bidimedia", "BiDiMedia"),
             ("swg", "SWG"), ("demopolis", "Demopolis"), ("demos", "Demos&Pi"), ("tecn", "Tecnè"),
             ("youtrend", "Youtrend"), ("only numbers", "Only Numbers"), ("eumetra", "Eumetra"),
             ("noto", "Noto"), ("izi", "IZI"), ("winpoll", "Winpoll"), ("ix", "Ixè")]


def normalize_pollster(realizzatore):
    low = (realizzatore or "").lower()
    for key, name in POLLSTERS:
        if key in low:
            return name
    return realizzatore


def favorability_questions(driver, row):
    # open one archive document and yield (title, text) for every gradimento/fiducia
    # question in it (the main scraper only ever reads the voting-intention one)
    click_on_row(driver, row)
    click_on_domande(driver)
    titles = [(d.get_attribute("id"), d.get_attribute("title")) for d in get_lista_domande(driver)]
    found = []
    for elem_id, title in titles:
        if not RELEVANT.search(title or ""):
            continue
        driver.find_element("id", elem_id).click()
        found.append((title, get_risposta_or_allegato(driver)))
        driver.back()
        driver.implicitly_wait(1)
    go_back_to_sondaggi(driver)
    driver.implicitly_wait(1)
    return found


def load_seen():
    try:
        rows = [json.loads(l) for l in open(FILENAME) if l.strip()]
    except FileNotFoundError:
        rows = []
    seen = {(r["deposit_date"], r.get("source_title")) for r in rows}
    return rows, seen


def crawl(full=False, max_pages=300):
    # full=False: daily incremental, stop after 2 pages of only-already-seen docs.
    # full=True: backfill, ignore what's saved and crawl the whole archive from
    # scratch until pagination ends. Both share this one loop.
    logging.basicConfig(level=logging.INFO)
    old_rows, seen = ([], set()) if full else load_seen()
    driver = start_driver(headless=True)
    new_rows, pages_all_seen = [], 0
    for _ in range(max_pages):
        new_this_page = 0
        for doc in find_sondaggi_table(driver):
            if (doc["Data Inserimento"], doc["Titolo"]) in seen:
                continue
            pollster = normalize_pollster(doc.get("Realizzatore"))
            try:
                questions = favorability_questions(driver, doc["Row"])
            except Exception as exc:
                # don't mark seen: a transient blip shouldn't permanently skip this doc
                logging.error(f"{doc['Titolo']}: {exc}")
                continue
            seen.add((doc["Data Inserimento"], doc["Titolo"]))  # parsed OK, don't reprocess
            new_this_page += 1
            for title, text in questions:
                for r in parse_favorability(f"{title}\n{text}"):
                    new_rows.append({"pollster": pollster, "deposit_date": doc["Data Inserimento"],
                                    "source_title": doc["Titolo"], **r})
            logging.info(f"{doc['Data Inserimento']} {pollster} - {doc['Titolo']}")
        if not full:
            # incremental: stop once recent pages are entirely already-seen
            pages_all_seen = pages_all_seen + 1 if new_this_page == 0 else 0
            if pages_all_seen >= 2:
                break
        try:
            get_prossima_pagina(driver)
        except Exception:
            break  # reached the last archive page
    driver.quit()

    with open(FILENAME, "w") as file:
        file.write("\n".join(json.dumps(r, ensure_ascii=False) for r in new_rows + old_rows) + "\n")
    write_averages()
    logging.info(f"Added {len(new_rows)} rows, {len(new_rows) + len(old_rows)} total")


def daily_update():
    crawl(full=False)


def backfill():
    crawl(full=True)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "backfill":
        backfill()
    else:
        daily_update()
