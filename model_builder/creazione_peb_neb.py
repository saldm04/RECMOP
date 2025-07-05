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
    provincia_safe = safe_name(provincia)
    comune_safe = safe_name(comune)
    logger.info(f"Avvio join domanda-offerta per {provincia_safe} - {comune_safe}")

    logger.info(f"Colonne domanda: {list(gdf_domanda.columns)}")
    logger.info(f"Colonne offerta: {list(gdf_offerta.columns)}")

    # Colonne da escludere sempre
    exclude_cols = {'geometry', 'area'}

    # Colonne in comune da evitare nel merge per evitare conflitti
    comuni_da_escludere = set(gdf_domanda.columns) & set(gdf_offerta.columns) - {'FID'}
    offerta_cols = [col for col in gdf_offerta.columns if col not in comuni_da_escludere and col not in exclude_cols]

    # Mantieni 'FID' per il join
    if 'FID' in gdf_offerta.columns:
        offerta_cols = ['FID'] + [col for col in offerta_cols if col != 'FID']

    logger.info(f"Colonne selezionate per offerta dopo pulizia: {offerta_cols}")

    logger.info("Eseguo inner join su FID evitando conflitti di colonna...")
    gdf_join = gdf_domanda.merge(
        gdf_offerta[offerta_cols],
        on='FID',
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
    join_path = os.path.join(out_dir, f"domanda_offerta_energetica_{provincia_safe}_{comune_safe}.shp")

    logger.info(f"Salvataggio shapefile di join in {join_path}")
    gdf_join.to_file(join_path, encoding="utf-8")
    logger.info("Join domanda-offerta completato.")

def crea_peb_neb(provincia: str, comune: str):
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

    domanda_files = [f for f in os.listdir(domanda_dir) if f.lower().endswith('.shp')]
    offerta_files = [f for f in os.listdir(offerta_dir) if f.lower().endswith('.shp')]

    if not domanda_files or not offerta_files:
        logger.error("File shapefile non trovati nei percorsi specificati.")
        return

    domanda_shp = os.path.join(domanda_dir, domanda_files[0])
    offerta_shp = os.path.join(offerta_dir, offerta_files[0])

    logger.info("Caricamento shapefile di domanda e offerta...")
    gdf_domanda = gpd.read_file(domanda_shp)
    gdf_offerta = gpd.read_file(offerta_shp)

    logger.info("Creo shapefile domanda-offerta.")
    join_domanda_offerta(provincia, comune, gdf_domanda, gdf_offerta)

    logger.info("Eseguo join tra domanda e offerta su FID...")
    gdf_join = gdf_domanda.merge(
        gdf_offerta[['FID', 'Prod_kWh_y']],
        on='FID',
        how='inner',
        suffixes=('_dom', '_off')
    )

    gdf_join['diff'] = gdf_join['Prod_kWh_y'] - gdf_join['domanda_en']

    gdf_peb = gdf_join[gdf_join['diff'] >= 0].copy()
    gdf_peb['ID_P'] = gdf_peb['FID']
    gdf_peb['surplus'] = gdf_peb['diff']
    gdf_peb = gdf_peb[['geometry', 'ID_P', 'surplus']]
    gdf_peb = gpd.GeoDataFrame(gdf_peb, geometry='geometry', crs=gdf_domanda.crs)

    gdf_neb = gdf_join[gdf_join['diff'] < 0].copy()
    gdf_neb['ID_N'] = gdf_neb['FID']
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
    peb_path = os.path.join(peb_dir, f"PEB_{provincia_safe}_{comune_safe}.shp")
    neb_path = os.path.join(neb_dir, f"NEB_{provincia_safe}_{comune_safe}.shp")

    logger.info(f"Salvataggio PEB in {peb_path}")
    gdf_peb.to_file(peb_path, encoding="utf-8")

    logger.info(f"Salvataggio NEB in {neb_path}")
    gdf_neb.to_file(neb_path, encoding="utf-8")

    logger.info("Generazione shapefile PEB e NEB completata.")

# --- ESEMPIO USO ---
if __name__ == "__main__":
    # Abilita logging solo se eseguito standalone
    configure_logging_if_main(__name__)
    crea_peb_neb("salerno", "padula")
