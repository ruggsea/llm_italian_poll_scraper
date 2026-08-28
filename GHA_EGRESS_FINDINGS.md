# GHA-hosted egress findings (branch fix/gha-hosted-egress, 2026-08-28)

Goal: make the daily scrape work on GitHub-hosted runners (`ubuntu-latest`) again,
without the artemis self-hosted runner. **Verdict: not viable long-term. The
tarpit is per-IP and datacenter-broad; the few unblocked Azure IPs (~2/26 at
00:10–00:27 UTC on 2026-08-28) dropped to 0/48 within the hour. A 32-attempt
reachability-gated matrix is implemented here as a free fallback, but keep the
artemis runner (branch fix/gha-site-timeout) as the primary path.**

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

## Round 3-4: it's an IP lottery, not a fingerprint block

Same-runner test (r3): plain curl, curl with a Firefox UA, and real headless
Firefox ALL timed out from egress 20.161.45.113 → block is per-IP, not per-client.
An 8-runner matrix (r4): **1/8 runners reached the site** (57.151.83.102 → http 200;
other 7: 40.116.x, 40.76.x, 158.23.x, 20.161.x, 172.184.x, 52.238.x all tarpitted).
Separately, a full `daily_update.py` run on ubuntu-latest SUCCEEDED end-to-end
(scrape → parse → plot) on a runner that drew an unblocked IP.

## Chosen workaround: reachability-lottery matrix (implemented in daily_update.yaml)

16 parallel matrix attempts; each sleeps `(N-1)*120s`, probes the homepage, and
only proceeds if reachable. Before scraping it checks whether a
`Daily update: <today>` commit already exists on main (idempotence guard), so in
practice exactly one attempt does the work. Push stays guarded to
`github.ref == 'refs/heads/main'`.

Estimated daily success at the ~1/8 rate measured around 00:27 UTC: ~88%.
BUT see below — reachability collapsed to 0/48 within the hour, so the real
rate is unstable and can be zero for long stretches. The matrix was later
bumped to 32 attempts / 60 s stagger.

## Viable paths, honestly

1. **Keep the artemis self-hosted runner** (branch `fix/gha-site-timeout`) —
   deterministic, zero cost, already set up. Still the safest choice.
2. **This branch's shotgun matrix on ubuntu-latest** — free, no keys, works
   ~9 days out of 10 at the current block rate; degrades if the site blocks more
   Azure ranges. Also relies on the site never tightening to ALL Azure IPs.
3. Paid/keyed scraping proxy with residential or unblocked DC IPs (ScraperAPI,
   ScrapingBee…). Even ScraperAPI's free tier needs API-key signup → out of scope
   per mission constraints. STOP.
4. (Hybrid, not pursued) GHA job egressing through artemis via a Tailscale exit
   node — still depends on artemis, adds secrets/complexity, defeats the purpose.

## End-to-end validation (STEP 3)

- Plain main-style workflow on ubuntu-latest (run 33129476621): scrape SUCCEEDED
  (lucky IP), run failed only at the branch-dispatch push-to-main step.
- Shotgun matrix, 16 attempts (run 33129919480): **0/16 reachable**, no scrape.
- Shotgun matrix, 32 attempts (run 33131628472): **0/32 reachable**, no scrape.

Timeline on 2026-08-28 (UTC): 00:10–00:27 → 2 of ~10 runner instances reached the
site (one full successful scrape); after 00:30 → 0 of 48. The unblocked Azure
pool shrank to zero within the hour — whether it comes back is unknown and
outside our control.

## Final verdict

**GHA-hosted is not viable long-term.** The site tarpits datacenter IPs broadly
and apparently adapts; the brief window of unblocked Azure IPs closed within an
hour of measurement. The 32-attempt matrix in this branch's daily_update.yaml is
kept as a free fallback (it self-skips and costs nothing when unreachable), but
the artemis self-hosted runner (branch fix/gha-site-timeout) should stay the
primary path. Only a paid residential/keyed proxy would make GHA-hosted
deterministic — out of scope (signup wall) per mission constraints.

