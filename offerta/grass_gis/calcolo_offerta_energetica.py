import os
import shutil
import sys
import subprocess
import logging
import uuid
import rasterio
from rasterio.enums import Resampling
import geopandas as gpd
import calendar
import pandas as pd
from pvlib.clearsky import lookup_linke_turbidity
from rasterstats import zonal_stats
from data_extraction.calcola_area_poligoni import calcola_area
from utils import safe_name, configure_logging_if_main, load_dot_env, raster_is_empty

# CONFIGURAZIONE LOG
logger = logging.getLogger(__name__)

# Directory base del progetto (una volta per tutte)
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

# Carica configurazioni da .env
load_dot_env(os.path.join(BASE_DIR, '.env'))
GRASS_BASE = os.getenv('GRASS_BASE')
GRASS_GISDB = os.getenv('GRASS_GISDB')
GRASS_MAPSET = os.getenv('GRASS_MAPSET', 'PERMANENT')

# Directory di input/output fissi
FABBRICATI_BASE = os.path.join(BASE_DIR, 'FABBRICATI')
DSM_BASE = os.path.join(BASE_DIR, 'input_dsm')
OUTPUT_DIR = os.path.join(BASE_DIR, 'offerta', 'grass_gis', 'irradiance_tif')
SHAPE_OUT_DIR = os.path.join(BASE_DIR, 'Data_Collection', 'shapefiles')
PANEL_DATA_PATH = os.path.join(BASE_DIR, 'offerta', 'panel', 'panels.csv')

def generate_temp_location(epsg, comune, provincia):
    unique = uuid.uuid4().hex[:8]
    return f'tmp_location_{epsg}_{safe_name(comune)}_{safe_name(provincia)}_{unique}'

def create_grass_location(grass_base, gisdb, location, epsg_code) -> None:
    """Crea una location GRASS se non esiste."""
    loc_path = os.path.join(gisdb, location)
    if not os.path.exists(loc_path):
        logger.info(f'Creazione GRASS location {location} con EPSG:{epsg_code}')
        grass_bin = os.path.join(grass_base, 'grass84.bat')
        subprocess.run([grass_bin, '-c', f'EPSG:{epsg_code}', '-e', loc_path], check=True)
        logger.info(f"Comando GRASS GIS per creazione location: {grass_bin} -c EPSG:{epsg_code} -e {loc_path}")

def remove_grass_location(grass_gisdb, location_name):
    import shutil
    loc_path = os.path.join(grass_gisdb, location_name)
    if os.path.exists(loc_path):
        shutil.rmtree(loc_path)
        logger.info(f"Location GRASS temporanea rimossa: {loc_path}")

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
    times = pd.to_datetime(['2021-01-01'] * 12) + pd.to_timedelta([d - 1 for d in mid_days], 'D')
    turb = lookup_linke_turbidity(times.tz_localize('UTC'), lat, lon)
    vals = {i + 1: float(v) for i, v in enumerate(turb.values)}
    logger.info(f'Turbidity Linke per mesi: {vals}')
    return vals

def resample_dsm_to_1x1(src_path, out_path):
    with rasterio.open(src_path) as src:
        res_x, res_y = src.res  # tuple (xres, yres)
        if max(res_x, res_y) <= 2:
            # No resampling needed
            print(f"Nessun resampling: il DSM '{os.path.basename(src_path)}' ha risoluzione {res_x}x{res_y} m <= 2 m.")
            return src_path  # return original DSM path
        # Calculate new shape
        scale_x = res_x / 1.0
        scale_y = res_y / 1.0
        new_width = int(src.width * scale_x)
        new_height = int(src.height * scale_y)
        print(f"Attenzione: il DSM '{os.path.basename(src_path)}' ha risoluzione {res_x}x{res_y} m: lo risampio a 1x1 m...")
        # Prepare destination dataset
        kwargs = src.meta.copy()
        kwargs.update({
            'height': new_height,
            'width': new_width,
            'transform': src.transform * src.transform.scale(
                (src.width / new_width),
                (src.height / new_height)
            )
        })
        with rasterio.open(out_path, 'w', **kwargs) as dst:
            for i in range(1, src.count + 1):
                data = src.read(
                    i,
                    out_shape=(new_height, new_width),
                    resampling=Resampling.bilinear  # or Resampling.cubic for smoother results
                )
                dst.write(data, i)
        return out_path

def needs_resampling_to_1x1(tif_path):
    with rasterio.open(tif_path) as src:
        res_x, res_y = src.res
    return max(res_x, res_y) > 2

