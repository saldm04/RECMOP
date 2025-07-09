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

def _get_target_dir(base_dir: str, base_name: str) -> str:
    target_dir = os.path.join(base_dir, base_name)
    if not os.path.isdir(target_dir):
        logger.warning(f"Directory non trovata: {target_dir}")
        raise ValueError(f"Directory non trovata: {target_dir}")
    return target_dir

def _get_single_shapefile(target_dir: str) -> str:
    files = os.listdir(target_dir)
    shp_files = [f for f in files if f.lower().endswith(".shp")]
    if len(shp_files) != 1:
        logger.warning(f"Atteso 1 shapefile, trovati {len(shp_files)}: {shp_files}")
        raise ValueError(f"Atteso 1 shapefile, trovati {len(shp_files)}: {shp_files}")
    return os.path.join(target_dir, shp_files[0])

def _read_valid_gdf(shp_path: str) -> gpd.GeoDataFrame:
    try:
        gdf = gpd.read_file(shp_path)
    except Exception as e:
        logger.error(f"Errore nel caricamento dello shapefile: {e}")
        raise RuntimeError(f"Errore nel caricamento dello shapefile: {e}")
    if gdf.empty or gdf.geometry.isna().all():
        logger.warning("Il file non contiene geometrie valide.")
        raise ValueError("Il file non contiene geometrie valide.")
    return gdf

def _clear_folder(target_dir: str):
    for fname in os.listdir(target_dir):
        path = os.path.join(target_dir, fname)
        if os.path.isfile(path):
            os.remove(path)
            logger.debug(f"File rimosso: {path}")

def _save_and_rename_shapefile(gdf: gpd.GeoDataFrame, target_dir: str, base_name: str):
    new_shp_path = os.path.join(target_dir, f"{base_name}.shp")
    gdf.to_file(new_shp_path, driver="ESRI Shapefile")
    logger.info(f"Shapefile salvato: {new_shp_path}")
    # Rinominare tutti i file in base_name + estensione
    for old_file in os.listdir(target_dir):
        old_path = os.path.join(target_dir, old_file)
        ext = os.path.splitext(old_file)[1]
        new_name = f"{base_name}{ext}"
        new_path = os.path.join(target_dir, new_name)
        os.rename(old_path, new_path)
        logger.debug(f"File rinominato: {old_file} -> {new_name}")

def normalize_fabbricati_input_auto(dir_path: str, provincia: str, comune: str) -> str:
    """
    Normalizza il contenuto di una directory contenente un singolo shapefile:
    - Se esiste una sottodirectory chiamata 'fabbricati_{provincia}_{comune}', lavora su quella (altrimenti solleva ValueError)
    - Verifica la presenza di un solo shapefile (altrimenti solleva ValueError)
    - Controlla che il file contenga geometrie (altrimenti solleva ValueError)
    - In base alle colonne presenti mantiene solo quelle utili:
      - Solo ID_FAB + geometria: ritorna 'zc_range'
      - ID_FAB + geometria + sup_risc + vol_risc: ritorna 'zc_suris_volris'
      - ID_FAB + geometria + sup_risc + vol_risc + sup_disp: ritorna 'zc_suris_volris_supdi'
      - Se presente la colonna opzionale delta_UHI, non la eliminare (vale per i tre modelli citati)
    - Rinomina tutti i file nella cartella con il prefisso 'fabbricati_{provincia}_{comune}'
    - In caso di errore solleva ValueError o RuntimeError.
    """
    base_name = f"fabbricati_{provincia}_{comune}"
    target_dir = _get_target_dir(dir_path, base_name)
    shp_path = _get_single_shapefile(target_dir)
    gdf = _read_valid_gdf(shp_path)

    # Determina le colonne da mantenere e la stringa di ritorno
    has_sup_risc = "sup_risc" in gdf.columns
    has_vol_risc = "vol_risc" in gdf.columns
    has_sup_disp = "sup_disp" in gdf.columns
    has_delta_UHI = "delta_UHI" in gdf.columns  # opzionale

    # Determina quali colonne tenere, considerando delta_UHI se presente
    keep_cols = ["ID_FAB"]
    if has_delta_UHI:
        keep_cols.append("delta_UHI")

    if has_sup_risc and has_vol_risc and has_sup_disp:
        keep_cols += ["sup_risc", "vol_risc", "sup_disp", gdf.geometry.name]
        return_string = "zc_suris_volris_supdi"
    elif has_sup_risc and has_vol_risc:
        keep_cols += ["sup_risc", "vol_risc", gdf.geometry.name]
        return_string = "zc_suris_volris"
    elif not has_sup_risc and not has_vol_risc and not has_sup_disp:
        keep_cols += [gdf.geometry.name]
        return_string = "zc_range"
    else:
        raise ValueError(
            "Colonne non coerenti: servono entrambi sup_risc e vol_risc (opzionale sup_disp), "
            "oppure nessuna delle tre per 'zc_range'."
        )

    # Controllo/aggiunta colonna ID_FAB
    if "ID_FAB" not in gdf.columns:
        logger.info("Colonna 'ID_FAB' assente: viene creata.")
        gdf.insert(0, "ID_FAB", range(len(gdf)))
    else:
        logger.info("Colonna 'ID_FAB' già presente.")

    # Mantieni solo le colonne necessarie (senza duplicare geometry se già inclusa)
    if gdf.geometry.name not in keep_cols:
        keep_cols.append(gdf.geometry.name)
    gdf = gdf[[col for col in keep_cols if col in gdf.columns]]

    logger.info(f"Shapefile normalizzato con colonne: {gdf.columns.tolist()}.")
    _clear_folder(target_dir)
    _save_and_rename_shapefile(gdf, target_dir, base_name)
    logger.info(f"Normalizzazione completata per: {base_name} (tipo {return_string})")
    return return_string

