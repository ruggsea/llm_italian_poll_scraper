"""
Per-table-kind extractors: mechanical (regex / JSON-key) extraction first,
LLM fallback only where code cannot read the table.

Every extractor returns an ExtractionResult(rows, review): `rows` are partial
row dicts (entity/metric/value/...; ledger.build_row adds provenance) and
`review` is a list of human-readable reasons why the table needs triage —
a table that fails its own structural contract NEVER yields rows silently.
"""

import json
import re
from dataclasses import dataclass, field

from .classify import (
    _label_class,
    get_pairs,
    split_scale_pairs,
    to_number,
)
from .derive import ipsos_index_matches, recompute_gradimento_index
from .taxonomy import (
    METRIC_FIDUCIA,
    METRIC_GIUDIZI_POSITIVI,
    METRIC_GRADIMENTO_INDEX,
    METRIC_VOTO_MEDIO,
    canonical_entity,
    entity_from_question_title,
)
from .validate import validate_llm_payload


@dataclass
class ExtractionResult:
    rows: list = field(default_factory=list)
    review: list = field(default_factory=list)
    # verbatim LLM fallback payload (parsed JSON) — persisted in the raw ledger
    # so `reprocess` can replay it offline instead of re-calling the API
    llm_payload: dict = None


def _row(entity, in_roster, metric, value, *, negative=None, dontknow=None,
         base="full_sample", scale_note=None, extraction="regex"):
    return {
        "entity": entity,
        "entity_in_roster": in_roster,
        "metric": metric,
        "value": round(float(value), 1),
        "value_negative": round(float(negative), 1) if negative is not None else None,
        "value_dontknow": round(float(dontknow), 1) if dontknow is not None else None,
        "base": base,
        "scale_note": scale_note,
        "derived": False,
        "derivation": None,
        "extraction": extraction,
    }


# --- mechanical extractors ------------------------------------------------------


def extract_scale(classification, pollster, title, text, client=None):
    """4/5-scale single-entity table -> one row (positives summed)."""
    pairs, is_json = get_pairs(text)
    scale_rows = split_scale_pairs(pairs)
    if not scale_rows:
        return ExtractionResult(review=[f"scale table without scale labels: {title!r}"])
    total = sum(value for _, _, value in scale_rows)
    if not 98 <= total <= 102:
        return ExtractionResult(review=[f"scale answers sum to {total:g}, not ~100: {title!r}"])
    entity, in_roster = entity_from_question_title(title)
    if entity is None:
        return ExtractionResult(review=[f"cannot resolve entity from title: {title!r}"])
    positives = [(label, value) for cls, label, value in scale_rows if cls == "positive"]
    negative = sum(value for cls, _, value in scale_rows if cls == "negative")
    dontknow = sum(value for cls, _, value in scale_rows if cls == "dontknow")
    value = sum(value for _, value in positives)
    note = " + ".join(f"{label.lower()} {value:g}" for label, value in positives)
    return ExtractionResult(rows=[_row(
        entity, in_roster, classification.metric, value, negative=negative,
        dontknow=dontknow or None, base="full_sample", scale_note=note,
        extraction="json_keys" if is_json else "regex",
    )])


def extract_binary(classification, pollster, title, text, client=None):
    """Forced yes/no trust -> one fiducia_binaria_pct row."""
    pairs, is_json = get_pairs(text)
    positive = next((v for label, v in pairs if re.match(r"(?i)^(hanno\s+fiducia|s[iì])$", label.strip())), None)
    negative = next((v for label, v in pairs if re.match(r"(?i)^(non\s+hanno\s+fiducia|no)$", label.strip())), None)
    if positive is None or negative is None or not 98 <= positive + negative <= 102:
        return ExtractionResult(review=[f"binary table does not sum to 100: {title!r}"])
    entity, in_roster = entity_from_question_title(title)
    if entity is None:
        return ExtractionResult(review=[f"cannot resolve entity from title: {title!r}"])
    return ExtractionResult(rows=[_row(
        entity, in_roster, classification.metric, positive, negative=negative,
        base="full_sample", scale_note=f"hanno fiducia {positive:g} / non hanno {negative:g}",
        extraction="json_keys" if is_json else "regex",
    )])


