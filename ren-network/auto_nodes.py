#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
auto_nodes.py  (part of step 1, used by merge_networks.py)
--------------------------------------------------------------------
Gives every edge of the merged REN+ a unique, stable element_nr `<von>_<bis>.<nn>` built from its
two end nodes. For that, every edge end must sit on a node:

- official nodes: the Detailnetz nodes (Verbindungspunkte with Knotenpunkt-ID), end within
  OFFICIAL_TOL_M;
- the 53 virtual nodes of 2025 (data/virtuelle_knoten_2025.gpkg): fixed names, fixed input like the
  Detailnetz nodes;
- automatic virtual nodes, set here by snapping:
  * on an edge: an edge end (not at an official node) lies on the interior of another REN+ edge
    (within SNAP_TOL_M). A node is set there and the other edge is split. Ends that meet the same
    spot on the same edge share one node.
  * junction: edge ends that meet each other (within SNAP_TOL_M) with no official node and no
    edge passing through share one node.
  * dead end: an end that touches nothing gets an end node.
  A 2025 node within NODE_2025_TOL_M of such a point supplies the name (and is the node).
  Every 2025 node also splits the edges that pass through it.

Naming like the app (netzanpassungen/src/network/naming.ts in the repo knotenpunkte): on an edge
`V<A>-<B>` with the nearest official nodes A and B along the host edge in both directions, on
collision `V<nearer>-2`, `-3`, ...; dead ends and junctions `V<nearest official>-<n>`.

Numbering: an existing element_nr is never changed unless it has to be. An edge keeps its element_nr
when it was not split (even if an end is off its node) and it is the longest edge with that element_nr.
All other edges (split pieces, extra separate parts of a multi-part edge, edges without element_nr) get `<von>_<bis>.<nn>`, `nn` counting per unordered node pair on top of the highest
number ever used by the Detailnetz and by REN+ before this step (dropped numbers included, so a number is never issued twice). Direction in the name is the direction of the line. The
element_nr before the change stays in `ursprung_element_nr`. `von_knoten`/`bis_knoten` of an edge that keeps its
element_nr are the nodes that number names; where its geometric ends sit on other nodes, those are in
`knoten_anfang`/`knoten_ende` (else empty).

