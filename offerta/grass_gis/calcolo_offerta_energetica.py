import os
import sys
import subprocess
import logging
from dotenv import load_dotenv
import rasterio
import geopandas as gpd
import calendar
import pandas as pd
from pvlib.clearsky import lookup_linke_turbidity
from rasterstats import zonal_stats
from data_extraction.calcola_area_poligoni import calcola_area
from utils import safe_name

# CONFIGURAZIONE LOG
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger('irradiance_pipeline')

# Carica configurazioni da .env
load_dotenv(os.path.join('..', '..', '.env'))
GRASS_BASE = os.getenv('GRASS_BASE')
GRASS_GISDB = os.getenv('GRASS_GISDB')
GRASS_LOCATION = os.getenv('GRASS_LOCATION', 'auto_location')
GRASS_MAPSET = os.getenv('GRASS_MAPSET', 'PERMANENT')

# Directory di input/output fissi
FABBRICATI_BASE = os.path.abspath(os.path.join('..', '..', 'FABBRICATI'))
DSM_BASE = os.path.abspath(os.path.join('..', '..', 'input_dsm'))
OUTPUT_DIR = os.path.abspath(os.path.join('..', 'grass_gis', 'irradiance_tif'))
SHAPE_OUT_DIR = os.path.abspath(os.path.join('..', '..', 'Data_Collection', 'shapefiles'))
# Percorso al file CSV dei pannelli fotovoltaici
PANEL_DATA_PATH = os.path.abspath(os.path.join('..', 'panel', 'panels.csv'))


def create_grass_location(grass_base, gisdb, location, epsg_code) -> None:
    """Crea una location GRASS se non esiste."""
    loc_path = os.path.join(gisdb, location)
    if not os.path.exists(loc_path):
        logger.info(f'Creazione GRASS location {location} con EPSG:{epsg_code}')
        grass_bin = os.path.join(grass_base, 'grass84.bat')
        subprocess.run([grass_bin, '-c', f'EPSG:{epsg_code}', '-e', loc_path], check=True)


def init_grass_environment(grass_base, gisdb, location, mapset):
    """Inizializza le variabili d'ambiente di GRASS GIS e ritorna il modulo grass.script."""
    logger.debug('Imposto ambiente GRASS GIS')
    os.environ['GISBASE'] = grass_base
    os.environ['PATH'] = os.pathsep.join([
        os.path.join(grass_base, 'bin'),
        os.path.join(grass_base, 'scripts'),
        os.environ.get('PATH', '')
    ])
    pythonpath = os.path.join(grass_base, 'etc', 'python')
    if pythonpath not in sys.path:
        sys.path.insert(0, pythonpath)
    os.environ['PYTHONPATH'] = pythonpath
    import grass.script.setup as gsetup
    gsetup.init(gisdb, location, mapset)
    import grass.script as gs
    logger.info('GRASS GIS inizializzato')
    return gs


