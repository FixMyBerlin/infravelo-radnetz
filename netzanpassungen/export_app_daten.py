#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
export_app_daten.py
--------------------------------------------------------------------
Schreibt die Eingabedatei der App „Netzanpassungen“ (Repo knotenpunkte,
Ordner netzanpassungen/). In der App werden entlang der Radfernwege neue
Kanten gezeichnet, wo das Detailnetz und das REN+ keine haben.

Die Datei enthält sechs FeatureCollections in WGS84:
- detailnetz: Kanten mit element_nr, beginnt_bei_vp, endet_bei_vp
- knoten: Detailnetzknoten aus den Kantenenden (erster Punkt =
  beginnt_bei_vp, letzter = endet_bei_vp) und die virtuellen Knoten
- ren_netz: Kartierungs-Netz mit element_nr, von_knoten, bis_knoten
- radfernwege: touristisches Radnetz
- luecken: Abschnitte der Radfernwege ohne Kante in GAP_DISTANCE_M
- knoten_vorschlaege: Punkte, an denen ein Radfernweg eine Detailnetzkante
  kreuzt, ohne dass dort ein Knoten liegt (Vorschlag für einen virtuellen Knoten)

INPUT:
- data/Berlin Straßenabschnitte Detailnetz.fgb (jüngster Stand)
- data/Virtuelle-Knotenpunkte.gpkg
- ren-network/output/ren_netz_kartierung.gpkg (unify_networks.py)
- data/netzquellen/touristisches_radnetz.gpkg
- data/Berlin Bezirke.gpkg (nur mit --bezirk)

OUTPUT:
- netzanpassungen/output/netzanpassungen_<gebiet>.json
- netzanpassungen/output/pruefliste_<gebiet>.csv

Aufruf:
    python netzanpassungen/export_app_daten.py
    python netzanpassungen/export_app_daten.py --bezirk Neukölln
