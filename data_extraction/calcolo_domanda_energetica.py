import os
import shutil
import pandas as pd
import geopandas as gpd
import logging

from geopandas import GeoDataFrame

from data_extraction.estrazione_dati_basi_territoriali import get_geom_basi_territoriali
from data_extraction.join_data_normattiva_varcens_basiterr import get_join_data
from data_extraction.siape import get_dati_siape
from data_extraction.calcola_area_poligoni import calcola_area
from data_extraction.interrogazione_wfs_catastale import get_dati_catasto
from utils import safe_name, get_regione_from_provincia, configure_logging_if_main

logger = logging.getLogger(__name__)

# =============================================================================
# FUNZIONI DI UTILITY
# =============================================================================

def filtra_df_comune(df_join, comune, provincia):
    """
        Filtra il DataFrame joinato per il comune e la provincia specificati (in forma normalizzata).

        Parametri
        ----------
        df_join : pd.DataFrame
            DataFrame contenente almeno le colonne 'COMUNE' e 'PROVINCIA'.
        comune : str
            Nome normalizzato del comune da selezionare.
        provincia : str
            Nome normalizzato della provincia da selezionare.

        Restituisce
        ----------
        pd.DataFrame
            DataFrame filtrato sul solo comune richiesto.

        Solleva
        -------
        ValueError
            Se non sono presenti dati per la combinazione richiesta.
        """
    df_join['_COMUNE_NORM'] = df_join['COMUNE'].astype(str).apply(safe_name)
    df_join['_PROVINCIA_NORM'] = df_join['PROVINCIA'].astype(str).apply(safe_name)
    df_comune = df_join[
        (df_join['_COMUNE_NORM'] == comune) &
        (df_join['_PROVINCIA_NORM'] == provincia)
    ]
    df_join.drop(columns=['_COMUNE_NORM', '_PROVINCIA_NORM'], inplace=True)
    if df_comune.empty:
        raise ValueError(f"Nessun dato trovato per il comune {comune} nella provincia {provincia}.")
    return df_comune

def estrai_zona_climatica(df_comune, df_siape, comune):
    """
    Estrae la zona climatica unica del comune dal DataFrame e restituisce
    anche il sottoinsieme dei dati SIAPE per quella zona.

    Parametri
    ----------
    df_comune : pd.DataFrame
        DataFrame filtrato per il comune.
    df_siape : pd.DataFrame
        DataFrame con i dati SIAPE per tutte le zone climatiche.
    comune : str
        Nome del comune.

    Restituisce
    ----------
    tuple
        (zona_climatica, df_siape_filtrato) per il comune.

    Solleva
    -------
    ValueError
        Se la zona climatica è ambigua o mancante, o se non ci sono dati SIAPE per la zona.
    """
    zc = df_comune['ZONA_CLIMATICA'].dropna().unique()
    if len(zc) != 1:
        raise ValueError(f"Zona climatica ambigua o mancante per {comune}. Valori trovati: {zc}")
    zc = zc[0]
    df_zc = df_siape[df_siape['zona_climatica'] == zc]
    if df_zc.empty:
        raise ValueError(f"Nessun dato SIAPE per la zona climatica {zc}")
    return zc, df_zc

def trova_range(valore, ranges):
    """
    Trova l'intervallo testuale in cui cade il valore, tra quelli forniti (formato: '<50', '50-100', '>5000').

    Parametri
    ----------
    valore : float
        Valore numerico da classificare.
    ranges : list of str
        Lista di intervalli testuali.

    Restituisce
    ----------
    str or None
        L'intervallo in cui cade il valore, oppure None se non trovato.
    """
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

def join_fabbricati_sezione(provincia: str, gdf_fabbricati: gpd.GeoDataFrame) -> pd.DataFrame:
    """
    Associa ogni fabbricato del GeoDataFrame a una sezione censuaria tramite spatial join sui centroidi.

    Parametri
    ----------
    provincia : str
        Nome della provincia dei fabbricati.
    gdf_fabbricati : gpd.GeoDataFrame
        GeoDataFrame con geometrie e colonna 'ID_FAB'.

    Restituisce
    ----------
    pd.DataFrame
        DataFrame con colonne 'ID_FAB' e 'SEZ2011' di appartenenza.
    """
    # Ottieni regione dalla provincia
    regione = get_regione_from_provincia(safe_name(provincia))
    # Carica le sezioni censuarie
    gdf_sezioni = get_geom_basi_territoriali(regione)

    # Controlla CRS e portali uguali se necessario
    if gdf_fabbricati.crs != gdf_sezioni.crs:
        crs_orig = gdf_fabbricati.crs
        gdf_fabbricati = gdf_fabbricati.to_crs(gdf_sezioni.crs)
    else:
        crs_orig = None

    # Usa i centroidi dei fabbricati
    gdf_centroidi = gdf_fabbricati.copy()
    gdf_centroidi['geometry'] = gdf_centroidi.geometry.centroid

    # Spatial join tra centroidi e sezioni
    joined = gpd.sjoin(
        gdf_centroidi[['ID_FAB', 'geometry']],
        gdf_sezioni[['SEZ2011', 'geometry']],
        how='inner',
        predicate='within'
    )
    # Il risultato contiene ID_FAB fabbricati e SEZ2011 sezione di appartenenza
    result = joined[['ID_FAB', 'SEZ2011']].reset_index(drop=True)

    # Ripristina CRS originale se necessario
    if crs_orig:
        gdf_fabbricati = gdf_fabbricati.to_crs(crs_orig)

    return result

