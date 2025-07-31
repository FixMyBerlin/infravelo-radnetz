# Scripts Ordner

Diese Skripte sind vorbereitende Schritte vor der Prozessierung, aber unabhängig von dieser.

## Initiales Setup

Um die benötigten Zwischen-Ordner für Ausgaben zu erstellen, sollte einmalig das Setup-Skript ausgeführt werden:

```bash
python scripts/setup.py
```

Dadurch werden die Ordner `output/snapping` und `output/matching` angelegt (falls noch nicht vorhanden).

## RVN Node Assigment Skript

Das [`assign_node_ids.py`](./assign_node_ids.py) fügt zwei Attribute zu den *Verbindungspunkten* aus dem Detailnetz hinzu: `Knotenpunkt-ID` und `Bezirksnummer`.

## OSM LSA Punkte

Für die Erfassung der LSA an Knotenpunkten können die entsprechenden Daten aus OSM dazu helfen diese einfacher zu erkennen. Das Skript [`consolidated_osm_traffic_signals.py`](./consolidated_osm_traffic_signals.py) erzeugt eine Datei aller LSA an Knotenpunkten im RVN.

## Clip TILDA Data Skript

Um die TILDA Daten auf bestimmte Regionen (Ganz Berlin oder einzelne Bezirke) zuzuschneiden, kann dieses Skript dazu verwendet werden, um ein Clipping durchzuführen.

## Enrich RVN With Detailnetz Skript

Das Skript [enrich_rvn_with_detailnetz.py](./enrich_rvn_with_detailnetz.py) fügt fehlende Kanten im Detailnetz aus dem RVN hinzu, sodass für jeden Teil des RVN eine Kanten im Knoten-Kanten-Modell existiert.

## Assign Element NR to RVN Skript

Das Skript [assign_element_nr_to_rvn.py](./assign_element_nr_to_rvn.py) verwendet das berechnete RVN und fügt bei RVN Kanten, welche keine `element_nr` besitzen, diese hinzu.