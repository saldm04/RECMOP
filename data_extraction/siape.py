import os
import logging
import pandas as pd
import requests

from utils import configure_logging_if_main

# Impostazione logging
logger = logging.getLogger(__name__)

# Costanti
URL_SIAPE = "https://siape.enea.it/api/v1/aggr-data"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.normpath(os.path.join(BASE_DIR, "..", "Data_Collection", "csv_tables-fase1"))
OUTPUT_FILENAMES = {
    "zc_range": "epgl_nren_ren_co2_tabella_siape_zc_range.csv",
    "zc_suris_volris": "epgl_nren_ren_co2_tabella_siape_zc_suris_volris.csv",
    "zc_suris_volris_supdi": "epgl_nren_ren_co2_tabella_siape_zc_suris_volris_supdi.csv",
}

ZONES = ['A', 'B', 'C', 'D', 'E', 'F']
PERIODS = [
    (-1000000000, 1944),
    (1944, 1972),
    (1972, 1991),
    (1991, 2005),
    (2005, 2015),
    (2015, 1000000000),
]
PERIOD_LABELS = {
    0: 'kE8E9',
    1: 'kE10E11',
    2: 'kE12E13',
    3: 'kE14E15',
    4: 'kE16',
    5: 'k2015',
}

SURIS_RANGES = [
    (-1000000000, 50), (50, 100), (100, 200),
    (200, 500), (500, 1000), (1000, 5000), (5000, 1000000000)
]
VOLRIS_RANGES = [
    (-1000000000, 50), (50, 100), (100, 200),
    (200, 500), (500, 1000), (1000, 5000),
    (5000, 10000), (10000, 1000000000)
]
SUPDI_RANGES = [
    (-1000000000, 50), (50, 100), (100, 200),
    (200, 500), (500, 1000), (1000, 5000), (5000, 1000000000)
]

HEADERS = {
    'Accept': 'application/json, text/javascript, */*; q=0.01',
    'Accept-Encoding': 'gzip, deflate, br, zstd',
    'Accept-Language': 'it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7',
    'Cache-Control': 'no-store, no-cache, must-revalidate',
    'Connection': 'keep-alive',
    'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
    'Origin': 'https://siape.enea.it',
    'Referer': 'https://siape.enea.it/caratteristiche-immobili',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-origin',
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/136.0.0.0 Safari/537.36'
    ),
    'X-Requested-With': 'XMLHttpRequest',
}

# =========================
#  FUNZIONI DI ESTRAZIONE
# =========================

def format_range(min_val: int, max_val: int) -> str:
    """
    Restituisce una stringa leggibile per rappresentare un intervallo (range) numerico.

    Parametri
    ----------
    min_val : int
        Valore minimo dell'intervallo.
    max_val : int
        Valore massimo dell'intervallo.

    Restituisce
    ----------
    str
        Rappresentazione testuale dell'intervallo (es: '<50', '50-100', '>5000').
    """
    if min_val == -1000000000:
        return f"<{max_val}"
    elif max_val == 1000000000:
        return f">{min_val}"
    else:
        return f"{min_val}-{max_val}"

def estrai_dati_siape_zc_range() -> pd.DataFrame:
    """
    Estrae i dati aggregati SIAPE per zona climatica e periodo edilizio,
    effettuando una chiamata POST per ogni combinazione.

    Restituisce
    ----------
    pd.DataFrame
        DataFrame con colonne: 'zona_climatica', 'periodo', 'EPgl_nren', 'EPgl_ren', 'CO2'.
    """
    records = []

    for zona in ZONES:
        for idx, (inizio, fine) in enumerate(PERIODS):
            periodo_label = PERIOD_LABELS.get(idx, f"{inizio}-{fine}")

            payload = {
                'group[]': 'claen',
                'where[destuso]': '0',
                'where[annoc][range][]': [str(inizio), str(fine)],
                'where[zoncli][]': zona,
                'nofilter': 'false',
            }

            try:
                response = requests.post(URL_SIAPE, headers=HEADERS, data=payload)
                response.raise_for_status()
                json_data = response.json()
                total = json_data.get('total', [])

                record = {
                    'zona_climatica': zona,
                    'periodo': periodo_label,
                    'EPgl_nren': total[1] if len(total) > 1 else None,
                    'EPgl_ren': total[2] if len(total) > 2 else None,
                    'CO2': total[3] if len(total) > 3 else None,
                }
                records.append(record)

                logger.info(
                    f"[OK] Zona {zona}, periodo {periodo_label}: "
                    f"EPgl_nren={record['EPgl_nren']}, "
                    f"EPgl_ren={record['EPgl_ren']}, "
                    f"CO2={record['CO2']}"
                )

            except Exception as e:
                logger.warning(f"[ERRORE] Zona {zona}, periodo {periodo_label}: {e}")

    df = pd.DataFrame(records)
    return df