# =============================================================================
# FUNZIONI DI CALCOLO COEFFICIENTI (INVARIATE)
# =============================================================================

def calcola_coefficiente_domanda_zc_range(
    gdf_fabbricati: gpd.GeoDataFrame,
    df_join: pd.DataFrame,
    df_siape: pd.DataFrame,
    comune: str,
    provincia: str
) -> gpd.GeoDataFrame:
    """
    Calcola e assegna il coefficiente di domanda energetica (coeff_dom) per fabbricato,
    secondo il modello SIAPE aggregato per zona climatica e periodo edilizio.

    Parametri
    ----------
    gdf_fabbricati : gpd.GeoDataFrame
        GeoDataFrame dei fabbricati.
    df_join : pd.DataFrame
        DataFrame joinato con info sezione e anagrafiche.
    df_siape : pd.DataFrame
        DataFrame SIAPE della zona climatica.
    comune : str
        Nome del comune.
    provincia : str
        Nome della provincia.

    Restituisce
    ----------
    gpd.GeoDataFrame
        GeoDataFrame con nuova colonna 'coeff_dom'.
    """
    logger.info(f"Calcolo coefficiente domanda per {comune} ({provincia})...")

    # Estrai le sezioni per ogni fabbricato
    df_ID_FAB_sez = join_fabbricati_sezione(provincia, gdf_fabbricati)  # ID_FAB, SEZ2011

    # Filtra il join solo per il comune di interesse
    df_comune = filtra_df_comune(df_join, comune, provincia)

    # Estrai la zona climatica
    zc, df_zc = estrai_zona_climatica(df_comune, df_siape, comune)

    # Calcola coeff_dom_sez per ogni sezione del comune
    sezioni = df_comune['SEZ2011'].unique()
    lista = []
    for sez in sezioni:
        row = df_comune[df_comune['SEZ2011'] == sez]
        if row.empty:
            continue
        # Somma i gruppi (prendi la prima riga, se per caso ce ne fossero più di una per sezione)
        r = row.iloc[0]
        b1 = r.get('E8', 0) + r.get('E9', 0)
        b2 = r.get('E10', 0) + r.get('E11', 0)
        b3 = r.get('E12', 0) + r.get('E13', 0)
        b4 = r.get('E14', 0) + r.get('E15', 0)
        b5 = r.get('E16', 0)
        totale_edifici = b1 + b2 + b3 + b4 + b5
        if totale_edifici == 0:
            coeff_dom_sez = 0
        else:
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

            coeff_dom_sez = (
                (b1 * epgl_nren_1 + b2 * epgl_nren_2 + b3 * epgl_nren_3 +
                 b4 * epgl_nren_4 + b5 * epgl_nren_5) / totale_edifici
            )
        lista.append({'SEZ2011': sez, 'coeff_dom_sez': round(coeff_dom_sez, 2)})

    df_coeff_sez = pd.DataFrame(lista)

    # Join tra ID_FAB, SEZ2011 e coeff_dom_sez
    df_ID_FAB_sez = df_ID_FAB_sez.merge(df_coeff_sez, on='SEZ2011', how='left')

    # Assegna coeff_dom a gdf_fabbricati in base al ID_FAB
    gdf_fabbricati = gdf_fabbricati.copy()
    gdf_fabbricati = gdf_fabbricati.merge(df_ID_FAB_sez[['ID_FAB', 'coeff_dom_sez']], on='ID_FAB', how='left')
    gdf_fabbricati['coeff_dom'] = gdf_fabbricati['coeff_dom_sez'].fillna(0)
    gdf_fabbricati.drop(columns=['coeff_dom_sez'], inplace=True)

    return gdf_fabbricati

