from openai import OpenAI
import os
import json
from typing import Dict, Optional
from dotenv import load_dotenv  

# load the .env file from the root directory
load_dotenv(override=True)

print(os.getenv("OPENAI_API_KEY"))

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
    You are a system that converts text input of Italian political poll results into a JSON object with the percentages for the following political parties:
    - Partito Democratico
    - Forza Italia
    - Fratelli d'Italia
    - Alleanza Verdi Sinistra
    - Lega
    - Movimento 5 Stelle
    - +Europa
    - Azione
    - Italia Viva
    - Altri (sum of all other parties not listed above)

    If any of the specified parties are missing, include them with a null value. For "Altri", sum up the percentages of the other parties that appear in the text input but are not listed above. It does not need to add up to 100%, just the percentages of the parties mentioned in the text input, stick to the party mentioned in the text input and ignore nonresponders or other irrelevant percentages.
    """

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    
    # Prompt GPT to perform the task using the specified model
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text_input}
        ],
        temperature=0.0,
        response_format={"type": "json_object"}
    )
    
    response_text = response.choices[0].message.content
    
    total_tokens = response.usage.total_tokens
    
    # print(f"Total tokens: {total_tokens}")
    
    # Extract the answer from the GPT response
    data=json.loads(response_text)
    
    # Ensure the data matches the expected format
    expected_keys = [
        "Partito Democratico", "Forza Italia", "Fratelli d'Italia",
        "Alleanza Verdi Sinistra", "Lega", "Movimento 5 Stelle",
        "+Europa", "Azione", "Italia Viva", "Altri"
    ]
    
    # Create a dictionary with the expected keys and set missing ones to None
    result = {key: data.get(key, None) for key in expected_keys}
    
    print(result)
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