#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
match_cycle_routes.py  (Schritt 2 der Pipeline)
--------------------------------------------------------------------
Ordnet die Radfernwege (touristisches Radnetz, GPS-Linien) automatisch den Kanten des
Rohnetzes und des Detailnetzes zu. Keine Handarbeit in diesem Schritt; was nicht eindeutig
passt, wird in der App Netzanpassungen gelöst.

Regel (Werte und Begründung: docs/netz-ablauf.md im Repo knotenpunkte, Abschnitt
„Zuordnungsregel“): Eine Kante gehört zur Route, wenn ein großer Teil ihrer Länge höchstens
MATCH_DISTANCE_M von der Route entfernt liegt UND die Route dort ungefähr parallel läuft
(Winkel unter MAX_ANGLE_DEG). Der Winkel verhindert, dass Querstraßen an Kreuzungen
mitgenommen werden. Gemessen wird an Stützpunkten alle SAMPLE_STEP_M entlang der Kante.
Kanten knapp darunter (ab CANDIDATE_SHARE) und lange Kanten, bei denen trotz hohem Anteil mehr als
MAX_OPEN_M ohne Route bleiben, sind Kandidaten für die App.
Hausdorff und das 95. Perzentil sind Kennzahlen je Abschnitt, kein Kriterium.

- REN+-Kanten (Rohnetz) bekommen `routen_fernradweg`, `routen_quelle = auto`.
- Detailnetzkanten, die noch nicht im REN+ sind und nicht neben einer zugeordneten REN+-Kante
  derselben Route liegen, kommen ins Netz (`quelle = detailnetz_radfernweg`,
  `grund_aufnahme = radfernweg`).
- Jeder Radfernweg wird lückenlos in Abschnitte zerlegt (Datei radfernweg_abschnitte.gpkg):
  `auf_ren`, `aufgenommen` oder `luecke`. Die Id ist fest: <route-slug>@<von>-<bis> (Meter
  entlang der Route). Die Lücken der App (`luecken`) sind die Abschnitte mit `luecke` ab
  MIN_GAP_LENGTH_M.

Die Schlüssel der Kanten in `kanten`/`kandidaten` sind die der App: `ren:<ref>` und
`detailnetz:<ref>` (ref = element_nr, ab der zweiten Linie derselben Nummer `#2`, ...; siehe
line_refs in write_app_input.py).

INPUT:
- ren-network/output/ren_netz_roh.gpkg (merge_networks.py)
- data/Berlin Straßenabschnitte Detailnetz*.fgb (jüngster Stand)
- data/netzquellen/touristisches_radnetz.gpkg (Drive, data/download_inputs.py)

OUTPUT (netzanpassungen/output/):
- ren_netz_auto.gpkg (Layer ren_netz): Rohnetz + Spalten quelle, grund_aufnahme, routen_fernradweg,
  routen_quelle, verkehrsrichtung + die aufgenommenen Detailnetzkanten
- radfernweg_abschnitte.gpkg (Layer radfernweg_abschnitte)

Aufruf:
    python netzanpassungen/match_cycle_routes.py
