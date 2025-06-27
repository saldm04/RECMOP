import logging
import os
import geopandas as gpd
import pandas as pd
from datetime import datetime

logger = logging.getLogger(__name__)

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
    """
    Carica e normalizza il file panels.csv contenente i dati dei pannelli fotovoltaici.
    Verifica che il file esista e contenga dati validi.
    Utilizza logging per messaggi informativi e di debug.
    """
    pannelli_path = os.path.join('offerta', 'panel', 'panels.csv')

    if not os.path.isfile(pannelli_path):
        logger.error(f"File pannelli non trovato: {pannelli_path}")
        raise FileNotFoundError(f"File pannelli non trovato: {pannelli_path}")

    df_pannelli = pd.read_csv(pannelli_path, sep=',', encoding='utf-8-sig')

    if df_pannelli.empty:
        logger.error("Il file dei pannelli è vuoto o non contiene dati validi.")
        raise ValueError("Il file dei pannelli è vuoto o non contiene dati validi.")

    logger.debug(f"Colonne lette: {df_pannelli.columns.tolist()}")

    # Normalizza intestazioni
    df_pannelli.columns = (
        df_pannelli.columns
        .str.strip()
        .str.replace('\ufeff', '')  # rimuove BOM se presente
        .str.replace(r'\s*\((.*?)\)', lambda m: f"({m.group(1)})", regex=True)
    )

    logger.debug(f"Colonne normalizzate: {df_pannelli.columns.tolist()}")

    logger.info(f"File pannelli caricato correttamente con {len(df_pannelli)} righe.")
    return df_pannelli


def normalize_fabbricati_input(dir_path: str, provincia: str, comune: str) -> bool:
    """
    Normalizza il contenuto di una directory contenente un singolo shapefile:
    - Se esiste una sottodirectory chiamata 'fabbricati_{provincia}_{comune}', lavora su quella (altrimenti ritorna False)
    - Verifica la presenza di un solo shapefile (altrimenti ritorna False)
    - Controlla che il file contenga geometrie (altrimenti ritorna False)
    - Controlla se esiste la colonna 'FID'; se assente, la crea
    - Rimuove tutte le colonne tranne 'FID' e la geometria
    - Rinomina tutti i file nella cartella con il prefisso 'fabbricati_{provincia}_{comune}'
      (ritorna True)
    """

    base_name = f"fabbricati_{provincia.lower()}_{comune.lower()}"
    target_dir = os.path.join(dir_path, base_name)

    if not os.path.isdir(target_dir):
        logger.warning(f"Directory non trovata: {target_dir}")
        return False

    files = os.listdir(target_dir)
    shp_files = [f for f in files if f.lower().endswith(".shp")]

    if len(shp_files) != 1:
        logger.warning(f"Attesi 1 shapefile, trovati {len(shp_files)}: {shp_files}")
        return False

    shp_name = shp_files[0]
    shp_path = os.path.join(target_dir, shp_name)

    try:
        gdf = gpd.read_file(shp_path)
    except Exception as e:
        logger.error(f"Errore nel caricamento dello shapefile: {e}")
        return False

    if gdf.empty or gdf.geometry.isna().all():
        logger.warning("Il file non contiene geometrie valide.")
        return False

    if "FID" not in gdf.columns:
        logger.info("Colonna 'FID' assente: viene creata.")
        gdf.insert(0, "FID", range(len(gdf)))
    else:
        logger.info("Colonna 'FID' già presente.")

    gdf = gdf[["FID", gdf.geometry.name]]
    logger.info("Shapefile normalizzato con solo 'FID' e geometria.")

    # Rimozione vecchi componenti
    base_noext = shp_name.rsplit(".shp", 1)[0]
    for ext in [".shp", ".shx", ".dbf", ".prj", ".cpg", ".qpj"]:
        path = os.path.join(target_dir, base_noext + ext)
        if os.path.exists(path):
            os.remove(path)
            logger.debug(f"File rimosso: {path}")

    # Salvataggio nuovo shapefile
    new_shp_path = os.path.join(target_dir, f"{base_name}.shp")
    gdf.to_file(new_shp_path, driver="ESRI Shapefile")
    logger.info(f"Shapefile salvato: {new_shp_path}")

    # Rinomina file rimanenti con prefisso coerente
    for old_file in os.listdir(target_dir):
        old_path = os.path.join(target_dir, old_file)
        ext = os.path.splitext(old_file)[1]
        new_name = f"{base_name}{ext}"
        new_path = os.path.join(target_dir, new_name)
        os.rename(old_path, new_path)
        logger.debug(f"File rinominato: {old_file} -> {new_name}")

    logger.info(f"Normalizzazione completata per: {base_name}")
    return True

def normalize_dsm_input(dir_path: str, provincia: str, comune: str) -> bool:
    """
    Controlla se nella directory specificata è presente esattamente il file DSM_{provincia}_{comune}.tif.

    Restituisce:
        True se il file esiste, False altrimenti.
    """
    expected_name = f"DSM_{provincia}_{comune}.tif"
    file_path = os.path.join(dir_path, expected_name)

    if not os.path.isdir(dir_path):
        logger.warning(f"Directory non trovata: {dir_path}")
        return False

    if os.path.isfile(file_path):
        logger.info(f"File DSM trovato: {file_path}")
        return True
    else:
        logger.warning(f"File DSM non trovato: {file_path}")
        return False

def get_file_modification_date(file_path: str) -> str:
    """
    Restituisce la data e ora dell'ultima modifica del file in formato leggibile.
    Se il file non esiste, ritorna 'File non trovato'.
    """
    if os.path.isfile(file_path):
        print(f"Controllo ultima modifica per: {file_path}")
        timestamp = os.path.getmtime(file_path)
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
    else:
        return "File non trovato"

def configure_logging_globale(attivo: bool, livello: int = logging.INFO) -> None:
    """
    Configura il logging globale: visibile anche da altri moduli.
    Se è già stato configurato, non fa nulla.
    """
    if not logging.getLogger().hasHandlers():
        logging.basicConfig(
            level=livello if attivo else logging.CRITICAL,
            format="%(asctime)s - %(levelname)s - %(message)s"
        )

def configure_logging_if_main(name: str, level: int = logging.INFO) -> None:
    """
    Configura il logging solo se il modulo viene eseguito direttamente (__main__).

    Args:
        name (str): Il valore di __name__ dal modulo chiamante.
        level (int): Il livello di logging da usare (default: logging.INFO).
    """
    if name == "__main__":
        logging.basicConfig(
            level=level,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )