import pytest
import json
from llm_poll_parser.website_getter import parse_allegato_table

with open('tests/piepoli_test.html', 'r') as file:
    piepoli_html = file.read()

with open('tests/corsera_test.html', 'r') as file:
    corsera_html = file.read()
        
def test_parse_allegato_table():
    
    # Call the function to test
    result = parse_allegato_table(piepoli_html)
    
    print(result)
    
    assert len(result)>10
    
    corsera_result= parse_allegato_table(corsera_html)
    
    assert len(corsera_result)>10
    
if __name__ == "__main__":
    pytest.main()
