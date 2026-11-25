#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bauwerke.py
--------------------------------------------------------------------
Candidates for the check queue „Brücken und Tunnel“ of the Netzanpassungen app. At a bridge or tunnel the
coarse edge model sometimes joins an edge that runs UNDER the bridge (or over the tunnel) with the edges ON
the structure at one node, so routing could jump levels. This module finds those nodes; a person decides in
the app (OK, or split the levels, see apply_app_result.py, entry kind bridge_check).

Detection (EPSG:25833, structures of the Senate dataset „Straßennetz Bauwerke“, layer b_bauwerke):
- zone = structure line buffered by ZONE_BUFFER_M
- an edge lies ON the structure („auf“) when its overlap with the zone is at least ALONG_MIN_OVERLAP_M and
  at least ALONG_MIN_SHARE_OF_STRUCTURE of the structure length or ALONG_MIN_SHARE_OF_EDGE of the edge length
- an edge CROSSES it („quer“) when it hits the structure line farther than CROSS_MIN_END_DISTANCE_M from both ends
  and is not „auf“
- case „verbunden“: a node joins an „auf“ and a „quer“ edge of the same structure
- case „mitten“: the node is at most MIDDLE_MAX_LINE_DISTANCE_M from the structure line, more than
  MIDDLE_MIN_END_DISTANCE_M from both its ends, and an edge at the node overlaps the zone by at most
  MIDDLE_MAX_OVERLAP_M
Edges are the Detailnetz and the REN+; only nodes with at least one REN+ edge are kept (the app edits the REN+).
One candidate per node: where a node hits several structures, the one where it is „verbunden“, else the longest.

