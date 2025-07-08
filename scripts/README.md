# Scripts

These python scripts are independent from the other processing modules.

## RVN Node Assigment Script

The [`assign_node_ids.py`](./assign_node_ids.py) is a special script and independent from the other processing steps.

It add's two attributs to the *Verbindungspunkte* in the Detailnetz / Rdavorrangnetz: `Knotenpunkt-ID` and `Bezirksnummer`.

## OSM Traffic signals

For the `Verbindungspunkte` we need to know, where traffic signals are. The script [`consolidated_osm_traffic_signals.py`](./consolidated_osm_traffic_signals.py) retrieves that info from OpenStreetMap and consolidates the data.