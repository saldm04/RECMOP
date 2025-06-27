import os
import logging
import pandas as pd
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
    Trova un file con l'estensione specificata all'interno della cartella della regione.
    """
    cartella = os.path.join(BASE_INPUT_DIR, safe_name(regione))
    files = [f for f in os.listdir(cartella) if f.lower().endswith(extension)]
    if not files:
        raise FileNotFoundError(f"Nessun file {extension} trovato nella cartella: {cartella}")
    if len(files) > 1:
        logger.warning(f"Trovati più file {extension} in {cartella}, verrà usato il primo: {files[0]}")
    return os.path.join(cartella, files[0])


def trova_dbf_in_regione(regione: str) -> str:
    return trova_file_in_regione(regione, ".dbf")


def estrai_dati_basi_territoriali(percorso_file: str) -> pd.DataFrame:
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
    os.makedirs(cartella_output, exist_ok=True)
    output_path = os.path.join(cartella_output, nome_file)
    if os.path.exists(output_path):
        os.remove(output_path)
        logger.info(f"File esistente rimosso: {output_path}")
    df.to_csv(output_path, index=False, sep=sep, encoding=encoding)
    logger.info(f"Dati salvati in: {output_path}")


def run_estrazione_basi_territoriali(regione: str) -> pd.DataFrame:
    regione_safe = safe_name(regione)
    input_path = trova_dbf_in_regione(regione_safe)
    nome_file = f"basi_territoriali_{regione_safe}.csv"
    df = estrai_dati_basi_territoriali(input_path)
    salva_dati_basi_territoriali(df, OUTPUT_DIR, nome_file)
    return df


def get_dati_basi_territoriali(regione: str) -> pd.DataFrame:
    regione_safe = safe_name(regione)
    nome_file = f"basi_territoriali_{regione_safe}.csv"
    path_csv = os.path.join(OUTPUT_DIR, nome_file)
    if not os.path.exists(path_csv):
        logger.warning(f"File CSV non trovato per {regione}, avvio estrazione.")
        return run_estrazione_basi_territoriali(regione_safe)
    df = pd.read_csv(path_csv, sep=';', encoding='utf-8-sig')
    logger.info(f"Dati caricati da: {path_csv}")
    return df


def trova_shp_in_regione(regione: str) -> str:
    return trova_file_in_regione(regione, ".shp")


if __name__ == '__main__':
    # Abilita logging solo se eseguito standalone
    configure_logging_if_main(__name__)
    # Esempio di utilizzo
    df = get_dati_basi_territoriali("campania")
