#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
download_lsa.py
--------------------------------------------------------------------
Lädt Lichtsignalanlagen aus zwei Quellen für build_knotenpunkte.py:

- Open Data: WFS lsa:lsa (gdi.berlin.de)
- OpenStreetMap: highway=traffic_signals sowie Querungen mit Signal
  (crossing=traffic_signals, crossing:signals=yes) im Stadtgebiet

Übernommen aus infravelo-ml-knotenpunkte/vorbefuellung/01_daten_holen.py.

OUTPUT (EPSG:25833, nicht versioniert):
- data/netzquellen/lsa.gpkg
- data/netzquellen/osm_ampeln.gpkg

Vorhandene Dateien werden übersprungen, --neu lädt erneut.
"""

import argparse
import logging
import time
from pathlib import Path

import geopandas as gpd
import requests
from shapely.geometry import Point

ROOT = Path(__file__).resolve().parent.parent
SOURCES_DIR = ROOT / "data" / "netzquellen"
LSA_PATH = SOURCES_DIR / "lsa.gpkg"
OSM_PATH = SOURCES_DIR / "osm_ampeln.gpkg"
DISTRICTS_PATH = ROOT / "data" / "Berlin Bezirke.gpkg"

CRS = "EPSG:25833"
WFS_URL = "https://gdi.berlin.de/services/wfs/lsa"
WFS_LAYER = "lsa:lsa"
WFS_PAGE_SIZE = 5000

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
OVERPASS_QUERY = """
[out:json][timeout:300];
area["boundary"="administrative"]["admin_level"="4"]["name"="Berlin"]->.berlin;
(
  node["highway"="traffic_signals"](area.berlin);
  node["crossing"="traffic_signals"](area.berlin);
  node["crossing:signals"="yes"](area.berlin);
);
out body;
"""
OSM_TAGS = ["highway", "crossing", "crossing:signals", "traffic_signals"]
USER_AGENT = "infravelo-radnetz/knotenpunkte (Berlin Open Data + OSM)"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def save(gdf, path):
    tmp = path.with_suffix(".tmp.gpkg")
    gdf.to_file(tmp, layer=path.stem, driver="GPKG")
    tmp.replace(path)
    logging.info(f"Geschrieben: {path} ({len(gdf)} Objekte)")


def download_wfs(session):
    features, start = [], 0
    while True:
        params = {
            "service": "WFS", "version": "2.0.0", "request": "GetFeature",
            "typeNames": WFS_LAYER, "outputFormat": "application/json",
            "count": WFS_PAGE_SIZE, "startIndex": start,
        }
        response = session.get(WFS_URL, params=params, timeout=300)
        response.raise_for_status()
        page = response.json().get("features", [])
        features.extend(page)
        if len(page) < WFS_PAGE_SIZE:
            break
        start += WFS_PAGE_SIZE
        time.sleep(0.5)
    # Die Berliner WFS liefern GeoJSON in EPSG:25833, nicht in WGS84
    return gpd.GeoDataFrame.from_features(features, crs=CRS)


def download_osm(session):
    response = None
    for attempt in range(6):
        url = OVERPASS_URLS[attempt % len(OVERPASS_URLS)]
        logging.info(f"Overpass über {url}")
        try:
            response = session.post(url, data={"data": OVERPASS_QUERY}, timeout=360)
            response.raise_for_status()
            break
        except requests.RequestException as error:
            logging.warning(f"{error}, nächster Versuch in 15 s")
            response = None
            time.sleep(15)
    if response is None:
        raise SystemExit("Overpass nicht erreichbar, später erneut versuchen.")

    elements = [e for e in response.json().get("elements", []) if "lat" in e]
    data = {"osm_id": [e["id"] for e in elements]}
    for tag in OSM_TAGS:
        data[tag] = [e.get("tags", {}).get(tag) for e in elements]
    osm = gpd.GeoDataFrame(data, geometry=[Point(e["lon"], e["lat"]) for e in elements], crs="EPSG:4326").to_crs(CRS)

    # Sicherheitshalber auf das Stadtgebiet zuschneiden
    berlin = gpd.read_file(DISTRICTS_PATH).to_crs(CRS).union_all()
    inside = osm.within(berlin)
    logging.info(f"{(~inside).sum()} OSM-Objekte außerhalb der Bezirksgrenzen verworfen")
    return osm[inside].reset_index(drop=True)


def main():
    parser = argparse.ArgumentParser(description="Lichtsignalanlagen aus Open Data und OSM laden")
    parser.add_argument("--neu", action="store_true", help="vorhandene Dateien erneut laden")
    args = parser.parse_args()

    SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    for path, download in [(LSA_PATH, download_wfs), (OSM_PATH, download_osm)]:
        if path.exists() and not args.neu:
            logging.info(f"Vorhanden, übersprungen: {path}")
            continue
        save(download(session), path)


if __name__ == "__main__":
    main()
