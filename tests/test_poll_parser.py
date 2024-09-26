# tests/test_poll_parser.py
import pytest
import json
from llm_poll_parser.poll_parser import parse_poll_results
import openai


def test_parse_poll_data():
    # Mock the OpenAI response
    mock_response = {
        "Partito Democratico": 20,
        "Forza Italia": 10,
        "Fratelli d'Italia": 15,
        "Alleanza Verdi Sinistra": 5,
        "Lega": 12,
        "Movimento 5 Stelle": 18,
        "+Europa": 3,
        "Azione": 4,
        "Italia Viva": 2,
        "Stati Uniti d'Europa": None,
        "Pace Terra Dignità": None,
        "Azione - Italia Viva": None,
        "Azione/+Europa": None,
        "Sinistra Ecologia Libertà": None,
        "Scelta Civica": None,
        "Unione di Centro": None,
        "Sud Chiama Nord": None,
        "Unione Popolare": None,
        "Altri": 3,
        "national_poll":1
    }
    
    mock_poll_text= """
    Partito Democratico: 20%
    Forza Italia: 10%
    Fratelli d'Italia: 15%
    Alleanza Verdi Sinistra: 5%
    Lega: 12%
    Movimento 5 Stelle: 18%
    +Europa: 3%
    Azione: 4%
    Italia Viva: 2%
    Sud Tiroler Volkspartei: 1%
    Partito che non esiste: 1%
    Altri partiti: 1%
    """
    


    # Call the function to test
    result = parse_poll_results(text_input=mock_poll_text)

    # remove national poll rationale
    print(result.pop("national_poll_rationale"))
    # Assert the result matches the expected result
    assert result == mock_response

if __name__ == "__main__":
    pytest.main()