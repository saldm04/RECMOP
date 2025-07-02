from tabulate import tabulate
from utils import get_pannelli, get_regione_from_provincia, safe_name, \
    normalize_dsm_input, \
    get_file_modification_date, configure_logging_globale, normalize_fabbricati_input_auto
from offerta.grass_gis.calcolo_offerta_energetica import calcolo_offerta_energetica, refresh_offerta_energetica
from data_extraction.calcolo_domanda_energetica import calcola_domanda_energetica_zc_range
from data_extraction.join_data_normattiva_varcens_basiterr import refresh_join_data
from model_builder.creazione_peb_neb import crea_peb_neb
from model_builder.interazione_peb_neb import ciclo_interazione_peb_neb
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

def main():
    # === CONFIGURAZIONE LOGGING ===
    usa_log = input("Vuoi visualizzare i log delle operazioni? (SI/NO): ").strip().upper()
    configure_logging_globale(attivo=(usa_log == "SI"))
    if usa_log == "SI":
        logger.info("Logging abilitato.")

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
        "L'analisi verrà effettuata sull'intersezione tra i fabbricati e il DSM forniti.\n"
    )

    # Inserimento dati
    comune = input("Inserisci il nome del comune: ")
    com_safe = safe_name(comune)
    provincia = input("Inserisci la provincia del comune: ")
    prov_safe = safe_name(provincia)

    try:
        # Normalizzazione e controllo fabbricati
        fabbricati_tipo = normalize_fabbricati_input_auto(os.path.abspath("FABBRICATI"), prov_safe, com_safe)
        normalize_dsm_input(os.path.abspath("input_dsm"), prov_safe, com_safe)
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
        risposta_siape = input(
            "Vuoi aggiornare dati delle prestazioni energetiche del SIAPE? (SI/NO): ").strip().upper()
        if risposta_siape == 'SI':
            run_estrazione_siape(fabbricati_tipo)
            print("Analisi SIAPE completata.")

    # Aggiornamento zone climatiche
    zona_path = os.path.join("Data_Collection", "csv_tables-fase1", "dati_normattiva.csv")
    ultima_mod_zone = get_file_modification_date(zona_path)
    print(f"Zone climatiche (Normattiva) - Ultimo aggiornamento: {ultima_mod_zone}")
    if ultima_mod_zone != "File non trovato":
        risposta_zone = input(
            "Vuoi aggiornare la lista dei comuni con le zone climatiche estratti da normattiva? (SI/NO): ").strip().upper()
        if risposta_zone == 'SI':
            refresh_join_data(regione)
            print("Lista comuni aggiornata con le zone climatiche.")

    # Calcolo domanda energetica
    print("Calcolo della domanda energetica in corso...")
    calcola_domanda_energetica_zc_range(com_safe, prov_safe)
    print("Domanda energetica calcolata con successo.")

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

    # Controllo esistenza tif irradiance
    tif_path = os.path.join("offerta", "grass_gis", "irradiance_tif", f"irradianza_annua_{prov_safe}_{com_safe}_kwh.tif")
    if os.path.exists(tif_path):
        ultima_mod_tif = get_file_modification_date(tif_path)
        print(f"Irradianza annua - Ultimo aggiornamento: {ultima_mod_tif}")
        risposta_ricalcolo = input("Vuoi ricalcolare il tif dell'irradianza annua? (SI/NO): ").strip().upper()
        if risposta_ricalcolo == 'SI':
            print("Calcolo dell'offerta energetica in corso...")
            refresh_offerta_energetica(prov_safe, com_safe, indice_pannello)
        else:
            print("Calcolo dell'offerta energetica in corso...")
            calcolo_offerta_energetica(prov_safe, com_safe, indice_pannello)
    else:
        print("Calcolo dell'offerta energetica in corso...")
        calcolo_offerta_energetica(prov_safe, com_safe, indice_pannello)

    print("Offerta energetica calcolata con successo.")

    # Creazione e interazione PEB/NEB
    print("Creazione PEB/NEB in corso...")
    crea_peb_neb(prov_safe, com_safe)
    print("Interazione PEB/NEB in corso...")
    ciclo_interazione_peb_neb(prov_safe, com_safe)

    print("Analisi completata con successo. I risultati sono dipsonibili nella cartella "
          "'Data_Collection' e 'model_builder_shapefiles'.")


# ==================== AVVIO ====================

if __name__ == "__main__":
    main()
