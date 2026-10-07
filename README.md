# infraVelo Radnetz

Dieses Projekt hat zum Ziel, bereits verarbeitete Fahrrad-Geodaten aus [TILDA](https://tilda-geo.de/) (basierend auf OpenStreetMap) in das Berliner [Detailnetz](https://gdi.berlin.de/geonetwork/geonetwork/api/records/cf374cd3-d0b8-3e6a-92c3-75e18dd595a1) zu überführen.

## Ordnerstruktur

Jeder Ordner ist für eine Aufgabe zuständig und hat eine eigene README.

- [`processing/`](./processing/README.md) – Pipeline TILDA → Radvorrangnetz: TILDA- und RVN-Aufbereitung, Map-Matching (Rust), Schutzstreifen-Konvertierung, Overrides, Aggregation, Validierung. Mit eigenen Outputs.
- [`ren-network/`](./ren-network/README.md) – Einheitliches Netz für REN+ aus Radverkehrsnetz, Hauptstraßennetz und Radschnellverbindungen.
- [`befahrungsbedarf/`](./befahrungsbedarf/README.md) – OSM-Wege am REN+-Netz ohne aktuelle Fotos, die neu befahren werden müssen.
- [`maproulette-centerline-tracks/`](./maproulette-centerline-tracks/README.md) – Aufgabenliste für MapRoulette: Radwege, die an der Straßen-Mittellinie erfasst sind.
- [`mapping-zuteilung/`](./mapping-zuteilung/README.md) – Aufteilung des REN+-Netzes auf die Mapping-Accounts.
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

## Lizenzen

Der Quellcode der Verarbeitungsskripte und des Inspectors steht unter der AGPL-3.0-Lizenz. Details findest du in der Datei [LICENSE](./LICENSE).

Die verwendeten Roh-Geodaten sind pro Datei lizenziert, siehe [data/LIZENZEN.md](./data/LIZENZEN.md) (Deutsch).

Die durch die Skripte erzeugten Geodaten sind in [processing/output/LIZENZEN.md](./processing/output/LIZENZEN.md) (Deutsch) beschrieben. Die erzeugten Dateien sind nicht im Repository enthalten, lassen sich aber aus den Rohdaten reproduzieren.
