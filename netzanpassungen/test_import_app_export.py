#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Selbsttest für import_app_export.py mit einem erfundenen Export und einem kleinen Netz.

    .venv/bin/python netzanpassungen/test_import_app_export.py

Deckt ab: verschoben, eingefuegt, attribut, ausgeschlossen, einen Konflikt (original_coordinates
5 cm daneben), ein Protokoll, das nicht zum gespeicherten Stand passt, eine Linie `#2` einer
MultiLineString, gelöschte Einträge, virtuelle Knoten, neue Kanten und einen zweiten Lauf.
"""

import itertools
import json
import sys
import tempfile
import unittest
from pathlib import Path

import geopandas as gpd
import pandas as pd
from pyproj import Transformer
from shapely.geometry import LineString, MultiLineString, Point

sys.path.append(str(Path(__file__).resolve().parent))

import import_app_export as imp  # noqa: E402

to_wgs = Transformer.from_crs(imp.CRS, "EPSG:4326", always_xy=True)
X0, Y0 = 392000.0, 5815000.0


def line(*points):
    return LineString([(X0 + x, Y0 + y) for x, y in points])


def lnglat(x, y):
    lng, lat = to_wgs.transform(X0 + x, Y0 + y)
    return [round(lng, 7), round(lat, 7)]


def coords(*points):
    return [lnglat(x, y) for x, y in points]


_vorgang = itertools.count(1)


def change(art, **fields):
    return {"vorgang_id": f"vorgang-{next(_vorgang)}", "art": art, "beschreibung": art, "von_nutzer": "tester", "am": "2026-11-12T10:00:00Z", **fields}


def correction(ref, element_nr, original, current, attribute, changes, comment=None):
    return {
        "kind": "edge_correction",
        "kante": {"art": "ren", "ref": ref, "element_nr": element_nr},
        "original_coordinates": original,
        "coordinates": current,
        "original_attribute": {"verkehrsrichtung": "B"},
        "attribute": attribute,
        "aenderungen": changes,
        **({"kommentar": comment} if comment else {}),
    }


def stored(entry_id, data, created="2026-11-12T09:00:00Z"):
    return {"id": entry_id, "data": data, "version": 1, "created_at": created, "updated_at": created,
            "created_by": "tester", "updated_by": "tester"}


def build_network():
    rows = [
        # element_nr, bearbeitet_2025, Geometrie
        ("10000001_10000002.01", "nein", MultiLineString([line((0, 0), (50, 0), (100, 0))])),
        ("10000002_10000003.01", "nein", MultiLineString([line((0, 20), (100, 20))])),
        ("10000003_10000004.01", "nein", MultiLineString([line((0, 40), (100, 40))])),
        ("10000004_10000005.01", "nein", MultiLineString([line((0, 60), (100, 60))])),
        ("10000005_10000006.01", "nein", MultiLineString([line((0, 80), (100, 80))])),
        ("10000006_10000007.01", "nein", MultiLineString([line((0, 100), (50, 100)), line((50, 100), (100, 100))])),
        ("10000007_10000008.01", "ja", MultiLineString([line((0, 120), (100, 120))])),
        ("10000008_10000009.01", "nein", MultiLineString([line((0, 140), (100, 140))])),
    ]
    return gpd.GeoDataFrame(
        {"element_nr": [r[0] for r in rows], "bearbeitet_2025": [r[1] for r in rows],
         "laenge_m": [round(r[2].length, 1) for r in rows]},
        geometry=[r[2] for r in rows], crs=imp.CRS)


def build_entries():
    a0 = coords((0, 0), (50, 0), (100, 0))
    a1 = coords((0, 0), (50, 7), (100, 0))
    b0 = coords((0, 20), (100, 20))
    b1 = coords((0, 20), (40, 27), (100, 20))
    c0 = coords((0, 40), (100, 40))
    d0 = coords((0, 60), (100, 60))
    e0 = coords((0, 80), (100, 80))
    # 6 cm neben der Kante im Netz
    e_wrong = [[lng, lat] for lng, lat in coords((0, 80.06), (100, 80.06))]
    f0 = coords((50, 100), (100, 100))
    f1 = coords((50, 100), (100, 103))
    g0 = coords((0, 140), (100, 140))
    return [
        stored("e1", correction(
            "10000001_10000002.01", "10000001_10000002.01", a0, a1, {}, [
                change("verschoben", index=1, von=a0[1], nach=a1[1], abstand_m=7.0)])),
        stored("e2", correction(
            "10000002_10000003.01", "10000002_10000003.01", b0, b1, {}, [
                change("eingefuegt", index=1, nach=b1[1])])),
        stored("e3", correction(
            "10000003_10000004.01", "10000003_10000004.01", c0, c0,
            {"fahrbahn_typ": "richtungsfahrbahn", "fahrbahn_gruppe": "FG-0001", "verkehrsrichtung": "R"}, [
                change("attribut", feld="fahrbahn_typ", von_wert=None, nach_wert="richtungsfahrbahn"),
                change("attribut", feld="fahrbahn_gruppe", von_wert=None, nach_wert="FG-0001"),
                change("attribut", feld="verkehrsrichtung", von_wert="B", nach_wert="R", am="2026-11-12T11:00:00Z")],
            comment="Scharnweberstraße")),
        stored("e4", correction(
            "10000004_10000005.01", "10000004_10000005.01", d0, d0, {"ausgeschlossen": True}, [
                change("ausgeschlossen", von_wert=False, nach_wert=True)])),
        stored("e5", correction(
            "10000005_10000006.01", "10000005_10000006.01", e_wrong, e_wrong,
            {"verkehrsrichtung": "G"}, [change("attribut", feld="verkehrsrichtung", von_wert="B", nach_wert="G")])),
        # Das Protokoll ergibt nicht den gespeicherten Stand (Stützpunkt 1 steht woanders)
        stored("e6", correction(
            "10000008_10000009.01", "10000008_10000009.01", g0, coords((0, 140), (50, 150), (100, 140)), {}, [
                change("eingefuegt", index=1, nach=coords((50, 141))[0])])),
        # Zweite Linie der MultiLineString
        stored("e7", correction(
            "10000006_10000007.01#2", "10000006_10000007.01", f0, f1, {}, [
                change("verschoben", index=1, von=f0[1], nach=f1[1], abstand_m=3.0)])),
        # Gelöscht: darf nichts bewirken
        stored("e8", {**correction("10000001_10000002.01", "10000001_10000002.01", a0, a1, {"ausgeschlossen": True}, []),
                      "geloescht": True}),
        stored("n1", {"kind": "virtual_node", "vorgang_id": "vorgang-n1", "unbekanntes_feld": 1, "name": "V10000001-10000002", "name_vorschlag": "V10000001-10000002",
                      "lngLat": lnglat(50, 7), "traeger": {"art": "ren", "ref": "10000001_10000002.01", "station_m": 57.0}}),
        stored("n2", {"kind": "virtual_node", "name": "V99", "name_vorschlag": "V99", "lngLat": lnglat(50, 60),
                      "traeger": {"art": "ren", "ref": "10000001_10000002.01", "station_m": 10.0}}),
        stored("n3", {"kind": "virtual_node", "name": "V404", "name_vorschlag": "V404", "lngLat": lnglat(1, 1),
                      "traeger": {"art": "ren", "ref": "10000001_10000002.01", "station_m": 1.0}, "geloescht": True}),
        stored("k1", {"kind": "new_edge", "vorgang_id": "vorgang-k1", "von": "k:10000001", "bis": "v:n1", "coordinates": coords((50, 7), (60, 30)),
                      "quelle": "gezeichnet", "strassenname": "Testweg"}, created="2026-11-12T09:30:00Z"),
        stored("k2", {"kind": "new_edge", "von": "k:10000001", "bis": "v:n1", "coordinates": coords((50, 7), (70, 30)),
                      "quelle": "radfernweg", "routen_fernradweg": "D3"}, created="2026-11-12T09:40:00Z"),
        stored("k3", {"kind": "new_edge", "von": "k:10000001", "bis": "k:10000009", "coordinates": coords((0, 0), (1, 1)),
                      "quelle": "gezeichnet", "geloescht": True}),
    ]


class ImportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        build_network().to_file(self.dir / "ren_netz_gesamt.gpkg", layer="ren_netz", driver="GPKG")
        gpd.GeoDataFrame({"Knotenpunkt-ID": ["V47500003-V47500008"]}, geometry=[Point(X0 + 5000, Y0)], crs=imp.CRS).to_file(
            self.dir / "Virtuelle-Knotenpunkte.gpkg", layer=imp.VIRTUAL_NODES_LAYER, driver="GPKG")
        self.export = self.dir / "export.json"
        self.export.write_text(json.dumps({"gebiet": "test", "exported_at": "2026-11-12T12:00:00Z", "entries": build_entries()}),
                               encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def run_import(self):
        return imp.run(self.export, ren_path=self.dir / "ren_netz_gesamt.gpkg", output_dir=self.dir / "out",
                       virtual_nodes_path=self.dir / "Virtuelle-Knotenpunkte.gpkg",
                       new_edges_path=self.dir / "touristische_kanten.gpkg")

    def test_import(self):
        stats, conflicts = self.run_import()
        corrected = gpd.read_file(self.dir / "out" / "ren_netz_gesamt_korrigiert.gpkg", layer="ren_netz").set_index("element_nr")

        # verschoben: Stützpunkt 1 steht 7 m weiter nördlich, Länge wächst
        moved = list(corrected.loc["10000001_10000002.01"].geometry.geoms[0].coords)
        self.assertAlmostEqual(moved[1][1] - Y0, 7.0, delta=0.02)
        self.assertEqual(corrected.loc["10000001_10000002.01", "korrigiert"], "ja")
        self.assertGreater(corrected.loc["10000001_10000002.01", "laenge_m"], 100.0)
        self.assertEqual(corrected.loc["10000001_10000002.01", "ausgeschlossen"], "nein")  # der gelöschte Eintrag zählt nicht
        self.assertEqual(corrected.loc["10000001_10000002.01", "anzahl_vorgaenge"], 1)

        # eingefuegt: aus zwei Stützpunkten werden drei
        self.assertEqual(len(corrected.loc["10000002_10000003.01"].geometry.geoms[0].coords), 3)

        # attribut: Geometrie bleibt, Attribute gesetzt, letzter Bearbeiter gesetzt
        attributes = corrected.loc["10000003_10000004.01"]
        self.assertEqual(attributes["korrigiert"], "nein")
        self.assertEqual(attributes["attribut_korrigiert"], "ja")
        self.assertEqual((attributes["fahrbahn_typ"], attributes["fahrbahn_gruppe"], attributes["verkehrsrichtung"]),
                         ("richtungsfahrbahn", "FG-0001", "R"))
        self.assertEqual(attributes["anzahl_vorgaenge"], 3)
        self.assertEqual(attributes["letzte_aenderung_am"], "2026-11-12T11:00:00Z")
        self.assertEqual(attributes["korrektur_kommentar"], "Scharnweberstraße")

        # ausgeschlossen: bleibt markiert im Gesamtnetz, fehlt in der Kartierung
        self.assertEqual(corrected.loc["10000004_10000005.01", "ausgeschlossen"], "ja")
        mapping = gpd.read_file(self.dir / "out" / "ren_netz_kartierung_korrigiert.gpkg", layer="ren_netz")
        self.assertNotIn("10000004_10000005.01", set(mapping["element_nr"]))
        self.assertNotIn("10000007_10000008.01", set(mapping["element_nr"]))  # bearbeitet_2025 = ja
        self.assertIn("10000001_10000002.01", set(mapping["element_nr"]))
        self.assertTrue((self.dir / "out" / "ren_netz_kartierung_korrigiert.geojson").exists())

        # Konflikt 5 cm: Kante unverändert, kein Attribut, Zeile im Bericht
        self.assertEqual(corrected.loc["10000005_10000006.01", "attribut_korrigiert"], "nein")
        self.assertTrue(pd.isna(corrected.loc["10000005_10000006.01", "verkehrsrichtung"]))
        report = pd.read_csv(self.dir / "out" / "korrekturen_konflikte.csv")
        by_entry = report.set_index("eintrag_id")
        self.assertIn("cm von der Kante im Eingangsnetz ab", by_entry.loc["e5", "grund"])
        self.assertAlmostEqual(by_entry.loc["e5", "abweichung_m"], 0.06, delta=0.015)
        # Protokoll passt nicht zum Stand: nicht angewendet
        self.assertIn("ergeben nicht den gespeicherten Stand", by_entry.loc["e6", "grund"])
        self.assertEqual(corrected.loc["10000008_10000009.01", "korrigiert"], "nein")

        # Linie #2 der MultiLineString: nur der zweite Teil ändert sich
        parts = list(corrected.loc["10000006_10000007.01"].geometry.geoms)
        self.assertEqual(len(parts), 2)
        self.assertAlmostEqual(parts[0].coords[-1][1] - Y0, 100.0, delta=0.001)
        self.assertAlmostEqual(parts[1].coords[-1][1] - Y0, 103.0, delta=0.02)

        # virtuelle Knoten: n1 liegt auf der korrigierten Kante und wird angehängt, n2 steht weit daneben (Hinweis),
        # der gelöschte n3 fehlt
        nodes = gpd.read_file(self.dir / "Virtuelle-Knotenpunkte.gpkg")
        self.assertEqual(sorted(nodes["Knotenpunkt-ID"]), ["V10000001-10000002", "V47500003-V47500008", "V99"])
        self.assertIn("neben seiner Trägerkante", by_entry.loc["n2", "grund"])
        self.assertNotIn("n1", by_entry.index)
        self.assertEqual(stats["virtuelle_knoten_neu"], 2)

        # neue Kanten: Nummern zählen je Knotenpaar, gelöschte fehlt
        edges = gpd.read_file(self.dir / "touristische_kanten.gpkg", layer=imp.NEW_EDGES_LAYER).set_index("entry_id")
        self.assertEqual(sorted(edges.index), ["k1", "k2"])
        self.assertEqual(edges.loc["k1", "element_nr"], "10000001_V10000001-10000002.01")
        self.assertEqual(edges.loc["k2", "element_nr"], "10000001_V10000001-10000002.02")
        self.assertEqual((edges.loc["k2", "von_knoten"], edges.loc["k2", "bis_knoten"]), ("10000001", "V10000001-10000002"))
        self.assertEqual(edges.loc["k2", "routen_fernradweg"], "D3")

        self.assertEqual(stats["angewendet"], 5)
        self.assertEqual(stats["konflikte"], 2)

    def test_second_run_changes_nothing(self):
        self.run_import()
        nodes_before = gpd.read_file(self.dir / "Virtuelle-Knotenpunkte.gpkg")
        edges_before = gpd.read_file(self.dir / "touristische_kanten.gpkg", layer=imp.NEW_EDGES_LAYER)
        stats, _ = self.run_import()
        self.assertEqual(stats["virtuelle_knoten_neu"], 0)
        self.assertEqual(len(gpd.read_file(self.dir / "Virtuelle-Knotenpunkte.gpkg")), len(nodes_before))
        edges_after = gpd.read_file(self.dir / "touristische_kanten.gpkg", layer=imp.NEW_EDGES_LAYER)
        self.assertEqual(sorted(edges_after["entry_id"]), sorted(edges_before["entry_id"]))
        self.assertEqual(sorted(edges_after["element_nr"]), sorted(edges_before["element_nr"]))

    def test_undo_fields(self):
        original = [[13.0, 52.0], [13.1, 52.1]]
        inserted = [13.05, 52.07]
        coordinates, attribute = imp.replay(original, [
            {"vorgang_id": "a", "art": "eingefuegt", "index": 1, "nach": inserted},
            {"vorgang_id": "b", "art": "attribut", "feld": "verkehrsrichtung", "nach_wert": "R"},
            # Rücknahme von a: Zurücksetzen, dann alles außer a wiederholen
            {"vorgang_id": "c", "art": "zurueckgesetzt", "macht_rueckgaengig": "a"},
            {"vorgang_id": "c", "art": "attribut", "feld": "verkehrsrichtung", "nach_wert": "R",
             "beschreibung": "Wiederholt: Verkehrsrichtung"},
        ])
        self.assertEqual(coordinates, original)
        self.assertEqual(attribute, {"verkehrsrichtung": "R"})

    def test_replay(self):
        original = [[13.0, 52.0], [13.1, 52.1]]
        coordinates, attribute = imp.replay(original, [
            {"art": "eingefuegt", "index": 1, "nach": [13.05, 52.07]},
            {"art": "verschoben", "index": 0, "nach": [13.0, 52.01]},
            {"art": "attribut", "feld": "verkehrsrichtung", "nach_wert": "R"},
            {"art": "ausgeschlossen", "nach_wert": True},
        ])
        self.assertEqual(coordinates, [[13.0, 52.01], [13.05, 52.07], [13.1, 52.1]])
        self.assertEqual(attribute, {"verkehrsrichtung": "R", "ausgeschlossen": True})
        coordinates, attribute = imp.replay(original, [{"art": "attribut", "feld": "fahrbahn_typ", "nach_wert": "einbahnstrasse"},
                                                       {"art": "zurueckgesetzt"}])
        self.assertEqual((coordinates, attribute), (original, {}))


if __name__ == "__main__":
    unittest.main()
