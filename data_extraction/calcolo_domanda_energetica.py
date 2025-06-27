import os
import shutil

import pandas as pd
import geopandas as gpd
import logging

from .join_data_normattiva_varcens_basiterr import get_join_data
from data_extraction_siape.siape_zc_range import get_dati_siape
from .calcola_area_poligoni import calcola_area
from .interrogazione_wfs_catastale import get_dati_catasto
from utils import safe_name, get_regione_from_provincia, configure_logging_if_main

logger = logging.getLogger(__name__)

# === BASE DIR PER I PERCORSI RELATIVI AL PROGETTO ===
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.normpath(os.path.join(BASE_DIR, ".."))  # /data_extraction → progetto

# =============================================================================
# FUNZIONI DI CALCOLO
# =============================================================================

def calcola_coefficiente_domanda(df_join: pd.DataFrame, df_siape: pd.DataFrame, comune: str, provincia: str) -> float:
    logger.info(f"Calcolo coefficiente domanda per {comune} ({provincia})...")

    df_comune = df_join[
        (df_join['COMUNE'].str.upper() == comune.upper()) &
        (df_join['PROVINCIA'].str.upper() == provincia.upper())
        ]

    if df_comune.empty:
        raise ValueError(f"Nessun dato trovato per il comune {comune} nella provincia {provincia}.")

    def somma_colonne(*colonne):
        return sum(
            df_comune[col].fillna(0).astype(int).sum() for col in colonne
        )

    b1 = somma_colonne('E8', 'E9')
    b2 = somma_colonne('E10', 'E11')
    b3 = somma_colonne('E12', 'E13')
    b4 = somma_colonne('E14', 'E15')
    b5 = somma_colonne('E16')

    totale_edifici = b1 + b2 + b3 + b4 + b5
    if totale_edifici == 0:
        raise ValueError(f"Totale edifici nullo per il comune {comune}.")

    zc = df_comune['ZONA_CLIMATICA'].dropna().unique()
    if len(zc) != 1:
        raise ValueError(f"Zona climatica ambigua o mancante per {comune}. Valori trovati: {zc}")
    zc = zc[0]

    df_zc = df_siape[df_siape['zona_climatica'] == zc]
    if df_zc.empty:
        raise ValueError(f"Nessun dato SIAPE per la zona climatica {zc}")

    def get_coeff(df, periodo):
        val = df[df['periodo'] == periodo]['EPgl_nren']
        if val.empty or pd.isna(val.iloc[0]):
            raise ValueError(f"Valore EPgl_nren mancante per periodo {periodo} in zona {zc}")
        return float(val.iloc[0])

    epgl_nren_1 = get_coeff(df_zc, 'kE8E9')
    epgl_nren_2 = get_coeff(df_zc, 'kE10E11')
    epgl_nren_3 = get_coeff(df_zc, 'kE12E13')
    epgl_nren_4 = get_coeff(df_zc, 'kE14E15')
    epgl_nren_5 = get_coeff(df_zc, 'kE16')

    coefficiente_domanda = (
            (b1 * epgl_nren_1 + b2 * epgl_nren_2 + b3 * epgl_nren_3 +
             b4 * epgl_nren_4 + b5 * epgl_nren_5) / totale_edifici
    )

    return round(coefficiente_domanda, 2)


def calcola_domanda_energetica(comune: str, provincia: str) -> gpd.GeoDataFrame:
    logger.info("Inizio calcolo domanda energetica...")

    prov_safe = safe_name(provincia)
    comm_safe = safe_name(comune)
    regione = get_regione_from_provincia(prov_safe)

    # Carico dati unificati
    df_join = get_join_data(regione)
    logger.info("Dati unificati caricati.")

    # Carico dati SIAPE
    df_siape = get_dati_siape()
    logger.info("Dati SIAPE caricati.")

    # Path shapefile fabbricati
    shp_dir = os.path.normpath(os.path.join(PROJECT_ROOT, "FABBRICATI", f"fabbricati_{prov_safe}_{comm_safe}"))
    if not os.path.isdir(shp_dir):
        raise FileNotFoundError(f"Directory shapefile non trovata: {shp_dir}")

    shp_files = [f for f in os.listdir(shp_dir) if f.lower().endswith('.shp')]
    if len(shp_files) != 1:
        raise ValueError(f"Atteso un unico file .shp in {shp_dir}, trovati: {shp_files}")
    shp_path = os.path.join(shp_dir, shp_files[0])

    try:
        gdf_fabbricati = gpd.read_file(shp_path)
        logger.info(f"Shapefile fabbricati caricato da {shp_path}.")
    except Exception as e:
        logger.warning(f"Errore caricamento shapefile fabbricati: {e}")
        gdf_fabbricati = None

    # Calcolo area edifici
    gdf_fabbricati = calcola_area(gdf_fabbricati, nome_colonna='area_mq')

    # Calcolo coefficiente domanda
    coeff_dom = calcola_coefficiente_domanda(df_join, df_siape, comune, provincia)
    logger.info(f"Coefficiente domanda per {comune} ({provincia}): {coeff_dom} kWh/mq/anno")

    # Path output shapefile
    subdir = f"{prov_safe}_{comm_safe}"
    dirname = f"domanda_energetica_{prov_safe}_{comm_safe}"
    out_dir = os.path.normpath(os.path.join(PROJECT_ROOT, "Data_Collection", "shapefiles", subdir, dirname))
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir)
    out_shp = os.path.join(out_dir, f"{dirname}.shp")

    if gdf_fabbricati is not None:
        # Aggiungo colonna domanda energetica
        gdf_fabbricati['domanda_en'] = gdf_fabbricati['area_mq'] * coeff_dom
        logger.info("Colonna domanda energetica aggiunta.")

        # Aggiungo dati catastali
        gdf_fabbricati = get_dati_catasto(gdf_fabbricati, provincia, comune)

        # Salvo shapefile di output
        gdf_fabbricati.to_file(out_shp, driver='ESRI Shapefile')
        logger.info(f"Shapefile con domanda energetica salvato in {out_shp}")

    return gdf_fabbricati


if __name__ == '__main__':
    configure_logging_if_main(__name__)
    gdf = calcola_domanda_energetica('PADULA', 'SALERNO')
