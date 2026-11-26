# Scripts Ordner

Diese Scripts sind vorbereitende Schritte vor der Prozessierung, aber teilweise unabhängig von dieser. Die folgende Beschreibung ordnet die Scripts in der korrekten Verarbeitungsreihenfolge und zeigt deren Abhängigkeiten.

Alle Aufrufe erfolgen aus `processing/` heraus, mit aktiviertem `.venv` aus dem Projekt-Root. Pfade wie `data/` und `output/` sind relativ zu `processing/`.

## 📁 Datenvorverarbeitung (Unabhängig)

### TILDA-Daten laden
```bash
../data/download_tilda.sh processing
```
Lädt die TILDA-Exporte nach `data-raw-tilda/` und `data/TILDA Routing Berlin.gpkg`.

### TILDA-Routing-Netz vorbereiten
Das [`prepare_tilda_routing.py`](./prepare_tilda_routing.py) verknüpft `routing` mit den Attributen aus `bikelanes`/`roads`/`roadsPathClasses`, teilt die Wege an gemeinsamen Stützpunkten, behält nur das zusammenhängende Hauptnetz und übersetzt die TILDA-Attribute in RVN-Attribute (`translate_tilda_attributes`, Mapping-Regeln im selben Skript). Siehe [Workdoc](../map-matching/docs/tilda-routing.md).

- **Input**: `data/TILDA Routing Berlin.gpkg`, `data-raw-tilda/*.fgb`
- **Output**: `output/TILDA-routing/`, mit `--netz ren` ohne RVN-Zuschnitt nach `output/TILDA-routing-ren/`

### Bezirke zu Punkten zuweisen
Das [`assign_node_ids.py`](./assign_node_ids.py) fügt zwei Attribute zu den *Verbindungspunkten* aus dem Detailnetz hinzu: `Knotenpunkt-ID` und `Bezirksnummer`.

## 🛤️ RVN-Verarbeitung

```bash
./process_radnetz.sh
```

Dieses Skript führt die drei Vorverarbeitungsschritte des Zielnetzes (RVN oder REN+) aus:

### 1. Virtuelle Knotenpunkte verarbeiten
Die virtuellen Knotenpunkte kommen aus der App Netzanpassungen: `netzanpassungen/apply_app_result.py` schreibt `netzanpassungen/output/virtuelle_knoten.gpkg` (Pfad und Abbruch bei fehlender Datei zentral in [`helpers/virtuelle_knoten.py`](../helpers/virtuelle_knoten.py)); auch `convert_knotenpunkte.py` und die Validierung (`validation/checks/virtuelle_knotenpunkte.py`) lesen sie von dort.

Das [`split_rvn_at_virtual_nodes.py`](./split_rvn_at_virtual_nodes.py) teilt das Berliner Radvorrangsnetz an virtuellen Knotenpunkten auf. Virtuelle Knotenpunkte liegen mitten auf Linien und erfordern eine Aufteilung der betroffenen Linien.

- **Input**: `data/Berlin Radvorrangsnetz.fgb`, virtuelle Knotenpunkte über `read_active()` aus [`data/virtuelle_knotenpunkte.py`](../../data/virtuelle_knotenpunkte.py) (nur `status = aktiv`, Regeln: [VIRTUELLE-KNOTENPUNKTE.md](../../data/VIRTUELLE-KNOTENPUNKTE.md))
- **Output**: `output/rvn/Berlin Radvorrangsnetz_mit_virtuellen-knotenpunkten.fgb`

Die drei Skripte dieses Abschnitts nehmen `--netz rvn|ren` (Standard `rvn`). Mit `ren` verarbeiten sie das REN+ und schreiben nach `output/ren/`. Eingangsnetz ist `ren_netz_korrigiert.gpkg` (Korrekturen aus der App Netzanpassungen, `netzanpassungen/apply_app_result.py`), solange die Datei existiert, sonst `ren_netz.gpkg`; `--quelle auto|korrigiert|original` (nur im ersten Schritt, auch an `process_radnetz.sh` übergeben) wählt es. Das Log nennt die gewählte Datei. Die Pfade stehen in [`helpers/netz.py`](../helpers/netz.py); die Pfade stehen in [`helpers/netz.py`](../helpers/netz.py).

### 2. Element-Nummern zuweisen
Das [`assign_element_nr_to_rvn.py`](./assign_element_nr_to_rvn.py) fügt jedem Segment im Radvorrangsnetz eine `element_nr` hinzu, die auf den Verbindungspunkten basiert. Das Script berücksichtigt sowohl normale als auch virtuelle Knotenpunkte für die Zuweisung.

- **Input**: `output/rvn/Berlin Radvorrangsnetz_mit_virtuellen-knotenpunkten.fgb`, `output/knotenpunkte/knotenpunkte_mit_id.gpkg`, `netzanpassungen/output/virtuelle_knoten.gpkg`
- **Output**: `output/rvn/Berlin Vorrangnetz_with_element_nr.fgb`

### 3. RVN mit Detailnetz anreichern
Das [`enrich_rvn_with_detailnetz.py`](./enrich_rvn_with_detailnetz.py) fügt fehlende Kanten im Detailnetz aus dem RVN hinzu, sodass für jeden Teil des RVN eine Kante im Knoten-Kanten-Modell existiert. Hat das Zielnetz eine Spalte `verkehrsrichtung` (nur das korrigierte REN+ aus der App Netzanpassungen), gilt sie statt der des Detailnetzes.

- **Input**: `output/rvn/Berlin Vorrangnetz_with_element_nr.fgb`, `data/Berlin Straßenabschnitte Detailnetz.fgb`
- **Output**: `output/rvn/vorrangnetz_details_combined_rvn.fgb`

## 🚍 OSM-Daten Integration

### Bushaltestellen am Zielnetz
Das [`prepare_bus_stops.py`](./prepare_bus_stops.py) holt alle `highway=bus_stop`-Knoten in Berlin über die Overpass-API und schneidet sie auf das Zielnetz zu (Abstand höchstens 15 m, `--puffer` ändert das). Beim REN+ ist das Zielnetz `ren_netz.gpkg` aus Schritt 3, also alle Netzquellen gemeinsam. Kommt eine Quelle dazu, genügt ein neuer Lauf von `./run_pipeline.sh`; `execute_processing.sh` ruft das Skript vor der Schutzstreifen-Konvertierung selbst auf.

- **Input**: Overpass-API, danach Cache `data/netzquellen/osm_bushaltestellen.gpkg` (`--neu` lädt erneut), Zielnetz aus `helpers/netz.py`
- **Output**: `output/bus_stops_on_ren.fgb` bzw. mit `--netz rvn` `output/bus_stops_on_rvn.fgb`

## 📤 Export-Scripts

### GeoJSON-Konvertierung
Das [`convert_to_geojson.py`](./convert_to_geojson.py) konvertiert Geodateien (GeoPackage, FlatGeoBuf) in GeoJSON-Format (WGS84).

## ⚡ Verarbeitungsreihenfolge (Zusammenfassung)

Für die vollständige Verarbeitung sollten die Scripts in dieser Reihenfolge ausgeführt werden:

```bash
# 1. Datenvorverarbeitung
../data/download_tilda.sh processing
../.venv/bin/python scripts/prepare_tilda_routing.py --netz ren
python scripts/assign_node_ids.py

# 2. RVN-Verarbeitung
./process_radnetz.sh

# 3. Hauptverarbeitung
./execute_processing.sh

# 4. Nachgelagerte Analysen (optional)
python scripts/prepare_bus_stops.py --netz ren

# 5. Export (optional)
python scripts/convert_to_geojson.py
```