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
from .taxonomy import (
    METRIC_FIDUCIA,
    METRIC_GIUDIZI_POSITIVI,
    METRIC_GRADIMENTO_INDEX,
    METRIC_MOST_TRUSTED,
    METRIC_VOTO_MEDIO,
    METRICS,
    canonical_entity,
    entity_from_question_title,
)


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
    """Per-leader battery (Ipsos expressers index, EMG fiducia, 1-10 means)."""
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
    # base follows the metric: the Ipsos leader battery is the expressers index,
    # EMG/other batteries are full-sample fiducia, voto_medio has no base
    if classification.metric == METRIC_VOTO_MEDIO:
        base = "unknown"
    elif classification.metric == METRIC_GRADIMENTO_INDEX:
        base = "expressers"
    else:
        base = "full_sample"
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


# --- derived metrics (was derive.py) --------------------------------------------
#
# Derived metrics with provenance (pure functions).
# - The Ipsos "indice di gradimento" is recomputed as positives/(positives+
#   negatives) and must match the deposited INDICE row within +/-1 point or the
#   whole table is routed to review (a mismatch means we misread the table).
# - For 4/5-scale fiducia tables we optionally emit a DERIVED expressers-rate row
#   (same arithmetic as the Ipsos index) so cross-pollster comparisons on the same
#   base are possible - always tagged derived=true and kept out of the published
#   averages.
# The Ipsos per-leader index IS deposited directly (the "Indice gradimento 0-100"
# battery), so it needs no recomputation - it is read as-is into gradimento_index.
# Explicitly NOT derivable from this archive (documented gaps, do not impute):
# - SWG / Noto national leader fiducia: absent from the archive deposits.

def half_up(value):
    """Round half away from zero (Ipsos rounds 42.5 -> 43, not banker's 42)."""
    return int(value + 0.5) if value >= 0 else -int(-value + 0.5)


def recompute_gradimento_index(positives, negatives):
    """Ipsos index arithmetic: % positives over expressed judgments."""
    if not positives and not negatives:
        return None
    return half_up(100.0 * positives / (positives + negatives))


def ipsos_index_matches(deposited_index, positives, negatives, tolerance=1):
    """The deposited INDICE row must equal the recompute within ±tolerance."""
    recomputed = recompute_gradimento_index(positives, negatives)
    if recomputed is None or deposited_index is None:
        return False
    return abs(recomputed - deposited_index) <= tolerance


def expressers_rate_row(row):
    """Derived gradimento_index-style row from a full-sample fiducia row.

    Returns a NEW row dict (never mutates the input) or None when the negative
    share is missing. Clearly separated from published numbers via derived=true.
    """
    value, negative = row.get("value"), row.get("value_negative")
    if value is None or negative is None or (value + negative) == 0:
        return None
    derived_value = recompute_gradimento_index(value, negative)
    return {
        **row,
        "metric": "gradimento_index",
        "value": float(derived_value),
        "base": "expressers",
        "derived": True,
        "derivation": f"pos/(pos+neg) from positives={value:g}, negatives={negative:g}",
        "extraction": "derived",
    }


# --- validation contract (was validate.py) --------------------------------------
#
# Strict schema validation of LLM output plus structural cross-checks on extracted
# rows. Fail fast - anything that violates an invariant raises ValueError (LLM
# payloads) or is routed to the review queue (rows), and can therefore never reach
# favorability_polls.csv silently.

# The metric taxonomy binds each family to the base its numbers live on. Pooling
# an expressers-normalized value with a full-sample one (or vice versa) is the v1
# killer scale-mixing defect, so a row whose base contradicts its metric — most
# often an LLM-fallback mislabel — is routed to review, never averaged.
_METRIC_REQUIRED_BASE = {
    METRIC_GRADIMENTO_INDEX: "expressers",   # positives over those who express an opinion
    METRIC_FIDUCIA: "full_sample",
    METRIC_GIUDIZI_POSITIVI: "full_sample",
}

POPULATIONS = {"national", "subnational", "subgroup"}
BASES = {"full_sample", "expressers", "unknown"}


def _checked_number(name, value, upper=100.0, allow_none=False):
    if value is None:
        if allow_none:
            return None
        raise ValueError(f"{name} is required but null")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} is not a number: {value!r}")
    if not 0 <= float(value) <= upper:
        raise ValueError(f"{name} out of [0, {upper:g}] range: {value!r}")
    return float(value)