def reproject_if_needed(src_crs, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Riproietta il GeoDataFrame per matchare src_crs."""
    if gdf.crs.to_epsg() != src_crs.to_epsg():
        logger.warning('CRS non corrispondente: eseguo riproiezione vettoriale')
        return gdf.to_crs(src_crs)
    logger.debug('CRS corrispondente: nessuna riproiezione necessaria')
    return gdf


def get_epsg(dem_path: str) -> int:
    """Estrae il codice EPSG dal file DEM."""
    logger.debug(f'Leggo CRS da DEM: {dem_path}')
    with rasterio.open(dem_path) as src:
        epsg = src.crs.to_epsg()
    if epsg is None:
        logger.error('Impossibile rilevare EPSG dal DEM')
        raise ValueError('EPSG non rilevabile dal DEM')
    logger.info(f'EPSG rilevato dal DEM: {epsg}')
    return epsg


def get_centroid(shp_path: str) -> tuple:
    """Ritorna lat, lon del centroide in WGS84."""
    logger.debug(f'Calcolo centroide per: {shp_path}')
    gdf = gpd.read_file(shp_path)
    gdf = reproject_if_needed(gdf.crs, gdf).to_crs(epsg=4326)
    union_geom = gdf.geometry.union_all()
    centroid = union_geom.centroid
    return centroid.y, centroid.x


def get_linke_turbidity(lat: float, lon: float) -> dict:
    """Recupera i valori di turbidity Linke per ciascun mese."""
    logger.debug('Richiedo turbidity Linke')
    mid_days = []
    for m in range(1, 13):
        dim = calendar.monthrange(2021, m)[1]
        mid = sum(calendar.monthrange(2021, mm)[1] for mm in range(1, m)) + dim // 2
        mid_days.append(mid)
    times = pd.to_datetime(['2021-01-01'] * 12) + pd.to_timedelta([d-1 for d in mid_days], 'D')
    turb = lookup_linke_turbidity(times.tz_localize('UTC'), lat, lon)
    vals = {i+1: float(v) for i, v in enumerate(turb.values)}
    logger.info(f'Turbidity Linke per mesi: {vals}')
    return vals

def solar_radiation_pipeline(provincia: str, comune: str) -> str:
    """Genera il raster annuale di irradianza in kWh."""
    prov_safe = safe_name(provincia)
    com_safe = safe_name(comune)
    output_tif = os.path.join(OUTPUT_DIR, f'irradianza_annua_{prov}_{com}_kwh.tif')
    dem = os.path.join(DSM_BASE, f'DSM_{prov_safe}_{com_safe}.tif')
    shapefolder = os.path.join(FABBRICATI_BASE, f'fabbricati_{prov}_{com}')

    logger.info(f'Avvio pipeline solare per {provincia}/{comune}')
    shp_list = [f for f in os.listdir(shapefolder) if f.lower().endswith('.shp')]
    if not shp_list:
        raise FileNotFoundError(f'Nessuno shapefile in {shapefolder}')
    shp = os.path.join(shapefolder, shp_list[0])

    epsg = get_epsg(dem)
    create_grass_location(GRASS_BASE, GRASS_GISDB, GRASS_LOCATION, epsg)
    gs = init_grass_environment(GRASS_BASE, GRASS_GISDB, GRASS_LOCATION, GRASS_MAPSET)

    lat, lon = get_centroid(shp)
    turb_by_month = get_linke_turbidity(lat, lon)

    gs.run_command('r.import', input=dem, output='dem', overwrite=True)
    gs.run_command('r.slope.aspect', elevation='dem', slope='slope', aspect='aspect', overwrite=True)
    gs.run_command('v.import', input=shp, output='fabbricati', overwrite=True)
    gs.run_command('g.region', vector='fabbricati', res=2)

    rasters = []
    for m in range(1, 13):
        dim = calendar.monthrange(2021, m)[1]
        mid = sum(calendar.monthrange(2021, mm)[1] for mm in range(1, m)) + dim // 2
        linke = turb_by_month.get(m, 3.5)
        nome = f'irr_{mid}'
        gs.run_command('r.sun', elevation='dem', slope='slope', aspect='aspect',
                       glob_rad=nome, day=mid, step=0.5, linke_value=linke, albedo_value=0.2, overwrite=True)
        rasters.append(nome)

    gs.run_command('r.series', input=rasters, output='annua_avg', method='average', overwrite=True)
    gs.mapcalc('annua_kwh = annua_avg * 0.277778', overwrite=True)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    gs.run_command('r.out.gdal', input='annua_kwh', output=output_tif,
                   format='GTiff', type='Float64', createopt='COMPRESS=DEFLATE', overwrite=True)
    logger.info(f'Raster di irradianza salvato: {output_tif}')
    return output_tif


def calculate_building_irradiance(provincia: str, comune: str, idx_panel: int) -> gpd.GeoDataFrame:
    """Calcola l'offerta energetica per ogni fabbricato e salva shapefile con struttura cartelle coerente."""
    prov_safe = safe_name(provincia)
    com_safe = safe_name(comune)
    raster = os.path.join(OUTPUT_DIR, f'irradianza_annua_{prov_safe}_{com_safe}_kwh.tif')
    shapefolder = os.path.join(FABBRICATI_BASE, f'fabbricati_{prov_safe}_{com_safe}')

    logger.info(f'Calcolo offerta energetica per {provincia}/{comune}')
    shp_list = [f for f in os.listdir(shapefolder) if f.lower().endswith('.shp')]
    if not shp_list:
        raise FileNotFoundError(f'Nessuno shapefile in {shapefolder}')
    shp = os.path.join(shapefolder, shp_list[0])

    gdf = gpd.read_file(shp)
    gdf = reproject_if_needed(rasterio.open(raster).crs, gdf)
    stats = zonal_stats(gdf, raster, stats=['mean'])
    gdf['irr_kwh_m2'] = [s['mean'] for s in stats]
    gdf = gdf[gdf['irr_kwh_m2'] > 0]
    gdf = calcola_area(gdf, nome_colonna='area_mq')

    panel_df = pd.read_csv(PANEL_DATA_PATH, delimiter=';', decimal=',', na_values=['n.a.', 'N.A.', 'na', 'NA', '-', ''])
    for col in ['Potenza (Wp)', 'Efficienza (%)', 'Prezzo', 'Dimensione']:
        panel_df[col] = pd.to_numeric(panel_df[col], errors='coerce')
    panel_df.dropna(subset=['Potenza (Wp)', 'Efficienza (%)', 'Prezzo', 'Dimensione'], inplace=True)
    specs = panel_df.iloc[idx_panel]

    gdf['Ptnz_Wp'] = specs['Potenza (Wp)']
    gdf['Eff_pct'] = specs['Efficienza (%)']
    gdf['Dim_m2'] = specs['Dimensione']
    gdf['Prz_uni'] = specs['Prezzo']
    gdf['num_PV'] = (gdf['area_mq'] / gdf['Dim_m2']).astype(int).clip(lower=0)
    gdf['Prz_tot'] = gdf['num_PV'] * gdf['Prz_uni']
    gdf['Ptnz_tot'] = gdf['Ptnz_Wp'] * gdf['num_PV']
    gdf['Prod_kWh_y'] = gdf['irr_kwh_m2'] * (1 - gdf['Eff_pct']/100) * gdf['Ptnz_Wp'] * gdf['num_PV'] / 1000

    # --- Output coerente: .../shapefiles/salerno_padula/offerta_energetica_salerno_padula/offerta_energetica_salerno_padula.shp
    subdir = f'{prov_safe}_{com_safe}'
    dirname = f'offerta_energetica_{prov_safe}_{com_safe}'
    outdir = os.path.join(SHAPE_OUT_DIR, subdir, dirname)
    os.makedirs(outdir, exist_ok=True)
    outshp = os.path.join(outdir, f'{dirname}.shp')
    gdf.to_file(outshp)
    logger.info(f'Shapefile offerta energetica salvato: {outshp}')
    return gdf


def calcolo_offerta_energetica(provincia: str, comune: str, idx_panel: int):
    """Orchestratore: verifica raster ed esegui calcolo offerta."""
    prov = safe_name(provincia)
    com = safe_name(comune)
    raster = os.path.join(OUTPUT_DIR, f'irradianza_annua_{prov}_{com}_kwh.tif')
    logger.info(f'Avvio orchestrator per offerta energetica {provincia}/{comune}')
    if not os.path.isfile(raster):
        logger.info(f'Raster non trovato ({raster}), avvio pipeline')
        solar_radiation_pipeline(provincia, comune)
    else:
        logger.info(f'Utilizzo raster esistente: {raster}')
    return calculate_building_irradiance(provincia, comune, idx_panel)

def refresh_offerta_energetica(provincia: str, comune: str, idx_panel: int):
    prov = safe_name(provincia)
    com = safe_name(comune)
    raster = os.path.join(OUTPUT_DIR, f'irradianza_annua_{prov}_{com}_kwh.tif')
    solar_radiation_pipeline(provincia, comune)
    return calculate_building_irradiance(provincia, comune, idx_panel)

if __name__ == '__main__':
    # Esempio di esecuzione
    prov, com, idx = 'Salerno', 'Padula', 0
    _ = calcolo_offerta_energetica(prov, com, idx)
    logger.info('Processo completato')
