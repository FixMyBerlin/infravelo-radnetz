#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
auto_nodes.py  (part of step 1, used by merge_networks.py)
--------------------------------------------------------------------
Gives every edge of the merged REN+ a unique, stable element_nr `<von>_<bis>.<nn>` built from its
two end nodes. For that, every edge end must sit on a node:

- official nodes: the Detailnetz nodes (Verbindungspunkte with Knotenpunkt-ID), end within
  OFFICIAL_TOL_M;
- the active ones of the 53 virtual nodes of 2025 (numbers 0001-0053): entries of the Netzanpassungen
  app (KV database), read by merge_networks.py through data/virtuelle_knotenpunkte.py read_registry();
- node proposals (Knotenvorschläge), found here by snapping:
  * on an edge: an edge end (not at an official node) lies on the interior of another REN+ edge
    (within SNAP_TOL_M). The other edge is split there. Ends that meet the same spot on the same edge
    share one proposal.
  * junction: edge ends that meet each other (within SNAP_TOL_M) with no official node and no
    edge passing through share one proposal.
  * dead end: an end that touches nothing gets a proposal.
  A 2025 node within NODE_2025_TOL_M of such a point is that node (no proposal).
  Every 2025 node also splits the edges that pass through it.

  Arms at a proposal point: each line end there counts 1, each line passing through counts 2, and a Detailnetz line
  within DETAIL_ARM_TOL_M (also outside the network) adds its arms unless it runs within ARM_SAME_DEG of an arm already
  counted (over ARM_LOOK_M; the same street). The proposals file has the count in column `arme`; the app accepts
  proposals with arme >= 3 by itself.
  * Exactly two arms, the ends of two different lines (a point in the middle of a line): no proposal; the two lines
    are joined into one (join_two_arm_proposals, repeated for chains). The joined line keeps the row, element_nr and
    direction of the longer member with an element_nr (else of the longer member); the other member's number is
    dropped (and never issued again). Lines with two different non-missing values in a column the network carries per
    edge (all but JOIN_IGNORED_COLUMNS, e.g. strassenname, radverkehrsnetz, strassenklasse, netz_quellen) are not
    joined; a missing value fits any (the joined line takes the other). Nor are lines joined at a proposal that
    non-deleted entries of the Netzanpassungen app name, nor lines whose element_nr they name (app_references;
    merge_networks.py passes them in; an edge correction back at its original does not count), nor where a
    Detailnetz line is a third arm. In all these cases the proposal stays and separates them (logged). The two ends of
    one line (a loop) keep their proposal.
  * Three or more arms: the proposal stays (the app numbers it). Every line passing through it is split there (also at
    a junction, not only on_edge).
  * One arm (dead end): a dead end is never a node and needs no decision; it keeps a technical id P<x>-<y> (art
    dead_end) so the element_nr has two ends, and step 3 does not list it. A loose end within DEAD_END_NODE_TOL_M of
    an official or 2025 node is no dead end: it ends on that node (unless the app names its proposal id).

  Every edge end ends exactly on the point of its node (official, 2025 or proposal; snap_piece_ends: an overshoot is
  cut, else the line is extended), except on edges an edge correction of the app changes (corrected_edges: the app
  holds their geometry; logged). Other references of the app to a proposal do not stop the move.

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

import json
import logging
import math
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

# Two lines that meet at a proposal with nothing else there are joined unless they differ in a column the network
# carries per edge; these columns do not count (numbers, recomputed from the number later, geometry)
JOIN_IGNORED_COLUMNS = {"geometry", "element_nr", "element_nr_berechnet", "ursprung_element_nr", "in_detailnetz"}
# Rounds of joining (a chain of k lines through such points needs about log2(k) rounds)
MAX_JOIN_ROUNDS = 50

# A single loose end (a dead end) this close to an official node or a 2025 node ends on that node, no proposal. Chosen
# from the data (Berlin, 2026-11-19): P384911-5825704 lies 3.57 m from 39600001, where the other edges end; the next
# dead end is 9.6 m from any node.
DEAD_END_NODE_TOL_M = 4.0
# Moving an edge end exactly onto its node cuts at most this much overshoot (the end may be on the node through another
# end within SNAP_TOL_M that is within OFFICIAL_TOL_M of it, or DEAD_END_NODE_TOL_M)
END_SNAP_MAX_CUT_M = 6.0
# Arms at a proposal (see the module docstring): a Detailnetz line within DETAIL_ARM_TOL_M counts as an arm unless it
# runs within ARM_SAME_DEG of an arm already counted, measured over ARM_LOOK_M (the same street)
DETAIL_ARM_TOL_M = 1.5
ARM_LOOK_M = 10.0
ARM_SAME_DEG = 30.0

