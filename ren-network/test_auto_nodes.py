#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Self-test for auto_nodes.py (automatic virtual nodes and unique element_nr in step 1) with an invented network.

    .venv/bin/python ren-network/test_auto_nodes.py

Network (metres): official nodes 1 (0,0), 2 (200,0), 3 (100,100), 4 (0,300), 5 (300,0).
A 1-2 along y=0 (will be split), T arm from node 3 down to (100,1.5) (T on A, no element_nr),
C from node 2 east to (290,0) (end 10 m short of node 5: dead end), D and D2 two parts with the same
element_nr 4_5.01 that meet where nothing else is (they are joined into one edge), E 1-4 with a correct element_nr, F a loop-free
edge whose element_nr names other nodes than its ends.
A 2025 node (number 0007) lies 0.5 m beside A at x=100 and is the T node; without it the T node is a
proposal P<x>-<y>.
"""

import sys
import unittest
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, Point

sys.path.append(str(Path(__file__).resolve().parent))

import auto_nodes as an  # noqa: E402

X0, Y0 = 392000.0, 5815000.0
CRS = "EPSG:25833"
ID = "Knotenpunkt-ID"


def line(*points):
    return LineString([(X0 + x, Y0 + y) for x, y in points])


def point(x, y):
    return Point(X0 + x, Y0 + y)


def build(extra_2025=True):
    official = gpd.GeoDataFrame({ID: ["1", "2", "3", "4", "5"]},
                                geometry=[point(0, 0), point(200, 0), point(100, 100), point(0, 300), point(300, 0)], crs=CRS)
    rows = [
        ("1_2.01", line((0, 0), (200, 0))),                          # A: T node in the middle
        (None, line((100, 100), (100, 1.5))),                        # T arm
        ("2_5.01", line((200, 0), (290, 0))),                        # C: dead end
        ("4_5.01", line((0, 300), (150, 300))),                      # D: meets D2 at (150,300)
        ("4_5.01", line((150, 300), (310, 300))),                    # D2: same element_nr, other end loose
        ("1_4.01", line((0, 0), (0, 300))),                          # E: consistent, kept
        ("3_4.01", line((100, 100), (0, 300), (50, 400))),           # F: end not at node 4
    ]
    lines = gpd.GeoDataFrame({"element_nr": [r[0] for r in rows], "element_nr_berechnet": ["nein"] * len(rows)},
                             geometry=[r[1] for r in rows], crs=CRS)
    nodes_2025 = gpd.GeoDataFrame({ID: ["0007"]}, geometry=[point(100, 0.5)], crs=CRS)
    if not extra_2025:
        nodes_2025 = nodes_2025.iloc[0:0]
    return lines, official, nodes_2025


class AutoNodesTest(unittest.TestCase):
    def run_it(self, extra_2025=True, detail=()):
        lines, official, nodes_2025 = build(extra_2025)
        return an.snap_and_number(lines, official, nodes_2025, list(detail), ID)

    def test_unique_and_complete(self):
        result, proposals, report = self.run_it()
        an.assert_unique(result)
        self.assertEqual(result["element_nr"].isna().sum(), 0)
        self.assertEqual(result["element_nr"].nunique(), len(result))
        # every new number is built from the two end nodes; kept numbers are the existing ones
        for row in result.itertuples():
            if row.element_nr_berechnet == "ja":
                parsed = an.parse_element_nr(row.element_nr)
                self.assertEqual(an.pair_key(parsed[0], parsed[1]), an.pair_key(row.von_knoten, row.bis_knoten), row.element_nr)

    def test_t_node_is_the_2025_node_and_splits_the_host(self):
        result, proposals, report = self.run_it()
        numbers = set(result["element_nr"])
        self.assertNotIn("1_2.01", numbers)  # split
        self.assertEqual({"1_0007.01", "0007_2.01", "3_0007.01"} <= numbers, True, numbers)
        self.assertEqual(report["nodes_2025_matched"], 1)
        self.assertEqual(report["proposals"], len(proposals))
        self.assertNotIn("0007", set(proposals["id"]))  # a 2025 node is no proposal
        arm = result[result["element_nr"] == "3_0007.01"].iloc[0]
        self.assertTrue(pd.isna(arm["ursprung_element_nr"]))  # it had no number before
        self.assertEqual(result[result["element_nr"] == "1_0007.01"].iloc[0]["ursprung_element_nr"], "1_2.01")

    def test_without_2025_node_the_t_node_is_a_proposal_named_by_position(self):
        result, proposals, report = self.run_it(extra_2025=False)
        proposals = proposals.set_index("id")
        t = "P392100-5815000"  # on A at x=100, rounded to whole metres in EPSG:25833
        self.assertIn(t, proposals.index)
        self.assertEqual(proposals.loc[t, "art"], "on_edge")
        self.assertEqual(proposals.loc[t, "geteilte_element_nr"], "1_2.01")
        self.assertIn(f"1_{t}.01", set(result["element_nr"]))
        self.assertIn(f"3_{t}.01", set(result["element_nr"]))
        # the host edge in the file is an edge of the result that ends there, station at that end
        host = result[result["element_nr"] == proposals.loc[t, "traeger_element_nr"]].iloc[0]
        self.assertIn(t, (host["von_knoten"], host["bis_knoten"]))
        self.assertIn(proposals.loc[t, "station_m"], (0.0, round(host.geometry.length, 2)))
        self.assertTrue(an.is_proposal(t))
        self.assertFalse(an.is_proposal("0007"))
        self.assertFalse(an.is_proposal("45530016"))

    def test_dead_end_and_junction(self):
        result, proposals, report = self.run_it(extra_2025=False)
        proposals = proposals.set_index("id")
        # C ends 10 m short of node 5: dead end
        self.assertEqual(proposals.loc["P392290-5815000", "art"], "dead_end")
        c = result[result["element_nr"] == "2_5.01"].iloc[0]  # kept although off its node: nodes stay as named
        self.assertEqual((c["bis_knoten"], c["knoten_ende"]), ("5", "P392290-5815000"))
        # D and D2 meet at (150,300) with nothing else there: no proposal, they are joined
        self.assertNotIn("P392150-5815300", proposals.index)
        self.assertEqual(report["joined"], 1)
        self.assertEqual(report["proposals_by_art"], {"dead_end": 3, "on_edge": 1})

    def test_proposal_ids_are_unique_when_two_round_to_the_same_metre(self):
        nodes = an.Nodes()
        nodes.add("a:0", "proposal", None, Point(X0 + 0.2, Y0 + 0.2))
        nodes.add("a:1", "proposal", None, Point(X0 + 0.4, Y0 + 0.1))
        an.name_proposals(["a:0", "a:1"], nodes)
        self.assertEqual({nodes["a:0"]["name"], nodes["a:1"]["name"]}, {"P392000-5815000", "P392000-5815000-2"})

    def test_element_nr_is_kept_where_it_is_consistent_and_unique(self):
        result, proposals, report = self.run_it(extra_2025=False)
        numbers = list(result["element_nr"])
        self.assertIn("1_4.01", numbers)                       # E: kept
        kept = result[result["element_nr"] == "1_4.01"].iloc[0]
        self.assertTrue(pd.isna(kept["ursprung_element_nr"]))
        self.assertEqual(kept["element_nr_berechnet"], "nein")
        # D and D2 carried 4_5.01 twice and meet with nothing else there: joined, the one edge keeps 4_5.01
        self.assertEqual(numbers.count("4_5.01"), 1)
        d = result[result["element_nr"] == "4_5.01"].iloc[0]
        self.assertAlmostEqual(d.geometry.length, 310.0, delta=0.1)
        self.assertEqual(d["element_nr_berechnet"], "nein")
        # F ends 50 m beyond node 4 but was not split: it keeps 3_4.01
        f = result[result["element_nr"] == "3_4.01"].iloc[0]
        self.assertTrue(pd.isna(f["ursprung_element_nr"]))
        # the nodes named by the number stay; the actual end nodes are in knoten_anfang / knoten_ende
        self.assertEqual((f["von_knoten"], f["bis_knoten"]), ("3", "4"))
        self.assertEqual(f["knoten_anfang"], "3")
        self.assertTrue(an.is_proposal(f["knoten_ende"]))
        # consistent edges have no knoten_anfang / knoten_ende
        e = result[result["element_nr"] == "1_4.01"].iloc[0]
        self.assertTrue(pd.isna(e["knoten_anfang"]) and pd.isna(e["knoten_ende"]))

    def test_nn_counts_per_pair_above_detailnetz(self):
        result, proposals, report = self.run_it(extra_2025=False, detail=["1_P392100-5815000.05", "3_4.01"])
        self.assertIn("1_P392100-5815000.06", set(result["element_nr"]))

    def test_longest_part_keeps_a_shared_number(self):
        lines = gpd.GeoDataFrame({"element_nr": ["1_2.01", "1_2.01"], "element_nr_berechnet": ["nein", "nein"]},
                                 geometry=[line((0, 0), (200, 0)), line((0, 10), (60, 10), (0, 0))], crs=CRS)
        official = gpd.GeoDataFrame({ID: ["1", "2"]}, geometry=[point(0, 0), point(200, 0)], crs=CRS)
        result, _, _ = an.snap_and_number(lines, official, gpd.GeoDataFrame({ID: []}, geometry=[], crs=CRS), [], ID)
        self.assertEqual(sorted(result["element_nr"]), ["1_2.01", "P392000-5815010_1.01"])  # the shorter part gets its own number
        self.assertEqual(result[result["element_nr"] == "1_2.01"].geometry.length.iloc[0], 200.0)

    def test_a_number_is_never_issued_twice(self):
        """nn counts on top of every number REN+ used before, also of a line that is split and dropped."""
        lines = gpd.GeoDataFrame({"element_nr": ["1_2.05", "1_2.03", None], "element_nr_berechnet": ["nein"] * 3},
                                 geometry=[line((0, 0), (200, 0)), line((0, 2), (100, 10), (200, 2)),
                                           line((0, 0), (100, -8), (200, 0))], crs=CRS)
        official = gpd.GeoDataFrame({ID: ["1", "2"]}, geometry=[point(0, 0), point(200, 0)], crs=CRS)
        nodes_2025 = gpd.GeoDataFrame({ID: ["0077"]}, geometry=[point(100, 10)], crs=CRS)
        result, _, _ = an.snap_and_number(lines, official, nodes_2025, [], ID)
        numbers = list(result["element_nr"])
        self.assertEqual(len(numbers), len(set(numbers)))
        self.assertIn("1_2.05", numbers)
        # 1_2.03 was split at 0077 and dropped; the third line gets .06, not .03 or .04
        self.assertNotIn("1_2.03", numbers)
        self.assertIn("1_2.06", numbers)

    def test_assert_unique_fails_loudly(self):
        frame = pd.DataFrame({"element_nr": ["1_2.01", "1_2.01", None]})
        with self.assertRaises(RuntimeError):
            an.assert_unique(frame)


def frame(rows):
    """Lines from (element_nr, strassenname, geometry)."""
    return gpd.GeoDataFrame({"element_nr": [r[0] for r in rows], "element_nr_berechnet": ["nein"] * len(rows),
                             "strassenname": [r[1] for r in rows]}, geometry=[r[2] for r in rows], crs=CRS)


def run(rows, official_points):
    official = gpd.GeoDataFrame({ID: list(official_points)}, geometry=list(official_points.values()), crs=CRS)
    return an.snap_and_number(frame(rows), official, gpd.GeoDataFrame({ID: []}, geometry=[], crs=CRS), [], ID)


class TwoArmJoinTest(unittest.TestCase):
    """Rule 1: where exactly two line ends of two different lines meet and nothing passes, there is no proposal; the
    two lines become one edge, unless they differ in attributes."""

    OFFICIAL = {"1": point(0, 0), "2": point(300, 0)}

    def test_two_lines_meeting_without_anything_else_are_joined(self):
        # 1 -> (100,0.8) and (101,-0.8) -> (200,0) -> 2: ends 2 m apart, a chain of three lines through two such points
        result, proposals, report = run([
            ("1_2.01", "A-Straße", line((0, 0), (100, 0.8))),
            (None, "A-Straße", line((200, 0), (101, -0.8))),
            (None, "A-Straße", line((200, 0.5), (300, 0))),
        ], self.OFFICIAL)
        self.assertEqual(len(proposals), 0)
        self.assertEqual(report["joined"], 2)
        self.assertEqual(len(result), 1)
        edge = result.iloc[0]
        self.assertEqual(edge["element_nr"], "1_2.01")  # the member with a number keeps it, nothing else changes
        self.assertTrue(pd.isna(edge["ursprung_element_nr"]))
        geometry = edge.geometry.geoms[0]
        self.assertTrue(geometry.is_simple)
        self.assertLess(Point(geometry.coords[0]).distance(point(0, 0)), 0.01)  # direction of the numbered member
        self.assertLess(Point(geometry.coords[-1]).distance(point(300, 0)), 0.01)

    def test_lines_differing_in_attributes_are_not_joined(self):
        result, proposals, report = run([
            ("1_2.01", "A-Straße", line((0, 0), (150, 1))),
            ("1_2.02", "B-Straße", line((150, -1), (300, 0))),
        ], self.OFFICIAL)
        self.assertEqual(report["joined"], 0)
        self.assertEqual(list(proposals["art"]), ["junction"])
        self.assertEqual(report["join_refused"], [(proposals.iloc[0]["id"], ["strassenname"])])
        # the proposal separates them, both edges end exactly on its point
        for geometry in result.geometry:
            ends = [Point(geometry.geoms[0].coords[0]), Point(geometry.geoms[0].coords[-1])]
            self.assertTrue(any(end.equals(proposals.iloc[0].geometry) for end in ends))

    def test_a_missing_value_fits_any_and_the_joined_line_takes_the_other(self):
        result, proposals, report = run([
            ("1_2.01", None, line((0, 0), (150, 1))),
            (None, "B-Straße", line((150, -1), (300, 0))),
        ], self.OFFICIAL)
        self.assertEqual((report["joined"], len(proposals)), (1, 0))
        self.assertEqual(list(result["strassenname"]), ["B-Straße"])

    def test_no_join_at_a_proposal_the_app_uses(self):
        rows = [("1_2.01", "A", line((0, 0), (150, 0))), (None, "A", line((150, 0), (300, 0)))]
        entries = [
            {"data": {"kind": "edge_correction", "kante": {"ref": "1_P392150-5815000.01"}}},
            {"data": {"kind": "new_edge", "von": "k:P392999-5815999", "geloescht": True}},  # deleted: does not count
            # an OK of the route check and the check of a bridge or tunnel do not count either
            {"data": {"kind": "route_check", "kanten": ["ren:P392888-5815888_3.01"]}},
            {"data": {"kind": "bridge_check", "kanten": ["ren:P392777-5815777_3.01"], "unten": ["ren:P392777-5815777_3.01"]}},
        ]
        used = an.app_references(entries)
        self.assertEqual(used, {"P392150-5815000", "1_P392150-5815000.01"})
        official = gpd.GeoDataFrame({ID: list(self.OFFICIAL)}, geometry=list(self.OFFICIAL.values()), crs=CRS)
        result, proposals, report = an.snap_and_number(
            frame(rows), official, gpd.GeoDataFrame({ID: []}, geometry=[], crs=CRS), [], ID, app_refs=used)
        self.assertEqual(report["joined"], 0)
        self.assertEqual(report["join_skipped_app"], ["P392150-5815000"])
        self.assertEqual(list(proposals["id"]), ["P392150-5815000"])

    def test_no_join_of_a_line_the_app_corrected(self):
        rows = [("1_2.01", "A", line((0, 0), (150, 0.5))), (None, "A", line((150, -0.5), (300, 0)))]
        used = an.app_references([{"data": {"kind": "edge_correction", "kante": {"ref": "1_2.01"}}}])
        official = gpd.GeoDataFrame({ID: list(self.OFFICIAL)}, geometry=list(self.OFFICIAL.values()), crs=CRS)
        result, proposals, report = an.snap_and_number(
            frame(rows), official, gpd.GeoDataFrame({ID: []}, geometry=[], crs=CRS), [], ID, app_refs=used)
        self.assertEqual((report["joined"], len(proposals)), (0, 1))
        self.assertEqual(report["join_skipped_app"], [proposals.iloc[0]["id"]])

    def test_a_loop_keeps_its_proposal(self):
        # a line from node 1 and a loop whose two ends meet at (100,0)
        result, proposals, report = run([
            (None, "A-Straße", line((0, 0), (50, 50))),
            (None, "A-Straße", line((100, 0), (150, 50), (200, 0), (100.5, 0))),
        ], self.OFFICIAL)
        self.assertEqual(report["joined"], 0)
        self.assertIn("P392100-5815000", set(proposals["id"]))


class ThreeArmProposalTest(unittest.TestCase):
    """Rule 2: where three or more arms meet, the proposal stays; every line ending there ends exactly on its point and
    a line passing through is split there."""

    OFFICIAL = {"1": point(0, 0), "2": point(300, 0), "3": point(150, 200), "4": point(150, -200)}

    def test_line_ends_move_onto_the_proposal_point(self):
        result, proposals, report = run([
            (None, "A", line((0, 0), (149, 0.5))),
            (None, "A", line((300, 0), (151, 0))),
            (None, "A", line((150, 200), (150, 1.2))),
        ], self.OFFICIAL)
        self.assertEqual(report["joined"], 0)
        self.assertEqual(len(proposals), 1)
        proposal = proposals.iloc[0]
        self.assertEqual(proposal["art"], "junction")
        self.assertEqual(len(proposal["kanten"].split("; ")), 3)
        for geometry in result.geometry:
            self.assertTrue(Point(geometry.geoms[0].coords[-1]).equals(proposal.geometry))

    def test_a_line_passing_a_junction_is_split_there(self):
        # two ends meet 1.5 m beside the line 3-4 (which passes, ends far away): four arms, the line is split
        result, proposals, report = run([
            ("1_2.01", "A", line((0, 0), (148.5, 0.5))),
            ("1_2.02", "A", line((300, 0), (151.5, 0.5))),
            ("3_4.01", "B", line((150, 200), (150, -200))),
        ], self.OFFICIAL)
        self.assertEqual(report["joined"], 0)
        self.assertEqual(len(proposals), 1)
        proposal = proposals.iloc[0]
        self.assertEqual(proposal["geteilte_element_nr"], "3_4.01")
        self.assertEqual(len(proposal["kanten"].split("; ")), 4)
        self.assertNotIn("3_4.01", set(result["element_nr"]))
        self.assertEqual(sorted(result["ursprung_element_nr"].dropna()), ["3_4.01", "3_4.01"])
        self.assertTrue({"1_2.01", "1_2.02"} <= set(result["element_nr"]))  # ending there is no split
        self.assertEqual(int(proposal["arme"]), 4)


def snap(rows, official_points, detail_lines=None, app_refs=frozenset(), corrected=frozenset()):
    official = gpd.GeoDataFrame({ID: list(official_points)}, geometry=list(official_points.values()), crs=CRS)
    return an.snap_and_number(frame(rows), official, gpd.GeoDataFrame({ID: []}, geometry=[], crs=CRS), [], ID,
                              app_refs=app_refs, detail_lines=detail_lines, corrected=corrected)


def ends_of(geometry):
    part = geometry.geoms[0] if geometry.geom_type == "MultiLineString" else geometry
    return Point(part.coords[0]), Point(part.coords[-1])


class CleanGeometryTest(unittest.TestCase):
    """Every edge end lies exactly on its node; Detailnetz lines count as arms; dead ends near a node end on it."""

    OFFICIAL = {"1": point(0, 0), "2": point(300, 0), "3": point(150, 200)}

    def test_every_end_lies_exactly_on_its_official_node(self):
        result, _, report = snap([("1_2.01", "A", line((1.5, 1.0), (298, -1.2)))], self.OFFICIAL)
        start, end = ends_of(result.iloc[0].geometry)
        self.assertTrue(start.equals(point(0, 0)) and end.equals(point(300, 0)))
        self.assertEqual(report["ends_moved"], 2)

    def test_an_edge_the_app_corrected_keeps_its_ends(self):
        coordinates = [[13.1, 52.1], [13.2, 52.2]]
        entries = [{"data": {"kind": "edge_correction", "kante": {"ref": "1_2.01", "element_nr": "1_2.01"},
                             "original_coordinates": coordinates, "coordinates": [[13.1, 52.1], [13.2, 52.3]],
                             "attribute": {}}}]
        corrected = an.corrected_edges(entries)
        self.assertEqual(corrected, {"1_2.01"})
        result, _, report = snap([("1_2.01", "A", line((1.5, 1.0), (300, 0)))], self.OFFICIAL,
                                 app_refs=an.app_references(entries), corrected=corrected)
        start, _ = ends_of(result.iloc[0].geometry)
        self.assertAlmostEqual(start.distance(point(0, 0)), 1.80, places=2)
        self.assertEqual(report["ends_left_app"], [("1_2.01", "1", 1.8)])

    def test_other_app_references_do_not_keep_ends_off_the_proposal(self):
        """A virtual node accepting the proposal (vorschlag_id, traeger.ref) stops the join there but not the move of
        the edge ends onto the proposal point; a correction back at the original protects nothing."""
        rows = [("1_2.01", "A", line((0, 0), (150, 0.4))), (None, "A", line((150.3, -0.4), (300, 0)))]
        coordinates = [[13.1, 52.1], [13.2, 52.2]]
        entries = [
            {"data": {"kind": "virtual_node", "nummer": "0396", "herkunft": "vorschlag",
                      "vorschlag_id": "P392150-5815000", "traeger": {"art": "ren", "ref": "1_P392150-5815000.01"}}},
            {"data": {"kind": "edge_correction", "kante": {"ref": "1_P392150-5815000.01"}, "attribute": {},
                      "coordinates": coordinates, "original_coordinates": coordinates}},
        ]
        result, proposals, report = snap(rows, self.OFFICIAL, app_refs=an.app_references(entries),
                                         corrected=an.corrected_edges(entries))
        self.assertEqual(report["joined"], 0)
        self.assertEqual(report["ends_left_app"], [])
        proposal = proposals.set_index("id").loc["P392150-5815000"].geometry
        for geometry in result.geometry:
            self.assertTrue(any(end.equals(proposal) for end in ends_of(geometry)))

    def test_a_correction_that_changes_nothing_is_no_app_reference(self):
        coordinates = [[13.1, 52.1], [13.2, 52.2]]
        reset = {"kind": "edge_correction", "kante": {"ref": "1_P392150-5815000.01"}, "coordinates": coordinates,
                 "original_coordinates": coordinates, "attribute": {},
                 "aenderungen": [{"art": "zurueckgesetzt"}]}
        moved = {**reset, "coordinates": [[13.1, 52.1], [13.2, 52.3]]}
        directed = {**reset, "attribute": {"verkehrsrichtung": None}}  # direction cleared: a change
        self.assertEqual(an.app_references([{"data": reset}]), set())
        self.assertEqual(an.app_references([{"data": moved}]), {"1_P392150-5815000.01", "P392150-5815000"})
        self.assertEqual(an.app_references([{"data": directed}]), {"1_P392150-5815000.01", "P392150-5815000"})

    def test_a_detailnetz_line_meeting_two_ends_is_a_third_arm(self):
        rows = [("1_2.01", "A", line((0, 0), (150, 0))), (None, "A", line((150, 0), (300, 0)))]
        # the Detailnetz line from node 3 ends there, plus a Detailnetz line along the network (same street): one arm
        detail = [line((150, 200), (150, 0)), line((0, 0.3), (150, 0.3))]
        result, proposals, report = snap(rows, self.OFFICIAL, detail_lines=detail)
        self.assertEqual(report["joined"], 0)
        self.assertEqual(report["join_detail_arm"], ["P392150-5815000"])
        self.assertEqual(list(proposals["arme"]), [3])
        # without the line from node 3 only the street along the network is there: joined
        result, proposals, report = snap(rows, self.OFFICIAL, detail_lines=detail[1:])
        self.assertEqual((report["joined"], len(proposals)), (1, 0))

    def test_a_dead_end_near_a_node_ends_on_it(self):
        rows = [("1_2.01", "A", line((0, 0), (300, 0))), (None, "B", line((150, 100), (150, 203.5)))]
        result, proposals, report = snap(rows, {**self.OFFICIAL, "4": point(150, 100)})
        self.assertEqual(len(proposals), 0)
        self.assertEqual(report["dead_ends_on_node"], ["3"])
        edge = result[result["strassenname"] == "B"].iloc[0]
        self.assertTrue(ends_of(edge.geometry)[1].equals(point(150, 200)))
        self.assertEqual(an.pair_key(edge["von_knoten"], edge["bis_knoten"]), ("3", "4"))


if __name__ == "__main__":
    unittest.main()
