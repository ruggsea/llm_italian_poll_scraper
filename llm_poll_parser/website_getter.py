from selenium import webdriver
from bs4 import BeautifulSoup
import re, time, json



def start_driver():
    # Create a new instance of the Chrome driver
    driver = webdriver.Firefox()
    # Open the website
    driver.get('https://www.sondaggipoliticoelettorali.it/Home.aspx?st=HOME')

    # Find the "sondaggi" link by its text and click on it
    sondaggi_link = driver.find_element('link text', 'Sondaggi')
    sondaggi_link.click()
    
    return driver


def extract_table_data(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')

    # Initialize list to hold data
    data_list = []

    # Find all input elements
    inputs = soup.find_all('input')

    # Initialize dictionary to hold current row data
    current_row_data = {}

    # Define patterns to identify data row inputs
    for input_elem in inputs:
        # get id
        input_id = input_elem.get('id')
        # first check if the input is a data row input by checking if id contains dgSondaggi_Row
        if 'dgSondaggi_Row' not in input_id:
            continue
        # get title
        input_title = input_elem.get('title')
        # get field name, it's the last part of the id after the last underscore
        field_name = input_id.split('_')[-1]
        # row number is the one or two digits before the last underscore
        row_number = int(input_id.split('_')[-2].replace('Row', ''))
        if field_name == 'DataInserimento':
            if current_row_data:
                data_list.append(current_row_data)
            current_row_data = {'Row': row_number, 'Data Inserimento': input_title}
        elif field_name == 'Realizzatore':
            current_row_data['Realizzatore'] = input_title
        elif field_name == 'Committente':
            current_row_data['Committente'] = input_title
    
    # Append the last row if it exists
    if current_row_data:
        data_list.append(current_row_data)

    # now get the Titolo, all of them are in a td 
    tds = soup.find_all('td')
    titles = []
    for td in tds:
        title = td.get_text()
        # get rid of newlines and \t
        title = title.replace('\t', '')
        title = title.replace('\n', '')
        # skip it if it's empty or contains Pagina
        if not title or 'Pagina' in title:
            continue
        
        titles.append(title)
    
    # Add the titles to the data list
    for i, data_list_item in enumerate(data_list):
        data_list_item['Titolo'] = titles[i]
        
    return data_list
        
def find_sondaggi_table(driver):
    # Find the table element containing the sondaggi
    table = driver.find_element('id', 'lista')

    # Print the table content
    html_content = table.get_attribute('innerHTML')
    
    return extract_table_data(html_content)

def rows_intenzioni_di_voto(driver, table):
    rows_to_click = []
    # go over the table and find which rows title contains "intenzione di voto" or "sondaggio politico"
    for row in table:
        if 'intenzioni di voto' in row['Titolo'].lower() or 'sondaggio su elezioni politiche' in row['Titolo'].lower() or "monitor italia" in row['Titolo'].lower() or "osservatorio italia" in row['Titolo'].lower() or "sondaggio su elezioni nazionali" in row['Titolo'].lower():
            # return the row number and data inserimento
            rows_to_click.append(row['Row'])
    return rows_to_click

def click_on_row(driver, row):
    # find the input element to click, it is an eliment the id of which contains dgSondaggi_Row{row}_DataInserimento
    input_elem=driver.find_element('id', f'ctl00_Contenuto_dgSondaggi_Row{row}_DataInserimento')
    # click on it once
    input_elem.click()
    # wait for the page to load
    driver.implicitly_wait(0.01)
    
def click_on_domande(driver):
    # find the domande element, it has id ctl00_Titolo_TabSondaggio_DomandeRisposte
    domande_elem = driver.find_element('id', 'ctl00_Titolo_TabSondaggio_DomandeRisposte')
    domande_elem.click()
    

def get_lista_domande(driver):
    # we want a list of the elements that contain the domande, their id look like ctl00_Contenuto_ucGestioneDomande_ucListaDomande_dgDomande_Row1_Domanda
    domande=[]
    for i in range(1, 100):
        try:
            domanda_elem = driver.find_element('id', f'ctl00_Contenuto_ucGestioneDomande_ucListaDomande_dgDomande_Row{i}_Domanda')
            # get the title of the domanda
            domanda_title = domanda_elem.get_attribute('title')
            domande.append(domanda_elem)
        except:
            break
    return domande

def get_right_domanda(driver, domande):
    
    domanda_to_click=None
    
    # we want to find the domanda that contains the word "intenzione di voto" or "sondaggio politico"
    for domanda in domande:
        titolo_domanda = domanda.get_attribute('title')
        if 'elezioni nazionali' in titolo_domanda.lower() or 'intenzioni di voto' in titolo_domanda.lower() or "elezioni politiche" in titolo_domanda.lower() or "votasse oggi" in titolo_domanda.lower() or "borsino dei partiti" in titolo_domanda.lower():
            # find the element again and click on it
            domanda_to_click = driver.find_element('id', domanda.get_attribute('id'))
            domanda_to_click.click()
            # print(f'Clicked on {titolo_domanda}')
            break
    if not domanda_to_click:
        # if we didn't find the right domanda, click on the first one
        domanda_to_click = driver.find_element('id', domande[0].get_attribute('id'))
        domanda_to_click.click()
        # print(f'Clicked on {domande[0].get_attribute("title")}')
    return titolo_domanda
        
def get_testo_risposta(driver):
    # find the element that contains the testo risposta with id ctl00_Contenuto_ucGestioneDomande_ucSchedaDomandaReadOnly_Risposta
    testo_risposta_elem = driver.find_element('id', 'ctl00_Contenuto_ucGestioneDomande_ucSchedaDomandaReadOnly_Risposta')
    # get the text
    testo_risposta = testo_risposta_elem.text
    return testo_risposta       

def parse_allegato_table(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Find the table
    table = soup.find('table', {'summary': 'Allegato Domanda'})
        
    # Initialize dictionary to hold data
    table_data = {}

    # if n rows is 0, return None
    if len(table.find_all('tr')) == 0:
        return None
    
    # Iterate over each row in the table
    for row in table.find_all('tr'):
        cols = row.find_all('td')
        # Ensure there are two columns
        if len(cols) == 2:
            key = cols[0].get_text(strip=True)
            value = cols[1].get_text(strip=True)
            # Add to the dictionary
            table_data[key] = value
            
    return table_data


def get_risposta_or_allegato(driver):
     # Get risposta
    testo_risposta = get_testo_risposta(driver)
    attachment_html = driver.page_source  
    
    allegato_data = None
    # Extract and parse the allegato table
    try:
        allegato_data = parse_allegato_table(attachment_html)
        # stringifying the dictionary
        allegato_data = json.dumps(allegato_data)
    except:
        pass
    finally:
        if allegato_data:
            return allegato_data   
        else:
            return testo_risposta

def go_back_to_sondaggi(driver):
    # go back 3 times
    for i in range(3):
        driver.back()
        
def get_prossima_pagina(driver):
    # find the element that contains the prossima pagina, a button with id ctl00_Contenuto_dgSondaggi_PaginaSuccessiva
    prossima_pagina_button = driver.find_element('id', 'ctl00_Contenuto_dgSondaggi_PaginaSuccessiva')
    # click on it
    prossima_pagina_button.click()
    time.sleep(2)
    
    
def handle_one_sondaggio(driver, rownumber):
    # Click on the sondaggio
    click_on_row(driver, rownumber)   
    # Click on domande
    click_on_domande(driver)
    domande=get_lista_domande(driver)
    right_domanda=get_right_domanda(driver, domande)    
    testo_sondaggio = get_risposta_or_allegato(driver)
    
    # Go back to the sondaggi page
    go_back_to_sondaggi(driver)
    driver.implicitly_wait(0.5)
    
    return right_domanda, testo_sondaggio
    
def get_poll_data(driver):
    # Find the table containing the sondaggi
    table = find_sondaggi_table(driver)
    
    # Find the rows that contain intenzioni di voto
    rows_to_click = rows_intenzioni_di_voto(driver, table)
    
    testi_sondaggi = []
    # handle on each row
    for row in rows_to_click:
        try:
            right_domanda, testo_sondaggio = handle_one_sondaggio(driver, row)
            testi_sondaggi.append((row, right_domanda, testo_sondaggio))
        except Exception as e:
            print(f"Error handling sondaggio: {e}")
            testi_sondaggi.append((row, None, None))
        
    return testi_sondaggi

   
   
if __name__ == "__main__":
    driver = start_driver()
    testi_sondaggi=get_poll_data(driver)
    
    # test getting the next page
    get_prossima_pagina(driver)
    
    # Close the driver
    driver.quit()