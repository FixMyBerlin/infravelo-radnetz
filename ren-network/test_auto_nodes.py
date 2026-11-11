#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Self-test for auto_nodes.py (automatic virtual nodes and unique element_nr in step 1) with an invented network.

    .venv/bin/python ren-network/test_auto_nodes.py

Network (metres): official nodes 1 (0,0), 2 (200,0), 3 (100,100), 4 (0,300), 5 (300,0).
A 1-2 along y=0 (will be split), T arm from node 3 down to (100,1.5) (T on A, no element_nr),
C from node 2 east to (290,0) (end 10 m short of node 5: dead end), D and D2 two parts with the same
element_nr 4_5.01 that meet in an unnamed junction, E 1-4 with a correct element_nr, F a loop-free
edge whose element_nr names other nodes than its ends.
A 2025 node lies 0.5 m beside A at x=100 and has to supply the name of the T node.
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
    nodes_2025 = gpd.GeoDataFrame({ID: ["V2025"]}, geometry=[point(100, 0.5)], crs=CRS)
    if not extra_2025:
        nodes_2025 = nodes_2025.iloc[0:0]
    return lines, official, nodes_2025


class AutoNodesTest(unittest.TestCase):
    def run_it(self, extra_2025=True, detail=()):
        lines, official, nodes_2025 = build(extra_2025)
        return an.snap_and_number(lines, official, nodes_2025, list(detail), ID)

    def test_unique_and_complete(self):
        result, virtual, report = self.run_it()
        an.assert_unique(result)
        self.assertEqual(result["element_nr"].isna().sum(), 0)
        self.assertEqual(result["element_nr"].nunique(), len(result))
        # every new number is built from the two end nodes; kept numbers are the existing ones
        for row in result.itertuples():
            if row.element_nr_berechnet == "ja":
                parsed = an.parse_element_nr(row.element_nr)
                self.assertEqual(an.pair_key(parsed[0], parsed[1]), an.pair_key(row.von_knoten, row.bis_knoten), row.element_nr)

    def test_t_node_takes_the_name_of_the_2025_node_and_splits_the_host(self):
        result, virtual, report = self.run_it()
        numbers = set(result["element_nr"])
        self.assertNotIn("1_2.01", numbers)  # split
        self.assertEqual({"1_V2025.01", "V2025_2.01", "3_V2025.01"} <= numbers, True, numbers)
        self.assertEqual(report["nodes_2025_matched"], 1)
        self.assertEqual(report["auto_nodes"] - (virtual["quelle"] == "auto").sum(), 0)
        node = virtual[virtual[ID] == "V2025"].iloc[0]
        self.assertEqual(node["quelle"], "2025")
        self.assertEqual(node["art"], "on_edge")
        self.assertEqual(node["traeger_element_nr"], "1_2.01")
        arm = result[result["element_nr"] == "3_V2025.01"].iloc[0]
        self.assertTrue(pd.isna(arm["ursprung_element_nr"]))  # it had no number before
        self.assertEqual(result[result["element_nr"] == "1_V2025.01"].iloc[0]["ursprung_element_nr"], "1_2.01")

    def test_without_2025_node_an_auto_node_is_named_like_the_app(self):
        result, virtual, report = self.run_it(extra_2025=False)
        autos = virtual[virtual["quelle"] == "auto"].set_index(ID)
        # on A between the official nodes 1 and 2; the T arm leads to 3, but "along the host" counts: 1 and 2
        self.assertIn("V1-2", autos.index)
        self.assertEqual(autos.loc["V1-2", "art"], "on_edge")
        self.assertEqual(autos.loc["V1-2", "traeger_element_nr"], "1_2.01")
        self.assertIn("1_V1-2.01", set(result["element_nr"]))
        self.assertIn("3_V1-2.01", set(result["element_nr"]))

    def test_dead_end_and_junction(self):
        result, virtual, report = self.run_it(extra_2025=False)
        autos = virtual[virtual["quelle"] == "auto"].set_index(ID)
        # C ends 10 m short of node 5: dead end named after the nearest official node (2)
        self.assertEqual(autos.loc["V2-1", "art"], "dead_end")
        c = result[result["element_nr"] == "2_5.01"].iloc[0]  # kept although off its node: nodes stay as named
        self.assertEqual((c["bis_knoten"], c["knoten_ende"]), ("5", "V2-1"))
        # D and D2 meet at (150,300) without a node: a junction, named after the nearest official node 4
        self.assertEqual(autos.loc["V4-1", "art"], "junction")
        self.assertEqual(report["auto_by_art"], {"dead_end": 3, "junction": 1, "on_edge": 1})

    def test_element_nr_is_kept_where_it_is_consistent_and_unique(self):
        result, virtual, report = self.run_it(extra_2025=False)
        numbers = list(result["element_nr"])
        self.assertIn("1_4.01", numbers)                       # E: kept
        kept = result[result["element_nr"] == "1_4.01"].iloc[0]
        self.assertTrue(pd.isna(kept["ursprung_element_nr"]))
        self.assertEqual(kept["element_nr_berechnet"], "nein")
        # D and D2 carried 4_5.01 twice: the longer D2 keeps it, D gets its own number from its end nodes
        self.assertEqual(numbers.count("4_5.01"), 1)
        d2 = result[result["element_nr"] == "4_5.01"].iloc[0]
        self.assertAlmostEqual(d2.geometry.length, 160.0, delta=0.1)
        d = result[result["ursprung_element_nr"] == "4_5.01"].iloc[0]
        self.assertEqual(d["element_nr_berechnet"], "ja")
        # F ends 50 m beyond node 4 but was not split: it keeps 3_4.01
        f = result[result["element_nr"] == "3_4.01"].iloc[0]
        self.assertTrue(pd.isna(f["ursprung_element_nr"]))
        # the nodes named by the number stay; the actual end nodes are in knoten_anfang / knoten_ende
        self.assertEqual((f["von_knoten"], f["bis_knoten"]), ("3", "4"))
        self.assertEqual(f["knoten_anfang"], "3")
        self.assertTrue(f["knoten_ende"].startswith("V"))
        # consistent edges have no knoten_anfang / knoten_ende
        e = result[result["element_nr"] == "1_4.01"].iloc[0]
        self.assertTrue(pd.isna(e["knoten_anfang"]) and pd.isna(e["knoten_ende"]))

    def test_nn_counts_per_pair_above_detailnetz(self):
        result, virtual, report = self.run_it(extra_2025=False, detail=["1_V1-2.05", "3_4.01"])
        self.assertIn("1_V1-2.06", set(result["element_nr"]))

    def test_longest_part_keeps_a_shared_number(self):
        lines = gpd.GeoDataFrame({"element_nr": ["1_2.01", "1_2.01"], "element_nr_berechnet": ["nein", "nein"]},
                                 geometry=[line((0, 0), (200, 0)), line((0, 10), (60, 10), (0, 0))], crs=CRS)
        official = gpd.GeoDataFrame({ID: ["1", "2"]}, geometry=[point(0, 0), point(200, 0)], crs=CRS)
        result, _, _ = an.snap_and_number(lines, official, gpd.GeoDataFrame({ID: []}, geometry=[], crs=CRS), [], ID)
        self.assertEqual(sorted(result["element_nr"]), ["1_2.01", "V1-1_1.01"])  # the shorter part gets its own number
        self.assertEqual(result[result["element_nr"] == "1_2.01"].geometry.length.iloc[0], 200.0)

    def test_assert_unique_fails_loudly(self):
        frame = pd.DataFrame({"element_nr": ["1_2.01", "1_2.01", None]})
        with self.assertRaises(RuntimeError):
            an.assert_unique(frame)


if __name__ == "__main__":
    unittest.main()
