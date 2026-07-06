"""
Metric taxonomy, entity roster, pollster normalization and question templates.

Pure data plus tiny pure functions. The metric enum is CLOSED: adding a value
requires a fixture in tests/favorability/fixtures plus a test, because pooling
numbers published on different scales is exactly the defect that killed v1
(Ipsos "indice di gradimento" 48 vs raw "% giudizi positivi" 30 for the same
leader in the same week).
"""

import re

# --- metric enum (closed) ----------------------------------------------------

METRIC_FIDUCIA = "fiducia_pct"                    # molta+abbastanza over FULL sample
METRIC_FIDUCIA_BINARIA = "fiducia_binaria_pct"    # forced yes/no trust
METRIC_GRADIMENTO_INDEX = "gradimento_index"      # positives / expressers (Ipsos)
METRIC_GIUDIZI_POSITIVI = "giudizi_positivi_pct"  # raw % positive over full sample
METRIC_MOST_TRUSTED = "most_trusted_share"        # single choice, sums to 100
METRIC_VOTO_MEDIO = "voto_medio_1_10"             # mean 1-10 score

METRICS = [
    METRIC_FIDUCIA,
    METRIC_FIDUCIA_BINARIA,
    METRIC_GRADIMENTO_INDEX,
    METRIC_GIUDIZI_POSITIVI,
    METRIC_MOST_TRUSTED,
    METRIC_VOTO_MEDIO,
]

# --- entity roster -----------------------------------------------------------

ENTITY_ROSTER = [
    "Governo",
    "Giorgia Meloni",
    "Giuseppe Conte",
    "Elly Schlein",
    "Antonio Tajani",
    "Matteo Salvini",
    "Roberto Vannacci",
    "Carlo Calenda",
    "Matteo Renzi",
    "Sergio Mattarella",
]

# surname (lowercase) -> canonical roster name
_SURNAME_TO_ENTITY = {
    "meloni": "Giorgia Meloni",
    "conte": "Giuseppe Conte",
    "schlein": "Elly Schlein",
    "tajani": "Antonio Tajani",
    "salvini": "Matteo Salvini",
    "vannacci": "Roberto Vannacci",
    "calenda": "Carlo Calenda",
    "renzi": "Matteo Renzi",
    "mattarella": "Sergio Mattarella",
}

_PARENTHETICAL = re.compile(r"\s*\([^)]*\)\s*")
_PARTY_SUFFIX = re.compile(r"\s+-\s+.*$")


def _normalize_case(cleaned):
    """Case normalization for non-roster names — CODE-side, so the series key
    can never depend on how a source table (or the LLM fallback echoing it)
    happened to case a label: "ANGELO BONELLI", "Angelo Bonelli" and
    "angelo bonelli" must all be the same entity. Degenerate casings
    (all-upper / all-lower) are rewritten to title case; genuinely mixed-case
    names pass through verbatim (they already carry intentional casing)."""
    if cleaned.isupper() or cleaned.islower():
        return cleaned.title()
    return cleaned


def _resolve_roster(lowered):
    """Resolve a lowercased label to (roster_name, True) or None if it matches
    no roster entity. Shared verbatim by canonical_entity() and
    entity_from_question_title() so the two never drift on how "Governo",
    a surname, or a presidential title maps onto the roster."""
    if re.search(r"\bgoverno\b", lowered) and "presidente del consiglio" not in lowered:
        return "Governo", True
    for surname, roster_name in _SURNAME_TO_ENTITY.items():
        if re.search(rf"\b{surname}\b", lowered):
            return roster_name, True
    if "presidente della repubblica" in lowered:
        return "Sergio Mattarella", True
    if "presidente del consiglio" in lowered:
        return "Giorgia Meloni", True
    return None


def canonical_entity(name):
    """Normalize an entity label to (canonical_name, in_roster).

    Strips party parentheticals ("Giorgia Meloni (Fratelli d'Italia)") and
    " - PARTY" suffixes ("Giuseppe Conte - M5S"); resolves surnames against the
    roster (case-insensitively). Unknown names are kept (trimmed and
    case-normalized) with in_roster=False — extraction never drops entities,
    presentation filters them.
    """
    cleaned = _PARTY_SUFFIX.sub("", _PARENTHETICAL.sub(" ", str(name))).strip(" .:-–")
    lowered = cleaned.lower()
    resolved = _resolve_roster(lowered)
    if resolved is not None:
        return resolved
    return _normalize_case(cleaned), False


_FIDUCIA_IN_X = re.compile(
    r"(?i)(?:fiducia|gradimento|giudizio)\s+(?:ha\s+)?"
    r"(?:nell'|nella|nello|negli|nei|nel|in|per|sull'|sulla|sugli|sul|su)\s*([^?,.\n(]+)"
)


