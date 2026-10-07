#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
create_mask.py
--------------------------------------------------------------------
Erzeugt je eine Maskierung für das Gesamtnetz und das Kartierungs-Netz von
REN+: die Fläche Berlins ohne einen Puffer um die Netzkanten. In der Karte
abgedunkelt dargestellt, bleibt so nur der Bereich entlang des Netzes sichtbar.

Entspricht der Maskierung des Radvorrangnetzes von 2025 (tilda-static-data,
region-berlin/radverkehrsnetz-vorrangnetz-mask), dort in QGIS erstellt:
Puffer 25 m, Differenz zu Berlin, vereinfachen.

INPUT:
- ren-network/output/ren_netz_gesamt.gpkg
- ren-network/output/ren_netz_kartierung.gpkg
- data/Berlin Bezirke.gpkg

OUTPUT (WGS84, je ein MultiPolygon):
- ren-network/output/ren_netz_gesamt_maske.geojson
- ren-network/output/ren_netz_kartierung_maske.geojson
"""

import logging
from pathlib import Path

import geopandas as gpd

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "ren-network" / "output"
DISTRICTS_PATH = ROOT / "data" / "Berlin Bezirke.gpkg"
# Datei des Netzes (ohne Endung) und Name der Maske
NETWORKS = {
    "ren_netz_gesamt": "Berlin ohne REN+-Gesamtnetz",
    "ren_netz_kartierung": "Berlin ohne REN+-Kartierungsnetz",
}

CRS = "EPSG:25833"
# Weniger als 25 m schneidet stellenweise separat geführte Radwege ab
BUFFER_M = 25
# Entspricht etwa der Toleranz von 0,0001 Grad der Maskierung von 2025
SIMPLIFY_M = 7

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def create_mask(network_name, mask_name, berlin):
    network = gpd.read_file(OUTPUT_DIR / f"{network_name}.gpkg").to_crs(CRS)
    output_path = OUTPUT_DIR / f"{network_name}_maske.geojson"

    corridor = network.buffer(BUFFER_M).union_all()
    mask = berlin.difference(corridor).simplify(SIMPLIFY_M)

    result = gpd.GeoDataFrame({"name": [mask_name]}, geometry=[mask], crs=CRS).to_crs("EPSG:4326")
    result.to_file(output_path, driver="GeoJSON", COORDINATE_PRECISION=6)

    logging.info(f"Netz: {len(network)} Kanten, Puffer {BUFFER_M} m, Vereinfachung {SIMPLIFY_M} m")
    logging.info(f"Maske: {len(mask.geoms)} Flächen, {mask.area / berlin.area:.0%} der Fläche Berlins, "
                 f"{output_path.stat().st_size / 1e6:.1f} MB")
    logging.info(f"Geschrieben: {output_path}")


def main():
    berlin = gpd.read_file(DISTRICTS_PATH).to_crs(CRS).union_all()
    for network_name, mask_name in NETWORKS.items():
        create_mask(network_name, mask_name, berlin)


if __name__ == "__main__":
    main()
