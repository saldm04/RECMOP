import os
import logging
import pandas as pd
import geopandas as gpd
from dbfread import DBF
from utils import safe_name, configure_logging_if_main

# Logger del modulo
logger = logging.getLogger(__name__)

# Costanti
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Ora costruisci i percorsi assoluti partendo da BASE_DIR
BASE_INPUT_DIR = os.path.normpath(os.path.join(BASE_DIR, "..", "Istat", "Regioni"))
OUTPUT_DIR = os.path.normpath(os.path.join(BASE_DIR, "..", "Data_Collection", "csv_tables-fase1"))

CAMPI_ESTRATTI = ['COD_REG', 'COD_ISTAT', 'PRO_COM', 'SEZ2011', 'SEZ', 'COD_LOC', 'TIPO_LOC']

def trova_file_in_regione(regione: str, extension: str) -> str:
    """
    Cerca e restituisce il percorso assoluto del primo file con la specifica estensione all'interno della cartella della regione.

    Parametri
    ----------
    regione : str
        Nome della regione (verrà normalizzato tramite safe_name).
    extension : str
        Estensione del file da cercare (ad es. ".dbf" o ".shp").

    Restituisce
    ----------
    str
        Percorso assoluto del file trovato.

    Solleva
    -------
    FileNotFoundError
        Se nessun file con l'estensione specificata viene trovato nella cartella della regione.
    """
    cartella = os.path.join(BASE_INPUT_DIR, safe_name(regione))
    files = [f for f in os.listdir(cartella) if f.lower().endswith(extension)]
    if not files:
        raise FileNotFoundError(f"Nessun file {extension} trovato nella cartella: {cartella}")
    if len(files) > 1:
        logger.warning(f"Trovati più file {extension} in {cartella}, verrà usato il primo: {files[0]}")
    return os.path.join(cartella, files[0])

def trova_dbf_in_regione(regione: str) -> str:
    """
    Restituisce il percorso assoluto del file .dbf relativo alla regione specificata.

    Parametri
    ----------
    regione : str
        Nome della regione.

    Restituisce
    ----------
    str
        Percorso assoluto del file .dbf trovato.
    """
    return trova_file_in_regione(regione, ".dbf")

def estrai_dati_basi_territoriali(percorso_file: str) -> pd.DataFrame:
    """
    Estrae i campi di interesse da un file DBF e li restituisce come DataFrame pandas.

    Parametri
    ----------
    percorso_file : str
        Percorso assoluto al file DBF da leggere.

    Restituisce
    ----------
    pd.DataFrame
        DataFrame contenente i campi estratti dal file DBF.
    """
    table = DBF(percorso_file, load=True, ignorecase=True, recfactory=dict)
    records = [{campo: rec.get(campo) for campo in CAMPI_ESTRATTI} for rec in table]
    df = pd.DataFrame(records)
    for col in df.columns:
        try:
            df[col] = df[col].astype('int64')
        except (ValueError, TypeError):
            logger.warning(f"Colonna non convertita a intero: {col}")
    return df

def salva_dati_basi_territoriali(df: pd.DataFrame, cartella_output: str, nome_file: str,
                                 sep: str = ';', encoding: str = 'utf-8-sig') -> None:
    """
    Salva un DataFrame pandas come file CSV nella cartella di output specificata.

    Se esiste già un file con lo stesso nome, viene sovrascritto.

    Parametri
    ----------
    df : pd.DataFrame
        DataFrame da salvare.
    cartella_output : str
        Cartella di destinazione del file CSV.
    nome_file : str
        Nome del file CSV.
    sep : str, opzionale
        Separatore di campo del CSV (default: ';').
    encoding : str, opzionale
        Codifica del file CSV (default: 'utf-8-sig').
    """
    os.makedirs(cartella_output, exist_ok=True)
    output_path = os.path.join(cartella_output, nome_file)
    if os.path.exists(output_path):
        os.remove(output_path)
        logger.info(f"File esistente rimosso: {output_path}")
    df.to_csv(output_path, index=False, sep=sep, encoding=encoding)
    logger.info(f"Dati salvati in: {output_path}")

def run_estrazione_basi_territoriali(regione: str) -> pd.DataFrame:
    """
    Esegue il flusso completo di estrazione, trasformazione e salvataggio dei dati delle basi territoriali per una regione.

    Parametri
    ----------
    regione : str
        Nome della regione.

    Restituisce
    ----------
    pd.DataFrame
        DataFrame contenente i dati estratti e salvati.
    """
    regione_safe = safe_name(regione)
    input_path = trova_dbf_in_regione(regione_safe)
    nome_file = f"basi_territoriali_{regione_safe}.csv"
    df = estrai_dati_basi_territoriali(input_path)
    salva_dati_basi_territoriali(df, OUTPUT_DIR, nome_file)
    return df

def get_dati_basi_territoriali(regione: str) -> pd.DataFrame:
    """
    Carica il DataFrame delle basi territoriali di una regione dal CSV; se il file non esiste, avvia l'estrazione e il salvataggio.

    Parametri
    ----------
    regione : str
        Nome della regione.

    Restituisce
    ----------
    pd.DataFrame
        DataFrame contenente i dati delle basi territoriali.
    """
    regione_safe = safe_name(regione)
    nome_file = f"basi_territoriali_{regione_safe}.csv"
    path_csv = os.path.join(OUTPUT_DIR, nome_file)
    if not os.path.exists(path_csv):
        logger.warning(f"File CSV non trovato per {regione}, avvio estrazione.")
        return run_estrazione_basi_territoriali(regione_safe)
    df = pd.read_csv(path_csv, sep=';', encoding='utf-8-sig')
    logger.info(f"Dati caricati da: {path_csv}")
    return df

def get_geom_basi_territoriali(regione: str) -> gpd.GeoDataFrame:
    """
    Carica e restituisce il GeoDataFrame contenente le geometrie delle sezioni censuarie di una regione dal relativo shapefile.

    Filtra solo le colonne 'SEZ2011' e 'geometry'.

    Parametri
    ----------
    regione : str
        Nome della regione.

    Restituisce
    ----------
    gpd.GeoDataFrame
        GeoDataFrame contenente le geometrie e il campo SEZ2011.
    """
    regione_safe = safe_name(regione)
    percorso_shp = trova_shp_in_regione(regione_safe)
    gdf = gpd.read_file(percorso_shp)
    logger.info(f"Shapefile caricato da: {percorso_shp}")
    # Filtra solo le colonne 'SEZ2011' e 'geometry'
    colonne_necessarie = ['SEZ2011', 'geometry']
    gdf = gdf[[col for col in colonne_necessarie if col in gdf.columns]]
    return gdf

def trova_shp_in_regione(regione: str) -> str:
    """
    Restituisce il percorso assoluto del file .shp relativo alla regione specificata.

    Parametri
    ----------
    regione : str
        Nome della regione.

    Restituisce
    ----------
    str
        Percorso assoluto del file .shp trovato.
    """
    return trova_file_in_regione(regione, ".shp")
