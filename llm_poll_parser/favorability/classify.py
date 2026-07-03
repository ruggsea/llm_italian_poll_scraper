"""
Deterministic classification decision tree — runs BEFORE any LLM call.

Input: (pollster_norm, domanda_title, text) where text is either the plain
risposta text or the stringified allegato-table JSON captured by the crawler.
Output: a Classification telling the pipeline what the table IS, which metric
its numbers live on, and which extractor can read it. Order of the rules
matters; the first match wins. Every v1 defect is a rule here:

- subgroup breakdowns (Piepoli "per orientamento politico", Meloni-88) -> REJECT
- single-choice rankings (LAB21 TOP TEN, sums to 100) -> most_trusted_share
- Ipsos leader battery raw positives -> giudizi_positivi_pct, NEVER the index
- subnational/local questions -> REJECT (population != national)
"""

import json
import re
from dataclasses import dataclass, field

from .taxonomy import (
    METRIC_FIDUCIA,
    METRIC_FIDUCIA_BINARIA,
    METRIC_GIUDIZI_POSITIVI,
    METRIC_GRADIMENTO_INDEX,
    METRIC_MOST_TRUSTED,
    METRIC_VOTO_MEDIO,
    is_relevant_question,
)

ACCEPT = "ACCEPT"
REJECT = "REJECT"
REVIEW = "REVIEW"
LLM = "LLM"  # recognizably favorability, but no mechanical rule fired


@dataclass(frozen=True)
class Classification:
    action: str                      # ACCEPT | REJECT | REVIEW | LLM
    table_kind: str
    metric: str = None               # one of taxonomy.METRICS when ACCEPT
    population: str = "national"
    extractor: str = None            # key into extract.EXTRACTORS when ACCEPT
    reason: str = ""
    crosscheck: dict = field(default_factory=dict)  # e.g. subgroup footer national value


# --- text parsing helpers (pure) ----------------------------------------------

_NUMBER = r"(\d{1,3}(?:[.,]\d+)?)"
# "- Molto 16%", "Molta: 20%", "Giorgia Meloni (Fratelli d'Italia) 36,7%"
_LABEL_VALUE_LINE = re.compile(rf"^[-°•*\s]*(.+?)[:\s]\s*{_NUMBER}\s*%?\s*(?:\([^)]*\))?$")

_EXTRA_LABEL = re.compile(r"(?i)\+|totale")  # footers like "Molto+abbastanza: 45%"
_POSITIVE = re.compile(r"(?i)^(molt[oa]\b|abbastanza|s[iì]\b|positiv|favorevol|hanno\s+fiducia)")
_NEGATIVE = re.compile(
    r"(?i)^(poc[oa]\b|per\s+n(?:ull|ient)\w*|nessun|negativ|sfavorevol|contrari"
    r"|no\b|non\s+hanno\s+fiducia)"
)
_DONTKNOW = re.compile(
    r"(?i)^(senza\s+opinione|non\s+s[oa]|non\s+sanno|non\s+saprei|non\s+risponde"
    r"|non\s+indica|ns\s*/?\s*nr|non\s+si\s+esprim|non\s+conosc)"
)

SUBGROUP_LABEL_PATTERN = re.compile(
    r"(?i)^(centro\s*-?\s*destra|centro\s*-?\s*sinistra|centrodestra|centrosinistra"
    r"|m5s|movimento\s+5\s+stelle|fdi|fratelli\s+d.italia|fi\b|forza\s+italia"
    r"|lega(\s+salvini)?|ls\b|pd\b|partito\s+democratico|avs\b|terzo\s+polo)"
)

_SUBGROUP_TITLE = re.compile(
    r"(?i)\(\s*(?:per|suddivisione\s+per)\s+[^)]*(?:politic|schier|orientament|coalizion)[^)]*\)?"
)

_SUBNATIONAL = re.compile(
    r"(?i)sindac|assessor|comune\s+di|provinc|region(?:e|ale|ali)\b|presidenti?\s+di\s+regione"
    r"|metropolitan|consiglier[ei]|toscan|piemont|lombard|sicilian?|venet[oi]\b|campan[io]\b"
    r"|pugliese|calabr|sardegn|liguri|alessandrin|comunali|regionali"
)

