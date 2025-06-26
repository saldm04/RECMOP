import os

import pandas as pd


def safe_name(nome: str) -> str:
    """Restituisce il nome in minuscolo e con spazi sostituiti da -."""
    return nome.strip().lower().replace(' ', '-').replace("'","-")

def get_regione_from_provincia(provincia: str) -> str:
    """
    Mappa il nome di una provincia alla sua regione italiana.
    """
    provincia = safe_name(provincia)

    mappa_provincia_regione = {
        # piemonte
        "torino": "piemonte", "vercelli": "piemonte", "biella": "piemonte", "cuneo": "piemonte",
        "asti": "piemonte", "alessandria": "piemonte", "novara": "piemonte",
        # valle-d'aosta
        "aosta": "valle-d'aosta",
        # lombardia
        "varese": "lombardia", "como": "lombardia", "sondrio": "lombardia", "milano": "lombardia",
        "bergamo": "lombardia", "brescia": "lombardia", "pavia": "lombardia", "cremona": "lombardia",
        "mantova": "lombardia",
        # trentino-alto-adige
        "bolzano": "trentino-alto-adige", "trento": "trentino-alto-adige",
        # veneto
        "verona": "veneto", "vicenza": "veneto", "belluno": "veneto", "treviso": "veneto",
        "venezia": "veneto", "padova": "veneto", "rovigo": "veneto",
        # friuli-venezia-giulia
        "udine": "friuli-venezia-giulia", "gorizia": "friuli-venezia-giulia",
        "trieste": "friuli-venezia-giulia", "pordenone": "friuli-venezia-giulia",
        # liguria
        "imperia": "liguria", "savona": "liguria", "genova": "liguria", "la-spezia": "liguria",
        # emilia-romagna
        "piacenza": "emilia-romagna", "parma": "emilia-romagna", "reggio-emilia": "emilia-romagna",
        "modena": "emilia-romagna", "bologna": "emilia-romagna", "ferrara": "emilia-romagna",
        "ravenna": "emilia-romagna", "forlì-cesena": "emilia-romagna",
        # toscana
        "massa-carrara": "toscana", "lucca": "toscana", "pistoia": "toscana", "firenze": "toscana",
        "livorno": "toscana", "pisa": "toscana", "arezzo": "toscana", "siena": "toscana", "grosseto": "toscana",
        # umbria
        "perugia": "umbria", "terni": "umbria",
        # marche
        "pesaro-e-urbino": "marche", "ancona": "marche", "macerata": "marche", "ascoli-piceno": "marche",
        # lazio
        "viterbo": "lazio", "rieti": "lazio", "roma": "lazio", "latina": "lazio", "frosinone": "lazio",
        # abruzzo
        "l'aquila": "abruzzo", "teramo": "abruzzo", "pescara": "abruzzo", "chieti": "abruzzo",
        # molise
        "campobasso": "molise", "isernia": "molise",
        # campania
        "caserta": "campania", "benevento": "campania", "napoli": "campania",
        "avellino": "campania", "salerno": "campania",
        # puglia
        "foggia": "puglia", "bari": "puglia", "taranto": "puglia",
        "brindisi": "puglia", "lecce": "puglia",
        # basilicata
        "potenza": "basilicata", "matera": "basilicata",
        # calabria
        "cosenza": "calabria", "catanzaro": "calabria", "reggio-calabria": "calabria",
        # sicilia
        "trapani": "sicilia", "palermo": "sicilia", "messina": "sicilia", "agrigento": "sicilia",
        "caltanissetta": "sicilia", "enna": "sicilia", "catania": "sicilia", "ragusa": "sicilia", "siracusa": "sicilia",
        # sardegna
        "sassari": "sardegna", "nuoro": "sardegna", "cagliari": "sardegna", "oristano": "sardegna"
    }

    if provincia not in mappa_provincia_regione:
        raise ValueError(f"Provincia '{provincia}' non riconosciuta o non presente in mappa.")

    return mappa_provincia_regione[provincia]

def get_pannelli() -> pd.DataFrame:
    pannelli_path = os.path.join('offerta', 'panel', 'panels.csv')
    if not os.path.isfile(pannelli_path):
        raise FileNotFoundError(f"File pannelli non trovato: {pannelli_path}")

    df_pannelli = pd.read_csv(pannelli_path, sep=',', encoding='utf-8-sig')
    if df_pannelli.empty:
        raise ValueError("Il file dei pannelli è vuoto o non contiene dati validi.")

    # Stampa intestazioni originali per debug
    print("Colonne lette:", df_pannelli.columns.tolist())

    # Normalizza intestazioni
    df_pannelli.columns = (
        df_pannelli.columns
        .str.strip()
        .str.replace('\ufeff', '')  # toglie eventuale BOM
        .str.replace(r'\s*\((.*?)\)', lambda m: f"({m.group(1)})", regex=True)
    )

    # Stampa intestazioni normalizzate
    print("Colonne normalizzate:", df_pannelli.columns.tolist())

    return df_pannelli

