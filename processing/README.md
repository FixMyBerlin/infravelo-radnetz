# Processing: TILDA → Radvorrangnetz

Die Pipeline überträgt die TILDA-Radinfrastruktur auf das Radvorrangnetz (RVN) und erzeugt daraus die Datensätze A–C.

Alle Pfade in diesem Ordner sind relativ zu `processing/`. Die Shell-Skripte wechseln selbst hierher und können von überall aufgerufen werden. Gemeinsame Eingangsdaten liegen im Projekt-Root unter `data/`. `processing/data` ist ein Symlink darauf.

Das System nutzt Zwischendateien zur Beschleunigung, was zu **Caching-Problemen** führen kann. Bei Problemen: `output`-Ordner löschen oder `--clean-cache` verwenden.

Siehe [REQUIREMENTS.md](./REQUIREMENTS.md) für Geodaten-Anforderungen. *Getestet mit Python 3.13.3.*

## Setup

Das Python-Environment liegt im Projekt-Root. Für das Map-Matching wird zusätzlich Rust (`cargo`) benötigt.

```sh
# im Projekt-Root
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Ordner

- `data-raw-tilda/` – Rohdaten aus den TILDA-Exporten (bikelanes, roads, roadsPathClasses)
- `scripts/` – Aufbereitung von TILDA und RVN, Exporte (siehe [scripts/README.md](./scripts/README.md))
- `map-matching/` – HMM-/Viterbi-Map-Matching in Rust (siehe [map-matching/README.md](./map-matching/README.md))
- `helpers/` – gemeinsame Python-Module der Verarbeitungsschritte
- `validation/` – Validierung der Ergebnisse
- `output/` – alle erzeugten Dateien
- `output-bbox/` – Ausgaben einer Verarbeitung mit `--view` (Bounding Box)
- `output-last-run/` – Backup der Ausgaben vom letzten Lauf
- `QGIS QA Processing.qgz`, `QGIS Aggregated Visualization.qgz` – QGIS-Projekte zur Kontrolle

## Verarbeitungskette

```sh
cd processing
./process_tilda_data.sh   # 1. TILDA-Daten vorbereiten
./process_rvn.sh          # 2. RVN vorbereiten
./execute_processing.sh   # 3. Hauptverarbeitung
./run_validation.sh       # 4. Validierung

# Optional
../.venv/bin/python scripts/convert_to_geojson.py   # GeoJSON-Export
./copy_to_tilda_static.sh                           # Kopie nach ../../tilda-static-data
```

`execute_processing.sh` und `run_validation.sh` akzeptieren `--clip neukoelln|norden|sueden`. `execute_processing.sh` außerdem `--start-step 1-4` und `--clean-cache`.

### 1. TILDA-Daten vorbereiten (`process_tilda_data.sh`)

Schneidet TILDA-Rohdaten (`data-raw-tilda/`) auf Berlin zu und übersetzt Attribute zu RVN-Format.

**Ausgabe**: `data/TILDA *.fgb` und `output/TILDA-translated/*.fgb`

### 2. RVN vorbereiten (`process_rvn.sh`)

Teilt das RVN an virtuellen Knotenpunkten, weist `element_nr` zu und reichert es mit dem Detailnetz an.

**Ausgabe**: `output/rvn/vorrangnetz_details_combined_rvn.fgb` (Netz für das Map-Matching)

### 3. Hauptverarbeitung (`execute_processing.sh`)

#### Schritt 1-2: Map-Matching (`map-matching/`, Rust)
Matcht die TILDA-Wege per Hidden Markov Model und Viterbi auf die gerichteten RVN-Kanten, teilt jede Kante nach den Routen-Anteilen auf und überträgt die TILDA-Attribute.

**Ausgabe**: `output/map-matching/network_enriched_hmm.fgb`, von `execute_processing.sh` nach `output/snapping_network_enriched.fgb` kopiert

#### Schritt 3: Schutzstreifen-Konvertierung (`start_bikelane_conversion.py`)
Konvertiert Schutzstreifen unter bestimmten Bedingungen:
- An Bushaltestellen → Radfahrstreifen (nur rechte Seite, benachbart zu Radfahrstreifen)
- Kurze Segmente (<50m) → Radfahrstreifen (benachbart zu Radfahrstreifen)
- Kurze Segmente an Knotenpunkten → Kreuzungswege

**Ausgabe**: `output/snapping_converted_bikelanes.fgb`

#### Schritt 3b: Override-Anwendung (`start_overriding.py`)
Wendet manuelle Overrides aus `data/override_ways.gpkg` und `data/override_ways.txt` auf Netzwerkdaten an. Überschreibt gezielt Attribute (fuehr, ofm, protek, pflicht, breite, farbe, trennstreifen, nutz_beschr, verkehrsri).

**Ausgabe**: `output/snapping_with_overrides.fgb`

#### Schritt 4: Aggregation (`start_aggregation.py`)
Aggregiert Segmente nach `element_nr` + `ri` (Fahrtrichtung). Regelbasiert: längster Abschnitt für Führungsform/Bezirk/Material, schlechteste Ausprägung für Breite/Trennstreifen.

**Ausgabe**: `output/aggregated_rvn_final.gpkg` (Layer: `hinrichtung`, `gegenrichtung`)

### 4. Validierung (`run_validation.sh`)

Prüft virtuelle Knotenpunkte, TILDA-Knotenpunkte, Datensatz B und C sowie Überschneidungen der manuellen Wege-Listen. Logs in `validation/output/`.

## Helper-Module (`helpers/`)
- `globals.py`: Konstanten (CRS, Pfade)
- `district_assignment.py`: Bezirkszuweisung
- `clipping.py`: Regionale/Viewport-Zuschnitte
- `convert_*.py`: Schutzstreifen-Konvertierungslogik
- `override_edges.py`: Override-Verarbeitung
