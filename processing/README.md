# Processing Script

**`main.py`** ist der Startpunkt des Verarbeitungsprozesses. Es wählt alle OSM-Wege aus, die sich in `BUFFER_METERS` Entfernung zum Radvorrangsnetz befinden.

Das Skript erstellt Zwischendateien für die Geodaten. Dies ermöglicht es, die Geschwindigkeit des Skripts bei Wiederholungen zu verbessern. Dies kann jedoch auch zu **Caching-Problemen** führen. Seien Sie sich dessen bewusst und löschen Sie gerne den `output`-Ordner, wenn Sie Probleme haben.

Siehe [REQUIREMENTS.md](./REQUIREMENTS.md) für Geodaten-Anforderungen.

*Getestet mit Python 3.13.3.*

## Processing Scripts & Steps

### Snapping Script

Empfohlener Start über das Wrapper-Skript:

```sh
python ./processing/start_snapping.py \
  --net ./output/vorrangnetz_details_combined_rvn.fgb \
  --osm ./output/matched/matched_tilda_ways.fgb \
  --out ./output/snapping_network_enriched.fgb
```

Die Argumente entsprechen:
- Optional: `--buffer` für die Puffergröße in Metern (Standard: 20.0)
- Optional: `--max-angle` für den maximalen Winkelunterschied in Grad (Standard: 35.0)


### Current State

- [ ] **Matching**: Get all OSM Ways, which are part of the RVN
  - [x] Get all bikelanes
  - [x] Get all streets
  - [x] Get all other types of ways
  - [x] Add Extra RVN segments
  - [x] Merge all differente way types
  - [x] Enable manual inclusion and exclusion
  - [ ] Cut off ways which are out of buffer
- [ ] **Snapping**: Attributes on RVN edges
  - [x] Snap geometry to RVN edges
  - [x] Assign OSM Way attributes to RVN edges
  - [x] Calculate direction of the edges (oneway)
  - [x] Solve direction based snapping of edges 
- [ ] **Aggregation**: Aggregate edges
  - [x] Find way to calculate the length of the edges
  - [x] Merge edges where length > 50 m, even when attributes changes
  - [x] Direction based layers
- [ ] RVN edges on OSM Ways
- [x] Provide Extract for Neukölln (via script)
- [x] Provide TXT file of all OSM  Ways, which are part of the RVN

### Next ToDos

- [x] Direction `ri` based spatial search and choice of RVN edges
- [x] Calculate beginnt_bei_vp and endet_bei_vp, then element_nr
  - [x] Aggregating by element_nr 
  - [ ] Fix UNKNOWN issues
- [x] Dual carriageway oneway problems solve in snapping
- [ ] Improve difference calculations between streets and bikelanes -> search for one Einrichtungsverkehr way, if so, add Mischverkehr
- [x] Add script for converting aggregated geopackage to one merged GeoJSON
- [ ] ~~Merging all three datasets into one file with three layers~~


## Filters

Every filter has its own Python module. **All filters are enabled by default.**

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
