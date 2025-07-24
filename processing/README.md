# Processing Script

**`main.py`** ist der Startpunkt des Verarbeitungsprozesses. Es wählt alle OSM-Wege aus, die sich in `BUFFER_METERS` Entfernung zum Radvorrangsnetz befinden.

Das Skript erstellt Zwischendateien für die Geodaten. Dies ermöglicht es, die Geschwindigkeit des Skripts bei Wiederholungen zu verbessern. Dies kann jedoch auch zu **Caching-Problemen** führen. Seien Sie sich dessen bewusst und löschen Sie gerne den `output`-Ordner, wenn Sie Probleme haben.

Siehe [REQUIREMENTS.md](./REQUIREMENTS.md) für Geodaten-Anforderungen.

*Getestet mit Python 3.13.3.*

## Modul Struktur

Die Module sind nach Funktionalität organisiert:

### `/matching/` - Matching-Algorithmen
- `difference.py` - Differenzbildung zwischen Straßen und Radwegen
- `manual_interventions.py` - Manuelle Eingriffe (Ausschluss/Einschluss von OSM-Wegen)
- `orthogonal_filter.py` - Orthogonalitätsfilter für kurze Segmente

### `/snapping/` - Snapping-Algorithmen  
- `snap_and_cut.py` - Snapping von OSM-Wegen auf Zielnetzwerke
- `enrich_streetnet_with_osm.py` - Anreicherung von Straßennetzen mit OSM-Attributen

### Hauptmodule
- `main.py` - Orchestriert den gesamten Verarbeitungsprozess
- `export_geojson.py` - Exportiert alle .fgb-Dateien als .geojson

## Phases

- [ ] **Matching**: Get all OSM Ways, which are part of the RVN
  - [x] Get all bikelanes
  - [x] Get all streets
  - [x] Get all other types of ways
  - [ ] Add Extra RVN segments
  - [ ] Merge all differente way types
  - [x] Enable manual inclusion and exclusion
- [ ] **Snapping**: Attributes on RVN edges
  - [x] Snap geometry to RVN edges
  - [x] Assign OSM Way attributes to RVN edges
  - [x] Calculate direction of the edges (oneway)
  - [ ] Solve direction based snapping of edges 
- [ ] **Aggregation**: Aggregate edges
  - [x] Find way to calculate the length of the edges
  - [x] Merge edges where length > 50 m, even when attributes changes
  - [x] Direction based layers
- [ ] RVN edges on OSM Ways
- [x] Provide Extract for Neukölln (via script)
- [x] Provide TXT file of all OSM  Ways, which are part of the RVN

### Next ToDos

- [x] Direction `ri` based spatial search and choice of RVN edges
- [ ] Calculate beginnt_bei_vp and endet_bei_vp, then element_nr
  - [x] Aggregating by element_nr 
- [ ] Dual carriageway oneway problems solve in snapping
- [ ] Improve difference calculations between streets and bikelanes -> search for one Einrichtungsverkehr way, if so, add Mischverkehr
- [ ] Add script for converting aggregated geopackage to one merged GeoJSON
- [ ] ~~Merging all three datasets into one file with three layers~~


## Filters

Every filter has its own Python module. **All filters and processing steps are enabled by default.**

You can skip individual steps using the following arguments:

- `--skip-orthogonalfilter-bikelanes` – skips the orthogonality filter for the bikelanes dataset
- `--skip-orthogonalfilter-streets` – skips the orthogonality filter for the streets dataset
- `--skip-manual-interventions` – skips manual OSM inclusion/exclusion (from `data/exclude_ways.txt` and `data/include_ways.txt`)
- `--skip-difference-streets-bikelanes` – skips the difference calculation (streets without bikelanes)
- `--skip-bikelanes` – skips the processing of the bikelanes dataset completely
- `--skip-streets` – skips the processing of the streets dataset completely

See also: `./.venv/bin/python processing/main.py -h`.

### Orthogonal Filter

The `orthogonal_filter.py` is a processing step, which additionally:
* Selects short OSM Ways which are less length than `short_way_threshold`.
* Calculates a vector of the Radvorrangsnetz edges in `buffer_meters` distance.
* Throws out segments which are in greater difference than `angle_diff_threshold`.

These ways are usually crossings, which are not parallel to the whished Radvorrangsnetz.

### Manual OSM Inclusion & Exclusions

Manual interventions use the files `data/exclude_ways.txt` and `data/include_ways.txt` (one OSM way id per line) and exclude or include the OSM way into the dataset. This step is enabled by default and can be skipped with `--skip-manual-interventions`.

### Difference

By default, the script calculates the difference between two datasets (usually used for determinating all streets, where no bikelanes has been detected in OSM). You can skip this step with `--skip-difference-streets-bikelanes`.

### Process Steps

Useful, when developing on another processing step.

**`--skip-bikelanes`** skips the processing of bikelanes dataset completely.
**`--skip-streets`** skips the processing of streets dataset completely.

## Prepare static data

The main process will create geojson files in `/output-static-data-transfer`. You can run this on existing data with…

```
./.venv/bin/python processing/export_geojson.py
```


## Snapping Script

Empfohlener Start über das Wrapper-Skript:

```sh
python ./processing/start_snapping.py \
  --net ./output/vorrangnetz_details_combined_rvn.fgb \
  --osm ./output/matched/matched_tilda_ways.fgb \
  --out ./output/snapping_network_enriched.fgb \
  --buffer 20.0 \
  --max-angle 35.0
```

Die Argumente entsprechen:
- Optional: `--buffer` für die Puffergröße in Metern (Standard: 20.0)
- Optional: `--max-angle` für den maximalen Winkelunterschied in Grad (Standard: 35.0)
