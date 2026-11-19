#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
auto_nodes.py  (part of step 1, used by merge_networks.py)
--------------------------------------------------------------------
Gives every edge of the merged REN+ a unique, stable element_nr `<von>_<bis>.<nn>` built from its
two end nodes. For that, every edge end must sit on a node:

- official nodes: the Detailnetz nodes (Verbindungspunkte with Knotenpunkt-ID), end within
  OFFICIAL_TOL_M;
- the 53 virtual nodes of 2025 (data/Virtuelle-Knotenpunkte.gpkg, numbers 0001-0053): frozen input like
  the Detailnetz nodes;
- node proposals (Knotenvorschläge), found here by snapping:
  * on an edge: an edge end (not at an official node) lies on the interior of another REN+ edge
    (within SNAP_TOL_M). The other edge is split there. Ends that meet the same spot on the same edge
    share one proposal.
  * junction: edge ends that meet each other (within SNAP_TOL_M) with no official node and no
    edge passing through share one proposal.
  * dead end: an end that touches nothing gets a proposal.
  A 2025 node within NODE_2025_TOL_M of such a point is that node (no proposal).
  Every 2025 node also splits the edges that pass through it.

Step 1 gives no node names or numbers of its own (numbers are given only in the Netzanpassungen app). A
proposal is named by its position: `P<x>-<y>` with the coordinates in EPSG:25833 rounded to whole metres
(e.g. P391234-5818765), stable as long as the network does not change at that spot. When the app accepts
a proposal it gives it a number; step 3 replaces the proposal id by that number.

Numbering: an existing element_nr is never changed unless it has to be. An edge keeps its element_nr
when it was not split (even if an end is off its node) and it is the longest edge with that element_nr.
All other edges (split pieces, extra separate parts of a multi-part edge, edges without element_nr) get
`<von>_<bis>.<nn>`, `nn` counting per unordered node pair on top of the highest number ever used by the
Detailnetz and by REN+ before this step (dropped numbers included, so a number is never issued twice).
Direction in the name is the direction of the line. The element_nr before the change stays in
`ursprung_element_nr`. `von_knoten`/`bis_knoten` of an edge that keeps its element_nr are the nodes that
number names; where its geometric ends sit on other nodes, those are in `knoten_anfang`/`knoten_ende`
(else empty).

Before that, merge_networks.py moves line ends that lie within NAMED_NODE_TOL_M of the official node their
element_nr names onto that node (snap_ends_to_named_nodes), so they do not become proposals, and merges lines of
different sources between the same two nodes (parallel_clusters). After splitting, edges of different sources between
the same two end nodes are merged once more (merge_parallel_pieces, e.g. a numbered line split at two 2025 nodes and a
line without element_nr between them); the surviving edge keeps a kept number, else the lowest `nn`.

