# Shared helpers for the favorability v2 offline test suite.
# Fixtures are real archive table snippets (or spec-based snippets in the real
# layout for pollsters v1 never captured); the LLM is always mocked.
import json
import os
from types import SimpleNamespace

import pytest

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def load_fixture(name):
    with open(os.path.join(FIXTURES_DIR, f"{name}.json")) as file:
        return json.load(file)


def fixture_meta(fixture):
    from llm_poll_parser.favorability.taxonomy import normalize_pollster

    return {
        "Data Inserimento": fixture["deposit_date"],
        "Realizzatore": fixture["pollster_raw"],
        "Committente": "committente",
        "Titolo": fixture["titolo"],
        "pollster_norm": normalize_pollster(fixture["pollster_raw"]),
    }


class FakeClient:
    """Stands in for the OpenAI client: returns canned message contents
    (one per call, last one repeats). Salvaged from the v1 test harness."""

    def __init__(self, *contents):
        self.calls = []
        self._contents = list(contents)

        def create(**kwargs):
            self.calls.append(kwargs)
            content = self._contents.pop(0) if len(self._contents) > 1 else self._contents[0]
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
                usage=SimpleNamespace(total_tokens=42),
            )

        self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))


@pytest.fixture
def fake_client_factory():
    return FakeClient
