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
VINCOLI_BASE = os.path.join(BASE_DIR, 'VINCOLI')
DSM_BASE = os.path.join(BASE_DIR, 'input_dsm')
OUTPUT_DIR = os.path.join(BASE_DIR, 'offerta', 'grass_gis', 'irradiance_tif')
SHAPE_OUT_DIR = os.path.join(BASE_DIR, 'Data_Collection', 'shapefiles')
PANEL_DATA_PATH = os.path.join(BASE_DIR, 'offerta', 'panel', 'panels.csv')

def generate_temp_location(epsg, comune, provincia):
    """
    Genera un nome univoco per una location temporanea di GRASS GIS.

    Parametri
    ----------
    epsg : int
        Codice EPSG del sistema di riferimento.
    comune : str
        Nome del comune.
    provincia : str
        Nome della provincia.

    Restituisce
    ----------
    str
        Nome della location temporanea.
    """
    unique = uuid.uuid4().hex[:8]
    return f'tmp_location_{epsg}_{safe_name(comune)}_{safe_name(provincia)}_{unique}'

def create_grass_location(grass_base, gisdb, location, epsg_code) -> None:
    """
    Crea una location GRASS GIS, se non esiste già.

    Parametri
    ----------
    grass_base : str
        Percorso alla directory base di GRASS.
    gisdb : str
        Directory del database GIS.
    location : str
        Nome della location da creare.
    epsg_code : int
        Codice EPSG del sistema di riferimento.

    Restituisce
    ----------
    None

    Solleva
    -------
    subprocess.CalledProcessError
        Se il comando di creazione location fallisce.
    """
    loc_path = os.path.join(gisdb, location)
    if not os.path.exists(loc_path):
        logger.info(f'Creazione GRASS location {location} con EPSG:{epsg_code}')
        grass_bin = os.path.join(grass_base, 'grass84.bat')
        subprocess.run([grass_bin, '-c', f'EPSG:{epsg_code}', '-e', loc_path], check=True)
        logger.info(f"Comando GRASS GIS per creazione location: {grass_bin} -c EPSG:{epsg_code} -e {loc_path}")

def remove_grass_location(grass_gisdb, location_name):
    """
    Rimuove una location GRASS temporanea, se esiste.

    Parametri
    ----------
    grass_gisdb : str
        Directory del database GIS.
    location_name : str
        Nome della location da eliminare.

    Restituisce
    ----------
    None
    """
    import shutil
    loc_path = os.path.join(grass_gisdb, location_name)
    if os.path.exists(loc_path):
        shutil.rmtree(loc_path)
        logger.info(f"Location GRASS temporanea rimossa: {loc_path}")

def init_grass_environment(grass_base, gisdb, location, mapset):
    """
    Inizializza le variabili d'ambiente di GRASS GIS e ritorna il modulo grass.script.

    Parametri
    ----------
    grass_base : str
        Directory base di GRASS.
    gisdb : str
        Database GIS di GRASS.
    location : str
        Nome della location.
    mapset : str
        Nome del mapset.

    Restituisce
    ----------
    grass.script
        Modulo Python di GRASS GIS.
    """
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
    """
    Riproietta il GeoDataFrame sul CRS specificato, se necessario.

    Parametri
    ----------
    src_crs : rasterio.crs.CRS
        CRS di destinazione.
    gdf : geopandas.GeoDataFrame
        GeoDataFrame di input.

    Restituisce
    ----------
    geopandas.GeoDataFrame
        GeoDataFrame proiettato sul CRS richiesto.
    """
    if gdf.crs.to_epsg() != src_crs.to_epsg():
        logger.warning('CRS non corrispondente: eseguo riproiezione vettoriale')
        return gdf.to_crs(src_crs)
    logger.debug('CRS corrispondente: nessuna riproiezione necessaria')
    return gdf

def get_epsg(dem_path: str) -> int:
    """
    Estrae il codice EPSG dal file DEM raster.

    Parametri
    ----------
    dem_path : str
        Percorso al file DEM.

    Restituisce
    ----------
    int
        Codice EPSG del raster.

    Solleva
    -------
    ValueError
        Se il CRS non ha un EPSG associato.
    """
    logger.debug(f'Leggo CRS da DEM: {dem_path}')
    with rasterio.open(dem_path) as src:
        epsg = src.crs.to_epsg()
    if epsg is None:
        logger.error('Impossibile rilevare EPSG dal DEM')
        raise ValueError('EPSG non rilevabile dal DEM')
    logger.info(f'EPSG rilevato dal DEM: {epsg}')
    return epsg

