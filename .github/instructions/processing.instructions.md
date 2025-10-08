---
applyTo: '*/**.py'
---

Uses Python, geopandas and other libraries for processing geodata and openstreetmap data.

# Structure
There are three main processes and python scripts:
1. Matching (processing/start_matching.py)
2. Snapping (processing/start_snapping.py)
3. Aggregation (processing/aggregate_final_model.py)

## Snapping Algorithm

This script addresses the challenge of accurately transferring OSM (OpenStreetMap) attributes to a topologically correct, direction-oriented street network (such as a cycling priority network). The goal is to assign relevant OSM properties (like width, surface color, physical protection, surface type, one-way status, etc.) to each segment of the target network.

The methodology involves first splitting the target network into small, uniform segments to allow for precise attribute matching. For each segment, suitable OSM ways are identified within a spatial buffer, and their attributes are transferred—taking both geometric proximity and directional alignment into account to ensure accurate matches. Finally, adjacent segments with identical attributes are merged back together.

The result is an enriched street network where each segment carries the relevant OSM attributes.

## Richtungsberechnung (ri-Attribut)

Das `ri`-Attribut (Richtung) ist zentral für das gesamte Datenmodell und wird im Snapping-Prozess berechnet.

**Werte:**
- `ri=0`: Hinrichtung (Kante verläuft in gleicher Richtung wie die Geometrie)
- `ri=1`: Rückrichtung (Kante verläuft entgegengesetzt zur Geometrie)

**Berechnung:**

Die Richtung wird durch Vergleich der Winkel zwischen der Netzwerkkante und dem gematchten TILDA-Weg bestimmt:

1. **Winkelberechnung** (`calculate_line_angle`): Für jede Geometrie wird der Richtungswinkel vom Start- zum Endpunkt berechnet (0-360°)
2. **Richtungsbestimmung** (`determine_segment_direction`): 
   - Berechnet Winkeldifferenz zwischen Segment und OSM-Weg
   - Wenn Winkeldifferenz < 90°: `ri=0` (gleiche Richtung)
   - Wenn Winkeldifferenz ≥ 90°: `ri=1` (entgegengesetzte Richtung)

**Wichtig:**
- Pro Straßensegment (`element_nr`) entstehen normalerweise **zwei Kanten** (ri=0 und ri=1), eine pro Fahrtrichtung
- Ausnahme: Bei Einbahnstraßen gibt es nur eine Kante
- Die Aggregation erfolgt immer nach `element_nr` UND `ri` zusammen

## Chat

- When executing code in the console, don't forget to configure/activate the virtual environment first
- When there is a follow up request in chat, first check if the user applied changes to the code manually; do not overwrite those changes but incorporate them.
- Add useful and structured comments to the code in german.
- Structure the code in useful functions with sensible function size.
- Use english function and variables names.
- Use logging instead of print statements.
- Import packages only once at the top of the file.
- Use the globals.py if possible to import constants like DEFAULT_CRS or DEFAULT_OUTPUT_DIR.
- Use helpers from the helpers folder if possible.
- Add new helpers, if they can be used in different modules, to the helpers folder.
- Remove unused imports.
- When there are many different possibilites in the method or implementation, first ask the user for their preferences.
- Update the requirements.txt file with the new packages used in the code.
- Every Python module should include all relevant input and output files in the docstring at the top of the file.
- When testing the scripts, make sure to execute the scripts with the neukoelln cli parameter, so the execution is faster.
- Be aware, that there are always MultiLineString geometry objects, not just LineString.
- Remove cached files, before running python scripts.
- Be aware, that there are existing two directions for every edge in snapping and aggregated geodata!
