# Verarbeitungsskripte

Das Processing-System verarbeitet TILDA-Rohdaten zu finalen Radvorrangnetz-Daten in 5 Schritten.

Das System nutzt Zwischendateien zur Beschleunigung, was zu **Caching-Problemen** führen kann. Bei Problemen: `output`-Ordner löschen oder `--clean-cache` verwenden.

Siehe [REQUIREMENTS.md](./REQUIREMENTS.md) für Geodaten-Anforderungen. *Getestet mit Python 3.13.3.*

## Verarbeitungskette

### 1. TILDA-Daten vorbereiten

```bash
./process_tilda_data.sh
```

Schneidet TILDA-Rohdaten (`data-raw-tilda/`) auf Berlin zu und übersetzt Attribute zu RVN-Format.

**Ausgabe**: `data/TILDA *.fgb` und `output/TILDA-translated/*.fgb`

### 2. Hauptverarbeitung

```bash
./execute_processing.sh [--clip neukoelln|norden|sueden] [--start-step 1-5] [--clean-cache]
```

## Verarbeitungsschritte

### Schritt 1: Matching (`start_matching.py`)
Ordnet OSM-Wege räumlich dem Radvorrangsnetz zu. Wendet Filter an (Orthogonalität, manuelle Ein-/Ausschlüsse).

**Ausgabe**: `output/matched/matched_tilda_ways.fgb`

### Schritt 2: Snapping (`start_snapping.py`)
Überträgt TILDA-Attribute richtungsgenau auf topologisches Straßennetz. Segmentiert Netz in 2,5m-Abschnitte, matcht TILDA-Wege im Puffer (30m), bestimmt Fahrtrichtung (`ri=0`/`ri=1`) per Winkelvergleich, merged identische Segmente zurück.

**Besonderheit Kreisverkehre**: Bei geschlossenen Ringen (Start = Ende) wird Tangente am nächsten Punkt berechnet statt direkter Winkel.

**Ausgabe**: `output/snapping_network_enriched.fgb`

### Schritt 3: Schutzstreifen-Konvertierung (`start_bikelane_conversion.py`)
Konvertiert Schutzstreifen unter bestimmten Bedingungen:
- An Bushaltestellen → Radfahrstreifen (nur rechte Seite, benachbart zu Radfahrstreifen)
- Kurze Segmente (<50m) → Radfahrstreifen (benachbart zu Radfahrstreifen)
- Kurze Segmente an Knotenpunkten → Kreuzungswege

**Ausgabe**: `output/snapping_converted_bikelanes.fgb`

### Schritt 3b: Override-Anwendung (`start_overriding.py`)
Wendet manuelle Overrides aus `data/override_ways.gpkg` und `data/override_ways.txt` auf Netzwerkdaten an. Überschreibt gezielt Attribute (fuehr, ofm, protek, pflicht, breite, farbe, trennstreifen, nutz_beschr, verkehrsri).

**Ausgabe**: `output/snapping_with_overrides.fgb`

### Schritt 4: Aggregation (`start_aggregation.py`)
Aggregiert Segmente nach `element_nr` + `ri` (Fahrtrichtung). Regelbasiert: längster Abschnitt für Führungsform/Bezirk/Material, schlechteste Ausprägung für Breite/Trennstreifen.

**Ausgabe**: `output/aggregated_rvn_final.gpkg` (Layer: `hinrichtung`, `gegenrichtung`)

## Python-Skripte im Überblick

- **`start_matching.py`**: Schritt 1 - OSM-Matching mit Filtern
- **`start_snapping.py`**: Schritt 2 - Richtungsgerechtes Snapping
- **`start_bikelane_conversion.py`**: Schritt 3 - Schutzstreifen-Konvertierung
- **`start_overriding.py`**: Schritt 3b - Override-Anwendung
- **`start_aggregation.py`**: Schritt 4 - Finale Aggregation

### Helper-Module (`helpers/`)
- `globals.py`: Konstanten (CRS, Pfade)
- `snapping_calculations.py`: Winkelberechnungen, Richtungserkennung
- `district_assignment.py`: Bezirkszuweisung
- `clipping.py`: Regionale/Viewport-Zuschnitte
- `convert_*.py`: Schutzstreifen-Konvertierungslogik
- `override_edges.py`: Override-Verarbeitung

### Matching-Module (`matching/`)
- `orthogonal_filter.py`: Verwirft Segmente mit falscher Ausrichtung zum RVN
- `manual_interventions.py`: Lädt `exclude_ways.txt` / `include_ways.txt`
- `difference.py`: Berechnet Straßen ohne Radinfrastruktur
