import os
import logging

import pandas as pd
from rapidfuzz import process, fuzz

from utils import safe_name

# =============================================================================
# COSTANTI
# =============================================================================

THRESHOLD = 50

PROV_DICT = {
    "BI": "BIELLA", "TO": "TORINO", "VC": "VERCELLI", "NO": "NOVARA", "CN": "CUNEO", "AT": "ASTI", "AL": "ALESSANDRIA",
    "AO": "AOSTA", "VA": "VARESE", "CO": "COMO", "SO": "SONDRIO", "MI": "MILANO", "BG": "BERGAMO", "BS": "BRESCIA",
    "PV": "PAVIA", "CR": "CREMONA", "MN": "MANTOVA", "BZ": "BOLZANO", "TN": "TRENTO", "VR": "VERONA", "VI": "VICENZA",
    "BL": "BELLUNO", "TV": "TREVISO", "VE": "VENEZIA", "PD": "PADOVA", "RO": "ROVIGO", "UD": "UDINE", "GO": "GORIZIA",
    "TS": "TRIESTE", "PN": "PORDENONE", "IM": "IMPERIA", "SV": "SAVONA", "GE": "GENOVA", "SP": "LA SPEZIA",
    "PC": "PIACENZA", "PR": "PARMA", "RE": "REGGIO EMILIA", "MO": "MODENA", "BO": "BOLOGNA", "FE": "FERRARA",
    "RA": "RAVENNA", "FO": "FORLÌ-CESENA", "MS": "MASSA-CARRARA", "LU": "LUCCA", "PT": "PISTOIA", "FI": "FIRENZE",
    "LI": "LIVORNO", "PI": "PISA", "AR": "AREZZO", "SI": "SIENA", "GR": "GROSSETO", "PG": "PERUGIA", "TR": "TERNI",
    "PS": "PESARO E URBINO", "AN": "ANCONA", "MC": "MACERATA", "AP": "ASCOLI PICENO", "VT": "VITERBO",
    "RI": "RIETI", "RM": "ROMA", "LT": "LATINA", "FR": "FROSINONE", "AQ": "L'AQUILA", "CS": "COSENZA",
    "CZ": "CATANZARO", "RC": "REGGIO CALABRIA", "TP": "TRAPANI", "PA": "PALERMO", "TE": "TERAMO", "PE": "PESCARA",
    "CH": "CHIETI", "CB": "CAMPOBASSO", "IS": "ISERNIA", "CE": "CASERTA", "BN": "BENEVENTO", "NA": "NAPOLI",
    "AV": "AVELLINO", "SA": "SALERNO", "FG": "FOGGIA", "BA": "BARI", "TA": "TARANTO", "BR": "BRINDISI",
    "LE": "LECCE", "PZ": "POTENZA", "MT": "MATERA", "MR": "MATERA", "ME": "MESSINA", "AG": "AGRIGENTO",
    "CL": "CALTANISSETTA", "EN": "ENNA", "CT": "CATANIA", "RG": "RAGUSA", "SR": "SIRACUSA", "SS": "SASSARI",
    "NU": "NUORO", "CA": "CAGLIARI", "OR": "ORISTANO"
}

# Directory per output CSV per regione
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, '..', 'Data_Collection', 'csv_tables-fase1')
OUTPUT_DIR = os.path.abspath(OUTPUT_DIR)

# =============================================================================
# SETUP LOGGING
# =============================================================================

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

# =============================================================================
# ESTRAZIONE DATI
# =============================================================================
from .normattiva import get_dati_normattiva, run_estrazione_normattiva
from .estrazione_dati_basi_territoriali import get_dati_basi_territoriali, run_estrazione_basi_territoriali
from .estrazione_dati_variabili_censuarie import get_dati_variabili_censuarie, run_estrazione_variabili_censuarie



# =============================================================================
# ELABORAZIONE DATI
# =============================================================================

