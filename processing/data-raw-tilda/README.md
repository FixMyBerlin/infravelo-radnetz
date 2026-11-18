# Rohdaten TILDA Eingabe

Von diesem Ordner werden die originalen Geodaten, die von TILDA heruntergeladen wurden, geladen.

Diese Exporte müssen aus demselben Verarbeitungslauf stammen wie `data/TILDA Routing Berlin.gpkg` (siehe `prepare_tilda_routing.py`).

Dieser Ordner sollte nur fünf Dateien enthalten:

* **bikelanes.fgb**
* **roads.fgb**
* **roadsPathClasses.fgb**

=> TILDA Originaldaten

* README.md

=> Diese README-Datei

* .gitignore

=> Speichern Sie die Originaldaten nicht in GitHub.

## Download

Die drei Exporte kommen aus der TILDA-API (Region `infravelo`, braucht einen API-Key als `apiKey`-Parameter, siehe `ATLAS_API_KEY_PRODUCTION` in der `.env` von tilda-geo):

```sh
for t in bikelanes roads roadsPathClasses; do
  curl -fsSL -o "$t.fgb" "https://tilda-geo.de/api/export/infravelo/$t?format=fgb&apiKey=$ATLAS_API_KEY"
done
```

Der Export muss `smoothness`, `smoothness_source`, `surface`, `maxspeed`, `maxspeed_source`, `osm_maxspeed_forward`, `osm_maxspeed_backward` und `osm_maxspeed_conditional` (roads) sowie `parent_maxspeed` (bikelanes) und `adjoining_maxspeed` (bikelanes, roadsPathClasses) enthalten. Sie gehen als `tilda_surface`, `tilda_smoothness*`, `tilda_maxspeed*` in Datensatz B und C. Die beiden `*_maxspeed`-Spalten der Radwege und Wege fehlen in den Exporten bis 2026-10-05; dann bleibt `tilda_maxspeed` an Radwegen und Wegen leer.

Der Datenstand steht im Dateinamen der Antwort (`Content-Disposition`, z. B. `infravelo_bikelanes_2026-11-03.fgb`).
Aktueller Stand in diesem Ordner: **2026-11-03**.

`data/TILDA Routing Berlin.gpkg` muss danach aus demselben Lauf nachgeladen werden (`https://tilda-geo.de/api/export/infravelo/routing?format=gpkg&apiKey=$ATLAS_API_KEY`, Region `berlin` gibt es nicht mehr).

## Konvertieren zu TILDA * Berlin.fgb

Führe `./process_tilda_data.sh` aus.