ELEMENT_NR_PATTERN = re.compile(r"^(.+)_(.+)\.(\d+)$")
PROPOSAL_PREFIX = "P"
# Columns of ren-network/output/virtuelle_knoten_vorschlaege.gpkg
PROPOSAL_COLUMNS = ["id", "art", "arme", "traeger_element_nr", "station_m", "geteilte_element_nr", "kanten", "geometry"]


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
        """How far an end at `point` may move onto `node`: not at all where it meets lines that do not name `node`
        (moving it would tear that junction apart; lines without a number do not count); JUNCTION_TOL_M where at least JUNCTION_MIN_LINES lines meet and
        all name `node`; else `tolerance`."""
        if end_tree is None:
            return tolerance
        meeting = [end_names[int(i)] for i in end_tree.query(point, predicate="dwithin", distance=SNAP_TOL_M)]
        # Lines without element_nr name no node; they follow the moved end (below).
        if not all(node in names for _, names in meeting if names):
            return 0.0
        rows = {row for row, _ in meeting}
        if len(rows) >= JUNCTION_MIN_LINES and tolerance >= NAMED_NODE_TOL_M:
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
            if n in taken or (p, side) in used_ends or distance > allowed(point, n):
                continue
            if not end_at(parts[index][p], side, positions[n]).is_simple:
                continue  # extending would fold the line back on itself
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
                                and moves.get((index, p, 1 - side), (None,))[0] != node
                                and end_at(part, side, node_point).is_simple):
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


def parallel_clusters(geometries, pairs, sources, tolerance=PARALLEL_TOL_M, detail_numbers=None):
    """Groups of lines that are one stretch of street: same unordered node pair (`pairs[i]`), no source in common
    (`sources[i]` a set) and Hausdorff distance at most `tolerance` between every two members (complete linkage, so
    lines 0, 14 and 28 m apart do not chain into one). The closest pairs join first. A group never holds two lines of
    the same source, nor two different Detailnetz numbers (`detail_numbers[i]`, None if the line's number is not in the
    Detailnetz: two carriageways the Detailnetz keeps apart), except lines at most DUPLICATE_TOL_M apart, which are the
    same line twice. Returns a list of index lists with at least two members."""
    detail_numbers = detail_numbers or [None] * len(geometries)
    by_pair = defaultdict(list)
    for index, pair in enumerate(pairs):
        if pair is not None:
            by_pair[pair].append(index)
    clusters = []
    for members in by_pair.values():
        if len(members) < 2:
            continue
        distance = {}
        for k, i in enumerate(members):
            for j in members[k + 1:]:
                distance[i, j] = distance[j, i] = geometries[i].hausdorff_distance(geometries[j])
        candidates = sorted((distance[i, j], i, j) for k, i in enumerate(members) for j in members[k + 1:])

        def compatible(i, j):
            if distance[i, j] <= DUPLICATE_TOL_M:
                return True
            if distance[i, j] > tolerance or sources[i] & sources[j]:
                return False
            return not (detail_numbers[i] and detail_numbers[j] and detail_numbers[i] != detail_numbers[j])

        group = {i: frozenset((i,)) for i in members}
        for pair_distance, i, j in candidates:
            if pair_distance > tolerance:
                break
            if group[i] == group[j]:
                continue
            if not all(compatible(a, b) for a in group[i] for b in group[j]):
                continue
            merged = group[i] | group[j]
            for member in merged:
                group[member] = merged
        clusters.extend(sorted(g) for g in set(group.values()) if len(g) > 1)
    return sorted(clusters)


def _bearing(line, station, forward):
    """Direction in degrees from the point at `station` to the point ARM_LOOK_M along (or back along) the line."""
    target = min(line.length, station + ARM_LOOK_M) if forward else max(0.0, station - ARM_LOOK_M)
    a, b = line.interpolate(station), line.interpolate(target)
    return math.degrees(math.atan2(b.y - a.y, b.x - a.x))


