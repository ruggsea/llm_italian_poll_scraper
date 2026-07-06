# Golden-file regression test: encodes the 3/3 validation contract.
#
# With OPENAI_API_KEY unset, an offline reprocess + average + plot must
# reproduce the four committed ledger/output files BYTE-FOR-BYTE. This is the
# master invariant guarding every simplification and automation change: any
# edit that perturbs favorability_polls.csv / .jsonl, favorability_raw.jsonl or
# favorability_averages.csv makes `git diff` non-empty and fails here.
import os
import subprocess

import pytest

# repo root = the directory that holds the committed favorability outputs
REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

GOLDEN_FILES = [
    "favorability_raw.jsonl",
    "favorability_polls.jsonl",
    "favorability_polls.csv",
    "favorability_averages.csv",
]


def _git_diff(files):
    result = subprocess.run(
        ["git", "diff", "--", *files],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    return result.stdout


def test_offline_replay_is_byte_identical(monkeypatch):
    if not all(os.path.exists(os.path.join(REPO_ROOT, f)) for f in GOLDEN_FILES):
        pytest.skip("committed golden files not present in this checkout")

    # the contract is an OFFLINE replay: no key, no selenium, no live API
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.chdir(REPO_ROOT)

    from llm_poll_parser.favorability.crawler import reprocess
    from llm_poll_parser.favorability.averaging import (
        load_rows,
        make_plot,
        summarize,
        write_summary,
    )

    reprocess()                       # rebuild raw/rows ledgers from cached payloads
    rows = load_rows()
    write_summary(summarize(rows))    # rebuild favorability_averages.csv
    make_plot(rows)                   # plot is not diffed (binary), but must not raise

    diff = _git_diff(GOLDEN_FILES)
    assert diff == "", (
        "offline replay is NOT byte-identical to the committed golden files:\n"
        + diff[:4000]
    )