def normalize_vincoli_input(dir_path: str, provincia: str, comune: str) -> bool:
    base_name = f"vincoli_{provincia}_{comune}"
    target_dir = os.path.join(dir_path, base_name)
    if not os.path.isdir(target_dir):
        logger.info(f"Directory vincoli non trovata: {target_dir}")
        return False

    shp_path = None
    shp_files = [f for f in os.listdir(target_dir) if f.lower().endswith(".shp")]
    if not shp_files:
        logger.info(f"Nessuno shapefile trovato nella directory: {target_dir}")
        return False
    if len(shp_files) != 1:
        logger.warning(f"Atteso 1 shapefile, trovati {len(shp_files)}: {shp_files}")
        return False

    shp_path = os.path.join(target_dir, shp_files[0])
    try:
        gdf = _read_valid_gdf(shp_path)
    except Exception as e:
        logger.warning(f"Errore nel caricamento shapefile dei vincoli: {e}")
        return False

    gdf = gdf[[gdf.geometry.name]]
    logger.info(f"Shapefile normalizzato: mantenuta solo la geometria ({gdf.geometry.name}).")
    _clear_folder(target_dir)
    _save_and_rename_shapefile(gdf, target_dir, base_name)
    return True

def normalize_dsm_input(dir_path: str, tif_path: str, provincia: str, comune: str) -> None:
    """
    Controlla se nella directory specificata è presente esattamente il file DSM_{provincia}_{comune}.tif.
    Se non esiste, controlla se esiste irradianza_annua_{provincia}_{comune}_kwh.tif in tif_path.
    Solleva:
        ValueError se la directory non esiste.
        FileNotFoundError se nessuno dei due file esiste.
    Restituisce:
        None se tutto ok.
    """
    expected_dsm = f"DSM_{provincia}_{comune}.tif"
    expected_irr = f"irradianza_annua_{provincia}_{comune}_kwh.tif"

    dsm_path = os.path.join(dir_path, expected_dsm)
    irr_path = os.path.join(tif_path, expected_irr)

    if not os.path.isdir(dir_path):
        logger.warning(f"Directory non trovata: {dir_path}")
        raise ValueError(f"Directory non trovata: {dir_path}")

    if os.path.isfile(dsm_path):
        logger.info(f"File DSM trovato: {dsm_path}")
        return None

    # DSM non trovato, controllo l'irradianza
    if os.path.isfile(irr_path):
        logger.info(f"File irradianza trovato: {irr_path}")
        return None

    # Nessuno dei due file trovato
    logger.warning(f"File DSM non trovato: {dsm_path} e file irradianza non trovato: {irr_path}")
    raise FileNotFoundError(
        f"File DSM non trovato: {dsm_path} e file irradianza non trovato: {irr_path}"
    )

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