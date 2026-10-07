# Scripts Ordner

Diese Scripts sind vorbereitende Schritte vor der Prozessierung, aber teilweise unabhängig von dieser. Die folgende Beschreibung ordnet die Scripts in der korrekten Verarbeitungsreihenfolge und zeigt deren Abhängigkeiten.

Alle Aufrufe erfolgen aus `processing/` heraus, mit aktiviertem `.venv` aus dem Projekt-Root. Pfade wie `data/` und `output/` sind relativ zu `processing/`.

## 📁 Datenvorverarbeitung (Unabhängig)

### TILDA-Daten vorbereiten
```bash
./process_tilda_data.sh
```
Bereitet die TILDA-Daten für die weitere Verarbeitung vor.

### TILDA-Daten zuschneiden
Das [`clip_tilda_data.py`](./clip_tilda_data.py) schneidet TILDA-Daten auf bestimmte Regionen (ganz Berlin oder einzelne Bezirke) zu.

### Bezirke zu Punkten zuweisen
Das [`assign_node_ids.py`](./assign_node_ids.py) fügt zwei Attribute zu den *Verbindungspunkten* aus dem Detailnetz hinzu: `Knotenpunkt-ID` und `Bezirksnummer`.

## 🛤️ RVN-Verarbeitung

```bash
./process_rvn.sh
```

Dieses Skript führt die drei wichtigen RVN-Vorverarbeitungsschritte aus:

### 1. Virtuelle Knotenpunkte verarbeiten
Das [`split_rvn_at_virtual_nodes.py`](./split_rvn_at_virtual_nodes.py) teilt das Berliner Radvorrangsnetz an virtuellen Knotenpunkten auf. Virtuelle Knotenpunkte liegen mitten auf Linien und erfordern eine Aufteilung der betroffenen Linien.

- **Input**: `data/Berlin Radvorrangsnetz.fgb`, `data/Virtuelle-Knotenpunkte.gpkg`
- **Output**: `output/rvn/Berlin Radvorrangsnetz_mit_virtuellen-knotenpunkten.fgb`

### 2. Element-Nummern zuweisen
Das [`assign_element_nr_to_rvn.py`](./assign_element_nr_to_rvn.py) fügt jedem Segment im Radvorrangsnetz eine `element_nr` hinzu, die auf den Verbindungspunkten basiert. Das Script berücksichtigt sowohl normale als auch virtuelle Knotenpunkte für die Zuweisung.

- **Input**: `output/rvn/Berlin Radvorrangsnetz_mit_virtuellen-knotenpunkten.fgb`, `output/knotenpunkte/knotenpunkte_mit_id.gpkg`, `data/Virtuelle-Knotenpunkte.gpkg`
- **Output**: `output/rvn/Berlin Vorrangnetz_with_element_nr.fgb`

### 3. RVN mit Detailnetz anreichern
Das [`enrich_rvn_with_detailnetz.py`](./enrich_rvn_with_detailnetz.py) fügt fehlende Kanten im Detailnetz aus dem RVN hinzu, sodass für jeden Teil des RVN eine Kante im Knoten-Kanten-Modell existiert.

- **Input**: `output/rvn/Berlin Vorrangnetz_with_element_nr.fgb`, `data/Berlin Straßenabschnitte Detailnetz.fgb`
- **Output**: `output/rvn/vorrangnetz_details_combined_rvn.fgb`

## 🚍 OSM-Daten Integration

### Bushaltestellen auf RVN filtern
Das [`filter_bus_stops_on_rvn.py`](./filter_bus_stops_on_rvn.py) filtert Bushaltestellen, die sich auf dem Radvorrangsnetz befinden (15m Puffer).

- **Input**: `data/Stop-Positions-Bus-OSM.fgb`, `output/matching/vorrangnetz_buffered_15m_round.fgb`
- **Output**: `output/bus_stops_on_rvn.fgb`

## 📤 Export-Scripts

### GeoJSON-Konvertierung
Das [`convert_to_geojson.py`](./convert_to_geojson.py) konvertiert Geodateien (GeoPackage, FlatGeoBuf) in GeoJSON-Format (WGS84).

## ⚡ Verarbeitungsreihenfolge (Zusammenfassung)

Für die vollständige Verarbeitung sollten die Scripts in dieser Reihenfolge ausgeführt werden:

```bash
# 1. Datenvorverarbeitung
./process_tilda_data.sh
python scripts/assign_node_ids.py

# 2. RVN-Verarbeitung
./process_rvn.sh

# 3. Hauptverarbeitung
./execute_processing.sh

# 4. Nachgelagerte Analysen (optional)
python scripts/filter_bus_stops_on_rvn.py

# 5. Export (optional)
python scripts/convert_to_geojson.py
```