# Verarbeitungsskripte

Das Processing-System führt eine vollständige Verarbeitung der TILDA-Rohdaten bis hin zu den finalen aggregierten Radvorrangnetz-Daten durch.

Das System erstellt Zwischendateien für die Geodaten, um die Geschwindigkeit bei Wiederholungen zu verbessern. Dies kann jedoch auch zu **Caching-Problemen** führen. Bei Problemen löschen Sie den `output`-Ordner oder verwenden Sie `--clean-cache`.

Siehe [REQUIREMENTS.md](./REQUIREMENTS.md) für Geodaten-Anforderungen.

*Getestet mit Python 3.13.3.*

## Vollständige Verarbeitungskette

### 1. TILDA-Daten vorbereiten

Zuerst müssen die TILDA-Rohdaten prozessiert werden:

```bash
./scripts/process_tilda_data.sh
```

### 1b. Bushaltestellen auf RVN filtern (Optional, für Schutzstreifen-Konvertierung)

Um Schutzstreifen an Bushaltestellen zu konvertieren, müssen zunächst die relevanten Bushaltestellen gefiltert werden:

```bash
python scripts/filter_bus_stops_on_rvn.py
```

**Eingabe**: `data/OSM-highway=bus_stop.geojson` (Bushaltestellen-Plattformen)  
**Ausgabe**: `output/bus_stops_on_rvn.fgb` (Haltestellen auf dem RVN mit 15m Puffer)

Dieser Schritt:
- Lädt OSM-Bushaltestellen (`highway=bus_stop`, Plattformen)
- Filtert nur Haltestellen im 15m-Puffer des Radvorrangsnetzes
- Wird von `start_bikelane_conversion.py` für die Seitenprüfung verwendet

Dieser Schritt:
- Schneidet die TILDA-Rohdaten aus `data-raw-tilda/` auf Berlin zu
- Übersetzt TILDA-Attribute zu RVN-Attributen
- Erstellt drei bereinigte Datensätze in `data/` und `output/TILDA-translated/`

**Eingabedateien (data-raw-tilda/):**
- `bikelanes.fgb` → `TILDA Radwege Berlin.fgb` → `TILDA Bikelanes Translated.fgb`
- `roads.fgb` → `TILDA Straßen Berlin.fgb` → `TILDA Streets Translated.fgb`
- `roadsPathClasses.fgb` → `TILDA Wege Berlin.fgb` → `TILDA Paths Translated.fgb`

### 2. Vollständige Verarbeitung durchführen

Nach der TILDA-Datenvorbereitung wird die Hauptverarbeitung gestartet:

```bash
./processing/execute_processing.sh
```

**Optionen:**
- `--clip <region>` - Regionaler Zuschnitt: neukoelln, norden oder sueden
- `--view z/lat/lon` - Viewport-Zuschnitt (WGS84, z.B. 18/52.488306/13.425140)
- `--start-step <1-5>` - Startet ab bestimmtem Verarbeitungsschritt
- `--clean-cache` - Vollständige Cache-Bereinigung vor Verarbeitung

### Verarbeitungsschritte im Detail

#### Schritt 1: OSM-Matching (`start_matching.py`)
- Ordnet TILDA-übersetzte Attribute dem Berliner Radvorrangsnetz zu
- Führt räumliches Matching durch und erstellt bereinigte Datensätze
- **Ausgabe**: `output/matched/matched_tilda_ways.fgb`

#### Schritt 2: Snapping und Attribut-Übernahme (`start_snapping.py`) 
- Überträgt TILDA-Attribute auf ein topologisches Richtungs-Straßennetz
- Bei fehlenden TILDA-Daten wird `fuehr="Keine Radinfrastruktur vorhanden"` gesetzt
- Berechnet Segmentlängen in Metern
- **Ausgabe**: `output/snapping_network_enriched.fgb`

**Besonderheit: Kreisverkehre und geschlossene Ringe**

Das Snapping-System behandelt Kreisverkehre und andere geschlossene Ringe (Startpunkt == Endpunkt) speziell:

- **Problem**: Bei geschlossenen Ringen ist die Standard-Winkelberechnung (Start → Ende) undefiniert, da dx=0 und dy=0
- **Lösung**: Bei Kreisverkehren wird die Tangente am nächsten Punkt zum Segment berechnet
- **Funktionsweise**:
  1. Das System erkennt automatisch geschlossene Ringe (Distanz Start-Ende < 1cm)
  2. Es findet den nächsten Punkt auf dem Ring zum jeweiligen Netzwerk-Segment
  3. Die Tangente wird durch den Winkel zwischen vorherigem und nächstem Punkt berechnet
  4. Dies ermöglicht eine korrekte Richtungsbestimmung (ri=0 oder ri=1)