def calcola_coefficiente_domanda_zc_suris_volris(
    gdf_fabbricati: gpd.GeoDataFrame,
    df_join: pd.DataFrame,
    df_siape: pd.DataFrame,
    comune: str,
    provincia: str
) -> gpd.GeoDataFrame:
    """
    Calcola e assegna il coefficiente di domanda energetica per fabbricato,
    secondo il modello SIAPE raggruppato per zona climatica, superficie e volume riscaldato.

    Parametri
    ----------
    gdf_fabbricati : gpd.GeoDataFrame
        GeoDataFrame dei fabbricati.
    df_join : pd.DataFrame
        DataFrame joinato con info sezione e anagrafiche.
    df_siape : pd.DataFrame
        DataFrame SIAPE della zona climatica.
    comune : str
        Nome del comune.
    provincia : str
        Nome della provincia.

    Restituisce
    ----------
    gpd.GeoDataFrame
        GeoDataFrame con nuova colonna 'coeff_dom'.
    """
    logger.info(f"Calcolo coefficiente domanda per {comune} ({provincia})...")

    df_comune = filtra_df_comune(df_join, comune, provincia)

    zc, df_zc = estrai_zona_climatica(df_comune, df_siape, comune)

    suris_ranges = list(df_zc['suris_range'].unique())
    volris_ranges = list(df_zc['volris_range'].unique())

    def trova_epgl_robusto(sur_range, vol_range):
        # Cerca con entrambi
        riga = df_zc[
            (df_zc['suris_range'] == sur_range) & (df_zc['volris_range'] == vol_range)
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
            logger.warning(f"Range non trovato per fabbricato ID_FAB={row.get('ID_FAB', idx)}: sup_risc={sup}, vol_risc={vol}")
            coeff_dom_list.append(None)
            continue
        coeff = trova_epgl_robusto(range_sur, range_vol)
        coeff_dom_list.append(coeff)

    gdf_fabbricati['coeff_dom'] = coeff_dom_list
    return gdf_fabbricati

def calcola_coefficiente_domanda_zc_suris_volris_supdi(
    gdf_fabbricati: gpd.GeoDataFrame,
    df_join: pd.DataFrame,
    df_siape: pd.DataFrame,
    comune: str,
    provincia: str
) -> gpd.GeoDataFrame:
    """
    Calcola e assegna il coefficiente di domanda energetica per fabbricato,
    secondo il modello SIAPE raggruppato per zona climatica, superficie riscaldata, volume riscaldato e superficie disperdente.

    Parametri
    ----------
    gdf_fabbricati : gpd.GeoDataFrame
        GeoDataFrame dei fabbricati.
    df_join : pd.DataFrame
        DataFrame joinato con info sezione e anagrafiche.
    df_siape : pd.DataFrame
        DataFrame SIAPE della zona climatica.
    comune : str
        Nome del comune.
    provincia : str
        Nome della provincia.

    Restituisce
    ----------
    gpd.GeoDataFrame
        GeoDataFrame con nuova colonna 'coeff_dom'.
    """
    logger.info(f"Calcolo coefficiente domanda con supdi per {comune} ({provincia})...")

    df_comune = filtra_df_comune(df_join, comune, provincia)

    zc, df_zc = estrai_zona_climatica(df_comune, df_siape, comune)

    suris_ranges = list(df_zc['suris_range'].unique())
    volris_ranges = list(df_zc['volris_range'].unique())
    supdi_ranges = list(df_zc['supdi_range'].unique())

    def trova_epgl_fallback(sur_range, vol_range, supdi_range):
        # 1. zona_climatica;suris_range;volris_range;supdi_range;
        riga = df_zc[
            (df_zc['suris_range'] == sur_range) & (df_zc['volris_range'] == vol_range) & (df_zc['supdi_range'] == supdi_range)
        ]
        if not riga.empty:
            coeff = riga.iloc[0]['EPgl_nren']
            if coeff != 0:
                return coeff

        # 2. zona_climatica;suris_range;volris_range;
        riga = df_zc[
            (df_zc['suris_range'] == sur_range) & (df_zc['volris_range'] == vol_range)
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
                f"Range non trovato per fabbricato ID_FAB={row.get('ID_FAB', idx)}: "
                f"sup_risc={sup}, vol_risc={vol}, sup_disp={supdi}")
            coeff_dom_list.append(None)
            continue
        coeff = trova_epgl_fallback(range_sur, range_vol, range_supdi)
        coeff_dom_list.append(coeff)

    gdf_fabbricati['coeff_dom'] = coeff_dom_list
    return gdf_fabbricati

# =============================================================================
# FUNZIONE DI CALCOLO UNIFICATA
# =============================================================================

def calcola_domanda_energetica(
    comune: str,
    provincia: str,
    fabbricati_tipo: str
) -> gpd.GeoDataFrame:
    """
    Calcola la domanda energetica per tutti i fabbricati di un comune e provincia,
    secondo la tipologia di aggregazione SIAPE specificata.

    Parametri
    ----------
    comune : str
        Nome del comune.
    provincia : str
        Nome della provincia.
    fabbricati_tipo : str
        Tipo di aggregazione SIAPE ("zc_range", "zc_suris_volris", "zc_suris_volris_supdi").

    Restituisce
    ----------
    gpd.GeoDataFrame
        GeoDataFrame dei fabbricati arricchito con le colonne 'coeff_dom' e 'domanda_en'.
    """
    logger.info(f"Inizio calcolo domanda energetica [{fabbricati_tipo}]...")

    _COEFF_FUNCS = {
        "zc_range": calcola_coefficiente_domanda_zc_range,
        "zc_suris_volris": calcola_coefficiente_domanda_zc_suris_volris,
        "zc_suris_volris_supdi": calcola_coefficiente_domanda_zc_suris_volris_supdi,
    }
    _SIAPE_KEYS = {
        "zc_range": "zc_range",
        "zc_suris_volris": "zc_suris_volris",
        "zc_suris_volris_supdi": "zc_suris_volris_supdi",
    }

    if fabbricati_tipo not in _COEFF_FUNCS:
        raise ValueError(f"Tipologia fabbricati non riconosciuta: {fabbricati_tipo}")

    coeff_func = _COEFF_FUNCS[fabbricati_tipo]
    siape_key = _SIAPE_KEYS[fabbricati_tipo]

    return _calcola_domanda_energetica_impl(comune, provincia, siape_key, coeff_func)

# =============================================================================
# IMPLEMENTAZIONE PRIVATA, LOGICA INVARIATA
# =============================================================================

def _calcola_domanda_energetica_impl(
    comune: str,
    provincia: str,
    siape_key: str,
    coeff_func,
) -> GeoDataFrame | None:
    """
    Implementazione interna per il calcolo della domanda energetica su tutti i fabbricati,
    per comune e provincia, data la funzione di calcolo coefficiente e la chiave SIAPE.

    Parametri
    ----------
    comune : str
        Nome del comune.
    provincia : str
        Nome della provincia.
    siape_key : str
        Chiave SIAPE da usare per il caricamento dati.
    coeff_func : callable
        Funzione di calcolo del coefficiente da applicare ai fabbricati.

    Restituisce
    ----------
    gpd.GeoDataFrame o None
        GeoDataFrame dei fabbricati arricchito, o None in caso di errore.
    """
    logger.info(f"Inizio calcolo domanda energetica...")

    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    PROJECT_ROOT = os.path.normpath(os.path.join(BASE_DIR, ".."))

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
    out_gpkg = os.path.join(out_dir, f"{dirname}.gpkg")

    # Calcolo/assegnazione coefficiente
    gdf_fabbricati = coeff_func(gdf_fabbricati, df_join, df_siape, comm_safe, prov_safe)

    gdf_fabbricati['domanda_en'] = gdf_fabbricati['area'] * gdf_fabbricati['coeff_dom']

    if siape_key == "zc_range":
        # Salva gpkg SOLO per edifici con domanda_en == 0
        gdf_zero = gdf_fabbricati[gdf_fabbricati['domanda_en'] == 0].copy()
        out_dir_zero = os.path.normpath(
            os.path.join(PROJECT_ROOT, "Data_Collection", "shapefiles", subdir, dirname + "_zero"))
        if os.path.exists(out_dir_zero):
            shutil.rmtree(out_dir_zero)
        os.makedirs(out_dir_zero)
        out_gpkg_zero = os.path.join(out_dir_zero, f"{dirname}_zero.gpkg")
        if not gdf_zero.empty:
            gdf_zero.to_file(out_gpkg_zero, driver='GPKG')
            logger.info(f"gpkg con domanda_en=0 salvato in {out_gpkg_zero} ({len(gdf_zero)} edifici)")
        else:
            logger.info("Nessun edificio con domanda_en=0 da salvare in gpkg separato.")

        n_totale = len(gdf_fabbricati)
        gdf_fabbricati = gdf_fabbricati[gdf_fabbricati['domanda_en'] > 0].copy()
        n_eliminati = n_totale - len(gdf_fabbricati)
        logger.info(f"Eliminati {n_eliminati} edifici su {n_totale} (domanda_en=0)")

    # Aggiunta delta_UHI se presente
    if 'delta_UHI' in gdf_fabbricati.columns:
        logger.info("Colonna 'delta_UHI' trovata: aggiunta alla domanda energetica.")
        gdf_fabbricati['domanda_en'] += gdf_fabbricati['delta_UHI']

    gdf_fabbricati = get_dati_catasto(gdf_fabbricati, prov_safe, comm_safe)
    gdf_fabbricati.to_file(out_gpkg, driver='GPKG')

    logger.info(f"gpkg con domanda energetica salvato in {out_gpkg}")

    return gdf_fabbricati