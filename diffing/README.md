# GeoJSON Diffing Tool

This tool compares two GeoJSON files based on `element_nr` and `ri` (composite key) and generates detailed diff reports.

> [!warning]
> The code in this folder is "vibe coded" and has not been checked in detail.
> Only the result files have been spot-checked.

## How It Works

1. **Indexing**: Features are indexed by `(element_nr, ri)` composite key
2. **Comparison**: Compares OLD and NEW datasets to identify:
   - **ADDED**: Features in NEW but not in OLD
   - **DELETED**: Features in OLD but not in NEW
   - **MODIFIED**: Features in both with changed properties or geometry
3. **Merging**: DELETE + ADD pairs with the same `element_nr` and `ri` are merged into MODIFIED entries
4. **Splitting**: Output is split into three categories:
   - **fuehr**: Features where `fuehr` property changed
   - **breite**: Features where the `breite` property changed (separate diff file)
   - **properties**: Features where other (non-fuehr, non-breite) properties changed
5. **Output**: Generates both GeoJSON and CSV formats for each category

For MODIFIED features:
- Changed properties shown with `_OLD` and `_NEW` suffixes
- Geometry hash (SHA256 of NEW geometry)
- Old geometry stored if geometry changed

## Usage

### Basic Command

```bash
.venv/bin/python diffing/diff.py \
  /path/to/OLD/file.geojson \
  /path/to/NEW/file.geojson
```

### Output Directory

By default, outputs are written to `diffing/result/`. You can specify a custom output directory:

```bash
.venv/bin/python diffing/diff.py OLD.geojson NEW.geojson --output-dir /path/to/output
```

## Output Files

The tool generates 7 files in the output directory:

1. **`diff_fuehr.geojson`**: GeoJSON with features where `fuehr` property changed
2. **`diff_fuehr.csv`**: CSV version (geometry omitted, includes TILDA links)
3. **`diff_breite.geojson`**: GeoJSON with features where `breite` property changed
4. **`diff_breite.csv`**: CSV version (geometry omitted, includes TILDA links)
5. **`diff_properties.geojson`**: GeoJSON with features where other properties changed
6. **`diff_properties.csv`**: CSV version (geometry omitted, includes TILDA links)
7. **`report.md`**: Summary report with statistics and file information

**Property Format:**
- ADDED: Properties with `_NEW` suffix
- DELETED: Properties with `_OLD` suffix
- MODIFIED: Changed properties with both `_OLD` and `_NEW` suffixes
- Properties sorted: `_`-prefixed → other → `tilda_`-prefixed → `prio_`-prefixed

**CSV Format:**
- First column: `TILDA_Link` (generated from geometry centroid)
- Same property columns as GeoJSON (geometry excluded)
- Same property sorting as GeoJSON

## Requirements

- Python virtual environment (`.venv`) with dependencies from `requirements.txt`
- Both input GeoJSON files must have features with an `element_nr` property

## Notes

- Features without `element_nr` are skipped with a warning
- Duplicate `element_nr` values are logged as warnings
- The tool uses the local Python environment (`.venv/bin/python`) to ensure all dependencies are available
