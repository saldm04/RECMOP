import logging
import os
import geopandas as gpd
import numpy as np
import pandas as pd
from datetime import datetime
import rasterio
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

def raster_is_empty(raster_path: str) -> bool:
    """Ritorna True se tutte le celle sono NaN."""
    try:
        with rasterio.open(raster_path) as src:
            arr = src.read(1)
            return np.isnan(arr).all()
    except Exception as e:
        logger.error(f"Errore nell'apertura del raster {raster_path}: {e}")
        return True  # Se il raster non si apre, consideralo vuoto

def load_dot_env(env_path: str = ".env") -> None:
    """
    Carica le variabili d'ambiente da un file .env specificato.
    Se non viene passato un path, cerca ".env" nella directory corrente.

    :param env_path: Percorso al file .env (può essere assoluto o relativo)
    """
    abs_path = os.path.abspath(env_path)
    if not os.path.exists(abs_path):
        logger.warning(f"File .env non trovato nel percorso specificato: {abs_path}")
        return

    load_dotenv(dotenv_path=abs_path)
    logger.info(f"Variabili d'ambiente caricate da: {abs_path}")

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

def normalize_fabbricati_input_auto(dir_path: str, provincia: str, comune: str) -> str:
    """
    Normalizza il contenuto di una directory contenente un singolo shapefile:
    - Se esiste una sottodirectory chiamata 'fabbricati_{provincia}_{comune}', lavora su quella (altrimenti solleva ValueError)
    - Verifica la presenza di un solo shapefile (altrimenti solleva ValueError)
    - Controlla che il file contenga geometrie (altrimenti solleva ValueError)
    - In base alle colonne presenti mantiene solo quelle utili:
      - Solo FID + geometria: ritorna 'zc_range'
      - FID + geometria + sup_risc + vol_risc: ritorna 'zc_suris_volris'
      - FID + geometria + sup_risc + vol_risc + sup_disp: ritorna 'zc_suris_volris_supdi'
    - Rinomina tutti i file nella cartella con il prefisso 'fabbricati_{provincia}_{comune}'
    - In caso di errore solleva ValueError o RuntimeError.
    """
    base_name = f"fabbricati_{provincia}_{comune}"
    target_dir = os.path.join(dir_path, base_name)

    if not os.path.isdir(target_dir):
        logger.warning(f"Directory non trovata: {target_dir}")
        raise ValueError(f"Directory non trovata: {target_dir}")

    files = os.listdir(target_dir)
    shp_files = [f for f in files if f.lower().endswith(".shp")]

    if len(shp_files) != 1:
        logger.warning(f"Attesi 1 shapefile, trovati {len(shp_files)}: {shp_files}")
        raise ValueError(f"Attesi 1 shapefile, trovati {len(shp_files)}: {shp_files}")

    shp_name = shp_files[0]
    shp_path = os.path.join(target_dir, shp_name)

    try:
        gdf = gpd.read_file(shp_path)
    except Exception as e:
        logger.error(f"Errore nel caricamento dello shapefile: {e}")
        raise RuntimeError(f"Errore nel caricamento dello shapefile: {e}")

    if gdf.empty or gdf.geometry.isna().all():
        logger.warning("Il file non contiene geometrie valide.")
        raise ValueError("Il file non contiene geometrie valide.")

    # Determina le colonne da mantenere e la stringa di ritorno
    has_sup_risc = "sup_risc" in gdf.columns
    has_vol_risc = "vol_risc" in gdf.columns
    has_sup_disp = "sup_disp" in gdf.columns

    if has_sup_risc and has_vol_risc and has_sup_disp:
        keep_cols = ["FID", "sup_risc", "vol_risc", "sup_disp", gdf.geometry.name]
        return_string = "zc_suris_volris_supdi"
    elif has_sup_risc and has_vol_risc:
        keep_cols = ["FID", "sup_risc", "vol_risc", gdf.geometry.name]
        return_string = "zc_suris_volris"
    elif not has_sup_risc and not has_vol_risc and not has_sup_disp:
        keep_cols = ["FID", gdf.geometry.name]
        return_string = "zc_range"
    else:
        # Se c'è almeno una delle colonne ma la combinazione non è valida
        raise ValueError(
            "Colonne non coerenti: servono entrambi sup_risc e vol_risc (opzionale sup_disp), "
            "oppure nessuna delle tre per 'zc_range'.")

    # Controllo/aggiunta colonna FID
    if "FID" not in gdf.columns:
        logger.info("Colonna 'FID' assente: viene creata.")
        gdf.insert(0, "FID", range(len(gdf)))
    else:
        logger.info("Colonna 'FID' già presente.")

    # Mantieni solo le colonne necessarie
    gdf = gdf[[col for col in keep_cols if col in gdf.columns] + [gdf.geometry.name] if gdf.geometry.name not in keep_cols else keep_cols]
    logger.info(f"Shapefile normalizzato con colonne: {gdf.columns.tolist()}.")

    # Rimozione di tutti i file dalla cartella
    for fname in os.listdir(target_dir):
        path = os.path.join(target_dir, fname)
        if os.path.isfile(path):
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

    logger.info(f"Normalizzazione completata per: {base_name} (tipo {return_string})")
    return return_string

def normalize_dsm_input(dir_path: str, provincia: str, comune: str) -> None:
    """
    Controlla se nella directory specificata è presente esattamente il file DSM_{provincia}_{comune}.tif.

    Solleva:
        ValueError se la directory non esiste.
        FileNotFoundError se il file DSM non esiste.
    Restituisce:
        None se tutto ok.
    """
    expected_name = f"DSM_{provincia}_{comune}.tif"
    file_path = os.path.join(dir_path, expected_name)

    if not os.path.isdir(dir_path):
        logger.warning(f"Directory non trovata: {dir_path}")
        raise ValueError(f"Directory non trovata: {dir_path}")

    if not os.path.isfile(file_path):
        logger.warning(f"File DSM non trovato: {file_path}")
        raise FileNotFoundError(f"File DSM non trovato: {file_path}")

    logger.info(f"File DSM trovato: {file_path}")
    return None

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

def get_best_utm_epsg(gdf: gpd.GeoDataFrame) -> int:
    """
    Restituisce l'EPSG UTM più adatto sulla base del centroide del GeoDataFrame.
    """
    centroid = gdf.geometry.unary_union.centroid
    lon, lat = centroid.x, centroid.y
    zone_number = int((lon + 180) / 6) + 1
    if lat >= 0:
        return 32600 + zone_number  # emisfero nord
    else:
        return 32700 + zone_number  # emisfero sud