def estrai_join_data(
    regione_input: str,
    get_basi_territoriali=get_dati_basi_territoriali,
    get_variabili_censuarie=get_dati_variabili_censuarie,
    get_normattiva=get_dati_normattiva
) -> pd.DataFrame:
    """
    Esegue estrazione, merge e fuzzy-matching dei dati per la regione specificata.
    """
    # 1) Estrazione dati
    df_base = get_basi_territoriali(regione_input)
    df_cens = get_variabili_censuarie(regione_input)
    df_norm = get_normattiva()

    logger.info("Dati base estratti: %d righe", len(df_base))
    logger.info("Dati censuari estratti: %d righe", len(df_cens))
    logger.info("Dati normattivi estratti: %d righe", len(df_norm))

    # 2) Merge base + censuarie
    df_merged = pd.merge(df_base, df_cens, on='SEZ2011', how='inner')
    df_merged['COMUNE'] = df_merged['COMUNE'].str.upper()
    df_norm['COMUNE'] = df_norm['COMUNE'].str.upper()

    # 3) Mappa sigla provincia → nome
    df_norm['PROVINCIA'] = df_norm['PROVINCIA'].map(PROV_DICT)
    logger.info(
        "Province mappate in df_norm: %d di %d",
        df_norm['PROVINCIA'].notna().sum(), len(df_norm)
    )

    # 4) Join diretto
    df_join = pd.merge(
        df_merged,
        df_norm,
        on=['PROVINCIA', 'COMUNE'],
        how='left',
        indicator=True
    )
    direct_matched = df_join['_merge'] == 'both'
    logger.info(
        "Comuni con corrispondenza diretta: %d/%d",
        direct_matched.sum(), len(df_merged)
    )

    # 5) Identifico non matchati
    df_unmatched = df_join.loc[~direct_matched, df_merged.columns]
    logger.info("Numero comuni da fuzzy match: %d", len(df_unmatched))

    # 6) Preparo df_final con matched diretti
    df_final = df_join.loc[direct_matched].drop(columns=['_merge'])

    # 7) Fuzzy match limitato alla provincia
    for idx, row in df_unmatched.iterrows():
        prov = row['PROVINCIA']
        target = row['COMUNE']
        candidates = df_norm.loc[df_norm['PROVINCIA'] == prov, 'COMUNE'].unique()
        if candidates.size == 0:
            logger.warning(
                "Nessun candidato fuzzy per provincia %s (riga %s)", prov, idx
            )
            continue

        best, score, _ = process.extractOne(
            target, candidates, scorer=fuzz.token_sort_ratio
        )

        if score >= THRESHOLD:
            norm_row = df_norm[
                (df_norm['PROVINCIA'] == prov) & (df_norm['COMUNE'] == best)
            ].iloc[0]
            merged_row = pd.concat([row, norm_row.drop(['PROVINCIA', 'COMUNE'])])
            df_final = pd.concat([df_final, merged_row.to_frame().T], ignore_index=True)
            logger.info("Fuzzy match: '%s' → '%s' (score %d)", target, best, score)
        else:
            logger.warning(
                "Fuzzy LOW score per '%s' in %s: '%s' (%d)",
                target, prov, best, score
            )

    logger.info("Comuni fuzzy matchati: %d/%d", len(df_final), len(df_merged))
    return df_final


def salva_join_data(df: pd.DataFrame, regione_input: str, output_dir: str = OUTPUT_DIR) -> str:
    os.makedirs(output_dir, exist_ok=True)
    safe_region = safe_name(regione_input)
    filename = f"join_data_{safe_region}.csv"
    path = os.path.join(output_dir, filename)
    path = os.path.abspath(path)
    df.to_csv(path, index=False, sep=';', encoding='utf-8-sig')
    logger.info("Salvato CSV fase1 per %s in %s", regione_input, path)
    return path


def get_join_data(regione_input: str) -> pd.DataFrame:
    safe_region = safe_name(regione_input)
    filename = f"join_data_{safe_region}.csv"
    path = os.path.join(OUTPUT_DIR, filename)
    path = os.path.abspath(path)
    if os.path.isfile(path):
        logger.info("File esistente trovato per %s: %s", regione_input, path)
        return pd.read_csv(path, sep=';', encoding='utf-8-sig')
    else:
        logger.info("File non trovato per %s: creo e salvo", regione_input)
        df = estrai_join_data(regione_input)
        salva_join_data(df, regione_input, output_dir=OUTPUT_DIR)
        return df


def refresh_join_data(
        regione_input: str,
        get_basi_territoriali=run_estrazione_basi_territoriali,
        get_variabili_censuarie=run_estrazione_variabili_censuarie,
        get_normattiva=run_estrazione_normattiva
) -> pd.DataFrame:
    logger.info("Ricalcolo join data per %s...", regione_input)
    df = estrai_join_data(
        regione_input,
        get_basi_territoriali=get_basi_territoriali,
        get_variabili_censuarie=get_variabili_censuarie,
        get_normattiva=get_normattiva
    )
    salva_join_data(df, regione_input, output_dir=OUTPUT_DIR)
    return df


if __name__ == "__main__":
    regione = "campania"
    df_joined = get_join_data(regione)

