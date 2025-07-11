---
applyTo: '*/**.py'
---

Uses Python, geopandas and other libraries for processing geodata and openstreetmap data.

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