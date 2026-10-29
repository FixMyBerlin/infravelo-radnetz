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
- `output-last-run/` – Backup der Ausgaben vom letzten Lauf
- `QGIS QA Processing.qgz`, `QGIS Aggregated Visualization.qgz` – QGIS-Projekte zur Kontrolle

## Verarbeitungskette

```sh
cd processing
./process_tilda_data.sh   # 1. TILDA-Daten vorbereiten
./process_radnetz.sh      # 2. Netz vorbereiten (RVN oder REN+)
./execute_processing.sh   # 3. Hauptverarbeitung
./run_validation.sh       # 4. Validierung

# Optional
../.venv/bin/python scripts/convert_to_geojson.py   # GeoJSON-Export der Datensätze A, B, C
./copy_to_tilda_static.sh                           # Kopie nach ../../tilda-static-data/geojson/region-infravelo, danach CSV für TILDA (../tilda-pseudo-tags, einchecken)
```

`execute_processing.sh` und `run_validation.sh` akzeptieren `--clip neukoelln|norden|sueden`. `execute_processing.sh` außerdem `--start-step 1-4` und `--clean-cache`.

### Zielnetz (`--netz`)

Die Prozessierung läuft wahlweise auf dem Radvorrangnetz oder auf dem REN+, also allen Netzquellen gemeinsam (`../ren-network/output/ren_netz_gesamt.gpkg`). `process_radnetz.sh`, `execute_processing.sh`, `scripts/prepare_tilda_routing.py` und das Rust-Matching nehmen dafür `--netz rvn|ren`, Standard ist `rvn`. Beide Netze werden an denselben virtuellen Knotenpunkten geteilt (`data/Virtuelle-Knotenpunkte.gpkg`).

```sh
../.venv/bin/python scripts/prepare_tilda_routing.py --netz ren   # TILDA-Routing ohne RVN-Zuschnitt
./process_radnetz.sh --netz ren
./execute_processing.sh --netz ren
./run_validation.sh --netz ren
../.venv/bin/python scripts/convert_to_geojson.py --netz ren
./copy_to_tilda_static.sh --netz ren   # braucht die Ordner infravelo-ren-datensatz-{a,b,c}-fortlaufend in tilda-static-data
```

| | `rvn` | `ren` |
|---|---|---|
| Eingangsnetz | `data/Berlin Radvorrangsnetz.fgb` | `../ren-network/output/ren_netz_gesamt.gpkg` |
| TILDA-Routing | `output/TILDA-routing/` (auf den RVN-Puffer zugeschnitten) | `output/TILDA-routing-ren/` (ganz Berlin) |
| Netz für das Matching | `output/rvn/vorrangnetz_details_combined_rvn.fgb` | `output/ren/ren_netz_details_combined.fgb` |
| Matching | `output/map-matching/` | `output/map-matching-ren/` |
| Folgeschritte | `output/snapping_*.fgb`, `output/aggregated_rvn_final.gpkg` | dieselben Namen mit `_ren`, z. B. `output/aggregated_rvn_final_ren.gpkg` |
| GeoJSON (`convert_to_geojson.py`) | `output/{matched_tilda_ways,snapping_converted_bikelanes,aggregated_rvn_final}.geojson.gz` | dieselben Namen mit `_ren`; B und C mit Spalte `radverkehrsnetz` für den Pseudo-Tag |
| TILDA (`copy_to_tilda_static.sh`) | `infravelo-datensatz-{a,b,c}-fortlaufend` | `infravelo-ren-datensatz-{a,b,c}-fortlaufend` |

Die Pfade je Netz stehen in `helpers/netz.py` und in `map-matching/config/default.toml` (`[netze.*]`). Beim REN+ wird dessen `element_nr` übernommen. Nur Teilkanten an virtuellen Knotenpunkten bekommen eine neu berechnete Nummer, wie beim Radvorrangnetz.

### 1. TILDA-Daten vorbereiten (`process_tilda_data.sh`)

Schneidet TILDA-Rohdaten (`data-raw-tilda/`) auf Berlin zu und übersetzt Attribute zu RVN-Format.

**Ausgabe**: `data/TILDA *.fgb` und `output/TILDA-translated/*.fgb`

### 2. Netz vorbereiten (`process_radnetz.sh`)

Teilt das RVN (bzw. mit `--netz ren` das REN+) an virtuellen Knotenpunkten, weist `element_nr` zu und reichert es mit dem Detailnetz an.

**Ausgabe**: `output/rvn/vorrangnetz_details_combined_rvn.fgb` bzw. `output/ren/ren_netz_details_combined.fgb` (Netz für das Map-Matching)

### 3. Hauptverarbeitung (`execute_processing.sh`)

#### Schritt 1-2: Map-Matching (`map-matching/`, Rust)
Matcht die TILDA-Wege per Hidden Markov Model und Viterbi auf die gerichteten RVN-Kanten, teilt jede Kante nach den Routen-Anteilen auf und überträgt die TILDA-Attribute.

**Ausgabe**: `output/map-matching/network_enriched_hmm.fgb` (REN+: `output/map-matching-ren/`), von `execute_processing.sh` nach `output/snapping_network_enriched.fgb` (REN+: `…_ren.fgb`) kopiert

#### Schritt 3: Schutzstreifen-Konvertierung (`start_bikelane_conversion.py`)
Konvertiert Schutzstreifen unter bestimmten Bedingungen:
- An Bushaltestellen → Radfahrstreifen (nur rechte Seite, benachbart zu Radfahrstreifen)
- Kurze Segmente (<50m) → Radfahrstreifen (benachbart zu Radfahrstreifen)
- Kurze Segmente an Knotenpunkten → Kreuzungswege

**Ausgabe**: `output/snapping_converted_bikelanes.fgb`

#### Schritt 4: Aggregation (`start_aggregation.py`)
Aggregiert Segmente nach `element_nr` + `ri` (Fahrtrichtung). Regelbasiert: längster Abschnitt für Führungsform/Bezirk/Material, schlechteste Ausprägung für Breite/Trennstreifen.

**Ausgabe**: `output/aggregated_rvn_final.gpkg` (Layer: `hinrichtung`, `gegenrichtung`)

### 4. Validierung (`run_validation.sh`)

Prüft virtuelle Knotenpunkte, TILDA-Knotenpunkte, Datensatz B und C sowie Überschneidungen der manuellen Wege-Listen. Logs in `validation/output/`.

## Helper-Module (`helpers/`)
- `globals.py`: Konstanten (CRS, Pfade)
- `district_assignment.py`: Bezirkszuweisung
- `clipping.py`: Regionale Zuschnitte
- `convert_*.py`: Schutzstreifen-Konvertierungslogik
- `override_edges.py`: Override-Verarbeitung
