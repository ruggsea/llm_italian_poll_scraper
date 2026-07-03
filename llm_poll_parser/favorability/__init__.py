"""
Favorability v2: crawl every archive document, classify favorability tables
mechanically first, extract with the LLM only where code cannot, store
long-format rows under a strict metric taxonomy, and average only within
(entity, metric, population=national).

Known gaps (documented, NOT imputed):
- Ipsos publishes a per-leader "indice di gradimento" (Conte ~48) computed on
  expressers, but deposits only raw positives (Conte ~30) — the per-leader
  non-response needed to derive the index is not in the archive. The two live
  under different metrics (gradimento_index vs giudizi_positivi_pct) and are
  never pooled.
- SWG and Noto national leader fiducia series are absent from the archive.
- Deposits lag publication by up to ~1 week; Mattarella comes only from EMG.
"""