Result per node: `knoten`, `bauwerk` (name), `art` (BR, FBR, EBBR, TU, FTU), `nr`, `ebenen_verschieden`
(the edges on the structure and the edges crossing it at the node have different Detailnetz verkehrsebene, both
known), `vorschlag_unten` (edge keys of the app joined with `|`: for bridges the edges at the node that cross
the structure, for tunnels the edges at the node that lie on it).
"""

import logging
from collections import defaultdict
from pathlib import Path

import geopandas as gpd
import pandas as pd
import shapely
from shapely.geometry import Point
from shapely.ops import linemerge

STRUCTURES_PATH = Path(__file__).resolve().parent.parent / "data" / "Berlin Straßennetz Bauwerke.geojson"
CRS = "EPSG:25833"
BRIDGE_KINDS = ("BR", "FBR", "EBBR")
TUNNEL_KINDS = ("TU", "FTU")
KINDS = BRIDGE_KINDS + TUNNEL_KINDS

ZONE_BUFFER_M = 8.0
ALONG_MIN_OVERLAP_M = 5.0
ALONG_MIN_SHARE_OF_STRUCTURE = 0.5
ALONG_MIN_SHARE_OF_EDGE = 0.7
CROSS_MIN_END_DISTANCE_M = 5.0
MIDDLE_MAX_LINE_DISTANCE_M = 6.0
MIDDLE_MIN_END_DISTANCE_M = 12.0
MIDDLE_MAX_OVERLAP_M = 10.0

OUTPUT_COLUMNS = ["knoten", "bauwerk", "art", "nr", "ebenen_verschieden", "vorschlag_unten"]


def load_structures(path=STRUCTURES_PATH):
    """The structures (kinds in KINDS only) in EPSG:25833, or None with a warning when the file is missing."""
    path = Path(path)
    if not path.exists():
        logging.warning(f"Bauwerke fehlen: {path} – die Ebene bauwerk_knoten entfällt "
                        "(Quelle: data/download_bauwerke.py)")
        return None
    structures = gpd.read_file(path)
    if structures.crs is None:
        structures = structures.set_crs("EPSG:4326")
    if structures.crs.to_epsg() != 25833:
        structures = structures.to_crs(CRS)
    structures = structures[structures["bauwerksart"].isin(KINDS)].reset_index(drop=True)
    logging.info(f"Bauwerke: {len(structures)} ({structures['bauwerksart'].value_counts().to_dict()})")
    return structures


def _text(value):
    return None if value is None or pd.isna(value) or str(value).strip() in ("", "-") else str(value).strip()


def _line_ends(geometry):
    merged = linemerge(geometry) if geometry.geom_type == "MultiLineString" else geometry
    if merged.geom_type == "LineString":
        return Point(merged.coords[0]), Point(merged.coords[-1])
    return Point(merged.geoms[0].coords[0]), Point(merged.geoms[-1].coords[-1])


def find_candidates(structures, detail, ren_netz, nodes):
    """Candidate nodes for the check queue.

    `detail`: columns ref, element_nr, beginnt_bei_vp, endet_bei_vp, verkehrsebene, geometry.
    `ren_netz`: columns ref, element_nr, von_knoten, bis_knoten, geometry. `nodes`: id, geometry.
    All in EPSG:25833; `ref` is the key of the line in the app (`line_refs`). Returns a GeoDataFrame with
    OUTPUT_COLUMNS and the node position as geometry (EPSG:25833)."""
    edges = {}
    for row in detail.itertuples():
        edges[f"detailnetz:{row.ref}"] = {"net": "detail", "a": row.beginnt_bei_vp, "b": row.endet_bei_vp,
                                          "level": row.verkehrsebene, "geometry": row.geometry,
                                          "element_nr": row.element_nr}
    level_of = {}
    for row in detail.itertuples():
        if row.element_nr not in level_of and not pd.isna(row.verkehrsebene):
            level_of[row.element_nr] = row.verkehrsebene
    for row in ren_netz.itertuples():
        edges[f"ren:{row.ref}"] = {"net": "ren", "a": row.von_knoten, "b": row.bis_knoten,
                                   "level": level_of.get(row.element_nr), "geometry": row.geometry,
                                   "element_nr": row.element_nr}
    keys = list(edges)
    edge_tree = shapely.STRtree([edges[key]["geometry"] for key in keys])
    at_node = defaultdict(set)
    for key, edge in edges.items():
        for node in (edge["a"], edge["b"]):
            if isinstance(node, str) and node:
                at_node[node].add(key)
    node_ids = [str(node) for node in nodes["id"]]
    node_points = dict(zip(node_ids, nodes.geometry))
    node_tree = shapely.STRtree(list(node_points.values()))
    node_list = list(node_points)

    candidates = defaultdict(list)  # node -> [candidate]
    for structure in structures.itertuples():
        line = structure.geometry
        start, end = _line_ends(line)
        length = line.length
        zone = line.buffer(ZONE_BUFFER_M)
        relation = {}
        for position in edge_tree.query(zone, predicate="intersects"):
            key = keys[position]
            geometry = edges[key]["geometry"]
            overlap = geometry.intersection(zone).length
            along = overlap >= ALONG_MIN_OVERLAP_M and (overlap >= ALONG_MIN_SHARE_OF_STRUCTURE * length
                                                         or overlap >= ALONG_MIN_SHARE_OF_EDGE * geometry.length)
            cross = False
            if not along and geometry.intersects(line):
                hit = geometry.intersection(line)
                cross = hit.distance(start) > CROSS_MIN_END_DISTANCE_M and hit.distance(end) > CROSS_MIN_END_DISTANCE_M
            relation[key] = {"overlap": overlap, "along": along, "cross": cross}
        cases = defaultdict(set)
        for key, info in relation.items():
            if not info["along"]:
                continue
            for node in (edges[key]["a"], edges[key]["b"]):
                if isinstance(node, str) and node and any(relation.get(other, {}).get("cross") for other in at_node[node]):
                    cases[node].add("verbunden")
        for position in node_tree.query(line.buffer(MIDDLE_MAX_LINE_DISTANCE_M), predicate="intersects"):
            node = node_list[position]
            point = node_points[node]
            if (point.distance(start) > MIDDLE_MIN_END_DISTANCE_M and point.distance(end) > MIDDLE_MIN_END_DISTANCE_M
                    and any(relation.get(key, {}).get("overlap", 0) <= MIDDLE_MAX_OVERLAP_M for key in at_node[node])):
                cases[node].add("mitten")
        for node, found in cases.items():
            if node not in node_points:
                continue
            candidates[node].append({"verbunden": "verbunden" in found, "length": length, "structure": structure,
                                     "relation": relation})

    rows = []
    for node, options in candidates.items():
        if not any(edges[key]["net"] == "ren" for key in at_node[node]):
            continue
        best = max(options, key=lambda item: (item["verbunden"], item["length"]))
        structure, relation = best["structure"], best["relation"]
        kind = structure.bauwerksart
        on = sorted(key for key in at_node[node] if relation.get(key, {}).get("along"))
        crossing = sorted(key for key in at_node[node] if relation.get(key, {}).get("cross"))
        on_levels = {edges[key]["level"] for key in on if edges[key]["level"] is not None}
        cross_levels = {edges[key]["level"] for key in crossing if edges[key]["level"] is not None}
        different = bool(on_levels and cross_levels and len(on_levels | cross_levels) > 1)
        rows.append({
            "knoten": node, "bauwerk": _text(structure.bauwerksname) or "", "art": kind,
            "nr": _text(structure.bauwerksnummer), "ebenen_verschieden": different,
            "vorschlag_unten": "|".join(crossing if kind in BRIDGE_KINDS else on),
            "geometry": node_points[node],
        })
    frame = gpd.GeoDataFrame(rows, columns=OUTPUT_COLUMNS + ["geometry"], geometry="geometry", crs=CRS)
    frame = frame.sort_values(["bauwerk", "knoten"]).reset_index(drop=True)
    logging.info(f"Kandidaten Brücken und Tunnel: {len(frame)} Knoten ({frame['art'].value_counts().to_dict()}), "
                 f"verschiedene Ebenen: {int(frame['ebenen_verschieden'].sum())}")
    return frame
