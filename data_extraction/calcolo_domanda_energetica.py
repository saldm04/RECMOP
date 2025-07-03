import os
import shutil
import pandas as pd
import geopandas as gpd
import logging

from data_extraction.join_data_normattiva_varcens_basiterr import get_join_data
from data_extraction.siape import get_dati_siape
from data_extraction.calcola_area_poligoni import calcola_area
from data_extraction.interrogazione_wfs_catastale import get_dati_catasto
from utils import safe_name, get_regione_from_provincia, configure_logging_if_main

logger = logging.getLogger(__name__)

# === BASE DIR PER I PERCORSI RELATIVI AL PROGETTO ===
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.normpath(os.path.join(BASE_DIR, ".."))  # /data_extraction → progetto

# =============================================================================
# FUNZIONI DI CALCOLO
# =============================================================================

def calcola_coefficiente_domanda_zc_range(df_join: pd.DataFrame, df_siape: pd.DataFrame, comune: str, provincia: str) -> float:
    logger.info(f"Calcolo coefficiente domanda per {comune} ({provincia})...")

    # Applica la normalizzazione alle colonne
    df_join['_COMUNE_NORM'] = df_join['COMUNE'].astype(str).apply(safe_name)
    df_join['_PROVINCIA_NORM'] = df_join['PROVINCIA'].astype(str).apply(safe_name)

    # Filtro sui valori normalizzati
    df_comune = df_join[
        (df_join['_COMUNE_NORM'] == comune) &
        (df_join['_PROVINCIA_NORM'] == provincia)
        ]

    df_join.drop(columns=['_COMUNE_NORM', '_PROVINCIA_NORM'], inplace=True)

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

def calcola_domanda_energetica_zc_range(comune: str, provincia: str) -> gpd.GeoDataFrame:
    def coeff_wrapper(gdf, dfj, dfs, comune, provincia):
        coeff = calcola_coefficiente_domanda_zc_range(dfj, dfs, comune, provincia)
        gdf['coeff_dom'] = coeff
        return gdf
    return calcola_domanda_energetica(comune, provincia, "zc_range", coeff_wrapper)

def calcola_coefficiente_domanda_zc_suris_volris(
    gdf_fabbricati: gpd.GeoDataFrame,
    df_join: pd.DataFrame,
    df_siape: pd.DataFrame,
    comune: str,
    provincia: str
) -> gpd.GeoDataFrame:
    logger.info(f"Calcolo coefficiente domanda per {comune} ({provincia})...")

    # Normalizzazione
    df_join['_COMUNE_NORM'] = df_join['COMUNE'].astype(str).apply(safe_name)
    df_join['_PROVINCIA_NORM'] = df_join['PROVINCIA'].astype(str).apply(safe_name)

    # Filtro sui valori normalizzati
    df_comune = df_join[
        (df_join['_COMUNE_NORM'] == comune) &
        (df_join['_PROVINCIA_NORM'] == provincia)
    ]
    df_join.drop(columns=['_COMUNE_NORM', '_PROVINCIA_NORM'], inplace=True)

    if df_comune.empty:
        raise ValueError(f"Nessun dato trovato per il comune {comune} nella provincia {provincia}.")

    zc = df_comune['ZONA_CLIMATICA'].dropna().unique()
    if len(zc) != 1:
        raise ValueError(f"Zona climatica ambigua o mancante per {comune}. Valori trovati: {zc}")
    zc = zc[0]

    df_zc = df_siape[df_siape['zona_climatica'] == zc]
    if df_zc.empty:
        raise ValueError(f"Nessun dato SIAPE per la zona climatica {zc}")

    suris_ranges = list(df_zc['suris_range'].unique())
    volris_ranges = list(df_zc['volris_range'].unique())

    def trova_range(valore, ranges):
        for r in ranges:
            if r.startswith('<'):
                limite = float(r[1:])
                if valore < limite:
                    return r
            elif r.startswith('>'):
                limite = float(r[1:])
                if valore > limite:
                    return r
            elif '-' in r:
                min_, max_ = map(float, r.split('-'))
                if min_ <= valore < max_:
                    return r
        return None

    def trova_epgl_robusto(sur_range, vol_range):
        # Cerca con entrambi
        riga = df_zc[
            (df_zc['suris_range'] == sur_range) &
            (df_zc['volris_range'] == vol_range)
        ]
        if not riga.empty:
            coeff = riga.iloc[0]['EPgl_nren']
            if coeff != 0:
                return coeff
        # Primo fallback: media su zona_climatica + suris_range
        riga = df_zc[df_zc['suris_range'] == sur_range]
        media1 = riga['EPgl_nren'].replace(0, pd.NA).dropna()
        if not media1.empty:
            coeff = media1.mean()
            if coeff != 0:
                return coeff
        # Secondo fallback: media su zona_climatica + volris_range
        riga = df_zc[df_zc['volris_range'] == vol_range]
        media2 = riga['EPgl_nren'].replace(0, pd.NA).dropna()
        if not media2.empty:
            coeff = media2.mean()
            if coeff != 0:
                return coeff
        # Terzo fallback: media su tutta la zona_climatica
        media3 = df_zc['EPgl_nren'].replace(0, pd.NA).dropna()
        if not media3.empty:
            coeff = media3.mean()
            if coeff != 0:
                return coeff
        # Se proprio non c'è nulla di diverso da 0
        return 0

    coeff_dom_list = []
    for idx, row in gdf_fabbricati.iterrows():
        sup = row['sup_risc']
        vol = row['vol_risc']
        range_sur = trova_range(sup, suris_ranges)
        range_vol = trova_range(vol, volris_ranges)
        if range_sur is None or range_vol is None:
            logger.warning(f"Range non trovato per fabbricato FID={row.get('FID', idx)}: sup_risc={sup}, vol_risc={vol}")
            coeff_dom_list.append(None)
            continue
        coeff = trova_epgl_robusto(range_sur, range_vol)
        coeff_dom_list.append(coeff)

    gdf_fabbricati['coeff_dom'] = coeff_dom_list
    return gdf_fabbricati

