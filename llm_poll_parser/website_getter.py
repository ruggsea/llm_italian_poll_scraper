from selenium import webdriver

# Create a new instance of the Chrome driver
driver = webdriver.Firefox()

# Open the website
driver.get('https://www.sondaggipoliticoelettorali.it/Home.aspx?st=HOME')

# Find the "sondaggi" link by its text and click on it
sondaggi_link = driver.find_element('link text', 'Sondaggi')
sondaggi_link.click()

def find_and_print_sondaggi_table(driver):
    # Find the table element containing the sondaggi
    table = driver.find_element('id', 'lista')

    # Print the table content
    print(table)

# Find and print the sondaggi table
find_and_print_sondaggi_table(driver)
# # Close the browser
# driver.quit()