def get_centroid(shp_path: str) -> tuple:
    """
    Restituisce la latitudine e longitudine (WGS84) del centroide geometrico di uno shapefile.

    Parametri
    ----------
    shp_path : str
        Percorso al file shapefile.

    Restituisce
    ----------
    tuple
        Latitudine, longitudine del centroide.
    """
    logger.debug(f'Calcolo centroide per: {shp_path}')
    gdf = gpd.read_file(shp_path)
    gdf = reproject_if_needed(gdf.crs, gdf).to_crs(epsg=4326)
    union_geom = gdf.geometry.union_all()
    centroid = union_geom.centroid
    return centroid.y, centroid.x

def get_linke_turbidity(lat: float, lon: float) -> dict:
    """
    Recupera i valori di Linke Turbidity per ciascun mese in una posizione geografica.

    Parametri
    ----------
    lat : float
        Latitudine.
    lon : float
        Longitudine.

    Restituisce
    ----------
    dict
        Dizionario {mese: valore turbidity}.
    """
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
    """
    Risampia un raster a risoluzione 1x1 metri.

    Parametri
    ----------
    src_path : str
        Percorso al raster di input.
    out_path : str
        Percorso dove salvare il raster risamplato.

    Restituisce
    ----------
    str
        Percorso al raster (risamplato o originale).
    """
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
    """
    Controlla se il raster necessita di essere risamplato a risoluzione 1x1m.

    Parametri
    ----------
    tif_path : str
        Percorso al file raster.

    Restituisce
    ----------
    bool
        True se la risoluzione maggiore di 2m, False altrimenti.
    """
    with rasterio.open(tif_path) as src:
        res_x, res_y = src.res
    return max(res_x, res_y) > 2

def solar_radiation_pipeline(provincia: str, comune: str, location_tmp: str) -> str:
    """
    Esegue l’intera pipeline GRASS GIS per generare il raster annuale di irradianza
    (kWh/m² anno) per tutti i fabbricati del comune/provincia.

    Parametri
    ----------
    provincia : str
        Nome della provincia.
    comune : str
        Nome del comune.
    location_tmp : str
        Nome della location temporanea di GRASS GIS.

    Restituisce
    ----------
    str
        Percorso al raster GTiff annuale di irradianza prodotto.
    """
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