def extract_ranking(classification, pollster, title, text, client=None):
    """Single-choice most-trusted ranking -> one most_trusted_share row per person."""
    pairs, is_json = get_pairs(text)
    persons = [(label, value) for label, value in pairs if _label_class(label) is None]
    total = sum(value for _, value in persons)
    if len(persons) < 3 or not 98 <= total <= 102:
        return ExtractionResult(review=[f"ranking shares sum to {total:g}, not 100: {title!r}"])
    rows = []
    for label, value in persons:
        entity, in_roster = canonical_entity(label)
        rows.append(_row(entity, in_roster, classification.metric, value,
                         base="full_sample", scale_note=f"single choice, total {total:g}",
                         extraction="json_keys" if is_json else "regex"))
    return ExtractionResult(rows=rows)


def extract_ipsos_indice(classification, pollster, title, text, client=None):
    """Ipsos gov/PM table -> gradimento_index (INDICE row, base=expressers)
    AND giudizi_positivi_pct (raw positives row, base=full_sample)."""
    pairs, _ = get_pairs(text)

    def find(pattern):
        return next((v for label, v in pairs if re.search(pattern, label)), None)

    positives = find(r"(?i)voti\s+positivi")
    negatives = find(r"(?i)voti\s+negativi")
    dontknow = find(r"(?i)non\s+sanno|non\s+indicano")
    indice = find(r"(?i)indice\s+di\s+gradimento")
    if positives is None or negatives is None or indice is None:
        return ExtractionResult(review=[f"ipsos indice table missing a required row: {title!r}"])
    if not ipsos_index_matches(indice, positives, negatives):
        recomputed = recompute_gradimento_index(positives, negatives)
        return ExtractionResult(review=[
            f"deposited INDICE {indice:g} != recompute {recomputed} "
            f"from pos={positives:g} neg={negatives:g}: {title!r}"
        ])
    entity, in_roster = entity_from_question_title(title)
    if entity is None:
        return ExtractionResult(review=[f"cannot resolve entity from title: {title!r}"])
    index_row = _row(entity, in_roster, METRIC_GRADIMENTO_INDEX, indice,
                     base="expressers", extraction="json_keys",
                     scale_note=f"% voti positivi su voti espressi ({positives:g}/{positives + negatives:g})")
    index_row["derivation"] = (
        f"deposited INDICE row, verified == pos/(pos+neg) from "
        f"voti positivi={positives:g}, negativi={negatives:g}"
    )
    raw_row = _row(entity, in_roster, METRIC_GIUDIZI_POSITIVI, positives,
                   negative=negatives, dontknow=dontknow, base="full_sample",
                   scale_note="voti positivi (6-10) su totale campione", extraction="json_keys")
    return ExtractionResult(rows=[index_row, raw_row])


def extract_leader_battery(classification, pollster, title, text, client=None):
    """Per-leader battery (Ipsos raw positives, EMG fiducia, 1-10 means)."""
    pairs, is_json = get_pairs(text)
    # class None = a person name; 'extra'-classed labels are kept only when they
    # look like 'Name - PARTY' (e.g. "Riccardo Magi - + Europa"), never when they
    # are scale footers like "Molto+abbastanza: 45%"
    persons = [(label, value) for label, value in pairs
               if (_label_class(label) is None
                   or (_label_class(label) == "extra" and re.match(r".+\s-\s.+", label)))
               and not re.search(r"(?i)totale|indice|voti\s+", label)]
    if len(persons) < 2:
        return ExtractionResult(review=[f"battery with fewer than 2 entities: {title!r}"])
    if len({label for label, _ in persons}) != len(persons):
        return ExtractionResult(review=[
            f"battery with repeated labels (vertical multi-column layout?): {title!r}"
        ])
    total = sum(value for _, value in persons)
    if classification.metric != METRIC_VOTO_MEDIO and len(persons) >= 8 and 98 <= total <= 102:
        return ExtractionResult(review=[
            f"battery values sum to {total:g} (~100): looks like a single-choice "
            f"ranking, refusing per-leader percentages: {title!r}"
        ])
    base = "unknown" if classification.metric == METRIC_VOTO_MEDIO else "full_sample"
    rows = []
    for label, value in persons:
        entity, in_roster = canonical_entity(label)
        rows.append(_row(entity, in_roster, classification.metric, value, base=base,
                         extraction="json_keys" if is_json else "regex"))
    return ExtractionResult(rows=rows)