def solar_radiation_pipeline(provincia: str, comune: str, location_tmp: str) -> str:
    """Genera il raster annuale di irradianza in kWh, resampling solo sull'output finale."""
    prov_safe = safe_name(provincia)
    com_safe = safe_name(comune)
    output_tif = os.path.join(OUTPUT_DIR, f'irradianza_annua_{prov_safe}_{com_safe}_kwh.tif')
    output_tif_1x1 = os.path.join(OUTPUT_DIR, f'irradianza_annua_{prov_safe}_{com_safe}_kwh_1x1.tif')
    dem = os.path.join(DSM_BASE, f'DSM_{prov_safe}_{com_safe}.tif')
    shapefolder = os.path.join(FABBRICATI_BASE, f'fabbricati_{prov_safe}_{com_safe}')

    logger.info(f'Avvio pipeline solare per {provincia}/{comune}')
    shp_list = [f for f in os.listdir(shapefolder) if f.lower().endswith('.shp')]
    if not shp_list:
        raise FileNotFoundError(f'Nessuno shapefile in {shapefolder}')
    shp = os.path.join(shapefolder, shp_list[0])

    epsg = get_epsg(dem)
    create_grass_location(GRASS_BASE, GRASS_GISDB, location_tmp, epsg)
    gs = init_grass_environment(GRASS_BASE, GRASS_GISDB, location_tmp, GRASS_MAPSET)

    lat, lon = get_centroid(shp)
    turb_by_month = get_linke_turbidity(lat, lon)

    gs.run_command('r.import', input=dem, output='dem', overwrite=True)
    gs.run_command('r.slope.aspect', elevation='dem', slope='slope', aspect='aspect', overwrite=True)
    gs.run_command('v.import', input=shp, output='fabbricati', overwrite=True)
    gs.run_command('v.build', map='fabbricati')

    bbox_fab = gs.parse_command('v.info', map='fabbricati', flags='g')
    bbox_dem = gs.parse_command('r.info', map='dem', flags='g')

    n = min(float(bbox_fab['north']), float(bbox_dem['north']))
    s = max(float(bbox_fab['south']), float(bbox_dem['south']))
    e = min(float(bbox_fab['east']), float(bbox_dem['east']))
    w = max(float(bbox_fab['west']), float(bbox_dem['west']))

    gs.run_command('g.region', n=n, s=s, e=e, w=w, align='dem', res=2)

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
    # Esporta GTiff a risoluzione nativa (es: 10x10)
    gs.run_command('r.out.gdal', input='annua_kwh', output=output_tif,
                   format='GTiff', type='Float64', createopt='COMPRESS=DEFLATE', overwrite=True)
    logger.info(f'Raster di irradianza salvato: {output_tif}')

    if needs_resampling_to_1x1(output_tif):
        logger.info(f"Eseguo resampling raster irradianza da {output_tif} a risoluzione 1x1m...")
        resample_dsm_to_1x1(output_tif, output_tif_1x1)
        # Elimina il vecchio file e rinomina quello nuovo
        try:
            os.remove(output_tif)
            logger.info(f"File originale {output_tif} eliminato.")
        except Exception as e:
            logger.warning(f"Impossibile eliminare {output_tif}: {e}")
        try:
            os.rename(output_tif_1x1, output_tif)
            logger.info(f"File risamplato rinominato come {output_tif}")
        except Exception as e:
            logger.error(f"Impossibile rinominare {output_tif_1x1} in {output_tif}: {e}")
    else:
        logger.info("Nessun resampling necessario sull’output finale.")

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

    panel_df = pd.read_csv(PANEL_DATA_PATH, delimiter=',', decimal=',', na_values=['n.a.', 'N.A.', 'na', 'NA', '-', ''])
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
    gdf['Prod_kWh_y'] = gdf['irr_kwh_m2'] * (1 - gdf['Eff_pct'] / 100) * gdf['Ptnz_Wp'] * gdf['num_PV'] / 1000

    subdir = f'{prov_safe}_{com_safe}'
    dirname = f'offerta_energetica_{prov_safe}_{com_safe}'
    outdir = os.path.join(SHAPE_OUT_DIR, subdir, dirname)
    if os.path.exists(outdir):
        shutil.rmtree(outdir)
    os.makedirs(outdir)
    outshp = os.path.join(outdir, f'{dirname}.shp')
    gdf.to_file(outshp)
    logger.info(f'Shapefile offerta energetica salvato: {outshp}')
    return gdf

