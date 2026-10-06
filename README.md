# infraVelo Radnetz

Dieses Projekt hat zum Ziel, bereits verarbeitete Fahrrad-Geodaten aus [TILDA](https://tilda-geo.de/) (basierend auf OpenStreetMap) in das Berliner [Detailnetz](https://gdi.berlin.de/geonetwork/geonetwork/api/records/cf374cd3-d0b8-3e6a-92c3-75e18dd595a1) zu überführen.

## Ordnerstruktur

Jeder Ordner ist für eine Aufgabe zuständig und hat eine eigene README.

- [`processing/`](./processing/README.md) – Pipeline TILDA → Radvorrangnetz: TILDA- und RVN-Aufbereitung, Map-Matching (Rust), Schutzstreifen-Konvertierung, Overrides, Aggregation, Validierung. Mit eigenen Outputs.
- [`ren-network/`](./ren-network/README.md) – Einheitliches Netz für REN+ aus Radverkehrsnetz, Hauptstraßennetz und Radschnellverbindungen.
- [`inspector/`](./inspector/README.md) – Web-Tool zur Qualitätssicherung der verarbeiteten Daten.
- [`data/`](./data/README.md) – Gemeinsame Eingangsdaten (Detailnetz, Radvorrangsnetz, Bezirke, manuelle Listen).

## Setup

Python-Abhängigkeiten werden in einem gemeinsamen virtuellen Environment im Projekt-Root installiert:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Für das Map-Matching wird zusätzlich Rust (`cargo`) benötigt.

## Schnellstart

```sh
# Komplette Verarbeitung (Details in processing/README.md)
cd processing
./process_tilda_data.sh && ./process_rvn.sh && ./execute_processing.sh && ./run_validation.sh

# REN+-Netz erzeugen
python ren-network/unify_networks.py

# QA Inspector
cd inspector && npm run dev
```

## Stand 2025 (Radvorrangnetz)

Die Verarbeitung von 2025 mit dem Python-Matching und -Snapping ist im Tag `rvn-final-state` archiviert:

```sh
git worktree add ../radnetz-rvn-2025 rvn-final-state
```

## Projekt-Ordnerstruktur

- `data/` – Eingangsdaten wie Detailnetz, Radvorrangsnetz und weitere Geodaten
- `data-raw-tilda/` – Rohdaten aus den TILDA-Exporten (bikelanes, roads, roadsPathClasses)
- `inspector/` – Code zu Web-basiertes Tool zur Qualitätssicherung der verarbeiteten Daten
- `befahrungsbedarf/` – Eigenständige Auswertung: OSM-Wege am REN+-Netz ohne aktuelle Fotos (Befahrungsbedarf)
- `map-matching/` – Rust-Backend: HMM-/Viterbi-Map-Matching der TILDA-Wege auf das RVN (ersetzt Matching + Snapping)
- `legacy/` – bisherige Python-Skripte für Matching und Snapping (nicht mehr verwendet)
- `output/` – Alle durch die Verarbeitungsskripte erzeugten Ausgabedateien
- `output-bbox/` – Ausgabedateien beschränkt auf einen bestimmten (`--view`) Bounding-Box-Bereich
- `output-last-run/` – Backup der Ausgabedateien vom letzten Verarbeitungslauf
- `processing/` – Python-Skripte für Konvertierung, Overrides und Aggregation der Geodaten
- `scripts/` – Hilfs- und Wrapper-Skripte zur Automatisierung der Verarbeitung
- `validation/` – Skripte und Daten zur Validierung der Ergebnisse

## Das Projekt

Dieses Projekt überführt Fahrrad-Infrastrukturdaten aus OpenStreetMap (aufbereitet durch TILDA) in das strukturierte Berliner Detailnetz. Als Datenquellen dienen das Radvorrangsnetz (RVN), die TILDA-Exporte und das Berliner Straßennetz-Detailnetz. Die Verarbeitung erfolgt in mehreren automatisierten Schritten:

1. **TILDA-Datenaufbereitung** (`process_tilda_data.sh`): Übersetzung und Anreicherung der TILDA-Rohdaten mit zusätzlichen Attributen und Kategorisierungen
2. **Map-Matching** (`map-matching/`, Rust): Die TILDA-Wege werden per Hidden Markov Model und Viterbi auf die gerichteten RVN-Kanten gematcht. Jede Kante wird nach den Routen-Anteilen aufgeteilt und übernimmt die TILDA-Attribute. Das ersetzt das frühere Matching und Snapping (`legacy/`).
3. **Aggregation** (`start_aggregation.py`): Zusammenführung mehrerer OSM-Ways auf einer Detailnetz-Kante zu einem einzigen Feature mit konsolidierten Attributen.

Zusätzliche Skripte verarbeiten Knotenpunkte, Ampeln, Bushaltestellen und weitere Netzwerkelemente, welche in die Datensätze direkt oder indirekt einfließen. Das Wrapper-Skript `execute_processing.sh` führt alle Schritte automatisiert aus und unterstützt optionales Clipping auf bestimmte Regionen (Neukölln, Norden, Süden). Der Web-Inspector ermöglicht die visuelle Qualitätssicherung der Ergebnisse durch interaktive Kartendarstellung und Filterung nach Attributen.

## Lizenzen

Der Quellcode der Verarbeitungsskripte und des Inspectors steht unter der AGPL-3.0-Lizenz. Details findest du in der Datei [LICENSE](./LICENSE).

Die verwendeten Roh-Geodaten sind pro Datei lizenziert, siehe [data/LIZENZEN.md](./data/LIZENZEN.md) (Deutsch).

Die durch die Skripte erzeugten Geodaten sind in [processing/output/LIZENZEN.md](./processing/output/LIZENZEN.md) (Deutsch) beschrieben. Die erzeugten Dateien sind nicht im Repository enthalten, lassen sich aber aus den Rohdaten reproduzieren.