def calculate_building_irradiance(provincia: str, comune: str, idx_panel: int, use_vincoli: bool = True) -> gpd.GeoDataFrame:
    """
    Calcola l'offerta energetica per ogni fabbricato del comune, escludendo quelli nei vincoli.

    Parametri
    ----------
    provincia : str
        Nome della provincia.
    comune : str
        Nome del comune.
    idx_panel : int
        Indice del pannello fotovoltaico da utilizzare.
    use_vincoli : bool, opzionale
        Se True, esclude i fabbricati all’interno dei vincoli.

    Restituisce
    ----------
    geopandas.GeoDataFrame
        GeoDataFrame dei fabbricati con offerta energetica e dettagli pannello.
    """
    prov_safe = safe_name(provincia)
    com_safe = safe_name(comune)
    raster = os.path.join(OUTPUT_DIR, f'irradianza_annua_{prov_safe}_{com_safe}_kwh.tif')
    shapefolder = os.path.join(FABBRICATI_BASE, f'fabbricati_{prov_safe}_{com_safe}')
    vincoli_folder = os.path.join(VINCOLI_BASE, f'vincoli_{prov_safe}_{com_safe}')

    logger.info(f'Calcolo offerta energetica per {provincia}/{comune}')

    # --- Lettura fabbricati
    shp_list = [f for f in os.listdir(shapefolder) if f.lower().endswith('.shp')]
    if not shp_list:
        raise FileNotFoundError(f'Nessuno shapefile in {shapefolder}')
    shp = os.path.join(shapefolder, shp_list[0])
    gdf = gpd.read_file(shp)

    # --- Lettura vincoli (tollerante)
    mask_in_vincolo = pd.Series([False] * len(gdf), index=gdf.index)
    gdf_offerta = gdf.copy()
    if use_vincoli:
        vincoli_esistono = os.path.isdir(vincoli_folder)
        vincoli_list = []
        if vincoli_esistono:
            vincoli_list = [f for f in os.listdir(vincoli_folder) if f.lower().endswith('.shp')]

        if vincoli_list:
            vincoli_shp = os.path.join(vincoli_folder, vincoli_list[0])
            gdf_vincoli = gpd.read_file(vincoli_shp)
            # Allinea CRS tra fabbricati e vincoli (se necessario)
            if gdf.crs != gdf_vincoli.crs:
                logger.info("Allineamento CRS vincoli a quello dei fabbricati")
                gdf_vincoli = gdf_vincoli.to_crs(gdf.crs)
            # Filtra i fabbricati FUORI dai vincoli usando i centroidi
            centroids = gdf.geometry.centroid
            vincoli_union = gdf_vincoli.unary_union
            mask_in_vincolo = centroids.within(vincoli_union)
            gdf_offerta = gdf[~mask_in_vincolo].copy()
        else:
            logger.info("Vincoli non trovati o non richiesti: nessun edificio viene escluso")
    else:
        logger.info("Vincoli ignorati su richiesta utente.")

    # --- Riproiezione per zonal stats (solo se CRS raster diverso)
    raster_crs = rasterio.open(raster).crs
    if gdf_offerta.crs != raster_crs:
        gdf_offerta = reproject_if_needed(raster_crs, gdf_offerta)

    # --- Zonal stats SOLO su edifici FUORI dai vincoli
    stats = zonal_stats(gdf_offerta, raster, stats=['mean'], nodata=0)
    gdf_offerta['irr_kwh_m2'] = [s['mean'] for s in stats]
    gdf_offerta = gdf_offerta[gdf_offerta['irr_kwh_m2'] > 0]
    gdf_offerta = calcola_area(gdf_offerta, nome_colonna='area')

    # --- Carica i dati del pannello
    panel_df = pd.read_csv(PANEL_DATA_PATH, delimiter=',', decimal=',', na_values=['n.a.', 'N.A.', 'na', 'NA', '-', ''])
    for col in ['Potenza (Wp)', 'Efficienza (%)', 'Prezzo', 'Dimensione']:
        panel_df[col] = pd.to_numeric(panel_df[col], errors='coerce')
    panel_df.dropna(subset=['Potenza (Wp)', 'Efficienza (%)', 'Prezzo', 'Dimensione'], inplace=True)
    specs = panel_df.iloc[idx_panel]

    # --- Calcolo offerta energetica SOLO per fabbricati fuori vincoli
    gdf_offerta['Ptnz_Wp'] = specs['Potenza (Wp)']
    gdf_offerta['Eff_pct'] = specs['Efficienza (%)']
    gdf_offerta['Dim_m2'] = specs['Dimensione']
    gdf_offerta['Prz_uni'] = specs['Prezzo']
    gdf_offerta['num_PV'] = (gdf_offerta['area'] / gdf_offerta['Dim_m2']).astype(int).clip(lower=0)
    gdf_offerta['Prz_tot'] = gdf_offerta['num_PV'] * gdf_offerta['Prz_uni']
    gdf_offerta['Ptnz_tot'] = gdf_offerta['Ptnz_Wp'] * gdf_offerta['num_PV']
    gdf_offerta['Prod_kWh_y'] = gdf_offerta['irr_kwh_m2'] * (1 - gdf_offerta['Eff_pct'] / 100) * gdf_offerta['Ptnz_Wp'] * gdf_offerta['num_PV'] / 1000

    # --- Costruzione gdf finale: unisci i fabbricati filtrati e quelli dentro i vincoli con valori a 0
    float_cols = ['irr_kwh_m2', 'area', 'Ptnz_Wp', 'Eff_pct', 'Dim_m2', 'Prz_uni', 'Prz_tot', 'Ptnz_tot', 'Prod_kWh_y']
    int_cols = ['num_PV']

    # Inizializza le colonne col tipo corretto
    for col in float_cols:
        if col not in gdf.columns:
            gdf[col] = 0.0
    for col in int_cols:
        if col not in gdf.columns:
            gdf[col] = 0

    # Aggiorna i valori SOLO per quelli FUORI dai vincoli
    gdf.loc[gdf_offerta.index, float_cols] = gdf_offerta[float_cols].astype(float)
    gdf.loc[gdf_offerta.index, int_cols] = gdf_offerta[int_cols].astype(int)

    # --- Salva risultato
    subdir = f'{prov_safe}_{com_safe}'
    dirname = f'offerta_energetica_{prov_safe}_{com_safe}'
    outdir = os.path.join(SHAPE_OUT_DIR, subdir, dirname)
    if os.path.exists(outdir):
        shutil.rmtree(outdir)
    os.makedirs(outdir)
    outgpkg = os.path.join(outdir, f'{dirname}.gpkg')
    gdf.to_file(outgpkg, driver='GPKG')
    logger.info(f'gpkg offerta energetica salvato: {outgpkg}')
    return gdf

