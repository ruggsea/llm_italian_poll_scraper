from openai import OpenAI
import os
import json
from dotenv import load_dotenv

load_dotenv(override=True)

# Leader/government approval polls come on several incompatible scales; the LLM
# labels each number with its metric so we never average different scales
# together. Surnames are mapped to canonical names so a leader is one series.
metrics = ["fiducia_pct", "gradimento_index", "giudizi_positivi_pct",
           "most_trusted_share", "voto_medio_1_10"]

roster = {
    "meloni": "Giorgia Meloni", "conte": "Giuseppe Conte", "schlein": "Elly Schlein",
    "tajani": "Antonio Tajani", "salvini": "Matteo Salvini", "vannacci": "Roberto Vannacci",
    "calenda": "Carlo Calenda", "renzi": "Matteo Renzi", "mattarella": "Sergio Mattarella",
}


def canonical_entity(name):
    # "Giuseppe Conte - M5S" / "GIUSEPPE CONTE" -> "Giuseppe Conte"; "Governo" -> "Governo".
    # Unknown names are kept, just tidied, so nothing is silently dropped.
    clean = name.split(" - ")[0].split("(")[0].strip(" .:-–")
    low = clean.lower()
    if "governo" in low and "presidente del consiglio" not in low:
        return "Governo"
    for surname, full in roster.items():
        if surname in low:
            return full
    if "presidente della repubblica" in low:
        return "Sergio Mattarella"
    return clean.title() if (clean.isupper() or clean.islower()) else clean


system_prompt = """You extract Italian LEADER and GOVERNMENT approval numbers (gradimento/fiducia) from ONE poll table. These are all NATIONAL by nature (a leader-approval battery IS national).

Set national=0 with rows=[] ONLY if the table is a SUBGROUP breakdown (values split by CENTRO DESTRA / CENTRO SINISTRA / a party electorate, "per schieramento/orientamento politico") or an explicitly local/regional poll. Otherwise national=1 and extract EVERY leader/government row.

metric MUST be exactly one of:
- "most_trusted_share": a ranking where respondents pick ONE most-trusted leader; many leaders each with a % that TOGETHER sum to ~100. Emit every leader.
- "gradimento_index": positives computed among ONLY those who express an opinion (i.e. net of non-responses). Triggers: "INDICE DI GRADIMENTO", "Indice gradimento 0-100", "esclusi i non sa", "al netto delle non risposte / dei non rispondenti", "tra chi si esprime", positives over expressers. This is a DIFFERENT number from full-sample trust even for the same leader, so it is NEVER fiducia_pct. For an Ipsos government/PM table giving "voti positivi X% / voti negativi Y%", emit BOTH a gradimento_index row = round(100*X/(X+Y)) and a giudizi_positivi_pct row = X.
- "giudizi_positivi_pct": raw % positive over the FULL sample ("valutazione >= 6", "giudizio positivo"), NOT divided by expressers and NOT net of non-responses.
- "fiducia_pct": trust molta+abbastanza over the full sample (a 4-point molta/abbastanza/poca/nulla scale).
- "voto_medio_1_10": mean score on a 1-10 scale.

entity = the leader's name (e.g. "Giuseppe Conte") or "Governo"; never a party or a subgroup. value = a number without the % sign. Never mix metric families."""

json_schema = {
    "type": "object",
    "properties": {
        "national": {"type": "integer"},
        "rows": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "entity": {"type": "string"},
                    "metric": {"type": "string", "enum": metrics},
                    "value": {"type": "number"},
                },
                "required": ["entity", "metric", "value"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["national", "rows"],
    "additionalProperties": False,
}


def parse_favorability(text_input):
    """Parse one favorability/approval poll table into a list of
    {"entity", "metric", "value"} rows. Returns [] for subgroup/local tables or
    non-favorability text. Entities are normalised; out-of-range values dropped."""
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    response = client.chat.completions.create(
        model="gpt-4o",
        temperature=0.0,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text_input[:4000]},
        ],
        response_format={"type": "json_schema", "json_schema": {
            "name": "Favorability", "schema": json_schema, "strict": True}},
    )
    data = json.loads(response.choices[0].message.content)
    if not data.get("national"):
        return []
    rows = []
    for row in data["rows"]:
        value = row["value"]
        if value is None or not (0 <= value <= 100):
            continue
        rows.append({"entity": canonical_entity(row["entity"]),
                     "metric": row["metric"], "value": float(value)})
    return rows
