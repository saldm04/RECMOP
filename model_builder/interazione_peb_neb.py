import logging
import os
import sys
from typing import Dict
import numpy as np
import pandas as pd
import geopandas as gpd
from sklearn.neighbors import NearestNeighbors
import shutil
from utils import safe_name, get_best_utm_epsg

# Configure logging
logger = logging.getLogger(__name__)

class InterazionePebNeb:
    """
       Modello per l’interazione energetica tra edifici PEB e NEB (positivi e negativi),
       ispirato al modello builder QGIS con estensioni per l’autosufficienza e la creazione di comunità energetiche (NCER).

       Questa classe gestisce l’intero flusso: lettura, validazione, pulizia, join spaziali, calcoli energetici e logiche
       di aggregazione tra edifici, restituendo come output i dataset incrementali delle comunità (NCER), dei PED (positivi)
       e dei NED (negativi), pronti per successive analisi o visualizzazioni.

       Le principali funzionalità includono:
       - Lettura e validazione robusta dei dati spaziali in ingresso (GeoPackage, Shapefile)
       - Gestione automatica dei sistemi di riferimento e della validità geometrica
       - Algoritmo nearest-neighbor ottimizzato con soglia di distanza personalizzabile
       - Calcolo dinamico dei surplus/deficit e della percentuale di autosufficienza
       - Filtraggio, join e dissoluzione di layer in linea con il flusso QGIS
       - Produzione dei layer finali NCER (Comunità Energetiche), PED (edifici positivi) e NED (edifici negativi)

       Attributi
       ----------
       results : dict
           Dizionario che contiene i risultati delle elaborazioni principali.

       Note
       -----
       Per la riproduzione fedele della pipeline QGIS sono richieste strutture di input conformi
       (colonne ID_P, surplus per PEB e ID_N, deficit per NEB) e CRS coerente.
       Tutti i passaggi intermedi sono loggati tramite il modulo logging.
       """

    def __init__(self):
        self.results = {}

    def safe_read_file(self, path: str, label: str) -> gpd.GeoDataFrame:
        """Carica un file shapefile/GeoPackage in modo sicuro con logging e gestione errori."""
        try:
            gdf = gpd.read_file(path)
            logger.info("Caricato '%s' (%d feature) da %s", label, len(gdf), path)
            return gdf
        except Exception as e:
            logger.error("Errore nel caricamento di '%s': %s", label, e)
            sys.exit(1)

    def check_required_columns(self, gdf: gpd.GeoDataFrame, required: list, layer_name: str) -> None:
        """Verifica che il GeoDataFrame contenga tutte le colonne richieste."""
        missing = [fld for fld in required if fld not in gdf.columns]
        if missing:
            logger.error(
                "Layer '%s' manca le colonne: %s. Assicurarsi di rinominare o includere questi campi.",
                layer_name,
                missing
            )
            sys.exit(1)

    def validate_and_clean_geometry(self, gdf: gpd.GeoDataFrame, id_field: str, layer_name: str) -> gpd.GeoDataFrame:
        """Rimuove geometrie vuote, None, non-polygonali e feature con ID null."""
        original_count = len(gdf)
        mask_valid_geom = gdf.geometry.notnull() & ~gdf.geometry.is_empty
        gdf = gdf[mask_valid_geom]
        mask_poly = gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
        gdf = gdf[mask_poly]
        mask_id = gdf[id_field].notna()
        gdf = gdf[mask_id]
        removed = original_count - len(gdf)
        if removed > 0:
            logger.warning("Rimosse %d feature invalide da '%s'", removed, layer_name)
        return gdf

    def find_nearest_neighbors(
            self,
            gdf_positive: gpd.GeoDataFrame,
            gdf_negative: gpd.GeoDataFrame,
            distanza_massima: float = None
    ) -> gpd.GeoDataFrame:
        """
        Trova il vicino più prossimo tra due layer, filtrando per distanza massima (metri).
        Gestisce automaticamente la trasformazione temporanea a CRS metrico.
        Il risultato viene restituito nel CRS originale di gdf_positive.
        """
        original_crs = gdf_positive.crs

        # Trova EPSG metrico se serve
        if original_crs is not None and original_crs.is_projected:
            gdf_pos_m = gdf_positive
            gdf_neg_m = gdf_negative.to_crs(original_crs) if gdf_negative.crs != original_crs else gdf_negative
        else:
            epsg_metrico = get_best_utm_epsg(gdf_positive)
            gdf_pos_m = gdf_positive.to_crs(epsg=epsg_metrico)
            gdf_neg_m = gdf_negative.to_crs(epsg=epsg_metrico)

        # Calcolo centroidi
        pos_coords = np.array([[geom.centroid.x, geom.centroid.y] for geom in gdf_pos_m.geometry])
        neg_coords = np.array([[geom.centroid.x, geom.centroid.y] for geom in gdf_neg_m.geometry])

        # Calcolo nearest neighbors
        nbrs = NearestNeighbors(n_neighbors=1, algorithm='auto').fit(neg_coords)
        distances, indices = nbrs.kneighbors(pos_coords)

        # Costruisci output come join by nearest QGIS
        joined_data = []
        for i, (pos_idx, neg_idx) in enumerate(zip(range(len(gdf_pos_m)), indices.flatten())):
            dist = distances[i][0]
            if distanza_massima is not None and dist > distanza_massima:
                continue  # salta join oltre soglia

            pos_row = gdf_pos_m.iloc[pos_idx].copy()
            neg_row = gdf_neg_m.iloc[neg_idx].copy()
            combined_row = pos_row.copy()
            for col in neg_row.index:
                if col != 'geometry':
                    combined_row[col] = neg_row[col]
            combined_row['distance'] = dist
            joined_data.append(combined_row)

        # Crea il GeoDataFrame vuoto con le colonne giuste se non ci sono join
        if joined_data:
            result_gdf = gpd.GeoDataFrame(joined_data, crs=gdf_pos_m.crs)
        else:
            # Crea tutte le colonne previste, più la geometry
            col_pos = list(gdf_pos_m.columns)
            col_neg = [col for col in gdf_neg_m.columns if col not in col_pos and col != 'geometry']
            columns = col_pos + col_neg + ['distance']
            # Inizializza tutte le colonne a vuoto, incluso 'geometry'
            data = {col: [] for col in columns}
            data['geometry'] = []
            result_gdf = gpd.GeoDataFrame(data, geometry='geometry', crs=gdf_pos_m.crs)

        # Riconverti al CRS originale se necessario
        if original_crs is not None and not result_gdf.crs == original_crs:
            result_gdf = result_gdf.to_crs(original_crs)
        return result_gdf

    def calculate_field(self, gdf: gpd.GeoDataFrame, field_name: str, formula_func, field_type: str = 'float64') -> gpd.GeoDataFrame:
        """Calcola un nuovo campo basato su una formula."""
        gdf_copy = gdf.copy()
        gdf_copy[field_name] = formula_func(gdf_copy)

        if field_type == 'int32':
            gdf_copy[field_name] = gdf_copy[field_name].astype('int32')
        elif field_type == 'float64':
            gdf_copy[field_name] = gdf_copy[field_name].astype('float64')

        return gdf_copy

    def group_statistics(self, gdf: gpd.GeoDataFrame, group_col: str, value_col: str) -> pd.DataFrame:
        """Calcola statistiche per gruppi."""
        stats = gdf.groupby(group_col)[value_col].agg(['max', 'min', 'mean', 'sum', 'count']).reset_index()
        return stats

    def join_attributes(self, gdf1: gpd.GeoDataFrame, gdf2: gpd.GeoDataFrame,
                        field1: str, field2: str, fields_to_copy: list, how: str = 'left') -> gpd.GeoDataFrame:
        """Esegui join tra attributi."""
        # Prepara i dati per il join
        join_data = gdf2[[field2] + fields_to_copy].copy()

        # Esegui il join
        result = gdf1.merge(join_data, left_on=field1, right_on=field2, how=how, suffixes=('', '_right'))

        # Pulisci colonne duplicate
        cols_to_drop = [col for col in result.columns if col.endswith('_right')]
        result = result.drop(columns=cols_to_drop)

        return result

    def extract_by_expression(self, gdf: gpd.GeoDataFrame, expression_func) -> gpd.GeoDataFrame:
        """Estrai features basandosi su un'espressione."""
        mask = expression_func(gdf)
        return gdf[mask].copy()

    def dissolve_by_field(self, gdf: gpd.GeoDataFrame, field: str) -> gpd.GeoDataFrame:
        """Dissolvi geometrie per campo."""
        dissolved = gdf.dissolve(by=field, aggfunc='first').reset_index()
        return dissolved

    def merge_layers(self, gdfs_list: list) -> gpd.GeoDataFrame:
        """Unisci più layer."""
        if len(gdfs_list) == 1:
            return gdfs_list[0].copy()

        merged = gpd.GeoDataFrame(pd.concat(gdfs_list, ignore_index=True))
        merged.crs = gdfs_list[0].crs
        return merged

    def process_algorithm(self, input_positivo_path: str, input_negativo_path: str, percentuale_autosuff = 55,
                          distanza_max = None) -> Dict[str, gpd.GeoDataFrame]:
        """
        Algoritmo principale che replica la logica del Model Builder QGIS con le nuove funzionalità.
        """
        logger.info("Caricamento dati...")

        # Carica e valida i dati di input
        gdf_positive = self.safe_read_file(input_positivo_path, "input_positivo")
        gdf_negative = self.safe_read_file(input_negativo_path, "input_negativo")

        self.check_required_columns(gdf_positive, ["ID_P", "surplus"], "input_positivo")
        self.check_required_columns(gdf_negative, ["ID_N", "deficit"], "input_negativo")

        if gdf_positive.crs != gdf_negative.crs:
            gdf_positive = gdf_positive.to_crs(gdf_negative.crs)
            logger.info("Riproiettato 'input_positivo' in CRS di 'input_negativo'")

        gdf_positive = self.validate_and_clean_geometry(gdf_positive, "ID_P", "input_positivo")
        gdf_negative = self.validate_and_clean_geometry(gdf_negative, "ID_N", "input_negativo")

        logger.info("Step 1: Join dei vicini più prossimi...")
        joined = self.find_nearest_neighbors(gdf_positive, gdf_negative, distanza_max)

        logger.info("Step 2: Calcolo DELTA...")
        joined = self.calculate_field(joined, 'DELTA', lambda df: df['surplus'] + df['deficit'])

        # Rimuovi colonne non necessarie create nel join
        cols_to_drop = ['distance']
        joined = joined.drop(columns=[col for col in cols_to_drop if col in joined.columns])

        logger.info("Step 3: Statistiche per gruppi...")
        group_stats = self.group_statistics(joined, 'ID_N', 'DELTA')

        logger.info("Step 4: Join secondo attributi...")
        joined = self.join_attributes(joined, group_stats, 'ID_N', 'ID_N', ['max'])
        joined = self.calculate_field(joined, 'delta2', lambda df: df['max'])

        filtered = self.extract_by_expression(joined, lambda df: df['DELTA'] == df['delta2'])

        logger.info("Step 5: Calcoli AGR e Autosufficienza...")
        filtered = self.calculate_field(filtered, 'Agr', lambda df: range(len(df)), 'int32')
        filtered = self.calculate_field(filtered, 'Autosuff',
                                        lambda df: (df['surplus'] / df['deficit']) * -1)

        # Filtra per autosufficienza tra 0.55 e 1 di default, ma può essere modificato
        autosuff_filter = self.extract_by_expression(filtered,
                                                     lambda df: (df['Autosuff'] > percentuale_autosuff/100) & (df['Autosuff'] < 1))
        autosuff_fail = self.extract_by_expression(filtered,
                                                   lambda df: ~((df['Autosuff'] > percentuale_autosuff/100) & (df['Autosuff'] < 1)))

        logger.info("Step 6: Creazione NCER...")
        ncer_p = self.join_attributes(gdf_positive, autosuff_filter, 'ID_P', 'ID_P',
                                      ['ID_N', 'DELTA', 'Agr', 'Autosuff'], 'inner')
        ncer_n = self.join_attributes(gdf_negative, autosuff_filter, 'ID_N', 'ID_N',
                                      ['ID_P', 'DELTA', 'Agr', 'Autosuff'], 'inner')

        ncer_merged = self.merge_layers([ncer_p, ncer_n])
        ncer_dissolved = self.dissolve_by_field(ncer_merged, 'Agr')

        logger.info("Step 7: Gestione PED e NED...")
        pas_ped = self.join_attributes(gdf_positive, autosuff_fail, 'ID_P', 'ID_P',
                                       ['ID_N', 'DELTA', 'Agr'], 'inner')
        pas_ned = self.join_attributes(gdf_negative, autosuff_fail, 'ID_N', 'ID_N',
                                       ['ID_P', 'DELTA', 'Agr'], 'inner')

        merged_pas = self.merge_layers([pas_ped, pas_ned])
        dissolved_pas = self.dissolve_by_field(merged_pas, 'Agr')

        logger.info("Step 8: Preparazione output NCER...")
        cols_to_drop = ['deficit']
        ncer_cleaned = ncer_dissolved.drop(columns=[col for col in cols_to_drop if col in ncer_dissolved.columns])
        ncer_cleaned = self.calculate_field(ncer_cleaned, 'ID_CER',
                                            lambda df: df['ID_P'].astype(str) + '_' + df['ID_N'].astype(str), 'str')
        ncer_cleaned = self.calculate_field(ncer_cleaned, 'deficit',
                                            lambda df: (df['surplus'] / df['Autosuff']) * -1)

        final_ncer_cols = ['ID_N', 'ID_P']
        ncer_final = ncer_cleaned.drop(columns=[col for col in final_ncer_cols if col in ncer_cleaned.columns])

        logger.info("Step 9: Preparazione output finali...")
        # Gestione PED che non hanno partecipato all'aggregazione
        pre_pas_ped = self.join_attributes(gdf_positive, filtered, 'ID_P', 'ID_P',
                                           ['ID_N', 'DELTA', 'Agr'], 'left')
        pas_ped_final = self.extract_by_expression(pre_pas_ped, lambda df: df['Agr'].isna())

        # Gestione NED che non hanno partecipato all'aggregazione
        pre_pas_ned = self.join_attributes(gdf_negative, filtered, 'ID_N', 'ID_N',
                                           ['ID_P', 'DELTA', 'Agr'], 'left')
        pas_ned_final = self.extract_by_expression(pre_pas_ned, lambda df: df['Agr'].isna())

        # Creazione new PED e NED
        new_ped = self.extract_by_expression(dissolved_pas, lambda df: df['DELTA'] >= 0)
        new_ned = self.extract_by_expression(dissolved_pas, lambda df: df['DELTA'] < 0)

        # Merge finali PED2 e NED2
        ped2 = self.merge_layers([new_ped, pas_ped_final])
        ned2 = self.merge_layers([new_ned, pas_ned_final])

        # Aggiorna campi PED2
        ped2 = self.calculate_field(ped2, 'surplus2',
                                    lambda df: np.where(df['DELTA'].isna(), df['surplus'], df['DELTA']))

        # Aggiorna campi NED2
        if 'deficit' not in ned2.columns:
            ned2['deficit'] = ned2['DELTA']  # Usa DELTA se Deficit non esiste
        ned2 = self.calculate_field(ned2, 'deficit2',
                                    lambda df: np.where(df['deficit'].isna(), df['DELTA'], df['deficit']))

        def pulisci_id(*args):
            """Unisce i pezzi, rimuovendo nan, stringhe vuote e eventuali .0 finali."""
            return '_'.join([
                str(a).replace('.0', '') for a in args
                if pd.notnull(a) and str(a) != 'nan' and str(a).strip() != ''
            ])

        # Pulizia finale e rinominazione campi
        # PED2
        ped2 = self.calculate_field(
            ped2, 'ID_P2',
            lambda df: [
                pulisci_id(p, n) for p, n in zip(
                    df['ID_P'], df['ID_N']
                )
            ], 'str'
        )
        cols_to_drop = ['deficit', 'surplus', 'ID_P', 'ID_N', 'DELTA', 'Agr']
        ped2_final = ped2.drop(columns=[col for col in cols_to_drop if col in ped2.columns])
        ped2_final = ped2_final.rename(columns={'surplus2': 'surplus', 'ID_P2': 'ID_P'})

        # NED2
        ned2 = self.calculate_field(
            ned2, 'ID_N2',
            lambda df: [
                pulisci_id(n, p) for n, p in zip(
                    df['ID_N'], df['ID_P']
                )
            ], 'str'
        )
        ned2_final = ned2.drop(columns=[col for col in cols_to_drop if col in ned2.columns])
        ned2_final = ned2_final.rename(columns={'deficit2': 'deficit', 'ID_N2': 'ID_N'})

        for df in [ncer_final, ned2_final, ped2_final, new_ned, new_ped]:
            if 'Agr' in df.columns:
                df.drop(columns=['Agr'], inplace=True)

        logger.info("Elaborazione completata!")
        return {
            'NCER': ncer_final,
            'NED2': ned2_final,
            'PED2': ped2_final,
            'NEW_NED': new_ned,
            'NEW_PED': new_ped
        }

