#normalizza_input_fabbricati (funzione che controlla il formato della tabella e il nome file) !!!Chiedere reinserimento in caso errato
"""
Inserisci il nome della cartella che contiene i file shapefile (.shp, .dbf, .cpg, .shx, .prj) relativi ai fabbricati del comune di interesse.
La cartella deve essere nominata seguendo questo formato, quindi senza lettere maiuscole e senza spazi(se i nomi li hanno inserire '-'), ma separati da underscore come segue:
fabbricati_provincia_comune
Esempio:
1)fabbricati_napoli_poggiomarino
2)fabbricati_napoli_torre-annunziata
"""

#normalizza_DSM (funzione che controlla il formato del file)  !!!Chiedere reinserimento in caso errato
"""
Inserisci il nome del file DSM seguendo il seguente formato:
DSM_provincia_comune.tif
DSM in maiuscolo mentre provincia e comune tutto minuscolo, se i nomi hanno spazi fare come prima, inserire '-' tra gli spazi
Esempio:
1)DSM_napoli_poggiomarino.tif
2)DSM_napoli_torre-annunziata.tif
"""

#salvati comune e provincia prendendoli dal nome dei file separati tra underscore
#salvati regione = get_regione_from_provincia(provincia)
"""
Vuoi aggiornare dati delle prestazioni energetiche del SIAPE?
Esempio risposta:
SI           NO
#  SI = invoca run_estrazione_siape
Vuoi aggiornare la lista dei comuni con le zone climatiche estratti da normattiva?
Esempio risposta:
SI           NO
#  SI = invoca refresh_join_data(regione) + invoca calcola_domanda_energetica(comune, provincia)
#  NO = invoca calcola_domanda_energetica(comune, provincia)
"""

#**DOMANDA CALCOLATA**

"""
Seleziona pannello che preferisci:
    Marca          Modello    Potenza(Wp)  Efficienza(%)    Tecnologia   Prezzo  Superficie  Superifice+30%  
1) Sonnenkraft       ...................
2) FuturaSun         ...................
...
# Invoca get_pannelli() che ritorna un DataFrame e stampa quest'ultimo come specificato qui sopra prendentodi tutti i dati specificati 
Esempio risposta:
1
Prendi la risposta controllando che sia un numero e sottrai 1 perchè indica l'indice del csv
"""

"""
!!! Form da stampare solo se esiste già il tif (controllare se esiste il tif /offerta/grass_gis/irradiance_tif/irradianza_annua_provincia_comune.tif)
Vuoi ricalcolare il tif dell'irradianza annua?
Esempio risposta:
SI           NO
#  SI = invoca refresh_offerta_energetica(provincia, comune, indice_pannello)
#  NO = invoca calcola_offerta_energetica(provincia, comune, indice_pannello)
"""

#**OFFERTA CALCOLATA**


#Start del Model Builder
"""
crea_peb_neb(provincia, comune)   (creazione shp di input)
ciclo_interazione_peb_neb(provincia, comune)   (creazione shp di output)
"""


import os
import re
import pandas as pd

from utils import get_pannelli, get_regione_from_provincia

from data_extraction_siape.siape_zc_range import run_estrazione_siape
from offerta.grass_gis.calcolo_offerta_energetica import calcolo_offerta_energetica, refresh_offerta_energetica
from data_extraction.calcolo_domanda_energetica import calcola_domanda_energetica
from data_extraction.join_data_normattiva_varcens_basiterr import refresh_join_data
from model_builder.creazione_peb_neb import crea_peb_neb
from model_builder.interazione_peb_neb import ciclo_interazione_peb_neb


# ==================== FUNZIONI DI CONTROLLO INPUT ====================

def normalizza_input_fabbricati():
    while True:
        cartella = input("Inserisci il nome della cartella dei fabbricati: ").strip()
        if re.match(r'^fabbricati_[a-z]+_[a-z0-9\-]+$', cartella):
            return cartella
        print("Formato errato! Riprova.")

def normalizza_DSM():
    while True:
        file_DSM = input("Inserisci il nome del file DSM: ").strip()
        if re.match(r'^DSM_[a-z]+_[a-z0-9\-]+\.tif$', file_DSM):
            return file_DSM
        print("Formato errato! Riprova.")

# ==================== MAIN ====================

import os

def main():
    # Input cartella fabbricati
    cartella_fabbricati = normalizza_input_fabbricati()
    _, provincia, comune = cartella_fabbricati.split('_')
    regione = get_regione_from_provincia(provincia)

    # Input file DSM
    file_DSM = normalizza_DSM()

    # Aggiornamento SIAPE
    risposta_siape = input("Vuoi aggiornare dati delle prestazioni energetiche del SIAPE? (SI/NO): ").strip().upper()
    if risposta_siape == 'SI':
        run_estrazione_siape()

    # Aggiornamento zone climatiche e calcolo domanda
    risposta_zone = input("Vuoi aggiornare la lista dei comuni con le zone climatiche estratti da normattiva? (SI/NO): ").strip().upper()
    if risposta_zone == 'SI':
        refresh_join_data(regione)
    calcola_domanda_energetica(comune, provincia)

    # Selezione pannello
    pannelli_df = get_pannelli()

    # Normalizzazione intestazioni colonna
    pannelli_df.columns = pannelli_df.columns.str.strip().str.replace('\ufeff', '')

    print("\nSeleziona pannello che preferisci:")
    for idx, row in pannelli_df.iterrows():
        print(f"{idx+1}) {row['Marca']:15} {row['Modello']:12} {row['Potenza(Wp)']:>8}  {row['Efficienza(%)']:>8}  "
              f"{row['Tecnologia']:15} {row['Prezzo']:>6}  {row['Superficie']:>5}  {row['Dimensione']:>5}")

    while True:
        try:
            indice_pannello = int(input("Seleziona il numero del pannello: ")) - 1
            if 0 <= indice_pannello < len(pannelli_df):
                break
        except ValueError:
            pass
        print("Valore non valido! Riprova.")

    # Controllo esistenza tif irradiance
    tif_path = os.path.join("offerta", "grass_gis", "irradiance_tif", f"irradianza_annua_{provincia}_{comune}.tif")
    if os.path.exists(tif_path):
        risposta_ricalcolo = input("Vuoi ricalcolare il tif dell'irradianza annua? (SI/NO): ").strip().upper()
        if risposta_ricalcolo == 'SI':
            refresh_offerta_energetica(provincia, comune, indice_pannello)
        else:
            calcolo_offerta_energetica(provincia, comune, indice_pannello)
    else:
        calcolo_offerta_energetica(provincia, comune, indice_pannello)

    # Creazione e interazione PEB/NEB
    crea_peb_neb(provincia, comune)
    ciclo_interazione_peb_neb(provincia, comune)


# ==================== AVVIO ====================

if __name__ == "__main__":
    main()
