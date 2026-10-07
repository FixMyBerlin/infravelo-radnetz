#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
create_mask.py
--------------------------------------------------------------------
Erzeugt die Maskierung für das vereinheitlichte REN+-Netz: die Fläche Berlins
ohne einen Puffer um die Netzkanten. In der Karte abgedunkelt dargestellt,
bleibt so nur der Bereich entlang des Netzes sichtbar.

Entspricht der Maskierung des Radvorrangnetzes von 2025 (tilda-static-data,
region-berlin/radverkehrsnetz-vorrangnetz-mask), dort in QGIS erstellt:
Puffer 25 m, Differenz zu Berlin, vereinfachen.

INPUT:
- output/ren-network/ren_netz_vereinheitlicht.gpkg
- data/Berlin Bezirke.gpkg

OUTPUT:
- output/ren-network/ren_netz_maske.geojson (WGS84, ein MultiPolygon)
"""

import logging
from pathlib import Path

import geopandas as gpd

ROOT = Path(__file__).resolve().parent.parent
NETWORK_PATH = ROOT / "output" / "ren-network" / "ren_netz_vereinheitlicht.gpkg"
DISTRICTS_PATH = ROOT / "data" / "Berlin Bezirke.gpkg"
OUTPUT_PATH = NETWORK_PATH.with_name("ren_netz_maske.geojson")

CRS = "EPSG:25833"
# Weniger als 25 m schneidet stellenweise separat geführte Radwege ab
BUFFER_M = 25
# Entspricht etwa der Toleranz von 0,0001 Grad der Maskierung von 2025
SIMPLIFY_M = 7

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def main():
    network = gpd.read_file(NETWORK_PATH).to_crs(CRS)
    berlin = gpd.read_file(DISTRICTS_PATH).to_crs(CRS).union_all()

    corridor = network.buffer(BUFFER_M).union_all()
    mask = berlin.difference(corridor).simplify(SIMPLIFY_M)

    result = gpd.GeoDataFrame({"name": ["Berlin ohne REN+-Netz"]}, geometry=[mask], crs=CRS).to_crs("EPSG:4326")
    result.to_file(OUTPUT_PATH, driver="GeoJSON", COORDINATE_PRECISION=6)

    logging.info(f"Netz: {len(network)} Kanten, Puffer {BUFFER_M} m, Vereinfachung {SIMPLIFY_M} m")
    logging.info(f"Maske: {len(mask.geoms)} Flächen, {mask.area / berlin.area:.0%} der Fläche Berlins, "
                 f"{OUTPUT_PATH.stat().st_size / 1e6:.1f} MB")
    logging.info(f"Geschrieben: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
