# tests/test_failover.py
# The daily update must survive free proxies dying at startup or mid-run.
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "llm_poll_parser"))
import pytest
import daily_update


class FakeDriver:
    def __init__(self, proxy, page=1):
        self.proxy = proxy
        self.page = page
        self.quit_called = False

    def quit(self):
        self.quit_called = True


LATEST = {"Data Inserimento": "08/09/2026", "Committente": "RTI", "Titolo": "old"}
NEW = {"Data Inserimento": "10/09/2026", "Committente": "SWG", "Titolo": "new"}


def make_world(monkeypatch, dead_at_start=(), fail_pages=None):
    """dead_at_start: proxies that cannot open the site. fail_pages: {(proxy, page): how many loads of that page fail on it}."""
    fail_pages = dict(fail_pages or {})
    started, drivers = [], []

    def start_driver(headless, proxy, page):
        started.append((proxy, page))
        if proxy in dead_at_start:
            raise RuntimeError("proxyConnectFailure")
        drivers.append(FakeDriver(proxy, page))
        return drivers[-1]

    def find_sondaggi_table(driver):
        # page 2 holds the already saved poll at row 2, below one new poll
        return [dict(NEW, Row=1), dict(LATEST, Row=2)] if driver.page == 2 else [dict(NEW, Row=1)]

    def handle_one_pagina(driver, page, upto_row=None):
        if fail_pages.get((driver.proxy, page), 0) > 0:
            fail_pages[(driver.proxy, page)] -= 1
            raise RuntimeError("Unable to locate element")
        assert upto_row == (2 if page == 2 else None)
        return [NEW]

    monkeypatch.setattr(daily_update, "start_driver", start_driver)
    monkeypatch.setattr(daily_update, "find_sondaggi_table", find_sondaggi_table)
    monkeypatch.setattr(daily_update, "handle_one_pagina", handle_one_pagina)
    def next_page(driver):
        driver.page += 1
    monkeypatch.setattr(daily_update, "get_prossima_pagina", next_page)
    monkeypatch.setattr(daily_update, "get_latest_poll_from_file", lambda filename: LATEST)
    return started, drivers


def test_happy_path_stops_at_latest_saved(monkeypatch):
    started, drivers = make_world(monkeypatch)
    polls = daily_update.get_polls_until_latest_saved("x.jsonl", ["a", "b"])
    assert polls == [NEW, NEW]
    assert started == [("a", 1)]
    assert all(d.quit_called for d in drivers)


def test_dead_proxy_at_startup_is_skipped(monkeypatch):
    started, drivers = make_world(monkeypatch, dead_at_start={"a"})
    polls = daily_update.get_polls_until_latest_saved("x.jsonl", ["a", "b"])
    assert polls == [NEW, NEW]
    assert started == [("a", 1), ("b", 1)]


def test_proxy_dying_mid_run_switches_and_redoes_page(monkeypatch):
    # "a" works for page 1 then dies on page 2; "b" must reopen the site directly at page 2
    started, drivers = make_world(monkeypatch, fail_pages={("a", 2): 1})
    polls = daily_update.get_polls_until_latest_saved("x.jsonl", ["a", "b"])
    assert polls == [NEW, NEW]
    assert started == [("a", 1), ("b", 2)]
    assert drivers[0].quit_called


def test_rotation_wraps_around(monkeypatch):
    # every proxy fails page 1 once; with 2 proxies the third attempt lands on "a" again
    started, drivers = make_world(monkeypatch, fail_pages={("a", 1): 1, ("b", 1): 1})
    polls = daily_update.get_polls_until_latest_saved("x.jsonl", ["a", "b"])
    assert polls == [NEW, NEW]
    assert started == [("a", 1), ("b", 1), ("a", 1)]


def test_gives_up_after_max_failures(monkeypatch):
    started, drivers = make_world(monkeypatch, fail_pages={("a", 1): 99})
    with pytest.raises(RuntimeError, match="Unable to locate"):
        daily_update.get_polls_until_latest_saved("x.jsonl", ["a"])
    assert len(started) == daily_update.MAX_PAGE_FAILURES
    assert all(d.quit_called for d in drivers)


def test_all_proxies_dead_raises(monkeypatch):
    make_world(monkeypatch, dead_at_start={"a", "b"})
    with pytest.raises(RuntimeError, match="None of the proxies"):
        daily_update.get_polls_until_latest_saved("x.jsonl", ["a", "b"])


def test_refuses_to_crawl_past_max_pages(monkeypatch):
    started, drivers = make_world(monkeypatch)
    monkeypatch.setattr(daily_update, "find_sondaggi_table", lambda driver: [dict(NEW, Row=1)])
    monkeypatch.setattr(daily_update, "handle_one_pagina", lambda driver, page, upto_row=None: [NEW])
    with pytest.raises(RuntimeError, match="refusing to crawl"):
        daily_update.get_polls_until_latest_saved("x.jsonl", ["a"])
    assert drivers[-1].quit_called


def test_get_proxies_env(monkeypatch):
    monkeypatch.delenv("SCRAPER_PROXIES", raising=False)
    monkeypatch.delenv("SCRAPER_PROXY", raising=False)
    assert daily_update.get_proxies() == ["direct"]
    monkeypatch.setenv("SCRAPER_PROXY", "1.1.1.1:80")
    assert daily_update.get_proxies() == ["1.1.1.1:80"]
    monkeypatch.setenv("SCRAPER_PROXIES", "1.1.1.1:80, 2.2.2.2:8080,")
    assert daily_update.get_proxies() == ["1.1.1.1:80", "2.2.2.2:8080"]
