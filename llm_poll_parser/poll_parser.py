from openai import OpenAI
import os
import json
from typing import Dict, Optional
from dotenv import load_dotenv  

# load the .env file from the root directory
load_dotenv(override=True)


def parse_poll_results(text_input: str) -> Dict[str, Optional[float]]:
    """
    Parses the text input of Italian political poll results and returns a JSON object with the percentages
    for the specified political parties.

    Parameters:
    - text_input (str): The raw text input of poll results.

    Returns:
    - dict: A dictionary with party names as keys and their respective percentages as values. Missing parties will have a None value.
    """

    # The system prompt to instruct GPT on the task
    system_prompt = """
    You are a system that detects national voting polls and converts text input of Italian political poll question into a JSON object. Before extracting the party percentages, you need to determine if the poll is a national voting intention poll. A national poll is one that includes all the major parties (not leader approval ratings or other types of polls) and refers to nationwide voting intentions. You write your reasoning about whether the poll is a national voting intention poll or not inside the "national_poll_rationale" field and the conclusion inside the "national_poll" field (1 if it is a national poll, 0 if it is not). Then, you extract the percentages of the following parties from the text input and return them in a JSON object: 
    - Partito Democratico
    - Forza Italia (also called Popolo della Libertà or PdL before 2013)
    - Fratelli d'Italia
    - Alleanza Verdi Sinistra (also known as Verdi/Sinistra Italiana or AVS)
    - Lega (before 2018, it was known as Lega Nord)
    - Movimento 5 Stelle
    - +Europa
    - Italia Viva 
    - Stati Uniti d'Europa
    - Pace Terra Dignità (from 2024)
    - Azione - Italia Viva (Federation between Azione and Italia Viva that existed between 2022 and 2023)
    - Azione/+Europa (Federation between Azione and +Europa that existed between 2021 and 2022)
    - Sinistra Ecologia Libertà (SEL) - only if polls are from before 2017
    - Azione
    - Unione di Centro (UdC) 
    - Scelta Civica (SC, Con Monti per l'Italia alle elezioni 2013) (from 2013 to 2019)
    - Sud Chiama Nord (SCN) (from 2022)
    - Unione Popolare (UP) (from 2022)
    - Altri (sum of all other parties not listed above)
    
    Alongside the party percentages, the system returns "national_poll" 1 or 0 based on if the poll is an actual national voting intention poll or not. A national poll is one that includes all the current major parties (not leader approval ratings or head to head or other types of polls) and refers to nationwide voting intentions.  
    If any of the specified parties are missing, include them with a null value. Sum up every other party/generic "others" inside the "Altri" field (include your calculations inside national_poll_rationale). It does not need to add up to 100%, just the percentages of the parties mentioned in the text input, stick to the party mentioned in the text input and ignore nonresponders or other irrelevant percentages.
    """

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    # Ensure the data matches the expected format
    expected_keys = [
        "national_poll_rationale",
        "national_poll",
        "Partito Democratico", "Forza Italia", "Fratelli d'Italia",
        "Alleanza Verdi Sinistra", "Lega", "Movimento 5 Stelle",
        "+Europa", "Azione", "Italia Viva", "Stati Uniti d'Europa", "Pace Terra Dignità",
        "Azione - Italia Viva", "Azione/+Europa", "Sinistra Ecologia Libertà", "Scelta Civica",
        "Unione di Centro", "Sud Chiama Nord", "Unione Popolare","Altri",
    ]
    
    json_schema = {
        "type": "object",
        "properties": {
            "national_poll_rationale": {"type": "string"},
            "national_poll": {"type": "integer"},
            "Partito Democratico": {"type": ["number", "null"]},
            "Forza Italia": {"type": ["number", "null"]},
            "Fratelli d'Italia": {"type": ["number", "null"]},
            "Alleanza Verdi Sinistra": {"type": ["number", "null"]},
            "Lega": {"type": ["number", "null"]},
            "Movimento 5 Stelle": {"type": ["number", "null"]},
            "+Europa": {"type": ["number", "null"]},
            "Azione": {"type": ["number", "null"]},
            "Italia Viva": {"type": ["number", "null"]},
            "Stati Uniti d'Europa": {"type": ["number", "null"]},
            "Pace Terra Dignità": {"type": ["number", "null"]},
            "Azione - Italia Viva": {"type": ["number", "null"]},
            "Azione/+Europa": {"type": ["number", "null"]},
            "Sinistra Ecologia Libertà": {"type": ["number", "null"]},
            "Unione di Centro": {"type": ["number", "null"]},
            "Scelta Civica": {"type": ["number", "null"]},
            "Sud Chiama Nord": {"type": ["number", "null"]},
            "Unione Popolare": {"type": ["number", "null"]},
            "Altri": {"type": ["number", "null"]},
        },
        "required": ["national_poll_rationale", "national_poll", "Partito Democratico", "Forza Italia", "Fratelli d'Italia", "Alleanza Verdi Sinistra", "Lega", "Movimento 5 Stelle", "+Europa", "Azione", "Italia Viva", "Stati Uniti d'Europa", "Pace Terra Dignità", "Azione - Italia Viva", "Azione/+Europa", "Sinistra Ecologia Libertà","Unione di Centro", "Sud Chiama Nord", "Unione Popolare","Altri"]
    }
        
        
    # Prompt GPT to perform the task using the specified model
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text_input}
        ],
        temperature=0.0,
        response_format={"type": "json_schema", 
                         "json_schema": {
                            "name": "PollResults",
                            "schema": json_schema,
                            }
        }
    )
    
    response_text = response.choices[0].message.content
    
    total_tokens = response.usage.total_tokens
    
    # print(f"Total tokens: {total_tokens}")

    # Extract the answer from the GPT response
    data=json.loads(response_text)
    
    # print(data["national_poll_rationale"])
    # print(data["national_poll"])
    
    # Create a dictionary with the expected keys and set missing ones to None
    result = {key: data.get(key, None) for key in expected_keys}
    return result

if __name__ == "__main__":
    parse_poll_results("""
                       Partito Democratico: 20%
                       Forza Italia: 10%
                       Fratelli d'Italia: 15%
                       Alleanza Verdi Sinistra: 5%
                       Partito che non esiste: 1%
                       Altri: 3%
                       Non responde: 1%
                       Ci ha pensato troppo: 1%
                       """)
    
    parse_poll_results("""
                        Testo Domanda

Se oggi si votasse per l'elezione del Consiglio Comunale a quale delle seguenti liste darebbe il suo voto?
Testo Risposta

 
Area Allegato

Fratelli d'Italia 	18,5%
Partito Democratico 	16,1%
Movimento 5 Stelle 	14,2%
Carlo Calenda Sindaco 	13,8%
Lega 	6,9%
Forza Italia - UDC 	4,3%
Roma Futura 	3,6%
Sinistra Civica Ecologista 	3,4%
Lista Civica Virgina Raggi 	3,2%
Lista Civ. Gualtieri Sindaco 	2,8%
Enrico Michetti Sindaco 	2,5%
Revoluzione Civica 	1,5%
Demos 	1,0%
Europa Verde 	1,0%
Popolo della Famiglia 	0,8%
Potere al Popolo! 	0,8%
Partito Comunista 	0,7%
Roma ti Riguarda 	0,7%
Roma Ecologista 	0,5%
Rinascimento - Cambiamo! 	0,4%
Altre liste di Raggi 	0,4%
Partito Gay 	0,4%
Partito Liberale Europeo 	0,2%
Riconquistare l'Italia 	0,3%
Altre liste 	1,5%
Partito Socialista Italiano 	0""")