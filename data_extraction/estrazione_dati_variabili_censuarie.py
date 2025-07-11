import os
import logging
import pandas as pd

from utils import safe_name, configure_logging_if_main

logger = logging.getLogger(__name__)

# Base directory (cartella di questo file)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Costanti con path assoluti
BASE_INPUT_DIR = os.path.normpath(os.path.join(BASE_DIR, "..", "Istat", "Variabili_Censuarie", "Sezioni_di_Censimento"))
OUTPUT_DIR = os.path.normpath(os.path.join(BASE_DIR, "..", "Data_Collection", "csv_tables-fase1"))

COLONNE_RICHIESTE = [
    'SEZ2011', 'COMUNE', 'PROVINCIA', 'P1', 'E8', 'E9',
    'E10', 'E11', 'E12', 'E13', 'E14', 'E15', 'E16', 'A44'
]


def estrai_dati_variabili_censuarie(percorso_file: str, sep: str = ';', encoding: str = 'latin-1') -> pd.DataFrame:
    """
    Estrae le colonne di interesse dai file CSV delle variabili censuarie Istat.

    Parametri
    ----------
    percorso_file : str
        Percorso al file CSV Istat da cui estrarre i dati.
    sep : str, opzionale
        Separatore di campo del CSV (default: ';').
    encoding : str, opzionale
        Codifica del file CSV (default: 'latin-1').

    Restituisce
    ----------
    pd.DataFrame
        DataFrame contenente solo le colonne richieste (quelle effettivamente presenti).
    """
    df = pd.read_csv(percorso_file, sep=sep, encoding=encoding, dtype=str)
    df.columns = df.columns.str.strip()

    colonne_presenti = [col for col in COLONNE_RICHIESTE if col in df.columns]
    colonne_mancanti = [col for col in COLONNE_RICHIESTE if col not in df.columns]

    if colonne_mancanti:
        logger.warning(f"Colonne mancanti nel CSV: {colonne_mancanti}")

    df_result = df[colonne_presenti].copy()

    if 'SEZ2011' in df_result.columns:
        df_result['SEZ2011'] = df_result['SEZ2011'].astype('int64')
    if 'COMUNE' in df_result.columns:
        df_result['COMUNE'] = df_result['COMUNE'].str.upper()
    if 'PROVINCIA' in df_result.columns:
        df_result['PROVINCIA'] = df_result['PROVINCIA'].str.upper()

    return df_result


def salva_dati_variabili_censuarie(df: pd.DataFrame, cartella_output: str, nome_file: str,
                                    sep: str = ';', encoding: str = 'utf-8-sig') -> None:
    """
    Salva un DataFrame in formato CSV nella cartella specificata.

    Se il file esiste già, viene sovrascritto.

    Parametri
    ----------
    df : pd.DataFrame
        Il DataFrame da salvare.
    cartella_output : str
        Directory di destinazione.
    nome_file : str
        Nome del file CSV di output.
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
    logger.info(f"Dati estratti e salvati in: {output_path}")


def run_estrazione_variabili_censuarie(regione: str) -> pd.DataFrame:
    """
    Estrae le variabili censuarie per una regione da file CSV, le salva su disco e restituisce il DataFrame.

    Parametri
    ----------
    regione : str
        Nome della regione (es. "campania").

    Restituisce
    ----------
    pd.DataFrame
        DataFrame con i dati censuari estratti e salvati.
    """
    regione_safe = safe_name(regione)
    input_path = os.path.join(BASE_INPUT_DIR, f"{regione_safe}.csv")
    output_filename = f"variabili_censuarie_{regione_safe}.csv"

    df_estratto = estrai_dati_variabili_censuarie(input_path)
    salva_dati_variabili_censuarie(df_estratto, cartella_output=OUTPUT_DIR, nome_file=output_filename)
    return df_estratto


def get_dati_variabili_censuarie(regione: str) -> pd.DataFrame:
    """
    Carica il DataFrame delle variabili censuarie per una regione da file CSV; se il file non esiste, avvia l’estrazione.

    Parametri
    ----------
    regione : str
        Nome della regione (es. "campania").

    Restituisce
    ----------
    pd.DataFrame
        DataFrame contenente i dati censuari della regione.
    """
    regione_safe = safe_name(regione)
    output_filename = f"variabili_censuarie_{regione_safe}.csv"
    path_csv = os.path.join(OUTPUT_DIR, output_filename)

    if not os.path.exists(path_csv):
        logger.warning(f"File non trovato. Estrazione in corso: {path_csv}")
        return run_estrazione_variabili_censuarie(regione_safe)

    df = pd.read_csv(path_csv, sep=';', encoding='utf-8-sig')
    logger.info(f"Dati caricati da: {path_csv}")
    return df