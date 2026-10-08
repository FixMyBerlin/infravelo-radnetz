#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
merge_bewertungen.py
--------------------------------------------------------------------
Führt die Bewertungen aus der Knotenpunkt-App mit dem Knotenpunkt-Datensatz
zum Abgabestand zusammen.

Übernommen werden nur vollständig bewertete Knoten (status = complete), die
nicht 2025 geliefert wurden. Werte von 2025 bleiben unverändert. Die
App-Attribute KP_HVS und LSA_KP werden nach Hauptverkehrsstrasse und
LSA_vorhanden geschrieben und ersetzen dort die abgeleiteten Werte.

INPUT:
- knotenpunkte/output/knotenpunkte_gesamt.gpkg (build_knotenpunkte.py)
- GeoJSON-Export der Knotenpunkt-App (ratings-<bereich>-<datum>.geojson)

OUTPUT:
- knotenpunkte/output/knotenpunkte_abgabe.gpkg (Layer: knotenpunkte) / .geojson (WGS84)

VERWENDUNG:
    python knotenpunkte/merge_bewertungen.py ratings-infravelo-2026-2026-11-30.geojson
"""

import argparse
import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd

from build_knotenpunkte import FINAL_COLUMNS, NODE_ID, OUTPUT_DIR, OUTPUT_LAYER, OUTPUT_PATH, id_text

OUTPUT_DELIVERY_PATH = OUTPUT_DIR / "knotenpunkte_abgabe.gpkg"

# App-Attribut -> Attribut im Datensatz
APP_COLUMNS = {
    "Mar_RVF_KP": "Mar_RVF_KP",
    "Furt_rot": "Furt_rot",
    "Fl_Linksab": "Fl_Linksab",
    "vorgez_Fl": "vorgez_Fl",
    "RFS_Mitte": "RFS_Mitte",
    "KP_Nichtbetrachten": "KP_Nichtbetrachten",
    "Mapillary-ID": "Mapillary-ID",
    "Kommentar": "Kommentar",
    "KP_HVS": "Hauptverkehrsstrasse",
    "LSA_KP": "LSA_vorhanden",
}
# Reihenfolge, in der die App die ID ablegt (properties.id ist die geparste ID)
APP_ID_COLUMNS = ["id", "NUMMER", NODE_ID, "Knotenpunkt-ID"]


def load_ratings(path):
    ratings = gpd.read_file(path)
    id_column = next((c for c in APP_ID_COLUMNS if c in ratings.columns), None)
    if id_column is None:
        raise SystemExit(f"Keine ID-Spalte {APP_ID_COLUMNS} in {path}")
    ratings["node_id"] = ratings[id_column].map(id_text)
    logging.info(f"App-Export: {len(ratings)} Knoten, status {ratings['status'].value_counts().to_dict()}, "
                 f"qa {ratings['qa'].value_counts().to_dict()}")
    return ratings[ratings["status"] == "complete"].set_index("node_id")


def merge(nodes, ratings):
    delivered = nodes.loc[nodes["bearbeitet_2025"] == "ja", NODE_ID]
    in_2025 = ratings.index.isin(delivered)
    if in_2025.any():
        logging.warning(f"{in_2025.sum()} bewertete Knoten wurden 2025 geliefert und bleiben unverändert: "
                        f"{sorted(ratings.index[in_2025])[:10]}")
    unknown = ~ratings.index.isin(nodes[NODE_ID])
    if unknown.any():
        logging.warning(f"{unknown.sum()} bewertete Knoten fehlen im Datensatz: {sorted(ratings.index[unknown])[:10]}")
    ratings = ratings[~in_2025 & ~unknown]

    rows = nodes[NODE_ID].isin(ratings.index)
    source = ratings.reindex(nodes.loc[rows, NODE_ID])
    source.index = nodes.index[rows]
    for app_column, column in APP_COLUMNS.items():
        if app_column not in source.columns:
            continue
        values = source[app_column]
        if column in ("Hauptverkehrsstrasse", "LSA_vorhanden"):
            # Übersprungene Knoten haben keine Werte, dann bleibt die Ableitung stehen
            values = values.dropna().astype(int).astype(bool)
            nodes.loc[values.index, column] = values
            if column == "LSA_vorhanden":
                nodes.loc[values.index, "LSA_Konflikt"] = None
        else:
            nodes.loc[rows, column] = values
    # Die App setzt ist_virtuell standardmäßig auf 0, gepflegte virtuelle Knoten bleiben virtuell
    nodes.loc[rows, "ist_virtuell"] = nodes.loc[rows, "ist_virtuell"].combine(source["ist_virtuell"].fillna(0).astype(int), max)

    open_nodes = (nodes["bearbeitet_2025"] == "nein") & ~rows
    logging.info(f"Übernommen: {rows.sum()} Knoten, noch offen: {open_nodes.sum()}")
    return nodes


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s", force=True)
    parser = argparse.ArgumentParser(description="Bewertungen der Knotenpunkt-App übernehmen")
    parser.add_argument("export", type=Path, help="GeoJSON-Export der Knotenpunkt-App")
    args = parser.parse_args()

    nodes = gpd.read_file(OUTPUT_PATH, layer=OUTPUT_LAYER)
    # Nullbare Booleans liest geopandas als float zurück
    for column in ["LSA_vorhanden", "Betrachtung"]:
        nodes[column] = nodes[column].map({1.0: True, 0.0: False}).astype("boolean")
    nodes["Hauptverkehrsstrasse"] = nodes["Hauptverkehrsstrasse"].astype("boolean")
    nodes = merge(nodes, load_ratings(args.export))

    # Betrachtung wie in build_knotenpunkte.add_betrachtung neu berechnen
    lsa = nodes["LSA_vorhanden"]
    nodes["Betrachtung"] = pd.Series(pd.NA, index=nodes.index, dtype="boolean")
    nodes.loc[lsa.notna(), "Betrachtung"] = lsa[lsa.notna()].astype(bool)
    nodes.loc[nodes["Hauptverkehrsstrasse"].fillna(False), "Betrachtung"] = True
    nodes["KP_Nichtbetrachten"] = pd.to_numeric(nodes["KP_Nichtbetrachten"]).astype("Int64")

    nodes = nodes[FINAL_COLUMNS]
    nodes.to_file(OUTPUT_DELIVERY_PATH, layer=OUTPUT_LAYER, driver="GPKG")
    logging.info(f"Geschrieben: {OUTPUT_DELIVERY_PATH}")
    geojson_path = OUTPUT_DELIVERY_PATH.with_suffix(".geojson")
    nodes.to_crs("EPSG:4326").to_file(geojson_path, driver="GeoJSON", COORDINATE_PRECISION=7)
    logging.info(f"Geschrieben: {geojson_path}")


if __name__ == "__main__":
    main()
