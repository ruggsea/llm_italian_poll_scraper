import json
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime
import matplotlib.dates as mdates

parties_list = [
    "Partito Democratico",
    "Forza Italia",
    "Fratelli d'Italia",
    "Alleanza Verdi Sinistra",
    "Lega",
    "Movimento 5 Stelle",
    "+Europa",
    "Azione",
    "Italia Viva",
    "Altri"
]

party_colors = {
    "Partito Democratico": "red",
    "Forza Italia": "lightblue",
    "Fratelli d'Italia": "blue",
    "Alleanza Verdi Sinistra": "green",
    "Lega": "darkgreen",
    "Movimento 5 Stelle": "yellow",
    "+Europa": "gold",
    "Azione": "navy",
    "Italia Viva": "pink",
    "Altri": "grey"
}


            

def load_and_process_data(filepath):
    with open(filepath, "r") as file:
        polls = [json.loads(line) for line in file]
    
    df = pd.DataFrame(polls)
    df['date'] = pd.to_datetime(df['Data Inserimento'], format='%d/%m/%Y')
    df = df.sort_values('date')
    
    for party in parties_list:
        # each party percentages is either a string or a float, make sure it's a float
        for i, row in df.iterrows():
            if type(row[party]) == str:
                try:
                    df.at[i, party] = float(row[party].replace("%", "").replace(",", "."))
                except (ValueError, ValueError):
                    df.at[i, party] = None
            elif type(row[party]) == int:
                df.at[i, party] = float(row[party])
            
        
    # drop polls with more than 3 missing values in the party percentages
    df = df.dropna(subset=parties_list, thresh=len(parties_list) - 4)
    
    # how many nas per party
    print(f"Missing values per party:")
    print(df[parties_list].isna().sum())
    
    # make sure every party percentage is a float
    for party in parties_list:
        df[party] = df[party].astype(float)
    
    return df

def calculate_moving_average(df, span=10):
    ewm = df[parties_list].ewm(span=span, adjust=False).mean()
    
    
    # Normalize to ensure sum is 100%
    normalized = ewm.div(ewm.sum(axis=1), axis=0) * 100
    
    # order the columns by value in the last row
    normalized = normalized[sorted(normalized.columns, key=lambda x: normalized[x].iloc[-1], reverse=True)]
    return normalized

def make_temporal_plot(moving_averages, df, gaps=None):
    plt.figure(figsize=(20, 12))
    plt.title("Italian Political Polls Moving Averages")
    
    
    
    # do not plot azione, +europa, italia viva and altri
    for party in parties_list:
        if party in ["Azione", "+Europa", "Italia Viva", "Altri"]:
            continue
        plt.plot(df['date'], moving_averages[party], label=party, color=party_colors[party])
        
    plt.legend()
    plt.ylim(0, 50)
    plt.xlabel('Date')
    plt.ylabel('Percentage')
    

    
    plt.gca().xaxis.set_major_locator(mdates.YearLocator())
    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    
    # x axis should start from the first date
    plt.xlim(df['date'].iloc[0], df['date'].iloc[-1])
    
    
    plt.grid(True, which='both', linestyle='--', linewidth=0.5)
    plt.tight_layout()
    plt.savefig("latest_average_plot.png")

def main():
    filepath = "italian_polls.jsonl"
    df = load_and_process_data(filepath)
    moving_averages = calculate_moving_average(df, span=15)
    
    for party in parties_list:
        print(f"{party}: {moving_averages[party].iloc[-1]:.2f}%")
    print(f"Sum: {moving_averages.iloc[-1].sum():.2f}%")
    make_temporal_plot(moving_averages, df)

if __name__ == "__main__":
    main()
