# Rohdaten TILDA Eingabe

In diesem Ordner liegen die originalen TILDA-Exporte. Sie werden nicht in GitHub gespeichert (`.gitignore`).

* **bikelanes.fgb**, **roads.fgb**, **roadsPathClasses.fgb**: TILDA-Exporte
* **tilda_export.json**: Datenstand jedes Exports, geschrieben von `data/download_tilda.sh`
* **knotenpunkte_mit_id_und_bezirken.gpkg**: Knotenpunkte für die Schutzstreifen-Konvertierung (`start_bikelane_conversion.py`, `scripts/convert_knotenpunkte.py`), kein TILDA-Export
* README.md, .gitignore

## Download

```sh
data/download_tilda.sh processing   # aus dem Projekt-Root
```

Das Skript lädt die drei Exporte aus der TILDA-API (Region `infravelo`) hierher und den Export `routing` nach `data/TILDA Routing Berlin.gpkg`. Den API-Key nimmt es aus `ATLAS_API_KEY` oder aus `ATLAS_API_KEY_PRODUCTION` in der `.env` von tilda-geo. Erst wenn alle vier Downloads geklappt haben, ersetzt es die vorhandenen Dateien. TILDA rechnet die Daten einmal pro Nacht neu; wurde heute schon geladen (`geladen` in `tilda_export.json`), überspringt das Skript den Download. `--neu` lädt trotzdem.

Den Datenstand liefert TILDA im Dateinamen der Antwort (`Content-Disposition`, z. B. `infravelo_bikelanes_<datum>.fgb`). Das Skript schreibt ihn nach `tilda_export.json`. Die Datenstände der Exporte dürfen sich unterscheiden. `prepare_tilda_routing.py` bricht aber ab, wenn mehr als 1 % der Routing-Kanten kein Quellobjekt in den drei Exporten finden.

Der Export muss `smoothness`, `smoothness_source`, `surface`, `maxspeed`, `maxspeed_source`, `osm_maxspeed_forward`, `osm_maxspeed_backward` und `osm_maxspeed_conditional` (roads) sowie `parent_maxspeed` (bikelanes) und `adjoining_maxspeed` (bikelanes, roadsPathClasses) enthalten. Sie gehen als `tilda_surface`, `tilda_smoothness*`, `tilda_maxspeed*` in Datensatz B und C. Die beiden `*_maxspeed`-Spalten der Radwege und Wege fehlen in den Exporten bis 2026-10-05; dann bleibt `tilda_maxspeed` an Radwegen und Wegen leer.

## Weiterverarbeitung

`processing/run_all.sh` lädt die Daten und führt die ganze Prozessierung aus (siehe [processing/README.md](../README.md)).
