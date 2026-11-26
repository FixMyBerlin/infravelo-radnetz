# infraVelo Radnetz

Dieses Projekt hat zum Ziel, bereits verarbeitete Fahrrad-Geodaten aus [TILDA](https://tilda-geo.de/) (basierend auf OpenStreetMap) in das Berliner [Detailnetz](https://gdi.berlin.de/geonetwork/geonetwork/api/records/cf374cd3-d0b8-3e6a-92c3-75e18dd595a1) zu überführen.

## Ordnerstruktur

Jeder Ordner ist für eine Aufgabe zuständig und hat eine eigene README.

- [`processing/`](./processing/README.md) – Pipeline TILDA → Radvorrangnetz: TILDA- und RVN-Aufbereitung, Map-Matching (Rust), Schutzstreifen-Konvertierung, Overrides, Aggregation, Validierung. Mit eigenen Outputs.
- [`ren-network/`](./ren-network/README.md) – Einheitliches Netz für REN+ aus Radverkehrsnetz, Hauptstraßennetz und Radschnellverbindungen.
- [`knotenpunkte/`](./knotenpunkte/README.md) – Knotenpunkt-Datensatz für alle REN+-Knoten, Abgleich mit der Lieferung 2025, Übergabe an Knotenpunkt-App und ML.
- [`netzanpassungen/`](./netzanpassungen/README.md) – Eingabedatei für die App „Netzanpassungen“ (neue Kanten entlang der Radfernwege, virtuelle Knoten, Korrekturen am REN+) und Anwenden ihrer Einträge (direkt aus ihrer KV-Datenbank).
- [`befahrungsbedarf/`](./befahrungsbedarf/README.md) – OSM-Wege am REN+-Netz ohne aktuelle Fotos, die neu befahren werden müssen.
- [`maproulette-centerline-tracks/`](./maproulette-centerline-tracks/README.md) – Aufgabenliste für MapRoulette: Radwege, die an der Straßen-Mittellinie erfasst sind.
- [`mapping-zuteilung/`](./mapping-zuteilung/README.md) – Aufteilung des REN+-Netzes auf die Mapping-Accounts; die Zuteilung steht seit 2026-11-03 in `assignment.csv`, regelmäßig läuft nur das Update.
- [`tilda-pseudo-tags/`](./tilda-pseudo-tags/README.md) – CSV für den TILDA-Pseudo-Tag `infravelo_netz` (welche OSM-Wege zum Radnetz gehören), eingecheckt und von TILDA aus dem Repo geladen.
- [`bearbeitungsstand/`](./bearbeitungsstand/README.md) – Liest aus dem Mapping-Editor, welche Linien erledigt sind; genutzt von den beiden Ordnern darüber.
- [`tilda-qa/`](./tilda-qa/README.md) – QA-Ansichten in TILDA je Lieferung: Bereiche je Netzkante und Referenzwerte zum Stand der Lieferung (SQL-Dateien für tilda-geo `data-schema/`).
- [`osm-cleanup/`](./osm-cleanup/) – Bereinigungen in OSM, je Bereinigung ein Ordner mit README, Regeln und Skripten; zuerst [`oneway-2026-11/`](./osm-cleanup/oneway-2026-11/README.md) (falsche `cycleway:*:oneway=yes`), dann [`sidepath-direction-2026-11/`](./osm-cleanup/sidepath-direction-2026-11/README.md) (separate Radwege mit `-1` oder gegen den Verkehr daneben, Maid-Aufgabenlisten).
- [`data/`](./data/README.md) – Gemeinsame Eingangsdaten (Detailnetz, Radvorrangsnetz, Bezirke, manuelle Listen).

**Virtuelle Knotenpunkte:** Nummern, Anlegen, Löschen und `element_nr` regelt [`data/VIRTUELLE-KNOTENPUNKTE.md`](./data/VIRTUELLE-KNOTENPUNKTE.md). Gilt für alle Repos des Projekts.

## REN+-Netz in einem Befehl

`run_pipeline.sh` baut das REN+-Netz von den Netzquellen bis Schritt 3 und bricht beim ersten Fehler ab (Gesamtbild: [`docs/network-pipeline.md`](./docs/network-pipeline.md)):

```sh
./run_pipeline.sh                       # Einträge der App Netzanpassungen aus der KV-Datenbank, Gebiet berlin
./run_pipeline.sh --export <datei>.json # statt der KV-Datenbank der App-Export „Alle Einträge“
./run_pipeline.sh --gebiet <gebiet>     # anderes Gebiet der App
```

| Schritt | Skript | Ergebnis |
|---|---|---|
| 1 | `ren-network/merge_networks.py` | `ren_netz_roh.gpkg`, Knotenvorschläge `virtuelle_knoten_vorschlaege.gpkg` |
| 2 | `netzanpassungen/match_cycle_routes.py` | `ren_netz_auto.gpkg`, `radfernweg_abschnitte.gpkg` |
| – | `netzanpassungen/write_app_input.py` | `netzanpassungen_<gebiet>.json` für die App |
| 3 | `netzanpassungen/apply_app_result.py` | `ren_netz.gpkg` (Kunde), `ren_netz_korrigiert.gpkg` (Matching, Mapping), Kartierung, `virtuelle_knoten.gpkg` |
| – | `data/virtuelle_knotenpunkte.py pruefen` | Prüfung der virtuellen Knoten |

Voraussetzungen: `.env` mit `INPUTS_DRIVE_FOLDER_URL` (Eingangsdaten) und `VITE_KV_BASE_URL`, `VITE_KV_PROJECT`, `VITE_KV_API_KEY` (Lesezugriff auf die App, Werte wie in `infravelo-apps/netzanpassungen/.env`), siehe `.env.example`; `tilda-static-data` als Schwesterordner (Lieferung 2025).

### Ausgaben für TILDA und die Mapper: nur von Hand

Maske, Zuteilung (Gebiete und Kanten je Mapper), Befahrungsbedarf und MapRoulette-Aufgaben baut `run_pipeline.sh` nicht. Sie laufen nur auf Anweisung, mit einem eigenen Skript auf dem Ergebnis von Schritt 3:

```sh
./run_mapper_outputs.sh
```

| Skript | Ergebnis |
|---|---|
| `ren-network/create_mask.py` | Maske |
| `mapping-zuteilung/update_assignment.py` | Zuteilung |
| `befahrungsbedarf/build.py` | Befahrungsbedarf |
| `maproulette-centerline-tracks/extract_centerline_tracks.py` | MapRoulette-Aufgaben |

Voraussetzungen: ein Lauf von `run_pipeline.sh`, die eigenen Eingangsdaten der Skripte (`befahrungsbedarf/download_data.sh`, Symlinks in `maproulette-centerline-tracks/data/`). Ändert die Zuteilung `mapping-zuteilung/assignment.csv`, die Datei committen. Das Skript schreibt nur in dieses Repo. Das Hochladen nach tilda-static-data und TILDA bleibt ein eigener Schritt von Hand (`bearbeitungsstand/update.sh`, `processing/copy_to_tilda_static.sh`).

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
./process_tilda_data.sh && ./process_radnetz.sh && ./execute_processing.sh && ./run_validation.sh

# Eingangsdaten aus dem gemeinsamen Google Drive (Link in .env, siehe .env.example; läuft auch zu Beginn von merge_networks.py)
python data/download_inputs.py

# REN+-Netz: Schritt 1 Rohnetz, Schritt 2 Radfernwege zuordnen, App-Eingabe, Schritt 3 App-Ergebnis (docs/network-pipeline.md)
python ren-network/merge_networks.py
python netzanpassungen/match_cycle_routes.py
python netzanpassungen/write_app_input.py   # Datei für die App Netzanpassungen hochladen

# Bearbeitungsstand der Mapper nach TILDA (Zuteilung und Mittellinien-Radwege, Upload nach production)
bearbeitungsstand/update.sh

# Export der App Netzanpassungen einlesen: ren_netz.gpkg (Kunde), ren_netz_korrigiert.gpkg (Matching, Mapping) und die virtuellen Knoten (netzanpassungen/output/virtuelle_knoten.gpkg); vor processing/ und knotenpunkte/
python netzanpassungen/apply_app_result.py <export-alle-eintraege>.json   # oder --ohne-export

# Knotenpunkte erzeugen
python knotenpunkte/download_lsa.py && python knotenpunkte/build_knotenpunkte.py
```

## Stand 2025 (Radvorrangnetz)

Die Verarbeitung von 2025 mit dem Python-Matching und -Snapping ist im Tag `rvn-final-state` archiviert:

```sh
git worktree add ../radnetz-rvn-2025 rvn-final-state
```

## Lizenzen

Der Quellcode der Verarbeitungsskripte steht unter der AGPL-3.0-Lizenz. Details findest du in der Datei [LICENSE](./LICENSE).

Die verwendeten Roh-Geodaten sind pro Datei lizenziert, siehe [data/LIZENZEN.md](./data/LIZENZEN.md) (Deutsch).

Die durch die Skripte erzeugten Geodaten sind in [processing/output/LIZENZEN.md](./processing/output/LIZENZEN.md) (Deutsch) beschrieben. Die erzeugten Dateien sind nicht im Repository enthalten, lassen sich aber aus den Rohdaten reproduzieren.
