# infraVelo Radnetz

Dieses Projekt hat zum Ziel, bereits verarbeitete Fahrrad-Geodaten aus [TILDA](https://tilda-geo.de/) (basierend auf OpenStreetMap) in das Berliner [Detailnetz](https://gdi.berlin.de/geonetwork/geonetwork/api/records/cf374cd3-d0b8-3e6a-92c3-75e18dd595a1) zu überführen.

## QA
Der Inspector dient der Qualitätssicherung (QA).

Starte den Inspector mit:
```sh
cd inspector && npm run dev
```

Alternativ kannst das QGIS-Projekt `QGIS QA Processing.qgz` verwendet werden, das die verschiedenen Ausgabedateien visualisiert.

## Verarbeitung

Das Verarbeitungsscript nutzt Python und mehrere Bibliotheken.

Es empfiehlt sich, ein virtuelles Python-Environment (`venv`) anzulegen und die Abhängigkeiten aus `processing/requirements.txt` zu installieren.

Nach dem Erstellen des Environments führe folgende Befehle in der Projekt-Root aus:
```sh
# Falls noch nicht vorhanden: venv anlegen
python3 -m venv .venv

# In einer neuen Shell das venv aktivieren
source .venv/bin/activate

# Abhängigkeiten installieren
pip install -r processing/requirements.txt

# Die Verarbeitungs-Schritte müssen in dieser Reihenfolge ausgeführt werden
./scripts/process_tilda_data.sh

./.venv/bin/python processing/start_matching.py
./.venv/bin/python processing/start_snapping.py
./.venv/bin/python processing/start_aggregation.py --input ./output/snapping_converted_bikelanes.fgb
```

```sh
# Kurzvariante zur Ausführung aller Schritte für ein bestimmtes Gebiet:
# --clip <region>  Clips alle Daten auf eine Region (neukoelln, norden, sueden)

# Vorher ausführbar machen: chmod +x processing/execute_processing.sh
./scripts/process_tilda_data.sh
./processing/execute_processing.sh
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
- `testing/` – Testdaten und Testskripte
- `validation/` – Skripte und Daten zur Validierung der Ergebnisse

## Lizenzen

Der Quellcode der Verarbeitungsskripte und des Inspectors steht unter der AGPL-3.0-Lizenz. Details findest du in der Datei [LICENSE](./LICENSE).

Die verwendeten Roh-Geodaten sind pro Datei lizenziert, siehe [data/LIZENZEN.md](./data/LIZENZEN.md) (Deutsch).

Die durch die Skripte erzeugten Geodaten sind in [output/LIZENZEN.md](./output/LIZENZEN.md) (Deutsch) beschrieben. Die erzeugten Dateien sind nicht im Repository enthalten, lassen sich aber aus den Rohdaten reproduzieren.