_BIDIMEDIA_LINE = re.compile(
    r"^[-•*\s]*(.+?)\s*\((\d{1,3}(?:[.,]\d+)?)\s*%?\)\s*:\s*(\d{1,3}(?:[.,]\d+)?)\s*%?\s*$"
)


def extract_bidimedia_battery(classification, pollster, title, text, client=None):
    """BiDiMedia 'Surname (awareness%): fiducia%' battery -> POST-colon number.

    Mechanical guard: if the extracted values cluster in 55-98 across leaders,
    the parser almost certainly grabbed the awareness column -> REVIEW.
    """
    entries = []
    for line in str(text or "").splitlines():
        match = _BIDIMEDIA_LINE.match(line.strip())
        if match:
            entries.append((match.group(1).strip(), to_number(match.group(2)), to_number(match.group(3))))
    if len(entries) < 2:
        return ExtractionResult(review=[f"bidimedia battery: no 'Name (aw%): v%' lines: {title!r}"])
    values = [value for _, _, value in entries]
    if len(values) >= 5 and min(values) >= 55 and max(values) <= 98:
        return ExtractionResult(review=[
            f"bidimedia battery values cluster in 55-98 - awareness column grabbed?: {title!r}"
        ])
    rows = []
    for label, awareness, value in entries:
        entity, in_roster = canonical_entity(label)
        rows.append(_row(entity, in_roster, classification.metric, value,
                         base="full_sample", scale_note=f"conoscenza {awareness:g}%",
                         extraction="regex"))
    return ExtractionResult(rows=rows)


def extract_expressers_single(classification, pollster, title, text, client=None):
    """Values published net of non-respondents ("al netto delle non risposte"):
    expressers-base shares, stored as gradimento_index, never fiducia_pct.

    Handles the Demos&Pi Capo dello Stato series (single JSON row whose label
    carries the entity) and scale tables republished on the expressers base.
    """
    pairs, is_json = get_pairs(text)
    scale_rows = split_scale_pairs(pairs)
    note = "share net of non-respondents (expressers base)"
    if scale_rows and any(cls == "positive" for cls, _, _ in scale_rows):
        entity, in_roster = entity_from_question_title(title)
        if entity is None:
            return ExtractionResult(review=[f"cannot resolve entity from title: {title!r}"])
        value = sum(value for cls, _, value in scale_rows if cls == "positive")
        return ExtractionResult(rows=[_row(entity, in_roster, classification.metric, value,
                                           base="expressers", scale_note=note,
                                           extraction="json_keys" if is_json else "regex")])
    rows = []
    for label, value in pairs:
        if _label_class(label) is not None:
            continue
        entity, in_roster = canonical_entity(label)
        if not entity:
            entity, in_roster = entity_from_question_title(title)
        if not entity:
            continue
        rows.append(_row(entity, in_roster, classification.metric, value, base="expressers",
                         scale_note=note, extraction="json_keys" if is_json else "regex"))
    if not rows:
        return ExtractionResult(review=[f"expressers-base table with no readable rows: {title!r}"])
    return ExtractionResult(rows=rows)


def extract_demospi(classification, pollster, title, text, client=None):
    """Demos&Pi two-column table -> the '>= 6' judgments column ONLY."""
    stripped = str(text or "").strip()
    try:
        data = json.loads(stripped)
    except (json.JSONDecodeError, TypeError):
        return ExtractionResult(review=[f"demospi table is not allegato JSON: {title!r}"])
    column = re.compile(r"(?i)uguale\s+o\s+superiore\s+a\s+6|voto\s+da\s+6\s+a\s+10|>=\s*6")
    rows = []
    for label, cells in data.items():
        if not isinstance(cells, dict) or _label_class(label) is not None \
                or re.search(r"(?i)totale", label):
            continue
        value = next((to_number(cell) for key, cell in cells.items() if column.search(str(key))), None)
        if value is None and column.search(label):
            value = next((to_number(cell) for cell in cells.values()), None)
        if value is None:
            continue
        entity, in_roster = canonical_entity(label)
        rows.append(_row(entity, in_roster, classification.metric, value, base="full_sample",
                         scale_note="giudizio uguale o superiore a 6", extraction="json_keys"))
    if not rows:
        return ExtractionResult(review=[f"demospi table: no >=6 column found: {title!r}"])
    return ExtractionResult(rows=rows)