def entity_from_question_title(title):
    """Resolve the measured entity from a single-entity question title.

    "QUANTO HA FIDUCIA IN GIORGIA MELONI, PRESIDENTE DEL CONSIGLIO?" ->
    ("Giorgia Meloni", True); "Quanta fiducia ha nel Governo Meloni?" ->
    ("Governo", True); "QUANTO HA FIDUCIA IN DONALD TRUMP?" ->
    ("Donald Trump", False).
    """
    text = str(title or "")
    lowered = text.lower()
    resolved = _resolve_roster(lowered)
    if resolved is not None:
        return resolved
    match = _FIDUCIA_IN_X.search(text)
    if match:
        return canonical_entity(match.group(1).title())
    return None, False


# --- pollster normalization ----------------------------------------------------

# first regex match wins; verbatim Realizzatore is preserved in pollster_raw
_POLLSTER_PATTERNS = [
    (re.compile(r"(?i)ipsos"), "Ipsos"),
    (re.compile(r"(?i)\bemg\b"), "EMG"),
    (re.compile(r"(?i)piepoli"), "Piepoli"),
    (re.compile(r"(?i)termome[a-z]*tro"), "Termometro Politico"),  # incl. "Termomemtro" typo in source
    (re.compile(r"(?i)lab\s*21|lab2101"), "LAB21"),
    (re.compile(r"(?i)bidimedia"), "BiDiMedia"),
    (re.compile(r"(?i)\bswg\b"), "SWG"),
    (re.compile(r"(?i)demopolis"), "Demopolis"),
    (re.compile(r"(?i)demos\s*&?\s*pi"), "Demos&Pi"),
    (re.compile(r"(?i)tecn[eèé]"), "Tecnè"),
    (re.compile(r"(?i)youtrend"), "Youtrend"),
    (re.compile(r"(?i)only\s*numbers"), "Only Numbers"),
    (re.compile(r"(?i)euromedia"), "Euromedia"),
    (re.compile(r"(?i)eumetra"), "Eumetra"),
    (re.compile(r"(?i)\bnoto\b"), "Noto"),
    (re.compile(r"(?i)\bizi\b"), "IZI"),
    (re.compile(r"(?i)winpoll"), "Winpoll"),
    (re.compile(r"(?i)ix[eè]"), "Ixè"),
    (re.compile(r"(?i)quorum"), "Quorum"),
    (re.compile(r"(?i)analisi\s*politica"), "AnalisiPolitica"),
    (re.compile(r"(?i)demetra"), "Demetra"),
]


def normalize_pollster(realizzatore):
    """'Emg srl' / 'EMG Different' -> 'EMG'; unknowns pass through trimmed."""
    raw = str(realizzatore or "").strip()
    for pattern, canonical in _POLLSTER_PATTERNS:
        if pattern.search(raw):
            return canonical
    return raw


# --- question-level relevance (replaces v1's document-title gate) --------------

QUESTION_RELEVANCE_PATTERN = re.compile(
    r"(?i)fiducia|gradiment|giudizi|apprezzament|voto\s+da\s+1\s+a\s+10|indice"
)

# known per-pollster question templates that must be opened even if the generic
# keywords ever miss them (kept in sync with the archive census)
QUESTION_TEMPLATES = [
    re.compile(r"(?i)lei\s+quanta\s+fiducia\s+ha"),                        # EMG
    re.compile(r"(?i)ha\s+fiducia\s+nel\s+presidente\s+del\s+consiglio"),  # Termometro Politico
    re.compile(r"(?i)le\s+elencher[oò]\s+ora\s+i\s+nomi"),                 # EMG leader battery
    re.compile(r"(?i)giudizio\s+.*lavoro\s+.*governo"),                    # Youtrend
    re.compile(r"(?i)il\s+gradimento\s+dei\s+leader"),                     # Demos&Pi
    re.compile(r"(?i)quanta\s+fiducia\s+ha"),                              # BiDiMedia / generic
    re.compile(r"(?i)top\s+ten"),                                          # LAB21 ranking
]


def is_relevant_question(domanda_title):
    """Question-level filter: does this domanda look like favorability at all?

    Deliberately loose — a hit only means "open it and classify"; the decision
    tree in classify.py does the real accept/reject work. Documents are ALWAYS
    opened regardless of their archive title (v1's title gate lost every
    'Monitor Italia'-style omnibus deposit).
    """
    title = str(domanda_title or "")
    if QUESTION_RELEVANCE_PATTERN.search(title):
        return True
    return any(pattern.search(title) for pattern in QUESTION_TEMPLATES)
