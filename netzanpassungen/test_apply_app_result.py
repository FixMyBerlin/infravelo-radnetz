#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Selbsttest für apply_app_result.py (Schritt 3) mit einem erfundenen Export und einem kleinen Netz.

    .venv/bin/python netzanpassungen/test_apply_app_result.py

Deckt ab: verschoben, eingefuegt, attribut, ausgeschlossen, einen Konflikt (original_coordinates
5 cm daneben), ein Protokoll, das nicht zum gespeicherten Stand passt, eine Linie `#2` einer
MultiLineString, gelöschte Einträge, virtuelle Knoten, neue Kanten und einen zweiten Lauf.
Dazu die Ergebnisnetze: Kundennetz ohne Lagekorrekturen, Arbeitsnetz mit lage_korrigiert und
Kennzahlen, die Markierungsspalten, Abschnitts-Zuordnungen (zugeordnet, Umlegung einer
automatischen Zuordnung, von Hand aufgenommene Detailnetzkante, keine_aktion, unbekannter
Abschnitt oder unbekannte Kante) und die Kartierung beider Netze.
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

import apply_app_result as imp  # noqa: E402

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
    """Netz wie aus Schritt 2 (ren_netz_auto.gpkg): Rohnetz mit verkehrsrichtung, quelle und automatischer Radfernweg-Zuordnung."""
    rows = [
        # element_nr, bearbeitet_2025, Geometrie, routen_fernradweg (auto), quelle
        ("10000001_10000002.01", "nein", MultiLineString([line((0, 0), (50, 0), (100, 0))]), None, "radnetz"),
        ("10000002_10000003.01", "nein", MultiLineString([line((0, 20), (100, 20))]), "Route D", "radnetz"),
        ("10000003_10000004.01", "nein", MultiLineString([line((0, 40), (100, 40))]), None, "radnetz"),
        ("10000004_10000005.01", "nein", MultiLineString([line((0, 60), (100, 60))]), None, "radnetz"),
        ("10000005_10000006.01", "nein", MultiLineString([line((0, 80), (100, 80))]), None, "radnetz"),
        ("10000006_10000007.01", "nein", MultiLineString([line((0, 100), (50, 100)), line((50, 100), (100, 100))]), None, "radnetz"),
        ("10000007_10000008.01", "ja", MultiLineString([line((0, 120), (100, 120))]), None, "radnetz"),
        ("10000008_10000009.01", "nein", MultiLineString([line((0, 140), (100, 140))]), "Route B", "radnetz"),
        ("10000009_10000010.01", "nein", MultiLineString([line((0, 160), (100, 160))]), None, "radnetz"),
        # in Schritt 2 aufgenommene Detailnetzkante
        ("80000001_80000002.01", "nein", MultiLineString([line((0, 200), (100, 200))]), "Route C", "detailnetz_radfernweg"),
    ]
    return gpd.GeoDataFrame(
        {"lfd_nr": list(range(1, len(rows) + 1)),
         "element_nr": [r[0] for r in rows], "bearbeitet_2025": [r[1] for r in rows],
         "laenge_m": [round(r[2].length, 1) for r in rows],
         "element_nr_berechnet": ["nein"] * len(rows),
         "von_knoten": pd.array([int(r[0].split("_")[0]) for r in rows], dtype="Int64"),
         "bis_knoten": pd.array([int(r[0].split("_")[1].split(".")[0]) for r in rows], dtype="Int64"),
         "bezirksnummer": pd.array([1] * len(rows), dtype="Int64"),
         "strassenname": [None] * len(rows), "radverkehrsnetz": ["Radvorrangnetz"] * len(rows),
         "strassenklasse": [None] * len(rows), "netz_quellen": ["radverkehrsnetz"] * len(rows),
         "in_detailnetz": ["ja"] * len(rows), "hauptverkehrsstrasse": ["nein"] * len(rows),
         "anteil_2025": [0.0] * len(rows),
         "verkehrsrichtung": ["B"] * len(rows),
         "quelle": [r[4] for r in rows],
         "grund_aufnahme": [("radfernweg" if r[4] != "radnetz" else None) for r in rows],
         "routen_fernradweg": [r[3] for r in rows],
         "routen_quelle": [("auto" if r[3] else None) for r in rows]},
        geometry=[r[2] for r in rows], crs=imp.CRS)


def build_detailnetz():
    """Detailnetz-Datei für von Hand zugeordnete Kanten (Spalten wie die Datei der Senatsverwaltung)."""
    rows = [
        ("10000002_10000003.01", MultiLineString([line((0, 20), (100, 20))])),   # liegt schon im Netz
        ("70000001_70000002.01", MultiLineString([line((0, 300), (100, 300))])),  # fehlt im Netz
        ("80000001_80000002.01", MultiLineString([line((0, 200), (100, 200))])),  # automatisch aufgenommen
    ]
    return gpd.GeoDataFrame(
        {"element_nr": [r[0] for r in rows], "beginnt_bei_vp": [r[0].split("_")[0] for r in rows],
         "endet_bei_vp": [r[0].split("_")[1].split(".")[0] for r in rows], "strassenname": ["Testweg"] * len(rows),
         "verkehrsebene": [0] * len(rows), "okstra_id": ["x"] * len(rows), "verkehrsrichtung": ["R", "R", "B"],
         "strassenklasse1": ["V", "V", "V"], "strassenklasse2": ["STRA"] * len(rows)},
        geometry=[r[1] for r in rows], crs=imp.CRS)


