from poll_parser import parse_poll_results
from website_getter import get_poll_data, get_prossima_pagina, start_driver, find_sondaggi_table
import json
import logging

def serialize_poll_data(poll_data):
    # Serialize the poll data to a JSON string
    return json.dumps(poll_data)

def add_data_to_file(poll_data, filename):
    # Serialize the poll data one by one and write it to the file
    for poll in poll_data:
        serialized_data = serialize_poll_data(poll)   
        # Write the serialized data to the polls.jsonl file appending it to the file
        # if the file does not exist, it will be created
        with open(f"{filename}", "a") as file:
            file.write(serialized_data + "\n")


def handle_one_pagina(driver):
    table = find_sondaggi_table(driver)
    # Get the poll data from the current page
    poll_data = get_poll_data(driver)
    
    # poll data is a list of (rownumber, poll) tuples
    # get corresponding table rows from table
    final_dicts = []
    for rownumber, right_domanda, poll in poll_data:
        table_row = table[rownumber-1]
        # Append the poll data to the table row
        table_row["text"] = poll
        table_row["domanda"] = right_domanda
        
        # if text is None or empty, log an error
        if table_row["text"] is None or table_row["text"] == "":
            logging.error(f"Poll data is None for row {rownumber} and title {table_row['Titolo']}")
        
        # make a string that contains the poll with the domanda in the beginning
        poll_with_domanda = f"{right_domanda}\n{poll}"
        
        # call the parse_poll_results function to get the percentages
        parsed_poll = parse_poll_results(poll_with_domanda)
        table_row.update(parsed_poll)

        if table_row["national_poll"] == 1:
            final_dicts.append(table_row)

    return final_dicts
    
if __name__ == "__main__":
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

    driver = start_driver()
    logging.info('Driver started')

    # Get the first page
    table = handle_one_pagina(driver)
    logging.info('First page handled')

    # Write the data to the polls.jsonl file
    add_data_to_file(table, filename)
    logging.info('Data added to file')

    page_counter = 1
    # do it for the next pages until get_prossima_pagina fails
    while True:
        try:
            get_prossima_pagina(driver)
            logging.info(f'Page {page_counter} retrieved')
            table = handle_one_pagina(driver)
            logging.info(f'Page {page_counter} handled')
            add_data_to_file(table, filename)
            logging.info(f'Page {page_counter} data added to file')
            page_counter += 1
        except:
            logging.error('Error occurred')
            break

    driver.quit()
    logging.info('Driver quit')