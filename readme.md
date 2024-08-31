## Media di oggi

Partito Democratico: 24.12%
Forza Italia: 9.30%
Fratelli d'Italia: 29.78%
Alleanza Verdi Sinistra: 6.69%
Lega: 8.80%
Movimento 5 Stelle: 10.78%
+Europa: 1.80%
Azione: 3.29%
Italia Viva: 2.24%
Altri: 3.19%
## Grafico
![Latest Moving Average](latest_average_plot.png)

# Archiving Italian Political Polls

Questo progetto si occupa di archiviare tutti i sondaggi mai caricati sul sito ufficiale [sondaggipoliticoelettorali.it](https://www.sondaggipoliticoelettorali.it/), cercando quelli che riguardano l'intenzione di voto nazionale utilizzando il confronto di stringhe e l'estrazione delle risposte al sondaggio utilizzando un Large Language Model (LLM).
Per a chi interessano solo i dati dei sondaggi aggiornati giornalieramente, sono disponibili in formato JSONL nel file `italian_polls.jsonl`.

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