def build_sections():
    """Abschnitte aus Schritt 2 (radfernweg_abschnitte.gpkg): id, radfernweg, kanten der automatischen Zuordnung."""
    rows = [
        ("route-a@0-100", "Route A", ""),
        ("route-a@100-200", "Route A", ""),
        ("route-b@0-100", "Route B", "ren:10000008_10000009.01"),
        ("route-c@0-100", "Route C", "detailnetz:80000001_80000002.01"),
        ("route-d@0-100", "Route D", "ren:10000002_10000003.01"),
        ("route-e@0-100", "Route E", ""),
        ("route-f@0-50", "Route F", ""),
        ("route-g@0-50", "Route G", ""),
        ("route-h@0-50", "Route H", ""),
        ("route-i@0-50", "Route I", ""),
    ]
    return gpd.GeoDataFrame(
        {"id": [r[0] for r in rows], "radfernweg": [r[1] for r in rows], "kanten": [r[2] for r in rows]},
        geometry=[line((0, 500 + 10 * i), (100, 500 + 10 * i)) for i in range(len(rows))], crs=imp.CRS)


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
                change("ausgeschlossen", von_wert=False, nach_wert=True)], comment="Tunnel")),
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
        # teilt die REN+-Kante 10000009_10000010.01 bei 40 m; die gezeichneten Kanten k1 und k2 enden an ihm
        stored("n1", {"kind": "virtual_node", "vorgang_id": "vorgang-n1", "unbekanntes_feld": 1, "name": "V10000001-10000002", "name_vorschlag": "V10000001-10000002",
                      "lngLat": lnglat(40, 160), "traeger": {"art": "ren", "ref": "10000009_10000010.01", "station_m": 40.0}}),
        stored("n2", {"kind": "virtual_node", "name": "V99", "name_vorschlag": "V99", "lngLat": lnglat(50, 60),
                      "traeger": {"art": "ren", "ref": "10000001_10000002.01", "station_m": 10.0}}),
        stored("n3", {"kind": "virtual_node", "name": "V404", "name_vorschlag": "V404", "lngLat": lnglat(1, 1),
                      "traeger": {"art": "ren", "ref": "10000001_10000002.01", "station_m": 1.0}, "geloescht": True}),
        stored("k1", {"kind": "new_edge", "vorgang_id": "vorgang-k1", "von": "k:10000001", "bis": "v:n1", "coordinates": coords((50, 7), (60, 30)),
                      "quelle": "gezeichnet", "strassenname": "Testweg"}, created="2026-11-12T09:30:00Z"),
        stored("k2", {"kind": "new_edge", "von": "k:10000001", "bis": "v:n1", "coordinates": coords((50, 7), (70, 30)),
                      "quelle": "radfernweg", "routen_fernradweg": "D3"}, created="2026-11-12T09:40:00Z"),
        # gezeichnet zwischen zwei vorhandenen Knoten, vom virtuellen Knoten n4 auf ihr selbst geteilt
        stored("k4", {"kind": "new_edge", "von": "k:10000003", "bis": "k:10000005", "coordinates": coords((0, 40), (50, 50), (100, 60)),
                      "quelle": "radfernweg", "routen_fernradweg": "D4"}, created="2026-11-12T09:50:00Z"),
        stored("n4", {"kind": "virtual_node", "name": "V10000003-10000005", "name_vorschlag": "V10000003-10000005", "lngLat": lnglat(50, 50),
                      "traeger": {"art": "neu", "ref": "k4", "station_m": 70.0}}),
        stored("k3", {"kind": "new_edge", "von": "k:10000001", "bis": "k:10000009", "coordinates": coords((0, 0), (1, 1)),
                      "quelle": "gezeichnet", "geloescht": True}),
    ] + build_assignments()


def assignment(entry_id, section_id, route, art, keys, comment=None, **extra):
    return stored(entry_id, {"kind": "section_assignment", "abschnitt": {"id": section_id, "radfernweg": route},
                             "art": art, "kanten": keys, "abschnitt_coordinates": coords((0, 500), (100, 500)),
                             **({"kommentar": comment} if comment else {}), **extra})


