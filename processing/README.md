# Processing Script

**`main.py`** is the start of the processing script. It selects all OSM ways, which are in `BUFFER_METERS` distance to the Radvorrangsnetz.

The script creates intermediate geodata versions. This enables to speed up the scripts speed when rerunning. But this can also relate to **caching issues**. So be aware, and be free to delete the `output` folder when having issues.

See [REQUIREMENTS.md](./REQUIREMENTS.md) for geodata requirements.

*Tested with Python 3.13.3.*

## Phases

- [ ] Get all OSM Ways, which are part of the RVN
  - [x] Get all bikelanes
  - [x] Get all streets
  - [ ] Get all other types of ways
  - [ ] Merge all differente way types
  - [x] Enable manual inclusion and exclusion
- [ ] Attributes on RVN edges
  - [ ] Snap geometry to RVN edges
  - [ ] Assign OSM Way attributes to RVN edges
  - [ ] Calculate direction of the edges (oneway)
  - [ ] Solve direction based snapping of edges 
  - [ ] Find way to calculate the length of the edges
- [ ] RVN edges on OSM Ways

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


## Enrich Streetnet with OSM

Execute with CLI Arguments:

```sh
python ./processing/enrich_streetnet_with_osm.py \
  --net ./output/vorrangnetz_details_combined_rvn.fgb \
  --osm ./output/matched_osm_ways.fgb \
  --out ./output/snapping_netz_enriched.gpkg
```