"""

import argparse
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely.geometry import MultiLineString, Point

ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT / "ren-network"))

import unify_networks as ren  # noqa: E402

CRS = f"EPSG:{ren.DEFAULT_CRS}"
SCHEMA = "netzanpassungen-app/v1"

VIRTUAL_NODES_PATH = ROOT / "data" / "Virtuelle-Knotenpunkte.gpkg"
RADFERNWEGE_PATH = ROOT / "data" / "netzquellen" / "touristisches_radnetz.gpkg"
OUTPUT_DIR = Path(__file__).resolve().parent / "output"

# Ein Radfernweg-Abschnitt gilt als Lücke, wenn keine Kante so nah ist
GAP_DISTANCE_M = 10.0
# Kürzere Lücken sind meist nur Abweichungen an Kreuzungen
MIN_GAP_LENGTH_M = 20.0
# Mit --bezirk bleiben Kanten bis zu diesem Abstand zur Bezirksgrenze enthalten
AREA_BUFFER_M = 200.0
# Liegen die Kantenenden desselben Knotens weiter auseinander, kommt er auf die Prüfliste
NODE_POSITION_TOLERANCE_M = 0.5
# Kreuzungen näher als das an einem vorhandenen Knoten brauchen keinen neuen
NODE_SUGGESTION_MIN_NODE_DISTANCE_M = 15.0
# Kreuzungen auf derselben Kante, die näher beieinander liegen, werden zu einem Vorschlag
NODE_SUGGESTION_MERGE_DISTANCE_M = 10.0
# Liegt der Anfang oder das Ende einer Lücke so nah am Vorschlag, beginnt dort wohl eine neue Kante
NODE_SUGGESTION_GAP_DISTANCE_M = 25.0
# Schnittwinkel zwischen Radfernweg und Kante; flacher gilt als „läuft parallel“
NODE_SUGGESTION_STEEP_ANGLE_DEG = 30.0
# Strecke, über die die Richtung der Linien am Schnittpunkt gemessen wird
DIRECTION_SAMPLE_M = 5.0
# 7 Nachkommastellen in WGS84 sind etwa 1 cm
COORDINATE_GRID = 1e-7

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s", force=True)


def slugify(value):
    slug = value.strip().lower()
    for umlaut, replacement in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        slug = slug.replace(umlaut, replacement)
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    return slug or "gebiet"


def single_lines(frame):
    """Ein LineString je Zeile; echte MultiLineStrings werden in Teile zerlegt."""
    frame = frame.explode(index_parts=False).reset_index(drop=True)
    return frame[frame.geometry.geom_type == "LineString"].reset_index(drop=True)


def detailnetz_path():
    dated = sorted(ren.DETAILNETZ_PATH.parent.glob(ren.DETAILNETZ_DATED_GLOB))
    return dated[-1] if dated else ren.DETAILNETZ_PATH


def load_detailnetz():
    path = detailnetz_path()
    logging.info(f"Detailnetz: {path.name}")
    detail = gpd.read_file(path, columns=[
        "element_nr", "beginnt_bei_vp", "endet_bei_vp", "strassenname", "verkehrsebene", "okstra_id"])
    if detail.crs is None or detail.crs.to_epsg() != ren.DEFAULT_CRS:
        detail = detail.to_crs(CRS)
    return single_lines(detail), path


def nodes_from_edges(detail):
    """Detailnetzknoten aus den Kantenenden. Weichen die Enden eines Knotens ab, gilt das erste."""
    starts = gpd.GeoDataFrame({
        "id": detail["beginnt_bei_vp"],
        "element_nr": detail["element_nr"],
    }, geometry=[Point(line.coords[0]) for line in detail.geometry], crs=detail.crs)
    ends = gpd.GeoDataFrame({
        "id": detail["endet_bei_vp"],
        "element_nr": detail["element_nr"],
    }, geometry=[Point(line.coords[-1]) for line in detail.geometry], crs=detail.crs)
    ends_all = pd.concat([starts, ends], ignore_index=True)
    ends_all = ends_all[ends_all["id"].notna() & (ends_all["id"].astype(str) != "")]
    ends_all["id"] = ends_all["id"].astype(str)

    nodes = ends_all.drop_duplicates("id").set_index("id")
    position = nodes.geometry.reindex(ends_all["id"]).to_numpy()
    distance = shapely.distance(ends_all.geometry.to_numpy(), position)
    off = ends_all[distance > NODE_POSITION_TOLERANCE_M].copy()
    off["abstand_m"] = distance[distance > NODE_POSITION_TOLERANCE_M].round(2)

    nodes = gpd.GeoDataFrame({"id": nodes.index, "ist_virtuell": 0}, geometry=nodes.geometry.to_numpy(), crs=detail.crs)
    logging.info(f"Knoten aus Kantenenden: {len(nodes)}, Kantenenden abseits ihres Knotens: {len(off)}")
    return nodes, off


def load_virtual_nodes():
    virtual = gpd.read_file(VIRTUAL_NODES_PATH)
    if virtual.crs is None or virtual.crs.to_epsg() != ren.DEFAULT_CRS:
        virtual = virtual.to_crs(CRS)
    virtual = virtual[virtual["Knotenpunkt-ID"].notna()]
    logging.info(f"Virtuelle Knoten: {len(virtual)}")
    return gpd.GeoDataFrame({
        "id": virtual["Knotenpunkt-ID"].astype(str).str.strip(),
        "ist_virtuell": 1,
    }, geometry=virtual.geometry.to_numpy(), crs=virtual.crs)


def node_id_text(value):
    """von_knoten / bis_knoten sind Integer64 im REN+; in der App sind Knoten-IDs Text."""
    if pd.isna(value):
        return None
    return str(int(value)) if isinstance(value, float) else str(value)


def load_ren_netz():
    network = gpd.read_file(ren.MAPPING_NETWORK_PATH, layer=ren.OUTPUT_LAYER, columns=[
        "element_nr", "von_knoten", "bis_knoten", "radverkehrsnetz", "strassenname"])
    if network.crs is None or network.crs.to_epsg() != ren.DEFAULT_CRS:
        network = network.to_crs(CRS)
    network["von_knoten"] = network["von_knoten"].map(node_id_text)
    network["bis_knoten"] = network["bis_knoten"].map(node_id_text)
    network = single_lines(network)
    logging.info(f"REN+-Kartierungs-Netz: {len(network)} Linien")
    return network


def load_radfernwege():
    routes = gpd.read_file(RADFERNWEGE_PATH, columns=["name"])
    if routes.crs is None or routes.crs.to_epsg() != ren.DEFAULT_CRS:
        routes = routes.to_crs(CRS)
    routes["geometry"] = shapely.force_2d(routes.geometry.to_numpy())
    routes = single_lines(routes)
    logging.info(f"Radfernwege: {routes['name'].nunique()} Routen, {len(routes)} Linien")
    return routes


def find_gaps(routes, edges):
    """Abschnitte der Radfernwege, die weiter als GAP_DISTANCE_M von jeder Kante liegen."""
    near = edges.iloc[edges.sindex.query(routes.geometry.buffer(GAP_DISTANCE_M * 2).union_all(),
                                         predicate="intersects")]
    covered = shapely.union_all(near.geometry.buffer(GAP_DISTANCE_M, quad_segs=2).to_numpy())
    gaps = routes.copy()
    gaps["geometry"] = gaps.geometry.difference(covered)
    gaps = single_lines(gaps[~gaps.geometry.is_empty])
    gaps = gaps[gaps.geometry.length >= MIN_GAP_LENGTH_M].reset_index(drop=True)
    gaps["laenge_m"] = gaps.geometry.length.round(1)
    logging.info(f"Lücken: {len(gaps)}, {gaps['laenge_m'].sum() / 1000:.1f} km")
    return gaps


def line_direction(line, position):
    """Richtung (Einheitsvektor) der Linie am Abstand `position` vom Anfang."""
    before = line.interpolate(max(position - DIRECTION_SAMPLE_M, 0))
    after = line.interpolate(min(position + DIRECTION_SAMPLE_M, line.length))
    dx, dy = after.x - before.x, after.y - before.y
    norm = (dx * dx + dy * dy) ** 0.5
    return (dx / norm, dy / norm) if norm else (0.0, 0.0)


def crossing_angle(route, edge, point):
    """Spitzer Schnittwinkel in Grad zwischen Radfernweg und Kante am Punkt."""
    ax, ay = line_direction(route, route.project(point))
    bx, by = line_direction(edge, edge.project(point))
    cosine = min(abs(ax * bx + ay * by), 1.0)
    return float(np.degrees(np.arccos(cosine)))


def find_node_suggestions(routes, detail, nodes, gaps):
    """Punkte, an denen ein Radfernweg eine Detailnetzkante kreuzt, fern von jedem Knoten.

    Hinweise je Vorschlag: `winkel_grad` (steil = echte Kreuzung, flach = läuft eher
    parallel) und `luecke_nah` (Anfang oder Ende einer Lücke in der Nähe).
    """
    node_tree = shapely.STRtree(nodes.geometry.to_numpy())
    gap_ends = [Point(c) for line in gaps.geometry for c in (line.coords[0], line.coords[-1])]
    gap_tree = shapely.STRtree(gap_ends) if gap_ends else None

    suggestions = []
    for route_name, route in zip(routes["name"], routes.geometry):
        for edge_pos in detail.sindex.query(route, predicate="intersects"):
            edge = detail.geometry.iloc[edge_pos]
            crossing = route.intersection(edge)
            for point in getattr(crossing, "geoms", [crossing]):
                if point.geom_type != "Point":
                    continue
                if node_tree.query_nearest(point, return_distance=True)[1][0] < NODE_SUGGESTION_MIN_NODE_DISTANCE_M:
                    continue
                angle = crossing_angle(route, edge, point)
                merged = next((s for s in suggestions if s["edge_pos"] == edge_pos
                               and s["point"].distance(point) < NODE_SUGGESTION_MERGE_DISTANCE_M), None)
                if merged:
                    merged["routes"].add(route_name)
                    if angle > merged["angle"]:
                        merged["angle"], merged["point"] = angle, point
                else:
                    suggestions.append({"edge_pos": edge_pos, "point": point, "routes": {route_name}, "angle": angle})

    rows = []
    for item in suggestions:
        edge_row = detail.iloc[item["edge_pos"]]
        point = item["point"]
        station = edge_row.geometry.project(point)
        near_gap = gap_tree is not None and gap_tree.query_nearest(
            point, return_distance=True)[1][0] <= NODE_SUGGESTION_GAP_DISTANCE_M
        rows.append({
            "element_nr": edge_row["element_nr"],
            "strassenname": edge_row["strassenname"],
            "verkehrsebene": edge_row["verkehrsebene"],
            "routen": " | ".join(sorted(str(name) for name in item["routes"] if name)),
            "winkel_grad": round(item["angle"], 1),
            "steil": bool(item["angle"] >= NODE_SUGGESTION_STEEP_ANGLE_DEG),
            "luecke_nah": bool(near_gap),
            "station_m": round(station, 1),
            "abstand_ende_m": round(edge_row.geometry.length - station, 1),
            "geometry": point,
        })
    frame = gpd.GeoDataFrame(rows, geometry="geometry", crs=detail.crs)
    frame = frame.sort_values(["element_nr", "station_m"]).reset_index(drop=True)
    logging.info(f"Knotenvorschläge: {len(frame)}, davon steil {int(frame['steil'].sum())}, "
                 f"mit Lücke in der Nähe {int(frame['luecke_nah'].sum())}")
    return frame


def area_polygon(bezirk):
    districts = gpd.read_file(ren.DISTRICTS_PATH)
    if districts.crs is None or districts.crs.to_epsg() != ren.DEFAULT_CRS:
        districts = districts.to_crs(CRS)
    match = districts[districts["name"].str.casefold() == bezirk.casefold()]
    if match.empty:
        names = ", ".join(sorted(districts["name"]))
        raise SystemExit(f"Bezirk „{bezirk}“ nicht gefunden. Vorhanden: {names}")
    return match.geometry.union_all().buffer(AREA_BUFFER_M)


def within_area(frame, area):
    if area is None:
        return frame
    return frame[frame.geometry.intersects(area)].reset_index(drop=True)


def feature_collection(frame):
    """GeoJSON in WGS84 mit gerundeten Koordinaten, ohne Feature-IDs."""
    wgs84 = frame.to_crs("EPSG:4326")
    wgs84["geometry"] = shapely.set_precision(wgs84.geometry.to_numpy(), COORDINATE_GRID)
    wgs84 = wgs84.astype(object).where(wgs84.notna(), None)
    return json.loads(gpd.GeoDataFrame(wgs84, geometry="geometry", crs="EPSG:4326").to_json(drop_id=True))


def file_date(path):
    match = re.search(r"\d{4}-\d{2}-\d{2}", path.name)
    if match:
        return match.group(0)
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).date().isoformat()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bezirk", help="Nur dieser Bezirk (Name wie in Berlin Bezirke.gpkg), z. B. Neukölln")
    args = parser.parse_args()

    area = area_polygon(args.bezirk) if args.bezirk else None
    gebiet = slugify(args.bezirk) if args.bezirk else "berlin"

    detail, detail_source = load_detailnetz()
    nodes, off_nodes = nodes_from_edges(detail)
    virtual = load_virtual_nodes()
    duplicates = sorted(set(virtual["id"]) & set(nodes["id"]))
    if duplicates:
        logging.warning(f"Virtuelle Knoten mit der ID eines Detailnetzknotens: {duplicates}")
    all_nodes = gpd.GeoDataFrame(pd.concat([nodes, virtual], ignore_index=True), crs=CRS)
    ren_netz = load_ren_netz()
    routes = load_radfernwege()
    gaps = find_gaps(routes, gpd.GeoDataFrame(
        pd.concat([detail[["geometry"]], ren_netz[["geometry"]]], ignore_index=True), crs=CRS))

    suggestions = find_node_suggestions(routes, detail, all_nodes, gaps)

    detail = within_area(detail, area)
    suggestions = within_area(suggestions, area)
    all_nodes = within_area(all_nodes, area)
    ren_netz = within_area(ren_netz, area)
    routes = within_area(routes, area)
    gaps = within_area(gaps, area)

    output = {
        "schema": SCHEMA,
        "gebiet": gebiet,
        "erzeugt_am": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "quellen": {
            "detailnetz": file_date(detail_source),
            "ren_netz": file_date(ren.MAPPING_NETWORK_PATH),
            "radfernwege": file_date(RADFERNWEGE_PATH),
            "virtuelle_knoten": file_date(VIRTUAL_NODES_PATH),
        },
        "detailnetz": feature_collection(detail),
        "knoten": feature_collection(all_nodes),
        "ren_netz": feature_collection(ren_netz),
        "radfernwege": feature_collection(routes),
        "luecken": feature_collection(gaps),
        "knoten_vorschlaege": feature_collection(suggestions),
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"netzanpassungen_{gebiet}.json"
    path.write_text(json.dumps(output, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    logging.info(f"Geschrieben: {path} ({path.stat().st_size / 1_000_000:.1f} MB)")

    report = within_area(off_nodes, area).to_crs("EPSG:4326")
    report_path = OUTPUT_DIR / f"pruefliste_{gebiet}.csv"
    pd.DataFrame({
        "knoten": report["id"],
        "element_nr": report["element_nr"],
        "abstand_m": report["abstand_m"],
        "lon": report.geometry.x.round(7),
        "lat": report.geometry.y.round(7),
    }).to_csv(report_path, index=False)
    logging.info(f"Prüfliste: {report_path} ({len(report)} Kantenenden abseits ihres Knotens)")


if __name__ == "__main__":
    main()