def safe_building_irradiance(provincia: str, comune: str, idx_panel: int, pipeline_func=None):
    """
    Calcola l'offerta energetica per ogni fabbricato, rilanciando la pipeline se il risultato è vuoto.
    pipeline_func: funzione da chiamare per rigenerare i dati se necessario (es: solar_radiation_pipeline).
    Max 2 tentativi; se ancora vuoto solleva RuntimeError.
    """
    tentativi = 2
    prov_safe = safe_name(provincia)
    com_safe = safe_name(comune)
    raster = os.path.join(OUTPUT_DIR, f'irradianza_annua_{prov_safe}_{com_safe}_kwh.tif')
    for i in range(tentativi):
        if pipeline_func and i > 0:
            logger.info(f"Rilancio pipeline per {provincia}/{comune} (tentativo {i + 1})")
            pipeline_func(provincia, comune)
        # Primo controllo: raster contiene solo NaN?
        if not os.path.exists(raster) or raster_is_empty(raster):
            logger.warning(f"Il raster prodotto è vuoto (tentativo {i + 1}/{tentativi}).")
            continue  # rilancia la pipeline o tenta di nuovo
        gdf = calculate_building_irradiance(provincia, comune, idx_panel)
        # Secondo controllo: GeoDataFrame vuoto?
        if not gdf.empty:
            return gdf
        logger.warning(f"L'offerta energetica calcolata è vuota (tentativo {i + 1}/{tentativi}).")
        if pipeline_func is None:
            break  # Se non posso rilanciare la pipeline, non ha senso continuare
    logger.error(f"Offerta energetica vuota anche dopo {tentativi} tentativi per {provincia}/{comune}.")
    raise RuntimeError(
        f"Offerta energetica vuota anche dopo {tentativi} tentativi! Verificare input e pipeline per {provincia}/{comune}."
    )

def calcolo_offerta_energetica(provincia: str, comune: str, idx_panel: int):
    """
    Orchestratore: se serve aggiorna raster con location temporanea, poi esegue calcolo offerta.
    """
    prov = safe_name(provincia)
    com = safe_name(comune)
    raster = os.path.join(OUTPUT_DIR, f'irradianza_annua_{prov}_{com}_kwh.tif')
    dem = os.path.join(DSM_BASE, f'DSM_{prov}_{com}.tif')
    epsg = get_epsg(dem)

    # Valuta se serve rigenerare il raster
    raster_da_rifare = (not os.path.isfile(raster)) or raster_is_empty(raster)
    location_tmp = None

    try:
        if raster_da_rifare:
            location_tmp = generate_temp_location(epsg, comune, provincia)
            logger.info(f'Creo location temporanea: {location_tmp}')
            solar_radiation_pipeline(provincia, comune, location_tmp)  # passa la location come parametro!
        gdf = safe_building_irradiance(provincia, comune, idx_panel, pipeline_func=lambda p, c: solar_radiation_pipeline(p, c, location_tmp))
        # Successo: elimina subito la location temporanea
        if location_tmp:
            remove_grass_location(GRASS_GISDB, location_tmp)
        return gdf
    except Exception as e:
        # Se fallisce, elimina comunque la location temporanea dopo il secondo tentativo
        if location_tmp:
            remove_grass_location(GRASS_GISDB, location_tmp)
        raise


def refresh_offerta_energetica(provincia: str, comune: str, idx_panel: int):
    prov = safe_name(provincia)
    com = safe_name(comune)
    dem = os.path.join(DSM_BASE, f'DSM_{prov}_{com}.tif')
    epsg = get_epsg(dem)
    location_tmp = generate_temp_location(epsg, comune, provincia)
    try:
        logger.info(f"Refresh completo dell’offerta energetica per {provincia}/{comune} (location: {location_tmp})")
        solar_radiation_pipeline(provincia, comune, location_tmp)
        gdf = safe_building_irradiance(provincia, comune, idx_panel, pipeline_func=lambda p, c: solar_radiation_pipeline(p, c, location_tmp))
        remove_grass_location(GRASS_GISDB, location_tmp)
        return gdf
    except Exception as e:
        remove_grass_location(GRASS_GISDB, location_tmp)
        raise

if __name__ == '__main__':
    # Esempio di esecuzione
    # Abilita logging solo se eseguito standalone
    configure_logging_if_main(__name__)
    prov, com, idx = 'Salerno', 'padula', 0
    _ = calcolo_offerta_energetica(prov, com, idx)
    logger.info('Processo completato')