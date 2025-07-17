from tabulate import tabulate
from utils import get_pannelli, get_regione_from_provincia, safe_name, \
    normalize_dsm_input, \
    get_file_modification_date, configure_logging_globale, normalize_fabbricati_input_auto, normalize_vincoli_input
from offerta.grass_gis.calcolo_offerta_energetica import calcolo_offerta_energetica, refresh_offerta_energetica
from data_extraction.calcolo_domanda_energetica import calcola_domanda_energetica
from data_extraction.join_data_normattiva_varcens_basiterr import refresh_join_data
from model_builder.creazione_peb_neb import crea_peb_neb
from model_builder.interazione_peb_neb import ciclo_interazione_peb_neb, step_interazione_peb_neb
from data_extraction.siape import run_estrazione_siape
from utils import load_dot_env

import os
import logging
import sys
import pandas as pd

logger = logging.getLogger(__name__)

load_dot_env()

def mostra_pannelli(df: pd.DataFrame) -> None:
    """
    Stampa una tabella ben formattata dei pannelli fotovoltaici disponibili.
    La colonna 'Dimensione' viene rinominata in 'Superficie + 30%' solo per la visualizzazione.
    """
    colonne = [
        'Marca', 'Modello', 'Potenza(Wp)', 'Efficienza(%)',
        'Tecnologia', 'Prezzo', 'Superficie', 'Dimensione'
    ]
    df_vis = df[colonne].copy()
    df_vis.index += 1  # numerazione da 1

    # Rinomina colonna per la sola visualizzazione
    df_vis = df_vis.rename(columns={"Dimensione": "Superficie + 30%"})

    print("\nSeleziona il pannello che preferisci:\n")
    print(tabulate(df_vis, headers="keys", tablefmt="grid", showindex=True))

import os
import geopandas as gpd

def report_interazione_outputs(provincia: str, comune: str):
    """
    Stampa il numero di CER prodotti, PEB totali e NEB totali ad ogni iterazione,
    e i totali finali per provincia e comune richiesti.
    """
    prov_safe = safe_name(provincia)
    com_safe = safe_name(comune)
    base_dir = os.path.join("model_builder_shapefiles", f"{prov_safe}_{com_safe}", "outputs")

    iter_num = 1
    output_exists = False

    while True:
        iter_dir = os.path.join(base_dir, f"output{iter_num}")
        if not os.path.isdir(iter_dir):
            break

        ncer_path = os.path.join(iter_dir, f"ncer_{prov_safe}_{com_safe}_{iter_num}.gpkg")
        peb_path = os.path.join(iter_dir, f"outpeb_{prov_safe}_{com_safe}_{iter_num}.gpkg")
        neb_path = os.path.join(iter_dir, f"outneb_{prov_safe}_{com_safe}_{iter_num}.gpkg")

        ncer_count = 0
        peb_count = 0
        neb_count = 0

        if os.path.exists(ncer_path):
            try:
                ncer_count = len(gpd.read_file(ncer_path))
            except Exception:
                ncer_count = 0
        if os.path.exists(peb_path):
            try:
                peb_count = len(gpd.read_file(peb_path))
            except Exception:
                peb_count = 0
        if os.path.exists(neb_path):
            try:
                neb_count = len(gpd.read_file(neb_path))
            except Exception:
                neb_count = 0

        print(f"Iterazione {iter_num}: CER prodotti: {ncer_count}, PEB totali: {peb_count}, NEB totali: {neb_count}")

        output_exists = True
        iter_num += 1

    # Finali
    ncer_final_path = os.path.join(base_dir, f"ncer_{prov_safe}_{com_safe}.gpkg")
    peb_final_path = os.path.join(base_dir, f"output{iter_num-1}", f"outpeb_{prov_safe}_{com_safe}_{iter_num-1}.gpkg")
    neb_final_path = os.path.join(base_dir, f"output{iter_num-1}", f"outneb_{prov_safe}_{com_safe}_{iter_num-1}.gpkg")

    cer_tot = 0
    peb_tot = 0
    neb_tot = 0

    if os.path.exists(ncer_final_path):
        try:
            # layer="ncer" è quello incrementale (default se non specificato)
            cer_tot = len(gpd.read_file(ncer_final_path, layer="ncer"))
        except Exception:
            cer_tot = 0
    if os.path.exists(peb_final_path):
        try:
            peb_tot = len(gpd.read_file(peb_final_path))
        except Exception:
            peb_tot = 0
    if os.path.exists(neb_final_path):
        try:
            neb_tot = len(gpd.read_file(neb_final_path))
        except Exception:
            neb_tot = 0

    print("\n=== Totali Finali ===")
    print(f"Totale CER: {cer_tot}")
    print(f"Totale PEB: {peb_tot}")
    print(f"Totale NEB: {neb_tot}")

    if not output_exists:
        print("Nessun output trovato. Tutti i valori sono 0.")

