import json
import logging
import time
from datetime import datetime
from typing import Union
import pandas as pd
from website_getter import get_poll_data, get_prossima_pagina, start_driver, find_sondaggi_table
from archiving_polls import handle_one_pagina
from calculating_average import load_and_process_data, make_temporal_plot, calculate_moving_average, parties_list, party_colors
from poll_parser import parse_poll_results
import pandas as pd

def add_beginning_of_file(filename: str, poll_data: Union[dict, list[dict]]) -> None:
    if isinstance(poll_data, dict):
        poll_data = [poll_data]

    with open(filename, "r") as file:
        data = file.read()

    with open(filename, "w") as file:
        serialized_data = [json.dumps(poll) for poll in poll_data]
        file.write("\n".join(serialized_data) + "\n")
        file.write(data)

def get_latest_poll_from_file(filename: str) -> dict:
        polls = pd.read_json(filename, lines=True)
        polls["date"] = pd.to_datetime(polls["Data Inserimento"], format="%d/%m/%Y")
        polls.sort_values("date", inplace=True)
        latest_poll = polls.iloc[-1].to_dict()
        return latest_poll

def get_polls_until_latest_saved(driver, filename):
    latest_poll = get_latest_poll_from_file(filename)
    latest_date = latest_poll["Data Inserimento"]
    latest_committente = latest_poll["Committente"]
    latest_titolo = latest_poll["Titolo"]

    logging.info(f"Latest poll is the one dated {latest_date} from {latest_committente} with the title {latest_titolo}")

    poll_data = []
    while True:
        one_page_poll_data = handle_one_pagina(driver)
        for poll in one_page_poll_data:
            if poll["Data Inserimento"] == latest_date and poll["Committente"] == latest_committente and poll["Titolo"] == latest_titolo:
                logging.info(f"Found the latest poll already saved in the file, adding {len(poll_data)} new polls to the file")
                return poll_data
            else:
                poll_data.append(poll)
        get_prossima_pagina(driver)

def update_readme_with_moving_averages(moving_averages):
    with open("readme.md", "r") as file:
        readme = file.readlines()

    start_index = readme.index("## Media di oggi\n")
    end_index = readme.index("## Grafico\n")
    # Sort parties by top parties in the readme
    parties_list = list(moving_averages.keys())
    parties_list.sort(key=lambda party: moving_averages[party].iloc[-1], reverse=True)
    
    readme[start_index+2:end_index] = [f"{party}: {moving_averages[party].iloc[-1]:.2f}%  \n" for party in parties_list]

    with open("readme.md", "w") as file:
        file.writelines(readme)

def convert_jsonl_to_csv():
    polls = pd.read_json("italian_polls.jsonl", lines=True)
    polls.to_csv("italian_polls.csv", index=False)

def reparse(since=None):
    # Re-run the parser over the raw text already stored for each poll, so
    # parser/prompt changes (e.g. a newly added party) get applied to history
    # without re-scraping the site. `since` is a DD/MM/YYYY floor; empty = all.
    # This is what fixes a new party in old rows AND recomputes "Altri" for them.
    filename = "italian_polls.jsonl"
    logging.basicConfig(level=logging.INFO)
    polls = [json.loads(line) for line in open(filename) if line.strip()]
    since_date = datetime.strptime(since, "%d/%m/%Y") if since else None

    for poll in polls:
        if since_date and datetime.strptime(poll["Data Inserimento"], "%d/%m/%Y") < since_date:
            continue
        logging.info(f"Reparsing {poll['Data Inserimento']} - {poll['Titolo']}")
        poll.update(parse_poll_results(poll["text"]))

    with open(filename, "w") as file:
        file.write("\n".join(json.dumps(poll) for poll in polls) + "\n")

    polls = load_and_process_data(filename)
    moving_averages = calculate_moving_average(polls)
    update_readme_with_moving_averages(moving_averages)
    make_temporal_plot(moving_averages, polls)
    convert_jsonl_to_csv()

def main():
    filename = "italian_polls.jsonl"
    logging.basicConfig(level=logging.INFO)

    if not any(isinstance(handler, logging.StreamHandler) for handler in logging.getLogger().handlers):
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        console_handler.setFormatter(console_formatter)
        logging.getLogger().addHandler(console_handler)

    driver = start_driver(headless=True)
    logging.info("Started the driver")

    poll_data = get_polls_until_latest_saved(driver, filename)
    # if poll_data is empty, there are no new polls to add
    if poll_data:
        add_beginning_of_file(filename, poll_data)
    else:
        logging.info("No new polls to add to the file")

    polls = load_and_process_data(filename)
    moving_averages = calculate_moving_average(polls)

    update_readme_with_moving_averages(moving_averages)
    logging.info("Substituted the old moving averages with the new ones")

    make_temporal_plot(moving_averages, polls)
    logging.info("Made the temporal plot")

    convert_jsonl_to_csv()
    logging.info("Turned the jsonl file into a csv file")

    driver.quit()
    logging.info("Quitted the driver")

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "reparse":
        reparse(sys.argv[2] if len(sys.argv) > 2 else None)
    else:
        main()