_RANKING_TITLE = re.compile(r"(?i)top\s+ten|classifica")
_AL_NETTO = re.compile(r"(?i)al\s+netto\s+dell?e?\s+non\s+rispost|al\s+netto\s+dei\s+non\s+rispond")
_BINARY_LABEL = re.compile(r"(?i)^(hanno\s+fiducia|non\s+hanno\s+fiducia|s[iì]|no)$")
_NAME_PARTY_KEY = re.compile(r".+\s-\s.+")


def to_number(raw):
    """'36,7%' -> 36.7; returns None for non-numeric strings."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    cleaned = str(raw).strip().replace("%", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_label_value_lines(text):
    """Extract [(label, value)] from simple 'Label NN%' body lines.

    Lines whose label still contains digits (multi-column tables like
    Youtrend's 'John Elkann 14 59 27') are NOT parsed — a mechanical extractor
    must never guess which column it grabbed; those tables go to the LLM.
    """
    pairs = []
    for line in str(text or "").splitlines():
        line = line.strip()
        if not line or line.lower().startswith("base"):
            continue
        match = _LABEL_VALUE_LINE.match(line)
        if match:
            label = match.group(1).strip(" .:-–")
            if label.startswith("(") and label.endswith(")"):
                label = label[1:-1].strip()
            value = to_number(match.group(2))
            # digits OUTSIDE parentheticals mean a multi-column row
            # ("John Elkann 14 59 27"); digits inside are fine
            # ("Giuseppe Conte (Movimento 5 Stelle)")
            bare_label = re.sub(r"\([^)]*\)", "", label)
            if value is not None and not re.search(r"\d", bare_label):
                pairs.append((label, value))
    return pairs


def parse_allegato(text):
    """Parse the crawler's stringified allegato-table JSON into [(label, value)].

    The allegato dict maps row label -> {column header: cell}; we take the first
    numeric cell of each row. Returns None when text is not allegato JSON.
    """
    stripped = str(text or "").strip()
    if not stripped.startswith("{"):
        return None
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    pairs = []
    for label, cells in data.items():
        if not isinstance(cells, dict):
            cells = {"": cells}
        for cell in cells.values():
            value = to_number(cell)
            if value is not None:
                pairs.append((str(label).strip(), value))
                break
    return pairs


def get_pairs(text):
    """(pairs, is_json): allegato JSON pairs if text is JSON, else body lines."""
    allegato = parse_allegato(text)
    if allegato is not None:
        return allegato, True
    return parse_label_value_lines(text), False


def _label_class(label):
    """'positive' | 'negative' | 'dontknow' | 'extra' | None for a row label."""
    cleaned = re.sub(r"\s+", " ", str(label)).strip(" .:-–()")
    if _EXTRA_LABEL.search(cleaned):
        return "extra"
    if _POSITIVE.match(cleaned):
        return "positive"
    if _NEGATIVE.match(cleaned):
        return "negative"
    if _DONTKNOW.match(cleaned):
        return "dontknow"
    return None


def split_scale_pairs(pairs):
    """[(class, label, value)] for scale rows, or None if any label is foreign."""
    rows = []
    for label, value in pairs:
        cls = _label_class(label)
        if cls is None:
            return None
        if cls != "extra":
            rows.append((cls, label, value))
    return rows or None


def is_scale_table(pairs):
    """True when labels are answer-scale categories summing to 98-102."""
    rows = split_scale_pairs(pairs)
    if rows is None or len(rows) < 2:
        return False
    if not any(cls == "positive" for cls, _, _ in rows):
        return False
    return 98 <= sum(value for _, _, value in rows) <= 102


def _subgroup_footer_crosscheck(text):
    match = re.search(rf"(?i)base:?\s*molto\s*\+\s*abbastanza[^0-9]*{_NUMBER}\s*%", str(text or ""))
    return {"national_value": to_number(match.group(1))} if match else {}


def looks_like_subgroup_body(text, pairs):
    """Row labels are coalitions/parties instead of scale answers."""
    subgroup_hits = sum(1 for label, _ in pairs if SUBGROUP_LABEL_PATTERN.match(label.strip("-° ")))
    if subgroup_hits >= 2:
        return True
    # JSON variant: {"": {"CENTRO DESTRA": "88%", ...}, "FDI": {...}}
    stripped = str(text or "").strip()
    return stripped.startswith("{") and bool(
        re.search(r"(?i)centro\s*-?\s*destra|centro\s*-?\s*sinistra", stripped)
    )


def _person_pairs(pairs):
    return [
        (label, value)
        for label, value in pairs
        if _label_class(label) is None and not re.search(r"(?i)totale|indice|voti\s+", label)
    ]


# --- decision tree --------------------------------------------------------------


def classify(pollster, domanda_title, text, document_title=None):  # noqa: C901 - the tree mirrors the spec
    """The 12-step decision tree from the v2 design spec. First match wins."""
    title = str(domanda_title or "")
    body = str(text or "")
    pairs, is_json = get_pairs(body)
    persons = _person_pairs(pairs)

    # 1. question-level relevance filter
    if not is_relevant_question(title) and not is_relevant_question(body[:200]):
        return Classification(REJECT, "not_favorability",
                              reason="no favorability keyword in question")

    # 2. subnational/local reject — the DOCUMENT title counts too ("Monitoraggio
    #    mensile del voto e delle problematiche toscane" carries a national-looking
    #    "fiducia nel Governo" question asked to a Tuscany-only sample)
    if _SUBNATIONAL.search(title) or _SUBNATIONAL.search(body[:400]) \
            or _SUBNATIONAL.search(str(document_title or "")):
        return Classification(REJECT, "subnational", population="subnational",
                              reason="local/regional entities or sample")

    # 3. subgroup breakdown reject (the Piepoli Meloni-88 defect)
    if _SUBGROUP_TITLE.search(title) or looks_like_subgroup_body(body, pairs):
        return Classification(REJECT, "subgroup_breakdown", population="subgroup",
                              reason="per-coalition breakdown of a national question",
                              crosscheck=_subgroup_footer_crosscheck(body))

    # 4. single-choice ranking detect (structural, not semantic)
    persons_sum = sum(value for _, value in persons)
    if pairs and (_RANKING_TITLE.search(title) or
                  (len(persons) >= 8 and 98 <= persons_sum <= 102)):
        if len(persons) >= 3 and 98 <= persons_sum <= 102:
            return Classification(ACCEPT, "most_trusted_ranking", METRIC_MOST_TRUSTED,
                                  extractor="ranking",
                                  reason="single-choice ranking, shares sum to 100")
        return Classification(REVIEW, "most_trusted_ranking",
                              reason="ranking title but shares do not sum to 100")

    # 5. Ipsos gov/PM indice table (deposited INDICE row + raw positives row)
    if is_json and any(re.search(r"(?i)voti\s+positivi", label) for label, _ in pairs) \
            and any(re.search(r"(?i)indice\s+di\s+gradimento", label) for label, _ in pairs):
        return Classification(ACCEPT, "ipsos_indice", METRIC_GRADIMENTO_INDEX,
                              extractor="ipsos_indice",
                              reason="deposited INDICE row + raw positives row")

    # 6. Ipsos leader battery: >=8 'Name - PARTY' keys, one integer each, sum >> 100.
    #    HARD OVERRIDE: raw positive judgments even though the header claims
    #    "Indice gradimento 0-100" — the published index is computed on expressers
    #    and sits 15-20 points higher (the v1 killer defect).
    if is_json and len(persons) >= 8 and persons_sum > 150 \
            and sum(1 for label, _ in persons if _NAME_PARTY_KEY.match(label)) >= len(persons) // 2:
        return Classification(ACCEPT, "ipsos_leader_battery", METRIC_GIUDIZI_POSITIVI,
                              extractor="leader_battery",
                              reason="per-leader raw positive judgments (never the index)")

    # 6b. Demos&Pi two-column table ('giudizio uguale o superiore a 6') — must
    #     run BEFORE the generic battery rules or the >=6 raw-positive shares
    #     get mislabeled fiducia_pct and pooled with real fiducia numbers
    if is_json and re.search(r"(?i)uguale\s+o\s+superiore\s+a\s+6|voto\s+da\s+6\s+a\s+10", body):
        return Classification(ACCEPT, "demospi_leader_battery", METRIC_GIUDIZI_POSITIVI,
                              extractor="demospi", reason=">=6 judgments column only")

    # 7. binary fiducia (LAB21 single leader)
    binary = [(label, value) for label, value in pairs if _BINARY_LABEL.match(label.strip())]
    if len(binary) == 2 and 98 <= sum(value for _, value in binary) <= 102:
        return Classification(ACCEPT, "binary_fiducia", METRIC_FIDUCIA_BINARIA,
                              extractor="binary", reason="forced yes/no trust, no don't-know")

    # 7b. expressers-base values ("al netto delle non risposte", Demos&Pi Capo
    #     dello Stato series): NOT poolable with full-sample fiducia_pct — they
    #     live on the expressers base, i.e. the gradimento_index family
    if _AL_NETTO.search(body) and pairs and any(value > 10 for _, value in pairs):
        return Classification(ACCEPT, "expressers_rate", METRIC_GRADIMENTO_INDEX,
                              extractor="expressers_single",
                              reason="share computed net of non-respondents (expressers base)")

    # 8. 4/5-scale single-entity table (Piepoli, EMG, TP, BiDiMedia, Youtrend buckets)
    if is_scale_table(pairs):
        if any(re.search(r"(?i)^positiv", label) for label, _ in pairs):
            # Positivo/Negativo/Non so buckets = raw positive judgments
            return Classification(ACCEPT, "giudizio_buckets", METRIC_GIUDIZI_POSITIVI,
                                  extractor="scale",
                                  reason="positive/negative judgment buckets")
        kind = (f"{pollster.lower().replace(' ', '_')}_national_fiducia"
                if pollster else "national_fiducia")
        return Classification(ACCEPT, kind, METRIC_FIDUCIA, extractor="scale",
                              reason="scale answers sum to ~100 over full sample")

    # 9a. BiDiMedia leader battery with awareness: 'Surname (98%): 36%'
    if re.search(r"(?i)\(conoscenza", title + body[:200]) or \
            re.search(r"\(\s*\d{2,3}\s*%\s*\)\s*:", body):
        return Classification(ACCEPT, "bidimedia_leader_battery", METRIC_FIDUCIA,
                              extractor="bidimedia_battery",
                              reason="fiducia battery with awareness in parentheses")

    # 9b. EMG-style leader battery: many 'Name NN%' TEXT lines, sum >> 100.
    #     Labels must be UNIQUE: repeated labels mean a vertical multi-column
    #     layout ("Giani / Conoscenza: 93 / Fiducia: 50 / ...") that no
    #     mechanical extractor can read safely -> fall through to the LLM.
    #     JSON batteries are handled by rules 6/6b or the LLM, never here.
    if not is_json and len(persons) >= 8 and persons_sum > 150 \
            and len({label for label, _ in persons}) == len(persons):
        return Classification(ACCEPT, "leader_battery", METRIC_FIDUCIA,
                              extractor="leader_battery",
                              reason="per-leader fiducia percentages over full sample")

    # 11. voto medio 1-10
    if re.search(r"(?i)voto\s+(medio|da\s+1\s+a\s+10)|scala\s+da\s+1\s+a\s+10", title + body[:200]) \
            and pairs and all(0 <= value <= 10 for _, value in pairs):
        return Classification(ACCEPT, "voto_medio", METRIC_VOTO_MEDIO,
                              extractor="leader_battery", reason="mean 1-10 scores")

    # 12. fallback: favorability-looking but no mechanical rule fired
    return Classification(LLM, "unclassified", reason="no deterministic rule matched")