def estrai_dati_siape_zc_suris_volris() -> pd.DataFrame:
    """
    Estrae i dati SIAPE raggruppati per zona climatica, superficie riscaldata (SURIS) e volume riscaldato (VOLRIS).

    Restituisce
    ----------
    pd.DataFrame
        DataFrame con colonne: 'zona_climatica', 'suris_range', 'volris_range', 'EPgl_nren', 'EPgl_ren', 'CO2'.
    """
    records = []
    for zona in ZONES:
        for suris_min, suris_max in SURIS_RANGES:
            for volris_min, volris_max in VOLRIS_RANGES:

                suris_label = format_range(suris_min, suris_max)
                volris_label = format_range(volris_min, volris_max)

                payload = {
                    'group[]': 'claen',
                    'where[destuso]': '0',
                    'where[zoncli][]': zona,
                    'where[suris][range][]': [str(suris_min), str(suris_max)],
                    'where[volris][range][]': [str(volris_min), str(volris_max)],
                    'nofilter': 'false',
                }

                try:
                    response = requests.post(URL_SIAPE, headers=HEADERS, data=payload)
                    response.raise_for_status()
                    json_data = response.json()
                    total = json_data.get('total', [])

                    record = {
                        'zona_climatica': zona,
                        'suris_range': suris_label,
                        'volris_range': volris_label,
                        'EPgl_nren': total[1] if len(total) > 1 else None,
                        'EPgl_ren': total[2] if len(total) > 2 else None,
                        'CO2': total[3] if len(total) > 3 else None,
                    }
                    records.append(record)

                    logger.info(
                        f"[OK] Zona {zona}, SURIS {suris_label}, VOLRIS {volris_label}: "
                        f"EPgl_nren={record['EPgl_nren']}, "
                        f"EPgl_ren={record['EPgl_ren']}, "
                        f"CO2={record['CO2']}"
                    )

                except Exception as e:
                    logger.warning(
                        f"[ERRORE] Zona {zona}, SURIS {suris_label}, VOLRIS {volris_label}: {e}"
                    )
    df = pd.DataFrame(records)
    return df

def estrai_dati_siape_zc_suris_volris_supdi() -> pd.DataFrame:
    """
    Estrae i dati SIAPE raggruppati per zona climatica, superficie riscaldata (SURIS), volume riscaldato (VOLRIS) e superficie disperdente (SUPDI).

    Restituisce
    ----------
    pd.DataFrame
        DataFrame con colonne: 'zona_climatica', 'suris_range', 'volris_range', 'supdi_range', 'EPgl_nren', 'EPgl_ren', 'CO2'.
    """
    records = []
    for zona in ZONES:
        for suris_min, suris_max in SURIS_RANGES:
            for volris_min, volris_max in VOLRIS_RANGES:
                for supdi_min, supdi_max in SUPDI_RANGES:

                    suris_label = format_range(suris_min, suris_max)
                    volris_label = format_range(volris_min, volris_max)
                    supdi_label = format_range(supdi_min, supdi_max)

                    payload = {
                        'group[]': 'claen',
                        'where[destuso]': '0',
                        'where[zoncli][]': zona,
                        'where[suris][range][]': [str(suris_min), str(suris_max)],
                        'where[volris][range][]': [str(volris_min), str(volris_max)],
                        'where[supdi][range][]': [str(supdi_min), str(supdi_max)],
                        'nofilter': 'false',
                    }

                    try:
                        response = requests.post(URL_SIAPE, headers=HEADERS, data=payload)
                        response.raise_for_status()
                        json_data = response.json()
                        total = json_data.get('total', [])

                        record = {
                            'zona_climatica': zona,
                            'suris_range': suris_label,
                            'volris_range': volris_label,
                            'supdi_range': supdi_label,
                            'EPgl_nren': total[1] if len(total) > 1 else None,
                            'EPgl_ren': total[2] if len(total) > 2 else None,
                            'CO2': total[3] if len(total) > 3 else None,
                        }
                        records.append(record)

                        logger.info(
                            f"[OK] Zona {zona}, SURIS {suris_label}, VOLRIS {volris_label}, SUPDI {supdi_label}: "
                            f"EPgl_nren={record['EPgl_nren']}, "
                            f"EPgl_ren={record['EPgl_ren']}, "
                            f"CO2={record['CO2']}"
                        )

                    except Exception as e:
                        logger.warning(
                            f"[ERRORE] Zona {zona}, SURIS {suris_label}, VOLRIS {volris_label}, SUPDI {supdi_label}: {e}"
                        )
    df = pd.DataFrame(records)
    return df

