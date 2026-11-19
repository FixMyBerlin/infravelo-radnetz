#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Selbsttest für match_cycle_routes.py (Schritt 2) mit einer erfundenen Route und wenigen Kanten.

    .venv/bin/python netzanpassungen/test_match_cycle_routes.py

Deckt ab: parallele Kante wird genommen, Querstraße an einer Kreuzung nicht, parallele Straße in 35 m
nicht, eine Kante, die nur zur Hälfte neben der Route liegt, wird Kandidat, eine Detailnetzkante ohne
REN+-Kante kommt dazu (aufgenommen), eine Detailnetzkante neben einer zugeordneten REN+-Kante nicht,
die Abschnitte decken die Route lückenlos ab, feste Ids, Lücke am Ende, Kennzahlen.
"""

import sys
import unittest
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString

sys.path.append(str(Path(__file__).resolve().parent))

import match_cycle_routes as z  # noqa: E402

X0, Y0 = 392000.0, 5815000.0


def line(*points):
    return LineString([(X0 + x, Y0 + y) for x, y in points])


def lines_frame(prefix, rows):
    frame = gpd.GeoDataFrame({"element_nr": [r[0] for r in rows]}, geometry=[r[1] for r in rows], crs=z.CRS)
    frame["ref"] = z.line_refs(frame["element_nr"])
    frame["key"] = f"{prefix}:" + frame["ref"]
    frame["row"] = range(len(frame))
    return frame


def build():
    route = {"parts": [line((0, 0), (500, 0))], "offsets": np.array([0.0, 500.0]), "length": 500.0, "slug": "route-a"}
    # GPS-Linie mit Abstand zu den Kanten: Kante liegt 4 m daneben
    ren = lines_frame("ren", [
        ("1_2.01", line((0, 4), (100, 4))),            # parallel
        ("2_3.01", line((100, 4), (200, 4))),          # parallel
        ("9_9.01", line((150, -60), (150, 60))),       # Querstraße
        ("8_8.01", line((0, 35), (300, 35))),          # parallele Straße in 35 m
        ("7_7.01", line((0, 10), (70, 10), (100, 80))),  # liegt nur zur Hälfte neben der Route
    ])
    detail = lines_frame("detailnetz", [
        ("1_2.01", line((0, 4), (100, 4))),            # schon im REN+
        ("4_5.01", line((200, 3), (300, 3))),          # fehlt im REN+
        ("5_5.01", line((10, 12), (90, 12))),          # läuft neben der zugeordneten REN+-Kante 1_2.01
    ])
    detail["strassenklasse1"] = "V"
    detail["strassenklasse2"] = "STRA"
    detail["strassenname"] = "Testweg"
    detail["verkehrsrichtung"] = "B"
    in_ren = detail["element_nr"].isin({"1_2.01", "2_3.01", "9_9.01", "8_8.01", "7_7.01"}).to_numpy()
    return {"Route A": route}, ren, detail, in_ren


class MatchTest(unittest.TestCase):
    def setUp(self):
        self.routes, self.ren, self.detail, self.in_ren = build()
        self.matches = z.match_all(self.routes, self.ren, self.detail, self.in_ren)
        self.sections = z.build_sections(self.routes, self.matches, self.ren, self.detail)

    def taken(self):
        return set(self.matches.loc[self.matches["anteil"] >= z.MATCH_SHARE, "key"])

    def test_matching(self):
        taken = self.taken()
        self.assertTrue({"ren:1_2.01", "ren:2_3.01", "detailnetz:4_5.01", "detailnetz:5_5.01"} <= taken)
        self.assertNotIn("ren:9_9.01", taken)  # Querstraße: nah, aber nicht parallel
        self.assertNotIn("ren:8_8.01", taken)  # 35 m entfernt
        self.assertNotIn("detailnetz:1_2.01", set(self.matches["key"]))  # Detailnetz nur, wo das REN+ fehlt
        candidate = self.matches.set_index("key").loc["ren:7_7.01", "anteil"]
        self.assertTrue(z.CANDIDATE_SHARE <= candidate < z.MATCH_SHARE, candidate)
        # die Querstraße hat Stützpunkte nah an der Route, aber keinen parallelen
        self.assertNotIn("ren:9_9.01", set(self.matches["key"]))

    def test_sections_cover_the_route_without_gaps(self):
        sections = self.sections.sort_values("station_von_m")
        self.assertEqual(sections["station_von_m"].iloc[0], 0)
        self.assertEqual(sections["station_bis_m"].iloc[-1], 500)
        self.assertTrue((sections["station_von_m"].iloc[1:].to_numpy() == sections["station_bis_m"].iloc[:-1].to_numpy()).all())
        self.assertAlmostEqual(sections["laenge_m"].sum(), 500.0, delta=0.5)
        self.assertEqual(sections["id"].is_unique, True)

    def test_states_ids_and_edges(self):
        by_id = self.sections.set_index("id")
        # je REN+-Kante ein Abschnitt (die Kantenmenge wechselt), dann Detailnetz, dann Lücke
        self.assertEqual(list(by_id["zustand"]), ["auf_ren", "auf_ren", "aufgenommen", "luecke"])
        first = by_id.iloc[0]
        self.assertEqual(list(by_id.index), ["route-a@0-100", "route-a@100-200", "route-a@200-300", "route-a@300-500"])
        self.assertEqual(first["kanten"], "ren:1_2.01")
        self.assertEqual(by_id.loc["route-a@100-200", "kanten"], "ren:2_3.01")
        # die Detailnetzkante neben der zugeordneten REN+-Kante kommt nicht in den Abschnitt
        self.assertNotIn("detailnetz:5_5.01", first["kanten"])
        self.assertIn("ren:7_7.01", first["kandidaten"])
        self.assertEqual(by_id.loc["route-a@200-300", "kanten"], "detailnetz:4_5.01")
        self.assertEqual(by_id.loc["route-a@300-500", "kanten"], "")
        self.assertTrue(pd.isna(by_id.loc["route-a@300-500", "hausdorff_m"]))
        self.assertAlmostEqual(first["hausdorff_m"], 4.0, delta=0.5)
        self.assertAlmostEqual(first["p95_m"], 4.0, delta=0.5)

    def test_ids_are_stable(self):
        again = z.build_sections(self.routes, z.match_all(self.routes, self.ren, self.detail, self.in_ren), self.ren, self.detail)
        self.assertEqual(list(again["id"]), list(self.sections["id"]))

    def test_assignment_on_network(self):
        roh = gpd.GeoDataFrame({
            "lfd_nr": range(1, 6), "element_nr": list(self.ren["element_nr"]),
            "element_nr_berechnet": "nein", "von_knoten": pd.array([1, 2, 9, 8, 7], dtype="Int64"),
            "bis_knoten": pd.array([2, 3, 9, 8, 7], dtype="Int64"), "bezirksnummer": pd.array([1] * 5, dtype="Int64"),
            "strassenname": None, "radverkehrsnetz": "Radvorrangnetz", "strassenklasse": None, "netz_quellen": "radverkehrsnetz",
            "in_detailnetz": "ja", "hauptverkehrsstrasse": "nein", "bearbeitet_2025": "nein", "anteil_2025": 0.0,
            "routen_fernradweg": None, "laenge_m": 100.0},
            geometry=self.ren.geometry, crs=z.CRS)
        network = z.apply_assignment(roh, self.ren, self.detail, self.matches, self.sections)
        by_nr = network.set_index("element_nr")
        self.assertEqual(by_nr.loc["1_2.01", "routen_fernradweg"], "Route A")
        self.assertEqual(by_nr.loc["1_2.01", "routen_quelle"], "auto")
        self.assertEqual(by_nr.loc["1_2.01", "quelle"], "radnetz")
        self.assertTrue(pd.isna(by_nr.loc["9_9.01", "routen_fernradweg"]))
        self.assertTrue(pd.isna(by_nr.loc["7_7.01", "routen_fernradweg"]))  # Kandidat: nicht automatisch genommen
        added = by_nr.loc["4_5.01"]
        self.assertEqual((added["quelle"], added["grund_aufnahme"], added["routen_quelle"]),
                         ("detailnetz_radfernweg", "radfernweg", "auto"))
        self.assertEqual(len(network), 6)
        self.assertNotIn("5_5.01", by_nr.index)

    def test_gaps_are_the_long_luecke_sections(self):
        gaps = z.gaps_of(self.sections)
        self.assertEqual(list(gaps["id"]), ["route-a@300-500"])
        self.assertEqual(list(gaps["name"]), ["Route A"])


if __name__ == "__main__":
    unittest.main()
