import hashlib
import os
import shutil
import logging

import pandas as pd
import requests
import xml.etree.ElementTree as ET
import geopandas as gpd

from utils import safe_name, get_best_utm_epsg

# ========================
# CONFIGURAZIONE LOGGING
# ========================

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
def genera_centroidi_da_gdf(gdf_poligoni: gpd.GeoDataFrame, epsg_metrico: int = None) -> gpd.GeoDataFrame:
    """
    Calcola i centroidi delle geometrie nel GeoDataFrame fornito, mantenendo la colonna 'id'.

    Se il CRS è geografico (non proiettato), converte temporaneamente le geometrie in un CRS metrico (EPSG automatico o specificato).
    I centroidi risultanti sono restituiti in EPSG:6706, idoneo per richieste WFS.

    Parametri
    ----------
    gdf_poligoni : gpd.GeoDataFrame
        GeoDataFrame contenente poligoni e colonna 'id'.
    epsg_metrico : int, opzionale
        Codice EPSG del CRS metrico da usare per il calcolo centroidi (default: automatico).

    Restituisce
    ----------
    gpd.GeoDataFrame
        GeoDataFrame di centroidi con colonna 'id' e CRS EPSG:6706.
    """
    logger.info("Calcolo dei centroidi dai poligoni.")

    if 'id' not in gdf_poligoni.columns:
        raise ValueError("Il GeoDataFrame deve contenere una colonna 'id'.")

    original_crs = gdf_poligoni.crs

    # Se il CRS non è proiettato, si converte temporaneamente
    if original_crs is None or not original_crs.is_projected:
        if epsg_metrico is None:
            epsg_metrico = get_best_utm_epsg(gdf_poligoni)
            logger.info(f"CRS geografico rilevato. Uso automatico del CRS metrico EPSG:{epsg_metrico} per calcolo centroidi.")
        else:
            logger.info(f"CRS geografico rilevato. Uso CRS metrico specificato EPSG:{epsg_metrico} per calcolo centroidi.")
        gdf_temp = gdf_poligoni.to_crs(epsg=epsg_metrico)
    else:
        gdf_temp = gdf_poligoni

    # Calcolo dei centroidi nel CRS metrico
    centroids = gdf_temp.geometry.centroid

    # Restituisci centroidi in EPSG:6706 (per WFS)
    centroids_gdf = gpd.GeoDataFrame(
        gdf_poligoni[['id']],
        geometry=centroids,
        crs=gdf_temp.crs
    ).to_crs(epsg=6706)

    return centroids_gdf