def build_assignments():
    return [
        # zugeordnet auf eine REN+-Kante (die zugleich eine Attributkorrektur hat)
        assignment("z1", "route-a@0-100", "Route A", "zugeordnet", ["ren:10000003_10000004.01"], comment="Hinweis"),
        # Detailnetzkante, die noch nicht im Netz ist: wird aufgenommen
        assignment("z2", "route-a@100-200", "Route A", "zugeordnet", ["detailnetz:70000001_70000002.01"]),
        # Umlegung: Route B lag automatisch auf ...08_...09, jetzt auf ...05_...06
        assignment("z3", "route-b@0-100", "Route B", "zugeordnet", ["ren:10000005_10000006.01"]),
        # Umlegung weg von einer automatisch aufgenommenen Detailnetzkante: sie fällt weg
        assignment("z4", "route-c@0-100", "Route C", "zugeordnet", ["ren:10000001_10000002.01"]),
        # Kante hat schon eine automatische Route (D): E kommt hinzu, die Quelle wird "auto; manuell"
        assignment("z5", "route-e@0-100", "Route E", "zugeordnet", ["ren:10000002_10000003.01"]),
        # Detailnetzkante, die schon als REN+-Kante im Netz liegt: nur die Route kommt dazu
        assignment("z6", "route-g@0-50", "Route G", "zugeordnet", ["detailnetz:10000002_10000003.01"]),
        assignment("z7", "route-f@0-50", "Route F", "keine_aktion", [], comment="gibt es nicht"),
        # Konflikte: unbekannter Abschnitt, unbekannte Kante, falscher Radfernweg
        assignment("z8", "route-x@0-100", "Route X", "zugeordnet", ["ren:10000003_10000004.01"]),
        assignment("z9", "route-h@0-50", "Route H", "zugeordnet", ["ren:99999999_99999999.01"]),
        assignment("z10", "route-i@0-50", "Route A", "zugeordnet", ["ren:10000003_10000004.01"]),
        # gelöscht: ohne Wirkung
        assignment("z11", "route-f@0-50", "Route F", "zugeordnet", ["ren:10000007_10000008.01"], geloescht=True),
    ]


class ImportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        build_network().to_file(self.dir / "ren_netz_auto.gpkg", layer="ren_netz", driver="GPKG")
        build_sections().to_file(self.dir / "radfernweg_abschnitte.gpkg", layer=imp.SECTIONS_LAYER, driver="GPKG")
        build_detailnetz().to_file(self.dir / "detailnetz.gpkg", driver="GPKG")
        self.export = self.dir / "export.json"
        self.export.write_text(json.dumps({"gebiet": "test", "exported_at": "2026-11-12T12:00:00Z", "entries": build_entries()}),
                               encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def run_import(self, export=None):
        return imp.run(self.export if export is None else export, ren_path=self.dir / "ren_netz_auto.gpkg",
                       output_dir=self.dir / "out",
                       virtual_nodes_path=self.dir / "app-output" / "virtuelle_knoten.gpkg",
                       new_edges_path=self.dir / "app-output" / "touristische_kanten.gpkg",
                       detail_path=self.dir / "detailnetz.gpkg", sections_path=self.dir / "radfernweg_abschnitte.gpkg")

    def read(self, name):
        return gpd.read_file(self.dir / "out" / name, layer="ren_netz").set_index("element_nr")

    def test_import(self):
        stats, conflicts = self.run_import()
        corrected = self.read("ren_netz_korrigiert.gpkg")
        customer = self.read("ren_netz.gpkg")

        # verschoben: Stützpunkt 1 steht 7 m weiter nördlich, Länge wächst
        moved = list(corrected.loc["10000001_10000002.01"].geometry.geoms[0].coords)
        self.assertAlmostEqual(moved[1][1] - Y0, 7.0, delta=0.02)
        self.assertEqual(corrected.loc["10000001_10000002.01", "lage_korrigiert"], "ja")
        self.assertGreater(corrected.loc["10000001_10000002.01", "laenge_m"], 100.0)
        self.assertEqual(corrected.loc["10000001_10000002.01", "ausgeschlossen"], "nein")  # der gelöschte Eintrag zählt nicht
        self.assertEqual(corrected.loc["10000001_10000002.01", "anzahl_vorgaenge"], 1)
        # Kennzahlen im Arbeitsnetz: ein Stützpunkt 7 m verschoben, Dreieck 100 m x 7 m / 2 = 350 m2
        row = corrected.loc["10000001_10000002.01"]
        self.assertAlmostEqual(row["hausdorff_m"], 7.0, delta=0.05)
        self.assertAlmostEqual(row["max_verschiebung_m"], 7.0, delta=0.05)
        self.assertAlmostEqual(row["differenzflaeche_m2"], 350.0, delta=1.0)
        self.assertAlmostEqual(row["laenge_alt_m"], 100.0, delta=0.1)
        self.assertGreater(row["laenge_neu_m"], 100.5)
        self.assertTrue(pd.isna(corrected.loc["10000002_10000003.01", "hausdorff_m"]) is False)  # eingefuegt: auch gemessen
        self.assertTrue(pd.isna(corrected.loc["10000003_10000004.01", "hausdorff_m"]))  # nur Attribute: keine Lage-Kennzahl

        # Kundennetz: Originallage, aber alle Markierungen; ohne lage_korrigiert und Kennzahlen
        customer_moved = list(customer.loc["10000001_10000002.01"].geometry.geoms[0].coords)
        self.assertAlmostEqual(customer_moved[1][1] - Y0, 0.0, delta=0.001)
        self.assertAlmostEqual(customer.loc["10000001_10000002.01", "laenge_m"], 100.0, delta=0.1)
        for column in imp.LAGE_COLUMNS:
            self.assertNotIn(column, customer.columns)
            self.assertIn(column, corrected.columns)
        self.assertEqual(customer.loc["10000003_10000004.01", "verkehrsrichtung"], "R")
        self.assertEqual(customer.loc["10000003_10000004.01", "fahrbahn_typ"], "richtungsfahrbahn")
        self.assertEqual(customer.loc["10000004_10000005.01", "ausgeschlossen"], "ja")
        self.assertEqual(sorted(customer.index), sorted(corrected.index))  # dieselben Kanten

        # eingefuegt: aus zwei Stützpunkten werden drei
        self.assertEqual(len(corrected.loc["10000002_10000003.01"].geometry.geoms[0].coords), 3)

        # attribut: Geometrie bleibt, Attribute gesetzt, letzter Bearbeiter gesetzt
        attributes = corrected.loc["10000003_10000004.01"]
        self.assertEqual(attributes["lage_korrigiert"], "nein")
        self.assertEqual(attributes["verkehrsrichtung_original"], "B")
        self.assertEqual(attributes["verkehrsrichtung_korrigiert"], "ja")
        self.assertEqual(attributes["eintrag_ids"], "e3; z1")
        self.assertEqual((attributes["fahrbahn_typ"], attributes["fahrbahn_gruppe"], attributes["verkehrsrichtung"]),
                         ("richtungsfahrbahn", "FG-0001", "R"))
        self.assertEqual(attributes["anzahl_vorgaenge"], 3)
        self.assertEqual(attributes["letzte_aenderung_am"], "2026-11-12T11:00:00Z")
        self.assertEqual(attributes["korrektur_kommentar"], "Scharnweberstraße")

        # ausgeschlossen: bleibt markiert im Gesamtnetz, fehlt in der Kartierung
        self.assertEqual(corrected.loc["10000004_10000005.01", "ausgeschlossen"], "ja")
        self.assertEqual(corrected.loc["10000004_10000005.01", "ausschluss_grund"], "Tunnel")
        self.assertEqual(corrected.loc["10000004_10000005.01", "eintrag_ids"], "e4")
        # Kartierung beider Netze: ohne bearbeitet_2025 = ja und ohne ausgeschlossene Kanten
        for name in ("ren_netz_kartierung_korrigiert", "ren_netz_kartierung"):
            mapping = gpd.read_file(self.dir / "out" / f"{name}.gpkg", layer="ren_netz")
            self.assertNotIn("10000004_10000005.01", set(mapping["element_nr"]), name)
            self.assertNotIn("10000007_10000008.01", set(mapping["element_nr"]), name)  # bearbeitet_2025 = ja
            self.assertIn("10000001_10000002.01", set(mapping["element_nr"]), name)
            self.assertTrue((self.dir / "out" / f"{name}.geojson").exists())

        # Konflikt 5 cm: Kante unverändert, kein Attribut, Zeile im Bericht
        self.assertEqual(corrected.loc["10000005_10000006.01", "verkehrsrichtung_korrigiert"], "nein")
        self.assertEqual(corrected.loc["10000005_10000006.01", "verkehrsrichtung"], "B")  # unverändert, nicht G
        report = pd.read_csv(self.dir / "out" / "korrekturen_konflikte.csv")
        by_entry = report.set_index("eintrag_id")
        self.assertIn("cm von der Kante im Eingangsnetz ab", by_entry.loc["e5", "grund"])
        self.assertAlmostEqual(by_entry.loc["e5", "abweichung_m"], 0.06, delta=0.015)
        # Protokoll passt nicht zum Stand: nicht angewendet
        self.assertIn("ergeben nicht den gespeicherten Stand", by_entry.loc["e6", "grund"])
        self.assertEqual(corrected.loc["10000008_10000009.01", "lage_korrigiert"], "nein")

        # Linie #2 der MultiLineString: nur der zweite Teil ändert sich
        parts = list(corrected.loc["10000006_10000007.01"].geometry.geoms)
        self.assertEqual(len(parts), 2)
        self.assertAlmostEqual(parts[0].coords[-1][1] - Y0, 100.0, delta=0.001)
        self.assertAlmostEqual(parts[1].coords[-1][1] - Y0, 103.0, delta=0.02)

        # virtuelle Knoten: alle nicht gelöschten Einträge stehen in output/virtuelle_knoten.gpkg (n1 liegt auf der
        # korrigierten Kante, n2 steht weit daneben und bekommt einen Hinweis), der gelöschte n3 fehlt
        nodes = gpd.read_file(self.dir / "app-output" / "virtuelle_knoten.gpkg").set_index("Knotenpunkt-ID")
        self.assertEqual(sorted(nodes.index), ["V10000001-10000002", "V10000003-10000005", "V99"])
        self.assertEqual(nodes.loc["V10000001-10000002", "traeger_element_nr"], "10000009_10000010.01")
        self.assertEqual(nodes.loc["V10000001-10000002", "ist_virtuell"], 1)
        self.assertEqual(nodes.loc["V10000001-10000002", "eintrag_id"], "n1")
        self.assertAlmostEqual(nodes.loc["V10000001-10000002", "station_m"], 40.0)
        self.assertEqual(nodes.crs.to_epsg(), 25833)
        self.assertFalse((self.dir / "Virtuelle-Knotenpunkte.gpkg").exists())
        self.assertIn("neben seiner Trägerkante", by_entry.loc["n2", "grund"])
        self.assertNotIn("n1", by_entry.index)
        self.assertEqual(stats["virtuelle_knoten"], 3)

        # neue Kanten: Nummern zählen je Knotenpaar, gelöschte fehlt
        edges = gpd.read_file(self.dir / "app-output" / "touristische_kanten.gpkg", layer=imp.NEW_EDGES_LAYER).set_index("entry_id")
        self.assertEqual(sorted(edges.index), ["k1", "k2", "k4"])
        self.assertEqual(edges.loc["k1", "element_nr"], "10000001_V10000001-10000002.01")
        self.assertEqual(edges.loc["k2", "element_nr"], "10000001_V10000001-10000002.02")
        self.assertEqual((edges.loc["k2", "von_knoten"], edges.loc["k2", "bis_knoten"]), ("10000001", "V10000001-10000002"))
        self.assertEqual(edges.loc["k2", "routen_fernradweg"], "D3")

        self.assertEqual(stats["angewendet"], 5)
        self.assertEqual(stats["konflikte"], 2)

        self.check_assignments(stats, by_entry, corrected, customer)
        self.check_drawn_edges_and_splits(stats, corrected, customer)

    def check_drawn_edges_and_splits(self, stats, corrected, customer):
        """Gezeichnete Kanten und Teilung an virtuellen Knoten, in beiden Netzen und ihrer Kartierung."""
        mappings = {"ren_netz": customer, "ren_netz_korrigiert": corrected}
        for name, network in mappings.items():
            # k1/k2: zwischen einem vorhandenen Knoten und dem virtuellen Knoten n1; nn zählt je Knotenpaar
            k2 = network.loc["10000001_V10000001-10000002.02"]
            self.assertEqual((k2["quelle"], k2["routen_fernradweg"], k2["routen_quelle"], k2["eintrag_ids"]),
                             ("neu_gezeichnet", "D3", "manuell", "k2"), name)
            self.assertEqual((k2["von_knoten"], k2["bis_knoten"]), ("10000001", "V10000001-10000002"), name)
            self.assertEqual(k2["bearbeitet_2025"], "nein", name)
            k1 = network.loc["10000001_V10000001-10000002.01"]
            self.assertEqual((k1["quelle"], k1["strassenname"]), ("neu_gezeichnet", "Testweg"), name)
            self.assertTrue(pd.isna(k1["routen_fernradweg"]) and pd.isna(k1["routen_quelle"]), name)
            # die gelöschte k3 fehlt
            self.assertNotIn("10000001_10000009.01", network.index, name)
            # REN+-Kante vom virtuellen Knoten n1 bei 40 m geteilt: die Ursprungskante entfällt
            self.assertNotIn("10000009_10000010.01", network.index, name)
            first, second = network.loc["10000009_V10000001-10000002.01"], network.loc["V10000001-10000002_10000010.01"]
            self.assertEqual((first["ursprung_element_nr"], second["ursprung_element_nr"]), ("10000009_10000010.01",) * 2, name)
            self.assertAlmostEqual(first["laenge_m"], 40.0, delta=0.1, msg=name)
            self.assertAlmostEqual(second["laenge_m"], 60.0, delta=0.1, msg=name)
            self.assertAlmostEqual(first.geometry.geoms[0].coords[-1][0] - X0, 40.0, delta=0.05, msg=name)
            self.assertEqual((first["von_knoten"], first["bis_knoten"]), ("10000009", "V10000001-10000002"), name)
            self.assertEqual(first["eintrag_ids"], "n1", name)
            self.assertEqual(first["quelle"], "radnetz", name)
            self.assertNotEqual(first["lfd_nr"], second["lfd_nr"], name)
            # k4: zwischen zwei vorhandenen Knoten gezeichnet, an n4 selbst geteilt: der Teil trägt die Route
            self.assertNotIn("10000003_10000005.01", network.index, name)
            part = network.loc["10000003_V10000003-10000005.01"]
            other = network.loc["V10000003-10000005_10000005.01"]
            self.assertEqual(part["ursprung_element_nr"], "10000003_10000005.01", name)
            self.assertEqual((part["quelle"], part["routen_fernradweg"], part["routen_quelle"], part["grund_aufnahme"]),
                             ("neu_gezeichnet", "D4", "manuell", "radfernweg_manuell"), name)
            self.assertEqual(part["eintrag_ids"], "k4; n4", name)
            self.assertEqual(other["von_knoten"], "V10000003-10000005", name)
            self.assertAlmostEqual(part["laenge_m"] + other["laenge_m"], LineString([(0, 40), (50, 50), (100, 60)]).length, delta=0.1, msg=name)
            # n2 liegt 60 m neben seiner Trägerkante: sie bleibt ganz
            self.assertFalse(any("V99" in str(number) for number in network.index), name)
        for name in ("ren_netz_kartierung", "ren_netz_kartierung_korrigiert"):
            mapping = gpd.read_file(self.dir / "out" / f"{name}.gpkg", layer="ren_netz")
            numbers = set(mapping["element_nr"])
            self.assertIn("10000009_V10000001-10000002.01", numbers, name)
            self.assertIn("10000003_V10000003-10000005.01", numbers, name)
            self.assertNotIn("10000009_10000010.01", numbers, name)
        self.assertEqual(stats["geteilte_kanten"], 2)
        self.assertEqual(stats["teilkanten"], 4)
        self.assertEqual(stats["knoten_neben_traeger"], 1)

    def check_assignments(self, stats, by_entry, corrected, customer):
        """Abschnitts-Zuordnungen z1 bis z11."""
        for name, network in (("Arbeitsnetz", corrected), ("Kundennetz", customer)):
            # z1: manuell auf eine REN+-Kante, mit der KV-Id und dem Kommentar der Korrektur nebeneinander
            self.assertEqual(network.loc["10000003_10000004.01", "routen_fernradweg"], "Route A", name)
            self.assertEqual(network.loc["10000003_10000004.01", "routen_quelle"], "manuell", name)
            # z2: Detailnetzkante, die im Netz fehlte: neue Zeile, markiert
            added = network.loc["70000001_70000002.01"]
            self.assertEqual((added["quelle"], added["grund_aufnahme"], added["routen_fernradweg"], added["routen_quelle"]),
                             ("detailnetz_manuell", "radfernweg_manuell", "Route A", "manuell"), name)
            self.assertEqual(added["eintrag_ids"], "z2", name)
            self.assertEqual(added["verkehrsrichtung"], "R", name)  # aus dem Detailnetz
            self.assertEqual(added["strassenname"], "Testweg", name)
            self.assertEqual((added["von_knoten"], added["bis_knoten"]), ("70000001", "70000002"), name)
            self.assertEqual(added["bearbeitet_2025"], "nein", name)
            self.assertAlmostEqual(added["laenge_m"], 100.0, delta=0.1, msg=name)
            # z3: Umlegung von Route B: sie liegt jetzt auf ...05_...06 und nicht mehr auf ...08_...09
            self.assertEqual(network.loc["10000005_10000006.01", "routen_fernradweg"], "Route B", name)
            self.assertEqual(network.loc["10000005_10000006.01", "routen_quelle"], "manuell", name)
            self.assertTrue(pd.isna(network.loc["10000008_10000009.01", "routen_fernradweg"]), name)
            self.assertTrue(pd.isna(network.loc["10000008_10000009.01", "routen_quelle"]), name)
            # z4: Umlegung weg von einer automatisch aufgenommenen Detailnetzkante: sie fällt weg
            self.assertNotIn("80000001_80000002.01", network.index, name)
            self.assertEqual(network.loc["10000001_10000002.01", "routen_fernradweg"], "Route C", name)
            # z5: automatische Route D bleibt, E kommt dazu; z6 (Detailnetzkante derselben element_nr): G
            self.assertEqual(network.loc["10000002_10000003.01", "routen_fernradweg"], "Route D; Route E; Route G", name)
            self.assertEqual(network.loc["10000002_10000003.01", "routen_quelle"], "auto; manuell", name)
            # z6: eine Detailnetzkante, die schon als REN+-Kante im Netz liegt, wird nicht doppelt aufgenommen
            self.assertEqual(list(network.index).count("10000002_10000003.01"), 1, name)
            self.assertEqual(network.loc["10000002_10000003.01", "eintrag_ids"], "e2; z5; z6", name)
            # z7 (keine_aktion) und z11 (gelöscht) ändern nichts
            self.assertTrue(pd.isna(network.loc["10000007_10000008.01", "routen_fernradweg"]), name)
            self.assertEqual(len(network), 10 - 1 + 1 + 3 + 1 + 1, name)  # Zuordnung -1 +1, gezeichnet +3, zwei Teilungen +1 +1
        self.assertEqual(stats["zuordnung_zugeordnet"], 6)
        self.assertEqual(stats["zuordnung_keine_aktion"], 1)
        self.assertEqual(stats["zuordnung_aufgenommen"], 1)
        self.assertEqual(stats["zuordnung_umgelegt"], 2)
        self.assertEqual(stats["zuordnung_konflikte"], 3)
        # Konflikte: unbekannter Abschnitt, unbekannte Kante, falscher Radfernweg
        self.assertIn("nicht in radfernweg_abschnitte.gpkg", by_entry.loc["z8", "grund"])
        self.assertIn("ren:99999999_99999999.01 nicht im Netz", by_entry.loc["z9", "grund"])
        self.assertIn("gehört zu Route I", by_entry.loc["z10", "grund"])
        self.assertNotIn("z11", by_entry.index)
        listing = pd.read_csv(self.dir / "out" / "radfernweg_zuordnungen.csv").set_index("eintrag_id")
        self.assertEqual(listing.loc["z7", "art"], "keine_aktion")
        self.assertEqual(listing.loc["z7", "status"], "angewendet")
        self.assertEqual(listing.loc["z1", "kommentar"], "Hinweis")
        self.assertEqual(listing.loc["z8", "status"], "konflikt")
        self.assertIn("ins Netz aufgenommen", listing.loc["z2", "hinweis"])
        self.assertIn("löst 1 automatisch zugeordnete Kanten ab", listing.loc["z3", "hinweis"])

    def test_split_on_a_corrected_edge(self):
        """Der Knoten sitzt auf der verschobenen Kante: das Arbeitsnetz teilt am Knick, das Kundennetz bei gleichem Anteil."""
        entries = [e for e in build_entries() if e["id"] == "e1"]
        entries.append(stored("nx", {"kind": "virtual_node", "name": "VX", "name_vorschlag": "VX", "lngLat": lnglat(50, 7),
                                     "traeger": {"art": "ren", "ref": "10000001_10000002.01", "station_m": 50.5}}))
        self.export.write_text(json.dumps({"gebiet": "test", "exported_at": "x", "entries": entries}), encoding="utf-8")
        self.run_import()
        corrected, customer = self.read("ren_netz_korrigiert.gpkg"), self.read("ren_netz.gpkg")
        for network in (corrected, customer):
            self.assertNotIn("10000001_10000002.01", network.index)
        first = corrected.loc["10000001_VX.01"]
        self.assertEqual(first["lage_korrigiert"], "ja")
        self.assertNotIn("lage_korrigiert", customer.columns)
        self.assertAlmostEqual(first.geometry.geoms[0].coords[-1][1] - Y0, 7.0, delta=0.02)
        self.assertAlmostEqual(first["laenge_alt_m"], 49.5, delta=0.7)  # Anteil der Originallänge
        self.assertGreater(first["hausdorff_m"], 1.0)
        # Kundennetz: Originallage, Teilung bei 50/100,5 des Originals
        self.assertAlmostEqual(customer.loc["10000001_VX.01"].geometry.geoms[0].coords[-1][1] - Y0, 0.0, delta=0.001)
        self.assertAlmostEqual(customer.loc["10000001_VX.01", "laenge_m"] + customer.loc["VX_10000002.01", "laenge_m"], 100.0, delta=0.1)
        self.assertEqual(customer.loc["VX_10000002.01", "ursprung_element_nr"], "10000001_10000002.01")

    def test_without_export_gives_the_auto_network(self):
        """Ohne App-Einträge: beide Netze sind das Netz aus Schritt 2, ohne Markierungen."""
        stats, conflicts = imp.run(None, ren_path=self.dir / "ren_netz_auto.gpkg", output_dir=self.dir / "out",
                                   virtual_nodes_path=self.dir / "app-output" / "virtuelle_knoten.gpkg",
                                   new_edges_path=self.dir / "app-output" / "touristische_kanten.gpkg")
        self.assertEqual(conflicts, [])
        customer, working = self.read("ren_netz.gpkg"), self.read("ren_netz_korrigiert.gpkg")
        self.assertEqual(len(customer), len(build_network()))
        self.assertEqual(set(customer.columns) | set(imp.LAGE_COLUMNS), set(working.columns))
        for network in (customer, working):
            self.assertTrue((network["ausgeschlossen"] == "nein").all())
            self.assertTrue((network["verkehrsrichtung_korrigiert"] == "nein").all())
            self.assertTrue(network["eintrag_ids"].isna().all())
        self.assertEqual(customer.loc["80000001_80000002.01", "quelle"], "detailnetz_radfernweg")
        self.assertEqual(working.loc["10000002_10000003.01", "routen_quelle"], "auto")
        self.assertTrue((working["lage_korrigiert"] == "nein").all())

    def test_second_run_gives_the_same_files(self):
        self.run_import()
        nodes_before = gpd.read_file(self.dir / "app-output" / "virtuelle_knoten.gpkg")
        edges_before = gpd.read_file(self.dir / "app-output" / "touristische_kanten.gpkg", layer=imp.NEW_EDGES_LAYER)
        self.run_import()
        nodes_after = gpd.read_file(self.dir / "app-output" / "virtuelle_knoten.gpkg")
        edges_after = gpd.read_file(self.dir / "app-output" / "touristische_kanten.gpkg", layer=imp.NEW_EDGES_LAYER)
        self.assertEqual(sorted(nodes_after["Knotenpunkt-ID"]), sorted(nodes_before["Knotenpunkt-ID"]))
        self.assertEqual(sorted(edges_after["entry_id"]), sorted(edges_before["entry_id"]))
        self.assertEqual(sorted(edges_after["element_nr"]), sorted(edges_before["element_nr"]))

    def test_writes_nothing_to_data(self):
        """Der Import schreibt nur dorthin, wohin ihn der Aufrufer schickt (output/), nie nach data/."""
        self.assertEqual(imp.VIRTUAL_NODES_PATH.parent, imp.HERE / "output")
        self.assertEqual(imp.NEW_EDGES_PATH.parent, imp.HERE / "output")
        self.run_import()
        self.assertEqual(sorted(path.name for path in self.dir.iterdir() if path.is_file()), ["detailnetz.gpkg", "export.json", "radfernweg_abschnitte.gpkg", "ren_netz_auto.gpkg"])

    def test_duplicate_node_name(self):
        entries = build_entries()
        entries.append(stored("n9", {"kind": "virtual_node", "name": "V99", "name_vorschlag": "V99", "lngLat": lnglat(10, 7),
                                     "traeger": {"art": "ren", "ref": "10000001_10000002.01", "station_m": 10.0}}))
        self.export.write_text(json.dumps({"gebiet": "test", "exported_at": "x", "entries": entries}), encoding="utf-8")
        _, conflicts = self.run_import()
        self.assertTrue(any(c["eintrag_id"] == "n9" and "mehreren Einträgen" in c["grund"] for c in conflicts))
        nodes = gpd.read_file(self.dir / "app-output" / "virtuelle_knoten.gpkg")
        self.assertEqual(sorted(nodes["Knotenpunkt-ID"]).count("V99"), 1)

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

    def test_replay_like_the_app(self):
        original = [[13.0, 52.0], [13.1, 52.1]]
        moved = [13.0, 52.5]
        # verschoben: Index außerhalb oder negativ wird übersprungen
        for index in (2, -1):
            self.assertEqual(imp.replay(original, [{"art": "verschoben", "index": index, "nach": moved}])[0], original)
        # eingefuegt: Index hinter dem Ende wird übersprungen, am Ende (= Länge) geht
        self.assertEqual(imp.replay(original, [{"art": "eingefuegt", "index": 3, "nach": moved}])[0], original)
        self.assertEqual(imp.replay(original, [{"art": "eingefuegt", "index": 2, "nach": moved}])[0], original + [moved])
        self.assertEqual(imp.replay(original, [{"art": "eingefuegt", "index": -1, "nach": moved}])[0], original)
        # unbekannte Art: ignoriert, kein Fehler
        self.assertEqual(imp.replay(original, [{"art": "gibt_es_nicht"}]), (original, {}))
        # attribut nur für die drei Felder
        _, attribute = imp.replay(original, [{"art": "attribut", "feld": "ausgeschlossen", "nach_wert": True},
                                             {"art": "attribut", "feld": "irgendwas", "nach_wert": "x"},
                                             {"art": "attribut", "feld": "fahrbahn_typ", "nach_wert": "einbahnstrasse"}])
        self.assertEqual(attribute, {"fahrbahn_typ": "einbahnstrasse"})
        # ausgeschlossen: nur nach_wert True zählt
        for value, expected in ((True, True), (False, False), ("ja", False), (None, False)):
            self.assertEqual(imp.replay(original, [{"art": "ausgeschlossen", "nach_wert": value}])[1],
                             {"ausgeschlossen": expected})

    def test_missing_duplicate_and_vertex_count(self):
        entries = build_entries()
        a0 = coords((0, 0), (50, 0), (100, 0))
        # Ref fehlt: kein Ausweichen auf eine andere Linie derselben element_nr
        entries.append(stored("x1", correction("10000001_10000002.01#2", "10000001_10000002.01", a0, a0,
                                               {"verkehrsrichtung": "R"}, [change("attribut", feld="verkehrsrichtung", von_wert="B", nach_wert="R")])))
        # Doppelter Eintrag zur selben Kante: keiner wird angewendet
        c0 = coords((0, 40), (100, 40))
        entries.append(stored("x2", correction("10000003_10000004.01", "10000003_10000004.01", c0, c0,
                                               {"verkehrsrichtung": "G"}, [change("attribut", feld="verkehrsrichtung", von_wert="B", nach_wert="G")])))
        # andere Stützpunktzahl als im Netz (3 statt 2) zählt als Abweichung
        d3 = coords((0, 120), (50, 120), (100, 120))
        entries.append(stored("x3", correction("10000007_10000008.01", "10000007_10000008.01", d3, d3, {}, [])))
        self.export.write_text(json.dumps({"gebiet": "test", "exported_at": "x", "entries": entries}), encoding="utf-8")
        _, conflicts = self.run_import()
        reasons = {c["eintrag_id"]: c["grund"] for c in conflicts}
        self.assertIn("fehlt im Eingangsnetz", reasons["x1"])
        self.assertIn("Mehrere Einträge", reasons["x2"])
        self.assertIn("Mehrere Einträge", reasons["e3"])
        self.assertIn("andere Stützpunktzahl", reasons["x3"])
        corrected = self.read("ren_netz_korrigiert.gpkg")
        self.assertEqual(corrected.loc["10000003_10000004.01", "verkehrsrichtung_korrigiert"], "nein")

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