def main():
    # === CONFIGURAZIONE LOGGING ===
    while True:
        usa_log = input("Vuoi visualizzare i log delle operazioni? (SI/NO): ").strip().upper()
        if usa_log == "SI":
            configure_logging_globale(attivo=True)
            logger.info("Logging abilitato.")
            break
        elif usa_log == "NO":
            configure_logging_globale(attivo=False)
            break
        else:
            print("Risposta non valida. Scrivi 'SI' oppure 'NO'.")

    print(
        "\n--- PREPARAZIONE INPUT ---\n"
        "Assicurati che:\n"
        "- La directory 'FABBRICATI' contenga una sottodirectory chiamata 'fabbricati_provincia_comune'\n"
        "  con i file (.shp, .dbf, .cpg, .shx, .prj, ...) relativi ai fabbricati del comune di interesse.\n"
        "  Il nome della directory deve usare solo lettere minuscole e trattini al posto di spazi o apostrofi.\n"
        "  Esempi:\n"
        "    fabbricati_napoli_poggiomarino\n"
        "    fabbricati_napoli_torre-annunziata\n"
        "    fabbricati_napoli_pomigliano-d-arco\n"
        "\n"
        "- La directory 'input_dsm' contenga il file DSM relativo alla zona del comune.\n"
        "  Il nome del file deve avere il formato: DSM_provincia_comune.tif\n"
        "  Anche qui, usare solo minuscole e trattini per spazi o apostrofi.\n"
        "  Esempi:\n"
        "    DSM_napoli_poggiomarino.tif\n"
        "    DSM_napoli_torre-annunziata.tif\n"
        "    DSM_napoli_pomigliano-d-arco.tif\n"
        "\n"
        "Il tipo di analisi sulla domanda energetica dipenderà dalle colonne presenti nello shapefile dei fabbricati:\n"
        "- Se contiene solo geometrie → verrà usato il modello base: Zona climatica e classe d'età\n"
        "- Se contiene anche 'sup_risc' e 'vol_risc' → modello esteso: Zona climatica, Superficie utile riscaldata e volume riscaldato\n"
        "- Se contiene anche 'sup_disp' oltre a 'sup_risc' e 'vol_risc' → modello completo: Zona climatica, Superficie utile riscaldata, volume riscaldato e superficie disperdente\n"
        "\n"
        "In aggiunta, se lo shapefile contiene la colonna opzionale 'delta_UHI', il suo valore (espresso in kWh/anno) verrà sommato alla "
        "domanda energetica finale, per tenere conto dell'incremento dovuto all'effetto isola di calore urbana."
        "\n"
        "In alternativa al file DSM, puoi fornire un file tif di irradianza annua già calcolato (kWh/mq/annui).\n"
        "Nella directory 'offerta/grass_gis/irradiance_tif' deve essere presente un file con il nome: irradianza_annua_provincia_comune_kwh.tif\n"
        "Anche qui, usare solo minuscole e trattini per spazi o apostrofi.\n"
        "Esempi:\n"
        "irradianza_annua_napoli_poggiomarino_kwh.tif\n"
        "irradianza_annua_napoli_torre-annunziata_kwh.tif\n"
        "irradianza_annua_napoli_pomigliano-d-arco_kwh.tif\n"
        "\n"
        "L'analisi verrà effettuata sull'intersezione tra i fabbricati e il DSM forniti.\n"
        "Eventualmente, è possibile specificare all'interno di 'VINCOLI' una sottodirectory chiamata 'vincoli_provincia_comune'\n"
        "con i file (.shp, .dbf, .cpg, .shx, .prj, ...) relativi ai vincoli del comune di interesse.\n"
        "Il nome della directory deve usare solo lettere minuscole e trattini al posto di spazi o apostrofi.\n"
        "I vincoli sono opzionali e possono essere utilizzati per limitare l'area di calcolo dell'offerta energetica\n"
        "e per considerare eventuali restrizioni legate a vincoli urbanistici o paesaggistici.\n"
    )

    # Inserimento dati
    comune = input("Inserisci il nome del comune: ")
    com_safe = safe_name(comune)
    provincia = input("Inserisci la provincia del comune: ")
    prov_safe = safe_name(provincia)

    try:
        # Normalizzazione e controllo fabbricati
        fabbricati_tipo = normalize_fabbricati_input_auto(os.path.abspath("FABBRICATI"), prov_safe, com_safe)
        normalize_dsm_input(os.path.abspath("input_dsm"), os.path.abspath(os.path.join("offerta", "grass_gis", "irradiance_tif")),
                            prov_safe, com_safe)
        exist_vincoli = normalize_vincoli_input(os.path.abspath("VINCOLI"), prov_safe, com_safe)
    except Exception as e:
        print(f"Errore nella normalizzazione dei dati: {e}")
        print("Assicurati che i nomi delle directory e dei file siano corretti.")
        sys.exit(1)

    regione = get_regione_from_provincia(prov_safe)
    logger.info("Input fabbricati e DSM correttamente normalizzati. Avvio dell'analisi...")

    # Aggiornamento SIAPE
    siape_paths = {
        "zc_range": os.path.join("Data_Collection", "csv_tables-fase1", "epgl_nren_ren_co2_tabella_siape_zc_range.csv"),
        "zc_suris_volris": os.path.join("Data_Collection", "csv_tables-fase1",
                                        "epgl_nren_ren_co2_tabella_siape_zc_suris_volris.csv"),
        "zc_suris_volris_supdi": os.path.join("Data_Collection", "csv_tables-fase1",
                                              "epgl_nren_ren_co2_tabella_siape_zc_suris_volris_supdi.csv"),
    }
    siape_path = siape_paths.get(fabbricati_tipo)
    if siape_path is None:
        print(f"Tipologia fabbricati sconosciuta: {fabbricati_tipo}")
        sys.exit(1)
    ultima_mod_siape = get_file_modification_date(siape_path)
    print(f"Dati SIAPE - Ultimo aggiornamento: {ultima_mod_siape}")
    if ultima_mod_siape != "File non trovato":
        while True:
            risposta_siape = input(
                "Vuoi aggiornare dati delle prestazioni energetiche del SIAPE? (SI/NO): ").strip().upper()
            if risposta_siape == "SI":
                run_estrazione_siape(fabbricati_tipo)
                print("Analisi SIAPE completata.")
                break
            elif risposta_siape == "NO":
                break
            else:
                print("Risposta non valida. Scrivi 'SI' oppure 'NO'.")

    # Aggiornamento zone climatiche
    zona_path = os.path.join("Data_Collection", "csv_tables-fase1", "dati_normattiva.csv")
    ultima_mod_zone = get_file_modification_date(zona_path)
    print(f"Zone climatiche (Normattiva) - Ultimo aggiornamento: {ultima_mod_zone}")
    if ultima_mod_zone != "File non trovato":
        while True:
            risposta_zone = input(
                "Vuoi aggiornare la lista dei comuni con le zone climatiche estratti da normattiva? (SI/NO): ").strip().upper()
            if risposta_zone == "SI":
                refresh_join_data(regione)
                print("Lista comuni aggiornata con le zone climatiche.")
                break
            elif risposta_zone == "NO":
                break
            else:
                print("Risposta non valida. Scrivi 'SI' oppure 'NO'.")

    while True:
        coeff_moltiplicativo = input(
            "Specifica il coefficiente moltiplicativo per la domanda energetica\n"
            "(inserisci 1 o premi invio per lasciare invariato): "
        ).strip()
        if coeff_moltiplicativo == "":
            coeff_moltiplicativo = 1.0
            break
        try:
            coeff_moltiplicativo = float(coeff_moltiplicativo)
            if coeff_moltiplicativo <= 0:
                print("Il valore deve essere maggiore di zero.")
                continue
            break
        except ValueError:
            print("Valore non valido. Inserisci un numero valido (usa il punto per i decimali).")

    # Calcolo domanda energetica
    print("Calcolo della domanda energetica in corso...")
    try:
        calcola_domanda_energetica(com_safe, prov_safe, fabbricati_tipo, coeff_moltiplicativo)
        print("Domanda energetica calcolata con successo.")
    except Exception as e:
        print(f"Errore durante il calcolo della domanda energetica: {e}")
        sys.exit(1)

    if exist_vincoli:
        while True:
            risposta_vincoli = input(
                "Vuoi considerare i vincoli nel calcolo dell'offerta energetica? (SI/NO): ").strip().upper()
            if risposta_vincoli in ("SI", "NO"):
                use_vincoli = risposta_vincoli == "SI"
                break
            else:
                print("Risposta non valida. Scrivi 'SI' oppure 'NO'.")
    else:
        use_vincoli = False

    # Selezione pannello
    pannelli_df = get_pannelli()
    # Mostra i pannelli disponibili
    mostra_pannelli(pannelli_df)

    # Selezione pannello da utilizzare
    while True:
        try:
            indice_pannello = int(input("Seleziona il numero del pannello che preferisci: ")) - 1
            if 0 <= indice_pannello < len(pannelli_df):
                break
            else:
                print("Indice non valido. Riprova.")
        except ValueError:
            print("Input non valido. Inserisci un numero.")

    # Mostra i dettagli del pannello selezionato
    pannello_selezionato = pannelli_df.iloc[indice_pannello]
    print("\nPannello selezionato:")
    print(tabulate(pannello_selezionato.to_frame().T, headers="keys", tablefmt="grid", showindex=False))

    # Costruzione path
    tif_path = os.path.join("offerta", "grass_gis", "irradiance_tif",
                            f"irradianza_annua_{prov_safe}_{com_safe}_kwh.tif")
    dsm_path = os.path.join("input_dsm", f"DSM_{prov_safe}_{com_safe}.tif")

    esiste_tif = os.path.exists(tif_path)
    esiste_dsm = os.path.exists(dsm_path)

    if esiste_tif and esiste_dsm:
        ultima_mod_tif = get_file_modification_date(tif_path)
        print(f"Irradianza annua - Ultimo aggiornamento: {ultima_mod_tif}")
        while True:
            risposta_ricalcolo = input("Vuoi ricalcolare il tif dell'irradianza annua? (SI/NO): ").strip().upper()
            if risposta_ricalcolo == "SI":
                print("Calcolo dell'offerta energetica in corso...")
                refresh_offerta_energetica(prov_safe, com_safe, indice_pannello, use_vincoli=use_vincoli)
                break
            elif risposta_ricalcolo == "NO":
                print("Calcolo dell'offerta energetica in corso...")
                calcolo_offerta_energetica(prov_safe, com_safe, indice_pannello, use_vincoli=use_vincoli)
                break
            else:
                print("Risposta non valida. Scrivi 'SI' oppure 'NO'.")
    elif esiste_dsm and not esiste_tif:
        print("Calcolo dell'offerta energetica in corso...")
        calcolo_offerta_energetica(prov_safe, com_safe, indice_pannello, use_vincoli=use_vincoli)
    elif esiste_tif and not esiste_dsm:
        ultima_mod_tif = get_file_modification_date(tif_path)
        print(f"DSM assente. Utilizzo il tif di irradianza già presente (Ultimo aggiornamento: {ultima_mod_tif}).")
        print("Calcolo dell'offerta energetica in corso...")
        calcolo_offerta_energetica(prov_safe, com_safe, indice_pannello, use_vincoli=use_vincoli)
    else:
        print(
            f"Non sono stati trovati né il DSM ({dsm_path}) né il tif di irradianza ({tif_path}) per {prov_safe} - {com_safe}. Impossibile continuare.")
        sys.exit(1)

    print("Offerta energetica calcolata con successo.")

    # Richiesta della soglia di autosufficienza all'utente
    while True:
        try:
            percentuale_autosuff = float(input(
                "Inserisci la soglia di autosufficienza (percentuale tra 1 e 100):\n"
                "La soglia di autosufficienza indica la quota minima di deficit energetico\n"
                "che deve essere coperta dal surplus per permettere l’aggregazione tra zone.\n"
                "Ad esempio, inserendo 55, le aggregazioni saranno possibili solo se almeno il 55% del deficit può essere coperto dal surplus.\n"
                "Valore desiderato: "
            ))
            if 0 < percentuale_autosuff <= 100:
                break
            else:
                print("Inserisci un valore compreso tra 1 e 100 (inclusi).")
        except ValueError:
            print("Input non valido. Inserisci un numero.")

    # Chiedo all'utente se vuole impostare una distanza massima per il join
    while True:
        risposta = input(
            "Vuoi specificare una distanza massima per l'associazione tra edifici? (SI/NO): ").strip().upper()
        if risposta == "SI":
            # Seconda domanda: fissa o diversa a ogni iterazione
            while True:
                risposta_tipo = input(
                    "Vuoi inserire una distanza massima fissa per tutte le iterazioni, "
                    "o vuoi specificarla ad ogni iterazione? (SI -> fissa / NO -> iterazione): ").strip().upper()
                if risposta_tipo == "SI":
                    # Distanza fissa per tutte le iterazioni
                    while True:
                        distanza_input = input("Inserisci la distanza massima (in metri): ").strip()
                        try:
                            distanza_max = float(distanza_input)
                            if distanza_max > 0:
                                distanza_iterativa = False
                                break
                            else:
                                print("La distanza deve essere maggiore di zero.")
                        except ValueError:
                            print("Valore non valido. Inserisci un numero.")
                    break
                elif risposta_tipo == "NO":
                    distanza_iterativa = True
                    distanza_max = None
                    break
                else:
                    print("Risposta non valida. Scrivi 'SI' oppure 'NO'.")
            break
        elif risposta == "NO":
            distanza_iterativa = False
            distanza_max = None
            break
        else:
            print("Risposta non valida. Scrivi 'SI' oppure 'NO'.")

    print("Creazione PEB/NEB in corso...")
    num_peb, num_neb = crea_peb_neb(prov_safe, com_safe)
    print(f"PEB creati: {num_peb}, NEB creati: {num_neb}")

    print("Interazione PEB/NEB in corso...")

    if not distanza_iterativa:
        # Caso distanza max fissa o nessun limite: uso la funzione batch
        ciclo_interazione_peb_neb(
            prov_safe, com_safe, percentuale_autosuff, distanza_max=distanza_max)
    else:
        # Caso distanza iterativa: ciclo e chiedo input ogni volta
        script_dir = os.path.dirname(os.path.abspath(__file__))
        BASE_DIR = os.path.abspath(os.path.join(script_dir, "model_builder_shapefiles", f"{prov_safe}_{com_safe}"))
        OUTPUTS_DIR = os.path.join(BASE_DIR, "outputs")
        input_neg = os.path.join(BASE_DIR, "input", "neb", f"NEB_{prov_safe}_{com_safe}.gpkg")
        input_pos = os.path.join(BASE_DIR, "input", "peb", f"PEB_{prov_safe}_{com_safe}.gpkg")

        gdf_peb_init = gpd.read_file(input_pos)
        gdf_neb_init = gpd.read_file(input_neg)
        ncer_layer_name = "ncer"

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
            # Chiedi la distanza max per questa iterazione
            while True:
                distanza_input = input(
                    f"[Iterazione {step_result['n_iter']}] Inserisci la distanza massima in metri (invio per nessun limite): ").strip()
                if distanza_input == "":
                    distanza_max_iter = None
                    break
                try:
                    distanza_max_iter = float(distanza_input)
                    if distanza_max_iter > 0:
                        break
                    else:
                        print("La distanza deve essere maggiore di zero.")
                except ValueError:
                    print("Valore non valido. Inserisci un numero o lascia vuoto per nessun limite.")

            step_result = step_interazione_peb_neb(
                provincia=prov_safe,
                comune=com_safe,
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
                is_distanza_iterativa = True
            )
            if not step_result["continue"]:
                break

    print("Interazione PEB/NEB completata.")
    report_interazione_outputs(prov_safe, com_safe)
    print("Analisi completata con successo. I risultati sono disponibili nella cartella "
          "'Data_Collection' e 'model_builder_shapefiles'.")

# ==================== AVVIO ====================

if __name__ == "__main__":
    main()