# ========================
# QUERY WFS
# ========================
def query_catasto_point(x: float, y: float) -> dict:
    """
    Effettua una richiesta WFS al servizio catastale per ottenere i dati catastali del punto specificato (x, y).

    Parametri
    ----------
    x : float
        Coordinata X del punto (longitudine).
    y : float
        Coordinata Y del punto (latitudine).

    Restituisce
    ----------
    dict
        Dizionario con i dati catastali estratti (INSPIREID_LOCALID, LABEL, ADMINISTRATIVEUNIT, NATIONALCADASTRALREFERENCE),
        oppure None se non trovati o in caso di errore.
    """
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
        # Log dei dati che verranno salvati nel gpkg
        logger.info(f"Dati salvati gpkg ({x}, {y}): FOGLIO={result['INSPIREID_LOCALID'].split('_')[1].split('.')[0] if '_' in result['INSPIREID_LOCALID'] and '.' in result['INSPIREID_LOCALID'] else None}, "
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
    Restituisce la directory e il percorso completo dello shapefile/geopackage
    per una coppia provincia-comune (nome normalizzato).

    Parametri
    ----------
    provincia : str
        Nome della provincia.
    comune : str
        Nome del comune.

    Restituisce
    ----------
    tuple
        (percorso directory, percorso file .gpkg) normalizzati e già pronti per il salvataggio.
    """
    prov_safe = safe_name(provincia)
    comune_safe = safe_name(comune)
    subdir = f"{prov_safe}_{comune_safe}"
    dir_name = f"dati_catasto_{prov_safe}_{comune_safe}"
    dir_path = os.path.join(OUTPUT_BASE_DIR, subdir, dir_name)
    gpkg_name = f"{dir_name}.gpkg"
    gpkg_path = os.path.join(dir_path, gpkg_name)
    return dir_path, gpkg_path


# ========================
# SALVA gpkg
# ========================
def salva_shapefile_catastale(gdf: gpd.GeoDataFrame, provincia: str, comune: str):
    """
    Salva il GeoDataFrame fornito come geopackage in una directory dedicata a provincia e comune.

    Se la directory esiste già, viene rimossa e ricreata.

    Parametri
    ----------
    gdf : gpd.GeoDataFrame
        GeoDataFrame da salvare.
    provincia : str
        Nome della provincia.
    comune : str
        Nome del comune.
    """
    dir_path, gpkg_path = get_output_paths(provincia, comune)
    if os.path.exists(dir_path):
        shutil.rmtree(dir_path)
    os.makedirs(dir_path)
    logger.info(f"Salvataggio gpkg: {gpkg_path}")
    gdf.to_file(gpkg_path, driver='GPKG')

# ========================
# ELABORAZIONE GEOdataframe
# ========================
def _process_geodataframe(gdf_poligoni: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Elabora un GeoDataFrame di poligoni: genera i centroidi, effettua query catastali su ciascun centroide,
    e associa i dati catastali ai poligoni originali.

    Parametri
    ----------
    gdf_poligoni : gpd.GeoDataFrame
        GeoDataFrame di poligoni (con colonna 'id').

    Restituisce
    ----------
    gpd.GeoDataFrame
        GeoDataFrame dei poligoni con nuove colonne catastali ('FOGLIO', 'PARTICELLA', 'COD_COMUNE').
    """
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
        
    return merged

# ========================
# FUNZIONE GET
# ========================

def geom_hash(geom):
    """
    Calcola l'hash SHA1 di una geometria (usando il suo WKB) per confronti e deduplicazioni.

    Parametri
    ----------
    geom : shapely.geometry.base.BaseGeometry
        Oggetto geometria di shapely.

    Restituisce
    ----------
    str
        Hash SHA1 della geometria.
    """
    return hashlib.sha1(geom.wkb).hexdigest()

def get_dati_catasto(gdf_poligoni: gpd.GeoDataFrame, provincia: str, comune: str) -> gpd.GeoDataFrame:
    """
    Restituisce il GeoDataFrame arricchito con i dati catastali per comune e provincia specificati.

    Se esiste già un file geopackage per la combinazione (provincia, comune), lo riutilizza e aggiorna solo le nuove geometrie;
    in caso contrario esegue l'elaborazione completa.

    Parametri
    ----------
    gdf_poligoni : gpd.GeoDataFrame
        GeoDataFrame originale dei poligoni.
    provincia : str
        Nome della provincia.
    comune : str
        Nome del comune.

    Restituisce
    ----------
    gpd.GeoDataFrame
        GeoDataFrame originale arricchito con le colonne catastali ('FOGLIO', 'PARTICELLA', 'COD_COMUNE').
    """
    crs_originale = gdf_poligoni.crs
    dir_path, gpkg_path = get_output_paths(provincia, comune)

    if os.path.exists(gpkg_path):
        logger.info(f"gpkg catastale già esistente: {gpkg_path}. Caricamento dati.")
        gdf_catasto = gpd.read_file(gpkg_path).to_crs(crs_originale)

        logger.info("Confronto geometrie tramite hash...")
        catasto_hashes = set(gdf_catasto.geometry.map(geom_hash))
        gdf_poligoni['geom_hash'] = gdf_poligoni.geometry.map(geom_hash)

        gdf_poligoni_diff = gdf_poligoni[~gdf_poligoni['geom_hash'].isin(catasto_hashes)].copy()
        gdf_poligoni_diff.drop(columns='geom_hash', inplace=True)

        if not gdf_poligoni_diff.empty:
            logger.info(f"Elaborazione di {len(gdf_poligoni_diff)} nuove geometrie.")
            gdf_nuovi_dati = _process_geodataframe(gdf_poligoni_diff).to_crs(crs_originale)

            gdf_unito = pd.concat([gdf_catasto, gdf_nuovi_dati], ignore_index=True)
            gdf_unito = gpd.GeoDataFrame(gdf_unito, geometry='geometry', crs=crs_originale)

            if 'geom_hash' in gdf_unito.columns:
                gdf_unito = gdf_unito.drop(columns='geom_hash')

            # Salva solo i dati catastali minimali in EPSG:6706
            gdf_unito_gpkg = gdf_unito[['geometry', 'FOGLIO', 'PARTICELLA', 'COD_COMUNE']].copy()
            salva_shapefile_catastale(gdf_unito_gpkg, provincia, comune)
        else:
            gdf_unito = gdf_catasto
            logger.info("Nessuna nuova geometria da elaborare.")

    else:
        logger.info("Nessun gpkg preesistente: elaborazione completa.")
        gdf_unito = _process_geodataframe(gdf_poligoni).to_crs(crs_originale)
        gdf_unito_gpkg = gdf_unito[['geometry', 'FOGLIO', 'PARTICELLA', 'COD_COMUNE']].copy()
        salva_shapefile_catastale(gdf_unito_gpkg, provincia, comune)

    # Merge finale: arricchimento del GeoDataFrame originale
    logger.info("Arricchimento finale di gdf_poligoni con dati catastali.")
    gdf_unito['geom_hash'] = gdf_unito.geometry.map(geom_hash)
    gdf_poligoni['geom_hash'] = gdf_poligoni.geometry.map(geom_hash)

    gdf_finale = gdf_poligoni.merge(
        gdf_unito[['geom_hash', 'FOGLIO', 'PARTICELLA', 'COD_COMUNE']],
        on='geom_hash', how='left'
    ).drop(columns=['geom_hash'])

    return gdf_finale

# ========================
# FUNZIONE REFRESH
# ========================
def refresh_dati_catasto(gdf_poligoni: gpd.GeoDataFrame, provincia: str, comune: str) -> gpd.GeoDataFrame:
    """
    Ricalcola e sovrascrive i dati catastali per il comune e la provincia specificati,
    eliminando eventuali dati già esistenti.

    Parametri
    ----------
    gdf_poligoni : gpd.GeoDataFrame
        GeoDataFrame dei poligoni di input.
    provincia : str
        Nome della provincia.
    comune : str
        Nome del comune.

    Restituisce
    ----------
    gpd.GeoDataFrame
        GeoDataFrame arricchito con i dati catastali appena ricalcolati.
    """
    dir_path, gpkg_path = get_output_paths(provincia, comune)
    if os.path.exists(dir_path):
        logger.info(f"Directory esistente {dir_path}: rimozione per refresh.")
        shutil.rmtree(dir_path)
    gdf = _process_geodataframe(gdf_poligoni)
    salva_shapefile_catastale(gdf, provincia, comune)
    return gdf
