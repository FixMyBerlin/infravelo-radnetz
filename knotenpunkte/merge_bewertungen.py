#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
merge_bewertungen.py
--------------------------------------------------------------------
Führt die Bewertungen aus der Knotenpunkt-App mit dem Knotenpunkt-Datensatz
zum Abgabestand zusammen.

Übernommen werden nur vollständig bewertete Knoten (status = complete), die
nicht 2025 geliefert wurden. Werte von 2025 bleiben unverändert. App und
Datensatz nutzen dieselben Attribute und Werte; KP_HVS und LSA_KP aus der
App ersetzen die abgeleiteten Werte.

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

from build_knotenpunkte import (BINARY_COLUMNS, DERIVED_COLUMNS, FINAL_COLUMNS, NODE_ID, OUTPUT_DIR, OUTPUT_LAYER,
                                OUTPUT_PATH, add_betrachtung, id_text)

OUTPUT_DELIVERY_PATH = OUTPUT_DIR / "knotenpunkte_abgabe.gpkg"

# Bewertungen der App; KP_HVS und LSA_KP (DERIVED_COLUMNS) nur, wenn gesetzt
RATED_COLUMNS = ["Mar_RVF_KP", "Furt_rot", "Fl_Linksab", "vorgez_Fl", "RFS_Mitte",
                 "KP_Nichtbetrachten", "Mapillary-ID", "Kommentar"]
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
    for column in RATED_COLUMNS:
        if column in source.columns:
            nodes.loc[rows, column] = source[column]
    for column in DERIVED_COLUMNS:
        # Übersprungene Knoten haben keine Werte, dann bleibt die Ableitung stehen
        values = source[column].dropna().astype(int) if column in source.columns else pd.Series(dtype=int)
        nodes.loc[values.index, column] = values
        if column == "LSA_KP":
            nodes.loc[values.index, "LSA_Konflikt"] = None
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
    # Nullbare Ganzzahlen liest geopandas als float zurück
    for column in [*BINARY_COLUMNS, "KP_Nichtbetrachten"]:
        nodes[column] = nodes[column].astype("Int64")
    nodes = merge(nodes, load_ratings(args.export))

    nodes = add_betrachtung(nodes.astype({c: "boolean" for c in BINARY_COLUMNS}))
    nodes = nodes.astype({c: "Int64" for c in BINARY_COLUMNS})
    nodes["KP_Nichtbetrachten"] = pd.to_numeric(nodes["KP_Nichtbetrachten"]).astype("Int64")

    nodes = nodes[FINAL_COLUMNS]
    nodes.to_file(OUTPUT_DELIVERY_PATH, layer=OUTPUT_LAYER, driver="GPKG")
    logging.info(f"Geschrieben: {OUTPUT_DELIVERY_PATH}")
    geojson_path = OUTPUT_DELIVERY_PATH.with_suffix(".geojson")
    nodes.to_crs("EPSG:4326").to_file(geojson_path, driver="GeoJSON", COORDINATE_PRECISION=7)
    logging.info(f"Geschrieben: {geojson_path}")


if __name__ == "__main__":
    main()