def validate_llm_payload(data):
    """Strict schema check of the LLM fallback output; returns a NEW dict.

    Required shape: {"rationale": str, "favorability": 0|1, "rows": [...]},
    each row {"entity", "metric" (closed enum), "value", "population", ...}.
    """
    if not isinstance(data, dict):
        raise ValueError(f"LLM output is not a JSON object: {type(data).__name__}")
    for key in ("rationale", "favorability", "rows"):
        if key not in data:
            raise ValueError(f"LLM output is missing required key {key!r}")
    if data["favorability"] not in (0, 1):
        raise ValueError(f"favorability must be 0 or 1, got {data['favorability']!r}")
    if not isinstance(data["rows"], list):
        raise ValueError(f"rows must be a list, got {type(data['rows']).__name__}")
    if data["favorability"] == 0:
        return {"rationale": str(data["rationale"]), "favorability": 0, "rows": []}
    if not data["rows"]:
        raise ValueError("favorability is 1 but rows is empty")

    rows = []
    for raw in data["rows"]:
        if not isinstance(raw, dict):
            raise ValueError(f"row is not an object: {raw!r}")
        entity = str(raw.get("entity") or "").strip()
        if not entity:
            raise ValueError(f"row without entity: {raw!r}")
        metric = raw.get("metric")
        if metric not in METRICS:
            raise ValueError(f"metric must be one of {METRICS}, got {metric!r}")
        upper = 10.0 if metric == METRIC_VOTO_MEDIO else 100.0
        population = raw.get("population")
        if population not in POPULATIONS:
            raise ValueError(f"population must be one of {sorted(POPULATIONS)}, got {population!r}")
        base = raw.get("base") or "unknown"
        if base not in BASES:
            raise ValueError(f"base must be one of {sorted(BASES)}, got {base!r}")
        rows.append({
            "entity": entity,
            "metric": metric,
            "value": _checked_number("value", raw.get("value"), upper),
            "value_negative": _checked_number("value_negative", raw.get("value_negative"),
                                              100.0, allow_none=True),
            "value_dontknow": _checked_number("value_dontknow", raw.get("value_dontknow"),
                                              100.0, allow_none=True),
            "population": population,
            "base": base,
            "scale_note": str(raw["scale_note"]) if raw.get("scale_note") else None,
        })
    return {"rationale": str(data["rationale"]), "favorability": 1, "rows": rows}


def guard_rows(rows, context=""):
    """Structural cross-checks on extracted rows -> (accepted, review_reasons).

    - Ranking guard: >=8 same-metric per-person values summing to 100±2 MUST be
      most_trusted_share; any other metric claiming that shape is rejected
      wholesale (it poisons every leader's average — the LAB21 v1 defect).
    - most_trusted_share rows must actually sum to 100±2.
    """
    if not rows:
        return [], []
    review = []
    by_metric = {}
    for row in rows:
        by_metric.setdefault(row["metric"], []).append(row)

    accepted = []
    for metric, metric_rows in by_metric.items():
        required_base = _METRIC_REQUIRED_BASE.get(metric)
        if required_base is not None:
            off_base = [row for row in metric_rows if row.get("base") not in (required_base, None)]
            if off_base:
                bases = sorted({str(row.get("base")) for row in off_base})
                review.append(
                    f"{len(off_base)} {metric} rows on base {bases} (expected "
                    f"{required_base!r}): metric/base mismatch, scale not comparable ({context})"
                )
                metric_rows = [row for row in metric_rows if row not in off_base]
                if not metric_rows:
                    continue
        total = sum(row["value"] for row in metric_rows)
        if metric == METRIC_MOST_TRUSTED:
            if not 98 <= total <= 102:
                review.append(
                    f"most_trusted_share rows sum to {total:g}, not 100 ({context})"
                )
                continue
        elif metric != METRIC_VOTO_MEDIO and len(metric_rows) >= 8 and 98 <= total <= 102:
            review.append(
                f"{len(metric_rows)} {metric} rows sum to {total:g} (~100): "
                f"single-choice ranking misparsed as per-leader values ({context})"
            )
            continue
        accepted.extend(metric_rows)
    return accepted, review
