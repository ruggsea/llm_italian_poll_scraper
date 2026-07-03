"""
Favorability v2: crawl every archive document, classify favorability tables
mechanically first, extract with the LLM only where code cannot, store
long-format rows under a strict metric taxonomy, and average only within
(entity, metric, population=national).

Known gaps (documented, NOT imputed):
- Ipsos deposits its per-leader "indice di gradimento" (positives over
  expressers) but no other pollster does, so gradimento_index is an
  Ipsos-only series for the leaders and the government/PM — it is published
  per-pollster, never as a cross-pollster average (n_pollsters < 2). It is
  kept strictly apart from the raw full-sample giudizi_positivi_pct family
  (Demos&Pi/Eumetra "voto >= 6"); pooling the two scales was the v1 defect.
- SWG and Noto national leader fiducia series are absent from the archive.
- Deposits lag publication by up to ~1 week; Mattarella comes only from EMG.
"""
