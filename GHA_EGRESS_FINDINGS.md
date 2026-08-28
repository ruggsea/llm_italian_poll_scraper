# GHA-hosted egress findings (branch fix/gha-hosted-egress, 2026-08-28)

Goal: make the daily scrape work on GitHub-hosted runners (`ubuntu-latest`) again,
without the artemis self-hosted runner. **Verdict: not viable without a paid/keyed
proxy. Keep the artemis runner (branch fix/gha-site-timeout).**

## What the pipeline actually needs (STEP 0)

`daily_update.py` → `get_polls_until_latest_saved` paginates the listing with the
`PaginaSuccessiva` WebForms postback until it reaches the newest already-saved poll,
and `handle_one_pagina` clicks into every "intenzioni di voto" row. Per run:

1. GET `Home.aspx?st=HOME` (sets `ASP.NET_SessionId`; without it
   `ListaSondaggi.aspx` 302s to `Home.aspx?sessionended=1`)
2. GET `ListaSondaggi.aspx?st=SONDAGGI` (with the session cookie)
3. POST back to `ListaSondaggi.aspx` with `__VIEWSTATE`/`__VIEWSTATEGENERATOR`/
   `__EVENTVALIDATION` + `ctl00$Contenuto$dgSondaggi_PaginaSuccessiva=" > "` per page
   (verified working with plain curl from a residential IP: page 1 first date
   16/08/2026 → page 2 first date 03/08/2026)
4. Per poll: row-click postback → "Domande" tab postback → question postback → back.

So a single-shot fetch is NOT enough — the scrape needs dozens of sequential,
stateful (cookie + viewstate) requests through the SAME egress IP. Any workaround
must support cookies + POSTs + multi-request sessions.

## Probe results from a GitHub-hosted runner (STEP 1)

Debug runs: see workflow run history on this branch (debug workflow since deleted).

| Method | Result |
|---|---|
| a) direct | FAIL — http=000 after 25 s (tarpit confirmed on Azure IPs) |
| b1) api.allorigins.win/raw | FAIL — 408 (their DC fetch to the site times out; also blocked) |
| b2) corsproxy.io | FAIL — 401 (now requires an API key → signup wall, out of scope) |
| c) r.jina.ai | FAIL — 422, their browser times out navigating to the site (DC IPs blocked too) |
| d) free HTTP proxies (proxyscrape list) | PARTIAL — 2/30 (152.53.136.178:10000, 51.146.240.4:3128) fetched Home+Lista once; both died before the next request; postback through them FAILED. One was already dead minutes later from another host. |
| e) translate.goog proxy | FAIL — 408 on both Home and Lista |

The site does not just tarpit Azure: allorigins, jina and translate.goog fetch
fleets (all datacenter IPs) time out as well. The blocklist appears to cover
datacenter ASNs broadly; residential IPs work.

## Why free proxies don't save us (STEP 2)

Even when one proxy completes a single GET, the flow needs dozens of sequential
requests through it (see above). Free public proxies die mid-flow — observed both
from the runner and locally. A daily cron on proxy roulette would fail most days
and hammer a public-service site from random open proxies. Not a real option.

## Viable paths, honestly

1. **Keep the artemis self-hosted runner** (branch `fix/gha-site-timeout`) — works
   today, zero cost, already set up. Recommended.
2. Paid/keyed scraping proxy with residential or unblocked DC IPs (ScraperAPI,
   ScrapingBee, Bright Data…). ScraperAPI has a free tier (1k credits/mo — a daily
   run needs ~50+ requests/run ⇒ ~1.5k/mo, so even that tier is marginal), but
   requires API-key signup → out of scope for this mission, documented here per
   instructions. STOP.
3. (Hybrid, not pursued) GHA job egressing through artemis via a Tailscale exit
   node — still depends on artemis, adds secrets/complexity, defeats the purpose.

## End-to-end validation (STEP 3)

`daily_update.yaml` dispatched on this branch with `runs-on: ubuntu-latest`:
expected failure at `driver.get(...)` (Selenium netTimeout / page-load timeout),
same as the failures since 2026-08-16. See run URL in the mission report.
