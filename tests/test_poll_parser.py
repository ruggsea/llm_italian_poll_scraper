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
                    "Altri": 3
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
    Altri: 1%
    """
    


    # Call the function to test
    result = parse_poll_results(text_input=mock_poll_text)


    # Assert the result matches the expected result
    assert result == mock_response

if __name__ == "__main__":
    pytest.main()