def calcola_domanda_energetica_zc_suris_volris(comune: str, provincia: str) -> gpd.GeoDataFrame:
    return calcola_domanda_energetica(
        comune, provincia, "zc_suris_volris", calcola_coefficiente_domanda_zc_suris_volris
    )

def calcola_coefficiente_domanda_zc_suris_volris_supdi(
    gdf_fabbricati: gpd.GeoDataFrame,
    df_join: pd.DataFrame,
    df_siape: pd.DataFrame,
    comune: str,
    provincia: str
) -> gpd.GeoDataFrame:
    logger.info(f"Calcolo coefficiente domanda con supdi per {comune} ({provincia})...")

    # Normalizzazione
    df_join['_COMUNE_NORM'] = df_join['COMUNE'].astype(str).apply(safe_name)
    df_join['_PROVINCIA_NORM'] = df_join['PROVINCIA'].astype(str).apply(safe_name)

    df_comune = df_join[
        (df_join['_COMUNE_NORM'] == comune) &
        (df_join['_PROVINCIA_NORM'] == provincia)
    ]
    df_join.drop(columns=['_COMUNE_NORM', '_PROVINCIA_NORM'], inplace=True)

    if df_comune.empty:
        raise ValueError(f"Nessun dato trovato per il comune {comune} nella provincia {provincia}.")

    zc = df_comune['ZONA_CLIMATICA'].dropna().unique()
    if len(zc) != 1:
        raise ValueError(f"Zona climatica ambigua o mancante per {comune}. Valori trovati: {zc}")
    zc = zc[0]

    df_zc = df_siape[df_siape['zona_climatica'] == zc]
    if df_zc.empty:
        raise ValueError(f"Nessun dato SIAPE per la zona climatica {zc}")

    suris_ranges = list(df_zc['suris_range'].unique())
    volris_ranges = list(df_zc['volris_range'].unique())
    supdi_ranges = list(df_zc['supdi_range'].unique())

    def trova_range(valore, ranges):
        for r in ranges:
            if r.startswith('<'):
                limite = float(r[1:])
                if valore < limite:
                    return r
            elif r.startswith('>'):
                limite = float(r[1:])
                if valore > limite:
                    return r
            elif '-' in r:
                min_, max_ = map(float, r.split('-'))
                if min_ <= valore < max_:
                    return r
        return None

    def trova_epgl_fallback(sur_range, vol_range, supdi_range):
        # 1. zona_climatica;suris_range;volris_range;supdi_range;
        riga = df_zc[
            (df_zc['suris_range'] == sur_range) &
            (df_zc['volris_range'] == vol_range) &
            (df_zc['supdi_range'] == supdi_range)
        ]
        if not riga.empty:
            coeff = riga.iloc[0]['EPgl_nren']
            if coeff != 0:
                return coeff

        # 2. zona_climatica;suris_range;volris_range;
        riga = df_zc[
            (df_zc['suris_range'] == sur_range) &
            (df_zc['volris_range'] == vol_range)
        ]
        media2 = riga['EPgl_nren'].replace(0, pd.NA).dropna()
        if not media2.empty:
            coeff = media2.mean()
            if coeff != 0:
                return coeff

        # 3. zona_climatica;suris_range;
        riga = df_zc[df_zc['suris_range'] == sur_range]
        media3 = riga['EPgl_nren'].replace(0, pd.NA).dropna()
        if not media3.empty:
            coeff = media3.mean()
            if coeff != 0:
                return coeff

        # 4. zona_climatica;volris_range;
        riga = df_zc[df_zc['volris_range'] == vol_range]
        media4 = riga['EPgl_nren'].replace(0, pd.NA).dropna()
        if not media4.empty:
            coeff = media4.mean()
            if coeff != 0:
                return coeff

        # 5. zona_climatica;
        media5 = df_zc['EPgl_nren'].replace(0, pd.NA).dropna()
        if not media5.empty:
            coeff = media5.mean()
            if coeff != 0:
                return coeff

        # Se proprio non c'è nessun valore diverso da zero
        return 0

    coeff_dom_list = []
    for idx, row in gdf_fabbricati.iterrows():
        sup = row['sup_risc']
        vol = row['vol_risc']
        supdi = row['sup_disp']
        range_sur = trova_range(sup, suris_ranges)
        range_vol = trova_range(vol, volris_ranges)
        range_supdi = trova_range(supdi, supdi_ranges)
        if range_sur is None or range_vol is None or range_supdi is None:
            logger.warning(
                f"Range non trovato per fabbricato FID={row.get('FID', idx)}: "
                f"sup_risc={sup}, vol_risc={vol}, sup_disp={supdi}")
            coeff_dom_list.append(None)
            continue
        coeff = trova_epgl_fallback(range_sur, range_vol, range_supdi)
        coeff_dom_list.append(coeff)

    gdf_fabbricati['coeff_dom'] = coeff_dom_list
    return gdf_fabbricati

