import os
import geopandas as gpd
import logging
from utils import safe_name

# === CONFIGURAZIONE LOGGING ===
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# === COSTANTI PATH ===
SHAPE_IN_DIR = os.path.abspath(os.path.join('..', 'Data_Collection', 'shapefiles'))
OUTPUT_MODEL_BUILDER = os.path.abspath(os.path.join('..', 'model_builder_shapefiles'))

def join_domanda_offerta(provincia: str, comune: str, gdf_domanda: gpd.GeoDataFrame, gdf_offerta: gpd.GeoDataFrame):
    """
    Unisce shapefile domanda_energetica e offerta_energetica (inner join su FID).
    Salva shapefile di output con tutte le colonne (area_mq non duplicata, nomi colonne originali).
    """
    provincia_safe = safe_name(provincia)
    comune_safe = safe_name(comune)
    logger.info(f"Avvio join domanda-offerta per {provincia_safe} - {comune_safe}")

    # Controlla duplicati nelle colonne
    logger.info(f"Colonne domanda: {list(gdf_domanda.columns)}")
    logger.info(f"Colonne offerta: {list(gdf_offerta.columns)}")

    # Se ci sono più colonne FID, tieni solo la prima (o una sola)
    # In caso di duplicati, pandas mette suffissi tipo FID, FID_1, ecc
    offerta_cols = [c for c in gdf_offerta.columns if c != 'geometry' and c != 'area_mq']

    # Rimuovi eventuali duplicati di FID (tieni solo una)
    fid_count = [c for c in offerta_cols if c == 'FID']
    if len(fid_count) > 1:
        # Tieni solo la prima occorrenza
        first = True
        new_cols = []
        for c in offerta_cols:
            if c == 'FID':
                if first:
                    new_cols.append(c)
                    first = False
                # Altrimenti salta
            else:
                new_cols.append(c)
        offerta_cols = new_cols

    # Fai merge senza suffissi
    logger.info("Eseguo inner join su FID senza suffissi nei nomi colonne...")
    gdf_join = gdf_domanda.merge(
        gdf_offerta[offerta_cols],
        on='FID',
        how='inner'
    )

    # Directory e nome file output
    out_dir = os.path.join(
        SHAPE_IN_DIR,
        f"{provincia_safe}_{comune_safe}",
        f"domanda-offerta_energetica_{provincia_safe}_{comune_safe}"
    )
    os.makedirs(out_dir, exist_ok=True)
    join_path = os.path.join(out_dir, f"domanda_offerta_energetica_{provincia_safe}_{comune_safe}.shp")

    # Salvataggio
    logger.info(f"Salvataggio shapefile di join in {join_path}")
    gdf_join.to_file(join_path, encoding="utf-8")
    logger.info("Join domanda-offerta completato.")



def crea_peb_neb(provincia: str, comune: str):
    """
    Genera shapefile di PEB e NEB a partire da offerta_energetica e domanda_energetica.
    """
    provincia_safe = safe_name(provincia)
    comune_safe = safe_name(comune)
    logger.info(f"Avvio generazione PEB e NEB per {provincia_safe} - {comune_safe}")

    # PATH INPUT
    domanda_dir = os.path.join(SHAPE_IN_DIR, f"{provincia_safe}_{comune_safe}", f"domanda_energetica_{provincia_safe}_{comune_safe}")
    offerta_dir = os.path.join(SHAPE_IN_DIR, f"{provincia_safe}_{comune_safe}", f"offerta_energetica_{provincia_safe}_{comune_safe}")

    domanda_files = [f for f in os.listdir(domanda_dir) if f.lower().endswith('.shp')]
    offerta_files = [f for f in os.listdir(offerta_dir) if f.lower().endswith('.shp')]

    if not domanda_files or not offerta_files:
        logger.error("File shapefile non trovati nei percorsi specificati.")
        return

    domanda_shp = os.path.join(domanda_dir, domanda_files[0])
    offerta_shp = os.path.join(offerta_dir, offerta_files[0])

    # Lettura SHP
    logger.info("Caricamento shapefile di domanda e offerta...")
    gdf_domanda = gpd.read_file(domanda_shp)
    gdf_offerta = gpd.read_file(offerta_shp)

    logger.info("Creo shapefile domanda-offerta.")
    join_domanda_offerta(provincia, comune, gdf_domanda, gdf_offerta)

    # Join su FID (ID edificio)
    logger.info("Eseguo join tra domanda e offerta su FID...")
    gdf_join = gdf_domanda.merge(
        gdf_offerta[['FID', 'Prod_kWh_y']],
        on='FID',
        how='inner',
        suffixes=('_dom', '_off')
    )

    # Calcolo surplus/deficit
    gdf_join['diff'] = gdf_join['Prod_kWh_y'] - gdf_join['domanda_en']

    # Split tra PEB (surplus >= 0) e NEB (deficit < 0)
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

    # Path output
    out_dir = os.path.join(OUTPUT_MODEL_BUILDER, f"{provincia_safe}_{comune_safe}", "input")
    peb_dir = os.path.join(out_dir, "peb")
    neb_dir = os.path.join(out_dir, "neb")
    os.makedirs(peb_dir, exist_ok=True)
    os.makedirs(neb_dir, exist_ok=True)

    peb_path = os.path.join(peb_dir, f"PEB_{provincia_safe}_{comune_safe}.shp")
    neb_path = os.path.join(neb_dir, f"NEB_{provincia_safe}_{comune_safe}.shp")

    # Salvataggio
    logger.info(f"Salvataggio PEB in {peb_path}")
    gdf_peb.to_file(peb_path, encoding="utf-8")

    logger.info(f"Salvataggio NEB in {neb_path}")
    gdf_neb.to_file(neb_path, encoding="utf-8")

    logger.info("Generazione shapefile PEB e NEB completata.")

# --- ESEMPIO USO ---
if __name__ == "__main__":
    crea_peb_neb("salerno", "padula")
