---
applyTo: '*/**.py'
---

Uses Python, geopandas and other libraries for processing geodata and openstreetmap data.

## Snapping Algorithm

This script addresses the challenge of accurately transferring OSM (OpenStreetMap) attributes to a topologically correct, direction-oriented street network (such as a cycling priority network). The goal is to assign relevant OSM properties (like width, surface color, physical protection, surface type, one-way status, etc.) to each segment of the target network.

The methodology involves first splitting the target network into small, uniform segments to allow for precise attribute matching. For each segment, suitable OSM ways are identified within a spatial buffer, and their attributes are transferred—taking both geometric proximity and directional alignment into account to ensure accurate matches. Finally, adjacent segments with identical attributes are merged back together.

The result is an enriched street network where each segment carries the relevant OSM attributes.

## Chat

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