def calcola_domanda_energetica_zc_suris_volris_supdi(comune: str, provincia: str) -> gpd.GeoDataFrame:
    return calcola_domanda_energetica(
        comune, provincia, "zc_suris_volris_supdi", calcola_coefficiente_domanda_zc_suris_volris_supdi, "_supdi"
    )

def calcola_domanda_energetica(
    comune: str,
    provincia: str,
    siape_key: str,
    coeff_func,
    suffix: str = ""
) -> gpd.GeoDataFrame:
    logger.info(f"Inizio calcolo domanda energetica{suffix}...")

    prov_safe = safe_name(provincia)
    comm_safe = safe_name(comune)
    regione = get_regione_from_provincia(prov_safe)
    df_join = get_join_data(regione)
    df_siape = get_dati_siape(siape_key)

    shp_dir = os.path.normpath(os.path.join(PROJECT_ROOT, "FABBRICATI", f"fabbricati_{prov_safe}_{comm_safe}"))
    if not os.path.isdir(shp_dir):
        raise FileNotFoundError(f"Directory shapefile non trovata: {shp_dir}")

    shp_files = [f for f in os.listdir(shp_dir) if f.lower().endswith('.shp')]
    if len(shp_files) != 1:
        raise ValueError(f"Atteso un unico file .shp in {shp_dir}, trovati: {shp_files}")
    shp_path = os.path.join(shp_dir, shp_files[0])

    try:
        gdf_fabbricati = gpd.read_file(shp_path)
    except Exception as e:
        logger.warning(f"Errore caricamento shapefile fabbricati: {e}")
        return None

    gdf_fabbricati = calcola_area(gdf_fabbricati, nome_colonna='area')

    subdir = f"{prov_safe}_{comm_safe}"
    dirname = f"domanda_energetica_{prov_safe}_{comm_safe}"
    out_dir = os.path.normpath(os.path.join(PROJECT_ROOT, "Data_Collection", "shapefiles", subdir, dirname))
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir)
    out_shp = os.path.join(out_dir, f"{dirname}.shp")

    # Calcolo/assegnazione coefficiente
    gdf_fabbricati = coeff_func(gdf_fabbricati, df_join, df_siape, comm_safe, prov_safe)
    gdf_fabbricati['domanda_en'] = gdf_fabbricati['area'] * gdf_fabbricati['coeff_dom']

    gdf_fabbricati = get_dati_catasto(gdf_fabbricati, prov_safe, comm_safe)
    gdf_fabbricati.to_file(out_shp, driver='ESRI Shapefile')

    logger.info(f"Shapefile con domanda energetica salvato in {out_shp}")
    return gdf_fabbricati

if __name__ == '__main__':
    configure_logging_if_main(__name__)
    gdf = calcola_domanda_energetica_zc_suris_volris_supdi("giffoni valle piana", "salerno")
