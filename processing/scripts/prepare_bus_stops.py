#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
prepare_bus_stops.py
--------------------------------------------------------------------
Holt alle Bushaltestellen (highway=bus_stop, Plattformen) aus OpenStreetMap
für ganz Berlin und schneidet sie auf das Zielnetz zu.

Das Zielnetz wird aus helpers/netz.py gelesen:
- ren: REN+ gesamt (ren-network/output/ren_netz_gesamt.gpkg), also alle Netzquellen
       (Radvorrang-, Ergänzungs-, Radschnellverbindungs- und Hauptstraßennetz).
       Kommt eine Quelle dazu (z. B. das Touristische Radnetz), reicht ein neuer Lauf
       von ren-network/unify_networks.py und dieses Skripts.
- rvn: Radvorrangnetz 2025

Die Plattformen liegen neben der Fahrbahn. Sie werden für die Seitenbestimmung bei der
Schutzstreifen-Konvertierung gebraucht (start_bikelane_conversion.py).

INPUT:
- Overpass-API (OSM) oder der Cache data/netzquellen/osm_bushaltestellen.gpkg
- Zielnetz (siehe oben), data/Berlin Bezirke.gpkg (Zuschnitt auf Berlin)

OUTPUT (EPSG:25833):
- data/netzquellen/osm_bushaltestellen.gpkg   (alle Haltestellen in Berlin, nicht versioniert)
- output/bus_stops_on_ren.fgb | output/bus_stops_on_rvn.fgb   (Haltestellen am Zielnetz)

USAGE (aus processing/):
- python scripts/prepare_bus_stops.py [--netz ren|rvn] [--neu] [--puffer 15]
  --neu      OSM-Daten erneut laden (sonst Cache verwenden)
  --puffer   Abstand der Haltestelle zum Netz in Metern (Standard 15)
"""

import argparse
import logging
import sys
import time
from pathlib import Path

import geopandas as gpd
import requests
from shapely.geometry import Point

PROCESSING_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROCESSING_DIR))
from helpers.globals import DEFAULT_CRS
from helpers.netz import PFADE, BUSHALTESTELLEN, add_netz_argument

CRS = f"EPSG:{DEFAULT_CRS}"
CACHE_PATH = PROCESSING_DIR / "data" / "netzquellen" / "osm_bushaltestellen.gpkg"
DISTRICTS_PATH = PROCESSING_DIR / "data" / "Berlin Bezirke.gpkg"
DEFAULT_BUFFER_METERS = 15

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
OVERPASS_QUERY = """
[out:json][timeout:300];
area["boundary"="administrative"]["admin_level"="4"]["name"="Berlin"]->.berlin;
node["highway"="bus_stop"](area.berlin);
out body;
"""
OSM_TAGS = ["name", "ref", "bus", "public_transport", "direction", "bench", "shelter", "bus_bay"]
USER_AGENT = "infravelo-radnetz/prepare_bus_stops (OSM)"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def download_osm():
    """Lädt alle highway=bus_stop-Knoten in Berlin über Overpass."""
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    response = None
    for attempt in range(6):
        url = OVERPASS_URLS[attempt % len(OVERPASS_URLS)]
        logging.info(f"Overpass über {url}")
        try:
            response = session.post(url, data={"data": OVERPASS_QUERY}, timeout=360)
            response.raise_for_status()
            result = response.json()
            # Overpass antwortet bei Timeout oder Überlast mit 200 und leerer Elementliste
            if result.get("remark") or not result.get("elements"):
                raise requests.RequestException(f"Keine Daten: {result.get('remark', 'leere Antwort')}")
            break
        except (requests.RequestException, ValueError) as error:
            logging.warning(f"{error}, nächster Versuch in 15 s")
            response = None
            time.sleep(15)
    if response is None:
        raise SystemExit("Overpass nicht erreichbar, später erneut versuchen.")

    elements = [e for e in result["elements"] if "lat" in e]
    data = {"osm_id": [e["id"] for e in elements]}
    for tag in OSM_TAGS:
        data[tag] = [e.get("tags", {}).get(tag) for e in elements]
    stops = gpd.GeoDataFrame(
        data, geometry=[Point(e["lon"], e["lat"]) for e in elements], crs="EPSG:4326"
    ).to_crs(CRS)

    # Der Area-Filter kann am Rand ungenau sein: auf die Bezirksgrenzen zuschneiden
    berlin = gpd.read_file(DISTRICTS_PATH).to_crs(CRS).union_all()
    inside = stops.within(berlin)
    logging.info(f"{(~inside).sum()} Haltestellen außerhalb der Bezirksgrenzen verworfen")
    return stops[inside].reset_index(drop=True)


def load_stops(neu):
    if CACHE_PATH.exists() and not neu:
        logging.info(f"Cache verwendet: {CACHE_PATH} (--neu lädt erneut)")
        return gpd.read_file(CACHE_PATH).to_crs(CRS)
    stops = download_osm()
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_PATH.with_suffix(".tmp.gpkg")
    stops.to_file(tmp, layer=CACHE_PATH.stem, driver="GPKG")
    tmp.replace(CACHE_PATH)
    logging.info(f"Geschrieben: {CACHE_PATH} ({len(stops)} Haltestellen)")
    return stops


def load_network(netz):
    pfad = PFADE[netz]
    path = PROCESSING_DIR / pfad["quelle"]
    if not path.exists():
        raise SystemExit(
            f"Zielnetz nicht gefunden: {path}"
            + ("\nHinweis: zuerst python ren-network/unify_networks.py ausführen." if netz == "ren" else "")
        )
    kwargs = {"layer": pfad["quelle_layer"]} if pfad["quelle_layer"] else {}
    return gpd.read_file(path, **kwargs).to_crs(CRS)


def main():
    parser = argparse.ArgumentParser(description="OSM-Bushaltestellen holen und auf das Zielnetz zuschneiden")
    add_netz_argument(parser)
    parser.add_argument("--neu", action="store_true", help="OSM-Daten erneut laden")
    parser.add_argument("--puffer", type=float, default=DEFAULT_BUFFER_METERS,
                        help=f"Abstand zum Netz in Metern (Standard {DEFAULT_BUFFER_METERS})")
    args = parser.parse_args()

    stops = load_stops(args.neu)
    if stops.empty:
        raise SystemExit(f"Keine Haltestellen geladen. Cache {CACHE_PATH} löschen und erneut versuchen.")
    network = load_network(args.netz)
    logging.info(f"{len(stops)} Haltestellen in Berlin, Netz {args.netz}: {len(network)} Kanten")

    buffered = network.geometry.buffer(args.puffer).union_all()
    on_network = stops[stops.within(buffered)].reset_index(drop=True)

    output = PROCESSING_DIR / BUSHALTESTELLEN[args.netz]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    on_network.to_file(output, driver="FlatGeobuf")
    logging.info(
        f"{len(on_network)} von {len(stops)} Haltestellen ({len(on_network) / max(len(stops), 1):.1%}) "
        f"liegen höchstens {args.puffer:g} m vom Netz {args.netz} → {output}"
    )


if __name__ == "__main__":
    main()
