from website_getter import get_poll_data, get_prossima_pagina, start_driver, find_sondaggi_table
from archiving_polls import handle_one_pagina
from calculating_average import load_and_process_data, make_temporal_plot, calculate_moving_average, parties_list, party_colors
import json, logging, time
from typing import Union
import json

def add_beginning_of_file(filename: str, poll_data: Union[dict, list[dict]]) -> None:
    # either a dict or a list of dicts should be appended to the beginning of the jsonl file
    # if only one dict is passed, it is converted to a list of one dict
    if isinstance(poll_data, dict):
        poll_data = [poll_data]
    
    with open(filename, "r") as file:
        data = file.read()
    with open(filename, "w") as file:
        for poll in poll_data:
            serialized_data = json.dumps(poll)
            file.write(serialized_data + "\n")
        for line in data:
            file.write(line)
        
        
def get_latest_poll_from_file(filename: str) -> dict:
    # Get the latest poll data from the file
    # the latest poll is one with the highest date, the date is in the format "dd/mm/yyyy" and in the field Data Inserimento
    with open(filename, "r") as file:
        lines = file.readlines()
        
    polls=[]
    # make the date actually a date object
    for line in lines:
        poll = json.loads(line)
        poll["date"] = time.strptime(poll["Data Inserimento"], "%d/%m/%Y")
        polls.append(poll)
        
    # sort the polls by date
    polls.sort(key=lambda x: x["date"])
    
    # return the latest poll 
    return polls[-1]

def get_polls_until_latest_saved(driver, filename):
    # Get the latest poll data from the file
    latest_poll = get_latest_poll_from_file(filename)
    # Get the date of the latest poll
    latest_date = latest_poll["Data Inserimento"]
    # Committente latest poll
    latest_committente = latest_poll["Committente"]
    # Titolo latest poll
    latest_titolo = latest_poll["Titolo"]
    
    logging.info(f"Latest poll is the one dated {latest_date} from {latest_committente} with the title {latest_titolo}")
    # Get the poll data from the website
    poll_data = []
    while True:
        # Get the poll data from the current page
        one_page_poll_data = handle_one_pagina(driver)
        # iterate through the polls on the page and see if there is a match
        for poll in one_page_poll_data:
            # if the poll is the latest one, stop the loop
            if poll["Data Inserimento"] == latest_date and poll["Committente"] == latest_committente and poll["Titolo"] == latest_titolo:
                logging.info(f"Found the latest poll already saved in the file, adding {len(poll_data)} new polls to the file")
                return poll_data
            else:
                poll_data.append(poll)


def main():
    filename = "italian_polls.jsonl"
    logging.basicConfig(level=logging.INFO)
    # Check if a StreamHandler is already added to the root logger
    if not any(isinstance(handler, logging.StreamHandler) for handler in logging.getLogger().handlers):
        # Add a StreamHandler to print logs to the terminal
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        console_handler.setFormatter(console_formatter)
        logging.getLogger().addHandler(console_handler)

    driver = start_driver(headless=True)
    logging.info("Started the driver")
    # Get the poll data until the latest saved poll
    poll_data = get_polls_until_latest_saved(driver, filename)
    # Add the poll data to the file
    add_beginning_of_file(filename, poll_data)
    
    # calculate the averages, put them at the beginning of the readme.md file
    polls=load_and_process_data(filename)
    moving_averages=calculate_moving_average(polls)
    # string to add to the readme.md file: the last moving average per party
    last_moving_average = moving_averages.iloc[-1].to_markdown()
    # add the moving averages to the beginning of the readme.md file
    with open("readme.md", "r") as file:
        readme = file.readlines()
    # substitute the old moving averages with the new ones, they are on different lines
    # get rid of everything in the last moving averages section
    start_index = readme.index("## Media di oggi\n")
    end_index = readme.index("## Grafico\n")
    
    string_to_use= ""
    for party in parties_list:
        string_to_use += f"{party}: {moving_averages[party].iloc[-1]:.2f}%\n"
    # add the new moving averages
    readme[start_index+2:end_index] = [string_to_use]
    
    logging.info("Substituted the old moving averages with the new ones")
    
    # write the new readme.md file
    with open("readme.md", "w") as file:
        file.writelines(readme)
    logging.info("Added the new moving averages to the readme.md file")
    
    # make the temporal plot
    make_temporal_plot(moving_averages, polls)

if __name__ == "__main__":
    main()
    