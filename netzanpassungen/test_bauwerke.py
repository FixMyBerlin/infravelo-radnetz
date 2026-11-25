#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Self-test for bauwerke.py (candidates of the check „Brücken und Tunnel“) on a tiny synthetic case, and for the
`bauwerk_knoten` layer of write_app_input.py.

    .venv/bin/python netzanpassungen/test_bauwerke.py
"""

import sys
import tempfile
import unittest
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, Point

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bauwerke as bw  # noqa: E402
import write_app_input as wai  # noqa: E402

X0, Y0 = 392000.0, 5815000.0


def line(*points):
    return LineString([(X0 + x, Y0 + y) for x, y in points])


def structures():
    rows = [
        ("BR", "Teststeg", "01-1", line((0, 0), (100, 0))),
        ("TU", "Testtunnel", "02-2", line((0, 1000), (100, 1000))),
        ("BR", "Mittensteg", "-", line((0, 2000), (100, 2000))),
        ("BR", "Steg ohne Ren", "04-4", line((0, 3000), (100, 3000))),
        ("FB", "Kein Bauwerk der Liste", "05-5", line((0, 4000), (100, 4000))),
    ]
    return gpd.GeoDataFrame({"bauwerksart": [r[0] for r in rows], "bauwerksname": [r[1] for r in rows],
                             "bauwerksnummer": [r[2] for r in rows]}, geometry=[r[3] for r in rows], crs=bw.CRS)


# element_nr, from node, to node, Verkehrsebene, geometry; the nodes lie at the first / last point
EDGES = [
    # bridge: two edges on it meet one crossing edge at node N1 (50, 0)
    ("N0_N1.01", "N0", "N1", 1, line((0, 0), (50, 0))),
    ("N1_N2.01", "N1", "N2", 1, line((50, 0), (100, 0))),
    ("N3_N1.01", "N3", "N1", 0, line((50, -60), (50, 0))),
    # tunnel: its edges lie in it, one crossing edge on top; they meet at M1 (50, 1000)
    ("M0_M1.01", "M0", "M1", 0, line((0, 1000), (50, 1000))),
    ("M1_M2.01", "M1", "M2", 0, line((50, 1000), (100, 1000))),
    ("M3_M1.01", "M3", "M1", 0, line((50, 940), (50, 1000))),
    # a node in the middle of a bridge with one edge ending there
    ("Q0_Q1.01", "Q0", "Q1", None, line((50, 2002), (50, 2060))),
    # a bridge with Detailnetz edges only
    ("R0_R1.01", "R0", "R1", 1, line((0, 3000), (50, 3000))),
    ("R1_R2.01", "R1", "R2", 1, line((50, 3000), (100, 3000))),
    ("R3_R1.01", "R3", "R1", 0, line((50, 2940), (50, 3000))),
]
NO_REN = {"R0_R1.01", "R1_R2.01", "R3_R1.01"}
NODES = {"N0": (0, 0), "N1": (50, 0), "N2": (100, 0), "N3": (50, -60), "M0": (0, 1000), "M1": (50, 1000), "M2": (100, 1000),
         "M3": (50, 940), "Q0": (50, 2002), "Q1": (50, 2060), "R0": (0, 3000), "R1": (50, 3000), "R2": (100, 3000),
         "R3": (50, 2940)}


def frames():
    detail = gpd.GeoDataFrame(
        {"element_nr": [e[0] for e in EDGES], "beginnt_bei_vp": [e[1] for e in EDGES], "endet_bei_vp": [e[2] for e in EDGES],
         "verkehrsebene": [e[3] for e in EDGES]}, geometry=[e[4] for e in EDGES], crs=bw.CRS)
    ren_rows = [e for e in EDGES if e[0] not in NO_REN]
    ren = gpd.GeoDataFrame(
        {"element_nr": [e[0] for e in ren_rows], "von_knoten": [e[1] for e in ren_rows], "bis_knoten": [e[2] for e in ren_rows]},
        geometry=[e[4] for e in ren_rows], crs=bw.CRS)
    detail["ref"], ren["ref"] = wai.line_refs(detail["element_nr"]), wai.line_refs(ren["element_nr"])
    nodes = gpd.GeoDataFrame({"id": list(NODES)}, geometry=[Point(X0 + x, Y0 + y) for x, y in NODES.values()], crs=bw.CRS)
    return detail, ren, nodes


class CandidatesTest(unittest.TestCase):
    def setUp(self):
        detail, ren, nodes = frames()
        self.result = bw.find_candidates(structures(), detail, ren, nodes).set_index("knoten")

    def test_which_nodes(self):
        # N1 (bridge, on + crossing), M1 (tunnel), Q1 is no node of the middle case: Q0 (the node 2 m from the line)
        self.assertEqual(sorted(self.result.index), ["M1", "N1", "Q0"])

    def test_bridge_proposes_the_crossing_edges_as_lower_level(self):
        row = self.result.loc["N1"]
        self.assertEqual((row["bauwerk"], row["art"], row["nr"]), ("Teststeg", "BR", "01-1"))
        self.assertEqual(row["vorschlag_unten"], "detailnetz:N3_N1.01|ren:N3_N1.01")
        self.assertTrue(row["ebenen_verschieden"])  # on the bridge level 1, crossing edge level 0

    def test_tunnel_proposes_the_edges_in_the_tunnel(self):
        row = self.result.loc["M1"]
        self.assertEqual((row["bauwerk"], row["art"]), ("Testtunnel", "TU"))
        self.assertEqual(row["vorschlag_unten"], "detailnetz:M0_M1.01|detailnetz:M1_M2.01|ren:M0_M1.01|ren:M1_M2.01")
        self.assertFalse(row["ebenen_verschieden"])  # all level 0

    def test_node_in_the_middle_without_levels(self):
        row = self.result.loc["Q0"]
        self.assertEqual((row["bauwerk"], row["art"]), ("Mittensteg", "BR"))
        self.assertTrue(pd.isna(row["nr"]))  # „-“ is no number (null in the file)
        self.assertEqual(row["vorschlag_unten"], "")
        self.assertFalse(row["ebenen_verschieden"])  # the level is unknown

    def test_only_nodes_with_a_ren_edge_and_only_listed_kinds(self):
        self.assertNotIn("R1", self.result.index)  # Detailnetz edges only
        self.assertEqual(set(self.result["art"]), {"BR", "TU"})

    def test_position_is_the_node(self):
        point = self.result.loc["N1"].geometry
        self.assertLess(point.distance(Point(X0 + 50, Y0)), 1e-6)
        self.assertEqual(list(self.result.columns), [c for c in bw.OUTPUT_COLUMNS if c != "knoten"] + ["geometry"])

    def test_one_candidate_per_node_prefers_the_connected_structure(self):
        # a second, longer structure passes N1 without joining anything there: the connected one stays
        longer = gpd.GeoDataFrame({"bauwerksart": ["BR"], "bauwerksname": ["Lange Brücke"], "bauwerksnummer": ["09-9"]},
                                  geometry=[line((50, 5), (50, 500))], crs=bw.CRS)
        both = gpd.GeoDataFrame(pd.concat([structures().iloc[:1], longer], ignore_index=True), geometry="geometry", crs=bw.CRS)
        detail, ren, nodes = frames()
        result = bw.find_candidates(both, detail, ren, nodes).set_index("knoten")
        self.assertEqual(result.loc["N1", "bauwerk"], "Teststeg")


class LoadStructuresTest(unittest.TestCase):
    def test_missing_file_gives_none(self):
        with self.assertLogs(level="WARNING") as logs:
            self.assertIsNone(bw.load_structures(Path("/nonexistent/bauwerke.geojson")))
        self.assertIn("Bauwerke fehlen", logs.output[0])

    def test_reads_wgs84_and_keeps_listed_kinds(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "b.geojson"
            frame = structures().to_crs("EPSG:4326")
            frame.to_file(path, driver="GeoJSON")
            loaded = bw.load_structures(path)
        self.assertEqual(len(loaded), 4)  # „FB“ is dropped
        self.assertEqual(loaded.crs.to_epsg(), 25833)


class FeatureCollectionTest(unittest.TestCase):
    def test_properties_of_the_app_layer(self):
        detail, ren, nodes = frames()
        collection = wai.feature_collection(bw.find_candidates(structures(), detail, ren, nodes))
        feature = next(f for f in collection["features"] if f["properties"]["knoten"] == "N1")
        self.assertIsNone(next(f for f in collection["features"] if f["properties"]["knoten"] == "Q0")["properties"]["nr"])
        self.assertEqual(sorted(feature["properties"]),
                         ["art", "bauwerk", "ebenen_verschieden", "knoten", "nr", "vorschlag_unten"])
        self.assertIs(feature["properties"]["ebenen_verschieden"], True)
        self.assertEqual(feature["geometry"]["type"], "Point")


if __name__ == "__main__":
    unittest.main()