"""

import argparse
import json
import logging
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely.geometry import LineString, MultiLineString

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.append(str(ROOT / "ren-network"))
sys.path.append(str(HERE))

import merge_networks as ren  # noqa: E402
from write_app_input import (  # noqa: E402
    AUTO_PATH, MIN_GAP_LENGTH_M, OUTPUT_DIR, RADFERNWEGE_PATH, SECTIONS_LAYER, SECTIONS_PATH,
    gaps_of, line_refs, load_detailnetz, slugify)

CRS = f"EPSG:{ren.DEFAULT_CRS}"
ROH_PATH = ren.OUTPUT_PATH

# --- Zuordnungsregel (Begründung der Werte: docs/netz-ablauf.md, „Zuordnungsregel“) ---
# Eine Kante gilt als nah, wenn ihr Stützpunkt höchstens so weit von der Route liegt
MATCH_DISTANCE_M = 20.0
# Anteil der Kantenlänge, der nah UND parallel sein muss; darunter ab CANDIDATE_SHARE: Kandidat
MATCH_SHARE = 0.60
CANDIDATE_SHARE = 0.40
# Auch bei hohem Anteil dürfen höchstens so viele Meter einer langen Kante ohne Route bleiben, sonst Kandidat
MAX_OPEN_M = 250.0
# Spitzer Winkel zwischen Kante und Route, unter dem sie als parallel gelten
MAX_ANGLE_DEG = 45.0
# Abstand der Stützpunkte entlang der Kante und Länge, über die die Richtung gemessen wird (je Seite)
SAMPLE_STEP_M = 5.0
DIRECTION_WINDOW_M = 8.0
# Detailnetzkanten, deren Streckenanteil schon von zugeordneten REN+-Kanten abgedeckt wird, bleiben draußen
DETAIL_COVERED_MAX = 0.5
# Detailnetz: Autobahnen und Zubringer gehören nicht zum Netz (wie in merge_networks.py)
EXCLUDED_DETAIL_CLASSES = ren.AUTOBAHN_KLASSEN

# --- Abschnitte ---
# Kürzere Lücken (MIN_GAP_LENGTH_M, aus write_app_input.py) sind Abweichungen an Kreuzungen
# und gehen im Nachbarabschnitt auf
# Kürzere Abschnitte gleichen Zustands werden mit dem Nachbarn zusammengelegt
MIN_SECTION_M = 25.0
# Stücke unter dieser Länge gehen im längeren Nachbarn auf, auch bei anderem Zustand
MIN_PIECE_M = 5.0
# Abstand der Stützpunkte für Hausdorff und P95 je Abschnitt
METRIC_STEP_M = 2.0
MAX_CANDIDATES_PER_SECTION = 8
MIN_CANDIDATE_OVERLAP_M = 5.0

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s", force=True)


# ---------------------------------------------------------------------------
# Laden
# ---------------------------------------------------------------------------

def explode_with_rows(frame):
    """Eine Zeile je Linie; `row` ist die Position der Quellzeile. Reihenfolge wie single_lines()."""
    exploded = frame.reset_index(drop=True).explode(index_parts=False)
    exploded["row"] = exploded.index
    exploded = exploded.reset_index(drop=True)
    return exploded[exploded.geometry.geom_type == "LineString"].reset_index(drop=True)


def load_routes():
    """Radfernwege: Teilstücke je Route in Dateireihenfolge, mit Anfangsstation im Verlauf der Route."""
    raw = gpd.read_file(RADFERNWEGE_PATH, columns=["name"])
    if raw.crs is None or raw.crs.to_epsg() != ren.DEFAULT_CRS:
        raw = raw.to_crs(CRS)
    raw["geometry"] = shapely.force_2d(raw.geometry.to_numpy())
    routes = {}
    for name, geometry in zip(raw["name"], raw.geometry):
        parts = [part for part in (geometry.geoms if hasattr(geometry, "geoms") else [geometry])
                 if isinstance(part, LineString) and not part.is_empty]
        offsets = np.concatenate([[0.0], np.cumsum([part.length for part in parts])])
        routes[name] = {"parts": parts, "offsets": offsets, "length": float(offsets[-1]), "slug": slugify(name)}
    logging.info(f"Radfernwege: {len(routes)} Routen, {sum(r['length'] for r in routes.values()) / 1000:.1f} km")
    return routes


def load_ren_lines():
    """Rohnetz als Linien mit Schlüssel `ren:<ref>`; row = Zeile im Rohnetz."""
    roh = gpd.read_file(ROH_PATH, layer=ren.OUTPUT_LAYER)
    if roh.crs is None or roh.crs.to_epsg() != ren.DEFAULT_CRS:
        roh = roh.to_crs(CRS)
    if "ursprung_element_nr" not in roh.columns:
        roh["ursprung_element_nr"] = None
    lines = explode_with_rows(roh)
    lines["ref"] = line_refs(lines["element_nr"])
    lines["key"] = "ren:" + lines["ref"]
    return roh, lines


def load_detail_lines():
    """Detailnetz als Linien mit Schlüssel `detailnetz:<ref>` (ohne Autobahnen)."""
    detail, source = load_detailnetz(extra_columns=("strassenklasse1", "strassenklasse2"))
    detail["ref"] = line_refs(detail["element_nr"])
    detail["key"] = "detailnetz:" + detail["ref"]
    return detail, source


# ---------------------------------------------------------------------------
# Zuordnung Kante <-> Route
# ---------------------------------------------------------------------------

def tangent(lines, positions, window):
    """Richtungsvektoren der Linien (Array) an den Abständen `positions` vom Anfang."""
    lengths = shapely.length(lines)
    before = shapely.line_interpolate_point(lines, np.clip(positions - window, 0, lengths))
    after = shapely.line_interpolate_point(lines, np.clip(positions + window, 0, lengths))
    return shapely.get_coordinates(after) - shapely.get_coordinates(before)


def acute_angle_deg(a, b):
    """Spitzer Winkel in Grad zwischen zwei Vektorreihen; bei Nullvektor 90 (zählt nie als parallel)."""
    norm = np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        cosine = np.where(norm > 0, np.abs(np.sum(a * b, axis=1)) / norm, 0.0)
    return np.degrees(np.arccos(np.clip(cosine, 0, 1)))


def edge_samples(geometries):
    """Stützpunkte alle ~SAMPLE_STEP_M entlang jeder Linie: (Kantenindex, Abstand vom Anfang, halbe Schrittlänge)."""
    lengths = shapely.length(geometries)
    count = np.maximum(1, np.ceil(lengths / SAMPLE_STEP_M)).astype(int)
    edge = np.repeat(np.arange(len(geometries)), count)
    first = np.cumsum(count) - count
    k = np.arange(count.sum()) - np.repeat(first, count)
    position = (k + 0.5) / count[edge] * lengths[edge]
    half = lengths[edge] / count[edge] / 2
    return edge, position, half


def match_route(route, geometries, distance=None, angle=None):
    """Stützpunkte der Kanten gegen eine Route.

    Gibt je Stützpunkt zurück: nah (Abstand <= distance), parallel (Winkel < angle), Abstand und
    Station der nächsten Stelle auf der Route (Meter vom Routenanfang)."""
    distance = MATCH_DISTANCE_M if distance is None else distance
    angle = MAX_ANGLE_DEG if angle is None else angle
    edge, position, half = edge_samples(geometries)
    lines = geometries[edge]
    points = shapely.line_interpolate_point(lines, position)
    count = len(points)

    near = np.zeros(count, dtype=bool)
    parallel = np.zeros(count, dtype=bool)
    dist = np.full(count, np.inf)
    station = np.full(count, np.nan)

    parts = np.array(route["parts"], dtype=object)
    tree = shapely.STRtree(parts)
    found, nearest = tree.query_nearest(points, max_distance=distance, return_distance=False, all_matches=False)
    # tree.query_nearest ohne return_distance liefert (Eingabeindex, Baumindex)
    if len(found):
        part_of = np.full(count, -1)
        part_of[found] = nearest
        route_dir = np.zeros((count, 2))
        for part_index in np.unique(nearest):
            members = np.where(part_of == part_index)[0]
            part = parts[part_index]
            along = shapely.line_locate_point(part, points[members])
            station[members] = route["offsets"][part_index] + along
            dist[members] = shapely.distance(points[members], part)
            route_dir[members] = tangent(np.array([part] * len(members), dtype=object), along, DIRECTION_WINDOW_M)
        near[found] = True
        edge_dir = tangent(lines, position, DIRECTION_WINDOW_M)
        degrees = acute_angle_deg(edge_dir, route_dir)
        parallel = near & (degrees < angle)
    return {"edge": edge, "position": position, "half": half, "near": near, "parallel": parallel,
            "distance": dist, "station": station}


def intervals_of(station, half):
    """Zusammengefasste Stationsintervalle aus Stützpunkten (je Punkt Station +- half)."""
    order = np.argsort(station)
    merged = []
    for s, h in zip(station[order], half[order]):
        low, high = s - h, s + h
        if merged and low <= merged[-1][1] + 1e-6:
            merged[-1][1] = max(merged[-1][1], high)
        else:
            merged.append([low, high])
    return [(float(a), float(b)) for a, b in merged]


def match_all(routes, ren_lines, detail_lines, detail_in_ren, **kwargs):
    """Alle Kanten gegen alle Routen. Gibt eine Tabelle mit einer Zeile je (Route, Kante) zurück:
    route, netz (ren/detail), index, key, anteil, abstand_m (Mittel der passenden Stützpunkte),
    intervalle (Stationen), laenge_m. Nur Kanten mit anteil > 0."""
    rows = []
    for netz, lines in (("ren", ren_lines), ("detail", detail_lines)):
        geometries = lines.geometry.to_numpy()
        tree = shapely.STRtree(geometries)
        for name, route in routes.items():
            distance = kwargs.get("distance", MATCH_DISTANCE_M)
            corridor = shapely.union_all([part.buffer(distance) for part in route["parts"]])
            candidates = np.sort(tree.query(corridor, predicate="intersects"))
            if netz == "detail":
                candidates = np.array([i for i in candidates if not detail_in_ren[i]], dtype=int)
            if len(candidates) == 0:
                continue
            result = match_route(route, geometries[candidates], **kwargs)
            edge = result["edge"]
            lengths = shapely.length(geometries[candidates])
            samples_per_edge = np.bincount(edge, minlength=len(candidates))
            good_per_edge = np.bincount(edge, weights=result["parallel"].astype(float), minlength=len(candidates))
            for local in np.where(good_per_edge > 0)[0]:
                mask = (edge == local) & result["parallel"]
                rows.append({
                    "route": name, "netz": netz, "index": int(candidates[local]),
                    "key": lines["key"].iloc[candidates[local]],
                    "anteil": good_per_edge[local] / samples_per_edge[local],
                    "abstand_m": float(np.mean(result["distance"][mask])),
                    "intervalle": intervals_of(result["station"][mask], result["half"][mask]),
                    "laenge_m": float(lengths[local]),
                })
    return pd.DataFrame(rows, columns=["route", "netz", "index", "key", "anteil", "abstand_m", "intervalle", "laenge_m"])


# ---------------------------------------------------------------------------
# Abschnitte
# ---------------------------------------------------------------------------

def interval_overlap(intervals, low, high):
    return sum(max(0.0, min(b, high) - max(a, low)) for a, b in intervals)


def interval_length(intervals):
    return sum(b - a for a, b in intervals)


def covered_share(intervals, other_intervals):
    """Anteil der Intervalle, der von `other_intervals` abgedeckt wird."""
    total = interval_length(intervals)
    if total <= 0:
        return 0.0
    union = shapely.union_all([LineString([(a, 0), (b, 0)]) for a, b in other_intervals]) if other_intervals else None
    if union is None or union.is_empty:
        return 0.0
    mine = shapely.union_all([LineString([(a, 0), (b, 0)]) for a, b in intervals])
    return mine.intersection(union).length / total


def build_pieces(route, taken):
    """Elementare Stücke der Route mit den Kanten (Schlüssel -> Netz), die dort liegen.
    `taken`: Zeilen (key, netz, intervalle). Stücke enden an Teilstückgrenzen und an Intervallenden."""
    breaks = set(float(v) for v in route["offsets"])
    for item in taken:
        for a, b in item["intervalle"]:
            breaks.update((max(a, 0.0), min(b, route["length"])))
    cuts = sorted(breaks)
    pieces = []
    boundaries = set(float(v) for v in route["offsets"])
    for low, high in zip(cuts[:-1], cuts[1:]):
        if high - low < 1e-6:
            continue
        middle = (low + high) / 2
        keys = {item["key"]: item["netz"] for item in taken
                if any(a <= middle <= b for a, b in item["intervalle"])}
        pieces.append({"low": low, "high": high, "keys": keys})
    return pieces, boundaries


def state_of(keys):
    if any(netz == "ren" for netz in keys.values()):
        return "auf_ren"
    return "aufgenommen" if keys else "luecke"


def merge_pieces(pieces, boundaries):
    """Fasst Stücke zu Abschnitten zusammen: gleiche Kantenmenge und gleicher Zustand verschmelzen,
    kurze Lücken und kurze Stücke gehen im Nachbarn auf. Über Teilstückgrenzen wird nie verschmolzen."""
    sections = [{"low": p["low"], "high": p["high"], "keys": dict(p["keys"])} for p in pieces]
    for section in sections:
        section["state"] = state_of(section["keys"])

    def adjacent(a, b):
        return abs(a["high"] - b["low"]) < 1e-6 and not any(abs(a["high"] - edge) < 1e-6 for edge in boundaries)

    def join(a, b, state=None):
        keys = {**a["keys"], **b["keys"]}
        if state is not None:
            # Der Zustand des Nachbarn gilt: nur Kanten dieses Zustands bleiben (keine bei luecke)
            wanted = {"auf_ren": "ren", "aufgenommen": "detail"}.get(state)
            keys = {key: netz for key, netz in keys.items() if netz == wanted}
        return {"low": a["low"], "high": b["high"], "keys": keys, "state": state or state_of(keys)}

    changed = True
    while changed:
        changed = False
        # 1. gleiche Kantenmenge hintereinander
        i = 0
        while i < len(sections) - 1:
            a, b = sections[i], sections[i + 1]
            if adjacent(a, b) and set(a["keys"]) == set(b["keys"]):
                sections[i:i + 2] = [join(a, b)]
                changed = True
            else:
                i += 1
        # 2. kurze Lücken in den längeren Nachbarn (der Zustand des Nachbarn gilt)
        for i, section in enumerate(sections):
            if section["state"] == "luecke" and section["high"] - section["low"] < MIN_GAP_LENGTH_M:
                neighbours = [j for j in (i - 1, i + 1) if 0 <= j < len(sections)
                              and sections[j]["state"] != "luecke"
                              and (adjacent(sections[j], section) if j < i else adjacent(section, sections[j]))]
                if neighbours:
                    j = max(neighbours, key=lambda n: sections[n]["high"] - sections[n]["low"])
                    low, high = sorted((j, i))
                    sections[low:high + 1] = [join(sections[low], sections[high], state=sections[j]["state"])]
                    changed = True
                    break
        if changed:
            continue
        # 3. kurze Stücke mit gleichem Zustand wie ein Nachbar verschmelzen
        for i, section in enumerate(sections):
            if section["high"] - section["low"] >= MIN_SECTION_M:
                continue
            neighbours = [j for j in (i - 1, i + 1) if 0 <= j < len(sections)
                          and sections[j]["state"] == section["state"]
                          and (adjacent(sections[j], section) if j < i else adjacent(section, sections[j]))]
            if neighbours:
                j = max(neighbours, key=lambda n: sections[n]["high"] - sections[n]["low"])
                low, high = sorted((j, i))
                sections[low:high + 1] = [join(sections[low], sections[high])]
                changed = True
                break
        if changed:
            continue
        # 4. winzige Stücke (Rundungsreste an Intervallenden) in den längeren Nachbarn, Zustand des Nachbarn gilt
        for i, section in enumerate(sections):
            if section["high"] - section["low"] >= MIN_PIECE_M:
                continue
            neighbours = [j for j in (i - 1, i + 1) if 0 <= j < len(sections)
                          and (adjacent(sections[j], section) if j < i else adjacent(section, sections[j]))]
            if neighbours:
                j = max(neighbours, key=lambda n: sections[n]["high"] - sections[n]["low"])
                low, high = sorted((j, i))
                sections[low:high + 1] = [join(sections[low], sections[high], state=sections[j]["state"])]
                changed = True
                break
    return sections


def route_geometry(route, low, high):
    """Linie der Route zwischen den Stationen (innerhalb eines Teilstücks)."""
    index = int(np.searchsorted(route["offsets"], (low + high) / 2, side="right") - 1)
    index = min(max(index, 0), len(route["parts"]) - 1)
    start = route["offsets"][index]
    return shapely.ops.substring(route["parts"][index], low - start, high - start)


def deviation_metrics(section_line, edge_geometries):
    """Hausdorff (Abschnitt -> Kanten, einseitig) und 95. Perzentil der Abstände, Meter."""
    union = shapely.union_all(edge_geometries)
    count = max(2, int(np.ceil(section_line.length / METRIC_STEP_M)) + 1)
    points = shapely.line_interpolate_point(section_line, np.linspace(0, section_line.length, count))
    distances = shapely.distance(points, union)
    return float(distances.max()), float(np.percentile(distances, 95))


def build_sections(routes, matches, ren_lines, detail_lines):
    """Zerlegt jede Route lückenlos in Abschnitte. Gibt (Abschnitte, genommene Kanten je Route) zurück."""
    rows = []
    geometries = {"ren": ren_lines.geometry.to_numpy(), "detail": detail_lines.geometry.to_numpy()}
    for name, route in routes.items():
        mine = matches[matches["route"] == name]
        is_taken = (mine["anteil"] >= MATCH_SHARE) & (mine["laenge_m"] * (1 - mine["anteil"]) <= MAX_OPEN_M)
        taken = mine[is_taken]
        rest = mine[~is_taken & (mine["anteil"] >= CANDIDATE_SHARE)]
        taken_items = [{"key": r.key, "netz": r.netz, "intervalle": r.intervalle, "index": r.index}
                       for r in taken.itertuples() if r.netz == "ren"]
        ren_intervals = [iv for item in taken_items for iv in item["intervalle"]]
        for r in taken.itertuples():
            if r.netz == "detail" and covered_share(r.intervalle, ren_intervals) <= DETAIL_COVERED_MAX:
                taken_items.append({"key": r.key, "netz": "detail", "intervalle": r.intervalle, "index": r.index})
        taken_index = {item["key"]: item["index"] for item in taken_items}
        pieces, boundaries = build_pieces(route, taken_items)
        for section in merge_pieces(pieces, boundaries):
            low, high = section["low"], section["high"]
            line = route_geometry(route, low, high)
            keys = sorted(section["keys"], key=lambda key: (section["keys"][key] != "ren", key))
            # Nur Kanten des Zustands zählen: REN+ bei auf_ren, Detailnetz bei aufgenommen, keine bei luecke
            wanted = {"auf_ren": "ren", "aufgenommen": "detail"}.get(section["state"])
            keys = [key for key in keys if section["keys"][key] == wanted]
            candidates = []
            for r in rest.itertuples():
                overlap = interval_overlap(r.intervalle, low, high)
                if overlap >= MIN_CANDIDATE_OVERLAP_M and r.key not in keys:
                    candidates.append((r.anteil, r.key))
            candidates = [key for _, key in sorted(candidates, reverse=True)[:MAX_CANDIDATES_PER_SECTION]]
            hausdorff = p95 = None
            if keys:
                edge_geoms = [geometries[section["keys"][key]][taken_index[key]] for key in keys]
                hausdorff, p95 = deviation_metrics(line, edge_geoms)
            rows.append({
                "id": f"{route['slug']}@{int(round(low))}-{int(round(high))}",
                "radfernweg": name,
                "station_von_m": int(round(low)),
                "station_bis_m": int(round(high)),
                "laenge_m": round(line.length, 1),
                "zustand": section["state"],
                "kanten": "|".join(keys),
                "kandidaten": "|".join(candidates),
                "hausdorff_m": None if hausdorff is None else round(hausdorff, 1),
                "p95_m": None if p95 is None else round(p95, 1),
                "geometry": line,
            })
    sections = gpd.GeoDataFrame(rows, geometry="geometry", crs=CRS)
    duplicated = sections["id"].duplicated()
    if duplicated.any():
        raise SystemExit(f"Doppelte Abschnitts-Ids: {sections.loc[duplicated, 'id'].tolist()}")
    return sections


# ---------------------------------------------------------------------------
# Netz mit Zuordnung
# ---------------------------------------------------------------------------

def as_multiline(geometry):
    return MultiLineString([geometry]) if isinstance(geometry, LineString) else geometry


def routes_text(names):
    return "; ".join(sorted(set(names))) if names else None


def append_detail_rows(network, edges, quelle, grund_aufnahme, routes, routes_quelle):
    """Hängt Detailnetzkanten als Zeilen an das Netz (Spalten wie merge_networks.py).

    `edges`: Linien des Detailnetzes (element_nr, strassenname, strassenklasse1, verkehrsrichtung, geometry),
    `routes`: je Kante der Text für routen_fernradweg. Wird auch von apply_app_result.py für von Hand
    zugeordnete Detailnetzkanten genutzt (quelle detailnetz_manuell)."""
    if len(edges) == 0:
        return network
    rows = []
    for edge, route in zip(edges.itertuples(), routes):
        klasse = edge.strassenklasse1
        rows.append({
            "element_nr": edge.element_nr,
            "element_nr_berechnet": "nein",
            "geometry": as_multiline(edge.geometry),
            "radverkehrsnetz": ren.RVN_KEIN,
            "strassenname": edge.strassenname,
            "strassenklasse": klasse if klasse not in (None, "", "0") and not pd.isna(klasse) else None,
            "netz_quellen": "detailnetz",
            "netz_quellen_teilweise": None,
            "in_detailnetz": "ja",
            "hauptverkehrsstrasse": "nein",  # nur Kanten des Hauptstraßennetzes zählen (wie in merge_networks.py)
            "bearbeitet_2025": "nein",
            "anteil_2025": 0.0,
            "verkehrsrichtung": edge.verkehrsrichtung if edge.verkehrsrichtung in ("B", "R", "G") else None,
            "quelle": quelle,
            "grund_aufnahme": grund_aufnahme,
            "routen_fernradweg": route,
            "routen_quelle": routes_quelle,
        })
    added = gpd.GeoDataFrame(rows, geometry="geometry", crs=CRS)
    added = ren.add_nodes(added)
    added = ren.add_district(added)
    added["laenge_m"] = added.geometry.length.round(1)
    first = int(network["lfd_nr"].max()) + 1 if len(network) else 1
    added["lfd_nr"] = range(first, first + len(added))
    added = added[[column for column in added.columns if column in network.columns]]
    # Die Indexmarken der bestehenden Zeilen bleiben, die neuen folgen dahinter
    start = int(network.index.max()) + 1 if len(network) else 0
    added.index = range(start, start + len(added))
    return gpd.GeoDataFrame(pd.concat([network, added]), geometry="geometry", crs=CRS)


def apply_assignment(roh, ren_lines, detail_lines, matches, sections):
    """Rohnetz mit routen_fernradweg/routen_quelle/quelle/verkehrsrichtung und den aufgenommenen Detailnetzkanten."""
    network = roh.copy()
    richtung = detail_lines.dropna(subset=["element_nr", "verkehrsrichtung"]).drop_duplicates("element_nr").set_index(
        "element_nr")["verkehrsrichtung"]
    # Edges renumbered in step 1 take the direction of the Detailnetz edge they came from
    origin = network["ursprung_element_nr"] if "ursprung_element_nr" in network.columns else pd.Series(None, index=network.index)
    direction = network["element_nr"].map(richtung).fillna(origin.map(richtung))
    network["verkehrsrichtung"] = direction.where(lambda column: column.isin(["B", "R", "G"]))
    network["quelle"] = "radnetz"
    network["grund_aufnahme"] = None
    network["routen_fernradweg"] = None
    network["routen_quelle"] = None

    taken_keys = {}
    for section in sections.itertuples():
        for key in filter(None, section.kanten.split("|")):
            taken_keys.setdefault(key, set()).add(section.radfernweg)
    # nur Kanten, die der Abschnitt auch wirklich zugeordnet hat, nicht jede Kante über der Schwelle
    ren_routes = {}
    for key, names in taken_keys.items():
        if key.startswith("ren:"):
            ren_routes[key] = names
    by_row = {}
    for key, row in zip(ren_lines["key"], ren_lines["row"]):
        if key in ren_routes:
            by_row.setdefault(row, set()).update(ren_routes[key])
    for row, names in by_row.items():
        network.at[network.index[row], "routen_fernradweg"] = routes_text(names)
        network.at[network.index[row], "routen_quelle"] = "auto"

    added_keys = sorted(key for key in taken_keys if key.startswith("detailnetz:"))
    lookup = detail_lines.set_index("key")
    network = append_detail_rows(network, lookup.loc[added_keys].reset_index(), "detailnetz_radfernweg", "radfernweg",
                                 [routes_text(taken_keys[key]) for key in added_keys], "auto")
    logging.info(f"REN+-Zeilen mit Radfernweg: {len(by_row)}, aufgenommene Detailnetzkanten: {len(added_keys)}")
    return network


def summarize(sections, matches):
    for state in ("auf_ren", "aufgenommen", "luecke"):
        part = sections[sections["zustand"] == state]
        logging.info(f"Abschnitte {state}: {len(part)}, {part['laenge_m'].sum() / 1000:.1f} km")
    logging.info(f"Lücken (ab {MIN_GAP_LENGTH_M:.0f} m): {len(gaps_of(sections))}")
    for name, group in sections.groupby("radfernweg"):
        total = group["laenge_m"].sum()
        gap = group.loc[group["zustand"] == "luecke", "laenge_m"].sum()
        logging.info(f"  {name}: {total / 1000:.1f} km, Lücke {gap / 1000:.2f} km ({gap / total:.0%})")


def run(output_dir=OUTPUT_DIR, write=True, **kwargs):
    roh, ren_lines = load_ren_lines()
    detail_lines, _ = load_detail_lines()
    detail_lines = detail_lines[~detail_lines["strassenklasse2"].isin(EXCLUDED_DETAIL_CLASSES)].reset_index(drop=True)
    routes = load_routes()
    # Step 1 renumbers edges it splits: a Detailnetz edge counts as in REN+ also under its old number (ursprung_element_nr)
    ren_numbers = set(roh["element_nr"].dropna()) | set(roh["ursprung_element_nr"].dropna())
    detail_in_ren = detail_lines["element_nr"].isin(ren_numbers).to_numpy()
    matches = match_all(routes, ren_lines, detail_lines, detail_in_ren, **kwargs)
    sections = build_sections(routes, matches, ren_lines, detail_lines)
    summarize(sections, matches)
    network = apply_assignment(roh, ren_lines, detail_lines, matches, sections)
    if write:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        network.to_file(output_dir / AUTO_PATH.name, layer=ren.OUTPUT_LAYER, driver="GPKG")
        sections.to_file(output_dir / SECTIONS_PATH.name, layer=SECTIONS_LAYER, driver="GPKG")
        logging.info(f"Geschrieben: {output_dir / AUTO_PATH.name}, {output_dir / SECTIONS_PATH.name}")
    return network, sections, matches


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.parse_args()
    # Gleiche Eingangsdaten für alle: vor jedem Lauf aus dem gemeinsamen Drive-Ordner
    ren.download_inputs()
    run()


if __name__ == "__main__":
    main()