# --- LLM fallback ----------------------------------------------------------------

LLM_MODEL = "gpt-4o-mini"

LLM_SYSTEM_PROMPT = """
You read ONE question of an Italian opinion poll (title + table text) and extract favorability/trust numbers into rows. Reply with JSON:
{"rationale": "...", "favorability": 0 or 1, "rows": [{"entity": "...", "metric": "...", "value": N, "value_negative": N|null, "value_dontknow": N|null, "population": "national|subnational|subgroup", "base": "full_sample|expressers|unknown", "scale_note": "..."}]}

favorability=1 only for approval/trust/judgment questions about NATIONAL Italian politics (government, party leaders, institutions, or named public figures). Voting intentions, seat projections and issue questions are 0 (empty rows).

metric must be exactly one of:
- "fiducia_pct": % of ALL respondents trusting (sum of molta+abbastanza when a scale is shown; write the sum in scale_note)
- "fiducia_binaria_pct": forced yes/no trust share
- "gradimento_index": approval index computed only on respondents expressing an opinion
- "giudizi_positivi_pct": raw % positive judgments over the full sample
- "most_trusted_share": single-choice "most trusted" shares that sum to 100 across people
- "voto_medio_1_10": mean score on a 1-10 scale

Rules: one row per measured entity. population="subgroup" for per-coalition/per-party breakdowns of a national question, "subnational" for local/regional questions. Use the exact person name as printed (no party suffix). If a table shows a time series, extract only the most recent wave. Never output vote shares of parties.
"""


def _llm_client():
    import os

    from dotenv import load_dotenv
    from openai import OpenAI

    load_dotenv(override=True)
    return OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def extract_llm(classification, pollster, title, text, client=None, cached_payload=None):
    """Fallback labeling+extraction for tables no mechanical rule can read.

    When `cached_payload` (a previously persisted LLM payload from the raw
    ledger) is given, NO API call is made: the payload is replayed through the
    same validation and row-building code, so replays are deterministic and
    offline while still benefiting from code-side fixes (entity normalization,
    guards). The payload is schema-validated (fail fast); rows are kept only
    for population=national; each value that a regex pass over the table also
    found is upgraded to extraction='llm_regex_agree'.
    """
    if cached_payload is not None:
        data = cached_payload
    else:
        if client is None:  # pragma: no cover - live path
            client = _llm_client()
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": LLM_SYSTEM_PROMPT},
                {"role": "user", "content": f"{title}\n\n{text}"},
            ],
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        try:
            data = json.loads(content)
        except (json.JSONDecodeError, TypeError) as error:
            raise ValueError(f"LLM returned non-JSON output: {error}") from error
    payload = validate_llm_payload(data)

    pairs, _ = get_pairs(text)
    regex_values = {value for _, value in pairs}
    rows = []
    for llm_row in payload["rows"]:
        if llm_row["population"] != "national":
            continue
        entity, in_roster = canonical_entity(llm_row["entity"])
        agrees = llm_row["value"] in regex_values
        rows.append(_row(
            entity, in_roster, llm_row["metric"], llm_row["value"],
            negative=llm_row.get("value_negative"), dontknow=llm_row.get("value_dontknow"),
            base=llm_row.get("base") or "unknown", scale_note=llm_row.get("scale_note"),
            extraction="llm_regex_agree" if agrees else "llm",
        ))
    return ExtractionResult(rows=rows, llm_payload=data)


EXTRACTORS = {
    "scale": extract_scale,
    "binary": extract_binary,
    "ranking": extract_ranking,
    "ipsos_indice": extract_ipsos_indice,
    "leader_battery": extract_leader_battery,
    "bidimedia_battery": extract_bidimedia_battery,
    "demospi": extract_demospi,
    "expressers_single": extract_expressers_single,
    "llm": extract_llm,
}


def run_extractor(classification, pollster, title, text, client=None, cached_payload=None):
    """Dispatch to the extractor named by the classification. `cached_payload`
    (a persisted LLM payload) is honored only by the LLM fallback extractor."""
    name = classification.extractor or "llm"
    if name == "llm":
        return extract_llm(classification, pollster, title, text,
                           client=client, cached_payload=cached_payload)
    return EXTRACTORS[name](classification, pollster, title, text, client=client)