def save_if_not_empty(gdf: gpd.GeoDataFrame, path: str, driver: str = 'GPKG', **kwargs):
    """
    Salva un GeoDataFrame su file solo se non vuoto; elimina eventuali file preesistenti se il nuovo output è vuoto.

    Parametri
    ----------
    gdf : gpd.GeoDataFrame
        Il GeoDataFrame da salvare.
    path : str
        Il percorso completo del file di output (inclusa estensione).
    driver : str, opzionale
        Driver di scrittura (default 'GPKG').
    **kwargs :
        Argomenti addizionali passati a `to_file`.

    Note
    -----
    Se il GeoDataFrame è vuoto e il file già esiste, il file viene eliminato.
    """
    if not gdf.empty:
        gdf.to_file(path, driver=driver, **kwargs)
    else:
        if os.path.exists(path):
            os.remove(path)

def step_interazione_peb_neb(
    provincia: str,
    comune: str,
    percentuale_autosuff=55,
    distanza_max=None,
    n_iter=1,
    input_pos=None,
    input_neg=None,
    prev_ncer=None,
    prev_ped2=None,
    prev_ned2=None,
    ncer_incrementale=None,
    outputs_dir_base=None,
    ncer_layer_name="ncer",
    is_distanza_iterativa = False
):
    """
    Esegue una singola iterazione dell'algoritmo di aggregazione PEB/NEB per la formazione delle Comunità Energetiche Rinnovabili (CER).

    L'algoritmo associa fabbricati con surplus energetico (PEB) e deficit (NEB) sulla base della soglia di autosufficienza e della distanza massima specificata, aggiornando i file di output e lo stato necessario per l'iterazione successiva.

    Parametri
    ----------
    provincia : str
        Nome della provincia.
    comune : str
        Nome del comune.
    percentuale_autosuff : float, opzionale
        Soglia di autosufficienza richiesta per l’aggregazione (default: 55).
    distanza_max : float, opzionale
        Distanza massima (in metri) per associare edifici (default: None).
    n_iter : int, opzionale
        Numero dell’iterazione corrente (default: 1).
    input_pos : str, opzionale
        Percorso al file PEB di input (default: auto).
    input_neg : str, opzionale
        Percorso al file NEB di input (default: auto).
    prev_ncer : GeoDataFrame, opzionale
        Stato precedente del DataFrame delle CER (default: None).
    prev_ped2 : GeoDataFrame, opzionale
        Stato precedente dei fabbricati PEB (default: None).
    prev_ned2 : GeoDataFrame, opzionale
        Stato precedente dei fabbricati NEB (default: None).
    ncer_incrementale : GeoDataFrame, opzionale
        DataFrame incrementale delle CER (default: None).
    outputs_dir_base : str, opzionale
        Directory base per l’output (default: auto).
    ncer_layer_name : str, opzionale
        Nome del layer per il salvataggio NCER (default: "ncer").
    is_distanza_iterativa : bool, opzionale
        Indica se la distanza viene inserita ad ogni iterazione (default: False).

    Restituisce
    ----------
    dict
        Dizionario con:
            - "continue": bool, True se deve continuare il ciclo iterativo.
            - "input_pos": percorso al nuovo input PEB.
            - "input_neg": percorso al nuovo input NEB.
            - "prev_ncer": stato aggiornato NCER.
            - "prev_ped2": stato aggiornato PEB.
            - "prev_ned2": stato aggiornato NEB.
            - "ncer_incrementale": DataFrame incrementale CER.
            - "n_iter": numero dell’iterazione successiva.

    Note
    ----
    Salva i risultati di ogni iterazione nelle apposite directory. Il ciclo termina se non ci sono più edifici aggregabili (output vuoti o nessun cambiamento rispetto all’iterazione precedente).
    """

    prov_norm = safe_name(provincia)
    com_norm = safe_name(comune)

    logger.info(
        f"[step_interazione_peb_neb] Iterazione {n_iter} - provincia: {prov_norm}, comune: {com_norm}, distanza_max: {distanza_max}")

    # Se non passati, costruisci path di default
    if outputs_dir_base is None:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        outputs_dir_base = os.path.abspath(
            os.path.join(script_dir, "..", "model_builder_shapefiles", f"{prov_norm}_{com_norm}", "outputs")
        )
    output_dir = os.path.join(outputs_dir_base, f"output{n_iter}")
    os.makedirs(output_dir, exist_ok=True)

    ncer_path = os.path.join(outputs_dir_base, f"ncer_{prov_norm}_{com_norm}.gpkg")
    output_ncer = os.path.join(output_dir, f"ncer_{prov_norm}_{com_norm}_{n_iter}.gpkg")
    output_ned2 = os.path.join(output_dir, f"outneb_{prov_norm}_{com_norm}_{n_iter}.gpkg")
    output_ped2 = os.path.join(output_dir, f"outpeb_{prov_norm}_{com_norm}_{n_iter}.gpkg")

    # Carica input iniziali se non forniti
    if n_iter == 1:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        base_dir = os.path.abspath(
            os.path.join(script_dir, "..", "model_builder_shapefiles", f"{prov_norm}_{com_norm}"))
        input_neg = input_neg or os.path.join(base_dir, "input", "neb", f"NEB_{prov_norm}_{com_norm}.gpkg")
        input_pos = input_pos or os.path.join(base_dir, "input", "peb", f"PEB_{prov_norm}_{com_norm}.gpkg")
        prev_ped2 = gpd.read_file(input_pos)
        prev_ned2 = gpd.read_file(input_neg)
        prev_ncer = None
        logger.info(f"[step_interazione_peb_neb] Caricati input iniziali: {input_pos}, {input_neg}")

    processor = InterazionePebNeb()
    logger.info(
        f"[step_interazione_peb_neb] Avvio process_algorithm con autosufficienza={percentuale_autosuff}, distanza_max={distanza_max}")
    results = processor.process_algorithm(
        input_positivo_path=os.path.abspath(input_pos),
        input_negativo_path=os.path.abspath(input_neg),
        percentuale_autosuff=percentuale_autosuff,
        distanza_max=distanza_max
    )

    ncer = results['NCER'].copy()
    ped2_gdf = results['PED2']
    ned2_gdf = results['NED2']

    ncer['iterazione'] = n_iter

    # Funzione per verificare cambiamento tra due DataFrame
    def changed(df, prev_df):
        if (prev_df is None or prev_df.empty) and (df is None or df.empty):
            return False
        return not df.equals(prev_df)

    ncer_changed = changed(ncer, prev_ncer)
    ped2_changed = changed(ped2_gdf, prev_ped2)
    ned2_changed = changed(ned2_gdf, prev_ned2)

    # Condizione di terminazione: output vuoto
    should_stop = False
    if ped2_gdf.empty or ned2_gdf.empty:
        logger.info(
            f"[step_interazione_peb_neb] Iterazione {n_iter}: almeno uno tra PEB o NEB è vuoto. Termino il ciclo.")
        if not ped2_gdf.empty:
            save_if_not_empty(ped2_gdf, output_ped2)
            logger.info(f"[step_interazione_peb_neb] Salvato PEB output ({len(ped2_gdf)} feature): {output_ped2}")
        if not ned2_gdf.empty:
            save_if_not_empty(ned2_gdf, output_ned2)
            logger.info(f"[step_interazione_peb_neb] Salvato NEB output ({len(ned2_gdf)} feature): {output_ned2}")
        should_stop = True

    # Logica per distanza fissa: tutto invariato rispetto all'iterazione precedente
    if not should_stop and not ncer_changed and not ped2_changed and not ned2_changed and not is_distanza_iterativa:
        logger.info(
            f"[step_interazione_peb_neb] Iterazione {n_iter}: nessun cambiamento rispetto alla precedente. Stop ciclo e pulizia output iterazione corrente.")
        if os.path.exists(output_dir):
            shutil.rmtree(output_dir)
        n_iter -= 1
        output_dir = os.path.join(outputs_dir_base, f"output{n_iter}")
        output_ned2 = os.path.join(output_dir, f"outneb_{prov_norm}_{com_norm}_{n_iter}.gpkg")
        output_ped2 = os.path.join(output_dir, f"outpeb_{prov_norm}_{com_norm}_{n_iter}.gpkg")
        should_stop = True

    # Salvataggi output
    if not should_stop:
        if not ped2_gdf.empty and (is_distanza_iterativa or ped2_changed or ncer_changed):
            save_if_not_empty(ped2_gdf, output_ped2)
            logger.info(f"[step_interazione_peb_neb] Salvato PEB output ({len(ped2_gdf)} feature): {output_ped2}")
        if not ned2_gdf.empty and (is_distanza_iterativa or ned2_changed or ncer_changed):
            save_if_not_empty(ned2_gdf, output_ned2)
            logger.info(f"[step_interazione_peb_neb] Salvato NEB output ({len(ned2_gdf)} feature): {output_ned2}")

    # NCER logica incrementale
    if not ncer.empty and ncer_changed:
        if ncer_incrementale is None:
            ncer_incrementale = ncer.copy()
        else:
            ncer_incrementale = pd.concat([ncer_incrementale, ncer], ignore_index=True)
        save_if_not_empty(ncer_incrementale, ncer_path, layer=ncer_layer_name)
        save_if_not_empty(ncer, output_ncer)
        logger.info(
            f"[step_interazione_peb_neb] Salvato NCER incrementale e NCER iterazione: {ncer_path}, {output_ncer}")

    # Prepara input per prossima iterazione
    new_input_pos = output_ped2
    new_input_neg = output_ned2
    new_prev_ncer = ncer.copy() if not ncer.empty else None
    new_prev_ped2 = ped2_gdf.copy() if not ped2_gdf.empty else None
    new_prev_ned2 = ned2_gdf.copy() if not ned2_gdf.empty else None

    logger.info(f"[step_interazione_peb_neb] Fine iterazione {n_iter}. Stato: should_stop={should_stop}")

    return {
        "continue": not should_stop,
        "input_pos": new_input_pos,
        "input_neg": new_input_neg,
        "prev_ncer": new_prev_ncer,
        "prev_ped2": new_prev_ped2,
        "prev_ned2": new_prev_ned2,
        "ncer_incrementale": ncer_incrementale,
        "n_iter": n_iter + 1
    }