- **Implementierung**: `helpers/snapping_analysis.py`
  - `is_closed_ring()` - Erkennung geschlossener Ringe
  - `calculate_tangent_angle_at_nearest_point()` - Tangentenberechnung
  - `calculate_line_angle(geom, reference_geom=None)` - Erweiterte Winkelberechnung

Diese Verbesserung verhindert falsche Zuordnungen bei Kreisverkehren und stellt sicher, dass die `direction_compatibility`-Prüfung korrekt funktioniert.

#### Schritt 3: Schutzstreifen-Konvertierung (`start_bikelane_conversion.py`)
**Konvertiert Schutzstreifen zu Radfahrstreifen unter bestimmten Bedingungen:**

1. **Kurze Schutzstreifen** (< 50m):
   - Werden zu Radfahrstreifen konvertiert, wenn sie an Radfahrstreifen **derselben Richtung** angrenzen
   - Berücksichtigt zusammenhängende Segmente

2. **Schutzstreifen an Bushaltestellen**:
   - Werden zu Radfahrstreifen konvertiert, wenn:
     - Sie im 20m Umkreis einer Bushaltestelle liegen UND
     - Sie an Radfahrstreifen **derselben Richtung** angrenzen UND
     - Die Bushaltestelle auf der **rechten Seite** (Fahrtrichtung) liegt
   - Berücksichtigt Rechtsverkehr in Deutschland
   - Benötigt vorheriges Ausführen von `scripts/filter_bus_stops_on_rvn.py`

**Wichtige Prüfungen:**
- Richtungscheck: Nur Radfahrstreifen mit gleichem `ri`-Attribut werden berücksichtigt
- Seitenprüfung: Bei Haltestellen wird nur die Seite mit Haltestelle konvertiert
- Filter für `fuehr=None`: Wege ohne Führungsform werden korrekt ausgefiltert

**Ausgabe**: `output/snapping_converted_bikelanes.fgb`

Siehe [CHANGELOG_SCHUTZSTREIFEN_CONVERSION.md](./CHANGELOG_SCHUTZSTREIFEN_CONVERSION.md) für Details.

#### Schritt 4: Finale Aggregation (`aggregate_final_model.py`)
- Aggregiert Netzwerkdaten nach `element_nr` und Fahrtrichtung (`ri`)
- Weist Bezirksnummern zu
- Erstellt finale GeoPackage-Dateien mit separaten Layern
- **Ausgabe**: `output/aggregated_rvn_final.gpkg`

#### Schritt 5: Qualitätssicherungstests
- Führt automatisierte Validierungen durch

## Finale Ausgabedateien

Nach erfolgreicher Verarbeitung finden Sie die finalen Datensätze hier:

### Standard-Modus (ganz Berlin):
- **`output/aggregated_rvn_final.gpkg`** - Finale aggregierte Netzwerkdaten mit 3 Layern:
  - `hinrichtung` - Kanten mit ri=0 
  - `gegenrichtung` - Kanten mit ri=1
- **`output/snapping_converted_bikelanes.fgb`** - Angereicherte Netzwerkdaten nach Schutzstreifen-Konvertierung

### Regionaler Zuschnitt (`--clip <region>`):
- **`output/aggregated_rvn_final_{region}.gpkg`** (z.B. neukoelln, norden, sueden)
- **`output/snapping_converted_bikelanes_{region}.fgb`**

### Zusätzliche Dateien:
- **`output/matched/`** - Gematchte OSM-Wege und Zwischendateien
- **`output-last-run/`** - Gesicherte finale Dateien vom vorherigen Lauf

## Filter und Verarbeitungslogik

### Orthogonaler Filter
Der `orthogonal_filter.py` führt zusätzliche Verarbeitungsschritte durch:
- Selektiert kurze OSM-Wege unter einem Schwellenwert
- Berechnet Vektoren der Radvorrangsnetz-Kanten in Puffer-Entfernung
- Verwirft Segmente mit zu großem Winkelunterschied
- Betrifft hauptsächlich Kreuzungen, die nicht parallel zum gewünschten Radvorrangsnetz verlaufen

### Manuelle OSM Ein- und Ausschlüsse
Manuelle Eingriffe verwenden die Dateien `data/exclude_ways.txt` und `data/include_ways.txt` (eine OSM-Weg-ID pro Zeile) zum Ausschließen oder Einschließen von OSM-Wegen. Dieser Schritt ist standardmäßig aktiviert und kann mit `--skip-manual-interventions` übersprungen werden.

### Differenz-Berechnung  
Das System berechnet standardmäßig die Differenz zwischen zwei Datensätzen (normalerweise verwendet zur Bestimmung aller Straßen, wo keine Radwege in OSM erkannt wurden). Dieser Schritt kann mit `--skip-difference-streets-bikelanes` übersprungen werden.