def end_bearing(line, side):
    """Direction in which a line leaves its start (side 0) or its end (side 1)."""
    return _bearing(line, 0.0, True) if side == 0 else _bearing(line, line.length, False)


def line_bearings_at(line, point, tolerance):
    """The arms of `line` at `point`: one per line end within `tolerance`, else two (the line passes)."""
    found = [end_bearing(line, side) for side in (0, 1)
             if shapely.get_point(line, -side).distance(point) <= tolerance]
    if found:
        return found
    station = line.project(point)
    return [_bearing(line, station, True), _bearing(line, station, False)]


def _angle(a, b):
    return abs((a - b + 180.0) % 360.0 - 180.0)


def detail_extra_arms(point, bearings, detail):
    """Arms of Detailnetz lines at `point` that are not one of the network arms (`bearings`, degrees): a Detailnetz
    line within DETAIL_ARM_TOL_M ending there counts once, passing twice, each arm only if it is more than ARM_SAME_DEG
    from every arm counted before. `detail`: (geometries, STRtree) or None."""
    if detail is None:
        return 0
    geoms, tree = detail
    taken, extra = list(bearings), 0
    for index in sorted(int(i) for i in tree.query(point, predicate="dwithin", distance=DETAIL_ARM_TOL_M)):
        for bearing in line_bearings_at(geoms[index], point, DETAIL_ARM_TOL_M):
            if all(_angle(bearing, other) > ARM_SAME_DEG for other in taken):
                taken.append(bearing)
                extra += 1
    return extra


def detail_index(detail_lines):
    """(geometries, STRtree) of the Detailnetz lines (LineString or MultiLineString), or None."""
    if detail_lines is None:
        return None
    geoms = [part for geometry in detail_lines if geometry is not None and not geometry.is_empty
             for part in _parts(geometry)]
    return (geoms, shapely.STRtree(geoms)) if geoms else None


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
    # Other edges passing through a node (crossing of two edges, an edge passing a junction) are split there, too
    for candidate in candidates:
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


def build_nodes_and_pieces(lines, official, nodes_2025, official_column, app_refs=frozenset()):
    """Nodes and split pieces. Returns (nodes, pieces, proposal keys, report). A dead end whose proposal id is in
    `app_refs` stays a proposal even near a node."""
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

    # A dead end within DEAD_END_NODE_TOL_M of an official or 2025 node ends on that node (unless the app uses its id)
    near_keys = official_keys + [f"v:{name}" for name in v_names]
    near_tree = shapely.STRtree(list(official.geometry) + v_points) if near_keys else None
    dead_end_node = {}
    for c, candidate in enumerate(candidates):
        if c in matched_candidate or candidate["art"] != "dead_end" or near_tree is None:
            continue
        if proposal_id(candidate["point"]) in app_refs:
            continue
        near = near_tree.query_nearest(candidate["point"], max_distance=DEAD_END_NODE_TOL_M, all_matches=False)
        if len(near):
            dead_end_node[c] = near_keys[int(near[0])]

    auto_keys = []
    for c, candidate in enumerate(candidates):
        if c in matched_candidate:
            key = f"v:{v_names[matched_candidate[c]]}"
            nodes[key]["art"] = candidate["art"]
            nodes[key]["matched"] = True
        elif c in dead_end_node:
            key = dead_end_node[c]
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

    name_proposals(auto_keys, nodes)

    # Split the edges (snap_piece_ends moves their ends onto the nodes)
    pieces = []
    for key in auto_keys:
        nodes[key]["ends"], nodes[key]["passing"] = [], []
    for line in range(count):
        a, b = end_node[(line, 0)], end_node[(line, 1)]
        for side, key in ((0, a), (1, b)):
            if nodes[key]["kind"] == "proposal":
                nodes[key]["ends"].append((line, side))
        geometry = geoms[line]
        length = geometry.length
        cuts = []
        for station, key in sorted(stops[line]):
            if cuts and station - cuts[-1][0] < MIN_STOP_GAP_M:
                continue
            cuts.append((station, key))
            if nodes[key]["kind"] == "proposal":
                nodes[key]["passing"].append(line)
        chain = [(0.0, a)] + cuts + [(length, b)]
        for (low, start_key), (high, end_key) in zip(chain[:-1], chain[1:]):
            part = geometry if len(chain) == 2 else substring(geometry, low, high)
            pieces.append({"parent": line, "a": start_key, "b": end_key, "geometry": part,
                           "length": part.length, "split": len(chain) > 2})

    report = {
        "lines": count, "pieces": len(pieces), "split_lines": sum(1 for line in stops if stops[line]),
        "proposals": len(auto_keys), "proposals_by_art": pd.Series([nodes[k]["art"] for k in auto_keys]).value_counts().to_dict(),
        "nodes_2025": len(v_names), "nodes_2025_matched": len(matched_node),
        "nodes_2025_split_edge": sum(1 for v in v_names if any(key == f"v:{v}" for line in stops for _, key in stops[line])),
        "nodes_2025_unused": [v for v in v_names if not any(key == f"v:{v}" for line in stops for _, key in stops[line])
                              and not any(k == f"v:{v}" for k in end_node.values())],
        "dead_ends_on_node": sorted({nodes[key]["name"] for key in dead_end_node.values()}),
    }
    return nodes, pieces, auto_keys, report


