<a href="https://datibenecomune.substack.com/about"><img src="https://img.shields.io/badge/%F0%9F%99%8F-%23datiBeneComune-%23cc3232"/></a>

Se vuoi più informazioni su questo progetto, ne ho parlato su [datiBeneComune](https://datibenecomune.substack.com/) in [questo numero](https://datibenecomune.substack.com/p/liberiamoli-tutti-numero-8).

## Media di oggi

Fratelli d'Italia: 29.12%  
Partito Democratico: 22.27%  
Movimento 5 Stelle: 13.07%  
Forza Italia: 8.22%  
Altri: 7.20%  
Alleanza Verdi Sinistra: 6.73%  
Lega: 6.18%  
Azione: 3.24%  
Italia Viva: 2.49%  
+Europa: 1.47%  
## Grafico
![Latest Moving Average](latest_average_plot.png)

# Archiving Italian Political Polls

Questo progetto si occupa di archiviare tutti i sondaggi mai caricati sul sito ufficiale [sondaggipoliticoelettorali.it](https://www.sondaggipoliticoelettorali.it/), cercando quelli che riguardano l'intenzione di voto nazionale utilizzando il confronto di stringhe e l'estrazione delle risposte al sondaggio utilizzando un Large Language Model (LLM).
Per a chi interessano solo i dati dei sondaggi aggiornati giornalieramente, sono disponibili in formato JSONL nel file `italian_polls.jsonl` e in formato CSV nel file `italian_polls.csv`. Se invece si desiderano i dati in formato long e ulteriormente puliti, sono disponibili alla sequente repo di onData: [italian_polls](https://github.com/ondata/liberiamoli-tutti/tree/main/italian_polls)

## Requisiti

Avere un'installazione di Python con un setup di Selenium funzionante e le librerie `openai` e `bs4` installate.
Avere nel proprio environment la variabile d'ambiente `OPENAI_API_KEY` settata con la propria chiave API di OpenAI.
Per esserne sicuri, basta installare i requisiti con il seguente comando:

```shell
pip install -r requirements.txt
```


## Installazione

1. Clona il repository sul tuo computer:

```shell
git clone https://github.com/ruggsea/llm_italian_poll_scraper.git
```

2. Entra nella directory del progetto:

```shell
cd llm_italian_poll_scraper
```

## Utilizzo

I sondaggi dovrebbero essere archiviati nel file `italian_polls.jsonl` in formato JSONL. Per aggiornare il file con i nuovi sondaggi, esegui il seguente comando:

```shell
python3 llm_poll_parser/archiving_polls.py
```


## Note

La media si basa sui sondaggi archiviati nel file `italian_polls.jsonl` e viene calcolata tramite media mobile a peso esponenziale (EWMA). Il grafico non riporta Azione, +Europa e Italia Viva poiché le loro unioni e divisioni rendono difficile rappresentarne una serie storica (sono tuttavia presenti nei dati raccolti).

Mentre il dataset è molto affidabile per i sondaggi odierni, potrebbero esserci errori nei sondaggi più vecchi. In particolare, alcuni sondaggi risultano sfasati o vuoti per via di errori di parsing o di mancato filtraggio. Varie correzioni nel parsing sono state apportate: per vederne i frutti, saltuariamente conduco uno scrape completo per ricostruire il dataset da zero usando la versione più aggiornata dello scraper.

## Partiti considerati

Sono considerati in maniera abbastanza esaustiva tutti i partiti sondati nei sondaggi archiviati sul sito (2013-presente). I partiti considerati sono:

- Fratelli d'Italia
- Partito Democratico
- Movimento 5 Stelle
- Forza Italia
- Lega
- Alleanza Verdi Sinistra
- Azione
- Italia Viva
- +Europa
- Pace Terra Dignità
- Sud Chiama Nord
- Stati Uniti d'Europa
- Azione/+Europa
- Azione - Italia Viva
- Unione Popolare
- Sinistra Ecologia Libertà
- Unione di Centro
- Scelta Civica

Sono incoraggiati consigli e suggerimenti su partiti da aggiungere, altri miglioramenti e correzione dei dati: in caso aprire una issue. Grazie!

Per domande, chiarificazione o contatti media contattemi su fu twitter at [ruggsea](https://twitter.com/ruggsea) o al seguente profilo [LinkedIn](https://www.linkedin.com/in/ruggsea/).

## Se usi questi dati

I dati sono rilasciati con licenza **CC BY 4.0**, quindi sei libero di utilizzarli per qualsiasi scopo, a patto di **citare questa fonte**. 

Quando li usi includi per favore la dicitura "dati estratti da [Ruggero Marino Lazzaroni](https://github.com/ruggsea/llm_italian_poll_scraper)", mettendo il link a questo repository (il link è <https://github.com/ruggsea/llm_italian_poll_scraper>).


## Favorability polls (v2, experimental)

Oltre alle intenzioni di voto, il branch `feat/favorability-v2` estrae i sondaggi di **gradimento/fiducia** (Governo e leader nazionali) dall'archivio ufficiale, con una pipeline separata in `llm_poll_parser/favorability/`:

- Ogni documento dell'archivio viene aperto (nessun filtro sul titolo del documento) e le singole domande vengono selezionate con un filtro a livello di domanda.
- Le tabelle vengono classificate da un albero di decisione deterministico (`classify.py`) PRIMA di qualsiasi chiamata LLM; l'LLM interviene solo come fallback su tabelle illeggibili meccanicamente, con output validato da schema. Il payload LLM viene salvato verbatim nel ledger (`favorability_raw.jsonl`), quindi `reprocess` è un replay deterministico e completamente offline: zero chiamate API, stesso output byte-per-byte a ogni esecuzione.
- I numeri sono salvati in formato long (`favorability_polls.jsonl`/`.csv`, una riga per (sondaggio, entità, metrica)) sotto una tassonomia di metriche CHIUSA: `fiducia_pct`, `fiducia_binaria_pct`, `gradimento_index`, `giudizi_positivi_pct`, `most_trusted_share`, `voto_medio_1_10`. Metriche diverse non vengono MAI mediate insieme.
- Breakdown per orientamento politico e sondaggi locali/regionali sono scartati come dati (population != national); le tabelle non classificabili finiscono in `favorability_review_queue.jsonl` per triage umano, mai nel CSV.
- Le medie (`favorability_averages.csv`) sono per (entità, metrica) con dedup di un sondaggio per istituto per finestra di 14 giorni. La media cross-istituto decade nel **tempo di calendario** (peso `0.5 ** (età_giorni / 14)`, con peso zero oltre i 60 giorni), così l'onda vecchia di un istituto lento non pesa quanto quella della settimana corrente; è soppressa dove n_pollsters < 2.

Comandi (dalla root del repo):

```bash
uv run python -m llm_poll_parser.favorability.crawler crawl --min-date 01/07/2025   # riprendibile
uv run python -m llm_poll_parser.favorability.crawler reprocess                     # replay offline dal ledger (deterministico, nessuna chiamata API; --llm per ri-estrarre tabelle senza payload in cache)
uv run python -m llm_poll_parser.favorability.crawler average
uv run python -m llm_poll_parser.favorability.crawler plot
```

**Lacune note (documentate, non imputate):**

- Ipsos deposita il suo "indice di gradimento" per leader (positivi sui soli rispondenti che si esprimono), ma nessun altro istituto lo fa: `gradimento_index` è quindi una serie **solo-Ipsos** per i leader e per Governo/Premier, pubblicata per-istituto e mai come media cross-istituto (n_pollsters < 2). È tenuta rigorosamente separata dai giudizi positivi grezzi sul campione totale (`giudizi_positivi_pct`, es. Demos&Pi/Eumetra "voto ≥ 6"): mescolare le due scale era il difetto della v1.
- Le serie nazionali di fiducia nei leader di SWG e Noto non sono depositate in archivio.
- I depositi ritardano fino a ~1 settimana rispetto alla pubblicazione; Mattarella è coperto solo da EMG (~bisettimanale); Calenda/Renzi sono serie sottili.
