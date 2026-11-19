#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Self-test for two rules of step 1 with an invented network modelled on Berlin, 27570001 (Spandau):

1. Lines of different sources between the same two nodes that lie close together are one edge
   (merge_networks.merge_parallel_edges by the nodes the element_nr names, auto_nodes.merge_parallel_pieces by the end
   nodes after splitting). Lines of the same source stay separate.
2. A line end within a few metres of the official node its element_nr names ends on that node
   (auto_nodes.snap_ends_to_named_nodes) instead of creating a node proposal.

    .venv/bin/python ren-network/test_parallel_edges.py

Network (metres): official nodes 27570001 (0,0), 28560007 (0,800), 28570001 (270,0), 27570002 (-340,0).
Hauptstraßennetz: Am Zeppelinpark 27570001_28560007.02 (x=0), Brunsbütteler Damm 27570001_28570001.02 and
27570002_27570001.03 (y=0). Radverkehrsnetz with the older numbers .01: both lines start at (-10,1), 10 m before
27570001 on the Brunsbütteler Damm, and run 8 m and 1 m beside the Hauptstraßennetz.
"""

import sys
import unittest
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, MultiLineString, Point

sys.path.append(str(Path(__file__).resolve().parent))

import auto_nodes as an  # noqa: E402
import merge_networks as mn  # noqa: E402

X0, Y0 = 372949.0, 5822269.0
CRS = "EPSG:25833"
ID = "Knotenpunkt-ID"
RVN, HSN, RSV = "radverkehrsnetz", "hauptstrassennetz", "radschnellverbindungen"
EMPTY_2025 = gpd.GeoDataFrame({ID: []}, geometry=[], crs=CRS)


def line(*points):
    return LineString([(X0 + x, Y0 + y) for x, y in points])


def point(x, y):
    return Point(X0 + x, Y0 + y)


def official(**nodes):
    return gpd.GeoDataFrame({ID: list(nodes)}, geometry=[point(*xy) for xy in nodes.values()], crs=CRS)


def network(rows):
    """rows: (element_nr, source, strassenname, geometry) -> network as after merge_by_element_nr."""
    return gpd.GeoDataFrame({
        "element_nr": [r[0] for r in rows],
        "netz_quellen": [r[1] for r in rows],
        "radverkehrsnetz": [mn.RVN_ERGAENZUNG if r[1] == RVN else None for r in rows],
        "strassenname": [r[2] for r in rows],
        "strassenklasse": [None] * len(rows),
        "netz_quellen_teilweise": [None] * len(rows),
        "element_nr_berechnet": ["nein"] * len(rows),
    }, geometry=[MultiLineString([r[3]]) for r in rows], crs=CRS)


def spandau():
    nodes = official(**{"27570001": (0, 0), "28560007": (0, 800), "28570001": (270, 0), "27570002": (-340, 0)})
    net = network([
        ("27570001_28560007.02", HSN, "Am Zeppelinpark", line((0, 0), (0, 800))),
        ("27570001_28570001.02", HSN, "Brunsbütteler Damm", line((0, 0), (270, 0))),
        ("27570002_27570001.03", HSN, "Brunsbütteler Damm", line((-340, 0), (0, 0))),
        ("27570001_28560007.01", RVN, None, line((-10, 1), (8, 20), (8, 790))),
        ("27570001_28570001.01", RVN, None, line((-10, 1), (270, 1))),
    ])
    return net, nodes


def lines_of(net):
    return net.explode(index_parts=False).reset_index(drop=True)


class SpandauTest(unittest.TestCase):
    def test_without_the_rules_the_extra_lines_get_02_and_a_proposal_splits_the_street(self):
        net, nodes = spandau()
        result, proposals, _ = an.snap_and_number(lines_of(net), nodes, EMPTY_2025, [], ID)
        self.assertEqual(len(result), 6)  # 5 lines, Brunsbütteler Damm 27570002_27570001.03 split
        self.assertEqual(sorted(result["element_nr"])[:4], ["27570001_28560007.01", "27570001_28560007.02",
                                                             "27570001_28570001.01", "27570001_28570001.02"])
        # on_edge where the Radverkehrsnetz starts 10 m before 27570001, dead_end 12.8 m before 28560007
        proposals = proposals.set_index("art")
        self.assertEqual(sorted(proposals.index), ["dead_end", "on_edge"])
        self.assertEqual(proposals.loc["on_edge", "geteilte_element_nr"], "27570002_27570001.03")

    def test_with_the_rules_one_edge_per_stretch_and_no_proposal(self):
        net, nodes = spandau()
        net, moved = an.snap_ends_to_named_nodes(net, nodes, ID)
        self.assertEqual(sorted((nr, node) for nr, node, _ in moved),
                         [("27570001_28560007.01", "27570001"), ("27570001_28560007.01", "28560007"),
                          ("27570001_28570001.01", "27570001")])
        detail = ["27570001_28560007.02", "27570001_28570001.02", "27570002_27570001.03"]
        net = mn.merge_parallel_edges(net, frozenset(detail))
        result, proposals, _ = an.snap_and_number(lines_of(net), nodes, EMPTY_2025, detail, ID,
                                                  combine=mn.combine_parallel)

        self.assertEqual(len(proposals), 0)
        self.assertEqual(sorted(result["element_nr"]),
                         ["27570001_28560007.02", "27570001_28570001.02", "27570002_27570001.03"])
        # the merged edge keeps the number the Detailnetz has (.02), not the older Radverkehrsnetz one (.01)
        edge = result.set_index("element_nr").loc["27570001_28560007.02"]
        self.assertEqual(edge["netz_quellen"], f"{HSN};{RVN}")
        self.assertEqual(edge["strassenname"], "Am Zeppelinpark")
        self.assertEqual(edge["radverkehrsnetz"], mn.RVN_ERGAENZUNG)
        # geometry of the Radverkehrsnetz (priority, not more than 10 m shorter), now from node to node
        geometry = edge.geometry.geoms[0]
        self.assertEqual(geometry.coords[0], (X0, Y0))
        self.assertEqual(geometry.coords[-1], (X0, Y0 + 800))
        self.assertIn((X0 + 8, Y0 + 20), list(geometry.coords))
        self.assertTrue(pd.isna(edge["knoten_anfang"]) and pd.isna(edge["knoten_ende"]))


class NamedNodeTest(unittest.TestCase):
    def test_overshoot_is_cut_and_far_ends_stay(self):
        nodes = official(**{"1": (0, 0), "2": (200, 0)})
        net = network([("1_2.01", RVN, None, line((0, 0), (206, 0))),         # 6 m beyond node 2
                       ("1_2.02", RVN, None, line((0, 0), (100, 5), (180, 5)))])  # 20.6 m before node 2: too far
        moved_net, moved = an.snap_ends_to_named_nodes(net, nodes, ID)
        self.assertEqual([(nr, node) for nr, node, _ in moved], [("1_2.01", "2")])
        self.assertEqual(list(moved_net.geometry.iloc[0].geoms[0].coords), [(X0, Y0), (X0 + 200, Y0)])
        self.assertTrue(moved_net.geometry.iloc[1].equals(net.geometry.iloc[1]))

    def test_end_on_a_2025_node_stays(self):
        nodes = official(**{"1": (0, 0), "2": (200, 0)})
        nodes_2025 = gpd.GeoDataFrame({ID: ["0004"]}, geometry=[point(190, 0)], crs=CRS)
        net = network([("1_2.01", RVN, None, line((0, 0), (190, 0)))])
        _, moved = an.snap_ends_to_named_nodes(net, nodes, ID, nodes_2025)
        self.assertEqual(moved, [])

    def test_ends_that_met_a_moved_end_follow_it(self):
        nodes = official(**{"1": (0, 0), "2": (200, 0), "3": (200, 300)})
        net = network([("1_2.01", RVN, None, line((0, 0), (192, 0))),
                       (None, RVN, None, line((192, 0), (200, 300)))])  # no number, met 1_2.01 8 m before node 2
        moved_net, moved = an.snap_ends_to_named_nodes(net, nodes, ID)
        self.assertEqual(len(moved), 2)
        self.assertEqual(moved_net.geometry.iloc[1].geoms[0].coords[0], (X0 + 200, Y0))

    def test_a_junction_whose_lines_name_the_node_moves_from_farther(self):
        """Like 57420036 (Richterstraße): three Radverkehrsnetz lines that all name node N meet 17 m from it. A single
        end 17 m from its node stays (beyond NAMED_NODE_TOL_M)."""
        nodes = official(**{"N": (0, 0), "A": (-300, 17), "B": (300, 17), "C": (0, 300), "D": (0, -300)})
        net = network([("A_N.01", RVN, None, line((-300, 17), (0, 17))),
                       ("N_B.01", RVN, None, line((0, 17), (300, 17))),
                       ("N_C.01", RVN, None, line((0, 17), (0, 300))),
                       ("D_N.01", HSN, None, line((0, -300), (0, -17)))])  # alone, 17 m before N
        moved_net, moved = an.snap_ends_to_named_nodes(net, nodes, ID)
        self.assertEqual(sorted(nr for nr, _, _ in moved), ["A_N.01", "N_B.01", "N_C.01"])
        for index in range(3):
            ends = moved_net.geometry.iloc[index].geoms[0].boundary.geoms
            self.assertTrue(any(end.equals(point(0, 0)) for end in ends))
        self.assertTrue(moved_net.geometry.iloc[3].equals(net.geometry.iloc[3]))

    def test_a_junction_with_a_line_naming_another_node_stays(self):
        nodes = official(**{"N": (0, 0), "M": (0, 600), "A": (-300, 17), "B": (300, 17)})
        net = network([("A_N.01", RVN, None, line((-300, 17), (0, 17))),
                       ("N_B.01", RVN, None, line((0, 17), (300, 17))),
                       ("M_B.01", RVN, None, line((0, 17), (0, 600)))])
        _, moved = an.snap_ends_to_named_nodes(net, nodes, ID)
        self.assertEqual(moved, [])


class ParallelTest(unittest.TestCase):
    def test_same_source_stays_separate_and_far_lines_too(self):
        nodes = official(**{"1": (0, 0), "2": (200, 0)})
        net = network([("1_2.01", RVN, None, line((0, 0), (200, 0))),
                       ("1_2.02", RVN, None, line((0, 0), (100, 4), (200, 0))),     # same source: real parallel edge
                       ("1_2.03", HSN, "Weg", line((0, 0), (100, 40), (200, 0)))])  # 40 m away: separate
        merged = mn.merge_parallel_edges(net)
        self.assertEqual(sorted(merged["element_nr"]), ["1_2.01", "1_2.02", "1_2.03"])

    def test_the_same_line_twice_merges_even_from_one_source(self):
        """Like 39560026_39560027: a Radschnellverbindung line lies exactly on an edge that already includes it."""
        net = network([("1_2.01", f"{HSN};{RSV}", "Weg", line((0, 0), (200, 0))),
                       ("1_2.02", RSV, None, line((0, 0), (100, 1), (200, 0))),   # 1 m: the same line
                       ("1_2.03", RSV, None, line((0, 0), (100, 4), (200, 0)))])  # 4 m: a real parallel edge
        merged = mn.merge_parallel_edges(net).set_index("element_nr")
        self.assertEqual(sorted(merged.index), ["1_2.01", "1_2.03"])
        self.assertEqual(merged.loc["1_2.01", "netz_quellen"], f"{HSN};{RSV}")

    def test_closest_pair_merges_and_keeps_the_lowest_number(self):
        nodes = official(**{"1": (0, 0), "2": (200, 0)})
        net = network([("1_2.03", RVN, None, line((0, 0), (100, 3), (200, 0))),
                       ("1_2.02", RVN, None, line((0, 0), (100, 12), (200, 0))),
                       ("1_2.01", HSN, "Weg", line((200, 0), (0, 0)))])  # digitised the other way
        merged = mn.merge_parallel_edges(net).set_index("element_nr")
        # the Hauptstraßennetz line joins the closer Radverkehrsnetz line only; .01 stays, .03 goes
        self.assertEqual(sorted(merged.index), ["1_2.01", "1_2.02"])
        edge = merged.loc["1_2.01"]
        self.assertEqual(edge["netz_quellen"], f"{HSN};{RVN}")
        coords = list(edge.geometry.geoms[0].coords)
        self.assertEqual(coords[1], (X0 + 100, Y0 + 3))           # Radverkehrsnetz geometry ...
        self.assertEqual(coords[0], (X0 + 200, Y0))               # ... in the direction of the number's line

    def test_pieces_between_two_2025_nodes_merge(self):
        """Like 0050_0021: a numbered Radverkehrsnetz line split at two 2025 nodes and a Radschnellverbindung without
        element_nr between them become one edge; a second Radverkehrsnetz line there stays separate."""
        nodes = official(**{"1": (0, 0), "2": (600, 0)})
        nodes_2025 = gpd.GeoDataFrame({ID: ["0050", "0021"]}, geometry=[point(100, 0), point(500, 0)], crs=CRS)
        net = network([("1_2.01", RVN, None, line((0, 0), (600, 0))),
                       (None, RSV, None, line((100, 0), (500, 0))),
                       (None, RVN, None, line((100, 0), (300, 3), (500, 0)))])
        result, proposals, report = an.snap_and_number(lines_of(net), nodes, nodes_2025, [], ID,
                                                       combine=mn.combine_parallel)
        middle = result[result["element_nr"].str.startswith("0050_0021")].set_index("element_nr")
        self.assertEqual(sorted(middle.index), ["0050_0021.01", "0050_0021.03"])
        self.assertEqual(middle.loc["0050_0021.01", "netz_quellen"], f"{RSV};{RVN}")
        self.assertEqual(middle.loc["0050_0021.01", "ursprung_element_nr"], "1_2.01")
        self.assertEqual(report["merged_parallel"], 1)
        self.assertEqual(len(proposals), 0)
        an.assert_unique(result)


if __name__ == "__main__":
    unittest.main()