def _missing(value):
    return value is None or (isinstance(value, str) and value == "") or (not isinstance(value, str) and pd.isna(value))


def _compatible(a, b):
    """Two values of a column fit when they are equal or one is missing (the joined line takes the other)."""
    return _missing(a) or _missing(b) or a == b


# A proposal id inside the data of an app entry (also as `k:P...` or inside an element_nr)
PROPOSAL_ID_IN_TEXT = re.compile(rf"(?<![A-Za-z0-9]){PROPOSAL_PREFIX}\d+-\d+(?:-\d+)?(?![0-9])")
# An element_nr inside the data of an app entry (kante.ref, `detailnetz:<element_nr>@...`, ...)
ELEMENT_NR_IN_TEXT = re.compile(r"(?<![A-Za-z0-9.-])[A-Za-z0-9-]+_[A-Za-z0-9-]+\.\d+(?![0-9])")


def is_noop_correction(data):
    """An edge_correction whose state is the original (coordinates equal original_coordinates and attribute empty, e.g.
    reset with `zurueckgesetzt`): it changes nothing, so nothing depends on it. An attribute set to null (direction
    cleared) is a change."""
    if data.get("kind") != "edge_correction" or data.get("attribute"):
        return False
    return data.get("coordinates") is not None and data.get("coordinates") == data.get("original_coordinates")


def corrected_edges(entries):
    """element_nr of the edges that non-deleted edge corrections of the app change (kante.ref without `#n`, and
    kante.element_nr); corrections back at the original (is_noop_correction) do not count. Only these edges keep their
    ends where they are (snap_piece_ends): the app holds their geometry."""
    found = set()
    for entry in entries or []:
        data = entry.get("data") or {}
        if data.get("kind") != "edge_correction" or data.get("geloescht") or is_noop_correction(data):
            continue
        kante = data.get("kante") or {}
        for value in (str(kante.get("ref") or "").split("#")[0], kante.get("element_nr")):
            if value:
                found.add(value)
    return found


# Kinds of app entries that depend on no proposal and no element_nr of step 1
IGNORED_APP_KINDS = ("route_check", "bridge_check")


def app_references(entries):
    """Proposal ids and element_nr that non-deleted entries of the Netzanpassungen app depend on: every `P<x>-<y>`
    and every `<von>_<bis>.<nn>` in the JSON of an entry's data (vorschlag_id of a virtual_node, kante.ref,
    traeger.ref, the kanten keys of a section_assignment, von/bis of a new_edge, ...). An edge correction that changes
    nothing (is_noop_correction) does not count."""
    found = set()
    for entry in entries or []:
        data = entry.get("data") or {}
        # An OK of the route check depends on nothing: it lapses by itself when the edges of its section change.
        # The same holds for the check of a node at a bridge or tunnel (bridge_check): it joins nothing at a proposal.
        if not data.get("geloescht") and data.get("kind") not in IGNORED_APP_KINDS and not is_noop_correction(data):
            text = json.dumps(data, ensure_ascii=False)
            found |= set(PROPOSAL_ID_IN_TEXT.findall(text)) | set(ELEMENT_NR_IN_TEXT.findall(text))
    return found


