import os
import shutil
import logging
import requests
import xml.etree.ElementTree as ET
import geopandas as gpd

# ========================
# CONFIGURAZIONE LOGGING
# ========================
LOG_FORMAT = '%(asctime)s - %(levelname)s - %(message)s'
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, handlers=[logging.StreamHandler()])
logger = logging.getLogger(__name__)

# ========================
# COSTANTI WFS
# ========================
BASE_URL_WFS = 'https://wfs.cartografia.agenziaentrate.gov.it/inspire/wfs/owfs01.php'
SRS_NAME = 'urn:ogc:def:crs:EPSG::6706'
LANGUAGE = 'ita'
TYPENAME = 'CP:CadastralParcel'

# Contatore richieste WFS
request_counter = 0

# ========================
# GENERA CENTROIDI
# ========================
def genera_centroidi_da_gdf(gdf_poligoni: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Calcola i centroidi del GeoDataFrame fornito, mantenendo la colonna 'id'."""
    logger.info("Calcolo dei centroidi dai poligoni.")

    if 'id' not in gdf_poligoni.columns:
        raise ValueError("Il GeoDataFrame deve contenere una colonna 'id'.")

    centroids = gdf_poligoni.geometry.centroid
    centroids_gdf = gpd.GeoDataFrame(
        gdf_poligoni[['id']],
        geometry=centroids,
        crs=gdf_poligoni.crs
    )
    centroids_gdf = centroids_gdf.to_crs(epsg=6706)
    return centroids_gdf

# ========================
# QUERY WFS
# ========================
def query_catasto_point(x: float, y: float) -> dict:
    """Effettua una richiesta WFS per ottenere i dati catastali in corrispondenza di (x, y)."""
    global request_counter
    request_counter += 1
    logger.info(f"Richiesta WFS n. {request_counter} - Punto: ({x}, {y})")

    params = {
        'SERVICE': 'WFS',
        'VERSION': '2.0.0',
        'REQUEST': 'GetFeature',
        'TYPENAMES': TYPENAME,
        'SRSNAME': SRS_NAME,
        'BBOX': f'{y},{x},{y},{x}',
        'LANGUAGE': LANGUAGE
    }

    try:
        response = requests.get(BASE_URL_WFS, params=params)
        response.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"Errore durante la richiesta WFS per ({x}, {y}): {e}")
        return None

    try:
        root = ET.fromstring(response.content)
        namespaces = {
            'wfs': 'http://www.opengis.net/wfs/2.0',
            'gml': 'http://www.opengis.net/gml/3.2',
            'CP': 'http://mapserver.gis.umn.edu/mapserver'
        }

        features = root.findall('.//CP:CadastralParcel', namespaces)
        if not features:
            logger.warning(f"Nessuna particella trovata per le coordinate ({x}, {y})")
            return None

        feat = features[0]
        result = {
            'INSPIREID_LOCALID': feat.find('.//CP:INSPIREID_LOCALID', namespaces).text,
            'LABEL': feat.find('.//CP:LABEL', namespaces).text,
            'ADMINISTRATIVEUNIT': feat.find('.//CP:ADMINISTRATIVEUNIT', namespaces).text,
            'NATIONALCADASTRALREFERENCE': feat.find('.//CP:NATIONALCADASTRALREFERENCE', namespaces).text
        }
        # Log dei dati che verranno salvati nel shapefile
        logger.info(f"Dati salvati shapefile ({x}, {y}): FOGLIO={result['INSPIREID_LOCALID'].split('_')[1].split('.')[0] if '_' in result['INSPIREID_LOCALID'] and '.' in result['INSPIREID_LOCALID'] else None}, "
                    f"PARTICELLA={result['LABEL']}, COD_COMUNE={result['ADMINISTRATIVEUNIT']}")
        return result
    except ET.ParseError as e:
        logger.error(f"Errore nel parsing XML per ({x}, {y}): {e}")
        return None

# ========================
# GESTIONE PERCORSI
# ========================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_BASE_DIR = os.path.normpath(os.path.join(BASE_DIR, "..", "Data_Collection", "shapefiles"))

def get_output_paths(provincia: str, comune: str) -> tuple:
    """
    Restituisce la directory e il percorso completo dello shapefile per provincia e comune (in minuscolo, senza spazi).
    [assoluto]/Data_Collection/shapefiles/[provincia]_[comune]/dati_catasto_[provincia]_[comune]/dati_catasto_[provincia]_[comune].shp
    """
    provincia = provincia.lower().replace(" ", "_")
    comune = comune.lower().replace(" ", "_")
    subdir = f"{provincia}_{comune}"
    dir_name = f"dati_catasto_{provincia}_{comune}"
    dir_path = os.path.join(OUTPUT_BASE_DIR, subdir, dir_name)
    shp_name = f"{dir_name}.shp"
    shp_path = os.path.join(dir_path, shp_name)
    return dir_path, shp_path


# ========================
# SALVA SHAPEFILE
# ========================
def salva_shapefile_catastale(gdf: gpd.GeoDataFrame, provincia: str, comune: str):
    """Salva il GeoDataFrame in shapefile nella directory dedicata."""
    dir_path, shp_path = get_output_paths(provincia, comune)
    os.makedirs(dir_path, exist_ok=True)
    logger.info(f"Salvataggio shapefile: {shp_path}")
    gdf.to_file(shp_path, driver='ESRI Shapefile')

# ========================
# ELABORAZIONE GEOdataframe
# ========================
def _process_geodataframe(gdf_poligoni: gpd.GeoDataFrame, provincia: str, comune: str) -> gpd.GeoDataFrame:
    """Processa i poligoni: genera centroidi, effettua query catastali e associa i dati."""
    # Assicura colonna id
    if 'id' not in gdf_poligoni.columns:
        gdf_poligoni = gdf_poligoni.reset_index().rename(columns={'index': 'id'})

    crs_originale = gdf_poligoni.crs
    cent_gdf = genera_centroidi_da_gdf(gdf_poligoni)

    # Prepara colonne
    cent_gdf['FOGLIO'] = None
    cent_gdf['PARTICELLA'] = None
    cent_gdf['COD_COMUNE'] = None

    logger.info(f"Elaborazione di {len(cent_gdf)} richieste WFS totali.")
    for idx, row in cent_gdf.iterrows():
        x, y = row.geometry.x, row.geometry.y
        result = query_catasto_point(x, y)
        if result:
            inspireid = result['INSPIREID_LOCALID']
            foglio = inspireid.split('_')[1].split('.')[0] if '_' in inspireid and '.' in inspireid else None
            cent_gdf.at[idx, 'FOGLIO'] = foglio
            cent_gdf.at[idx, 'PARTICELLA'] = result.get('LABEL')
            cent_gdf.at[idx, 'COD_COMUNE'] = result.get('ADMINISTRATIVEUNIT')

    # Unisci a poligoni
    merged = gdf_poligoni.merge(
        cent_gdf[['id', 'FOGLIO', 'PARTICELLA', 'COD_COMUNE']],
        on='id', how='left'
    ).drop(columns='id')

    # Ripristina CRS
    if merged.crs != crs_originale:
        merged = merged.set_crs(crs_originale, allow_override=True)

    # Salva
    salva_shapefile_catastale(merged, provincia, comune)
    return merged

# ========================
# FUNZIONE GET
# ========================
def get_dati_catasto(gdf_poligoni: gpd.GeoDataFrame, provincia: str, comune: str) -> gpd.GeoDataFrame:
    """
    Restituisce il GeoDataFrame arricchito con i dati catastali per il comune e provincia specificati.
    Se esiste già lo shapefile, lo carica; altrimenti lo genera.
    """
    dir_path, shp_path = get_output_paths(provincia, comune)
    if os.path.exists(shp_path):
        logger.info(f"Shapefile esistente trovato: {shp_path}. Caricamento dati.")
        return gpd.read_file(shp_path)
    logger.info("Nessun shapefile preesistente: avvio elaborazione dati catastali.")
    return _process_geodataframe(gdf_poligoni, provincia, comune)

# ========================
# FUNZIONE REFRESH
# ========================
def refresh_dati_catasto(gdf_poligoni: gpd.GeoDataFrame, provincia: str, comune: str) -> gpd.GeoDataFrame:
    """
    Ricalcola e riscrive i dati catastali per il comune e provincia specificati,
    sovrascrivendo eventuali dati esistenti.
    """
    dir_path, shp_path = get_output_paths(provincia, comune)
    if os.path.exists(dir_path):
        logger.info(f"Directory esistente {dir_path}: rimozione per refresh.")
        shutil.rmtree(dir_path)
    return _process_geodataframe(gdf_poligoni, provincia, comune)
