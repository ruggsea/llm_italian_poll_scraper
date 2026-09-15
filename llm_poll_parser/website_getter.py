from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from bs4 import BeautifulSoup
import re, time, json, os



HOME_URL = 'https://www.sondaggipoliticoelettorali.it/Home.aspx?st=HOME'
LISTA_URL = 'https://www.sondaggipoliticoelettorali.it/ListaSondaggi.aspx?st=SONDAGGI'


def start_driver(headless=False, proxy=None, page=1):
    """Start Firefox and open the sondaggi list at `page`.

    `proxy` is "host:port" or "direct" (no proxy); None falls back to the SCRAPER_PROXY env var.
    The site tarpits some IP ranges (e.g. github actions runners), hence the proxy."""
    options = webdriver.FirefoxOptions()
    if headless:
        # if headless is True, run the browser in headless mode for github actions
        options.headless = True
        options.add_argument("--headless")
    if proxy is None:
        proxy = os.environ.get('SCRAPER_PROXY') or 'direct'
    if proxy != 'direct':
        options.proxy = webdriver.Proxy({'proxyType': 'MANUAL', 'httpProxy': proxy, 'sslProxy': proxy})
    driver = webdriver.Firefox(options=options)
    # the server randomly never answers a request (~1 in 10): fail such loads fast and retry them
    driver.set_page_load_timeout(25)
    # the site (and free proxies) can be slow: every find_element waits up to 20s for the element to appear
    driver.implicitly_wait(20)
    try:
        open_lista_sondaggi(driver, page)
    except Exception:
        driver.quit()
        raise
    return driver


def get_with_retry(driver, url, attempts=3):
    for attempt in range(attempts):
        try:
            driver.get(url)
            return
        except TimeoutException:
            print(f'Loading {url} timed out (attempt {attempt + 1}/{attempts})')
    raise TimeoutException(f'{url} did not load in {attempts} attempts')


def open_lista_sondaggi(driver, page=1):
    # Load the sondaggi list from scratch and page forward to `page`
    # (paging is an ASP.NET postback, so page N has no URL of its own).
    # The home page must come first: without its session cookie the list redirects to Home.aspx?sessionended=1
    get_with_retry(driver, HOME_URL)
    get_with_retry(driver, LISTA_URL)
    driver.find_element('id', 'lista')
    for _ in range(page - 1):
        get_prossima_pagina(driver)


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
        keywords = [
            'intenzioni di voto',
            'sondaggio su elezioni politiche',
            'monitor italia',
            'osservatorio italia',
            'sondaggio su elezioni nazionali',
            'scenari politici',
            'scenario politico',
            'quadro politico',
            'peso dei partiti',
        ]
        if any(keyword in row['Titolo'].lower() for keyword in keywords):
            # return the row number and data inserimento
            rows_to_click.append(row['Row'])
    return rows_to_click

def click_on_row(driver, row):
    # find the input element to click, it is an eliment the id of which contains dgSondaggi_Row{row}_DataInserimento
    input_elem=driver.find_element('id', f'ctl00_Contenuto_dgSondaggi_Row{row}_DataInserimento')
    # click on it once
    input_elem.click()
    
def click_on_domande(driver):
    # find the domande element, it has id ctl00_Titolo_TabSondaggio_DomandeRisposte
    domande_elem = driver.find_element('id', 'ctl00_Titolo_TabSondaggio_DomandeRisposte')
    domande_elem.click()
    

def get_lista_domande(driver):
    # postback clicks don't block until the next page is loaded, so first wait for the domande grid to exist
    driver.find_element('id', 'ctl00_Contenuto_ucGestioneDomande_ucListaDomande_dgDomande')
    # the domande elements have ids like ctl00_Contenuto_ucGestioneDomande_ucListaDomande_dgDomande_Row1_Domanda
    return driver.find_elements('css selector', '[id^="ctl00_Contenuto_ucGestioneDomande_ucListaDomande_dgDomande_Row"][id$="_Domanda"]')

def get_right_domanda(driver, domande):
    
    domanda_to_click=None
    
    # we want to find the domanda that contains the word "intenzione di voto" or "sondaggio politico"
    for domanda in domande:
        titolo_domanda = domanda.get_attribute('title')
        if 'elezioni nazionali' in titolo_domanda.lower() or 'intenzioni di voto' in titolo_domanda.lower() or "elezioni politiche" in titolo_domanda.lower() or "votasse oggi" in titolo_domanda.lower() or "borsino dei partiti" in titolo_domanda.lower() or "peso dei partiti" in titolo_domanda.lower():
            # find the element again and click on it
            domanda_to_click = driver.find_element('id', domanda.get_attribute('id'))
            domanda_to_click.click()
            # print(f'Clicked on {titolo_domanda}')
            break
    if not domanda_to_click:
        # if we didn't find the right domanda, click on the first one
        domanda_to_click = driver.find_element('id', domande[0].get_attribute('id'))
        titolo_domanda = domande[0].get_attribute('title')
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
        
    print(table)
    # Initialize dictionary to hold data
    table_data = {}

    # if n rows is 0, return None
    if len(table.find_all('tr')) == 0:
        return None
    
    headers = [header.get_text(strip=True) for header in table.find('tr').find_all('td')]
    # Iterate over each row in the table
    for row in table.find_all('tr')[1:]:
        cols = row.find_all('td')
        if len(cols) >= len(headers):
            key = cols[0].get_text(strip=True)
            values = {}
            for i, col in enumerate(cols[1:], 1):
                values[headers[i]] = col.get_text(strip=True)
            # Add to the dictionary
            table_data[key] = values
            
            
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

def back_to_lista(driver, page=1):
    # 3 backs are cheaper than reloading the list and paging forward again; reload if a back stalls
    try:
        for i in range(3):
            driver.back()
        driver.find_element('id', 'lista')
    except Exception as e:
        print(f'Going back to the list failed ({type(e).__name__}), reloading it')
        open_lista_sondaggi(driver, page)

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
    return right_domanda, testo_sondaggio
    
ROW_ATTEMPTS = 3

def get_poll_data(driver, page=1, upto_row=None):
    # Find the table containing the sondaggi
    table = find_sondaggi_table(driver)
    
    # Find the rows that contain intenzioni di voto (only above `upto_row` when given)
    rows_to_click = rows_intenzioni_di_voto(driver, table)
    if upto_row is not None:
        rows_to_click = [row for row in rows_to_click if row < upto_row]
    
    testi_sondaggi = []
    # each row takes ~6 requests and the server (or a free proxy) randomly drops one, so a row gets
    # a few attempts, reloading the list in between. Running out of attempts raises so the caller can switch proxy.
    for row in rows_to_click:
        for attempt in range(ROW_ATTEMPTS):
            try:
                right_domanda, testo_sondaggio = handle_one_sondaggio(driver, row)
                break
            except Exception as e:
                print(f"Error handling sondaggio at row {row} (attempt {attempt + 1}/{ROW_ATTEMPTS}): {str(e)[:200]}")
                if attempt == ROW_ATTEMPTS - 1:
                    raise
                open_lista_sondaggi(driver, page)
        testi_sondaggi.append((row, right_domanda, testo_sondaggio))
        back_to_lista(driver, page)
        
    return testi_sondaggi

   
   
if __name__ == "__main__":
    driver = start_driver()
    testi_sondaggi=get_poll_data(driver)
    
    # test getting the next page
    get_prossima_pagina(driver)
    
    # Close the driver
    driver.quit()