def find_joins(lines, nodes, proposal_keys, app_refs=frozenset(), detail=None):
    """Proposals where exactly two line ends of two different lines meet and nothing passes through. Returns
    (joins [(proposal key, (line, side), (line, side))], refused [(proposal name, differing columns)], skipped
    [proposal names]): two lines with two different non-missing values in a column the network carries per edge (all
    but JOIN_IGNORED_COLUMNS) are not joined, nor at a proposal in `app_refs` (entries of the app depend on
    it), nor where a Detailnetz line is a third arm (detail_extra_arms; their names in `crossed`); the proposal stays
    and separates them. Each line takes part in at most one join per call. Returns (joins, refused, skipped, crossed)."""
    columns = [c for c in lines.columns if c not in JOIN_IGNORED_COLUMNS]
    joins, refused, skipped, crossed, used = [], [], [], [], set()
    geoms = lines.geometry.to_numpy()
    for key in proposal_keys:
        node = nodes[key]
        ends = node.get("ends", [])
        if len(ends) != 2 or node.get("passing") or ends[0][0] == ends[1][0]:
            continue  # a dead end, three or more arms, or the two ends of one line (a loop)
        (i, _), (j, _) = ends
        if detail_extra_arms(node["point"], [end_bearing(geoms[line], side) for line, side in ends], detail):
            crossed.append(node["name"])
            continue
        differing = [c for c in columns if not _compatible(lines.at[i, c], lines.at[j, c])]
        if differing:
            refused.append((node["name"], differing))
        elif node["name"] in app_refs or {lines.at[i, "element_nr"], lines.at[j, "element_nr"]} & app_refs:
            skipped.append(node["name"])
        elif i not in used and j not in used:
            joins.append((key, ends[0], ends[1]))
            used |= {i, j}
    return joins, refused, skipped, crossed


def join_lines(lines, joins, nodes):
    """Each join (proposal key, (line, side), (line, side)) makes one line of the two, through the proposal point.
    The joined line keeps the row (and so the element_nr) of the longer member with an element_nr, else of the longer
    member, and that member's direction. Returns (new lines, element_nr of the other members that are dropped)."""
    geoms = lines.geometry.to_numpy()
    records = lines.to_dict("records")
    joined_rows, removed, dropped_numbers = [], set(), []
    for key, first, second in joins:
        point = nodes[key]["point"]
        members = [first, second]

        def rank(member):
            element_nr = records[member[0]]["element_nr"]
            return (isinstance(element_nr, str) and element_nr != "", geoms[member[0]].length)

        (owner, owner_side), (other, other_side) = sorted(members, key=rank, reverse=True)
        own = end_at(geoms[owner], owner_side, point, max_cut_m=SNAP_TOL_M)
        rest = geoms[other] if other_side != owner_side else shapely.reverse(geoms[other])
        # `rest` now ends at the point on the side opposite to the owner's (start if the owner ends there)
        rest = end_at(rest, 1 - owner_side, point, max_cut_m=SNAP_TOL_M)
        coords = (list(own.coords) + list(rest.coords)[1:] if owner_side == 1
                  else list(rest.coords) + list(own.coords)[1:])
        row = dict(records[owner])
        for column in row:
            if column not in JOIN_IGNORED_COLUMNS and _missing(row[column]):
                row[column] = records[other][column]
        row["geometry"] = shapely.LineString(coords)
        joined_rows.append(row)
        removed |= {owner, other}
        number = records[other]["element_nr"]
        if isinstance(number, str) and number != "" and number != row["element_nr"]:
            dropped_numbers.append(number)
    kept_rows = [record for index, record in enumerate(records) if index not in removed]
    result = gpd.GeoDataFrame(kept_rows + joined_rows, columns=lines.columns, geometry="geometry", crs=lines.crs)
    return result, dropped_numbers