def safe_building_irradiance(provincia: str, comune: str, idx_panel: int, pipeline_func=None, use_vincoli: bool = True):
    """
    Calcola l'offerta energetica per ogni fabbricato, rilanciando la pipeline se il risultato è vuoto.
    Tenta max 2 volte.

    Parametri
    ----------
    provincia : str
        Nome della provincia.
    comune : str
        Nome del comune.
    idx_panel : int
        Indice del pannello fotovoltaico da utilizzare.
    pipeline_func : callable, opzionale
        Funzione da chiamare per rigenerare i dati se necessario.
    use_vincoli : bool, opzionale
        Se True, esclude i fabbricati all’interno dei vincoli.

    Restituisce
    ----------
    geopandas.GeoDataFrame
        GeoDataFrame con l’offerta energetica.

    Solleva
    -------
    RuntimeError
        Se il calcolo non restituisce dati validi dopo 2 tentativi.
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
        gdf = calculate_building_irradiance(provincia, comune, idx_panel, use_vincoli=use_vincoli)
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

def calcolo_offerta_energetica(provincia: str, comune: str, idx_panel: int, use_vincoli: bool = True):
    """
    Orchestratore principale: aggiorna il raster di irradianza se serve e calcola l’offerta energetica.

    Parametri
    ----------
    provincia : str
        Nome della provincia.
    comune : str
        Nome del comune.
    idx_panel : int
        Indice del pannello da utilizzare.
    use_vincoli : bool, opzionale
        Se True, esclude i fabbricati nei vincoli.

    Restituisce
    ----------
    geopandas.GeoDataFrame
        GeoDataFrame con l’offerta energetica.

    Solleva
    -------
    Propaga eventuali errori dalle pipeline sottostanti.
    """
    prov = safe_name(provincia)
    com = safe_name(comune)
    raster = os.path.join(OUTPUT_DIR, f'irradianza_annua_{prov}_{com}_kwh.tif')
    dem = os.path.join(DSM_BASE, f'DSM_{prov}_{com}.tif')

    # Prima controlla se esiste il DSM
    dem_exists = os.path.isfile(dem)
    raster_exists = os.path.isfile(raster)
    raster_empty = raster_is_empty(raster) if raster_exists else True

    epsg = get_epsg(dem) if dem_exists else None
    location_tmp = None

    try:
        # Caso 1: DSM esiste → se raster mancante/vuoto, rigeneralo
        if dem_exists:
            if (not raster_exists) or raster_empty:
                location_tmp = generate_temp_location(epsg, comune, provincia)
                logger.info(f'Creo location temporanea: {location_tmp}')
                solar_radiation_pipeline(provincia, comune, location_tmp)
        # Caso 2: DSM non esiste → NON tentare nessuna rigenerazione, usa solo quello che c'è
        gdf = safe_building_irradiance(provincia, comune, idx_panel,
                                       pipeline_func=lambda p, c: solar_radiation_pipeline(p, c, location_tmp),
                                       use_vincoli=use_vincoli)
        # Successo: elimina la location temporanea se creata
        if location_tmp:
            remove_grass_location(GRASS_GISDB, location_tmp)
        return gdf
    except Exception as e:
        # Pulisci la location temporanea anche in caso di errore
        if location_tmp:
            remove_grass_location(GRASS_GISDB, location_tmp)
        raise

def refresh_offerta_energetica(provincia: str, comune: str, idx_panel: int, use_vincoli: bool = True):
    """
    Rigenera da zero il raster di irradianza e tutti i dati di offerta energetica per il comune specificato.

    Parametri
    ----------
    provincia : str
        Nome della provincia.
    comune : str
        Nome del comune.
    idx_panel : int
        Indice del pannello da utilizzare.
    use_vincoli : bool, opzionale
        Se True, esclude i fabbricati nei vincoli.

    Restituisce
    ----------
    geopandas.GeoDataFrame
        GeoDataFrame con l’offerta energetica aggiornata.
    """
    prov = safe_name(provincia)
    com = safe_name(comune)
    dem = os.path.join(DSM_BASE, f'DSM_{prov}_{com}.tif')
    epsg = get_epsg(dem)
    location_tmp = generate_temp_location(epsg, comune, provincia)
    try:
        logger.info(f"Refresh completo dell’offerta energetica per {provincia}/{comune} (location: {location_tmp})")
        solar_radiation_pipeline(provincia, comune, location_tmp)
        gdf = safe_building_irradiance(provincia, comune, idx_panel, pipeline_func=lambda p, c: solar_radiation_pipeline(p, c, location_tmp), use_vincoli=use_vincoli)
        remove_grass_location(GRASS_GISDB, location_tmp)
        return gdf
    except Exception as e:
        remove_grass_location(GRASS_GISDB, location_tmp)
        raise