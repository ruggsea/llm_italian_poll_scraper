"""
Validation contract (pure): strict schema validation of LLM output plus
structural cross-checks on extracted rows. Fail fast — anything that violates
an invariant raises ValueError (LLM payloads) or is routed to the review
queue (rows), and can therefore never reach favorability_polls.csv silently.
"""

from .taxonomy import (
    METRIC_FIDUCIA,
    METRIC_GIUDIZI_POSITIVI,
    METRIC_GRADIMENTO_INDEX,
    METRIC_MOST_TRUSTED,
    METRIC_VOTO_MEDIO,
    METRICS,
)

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
