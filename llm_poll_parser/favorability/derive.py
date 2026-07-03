"""
Derived metrics with provenance (pure functions).

- The Ipsos "indice di gradimento" is recomputed as positives/(positives+negatives)
  and must match the deposited INDICE row within ±1 point or the whole table is
  routed to review (a mismatch means we misread the table).
- For 4/5-scale fiducia tables we optionally emit a DERIVED expressers-rate row
  (same arithmetic as the Ipsos index) so cross-pollster comparisons on the same
  base are possible — always tagged derived=true and kept out of the published
  averages.

Explicitly NOT derivable from this archive (documented gaps, do not impute):
- the Ipsos PUBLISHED per-leader index (Conte 48 etc.): per-leader non-response
  is not deposited, only raw positives are;
- SWG / Noto national leader fiducia: absent from the archive deposits.
"""


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
