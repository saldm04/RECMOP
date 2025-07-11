import os
import shutil

import geopandas as gpd
import logging
from utils import safe_name, configure_logging_if_main

# === CONFIGURAZIONE LOGGING ===
logger = logging.getLogger(__name__)

# === COSTANTI PATH ASSOLUTI ===
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
SHAPE_IN_DIR = os.path.abspath(os.path.join(BASE_DIR, '..', 'Data_Collection', 'shapefiles'))
OUTPUT_MODEL_BUILDER = os.path.abspath(os.path.join(BASE_DIR, '..', 'model_builder_shapefiles'))

def join_domanda_offerta(provincia: str, comune: str, gdf_domanda: gpd.GeoDataFrame, gdf_offerta: gpd.GeoDataFrame):
    """
    Esegue il join tra domanda energetica e offerta energetica sui fabbricati (ID_FAB).
    Salva il risultato in un file GPKG unico.

    Parametri
    ----------
    provincia : str
        Nome della provincia.
    comune : str
        Nome del comune.
    gdf_domanda : geopandas.GeoDataFrame
        GeoDataFrame contenente la domanda energetica per fabbricato.
    gdf_offerta : geopandas.GeoDataFrame
        GeoDataFrame contenente l'offerta energetica per fabbricato.

    Restituisce
    ----------
    None

    Effetti
    -------
    Salva su disco il file GPKG risultante dal join.
    """
    provincia_safe = safe_name(provincia)
    comune_safe = safe_name(comune)
    logger.info(f"Avvio join domanda-offerta per {provincia_safe} - {comune_safe}")

    logger.info(f"Colonne domanda: {list(gdf_domanda.columns)}")
    logger.info(f"Colonne offerta: {list(gdf_offerta.columns)}")

    # Colonne da escludere sempre
    exclude_cols = {'geometry', 'area'}

    # Colonne in comune da evitare nel merge per evitare conflitti
    comuni_da_escludere = set(gdf_domanda.columns) & set(gdf_offerta.columns) - {'ID_FAB'}
    offerta_cols = [col for col in gdf_offerta.columns if col not in comuni_da_escludere and col not in exclude_cols]

    # Mantieni 'ID_FAB' per il join
    if 'ID_FAB' in gdf_offerta.columns:
        offerta_cols = ['ID_FAB'] + [col for col in offerta_cols if col != 'ID_FAB']

    logger.info(f"Colonne selezionate per offerta dopo pulizia: {offerta_cols}")

    logger.info("Eseguo inner join su ID_FAB evitando conflitti di colonna...")
    gdf_join = gdf_domanda.merge(
        gdf_offerta[offerta_cols],
        on='ID_FAB',
        how='inner'
    )

    out_dir = os.path.abspath(os.path.join(
        SHAPE_IN_DIR,
        f"{provincia_safe}_{comune_safe}",
        f"domanda-offerta_energetica_{provincia_safe}_{comune_safe}"
    ))
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    join_path = os.path.join(out_dir, f"domanda_offerta_energetica_{provincia_safe}_{comune_safe}.gpkg")

    logger.info(f"Salvataggio gpkg di join in {join_path}")
    gdf_join.to_file(join_path, encoding="utf-8")
    logger.info("Join domanda-offerta completato.")

def crea_peb_neb(provincia: str, comune: str):
    """
    Genera i dataset PEB (edifici positivi) e NEB (edifici negativi) per domanda e offerta energetica.
    Salva i relativi file GPKG per input ai modelli successivi.

    Parametri
    ----------
    provincia : str
        Nome della provincia.
    comune : str
        Nome del comune.

    Restituisce
    ----------
    tuple of int
        Numero di edifici PEB e NEB generati (len(gdf_peb), len(gdf_neb)).

    Effetti
    -------
    Salva su disco i GPKG di PEB e NEB, e il join domanda-offerta.
    """
    provincia_safe = safe_name(provincia)
    comune_safe = safe_name(comune)
    logger.info(f"Avvio generazione PEB e NEB per {provincia_safe} - {comune_safe}")

    domanda_dir = os.path.abspath(os.path.join(
        SHAPE_IN_DIR, f"{provincia_safe}_{comune_safe}",
        f"domanda_energetica_{provincia_safe}_{comune_safe}"
    ))
    offerta_dir = os.path.abspath(os.path.join(
        SHAPE_IN_DIR, f"{provincia_safe}_{comune_safe}",
        f"offerta_energetica_{provincia_safe}_{comune_safe}"
    ))

    domanda_files = [f for f in os.listdir(domanda_dir) if f.lower().endswith('.gpkg')]
    offerta_files = [f for f in os.listdir(offerta_dir) if f.lower().endswith('.gpkg')]

    if not domanda_files or not offerta_files:
        logger.error("File gpkg non trovati nei percorsi specificati.")
        return

    domanda_shp = os.path.join(domanda_dir, domanda_files[0])
    offerta_shp = os.path.join(offerta_dir, offerta_files[0])

    logger.info("Caricamento gpkg di domanda e offerta...")
    gdf_domanda = gpd.read_file(domanda_shp)
    gdf_offerta = gpd.read_file(offerta_shp)

    logger.info("Creo gpkg domanda-offerta.")
    join_domanda_offerta(provincia, comune, gdf_domanda, gdf_offerta)

    logger.info("Eseguo join tra domanda e offerta su ID_FAB...")
    gdf_join = gdf_domanda.merge(
        gdf_offerta[['ID_FAB', 'Prod_kWh_y']],
        on='ID_FAB',
        how='inner',
        suffixes=('_dom', '_off')
    )

    gdf_join['diff'] = gdf_join['Prod_kWh_y'] - gdf_join['domanda_en']

    gdf_peb = gdf_join[gdf_join['diff'] >= 0].copy()
    gdf_peb['ID_P'] = gdf_peb['ID_FAB']
    gdf_peb['surplus'] = gdf_peb['diff']
    gdf_peb = gdf_peb[['geometry', 'ID_P', 'surplus']]
    gdf_peb = gpd.GeoDataFrame(gdf_peb, geometry='geometry', crs=gdf_domanda.crs)

    gdf_neb = gdf_join[gdf_join['diff'] < 0].copy()
    gdf_neb['ID_N'] = gdf_neb['ID_FAB']
    gdf_neb['deficit'] = gdf_neb['diff']
    gdf_neb = gdf_neb[['geometry', 'ID_N', 'deficit']]
    gdf_neb = gpd.GeoDataFrame(gdf_neb, geometry='geometry', crs=gdf_domanda.crs)

    out_dir = os.path.abspath(os.path.join(
        OUTPUT_MODEL_BUILDER, f"{provincia_safe}_{comune_safe}", "input"
    ))
    peb_dir = os.path.join(out_dir, "peb")
    neb_dir = os.path.join(out_dir, "neb")
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(peb_dir, exist_ok=True)
    os.makedirs(neb_dir, exist_ok=True)
    peb_path = os.path.join(peb_dir, f"PEB_{provincia_safe}_{comune_safe}.gpkg")
    neb_path = os.path.join(neb_dir, f"NEB_{provincia_safe}_{comune_safe}.gpkg")

    logger.info(f"Salvataggio PEB in {peb_path}")
    gdf_peb.to_file(peb_path, encoding="utf-8")

    logger.info(f"Salvataggio NEB in {neb_path}")
    gdf_neb.to_file(neb_path, encoding="utf-8")

    logger.info("Generazione gpkg PEB e NEB completata.")

    return len(gdf_peb), len(gdf_neb)