def join_two_arm_proposals(lines, official, nodes_2025, official_column, app_refs=frozenset(), detail=None):
    """Joins the lines at every proposal where exactly two line ends of two different lines meet with nothing passing
    through (find_joins), repeated until none is left (chains of such points). Returns (lines, element_nr dropped by
    joins, number of joins, refused [(proposal name, differing columns)], skipped [proposal names used by the app],
    crossed [proposal names where a Detailnetz line is a third arm]), the lists as of the last round."""
    dropped, count, refused, skipped, crossed = [], 0, [], [], []
    for _ in range(MAX_JOIN_ROUNDS):
        nodes, _, proposal_keys, _ = build_nodes_and_pieces(lines, official, nodes_2025, official_column, app_refs)
        joins, refused, skipped, crossed = find_joins(lines, nodes, proposal_keys, app_refs, detail)
        if not joins:
            break
        lines, numbers = join_lines(lines, joins, nodes)
        dropped += numbers
        count += len(joins)
    return lines, dropped, count, refused, skipped, crossed


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


def proposal_arms(nodes, proposal_keys, pieces, detail=None):
    """Arms per proposal key: every edge end there (a line passing through is split there, so it has two) plus the
    Detailnetz arms that are not one of them (detail_extra_arms)."""
    bearings = defaultdict(list)
    for piece in pieces:
        for side, key in ((0, piece["a"]), (1, piece["b"])):
            bearings[key].append(end_bearing(piece["geometry"], side))
    return {key: len(bearings[key]) + detail_extra_arms(nodes[key]["point"], bearings[key], detail)
            for key in proposal_keys}


def snap_piece_ends(pieces, nodes, element_nrs, lines, corrected=frozenset()):
    """Moves every piece end onto the point of its node (end_at: an overshoot is cut, else the line is extended), except
    for pieces whose element_nr, or the element_nr of their line before this step, is in `corrected` (edges an edge
    correction of the app changes, corrected_edges: the app holds their geometry). Other references of the app (a
    proposal id named by a virtual node, a drawn edge, a section assignment) do not stop the move. Returns (number of ends moved, [(element_nr, node name, distance m)] left off their node)."""
    moved, left = 0, []
    for index, piece in enumerate(pieces):
        original = lines["element_nr"].iloc[piece["parent"]]
        protected = element_nrs[index] in corrected or (isinstance(original, str) and original in corrected)
        part = piece["geometry"]
        for side, key in ((0, piece["a"]), (1, piece["b"])):
            point = nodes[key]["point"]
            distance = shapely.get_point(part, -side).distance(point)
            if distance == 0:
                continue
            if protected:
                left.append((element_nrs[index], nodes[key]["name"], round(distance, 2)))
                continue
            part = end_at(part, side, point, max_cut_m=END_SNAP_MAX_CUT_M)
            moved += 1
        piece["geometry"], piece["length"] = part, part.length
    return moved, left


def proposal_frame(nodes, proposal_keys, pieces, element_nrs, lines, crs, arms=None):
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
            "id": node["name"], "art": node["art"], "arme": (arms or {}).get(key),
            "traeger_element_nr": edges[0][0] if edges else None,
            "station_m": round(edges[0][1], 2) if edges else None,
            "geteilte_element_nr": split if isinstance(split, str) else None,
            "kanten": "; ".join(element_nr for element_nr, _ in edges),
            "geometry": node["point"],
        })
    frame = gpd.GeoDataFrame(rows, columns=PROPOSAL_COLUMNS, geometry="geometry", crs=crs)
    frame["arme"] = frame["arme"].astype("Int64")
    return frame.sort_values("id").reset_index(drop=True)