Nodes set in the app are not part of this step; step 3 adds them (netzanpassungen/apply_app_result.py).
"""

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
# An edge end this close to an official node its element_nr names ends on that node (the line is extended to it,
# an overshoot is cut). Chosen from the data (Berlin, 2026-11-19): of the line ends more than OFFICIAL_TOL_M from
# every official node, 95 lie within 10 m of a node their element_nr names, 126 within 15 m, 138 within 20 m, the
# rest farther (up to several km). Example: Radverkehrsnetz 27570001_28560007.01 ends 10.1 m before 27570001.
NAMED_NODE_TOL_M = 15.0
# Lines of different sources between the same two nodes within this Hausdorff distance are one edge. Chosen from the
# data (Berlin, 2026-11-19): in ren_netz_roh.gpkg before this rule, 149 node pairs had lines of different sources;
# 145 of them lie within 13.8 m, then 16.1 m (twice), 22.2 and 35.3 m. At the merge (after NAMED_NODE_TOL_M) 149 of
# 154 such pairs lie within 15 m (134 within 5 m), the next at 16.1 m (an end 16.1 m from its node). Lines of the
# same source between the same nodes stay separate (real parallel edges).
PARALLEL_TOL_M = 15.0
# A junction of at least JUNCTION_MIN_LINES line ends (within SNAP_TOL_M) whose lines all name the same official node
# moves onto it from up to this distance. Example: the Radverkehrsnetz meets 16.1 m north of 57420036 (Richterstraße),
# where Hauptstraßennetz and Detailnetz meet on the node. A plain 20 m for every end would also move single ends in
# tangled spots (57480005/57480022) and make them worse.
JUNCTION_TOL_M = 20.0
JUNCTION_MIN_LINES = 3
# Lines between the same two nodes within this Hausdorff distance are one edge even if they share a source. Chosen
# from the data (Berlin, 2026-11-19): after the rules above, 7 node pairs had such lines, 5 of them exactly on top of
# each other (mostly a Radschnellverbindung line without element_nr lying on an edge that already includes it), the
# farthest 1.6 m apart; the next pair of the same source is more than 15 m apart (a real parallel edge).
DUPLICATE_TOL_M = 2.0

ELEMENT_NR_PATTERN = re.compile(r"^(.+)_(.+)\.(\d+)$")
PROPOSAL_PREFIX = "P"
# Columns of ren-network/output/virtuelle_knoten_vorschlaege.gpkg
PROPOSAL_COLUMNS = ["id", "art", "traeger_element_nr", "station_m", "geteilte_element_nr", "kanten", "geometry"]


class Nodes:
    """All nodes with a key, kind (official | 2025 | proposal), name and position."""

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


def _parts(geometry):
    return list(geometry.geoms) if geometry.geom_type == "MultiLineString" else [geometry]


def end_at(line, side, point, max_cut_m=JUNCTION_TOL_M):
    """`line` with its start (side 0) or end (side 1) moved onto `point`: a tail beyond the point's projection
    (overshoot, at most `max_cut_m`) is cut, then the point is added as the new end vertex."""
    station = line.project(point)
    if side == 1:
        if 0 < station < line.length and line.length - station <= max_cut_m:
            line = substring(line, 0, station)
        coords = list(line.coords) + [(point.x, point.y)]
    else:
        if 0 < station < line.length and station <= max_cut_m:
            line = substring(line, station, line.length)
        coords = [(point.x, point.y)] + list(line.coords)
    deduped = [coords[0]] + [c for prev, c in zip(coords, coords[1:]) if c != prev]
    return shapely.LineString(deduped)


def snap_ends_to_named_nodes(network, official, official_column, nodes_2025=None, tolerance=NAMED_NODE_TOL_M):
    """Moves every line end that is not on a node (farther than OFFICIAL_TOL_M from every official node and than
    NODE_2025_TOL_M from every 2025 node in `nodes_2025`) but within `tolerance` of
    an official node its element_nr `<von>_<bis>.<nn>` names onto that node. Each named node takes at most one end of
    a row, the closest, and none if another end of the row already sits on it. Ends of other rows that met a moved end
    (within SNAP_TOL_M of its old position, also not on a node) move with it, unless the other end of their line is
    already at that node. Without this, such an end
    becomes a node proposal (or splits the edge it lies on) although its number says where it belongs.

    `network`: GeoDataFrame with `element_nr` and LineString or MultiLineString geometry. Returns (copy with the
    geometry changed, list of (element_nr, node id, distance in m) of the moved ends)."""
    positions = dict(zip(official[official_column].astype(str), official.geometry))
    official_tree = shapely.STRtree(official.geometry.to_numpy())

    tree_2025 = shapely.STRtree(nodes_2025.geometry.to_numpy()) if nodes_2025 is not None and len(nodes_2025) else None

    def on_official(point):
        """On an official node or a 2025 node: such an end stays where it is."""
        if len(official_tree.query(point, predicate="dwithin", distance=OFFICIAL_TOL_M)):
            return True
        return tree_2025 is not None and len(tree_2025.query(point, predicate="dwithin", distance=NODE_2025_TOL_M)) > 0

    parts = {index: _parts(geometry) for index, geometry in network.geometry.items()}

    # All line ends with the nodes their element_nr names, to find junctions whose lines agree on one node
    end_points, end_names = [], []
    for index, element_nr in network["element_nr"].items():
        parsed = parse_element_nr(element_nr)
        names = set(parsed[:2]) if parsed else set()
        for part in parts[index]:
            for side in (0, 1):
                end_points.append(shapely.get_point(part, -side))
                end_names.append((index, names))
    end_tree = shapely.STRtree(end_points) if end_points else None

    def allowed(point, node):
        """JUNCTION_TOL_M where at least JUNCTION_MIN_LINES lines meet and all name `node`, else `tolerance`."""
        if end_tree is None or tolerance < NAMED_NODE_TOL_M:
            return tolerance
        meeting = [end_names[int(i)] for i in end_tree.query(point, predicate="dwithin", distance=SNAP_TOL_M)]
        rows = {row for row, _ in meeting}
        if len(rows) >= JUNCTION_MIN_LINES and all(node in names for _, names in meeting):
            return max(tolerance, JUNCTION_TOL_M)
        return tolerance

    moves = {}  # (row, part, side) -> (node id, point)
    moved = []
    for index, element_nr in network["element_nr"].items():
        parsed = parse_element_nr(element_nr)
        named = [n for n in dict.fromkeys(parsed[:2]) if n in positions] if parsed else []
        if not named:
            continue
        ends = [(p, side, shapely.get_point(part, -side)) for p, part in enumerate(parts[index]) for side in (0, 1)]
        taken = {n for n in named if any(point.distance(positions[n]) <= OFFICIAL_TOL_M for _, _, point in ends)}
        options = sorted((point.distance(positions[n]), p, side, n, point) for p, side, point in ends
                         for n in named if n not in taken and not on_official(point))
        used_ends = set()
        for distance, p, side, n, point in options:
            if n in taken or (p, side) in used_ends or distance > tolerance and distance > allowed(point, n):
                continue
            moves[(index, p, side)] = (n, positions[n])
            moved.append((element_nr, n, distance))
            taken.add(n)
            used_ends.add((p, side))

    # Ends of other rows that met a moved end at its old position follow it to the node
    old_points = [shapely.get_point(parts[index][p], -side) for index, p, side in moves]
    targets = list(moves.values())
    if old_points:
        old_tree = shapely.STRtree(old_points)
        for index in network.index:
            for p, part in enumerate(parts[index]):
                for side in (0, 1):
                    if (index, p, side) in moves:
                        continue
                    point = shapely.get_point(part, -side)
                    near = old_tree.query_nearest(point, max_distance=SNAP_TOL_M, all_matches=False)
                    if len(near) and not on_official(point):
                        node, node_point = targets[int(near[0])]
                        other = shapely.get_point(part, -(1 - side))
                        if (point.distance(node_point) <= max(tolerance, JUNCTION_TOL_M) + SNAP_TOL_M
                                and other.distance(node_point) > OFFICIAL_TOL_M
                                and moves.get((index, p, 1 - side), (None,))[0] != node):
                            moves[(index, p, side)] = (node, node_point)
                            moved.append((network.at[index, "element_nr"], node, point.distance(node_point)))

    network = network.copy()
    for index in {index for index, _, _ in moves}:
        new_parts = list(parts[index])
        for p in range(len(new_parts)):
            for side in (0, 1):
                if (index, p, side) in moves:
                    new_parts[p] = end_at(new_parts[p], side, moves[(index, p, side)][1])
        geometry = network.at[index, "geometry"]
        network.at[index, "geometry"] = (shapely.MultiLineString(new_parts) if geometry.geom_type == "MultiLineString"
                                         else new_parts[0])
    return network, moved


def parallel_clusters(geometries, pairs, sources, tolerance=PARALLEL_TOL_M):
    """Groups of lines that are one stretch of street: same unordered node pair (`pairs[i]`), no source in common
    (`sources[i]` a set) and Hausdorff distance at most `tolerance`. The closest pairs join first; a group never holds
    two lines of the same source, except lines at most DUPLICATE_TOL_M apart, which are the same line twice.
    Returns a list of index lists with at least two members."""
    by_pair = defaultdict(list)
    for index, pair in enumerate(pairs):
        if pair is not None:
            by_pair[pair].append(index)
    clusters = []
    for members in by_pair.values():
        if len(members) < 2:
            continue
        candidates = sorted(
            (geometries[i].hausdorff_distance(geometries[j]), i, j)
            for k, i in enumerate(members) for j in members[k + 1:])
        group = {i: {i} for i in members}
        group_sources = {i: set(sources[i]) for i in members}
        for distance, i, j in candidates:
            if distance > tolerance:
                break
            a, b = min(group[i]), min(group[j])
            if a == b or (group_sources[a] & group_sources[b] and distance > DUPLICATE_TOL_M):
                continue
            root, other = min(a, b), max(a, b)
            merged = group[root] | group[other]
            group_sources[root] = group_sources[root] | group_sources[other]
            for member in merged:
                group[member] = merged
        clusters.extend(sorted(g) for g in {id(g): g for g in group.values()}.values() if len(g) > 1)
    return clusters


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


def proposal_id(point):
    """`P<x>-<y>` with the coordinates in EPSG:25833 rounded to whole metres."""
    return f"{PROPOSAL_PREFIX}{int(round(point.x))}-{int(round(point.y))}"


def is_proposal(node_id):
    """True for a proposal id of step 1 (`P<x>-<y>`)."""
    return isinstance(node_id, str) and re.match(rf"^{PROPOSAL_PREFIX}\d+-\d+(-\d+)?$", node_id) is not None


def name_proposals(proposal_keys, nodes):
    """Gives every proposal its id. Two proposals in the same square metre (rare) get `-2`, `-3`, ... on the
    later one, sorted by position."""
    taken = set()
    for key in sorted(proposal_keys, key=lambda k: (nodes[k]["point"].x, nodes[k]["point"].y)):
        name = proposal_id(nodes[key]["point"])
        if name in taken:
            count = 2
            while f"{name}-{count}" in taken:
                count += 1
            logging.warning(f"Two node proposals round to {name}; the second is {name}-{count}")
            name = f"{name}-{count}"
        nodes[key]["name"] = name
        taken.add(name)


def build_nodes_and_pieces(lines, official, nodes_2025, official_column):
    """Nodes and split pieces. Returns (nodes, pieces, proposal keys, report)."""
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
            nodes.add(key, "proposal", None, candidate["point"], art=candidate["art"],
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

    name_proposals(auto_keys, nodes)

    report = {
        "lines": count, "pieces": len(pieces), "split_lines": sum(1 for line in stops if stops[line]),
        "proposals": len(auto_keys), "proposals_by_art": pd.Series([nodes[k]["art"] for k in auto_keys]).value_counts().to_dict(),
        "nodes_2025": len(v_names), "nodes_2025_matched": len(matched_node),
        "nodes_2025_split_edge": sum(1 for v in v_names if any(key == f"v:{v}" for line in stops for _, key in stops[line])),
        "nodes_2025_unused": [v for v in v_names if not any(key == f"v:{v}" for line in stops for _, key in stops[line])
                              and not any(k == f"v:{v}" for k in end_node.values())],
    }
    return nodes, pieces, auto_keys, report


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


def proposal_frame(nodes, proposal_keys, pieces, element_nrs, lines, crs):
    """The node proposals: id, art, an edge of the result that ends there (`traeger_element_nr`, station at that
    end), the element_nr of the edge split there (`geteilte_element_nr`, on_edge only) and all edges ending there."""
    ending = defaultdict(list)  # node key -> [(element_nr, station)]
    for index, piece in enumerate(pieces):
        ending[piece["a"]].append((element_nrs[index], 0.0))
        ending[piece["b"]].append((element_nrs[index], piece["length"]))
    rows = []
    for key in proposal_keys:
        node = nodes[key]
        edges = sorted(ending.get(key, []))
        host = node["hosts"][0] if node.get("hosts") else None
        split = lines["element_nr"].iloc[host[0]] if host else None
        rows.append({
            "id": node["name"], "art": node["art"],
            "traeger_element_nr": edges[0][0] if edges else None,
            "station_m": round(edges[0][1], 2) if edges else None,
            "geteilte_element_nr": split if isinstance(split, str) else None,
            "kanten": "; ".join(element_nr for element_nr, _ in edges),
            "geometry": node["point"],
        })
    frame = gpd.GeoDataFrame(rows, columns=PROPOSAL_COLUMNS, geometry="geometry", crs=crs)
    return frame.sort_values("id").reset_index(drop=True)


def snap_and_number(network, official, nodes_2025, detail_element_nrs, official_column, combine=None,
                    parallel_tolerance=PARALLEL_TOL_M):
    """The whole sub-step: `network` (one LineString per row, `element_nr` possibly empty) ->
    (network with unique element_nr, von_knoten, bis_knoten, ursprung_element_nr; node proposals; report).

    With `combine`, edges of different sources (`netz_quellen`, `;`-separated) between the same two end nodes within
    `parallel_tolerance` (Hausdorff) become one edge (see merge_parallel_pieces); `combine(rows, owner)` merges their
    rows."""
    lines = network.reset_index(drop=True)
    nodes, pieces, proposal_keys, report = build_nodes_and_pieces(lines, official, nodes_2025, official_column)
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
    dropped = merge_parallel_pieces(rows, pieces, element_nrs, kept, combine, parallel_tolerance) if combine else set()
    remaining = [index for index in range(len(pieces)) if index not in dropped]
    kept = kept - dropped
    result = gpd.GeoDataFrame([rows[i] for i in remaining], geometry="geometry", crs=network.crs)
    assert_unique(result)

    report["merged_parallel"] = len(dropped)
    report["pieces"] = len(remaining)
    report["kept"] = len(kept)
    report["renumbered"] = len(remaining) - len(kept)
    report["renumbered_without_original"] = int(result["ursprung_element_nr"].isna().sum() - len(kept))
    proposals = proposal_frame(nodes, proposal_keys, [pieces[i] for i in remaining], [element_nrs[i] for i in remaining],
                               lines, network.crs)
    return result, proposals, report


def merge_parallel_pieces(rows, pieces, element_nrs, kept, combine, tolerance=PARALLEL_TOL_M):
    """Edges of different sources between the same two end nodes (after splitting) within `tolerance` become one
    (e.g. a Radverkehrsnetz line split at two 2025 nodes and a Radschnellverbindung without element_nr between the same
    nodes). The surviving edge keeps the number of a member that kept its element_nr, else the lowest `nn`; geometry
    and attributes come from `combine(member rows, owner position)`. Changes `rows` in place, returns the dropped piece
    indexes. Their numbers are not issued again: they were counted before."""
    sources = [set(str(row.get("netz_quellen") or "").split(";")) - {""} for row in rows]
    pairs = [pair_key(piece["a"], piece["b"]) if sources[i] else None for i, piece in enumerate(pieces)]
    dropped = set()
    for cluster in parallel_clusters([piece["geometry"] for piece in pieces], pairs, sources, tolerance):
        owner = min(cluster, key=lambda i: (i not in kept, parse_element_nr(element_nrs[i])[2], element_nrs[i]))
        rows[owner] = combine([rows[i] for i in cluster], cluster.index(owner))
        pieces[owner]["length"] = rows[owner]["geometry"].length
        dropped |= set(cluster) - {owner}
    return dropped


def log_report(report):
    logging.info(
        f"Node proposals: {report['proposals']} {report['proposals_by_art']}, virtual nodes of 2025: {report['nodes_2025']} "
        f"({report['nodes_2025_matched']} at a snap point of an edge end, {report['nodes_2025_split_edge']} split an edge, "
        f"{len(report['nodes_2025_unused'])} without any edge: {report['nodes_2025_unused']}). "
        f"{report['lines']} lines -> {report['pieces']} edges ({report['split_lines']} lines split), "
        f"element_nr kept for {report['kept']}, newly numbered {report['renumbered']}, "
        f"{report.get('merged_parallel', 0)} edges merged into a parallel edge of another source between the same nodes")