# ========================
#   SALVATAGGIO UNICO
# ========================

def salva_dati_siape(df: pd.DataFrame, tipo: str, sep: str = ";") -> pd.DataFrame:
    """
    Salva il DataFrame SIAPE in formato CSV nella cartella di output, utilizzando il nome file appropriato per il tipo scelto.

    Parametri
    ----------
    df : pd.DataFrame
        DataFrame da salvare.
    tipo : str
        Tipo di aggregazione (ad esempio 'zc_range', 'zc_suris_volris', ecc.).
    sep : str, opzionale
        Separatore del CSV (default: ';').

    Restituisce
    ----------
    pd.DataFrame
        Il DataFrame fornito, per eventuale chaining.
    """
    filename = OUTPUT_FILENAMES[tipo]
    percorso_output = os.path.join(OUTPUT_DIR, filename)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    if os.path.exists(percorso_output):
        os.remove(percorso_output)
        logger.info(f"File esistente rimosso: {percorso_output}")
    df.to_csv(percorso_output, sep=sep, index=False, encoding='utf-8')
    logger.info(f"Dati salvati in: {percorso_output}")
    return df

# ========================
#   INVOCATORE UNICO
# ========================

def run_estrazione_siape(tipo: str) -> pd.DataFrame:
    """
    Esegue il flusso di estrazione e salvataggio dei dati SIAPE per il tipo specificato.

    Parametri
    ----------
    tipo : str
        Tipo di aggregazione desiderata ('zc_range', 'zc_suris_volris' o 'zc_suris_volris_supdi').

    Restituisce
    ----------
    pd.DataFrame
        DataFrame estratto e salvato.
    """
    estrattori = {
        "zc_range": estrai_dati_siape_zc_range,
        "zc_suris_volris": estrai_dati_siape_zc_suris_volris,
        "zc_suris_volris_supdi": estrai_dati_siape_zc_suris_volris_supdi,
    }
    if tipo not in estrattori:
        raise ValueError(f"Tipo '{tipo}' non supportato per estrazione SIAPE.")
    df = estrattori[tipo]()
    salva_dati_siape(df, tipo)
    logger.info(f"Esportazione completata ({tipo}): {len(df)} record scritti.")
    return df

def get_dati_siape(tipo: str) -> pd.DataFrame:
    """
    Carica i dati SIAPE dal file CSV corrispondente se esiste, altrimenti avvia l’estrazione per il tipo richiesto.

    Parametri
    ----------
    tipo : str
        Tipo di aggregazione desiderata ('zc_range', 'zc_suris_volris' o 'zc_suris_volris_supdi').

    Restituisce
    ----------
    pd.DataFrame
        DataFrame con i dati SIAPE.
    """
    filename = OUTPUT_FILENAMES[tipo]
    percorso_output = os.path.join(OUTPUT_DIR, filename)
    if os.path.exists(percorso_output):
        logger.info(f"Dati SIAPE già presenti: {percorso_output}")
        return pd.read_csv(percorso_output, sep=";", encoding="utf-8")
    logger.info("Dati SIAPE non trovati, avvio estrazione...")
    return run_estrazione_siape(tipo)