Manual virtual nodes drawn in the app are not part of this step; step 3 adds them
(netzanpassungen/apply_app_result.py).
"""

import heapq
import logging
import re
from collections import defaultdict

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely.geometry import MultiLineString, Point
from shapely.ops import substring

# An edge end this close to another edge counts as touching it (also the margin to the host's ends)
SNAP_TOL_M = 2.0
# An edge end this close to an official node sits on it (same as assign_element_nr_to_rvn.py)
OFFICIAL_TOL_M = 3.0
# A 2025 node this close to a snap point is that node; it also splits edges passing within this distance
NODE_2025_TOL_M = 2.0
# Ends on the same host edge whose positions along it differ by at most this share one node
CLUSTER_STATION_M = 3.0
# Two split points on one edge closer than this count as one
MIN_STOP_GAP_M = 0.5
# Dijkstra limit when looking for the nearest official node
MAX_SEARCH_STEPS = 20000

ELEMENT_NR_PATTERN = re.compile(r"^(.+)_(.+)\.(\d+)$")
NODE_COLUMNS = ["Knotenpunkt-ID", "ist_virtuell", "quelle", "art", "traeger_netz", "traeger_element_nr",
                "station_m", "kommentar", "eintrag_id", "geometry"]


class Nodes:
    """Registry of all nodes with a key, kind (official | 2025 | auto), name and position."""

    def __init__(self):
        self.items = {}

    def add(self, key, kind, name, point, **extra):
        self.items[key] = {"key": key, "kind": kind, "name": name, "point": point, **extra}
        return self.items[key]

    def __getitem__(self, key):
        return self.items[key]


def parse_element_nr(element_nr):
    """(von, bis, nn) of `<von>_<bis>.<nn>`, otherwise None."""
    match = ELEMENT_NR_PATTERN.match(element_nr) if isinstance(element_nr, str) else None
    return (match.group(1), match.group(2), int(match.group(3))) if match else None


def pair_key(a, b):
    return tuple(sorted((a, b)))


def find_hosts(point, own_line, geoms, tree, starts, ends):
    """Other edges whose interior lies within SNAP_TOL_M of `point` (and whose ends are farther than that):
    list of (distance, line index, station)."""
    found = []
    for j in tree.query(point, predicate="dwithin", distance=SNAP_TOL_M):
        j = int(j)
        if j == own_line:
            continue
        if starts[j].distance(point) <= SNAP_TOL_M or ends[j].distance(point) <= SNAP_TOL_M:
            continue
        found.append((geoms[j].distance(point), j, geoms[j].project(point)))
    return sorted(found)


def cluster_by_distance(points, tolerance):
    """Single-link clusters of points closer than `tolerance`: list of lists of indexes."""
    if not points:
        return []
    tree = shapely.STRtree(points)
    parent = list(range(len(points)))

    def root(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for i, point in enumerate(points):
        for j in tree.query(point, predicate="dwithin", distance=tolerance):
            parent[root(i)] = root(int(j))
    groups = defaultdict(list)
    for i in range(len(points)):
        groups[root(i)].append(i)
    return list(groups.values())


def snap_candidates(unresolved, geoms, tree, starts, ends):
    """Groups the unresolved ends into candidate nodes.

    `unresolved`: list of (line index, side, point). Returns a list of dicts with art (on_edge | junction |
    dead_end), point, hosts [(line, station)] and members [(line, side)]."""
    candidates = []
    on_host = defaultdict(list)  # primary host -> [(station, member index)]
    free = []
    for member, (line, side, point) in enumerate(unresolved):
        hosts = find_hosts(point, line, geoms, tree, starts, ends)
        if hosts:
            _, host, station = hosts[0]
            on_host[host].append((station, member))
        else:
            free.append(member)

    for host, items in on_host.items():
        items.sort()
        groups = [[items[0]]]
        for item in items[1:]:
            if item[0] - groups[-1][-1][0] <= CLUSTER_STATION_M:
                groups[-1].append(item)
            else:
                groups.append([item])
        for group in groups:
            members = [member for _, member in group]
            centre = shapely.centroid(shapely.MultiPoint([unresolved[m][2] for m in members]))
            station = geoms[host].project(centre)
            point = geoms[host].interpolate(station)
            candidates.append({"art": "on_edge", "point": point, "hosts": [(host, station)],
                               "members": [(unresolved[m][0], unresolved[m][1]) for m in members]})

    # Ends without a host: join an edge node nearby, otherwise meet each other (junction) or stand alone (dead end)
    edge_points = [c["point"] for c in candidates]
    edge_tree = shapely.STRtree(edge_points) if edge_points else None
    rest = []
    for member in free:
        line, side, point = unresolved[member]
        near = edge_tree.query_nearest(point, max_distance=SNAP_TOL_M, all_matches=False) if edge_tree else []
        if len(near):
            candidates[int(near[0])]["members"].append((line, side))
        else:
            rest.append(member)
    for group in cluster_by_distance([unresolved[m][2] for m in rest], SNAP_TOL_M):
        members = [rest[g] for g in group]
        centre = shapely.centroid(shapely.MultiPoint([unresolved[m][2] for m in members]))
        candidates.append({"art": "junction" if len(members) > 1 else "dead_end", "point": centre, "hosts": [],
                           "members": [(unresolved[m][0], unresolved[m][1]) for m in members]})
    # Other edges passing through an edge node (crossing of two edges) are split there, too
    for candidate in candidates:
        if candidate["art"] != "on_edge":
            continue
        known = {line for line, _ in candidate["hosts"]}
        for _, j, station in find_hosts(candidate["point"], -1, geoms, tree, starts, ends):
            if j not in known and j not in {line for line, _ in candidate["members"]}:
                candidate["hosts"].append((j, station))
    return candidates


def nearest_official(adjacency, nodes, start, start_distance, blocked):
    """Nearest official node from `start` (Dijkstra, not passing `blocked`): (name, distance) or None."""
    if start in blocked:
        return None
    best = {start: start_distance}
    heap = [(start_distance, start)]
    done = set()
    for _ in range(MAX_SEARCH_STEPS):
        if not heap:
            return None
        distance, key = heapq.heappop(heap)
        if key in done:
            continue
        done.add(key)
        if nodes[key]["kind"] == "official":
            return nodes[key]["name"], distance
        for other, length in adjacency.get(key, ()):
            if other in blocked or other in done:
                continue
            candidate = distance + length
            if candidate < best.get(other, float("inf")):
                best[other] = candidate
                heapq.heappush(heap, (candidate, other))
    return None


def name_auto_nodes(auto_keys, nodes, pieces, adjacency, taken, host_of):
    """Names the automatic nodes (like suggestVirtualNodeName in the app). `host_of`: key -> original element_nr."""
    sort_key = lambda key: (0 if nodes[key]["art"] == "on_edge" else 1, host_of.get(key) or "",
                            nodes[key]["station"] if nodes[key]["station"] is not None else 0.0,
                            round(nodes[key]["point"].x, 1), round(nodes[key]["point"].y, 1))
    by_parent = defaultdict(list)
    for piece in pieces:
        by_parent[piece["parent"]].append(piece)
    for key in sorted(auto_keys, key=sort_key):
        node = nodes[key]
        name = None
        near = None
        if node["art"] == "on_edge":
            host = node["hosts"][0][0]
            left = next((p for p in by_parent[host] if p["b"] == key), None)
            right = next((p for p in by_parent[host] if p["a"] == key), None)
            side_a = nearest_official(adjacency, nodes, left["a"], left["length"], {key}) if left else None
            side_b = nearest_official(adjacency, nodes, right["b"], right["length"], {key}) if right else None
            if side_a and side_b and side_a[0] != side_b[0]:
                candidate = f"V{side_a[0]}-{side_b[0]}"
                if candidate not in taken:
                    name = candidate
            sides = [side for side in (side_a, side_b) if side]
            near = min(sides, key=lambda side: side[1])[0] if sides else None
        else:
            found = nearest_official(adjacency, nodes, key, 0.0, set())
            near = found[0] if found else None
        if name is None:
            prefix = f"V{near}" if near else "V"
            count = 2 if node["art"] == "on_edge" else 1
            while f"{prefix}-{count}" in taken:
                count += 1
            name = f"{prefix}-{count}"
        node["name"] = name
        taken.add(name)


def build_nodes_and_pieces(lines, official, nodes_2025, official_column):
    """Steps 1 to 4 of the module docstring: nodes, split pieces. Returns (nodes, pieces, report)."""
    geoms = lines.geometry.to_numpy()
    count = len(geoms)
    starts = shapely.get_point(geoms, 0)
    ends = shapely.get_point(geoms, -1)
    tree = shapely.STRtree(geoms)

    nodes = Nodes()
    for node_id, point in zip(official[official_column].astype(str), official.geometry):
        nodes.add(f"o:{node_id}", "official", node_id, point)
    end_node = {}  # (line, side) -> node key
    official_tree = shapely.STRtree(official.geometry.to_numpy())
    official_keys = [f"o:{node_id}" for node_id in official[official_column].astype(str)]
    for side, points in ((0, starts), (1, ends)):
        found, near = official_tree.query_nearest(points, max_distance=OFFICIAL_TOL_M, all_matches=False)
        for line, node in zip(found, near):
            end_node[(int(line), side)] = official_keys[int(node)]

    # Ends that touch the end of another edge sitting on an official node take that node
    resolved_points = [(starts if side == 0 else ends)[line] for (line, side) in end_node]
    resolved_keys = list(end_node.values())
    resolved_tree = shapely.STRtree(resolved_points) if resolved_points else None
    unresolved = []
    for side, points in ((0, starts), (1, ends)):
        for line in range(count):
            if (line, side) in end_node:
                continue
            point = points[line]
            near = resolved_tree.query_nearest(point, max_distance=SNAP_TOL_M, all_matches=False) if resolved_tree else []
            if len(near):
                end_node[(line, side)] = resolved_keys[int(near[0])]
            else:
                unresolved.append((line, side, point))
    candidates = snap_candidates(unresolved, geoms, tree, starts, ends)

    # 2025 nodes: a candidate within NODE_2025_TOL_M is that node, the closest pair first
    v_names = list(nodes_2025["Knotenpunkt-ID"].astype(str))
    v_points = list(nodes_2025.geometry)
    for name, point in zip(v_names, v_points):
        nodes.add(f"v:{name}", "2025", name, point, art=None, hosts=[], station=None)
    pairs = sorted(
        (candidate["point"].distance(point), c, v)
        for c, candidate in enumerate(candidates) for v, point in enumerate(v_points)
        if candidate["point"].distance(point) <= NODE_2025_TOL_M)
    matched_candidate, matched_node = {}, set()
    for distance, c, v in pairs:
        if c not in matched_candidate and v not in matched_node:
            matched_candidate[c] = v
            matched_node.add(v)

    stops = defaultdict(list)  # line -> [(station, node key)]

    def add_stop(line, station, key):
        if station < MIN_STOP_GAP_M or station > geoms[line].length - MIN_STOP_GAP_M:
            return  # at the end of the edge: no split
        if all(existing_key != key for _, existing_key in stops[line]):
            stops[line].append((station, key))

    auto_keys = []
    for c, candidate in enumerate(candidates):
        if c in matched_candidate:
            key = f"v:{v_names[matched_candidate[c]]}"
            nodes[key]["art"] = candidate["art"]
            nodes[key]["matched"] = True
        else:
            key = f"a:{len(auto_keys)}"
            nodes.add(key, "auto", None, candidate["point"], art=candidate["art"],
                      hosts=candidate["hosts"], station=candidate["hosts"][0][1] if candidate["hosts"] else None)
            auto_keys.append(key)
            for line, station in candidate["hosts"]:
                add_stop(line, station, key)
        for member in candidate["members"]:
            end_node[member] = key

    # Every 2025 node splits the edges passing through it
    for v, (name, point) in enumerate(zip(v_names, v_points)):
        key = f"v:{name}"
        for _, line, station in find_hosts(point, -1, geoms, tree, starts, ends):
            add_stop(line, station, key)
            node = nodes[key]
            if not node["hosts"]:
                node["hosts"] = [(line, station)]
                node["station"] = station
            else:
                node["hosts"].append((line, station))
    for c, candidate in enumerate(candidates):
        if c in matched_candidate:
            key = f"v:{v_names[matched_candidate[c]]}"
            for line, station in candidate["hosts"]:
                add_stop(line, station, key)
                if nodes[key]["station"] is None:
                    nodes[key]["hosts"] = [(line, station)]
                    nodes[key]["station"] = station

    # Split the edges
    pieces = []
    for line in range(count):
        a, b = end_node[(line, 0)], end_node[(line, 1)]
        geometry = geoms[line]
        length = geometry.length
        cuts = []
        for station, key in sorted(stops[line]):
            if cuts and station - cuts[-1][0] < MIN_STOP_GAP_M:
                continue
            cuts.append((station, key))
        chain = [(0.0, a)] + cuts + [(length, b)]
        for (low, start_key), (high, end_key) in zip(chain[:-1], chain[1:]):
            part = geometry if len(chain) == 2 else substring(geometry, low, high)
            pieces.append({"parent": line, "a": start_key, "b": end_key, "geometry": part,
                           "length": part.length, "split": len(chain) > 2})

    adjacency = defaultdict(list)
    for piece in pieces:
        adjacency[piece["a"]].append((piece["b"], piece["length"]))
        adjacency[piece["b"]].append((piece["a"], piece["length"]))
    taken = {node["name"] for node in nodes.items.values() if node["kind"] in ("official", "2025")}
    host_of = {}
    for key in auto_keys:
        hosts = nodes[key]["hosts"]
        if hosts:
            parent_element_nr = lines["element_nr"].iloc[hosts[0][0]]
            host_of[key] = parent_element_nr if isinstance(parent_element_nr, str) else None
    name_auto_nodes(auto_keys, nodes, pieces, adjacency, taken, host_of)

    report = {
        "lines": count, "pieces": len(pieces), "split_lines": sum(1 for line in stops if stops[line]),
        "auto_nodes": len(auto_keys), "auto_by_art": pd.Series([nodes[k]["art"] for k in auto_keys]).value_counts().to_dict(),
        "nodes_2025": len(v_names), "nodes_2025_matched": len(matched_node),
        "nodes_2025_split_edge": sum(1 for v in v_names if any(key == f"v:{v}" for line in stops for _, key in stops[line])),
        "nodes_2025_unused": [v for v in v_names if not any(key == f"v:{v}" for line in stops for _, key in stops[line])
                              and not any(k == f"v:{v}" for k in end_node.values())],
    }
    return nodes, pieces, auto_keys, host_of, report


def number_pieces(lines, pieces, nodes, detail_element_nrs):
    """element_nr per piece: an existing number is never changed unless it has to be (principle agreed with the
    customer). Kept: edges that were not split, the longest one where a number occurs on several lines. New
    `<von>_<bis>.<nn>`: edges without number, the pieces of split edges, the extra lines of a duplicated number.
    Returns (element_nr list, kept flags)."""
    names = lambda key: nodes[key]["name"]
    used = defaultdict(int)  # unordered pair -> highest nn
    # Count on top of every number ever used: Detailnetz and all REN+ numbers before this step, including the ones
    # that are dropped (split edges, extra lines), so a new number never repeats a string issued earlier
    for element_nr in list(detail_element_nrs) + list(lines["element_nr"].dropna()):
        parsed = parse_element_nr(element_nr)
        if parsed:
            key = pair_key(parsed[0], parsed[1])
            used[key] = max(used[key], parsed[2])

    keep = {}
    for index, piece in enumerate(pieces):
        if piece["split"]:
            continue
        element_nr = lines["element_nr"].iloc[piece["parent"]]
        if isinstance(element_nr, str) and element_nr != "":
            current = keep.get(element_nr)
            if current is None or piece["length"] > pieces[current]["length"]:
                keep[element_nr] = index
    kept = set(keep.values())
    for element_nr in keep:
        parsed = parse_element_nr(element_nr)
        if parsed:
            key = pair_key(parsed[0], parsed[1])
            used[key] = max(used[key], parsed[2])

    result = [None] * len(pieces)
    for index, piece in enumerate(pieces):
        if index in kept:
            result[index] = lines["element_nr"].iloc[piece["parent"]]
            continue
        a, b = names(piece["a"]), names(piece["b"])
        key = pair_key(a, b)
        used[key] += 1
        result[index] = f"{a}_{b}.{used[key]:02d}"
    return result, kept


def assert_unique(frame, column="element_nr"):
    """Fail loudly: every row has an element_nr and no element_nr occurs twice."""
    missing = int(frame[column].isna().sum())
    duplicated = sorted(set(frame.loc[frame[column].duplicated(keep=False) & frame[column].notna(), column]))
    if missing or duplicated:
        raise RuntimeError(f"{column} is not unique: {missing} rows without value, "
                           f"{len(duplicated)} values on several rows, e.g. {duplicated[:5]}")


def node_frame(nodes, auto_keys, pieces, lines, crs):
    """The virtual nodes (2025 and automatic) with the schema of virtuelle_knoten.gpkg."""
    rows = []
    for key, node in nodes.items.items():
        if node["kind"] == "official":
            continue
        host = node["hosts"][0] if node.get("hosts") else None
        host_element_nr = lines["element_nr"].iloc[host[0]] if host else None
        host_element_nr = host_element_nr if isinstance(host_element_nr, str) else None
        if node["kind"] == "2025":
            comment = ("Delivery 2025, fixed name; " +
                       (f"on {host_element_nr or 'an edge without element_nr'}" if host else "no REN+ edge within reach"))
        else:
            comment = {"on_edge": "Set automatically: an edge end lies on this edge",
                       "junction": "Set automatically: edge ends meet here",
                       "dead_end": "Set automatically: end of an edge that touches nothing"}[node["art"]]
        rows.append({
            "Knotenpunkt-ID": node["name"], "ist_virtuell": 1, "quelle": node["kind"],
            "art": node.get("art") or ("on_edge" if host else None),
            "traeger_netz": "ren" if host else None,
            "traeger_element_nr": host_element_nr,
            "station_m": round(host[1], 2) if host else None, "kommentar": comment, "eintrag_id": None,
            "geometry": node["point"],
        })
    frame = gpd.GeoDataFrame(rows, columns=NODE_COLUMNS, geometry="geometry", crs=crs)
    return frame.sort_values(["quelle", "Knotenpunkt-ID"]).reset_index(drop=True)


def snap_and_number(network, official, nodes_2025, detail_element_nrs, official_column):
    """The whole sub-step: `network` (one LineString per row, `element_nr` possibly empty) ->
    (network with unique element_nr, von_knoten, bis_knoten, ursprung_element_nr; virtual nodes; report)."""
    lines = network.reset_index(drop=True)
    nodes, pieces, auto_keys, host_of, report = build_nodes_and_pieces(lines, official, nodes_2025, official_column)
    element_nrs, kept = number_pieces(lines, pieces, nodes, detail_element_nrs)

    rows = []
    for index, piece in enumerate(pieces):
        row = lines.iloc[piece["parent"]].to_dict()
        original = row["element_nr"] if isinstance(row["element_nr"], str) else None
        actual = (nodes[piece["a"]]["name"], nodes[piece["b"]]["name"])
        parsed = parse_element_nr(element_nrs[index]) if index in kept else None
        # A kept edge keeps the nodes its element_nr names (customer data stays consistent); the nodes at its
        # geometric ends go to knoten_anfang / knoten_ende where they differ
        named = (parsed[0], parsed[1]) if parsed else actual
        differs = pair_key(*named) != pair_key(*actual)
        row.update({
            "element_nr": element_nrs[index],
            "von_knoten": named[0], "bis_knoten": named[1],
            "knoten_anfang": actual[0] if differs else None, "knoten_ende": actual[1] if differs else None,
            "ursprung_element_nr": original if original != element_nrs[index] else None,
            "element_nr_berechnet": row.get("element_nr_berechnet") if index in kept else "ja",
            "geometry": MultiLineString([piece["geometry"]]),
        })
        rows.append(row)
    result = gpd.GeoDataFrame(rows, geometry="geometry", crs=network.crs)
    assert_unique(result)

    report["kept"] = len(kept)
    report["renumbered"] = len(pieces) - len(kept)
    report["renumbered_without_original"] = int(result["ursprung_element_nr"].isna().sum() - len(kept))
    virtual = node_frame(nodes, auto_keys, pieces, lines, network.crs)
    return result, virtual, report


def log_report(report):
    logging.info(
        f"Virtual nodes: {report['auto_nodes']} automatic {report['auto_by_art']}, {report['nodes_2025']} from 2025 "
        f"({report['nodes_2025_matched']} at a snap point of an edge end, {report['nodes_2025_split_edge']} split an edge, "
        f"{len(report['nodes_2025_unused'])} without any edge: {report['nodes_2025_unused']}). "
        f"{report['lines']} lines -> {report['pieces']} edges ({report['split_lines']} lines split), "
        f"element_nr kept for {report['kept']}, newly numbered {report['renumbered']}")
