#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
download_bauwerke.py
--------------------------------------------------------------------
Lädt die Bauwerke (Brücken, Tunnel) des Detailnetzes Berlin aus dem WFS des Geoportals Berlin
(Layer b_bauwerke, derselbe wie in tilda-static-data/geojson/region-berlin/strassennetz-berlin-bauwerke)
nach data/Berlin Straßennetz Bauwerke.geojson (WGS84). Die Datei ist eingecheckt; dieses Skript
braucht man nur, um sie zu aktualisieren. netzanpassungen/write_app_input.py liest sie für die Prüfung
„Brücken und Tunnel“ der App.

Aufruf (im Projekt-Root):
    .venv/bin/python data/download_bauwerke.py
"""

import json
import logging
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "data" / "Berlin Straßennetz Bauwerke.geojson"
ENDPOINT = "https://gdi.berlin.de/services/wfs/detailnetz"
LAYER = "b_bauwerke"
TIMEOUT_S = 120


def main():
    logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    query = urllib.parse.urlencode({
        "SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature", "TYPENAMES": LAYER,
        "OUTPUTFORMAT": "application/json", "SRSNAME": "EPSG:4326"})
    with urllib.request.urlopen(f"{ENDPOINT}?{query}", timeout=TIMEOUT_S) as response:
        collection = json.loads(response.read().decode("utf-8"))
    features = collection.get("features") or []
    if not features:
        raise SystemExit(f"Der WFS {ENDPOINT} lieferte keine Bauwerke ({LAYER})")
    collection["name"] = LAYER
    TARGET.write_text(json.dumps(collection, ensure_ascii=False), encoding="utf-8")
    logging.info(f"{len(features)} Bauwerke nach {TARGET}")


if __name__ == "__main__":
    main()