def snap_and_number(network, official, nodes_2025, detail_element_nrs, official_column, combine=None,
                    parallel_tolerance=PARALLEL_TOL_M, app_refs=frozenset(), detail_lines=None, corrected=frozenset()):
    """The whole sub-step: `network` (one LineString per row, `element_nr` possibly empty) ->
    (network with unique element_nr, von_knoten, bis_knoten, ursprung_element_nr; node proposals; report).

    With `combine`, edges of different sources (`netz_quellen`, `;`-separated) between the same two end nodes within
    `parallel_tolerance` (Hausdorff) become one edge (see merge_parallel_pieces); `combine(rows, owner)` merges their
    rows. Lines are not joined at a proposal in `app_refs`, nor when one's element_nr is in it (entries of the app
    depend on them, see app_references). `detail_lines`: Detailnetz geometries; their arms count at proposals (no
    join where one is a third arm; column `arme`)."""
    detail = detail_index(detail_lines)
    lines = network.reset_index(drop=True)
    lines, dropped_numbers, joined, refused, skipped, crossed = join_two_arm_proposals(
        lines, official, nodes_2025, official_column, app_refs, detail)
    nodes, pieces, proposal_keys, report = build_nodes_and_pieces(lines, official, nodes_2025, official_column, app_refs)
    report["joined"], report["join_refused"], report["join_skipped_app"] = joined, refused, skipped
    report["join_detail_arm"] = crossed
    element_nrs, kept = number_pieces(lines, pieces, nodes, list(detail_element_nrs) + dropped_numbers)
    report["ends_moved"], report["ends_left_app"] = snap_piece_ends(pieces, nodes, element_nrs, lines, corrected)

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
    dropped = (merge_parallel_pieces(rows, pieces, element_nrs, kept, combine, parallel_tolerance,
                                     frozenset(detail_element_nrs)) if combine else set())
    remaining = [index for index in range(len(pieces)) if index not in dropped]
    kept = kept - dropped
    result = gpd.GeoDataFrame([rows[i] for i in remaining], geometry="geometry", crs=network.crs)
    assert_unique(result)

    report["merged_parallel"] = len(dropped)
    report["pieces"] = len(remaining)
    report["kept"] = len(kept)
    report["renumbered"] = len(remaining) - len(kept)
    report["renumbered_without_original"] = int(result["ursprung_element_nr"].isna().sum() - len(kept))
    remaining_pieces = [pieces[i] for i in remaining]
    arms = proposal_arms(nodes, proposal_keys, remaining_pieces, detail)
    proposals = proposal_frame(nodes, proposal_keys, remaining_pieces, [element_nrs[i] for i in remaining],
                               lines, network.crs, arms)
    report["proposals_by_arms"] = proposals.groupby(["art", "arme"]).size().to_dict() if len(proposals) else {}
    return result, proposals, report


def merge_parallel_pieces(rows, pieces, element_nrs, kept, combine, tolerance=PARALLEL_TOL_M,
                          detail_element_nrs=frozenset()):
    """Edges of different sources between the same two end nodes (after splitting) within `tolerance` become one
    (e.g. a Radverkehrsnetz line split at two 2025 nodes and a Radschnellverbindung without element_nr between the same
    nodes). The surviving edge keeps a number the Detailnetz has, else the number of a member that kept its element_nr,
    else the lowest `nn`; geometry
    and attributes come from `combine(member rows, owner position)`. Changes `rows` in place, returns the dropped piece
    indexes. Their numbers are not issued again: they were counted before."""
    sources = [set(str(row.get("netz_quellen") or "").split(";")) - {""} for row in rows]
    pairs = [pair_key(piece["a"], piece["b"]) if sources[i] else None for i, piece in enumerate(pieces)]
    dropped = set()
    detail = [nr if nr in detail_element_nrs else None for nr in element_nrs]
    for cluster in parallel_clusters([piece["geometry"] for piece in pieces], pairs, sources, tolerance, detail):
        owner = min(cluster, key=lambda i: (detail[i] is None, i not in kept, parse_element_nr(element_nrs[i])[2],
                                            element_nrs[i]))
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
    refused = report.get("join_refused", [])
    logging.info(f"Lines joined at a point where only they meet (no proposal there): {report.get('joined', 0)}; "
                 f"not joined because they differ in attributes (proposal kept): {len(refused)}"
                 + (f", e.g. {refused[:5]}" if refused else ""))
    skipped = report.get("join_skipped_app", [])
    logging.info(f"Not joined because entries of the Netzanpassungen app use the proposal or one of the lines (proposal kept): "
                 f"{len(skipped)} {sorted(skipped)}")
    crossed = report.get("join_detail_arm", [])
    logging.info(f"Not joined because a Detailnetz line outside the network is a third arm (proposal kept): "
                 f"{len(crossed)} {sorted(crossed)}")
    left = report.get("ends_left_app", [])
    logging.info(f"Edge ends moved exactly onto their node: {report.get('ends_moved', 0)}; left off their node because "
                 f"the app corrected the edge: {len(left)} {left}")
    logging.info(f"Dead ends within {DEAD_END_NODE_TOL_M:g} m of a node end on it: {report.get('dead_ends_on_node', [])}; "
                 f"proposals by art and arms: {report.get('proposals_by_arms', {})}")
