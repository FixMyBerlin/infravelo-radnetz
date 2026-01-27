# InfraVelo Radnetz - AI Coding Agent Instructions

This project converts bicycle infrastructure data from OpenStreetMap (processed via TILDA) into Berlin's structured Detailnetz (detailed street network). The codebase is bilingual: Python for geospatial processing, TypeScript/React for the QA inspector web app.

## Architecture Overview

The system processes data through a 4-step pipeline, each maintaining intermediate outputs for caching:

1. **TILDA Data Preparation** (`process_tilda_data.sh`) - Clips raw TILDA exports to Berlin boundaries and translates attributes
2. **Matching** (`processing/start_matching.py`) - Spatially matches OSM ways along the Radvorrangsnetz (RVN - priority cycling network)
3. **Snapping** (`processing/start_snapping.py`) - Geometrically aligns OSM data to Detailnetz edges with direction-aware attribute transfer
4. **Aggregation** (`processing/start_aggregation.py`) - Consolidates multiple attribute variations per edge into final features

**Critical Concept: Directional Edges (`ri` attribute)**
- Every street segment (`element_nr`) typically produces **two edges**: `ri=0` (forward direction) and `ri=1` (backward direction)
- Direction determined by comparing angles between network edge and TILDA way (< 90° = same direction)
- Aggregation ALWAYS groups by `element_nr` + `ri` together
- Oneway streets produce only one edge

## Project Structure

```
data/                    # Input geodata (Detailnetz, RVN, Berlin boundaries, override lists)
data-raw-tilda/          # Raw TILDA exports (bikelanes.fgb, roads.fgb, roadsPathClasses.fgb)
processing/              # Core Python pipeline scripts (start_matching.py, start_snapping.py, start_aggregation.py)
  helpers/               # Reusable geo utilities (globals.py, snapping_calculations.py, district_assignment.py)
  matching/              # Matching-specific logic (orthogonal_filter.py, manual_interventions.py)
scripts/                 # Preparatory scripts (assign_element_nr_to_rvn.py, filter_bus_stops_on_rvn.py)
validation/              # Analysis and debugging scripts for QA purposes (debug_segment_conversion.py, analyze_schutzstreifen_at_intersections.py)
inspector/               # React/TypeScript QA web app with MapLibre
output/                  # Generated intermediate and final geodata (matched/, snapping/, aggregated_rvn_final.gpkg)
output-last-run/         # Backup of previous run's final files
```

## Development Workflows

### Python Processing Pipeline

**Setup and execution:**
```bash
# Create venv and install dependencies
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt

# Full pipeline execution (use --clip neukoelln for faster testing)
./process_tilda_data.sh && ./execute_processing.sh --clip neukoelln

# Individual steps (useful with --start-step)
./.venv/bin/python processing/start_matching.py --clip neukoelln
./.venv/bin/python processing/start_snapping.py --clip neukoelln
./.venv/bin/python processing/start_aggregation.py --input ./output/snapping_converted_bikelanes.fgb
```

**Important flags:**
- `--clip <region>`: Process only neukoelln/norden/sueden (ALWAYS use for testing - much faster)
- `--view z/lat/lon`: Viewport clipping for tiny test areas (outputs to output-bbox/)
- `--clean-cache`: Delete cached intermediate files (use when debugging caching issues)
- `--start-step N`: Resume from step N (requires previous steps' outputs exist)

## Python Conventions

**Critical patterns:**
- Import constants from `helpers/globals.py` (DEFAULT_CRS = 25833, DEFAULT_OUTPUT_DIR)
- All processing scripts have extensive docstrings listing INPUT/OUTPUT files
- Use logging instead of print statements (`logging.info()`, `logging.warning()`)
- Add helpers to `processing/helpers/` when reusable across modules
- MultiLineString geometries exist alongside LineString - always handle both
- Delete cached files before testing changes: `rm -rf output/matched/ output/snapping/`

**Code style:**
- German comments and logging messages
- English function/variable names
- Structure code into focused functions (<100 lines)
- Remove unused imports
- Update requirements.txt for new dependencies
- **Place analysis and debugging scripts in `validation/` directory** (not in processing/helpers/)

**Common helper usage:**
```python
from helpers.globals import DEFAULT_CRS, DEFAULT_OUTPUT_DIR
from helpers.progressbar import print_progressbar
from helpers.clipping import clip_to_region, clip_to_view
from helpers.district_assignment import assign_district_to_edges
from helpers.snapping_calculations import calculate_line_angle, determine_segment_direction
```

## Snapping Algorithm Deep Dive

The most complex part of the system. Transfers OSM attributes to a topologically correct, direction-oriented network:

1. **Segmentation**: Split target network into 2.5m uniform segments for precise attribution
2. **Spatial matching**: Find candidate TILDA ways within buffer (default 30m) for each segment
3. **Direction-aware attribution**: Calculate angle between segment and TILDA way
   - `angle_diff < 90°` → `ri=0` (forward)
   - `angle_diff >= 90°` → `ri=1` (backward)
4. **Priority scoring**: Best candidate selected via composite score (see `SnappingPriorities` in `snapping_calculations.py`)
5. **Merging**: Consecutive segments with identical attributes are merged back together

**Special case: Kreisverkehre (roundabouts)**
- Closed rings (start == end point) have undefined angle via standard calculation
- System detects rings (distance < 1cm) and computes tangent at nearest point
- Enables correct direction determination for circular geometries

## Manual Interventions

The system supports manual data corrections via text files in `data/`:
- `include_ways.txt` - OSM way IDs to force include (one per line)
- `exclude_ways.txt` - OSM way IDs to force exclude
- `override_ways.txt` - Spatial override with custom attributes
- `override_ways.gpkg` - GeoPackage alternative to override_ways.txt
- `opposite_edge_overwrite_element_nr.txt` - Remove backward direction (ri=1) for specific element_nr

## Testing and Debugging

**Always test with neukoelln clipping first:**
```bash
# Fast iteration cycle
rm -rf output/matched/ output/snapping/  # Clear caches
./execute_processing.sh --clip neukoelln --start-step 2
```

**Common issues:**
- Caching problems → use `--clean-cache` or manually delete output subdirectories
- Missing TILDA data → ensure `./process_tilda_data.sh` ran successfully
- Direction errors → verify `ri` attribute calculation in `snapping_calculations.py`
- Aggregation mismatches → check that grouping uses BOTH `element_nr` AND `ri`

## Key Files Reference

- `processing/helpers/snapping_calculations.py` - Core direction/angle computation
- `processing/helpers/globals.py` - Project-wide constants
- `execute_processing.sh` - Main orchestration script with argument parsing

## When Helping Users

1. **Always activate Python venv** before running Python commands
2. **Check for manual code changes** before proposing edits - integrate, don't overwrite
3. **Test with --clip neukoelln** for speed
4. **Ask about preferences** when multiple implementation approaches exist
5. **Update requirements.txt** when adding Python dependencies
6. **Remember dual directions** - most features have ri=0 and ri=1 variants