def ciclo_interazione_peb_neb(
        provincia: str,
        comune: str,
        percentuale_autosuff=55,
        distanza_max=None
    ) -> None:
    """
    Gestisce il ciclo completo di aggregazione iterativa tra edifici PEB (Positive Energy Building) e NEB (Negative Energy Building) per la formazione delle CER, ripetendo l’algoritmo fino al raggiungimento di una condizione di arresto.

    Il ciclo richiama `step_interazione_peb_neb` per ciascuna iterazione, aggiorna i file di output e interrompe il processo quando non è più possibile formare nuove aggregazioni.

    Parametri
    ----------
    provincia : str
        Nome della provincia.
    comune : str
        Nome del comune.
    percentuale_autosuff : float, opzionale
        Soglia di autosufficienza richiesta per l’aggregazione (default: 55).
    distanza_max : float, opzionale
        Distanza massima (in metri) per associare edifici (default: None).

    Restituisce
    ----------
    None

    Effetti
    -------
    Salva su disco le aggregazioni (CER) generate ad ogni iterazione nella struttura di output prevista dal progetto. Registra i log del processo. Il ciclo si interrompe quando uno tra PEB o NEB in input risulta vuoto o non vi sono variazioni rispetto all’iterazione precedente.
    """
    prov_norm = safe_name(provincia)
    com_norm = safe_name(comune)
    prov_com = f"{prov_norm}_{com_norm}"

    script_dir = os.path.dirname(os.path.abspath(__file__))
    BASE_DIR = os.path.abspath(os.path.join(script_dir, "..", "model_builder_shapefiles", prov_com))
    logger.info(f"Directory di base impostata su: {BASE_DIR}")

    OUTPUTS_DIR = os.path.join(BASE_DIR, "outputs")
    input_neg = os.path.join(BASE_DIR, "input", "neb", f"NEB_{prov_norm}_{com_norm}.gpkg")
    input_pos = os.path.join(BASE_DIR, "input", "peb", f"PEB_{prov_norm}_{com_norm}.gpkg")

    ncer_path = os.path.join(OUTPUTS_DIR, f"ncer_{prov_norm}_{com_norm}.gpkg")
    ncer_layer_name = "ncer"

    if os.path.exists(ncer_path):
        os.remove(ncer_path)

    if os.path.exists(OUTPUTS_DIR):
        try:
            shutil.rmtree(OUTPUTS_DIR)
            logger.info(f"Cartella OUTPUTS eliminata: {OUTPUTS_DIR}")
        except Exception as e:
            logger.warning(f"Impossibile eliminare la cartella {OUTPUTS_DIR}: {e}")

    # Caricamento input per controllo "early stop"
    gdf_peb_init = gpd.read_file(input_pos)
    gdf_neb_init = gpd.read_file(input_neg)

    if gdf_peb_init.empty or gdf_neb_init.empty:
        logger.info(
            "Uno tra PEB o NEB di input è vuoto. Verrà salvato solo il file non vuoto come output1 e il ciclo verrà interrotto.")

        output_dir = os.path.join(OUTPUTS_DIR, "output1")
        os.makedirs(output_dir, exist_ok=True)
        output_ped2 = os.path.join(output_dir, f"outpeb_{prov_norm}_{com_norm}_1.gpkg")
        output_ned2 = os.path.join(output_dir, f"outneb_{prov_norm}_{com_norm}_1.gpkg")

        # Salva solo quello NON vuoto
        if not gdf_peb_init.empty:
            save_if_not_empty(gdf_peb_init, output_ped2)
            logger.info(f"Creato solo PEB output ({len(gdf_peb_init)} elementi)")
        if not gdf_neb_init.empty:
            save_if_not_empty(gdf_neb_init, output_ned2)
            logger.info(f"Creato solo NEB output ({len(gdf_neb_init)} elementi)")

        logger.info("Analisi interrotta: uno degli input era vuoto.")
        return

    # Stato iniziale per step_interazione_peb_neb
    n_iter = 1
    step_result = {
        "input_pos": input_pos,
        "input_neg": input_neg,
        "prev_ncer": None,
        "prev_ped2": gdf_peb_init,
        "prev_ned2": gdf_neb_init,
        "ncer_incrementale": None,
        "n_iter": n_iter
    }

    while True:
        logger.info(f"\n=== ITERAZIONE {step_result['n_iter']} ===")
        # Nessuna distanza iterativa, uso sempre quella passata
        distanza_max_iter = distanza_max

        # Esegui una iterazione tramite la funzione step_interazione_peb_neb
        step_result = step_interazione_peb_neb(
            provincia=provincia,
            comune=comune,
            percentuale_autosuff=percentuale_autosuff,
            distanza_max=distanza_max_iter,
            n_iter=step_result['n_iter'],
            input_pos=step_result['input_pos'],
            input_neg=step_result['input_neg'],
            prev_ncer=step_result['prev_ncer'],
            prev_ped2=step_result['prev_ped2'],
            prev_ned2=step_result['prev_ned2'],
            ncer_incrementale=step_result['ncer_incrementale'],
            outputs_dir_base=OUTPUTS_DIR,
            ncer_layer_name=ncer_layer_name,
            is_distanza_iterativa=False  # Non usiamo distanza iterativa in questo ciclo
        )

        if not step_result["continue"]:
            break

    logger.info(f"Ciclo completato! File NCER incrementale: {ncer_path}")
