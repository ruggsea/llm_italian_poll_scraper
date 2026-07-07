# tests/test_favorability_parser.py
import pytest
from llm_poll_parser.favorability_parser import parse_favorability


def test_parse_favorability_trust():
    # one unambiguous full-sample trust battery: molta+abbastanza = fiducia_pct
    poll_text = """
    Sondaggio EMG, ottobre 2024. Domanda: "Ha fiducia in Giorgia Meloni?"
    Risposte (base: 1000 intervistati):
      Molta fiducia: 22%
      Abbastanza fiducia: 25%
      Poca fiducia: 20%
      Nessuna fiducia: 30%
      Non sa: 3%

    Ha fiducia nel Governo?
      Molta: 20%   Abbastanza: 24%   Poca: 21%   Nessuna: 32%   Non sa: 3%
    """

    rows = {(r["entity"], r["metric"]): r["value"]
            for r in parse_favorability(poll_text)}

    # trust battery (molta+abbastanza over full sample) for the two entities
    assert ("Giorgia Meloni", "fiducia_pct") in rows
    assert ("Governo", "fiducia_pct") in rows
    assert rows[("Giorgia Meloni", "fiducia_pct")] == 47  # 22 + 25
    assert rows[("Governo", "fiducia_pct")] == 44  # 20 + 24


if __name__ == "__main__":
    pytest.main()
