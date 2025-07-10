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


def segmentiere_netz_in_meterabschnitte(net_gdf, crs, segmentlaenge=1.0):
    """
    Teilt alle Linien im Netz in ca. 1-Meter-Abschnitte auf.
    Gibt ein neues GeoDataFrame mit Segmenten und okstra_id zurück.
    """
    segmente = []
    for _, row in net_gdf.iterrows():
        geom = ls_from_geom(row.geometry)
        n_seg = max(1, int(np.ceil(geom.length / segmentlaenge)))
        breakpoints = np.linspace(0, geom.length, n_seg + 1)
        for i in range(n_seg):
            seg = LineString([
                geom.interpolate(breakpoints[i]),
                geom.interpolate(breakpoints[i+1])
            ])
            seg_row = row.copy()
            seg_row["geometry"] = seg
            segmente.append(seg_row)
    return gpd.GeoDataFrame(segmente, crs=crs)


def verschmelze_segmente(gdf, id_feld, osm_felder):
    """
    Verschmilzt benachbarte Segmente mit gleicher okstra_id und identischen OSM-Attributen.
    """
    from shapely.ops import linemerge
    gruppen = []
    for _, gruppe in gdf.groupby([id_feld] + osm_felder):
        # Sortiere nach Reihenfolge im Netz (optional: nach Startpunkt)
        geoms = list(gruppe.geometry)
        merged = linemerge(geoms)
        merged_row = gruppe.iloc[0].copy()
        merged_row["geometry"] = merged
        gruppen.append(merged_row)
    return gpd.GeoDataFrame(gruppen, crs=gdf.crs)


# ------------------------------------------------------------- Hauptablauf --
def process(net_path, osm_path, out_path, crs, buf):
    """
    Hauptfunktion: Segmentiert das Netz, führt das Snapping durch und verschmilzt die Segmente wieder.
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

    net = read(net_path).to_crs(crs)
    osm = read(osm_path).to_crs(crs)

    # Prüfen, ob alle Pflichtfelder im Netz vorhanden sind
    for fld in (FLD_EDGE, FLD_FROM, FLD_TO, FLD_DIR, "okstra_id"):
        if fld not in net.columns:
            sys.exit(f"Pflichtfeld “{fld}” fehlt im Netz!")

    # ---------- Netz segmentieren und speichern -----------------------------
    print("Segmentiere Netz in 1-Meter-Abschnitte ...")
    net_segmented = segmentiere_netz_in_meterabschnitte(net, crs, segmentlaenge=1.0)
    seg_path = "./output/qa-snapping/rvn-segmented.fgb"
    net_segmented.to_file(seg_path, driver="FlatGeobuf")
    print(f"✔  Segmentiertes Netz gespeichert als {seg_path}")

    # ---------- Snapping/Attributübernahme auf Segmente ---------------------
    print("Führe Snapping und OSM-Attributübernahme auf Segmente durch ...")
    # OSM-Spalten (außer Geometrie) umbenennen (Präfix 'osm_')
    osm_attrs = [c for c in osm.columns if c != "geometry"]
    osm = osm.rename(columns={c: f"osm_{c}" for c in osm_attrs})
    osm_sidx = osm.sindex  # Räumlicher Index für OSM-Ways

    # Für jedes Segment: nächstgelegene OSM-Geometrie im Buffer suchen und Attribute übernehmen
    snapped_records = []
    for idx, seg in net_segmented.iterrows():
        g = seg.geometry
        # Kandidaten im Buffer suchen
        cand_idx = list(osm_sidx.intersection(g.buffer(buf).bounds))
        if not cand_idx:
            snapped_records.append(seg)
            continue
        cand = osm.iloc[cand_idx].copy()
        # Nur Kandidaten im Buffer behalten
        cand["d"] = cand.geometry.distance(g)
        cand = cand[cand["d"] <= buf]
        if cand.empty:
            snapped_records.append(seg)
            continue
        # Nächstgelegene OSM-Geometrie bestimmen
        mid = g.interpolate(0.5, normalized=True)
        dist = cand.geometry.distance(mid)
        nearest = cand.loc[dist.idxmin()]
        # OSM-Attribute übernehmen
        for c in ["osm_road", "osm_surface", "osm_surface:colour", "osm_oneway"]:
            seg[c] = nearest.get(c, None)
        snapped_records.append(seg)
    net_segmented = gpd.GeoDataFrame(snapped_records, crs=crs)

    # ---------- Segmente verschmelzen ---------------------------------------
    print("Fasse Segmente mit gleicher okstra_id und OSM-Attributen zusammen ...")
    osm_felder = ["osm_road", "osm_surface", "osm_surface:colour", "osm_oneway"]
    out_gdf = verschmelze_segmente(net_segmented, "okstra_id", osm_felder)

    # ---------- Ergebnis speichern ------------------------------------------
    p, *layer = out_path.split(":")
    layer = layer[0] if layer else "edges_enriched"
    Path(p).unlink(missing_ok=True)
    out_gdf.to_file(p, layer=layer, driver="GPKG")
    print(f"✔  {len(out_gdf)} Kanten → {p}:{layer}")


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
