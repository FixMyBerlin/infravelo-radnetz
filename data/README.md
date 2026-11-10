# Data

## Eingabedaten (manuell gepflegt/updated)

Diese Dateien werden nicht von Skripten generiert und müssen manuell aktualisiert werden:

- `Berlin Radvorrangsnetz.fgb` – Gefilterte Geodaten des Radnetzes Berlin, enthält nur Kanten des Radvorrangsnetzes.
- `Berlin Bezirke.gpkg` – Bezirksgrenzen von Berlin zur räumlichen Filterung und Analyse.
- `Berlin Straßenabschnitte.gpkg` – Straßenabschnitte aus dem Detailnetz Berlin als GeoPackage.
- `Berlin Straßenabschnitte Detailnetz.fgb` – Straßenabschnitte aus dem Detailnetz Berlin als FlatGeobuf.
- `Berlin_Gebiet_Norden.gpkg` – Gebietsgrenze für die Verarbeitung der nördlichen Bezirke von Berlin.
- `Berlin_Gebiet_Süden.gpkg` – Gebietsgrenze für die Verarbeitung der südlichen Bezirke von Berlin.
- `Bezirk Neukölln Grenze.fgb` – Bezirksgrenze von Neukölln für gezielte Testverarbeitung.
- `Verbindungspunkte im RVN.gpkg` – Verbindungspunkte aus dem Radvorrangnetz/Detailnetz zur Netzwerkanalyse.
- `Virtuelle-Knotenpunkte.gpkg` – Manuell erstellte Knotenpunkte zur Ergänzung der Netzwerktopologie. Wird für neue virtuelle Knoten im [Knotenpunkt-Datensatz](../knotenpunkte/README.md) ergänzt.
- `OSM-highway=bus_stop.geojson` – Bushaltestellen aus OpenStreetMap für Konvertierungen von Schutzstreifen.
- `Stop-Positions-Bus-OSM.fgb` – Bushaltestellen-Positionen aus OpenStreetMap als FlatGeobuf.

## Generierte Dateien (durch `process_tilda_data.sh`)

Diese Dateien werden durch `processing/process_tilda_data.sh` aus den Rohdaten in `processing/data-raw-tilda/` erzeugt:

- `TILDA Radwege Berlin.fgb` – Auf Berlin zugeschnittene Radwege aus TILDA, basierend auf OpenStreetMap.
- `TILDA Straßen Berlin.fgb` – Auf Berlin zugeschnittene Straßen aus TILDA, basierend auf OpenStreetMap.
- `TILDA Wege Berlin.fgb` – Auf Berlin zugeschnittene Wege aus TILDA, basierend auf OpenStreetMap.

## TILDA-Routing-Netz

- `TILDA Routing Berlin.gpkg` – Routingfähiges TILDA-Netz (Tabelle `routing`), Export von `https://tilda-geo.de/api/export/berlin/routing?format=gpkg`. Stand 15.10.2026 lokal mit tilda-geo gerechnet. Muss zum Stand von `processing/data-raw-tilda/` passen. Details: [Workdoc](../processing/map-matching/docs/tilda-routing.md).

Für Lizenzen, siehe [LIZENZEN.md](./LIZENZEN.md)

# Data Modifiers

Wir verwenden manuell gepflegte Listen von OpenStreetMap-Way-IDs, die das endgültige Datenset verändern.

* `exclude_ways.txt` enthält in jeder Zeile eine OSM-Way-ID, die aus dem finalen Datensatz **entfernt** werden soll.
* `include_ways.txt` enthält in jeder Zeile eine OSM-Way-ID, die dem finalen Datensatz **hinzugefügt** werden soll.
- `override_ways.gpkg` – GeoPackage mit räumlichen Override-Geometrien zur gezielten Überschreibung von Attributen nach dem Snapping.
- `override_ways.txt` – Textdatei mit Text-Overrides im Format `tilda_id|element_nr|ri|attributes_json` für attributbasierte Überschreibungen.

## Eingangsdaten aus Google Drive

Einige Eingangsdaten liegen nicht im Repo und werden auch von keinem Skript geladen. Damit alle mit denselben Dateien rechnen, liegen sie in einem gemeinsamen Google-Drive-Ordner. Der Ordner ist für alle mit dem Link lesbar; der Link steht nur in der lokalen `.env` (`INPUTS_DRIVE_FOLDER_URL`, siehe `.env.example`) und nicht im Repo.

```bash
.venv/bin/python data/download_inputs.py
```

- `ren-network/unify_networks.py` und `netzanpassungen/export_app_daten.py` rufen das zu Beginn jedes Laufs auf. Fehlt der Link, bricht der Lauf ab.
- Der Ordner im Drive ist flach. `INPUT_FILES` im Skript ordnet jedem Dateinamen dort seinen Pfad im Repo zu:

| Datei im Drive | Pfad im Repo |
|---|---|
| `netzquellen_hauptstrassennetz.gpkg` | `data/netzquellen/hauptstrassennetz.gpkg` |
| `netzquellen_radverkehrsnetz.gpkg` | `data/netzquellen/radverkehrsnetz.gpkg` |
| `netzquellen_radschnellverbindungen.gpkg` | `data/netzquellen/radschnellverbindungen.gpkg` |
| `netzquellen_touristisches_radnetz.gpkg` | `data/netzquellen/touristisches_radnetz.gpkg` |
| `detailnetz_strassenabschnitte_2026-10-06.fgb` | `data/Berlin Straßenabschnitte Detailnetz 2026-10-06.fgb` |
| `detailnetz_verbindungspunkte.fgb` | `data/Berlin Verbindungspunkte Detailnetz.fgb` |
| `lor_planungsraeume_2021.geojson` | `mapping-zuteilung/data/lor_plr_2021.geojson` |

- [`inputs.json`](./inputs.json) (eingecheckt) hält Größe und SHA-256 jeder Datei fest. Geladen wird nur, was lokal fehlt oder davon abweicht; stimmen alle Dateien, läuft das Skript auch ohne Netz und ohne Link. Weicht eine Datei im Drive ab, bricht der Download ab, bevor er etwas überschreibt. So sieht man im Diff, wann sich Eingangsdaten geändert haben.

Neue Eingangsdaten ins Drive bringen:

1. Dateien lokal an ihren Platz legen, mit Drive-Namen in `INPUT_FILES` eintragen und ihren Pfad in die `.gitignore` des Ordners schreiben (`data/.gitignore`, `mapping-zuteilung/.gitignore`). Diese `.gitignore`-Dateien führen nur Drive-Dateien. So zeigt `git status` jede lokale Datei, die weder eingecheckt noch im Drive ist.
2. `.venv/bin/python data/download_inputs.py --write-manifest`, dann `inputs.json` committen.
3. `.venv/bin/python data/download_inputs.py --stage <ordner>` sammelt die Dateien unter ihrem Drive-Namen; den Inhalt des Ordners ins Drive kopieren und dabei die vorhandenen Dateien ersetzen.

Nicht im Drive, weil ein Skript sie lädt: die TILDA-Exporte (`befahrungsbedarf/download_data.sh`) und die Ampeln (`knotenpunkte/download_lsa.py`). Für die Knotenpunkte fehlt noch `data/netzquellen/knotenpunkte_2025.geojson.gz` (liegt bei Henri).
