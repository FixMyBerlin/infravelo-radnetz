#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Selbsttest für map_back_to_original.py mit einem erfundenen Matching-Ergebnis.

    .venv/bin/python ren-network/test_map_back_to_original.py

Original: A ist 100 m lang und gerade. Korrigiert: A hat einen Knick und ist 128,06 m lang. B ist
unverändert, C ist an einem virtuellen Knoten geteilt (Teilkanten C.1 und C.2), D gibt es nur im
korrigierten Netz (gezeichnete Kante).
"""

import sys
import tempfile
import unittest
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, MultiLineString

sys.path.append(str(Path(__file__).resolve().parent))

import map_back_to_original as zao  # noqa: E402

X0, Y0 = 392000.0, 5815000.0


def line(*points):
    return LineString([(X0 + x, Y0 + y) for x, y in points])


def network(rows):
    return gpd.GeoDataFrame({"element_nr": [r[0] for r in rows]}, geometry=[MultiLineString(r[1]) for r in rows], crs=zao.CRS)


class MapBackTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        network([("A", [line((0, 0), (100, 0))]), ("B", [line((0, 50), (100, 50))]),
                 ("C", [line((0, 100), (100, 100))]),
                 ("E", [line((0, 300), (10, 300))])]).to_file(self.dir / "original.gpkg", layer="ren_netz", driver="GPKG")
        # A: Stützpunkt in der Mitte 60 m nach Norden gezogen, die Linie ist dadurch länger
        self.bent = line((0, 0), (50, 60), (100, 0))
        network([("A", [self.bent]), ("B", [line((0, 50), (100, 50))]), ("C", [line((0, 100), (100, 100))]),
                 ("D", [line((0, 200), (30, 200))]), ("E", [line((0, 300), (0, 300))])]).to_file(self.dir / "korrigiert.gpkg", layer="ren_netz", driver="GPKG")
        gpd.GeoDataFrame({"element_nr": ["C.1", "C.2"], "elem_nr": ["C", "C"]},
                         geometry=[line((0, 100), (40, 100)), line((40, 100), (100, 100))], crs=zao.CRS).to_file(
            self.dir / "split.fgb", driver="FlatGeobuf")

        segments = [
            ("A", 0, line((0, 0), (50, 60))),                                         # erste Hälfte von A
            ("A", 1, line((50, 60), (100, 0))),                                       # zweite Hälfte
            ("B", 0, line((20, 50), (70, 50))),
            ("C.2", 0, line((40, 100), (100, 100))),                                  # Teilkante
            ("D", 0, line((0, 200), (30, 200))),                                      # gezeichnet
            ("A", 1, line((100, 0), (50, 60))),                                       # gegen die Linie (Gegenrichtung)
            ("E", 0, line((0, 300), (5, 300))),                                       # korrigierte Linie hat die Länge 0
            ("B", 0, line((20, 50), (20.0005, 50))),                                  # kürzer als 1 mm
            ("A", 0, line((50, 60), (50.0004, 59.9996))),                             # Abschnitt auf dem Original unter 1 mm
        ]
        gpd.GeoDataFrame({"sfid": range(1, len(segments) + 1), "element_nr": [s[0] for s in segments],
                          "ri": [s[1] for s in segments], "Länge": [int(s[2].length) for s in segments],
                          "fuehr": ["Radweg"] * len(segments)},
                         geometry=[s[2] for s in segments], crs=zao.CRS).to_file(self.dir / "matching.fgb", driver="FlatGeobuf")

    def tearDown(self):
        self.tmp.cleanup()

    def run_back(self):
        return zao.run(self.dir / "matching.fgb", self.dir / "out.fgb", self.dir / "original.gpkg",
                       self.dir / "korrigiert.gpkg", self.dir / "split.fgb")

    def test_map_back(self):
        output, missing = self.run_back()
        by_sfid = output.set_index("sfid")

        # Erste Hälfte von A: 0 bis 50 % der Kante, also die ersten 50 m des geraden Originals
        first = by_sfid.loc[1]
        self.assertEqual(first["kante_korrigiert"], "ja")
        self.assertAlmostEqual(first["von_anteil"], 0.0, places=3)
        self.assertAlmostEqual(first["bis_anteil"], 0.5, places=3)
        self.assertAlmostEqual(first["von_m"], 0.0, places=2)
        self.assertAlmostEqual(first["bis_m"], 50.0, places=2)
        self.assertEqual(list(first.geometry.coords), [(X0, Y0), (X0 + 50, Y0)])
        self.assertEqual(first["Länge"], 50)
        self.assertEqual(first["fuehr"], "Radweg")

        # Zweite Hälfte: 50 bis 100 m
        self.assertAlmostEqual(by_sfid.loc[2, "von_m"], 50.0, places=2)
        self.assertAlmostEqual(by_sfid.loc[2, "bis_m"], 100.0, places=2)

        # Gegen die Linie: gleiche Strecke, Geometrie und ri bleiben in der Richtung der Eingabe
        back = by_sfid.loc[6]
        self.assertEqual(list(back.geometry.coords), [(X0 + 100, Y0), (X0 + 50, Y0)])
        self.assertEqual(back["ri"], 1)
        self.assertAlmostEqual(back["von_m"], 50.0, places=2)

        # Unveränderte Kante: Geometrie wie im Ergebnis
        unchanged = by_sfid.loc[3]
        self.assertEqual(unchanged["kante_korrigiert"], "nein")
        self.assertEqual(list(unchanged.geometry.coords), [(X0 + 20, Y0 + 50), (X0 + 70, Y0 + 50)])
        self.assertAlmostEqual(unchanged["von_anteil"], 0.2, places=3)

        # Geteilte Kante: Ursprung C, Anteil bezogen auf C
        piece = by_sfid.loc[4]
        self.assertEqual(piece["ursprung_element_nr"], "C")
        self.assertEqual(piece["element_nr"], "C.2")
        self.assertAlmostEqual(piece["von_anteil"], 0.4, places=3)
        self.assertAlmostEqual(piece["bis_anteil"], 1.0, places=3)

        # Gezeichnete Kante D: nicht im Original
        self.assertNotIn(5, set(output["sfid"]))
        self.assertEqual(sorted(zip(missing["element_nr"], missing["grund"])), sorted([
            ("D", "Kante nicht im Original"),
            ("E", "Linie der korrigierten Kante hat die Länge 0"),
            ("B", "Teilsegment kürzer als 1 mm"),
            ("A", "Teilsegment kürzer als 1 mm")]))
        self.assertTrue((self.dir / "out_ohne_original.csv").exists())
        self.assertEqual(len(output), 5)
        self.assertNotIn(7, set(output["sfid"]))

    def test_pieces_in_the_result_networks_map_back_to_their_parent(self):
        """Step 1/3 write ursprung_element_nr: pieces present in both networks map directly and name their parent,
        without the intermediate file."""
        for name in ("original", "korrigiert"):
            frame = network([("C.1", [line((0, 100), (40, 100))]), ("C.2", [line((40, 100), (100, 100))])])
            frame["ursprung_element_nr"] = "C"
            frame.to_file(self.dir / f"{name}2.gpkg", layer="ren_netz", driver="GPKG")
        gpd.GeoDataFrame({"sfid": [1], "element_nr": ["C.2"], "ri": [0], "Länge": [60]},
                         geometry=[line((40, 100), (100, 100))], crs=zao.CRS).to_file(self.dir / "m2.fgb", driver="FlatGeobuf")
        output, missing = zao.run(self.dir / "m2.fgb", self.dir / "out2.fgb", self.dir / "original2.gpkg",
                                  self.dir / "korrigiert2.gpkg", self.dir / "does-not-exist.fgb")
        self.assertEqual(len(missing), 0)
        self.assertEqual(output.iloc[0]["ursprung_element_nr"], "C")
        self.assertAlmostEqual(output.iloc[0]["von_anteil"], 0.0, places=3)
        self.assertAlmostEqual(output.iloc[0]["bis_anteil"], 1.0, places=3)


if __name__ == "__main__":
    unittest.main()
