# infraVelo Radnetz

Dieses Projekt hat zum Ziel, bereits verarbeitete Fahrrad-Geodaten aus [TILDA](https://tilda-geo.de/) (basierend auf OpenStreetMap) in das Berliner [Detailnetz](https://gdi.berlin.de/geonetwork/geonetwork/api/records/cf374cd3-d0b8-3e6a-92c3-75e18dd595a1) zu überführen.

## QA Inspector
Der Inspector dient der Qualitätssicherung (QA).

Starte den Inspector mit:
```sh
cd inspector && npm run dev
```

Alternativ kannst das QGIS-Projekt `QGIS QA Processing.qgz` verwendet werden, das die verschiedenen Ausgabedateien visualisiert.

## RVN Prozessierung

Das Verarbeitungsscript nutzt Python und mehrere Bibliotheken.

Es empfiehlt sich, ein virtuelles Python-Environment (`venv`) anzulegen und die Abhängigkeiten aus `requirements.txt` zu installieren.

Nach dem Erstellen des Environments führe folgende Befehle in der Projekt-Root aus:
```sh
# Falls noch nicht vorhanden: venv anlegen
python3 -m venv .venv

# In einer neuen Shell das venv aktivieren
source .venv/bin/activate

# Abhängigkeiten installieren
pip install -r requirements.txt

# Die Verarbeitungs-Schritte müssen in dieser Reihenfolge ausgeführt werden
./process_tilda_data.sh

./.venv/bin/python processing/start_matching.py
./.venv/bin/python processing/start_snapping.py
./.venv/bin/python processing/start_aggregation.py --input ./output/snapping_converted_bikelanes.fgb
```

```sh
# Kurzvariante zur Ausführung aller Schritte für ein bestimmtes Gebiet:
# --clip <region>  Clips alle Daten auf eine Region (neukoelln, norden, sueden)

# Vorher ausführbar machen: chmod +x execute_processing.sh
# TILDA Daten müssen in ./data-raw-tilda liegen
./process_tilda_data.sh
./process_rvn.sh
./execute_processing.sh

# Alle drei hintereinander
./process_tilda_data.sh && ./process_rvn.sh && ./execute_processing.sh
```

## Projekt-Ordnerstruktur

- `data/` – Eingangsdaten wie Detailnetz, Radvorrangsnetz und weitere Geodaten
- `data-raw-tilda/` – Rohdaten aus den TILDA-Exporten (bikelanes, roads, roadsPathClasses)
- `inspector/` – Code zu Web-basiertes Tool zur Qualitätssicherung der verarbeiteten Daten
- `output/` – Alle durch die Verarbeitungsskripte erzeugten Ausgabedateien
- `output-bbox/` – Ausgabedateien beschränkt auf einen bestimmten (`--view`) Bounding-Box-Bereich
- `output-last-run/` – Backup der Ausgabedateien vom letzten Verarbeitungslauf
- `processing/` – Zentrale Python-Skripte für Matching, Snapping und Aggregation der Geodaten
- `scripts/` – Hilfs- und Wrapper-Skripte zur Automatisierung der Verarbeitung
- `validation/` – Skripte und Daten zur Validierung der Ergebnisse

## Das Projekt

Dieses Projekt überführt Fahrrad-Infrastrukturdaten aus OpenStreetMap (aufbereitet durch TILDA) in das strukturierte Berliner Detailnetz. Als Datenquellen dienen das Radvorrangsnetz (RVN), die TILDA-Exporte und das Berliner Straßennetz-Detailnetz. Die Verarbeitung erfolgt in mehreren automatisierten Schritten:

1. **TILDA-Datenaufbereitung** (`process_tilda_data.sh`): Übersetzung und Anreicherung der TILDA-Rohdaten mit zusätzlichen Attributen und Kategorisierungen
2. **Matching** (`start_matching.py`): Auswahl von OSM-Ways entlang von des Radvorrangsnetzes. Außerdem Anwendung von manuellen Einschlüssen und Ausschlüssen von Wege über OSM-ID.
3. **Snapping** (`start_snapping.py`): Geometrische Anpassung der OSM-Daten an die Detailnetz-Geometrie, sodass die Fahrrad-Infrastruktur exakt auf den Detailnetz-Kanten liegt.
4. **Aggregation** (`start_aggregation.py`): Zusammenführung mehrerer OSM-Ways auf einer Detailnetz-Kante zu einem einzigen Feature mit konsolidierten Attributen.

Zusätzliche Skripte verarbeiten Knotenpunkte, Ampeln, Bushaltestellen und weitere Netzwerkelemente, welche in die Datensätze direkt oder indirekt einfließen. Das Wrapper-Skript `execute_processing.sh` führt alle Schritte automatisiert aus und unterstützt optionales Clipping auf bestimmte Regionen (Neukölln, Norden, Süden). Der Web-Inspector ermöglicht die visuelle Qualitätssicherung der Ergebnisse durch interaktive Kartendarstellung und Filterung nach Attributen.

## Lizenzen

Der Quellcode der Verarbeitungsskripte und des Inspectors steht unter der AGPL-3.0-Lizenz. Details findest du in der Datei [LICENSE](./LICENSE).

Die verwendeten Roh-Geodaten sind pro Datei lizenziert, siehe [data/LIZENZEN.md](./data/LIZENZEN.md) (Deutsch).

Die durch die Skripte erzeugten Geodaten sind in [output/LIZENZEN.md](./output/LIZENZEN.md) (Deutsch) beschrieben. Die erzeugten Dateien sind nicht im Repository enthalten, lassen sich aber aus den Rohdaten reproduzieren.