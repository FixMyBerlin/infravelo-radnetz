# Data

## Eingabedaten (manuell gepflegt/updated)

Diese Dateien werden nicht von Skripten generiert und müssen manuell aktualisiert werden:

- `Berlin Radvorrangsnetz.fgb` – Gefilterte Geodaten des Radnetzes Berlin, enthält nur Kanten des Radvorrangsnetzes.
- `Berlin Bezirke.gpkg` – Bezirksgrenzen von Berlin zur räumlichen Filterung und Analyse.
- `Berlin Straßenabschnitte.gpkg` – Straßenabschnitte aus dem Detailnetz Berlin als GeoPackage.
- `Berlin Straßenabschnitte Detailnetz.fgb` – Straßenabschnitte aus dem Detailnetz Berlin als FlatGeobuf.
- `Berlin_Gebiet_Norden.gpkg` – Gebietsgrenze für die Verarbeitung der nördlichen Bezirke von Berlin.
- `Berlin_Gebiet_Süden.gpkg` – Gebietsgrenze für die Verarbeitung der südlichen Bezirke von Berlin.
- `Bezirk Neukölln Grenze.fgb` – Bezirksgrenze von Neukölln für gezielte Testverarbeitung.
- `Verbindungspunkte im RVN.gpkg` – Verbindungspunkte aus dem Radvorrangnetz/Detailnetz zur Netzwerkanalyse.
- `Virtuelle-Knotenpunkte.gpkg` – Manuell erstellte Knotenpunkte zur Ergänzung der Netzwerktopologie.
- `OSM-highway=bus_stop.geojson` – Bushaltestellen aus OpenStreetMap für Konvertierungen von Schutzstreifen.
- `Stop-Positions-Bus-OSM.fgb` – Bushaltestellen-Positionen aus OpenStreetMap als FlatGeobuf.

## Generierte Dateien (durch `process_tilda_data.sh`)

Diese Dateien werden durch `./process_tilda_data.sh` aus den Rohdaten in `data-raw-tilda/` erzeugt:

- `TILDA Radwege Berlin.fgb` – Auf Berlin zugeschnittene Radwege aus TILDA, basierend auf OpenStreetMap.
- `TILDA Straßen Berlin.fgb` – Auf Berlin zugeschnittene Straßen aus TILDA, basierend auf OpenStreetMap.
- `TILDA Wege Berlin.fgb` – Auf Berlin zugeschnittene Wege aus TILDA, basierend auf OpenStreetMap.

Für Lizenzen, siehe [LIZENZEN.md](./LIZENZEN.md)

# Data Modifiers

Wir verwenden manuell gepflegte Listen von OpenStreetMap-Way-IDs, die das endgültige Datenset verändern.

* `exclude_ways.txt` enthält in jeder Zeile eine OSM-Way-ID, die aus dem finalen Datensatz **entfernt** werden soll.
* `include_ways.txt` enthält in jeder Zeile eine OSM-Way-ID, die dem finalen Datensatz **hinzugefügt** werden soll.
* `opposite_edge_overwrite_element_nr.txt` enthält in jeder Zeile eine `element_nr`, für die die entgegengesetzte Richtung (ri=1) aus dem finalen Datensatz **entfernt** werden soll. Das ist nützlich, wenn der Snapping-Prozess fälschlicherweise Infrastruktur in beide Richtungen zuordnet, in der Realität aber nur die Vorwärtsrichtung (ri=0) existiert.
- `override_ways.gpkg` – GeoPackage mit räumlichen Override-Geometrien zur gezielten Überschreibung von Attributen nach dem Snapping.
- `override_ways.txt` – Textdatei mit Text-Overrides im Format `tilda_id|element_nr|ri|attributes_json` für attributbasierte Überschreibungen.
