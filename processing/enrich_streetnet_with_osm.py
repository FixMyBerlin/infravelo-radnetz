#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
enrich_streetnet_with_osm.py
--------------------------------------------------------------------
Überträgt OSM-Attribute auf ein topologisches Richtungs-Straßennetz
– MultiLineStrings werden korrekt behandelt
– feste Feldnamen:
      element_nr         = Edge-ID
      beginnt_bei_vp     = From-Node
      endet_bei_vp       = To-Node
      verkehrsrichtung   = R / G / B
--------------------------------------------------------------------
Aufrufbeispiel:

    python enrich_streetnet_with_osm.py \
           --net  vorrangnetz_details_combined_rvn.fgb \
           --osm  matched_osm_ways.fgb \
           --out  netz_enriched.gpkg
"""
import argparse, sys, uuid
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import LineString, MultiLineString, Point, MultiPoint
from shapely.ops import split as shp_split, linemerge


# -------------------------------------------------------------- Konstanten --
CRS_DEFAULT   = 25832     # EPSG-Code für Standard-Koordinatensystem
BUFFER_DEFAULT = 20.0     # Standard-Puffergröße in Metern für Matching

# Feldnamen für das Netz
FLD_EDGE = "element_nr"           # Kanten-ID
FLD_FROM = "beginnt_bei_vp"       # Startknoten-ID
FLD_TO   = "endet_bei_vp"         # Endknoten-ID
FLD_DIR  = "verkehrsrichtung"     # Werte: R / G / B (Richtung)


# --------------------------------------------------------- Hilfsfunktionen --
def ls_from_geom(g):
    """Stellt sicher, dass die Geometrie ein LineString ist. Falls MultiLineString, wird gemergt oder erster Teil genommen."""
    if isinstance(g, LineString):
        return g
    if isinstance(g, MultiLineString):
        merged = linemerge(g)
        if isinstance(merged, LineString):
            return merged
        return LineString(list(g.geoms[0].coords))
    raise TypeError(f"Geometry {g.geom_type} nicht unterstützt")


def reverse_geom(g):
    """Dreht die Richtung einer Linie oder Multi-Linie um."""
    if isinstance(g, LineString):
        return LineString(list(g.coords)[::-1])
    if isinstance(g, MultiLineString):
        parts = [LineString(list(ls.coords)[::-1]) for ls in g.geoms]
        return MultiLineString(parts[::-1])
    raise TypeError


def iter_coords(g):
    """Iteriert über alle Stützpunkte einer Geometrie, egal ob LineString oder MultiLineString."""
    if isinstance(g, LineString):
        yield from g.coords
    elif isinstance(g, MultiLineString):
        for ls in g.geoms:
            yield from ls.coords
    else:
        raise TypeError


def is_left(line: LineString, p: Point) -> bool:
    """Prüft, ob ein Punkt links der Linie liegt (für Richtungsprüfung)."""
    a_x, a_y = line.coords[0]
    b_x, b_y = line.coords[-1]
    return ((b_x - a_x) * (p.y - a_y) - (b_y - a_y) * (p.x - a_x)) > 0


def split_line(line, distances):
    """Teilt eine Linie an gegebenen Abständen in Teilstücke."""
    distances = [d for d in distances if 0.0 < d < line.length]
    if not distances:
        return [line]

    pts = [line.interpolate(d) for d in distances]
    result = shp_split(line, MultiPoint(pts))

    # Shapely 2.x: GeometryCollection → Teile über .geoms auslesen
    return list(result.geoms)          # statt  list(result)



def new_neg_id(counter):
    """Erzeugt eine neue negative ID für Zwischennoten (Splits)."""
    counter["val"] -= 1
    return counter["val"]


# ------------------------------------------------------------- Hauptablauf --
def process(net_path, osm_path, out_path, crs, buf):
    """
    Hauptfunktion: Überträgt OSM-Attribute auf das Netz und splittet Kanten an Schnittpunkten.
    net_path: Pfad zum Netz (mit Layer)
    osm_path: Pfad zu OSM-Ways (mit Layer)
    out_path: Ausgabepfad (mit Layer)
    crs: Ziel-Koordinatensystem (EPSG)
    buf: Puffergröße für Matching
    """
    # ---------- Daten laden -------------------------------------------------
    def read(path):
        f, *layer = path.split(":")
        return gpd.read_file(f, layer=layer[0] if layer else None)

    net = read(net_path).to_crs(crs)  # Netz einlesen und ins Ziel-CRS bringen
    osm = read(osm_path).to_crs(crs)  # OSM-Ways einlesen und ins Ziel-CRS bringen

    # Prüfen, ob alle Pflichtfelder im Netz vorhanden sind
    for fld in (FLD_EDGE, FLD_FROM, FLD_TO, FLD_DIR):
        if fld not in net.columns:
            sys.exit(f"Pflichtfeld “{fld}” fehlt im Netz!")

    # ---------- Richtungs-Kopien -------------------------------------------
    # Für jede Kante werden ggf. zwei Kopien (vorwärts/rückwärts) erzeugt
    copies = []
    for _, r in net.iterrows():
        vr = str(r[FLD_DIR]).upper()
        geom = ls_from_geom(r.geometry)

        if vr in {"R", "B"}:          # forward
            copies.append({**r, "dir_copy": "F", "geometry": geom})

        if vr in {"G", "B"}:          # backward
            copies.append({**r, "dir_copy": "B", "geometry": reverse_geom(geom)})

    net_dir = gpd.GeoDataFrame(copies, crs=crs)

    # ---------- OSM-Spalten vorbereiten ------------------------------------
    # Alle OSM-Spalten (außer Geometrie) werden umbenannt (Präfix 'osm_')
    osm_attrs = [c for c in osm.columns if c != "geometry"]
    osm = osm.rename(columns={c: f"osm_{c}" for c in osm_attrs})
    osm_sidx = osm.sindex  # Räumlicher Index für OSM-Ways

    # ---------- Verarbeitung ------------------------------------------------
    segrecs, node_ctr, split_nodes = [], {"val": 0}, {}

    # Iteration über alle Kanten (mit Richtung)
    for _, e in net_dir.iterrows():
        g = e.geometry
        g_len = g.length

        # Kandidaten aus OSM suchen, die im Puffer liegen
        cand_idx = list(osm_sidx.intersection(g.buffer(buf).bounds))
        if not cand_idx:
            segrecs.append(e.to_dict())
            continue

        cand = osm.iloc[cand_idx].copy()

        # Seitenprüfung: nur OSM-Ways auf der richtigen Seite behalten
        mids = cand.geometry.apply(lambda gg: gg.interpolate(0.5, normalized=True))
        ok_side = [
            not is_left(g, p) if e.dir_copy == "F" else is_left(g, p) for p in mids
        ]
        cand = cand[ok_side]

        # Nur Kandidaten im Puffer behalten
        cand["d"] = cand.geometry.distance(g)   # Distanzspalte anlegen
        cand = cand[cand["d"] <= buf]           # Kandidaten auf Puffer beschränken

        if cand.empty:
            # Falls keine passenden OSM-Ways gefunden, Originalkante übernehmen
            segrecs.append(e.to_dict())
            continue

        # Breakpoints bestimmen (Schnittpunkte mit OSM-Ways)
        bps = {0.0, g_len}
        for gg in cand.geometry:
            bps.update(
                d for d in (g.project(Point(xy)) for xy in iter_coords(gg))
                if 0.0 < d < g_len
            )

        # Kante an Breakpoints splitten und Attribute übernehmen
        for part in split_line(g, sorted(bps)):
            mid = part.interpolate(0.5, normalized=True)
            # Statt cand.sindex.nearest: Nächstgelegene OSM-Geometrie bestimmen
            dist = cand.geometry.distance(mid)       # Punkt-zu-Linie-Distanz
            nearest = cand.loc[dist.idxmin()]        # eine Zeile mit kleinstem Abstand

            def node_id(off, orig):
                # Bestimmt die Node-ID für Start/Ende des Segments
                if np.isclose(off, 0.0):
                    return e[FLD_FROM]
                if np.isclose(off, g_len):
                    return e[FLD_TO]
                key = (e[FLD_EDGE], round(off, 3))
                return split_nodes.setdefault(key, new_neg_id(node_ctr))

            off0 = g.project(Point(part.coords[0]))
            off1 = g.project(Point(part.coords[-1]))

            # Attribute zusammenführen: Netz, OSM, Geometrie, Split-IDs
            rec = (
                {**e.drop(labels="geometry"), **nearest.drop(labels="geometry")}
                | {
                    "geometry": part,
                    "orig_edge_id": e[FLD_EDGE],
                    FLD_FROM: node_id(off0, e[FLD_FROM]),
                    FLD_TO: node_id(off1, e[FLD_TO]),
                    "edge_split_id": uuid.uuid4().hex[:12],
                }
            )
            segrecs.append(rec)

    # Ergebnis als GeoDataFrame speichern
    out = gpd.GeoDataFrame(segrecs, crs=crs)
    p, *layer = out_path.split(":")
    layer = layer[0] if layer else "edges_enriched"
    Path(p).unlink(missing_ok=True)  # Vorherige Datei ggf. löschen
    out.to_file(p, layer=layer, driver="GPKG")
    print(f"✔  {len(out)} Kanten → {p}:{layer}")


# ------------------------------------------------------------- CLI Wrapper --
if __name__ == "__main__":
    # Kommandozeilenargumente parsen
    ap = argparse.ArgumentParser()
    ap.add_argument("--net",  required=True, help="Netz-Layer  (Pfad[:Layer])")
    ap.add_argument("--osm",  required=True, help="OSM-Ways   (Pfad[:Layer])")
    ap.add_argument("--out",  required=True, help="Ausgabe    (Pfad[:Layer])")
    ap.add_argument("--crs",  type=int,   default=CRS_DEFAULT,
                    help=f"Ziel-EPSG (default {CRS_DEFAULT})")
    ap.add_argument("--buffer", type=float, default=BUFFER_DEFAULT,
                    help=f"Matching-Puffer in m (default {BUFFER_DEFAULT})")
    args = ap.parse_args()

    # Hauptfunktion aufrufen
    process(args.net, args.osm, args.out, args.crs, args.buffer)
