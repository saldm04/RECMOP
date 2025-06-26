import os
import logging
import pandas as pd

from utils import safe_name

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Costanti
BASE_INPUT_DIR = os.path.join("..", "Istat", "Variabili_Censuarie", "Sezioni_di_Censimento")
OUTPUT_DIR = "../Data_Collection/csv_tables-fase1"
COLONNE_RICHIESTE = [
    'SEZ2011', 'COMUNE', 'PROVINCIA', 'P1', 'E8', 'E9',
    'E10', 'E11', 'E12', 'E13', 'E14', 'E15', 'E16', 'A44'
]


def estrai_dati_variabili_censuarie(percorso_file: str, sep: str = ';', encoding: str = 'latin-1') -> pd.DataFrame:
    """
    Estrae le colonne censuarie da un file CSV Istat.
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
    Salva un DataFrame in formato CSV.
    """
    os.makedirs(cartella_output, exist_ok=True)
    output_path = os.path.join(cartella_output, nome_file)
    df.to_csv(output_path, index=False, sep=sep, encoding=encoding)
    logger.info(f"Dati estratti e salvati in: {output_path}")


def run_estrazione_variabili_censuarie(regione: str) -> pd.DataFrame:
    """
    Estrae e salva i dati censuari per una data regione.

    Args:
        regione: Nome della regione (es. "campania").

    Returns:
        DataFrame estratto.
    """
    regione_safe = safe_name(regione)
    input_path = os.path.join(BASE_INPUT_DIR, f"{regione_safe}.csv")
    output_filename = f"variabili_censuarie_{regione_safe}.csv"

    df_estratto = estrai_dati_variabili_censuarie(input_path)
    salva_dati_variabili_censuarie(df_estratto, cartella_output=OUTPUT_DIR, nome_file=output_filename)
    return df_estratto


def get_dati_variabili_censuarie(regione: str) -> pd.DataFrame:
    """
    Restituisce il DataFrame dei dati censuari per la regione,
    creandolo se non ancora presente.

    Args:
        regione: Nome della regione (es. "campania").

    Returns:
        DataFrame con i dati censuari.
    """
    regione_safe = safe_name(regione)
    output_filename = f"variabili_censuarie_{regione_safe}.csv"
    path_csv = os.path.join(OUTPUT_DIR, output_filename)

    if not os.path.exists(path_csv):
        logger.warning(f"File non trovato. Estrazione in corso: {path_csv}")
        return run_estrazione_variabili_censuarie(regione)

    df = pd.read_csv(path_csv, sep=';', encoding='utf-8-sig')
    logger.info(f"Dati caricati da: {path_csv}")
    return df


if __name__ == "__main__":
    # Esempio d’uso
    get_dati_variabili_censuarie("campania")
