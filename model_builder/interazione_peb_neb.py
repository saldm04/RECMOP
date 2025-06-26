#!/usr/bin/env python3
"""
Script: interazione_peb_neb.py (versione aggiornata con nuove funzionalità)

Descrizione:
    Riproduce la logica del modello QGIS "INTERAZIONE PEB-NEB" con le nuove funzionalità
    di autosufficienza (55%) e creazione NCER, mantenendo la struttura dei percorsi originale.
"""
import argparse
import logging
import os
import sys
from typing import Dict
import numpy as np
import pandas as pd
import geopandas as gpd
from sklearn.neighbors import NearestNeighbors
import shutil

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

class InterazionePebNeb:
    """
    Classe principale che implementa la logica di interazione PEB-NEB con le nuove funzionalità.
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

    def find_nearest_neighbors(self, gdf_positive: gpd.GeoDataFrame, gdf_negative: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """Trova i vicini più prossimi tra layer positivi e negativi."""
        # Estrai coordinate dei centroidi
        pos_coords = np.array([[geom.centroid.x, geom.centroid.y] for geom in gdf_positive.geometry])
        neg_coords = np.array([[geom.centroid.x, geom.centroid.y] for geom in gdf_negative.geometry])

        # Trova il vicino più prossimo per ogni elemento positivo
        nbrs = NearestNeighbors(n_neighbors=1, algorithm='auto').fit(neg_coords)
        distances, indices = nbrs.kneighbors(pos_coords)

        # Crea il join
        joined_data = []
        for i, (pos_idx, neg_idx) in enumerate(zip(range(len(gdf_positive)), indices.flatten())):
            pos_row = gdf_positive.iloc[pos_idx].copy()
            neg_row = gdf_negative.iloc[neg_idx].copy()

            # Combina i dati
            combined_row = pos_row.copy()
            for col in neg_row.index:
                if col != 'geometry':
                    combined_row[col] = neg_row[col]
            combined_row['distance'] = distances[i][0]

            joined_data.append(combined_row)

        return gpd.GeoDataFrame(joined_data, crs=gdf_positive.crs)

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

    def process_algorithm(self, input_positivo_path: str, input_negativo_path: str,
                          output_ncer_path: str, output_ned2_path: str, output_ped2_path: str,
                          new_ned_path: str, new_ped_path: str) -> Dict[str, gpd.GeoDataFrame]:
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
        joined = self.find_nearest_neighbors(gdf_positive, gdf_negative)

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

        # Filtra per autosufficienza tra 0.55 e 1
        autosuff_filter = self.extract_by_expression(filtered,
                                                     lambda df: (df['Autosuff'] > 0.55) & (df['Autosuff'] < 1))
        autosuff_fail = self.extract_by_expression(filtered,
                                                   lambda df: ~((df['Autosuff'] > 0.55) & (df['Autosuff'] < 1)))

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

        logger.info("Salvataggio risultati...")
        # Salva i risultati
        ncer_final.to_file(output_ncer_path, driver='GPKG')
        ned2_final.to_file(output_ned2_path, driver='GPKG')
        ped2_final.to_file(output_ped2_path, driver='GPKG')
        #new_ned.to_file(new_ned_path, driver='GPKG')
        #new_ped.to_file(new_ped_path, driver='GPKG')


        logger.info("Elaborazione completata!")
        return {
            'NCER': ncer_final,
            'NED2': ned2_final,
            'PED2': ped2_final,
            'NEW_NED': new_ned,
            'NEW_PED': new_ped
        }


def normalize(s: str) -> str:
    """Normalizza stringa per nomi file."""
    return s.lower().replace(" ", "_")

def save_if_not_empty(gdf: gpd.GeoDataFrame, path: str, driver: str = 'GPKG', **kwargs):
    """
    Salva il GeoDataFrame solo se non vuoto. Se esiste un vecchio file ma il nuovo è vuoto, lo elimina.
    """
    if not gdf.empty:
        gdf.to_file(path, driver=driver, **kwargs)
    else:
        if os.path.exists(path):
            os.remove(path)


def processa_interazione_peb_neb(provincia: str, comune: str) -> None:
    """
    Esegue l'interazione PEB-NEB per una specifica coppia provincia-comune,
    costruendo i percorsi input/output sulla base della struttura dei file.
    """
    prov_com = f"{normalize(provincia)}_{normalize(comune)}"
    BASE_DIR = os.path.join("..", "model_builder_shapefiles", prov_com)

    # Costruzione percorsi input
    input_neg_dir = os.path.join(BASE_DIR, "input", "neb")
    input_pos_dir = os.path.join(BASE_DIR, "input", "peb")
    input_neg = os.path.join(input_neg_dir, f"NEB_{provincia}_{comune}.shp")
    input_pos = os.path.join(input_pos_dir, f"PEB_{provincia}_{comune}.shp")

    # Costruzione percorsi output (uso nomi file minuscoli)
# Costruzione percorsi output (uso nomi file minuscoli)
    prov_norm = normalize(provincia)
    com_norm = normalize(comune)
    output_ncer = os.path.join(BASE_DIR, "output", "ncer", f"ncer_{prov_norm}_{com_norm}.gpkg")
    output_ned2 = os.path.join(BASE_DIR, "output", "neb", f"outneb_{prov_norm}_{com_norm}.gpkg")
    output_ped2 = os.path.join(BASE_DIR, "output", "peb", f"outpeb_{prov_norm}_{com_norm}.gpkg")
    new_ned = os.path.join(BASE_DIR, "new", "neb", f"newneb_{prov_norm}_{com_norm}.gpkg")
    new_ped = os.path.join(BASE_DIR, "new", "peb", f"newpeb_{prov_norm}_{com_norm}.gpkg")


# Crea le directory di output se non esistono
    for path in [output_ncer, output_ned2, output_ped2, new_ned, new_ped]:
        outdir = os.path.dirname(path)
        if not os.path.exists(outdir):
            os.makedirs(outdir, exist_ok=True)

    # Inizializza e esegui il processore
    processor = InterazionePebNeb()

    try:
        results = processor.process_algorithm(
            input_positivo_path=input_pos,
            input_negativo_path=input_neg,
            output_ncer_path=output_ncer,
            output_ned2_path=output_ned2,
            output_ped2_path=output_ped2,
            new_ned_path=new_ned,
            new_ped_path=new_ped
        )

        logger.info("\n=== RISULTATI ===")
        for name, gdf in results.items():
            logger.info("%s: %d features", name, len(gdf))
            logger.info("Colonne: %s", list(gdf.columns))
            logger.info("CRS: %s", gdf.crs)
            logger.info("-" * 50)

    except Exception as e:
        logger.error("Errore durante l'elaborazione: %s", e, exc_info=True)
        sys.exit(1)

def ciclo_interazione_peb_neb(provincia: str, comune: str) -> None:
    """
    Esegue il ciclo di aggregazione PEB-NEB iterativamente,
    fermandosi quando almeno uno tra outpeb e outneb è vuoto.
    Ogni output viene scritto solo se non vuoto.
    Il file NCER viene aggiornato iterativamente (append) in un unico file.
    NON viene scritto il file NCER della singola iterazione finale se identico al globale.
    """
    prov_com = f"{normalize(provincia)}_{normalize(comune)}"
    BASE_DIR = os.path.join("..", "model_builder_shapefiles", prov_com)
    OUTPUTS_DIR = os.path.join(BASE_DIR, "outputs")

    prov_norm = normalize(provincia)
    com_norm = normalize(comune)
    input_neg = os.path.join(BASE_DIR, "input", "neb", f"NEB_{provincia}_{comune}.shp")
    input_pos = os.path.join(BASE_DIR, "input", "peb", f"PEB_{provincia}_{comune}.shp")

    n_iter = 1
    ncer_path = os.path.join(OUTPUTS_DIR, f"ncer_{prov_norm}_{com_norm}.gpkg")
    ncer_layer_name = "ncer"

    # Sicurezza: rimuovi eventuale file NCER globale già esistente
    if os.path.exists(ncer_path):
        os.remove(ncer_path)

    last_ncer_gpkg_path = None
    last_ncer_gdf = None

    prev_ncer = None  # per confronto tra iterazioni

    # --- NUOVO BLOCCO: elimina l'intera cartella outputs, se esiste ---
    if os.path.exists(OUTPUTS_DIR):
        try:
            shutil.rmtree(OUTPUTS_DIR)
            logger.info(f"Cartella OUTPUTS eliminata: {OUTPUTS_DIR}")
        except Exception as e:
            logger.warning(f"Impossibile eliminare la cartella {OUTPUTS_DIR}: {e}")

    while True:
        logger.info(f"\n=== ITERAZIONE {n_iter} ===")

        output_dir = os.path.join(OUTPUTS_DIR, f"output{n_iter}")
        os.makedirs(output_dir, exist_ok=True)

        output_ncer = os.path.join(output_dir, f"ncer_{prov_norm}_{com_norm}_{n_iter}.gpkg")
        output_ned2 = os.path.join(output_dir, f"outneb_{prov_norm}_{com_norm}_{n_iter}.gpkg")
        output_ped2 = os.path.join(output_dir, f"outpeb_{prov_norm}_{com_norm}_{n_iter}.gpkg")
        new_ned = os.path.join(output_dir, f"newneb_{prov_norm}_{com_norm}_{n_iter}.gpkg")
        new_ped = os.path.join(output_dir, f"newpeb_{prov_norm}_{com_norm}_{n_iter}.gpkg")

        processor = InterazionePebNeb()
        results = processor.process_algorithm(
            input_positivo_path=input_pos,
            input_negativo_path=input_neg,
            output_ncer_path=output_ncer,
            output_ned2_path=output_ned2,
            output_ped2_path=output_ped2,
            new_ned_path=new_ned,
            new_ped_path=new_ped
        )

        ncer = results['NCER'].copy()
        ped2_gdf = results['PED2']
        ned2_gdf = results['NED2']

        ncer['iterazione'] = n_iter

        # NCER globale: append solo se non vuoto
        if not ncer.empty:
            if not os.path.exists(ncer_path):
                save_if_not_empty(ncer, ncer_path, layer=ncer_layer_name)
            else:
                old_ncer = gpd.read_file(ncer_path, layer=ncer_layer_name)
                ncer_all = pd.concat([old_ncer, ncer], ignore_index=True)
                save_if_not_empty(gpd.GeoDataFrame(ncer_all, crs=ncer.crs), ncer_path, layer=ncer_layer_name)
            logger.info(f"NCER aggiornato con {len(ncer)} record (iterazione {n_iter})")

        # NCER iterazione: scrivi solo se non vuoto e diverso dal precedente (così non salvi inutili duplicati)
        write_ncer_iter = False
        if not ncer.empty and (prev_ncer is None or not ncer.equals(prev_ncer)):
            write_ncer_iter = True
        if write_ncer_iter:
            save_if_not_empty(ncer, output_ncer)
            last_ncer_gpkg_path = output_ncer
            last_ncer_gdf = ncer.copy()
        else:
            if os.path.exists(output_ncer):
                os.remove(output_ncer)
        prev_ncer = ncer.copy() if not ncer.empty else None

        # Altri output: solo se non vuoti
        save_if_not_empty(ped2_gdf, output_ped2)
        save_if_not_empty(ned2_gdf, output_ned2)
        # Se vuoi anche i NEW_NED / NEW_PED, decommenta qui:
        # save_if_not_empty(results['NEW_PED'], new_ped)
        # save_if_not_empty(results['NEW_NED'], new_ned)

        # Stop se uno dei due layer principali è vuoto
        if ped2_gdf.empty or ned2_gdf.empty:
            logger.info(f"Iterazione {n_iter}: condizione di terminazione raggiunta (uno degli output è vuoto).")
            break

        # Output della prossima iterazione
        input_pos = output_ped2
        input_neg = output_ned2
        n_iter += 1

    # --- Fine ciclo: elimina NCER iterazione finale se duplicato di quello globale
    if last_ncer_gpkg_path is not None and last_ncer_gdf is not None:
        ncer_final = gpd.read_file(ncer_path, layer=ncer_layer_name)
        ncer_last_iter = ncer_final[ncer_final['iterazione'] == n_iter]
        if not ncer_last_iter.empty and ncer_last_iter.equals(last_ncer_gdf):
            try:
                os.remove(last_ncer_gpkg_path)
                logger.info(f"Rimosso file NCER dell’ultima iterazione ({last_ncer_gpkg_path}) perché duplicato di quello incrementale.")
            except Exception as e:
                logger.warning(f"Impossibile eliminare {last_ncer_gpkg_path}: {e}")

    logger.info(f"Ciclo completato! File NCER incrementale: {ncer_path}")


if __name__ == "__main__":
    ciclo_interazione_peb_neb("Salerno", "Padula")