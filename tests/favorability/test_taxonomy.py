# Taxonomy tests: pollster normalization (census spellings), entity roster
# resolution, and the closed metric enum.
import pytest

from llm_poll_parser.favorability.taxonomy import (
    ENTITY_ROSTER,
    METRICS,
    canonical_entity,
    entity_from_question_title,
    is_relevant_question,
    normalize_pollster,
)


@pytest.mark.parametrize("raw, expected", [
    ("Ipsos Doxa", "Ipsos"), ("Ipsos srl", "Ipsos"),
    ("Emg srl", "EMG"), ("EMG Different", "EMG"), ("EMG", "EMG"),
    ("Istituto Piepoli", "Piepoli"),
    ("Termometro Politico", "Termometro Politico"),
    ("LAB21 SRL", "LAB21"), ("lab21 srl", "LAB21"), ("ISTITUTO DEMOSCOPICO LAB21", "LAB21"),
    ("BiDiMedia s.r.l.", "BiDiMedia"),
    ("SWG S.p.A.", "SWG"),
    ("Demopolis - Istituto di Ricerche", "Demopolis"),
    ("Demos&Pi e Demetra", "Demos&Pi"),
    ("tecnè srl", "Tecnè"), ("Tecnè Srl", "Tecnè"), ("tecné srl", "Tecnè"),
    ("Youtrend Strategies", "Youtrend"),
    ("Only Numbers", "Only Numbers"),
    ("Sconosciuto Institute", "Sconosciuto Institute"),   # unknowns pass through
])
def test_normalize_pollster_census_spellings(raw, expected):
    assert normalize_pollster(raw) == expected


@pytest.mark.parametrize("name, expected, in_roster", [
    ("Giorgia Meloni (Fratelli d'Italia)", "Giorgia Meloni", True),
    ("Giuseppe Conte - M5S", "Giuseppe Conte", True),
    ("Roberto Vannacci - Futuro - Nazionale", "Roberto Vannacci", True),
    ("Riccardo Magi - + Europa", "Riccardo Magi", False),
    ("Cateno De Luca (Sud chiama Nord)", "Cateno De Luca", False),
    ("Governo Meloni", "Governo", True),
    ("Schlein", "Elly Schlein", True),
])
def test_canonical_entity(name, expected, in_roster):
    assert canonical_entity(name) == (expected, in_roster)


# Regression (round-1 blocker): entity keys must never depend on source/LLM
# casing — "ANGELO BONELLI" splitting from "Angelo Bonelli" silently dropped
# the Bonelli/Fratoianni cross-pollster averages on replay.
@pytest.mark.parametrize("name, expected, in_roster", [
    ("ANGELO BONELLI", "Angelo Bonelli", False),
    ("angelo bonelli", "Angelo Bonelli", False),
    ("NICOLA FRATOIANNI", "Nicola Fratoianni", False),
    ("SILVIA SALIS", "Silvia Salis", False),
    ("magistratura", "Magistratura", False),
    ("MAGISTRATURA", "Magistratura", False),
    ("FORZE ARMATE", "Forze Armate", False),
    ("l'unione europea", "L'Unione Europea", False),
    ("GIORGIA MELONI", "Giorgia Meloni", True),    # roster match stays case-blind
    ("Cateno De Luca", "Cateno De Luca", False),   # mixed case passes verbatim
])
def test_canonical_entity_is_case_insensitive(name, expected, in_roster):
    assert canonical_entity(name) == (expected, in_roster)


def test_case_variants_map_to_one_entity_key():
    variants = ["Angelo Bonelli", "ANGELO BONELLI", "angelo bonelli"]
    assert len({canonical_entity(v) for v in variants}) == 1


@pytest.mark.parametrize("title, expected, in_roster", [
    ("QUANTO HA FIDUCIA IN GIORGIA MELONI, PRESIDENTE DEL CONSIGLIO?", "Giorgia Meloni", True),
    ("Quanta fiducia ha nel Governo Meloni?", "Governo", True),
    ("LEI QUANTA FIDUCIA HA NEL GOVERNO?", "Governo", True),
    ("Qual è il suo livello di gradimento nei confronti del governo guidato da Giorgia Meloni?",
     "Governo", True),
    ("Qual è il suo livello di gradimento nei confronti del Presidente del Consiglio, "
     "Giorgia Meloni?", "Giorgia Meloni", True),
    ("QUANTO HA FIDUCIA IN DONALD TRUMP?", "Donald Trump", False),
    ("LA FIDUCIA NELL'EUROPA", "Europa", False),
])
def test_entity_from_question_title(title, expected, in_roster):
    assert entity_from_question_title(title) == (expected, in_roster)


def test_metric_enum_is_closed_and_stable():
    assert METRICS == ["fiducia_pct", "fiducia_binaria_pct", "gradimento_index",
                       "giudizi_positivi_pct", "most_trusted_share", "voto_medio_1_10"]


def test_roster_is_v1_roster_with_governo():
    # v1's 10-entity roster (Governo + 9 national figures), unchanged
    assert ENTITY_ROSTER == ["Governo", "Giorgia Meloni", "Giuseppe Conte", "Elly Schlein",
                             "Antonio Tajani", "Matteo Salvini", "Roberto Vannacci",
                             "Carlo Calenda", "Matteo Renzi", "Sergio Mattarella"]


def test_relevance_is_loose_but_not_universal():
    assert is_relevant_question("TOP TEN FIDUCIA NEI LEADER DEI PARTITI POLITICI ITALIANI")
    assert is_relevant_question("Qual è il suo livello di gradimento per l'operato dei leader?")
    assert not is_relevant_question("Se oggi si votasse per le elezioni politiche, a quale "
                                    "delle seguenti liste darebbe il suo voto?")
    assert not is_relevant_question(None)


@pytest.mark.parametrize("title, expected", [
    ("Quanta fiducia ha nell'Unione Europea?", "Unione Europea"),          # Ixè
    ("Qual è il suo giudizio sul Presidente degli Stati Uniti Donald Trump",
     "Presidente Degli Stati Uniti Donald Trump"),                          # Demopolis
])
def test_entity_from_title_handles_ha_and_su_prepositions(title, expected):
    entity, in_roster = entity_from_question_title(title)
    assert entity == expected
    assert in_roster is False


def test_normalize_pollster_handles_termomemtro_typo():
    # the official archive contains "Termomemtro Politico" (sic) deposits
    from llm_poll_parser.favorability.taxonomy import normalize_pollster
    assert normalize_pollster("Termomemtro Politico") == "Termometro Politico"
    assert normalize_pollster("Termometro Politico srl") == "Termometro Politico"
