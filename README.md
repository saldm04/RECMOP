# RECMOP - Renewable Energy Communities: Monitoring, Optimization and Planning

## Descrizione del progetto

Il progetto **RECMOP** ("Renewable Energy Communities: Monitoring, Optimization and Planning") affronta il problema dell’inefficienza energetica degli edifici e della povertà energetica, promuovendo lo sviluppo delle **Comunità Energetiche Rinnovabili (CER)**.

Le CER, costituite da cittadini, PMI e autorità locali, consentono la produzione, il consumo e la condivisione di energia rinnovabile a livello locale, offrendo benefici ambientali, economici e sociali.

**RECMOP** mira a superare barriere come scarsa informazione, predominanza degli aspetti tecnologici ed economici, e mancata integrazione con la pianificazione urbanistica, attraverso:

* Monitoraggio delle CER per valutarne gli impatti.
* Ottimizzazione delle configurazioni spazio-temporali.
* Pianificazione urbana supportata da dati trasparenti e accessibili.

**Partner:** UNISA (capofila), LATITUDO 40, NEXSOFT.

---

## Architettura e principali moduli

* **calcola\_area\_poligoni.py**: Calcolo delle aree dei poligoni.
* **normattiva.py**: Parsing zone climatiche da Normattiva.
* **siape.py**: Estrazione dati energetici SIAPE.
* **estrazione\_dati\_basi\_territoriali.py**: Estrazione dati territoriali ISTAT.
* **estrazione\_dati\_variabili\_censuarie.py**: Estrazione variabili censuarie.
* **join\_data\_normattiva\_varcens\_basiterr.py**: Join dati climatici e censuari.
* **calcolo\_domanda\_energetica.py**: Pipeline domanda energetica edifici.
* **calcolo\_offerta\_energetica.py**: Calcolo offerta energetica (irradianza, pannelli FV).
* **creazione\_peb\_neb.py**: Generazione PEB (Positive Energy Buildings) e NEB (Negative Energy Buildings).
* **interazione\_peb\_neb.py**: Algoritmo aggregazione e formazione CER.
* **interrogazione\_wfs\_catastale.py**: Query al WFS catastale.
* **utils.py**: Utility generali (normalizzazione, logging, GIS).
* **main.py**: Orchestratore principale, interazione utente e pipeline.

---

## Struttura delle cartelle dati

* `FABBRICATI/fabbricati_provincia_comune` con shapefile edifici.
* `input_dsm/DSM_provincia_comune.tif` DSM raster.
* `VINCOLI/vincoli_provincia_comune` shapefile vincoli urbanistici (opzionale).
* `offerta/panel/panels.csv` database pannelli FV.
* `offerta/grass\_gis/irradiance\_tif/irradianza_annua_provincia_comune_kwh.tif` output raster irradianza.
* `Data\_Collection/` e `model\_builder\_shapefiles/` output analisi.

---

## Configurazione ambiente `.env`

File `.env` necessario per GRASS GIS (esempio in `env_example.txt`):

```dotenv
GRASS_BASE="C:\\Program Files\\GRASS GIS 8.4"
GRASS_GISDB="C:\\Users\\utente\\Documents\\grassdata"
GRASS_MAPSET=PERMANENT
```

---

## Requisiti

* **Python ≥ 3.9**
* **GRASS GIS 8.4**
* Sistema operativo: Windows o Linux

Installa dipendenze:

```bash
pip install -r requirements.txt
```

---

## Come utilizzare il sistema

1. Prepara cartelle dati.
2. Configura `.env` per GRASS GIS.
3. Installa dipendenze.
4. Avvia script principale:

```bash
python main.py
```

---

## Flusso guidato (da `main.py`)

* Abilitazione log.
* Inserimento comune e provincia.
* Controllo e normalizzazione input.
* Aggiornamento dati SIAPE e zone climatiche.
* Calcolo domanda energetica.
* Gestione vincoli.
* Selezione pannello FV.
* Calcolo offerta energetica.
* Soglia autosufficienza.
* Aggregazione edifici (opzionale distanza massima).

---

## Output

* Domanda e offerta energetica (CSV, GPKG).
* PEB/NEB e CER (GPKG).
* Tabelle intermedie dati climatici e censuari (CSV).
* Log operazioni.

---

## Note tecniche

* Necessaria installazione e configurazione di GRASS GIS per calcolo irradianza (`r.sun`).
* Gestione automatica normalizzazione dati input.
* Output salvati in `Data_Collection/` e `model_builder_shapefiles/`.
* Documentazione dettagliata nei docstring moduli Python.

---

## Esempio input utente

```
Inserisci il nome del comune: napoli
Inserisci la provincia del comune: napoli
Seleziona il numero del pannello che preferisci: 3
Inserisci la soglia di autosufficienza (percentuale tra 1 e 100): 55
Vuoi specificare una distanza massima per l'associazione tra edifici? (SI/NO): NO
```

---
