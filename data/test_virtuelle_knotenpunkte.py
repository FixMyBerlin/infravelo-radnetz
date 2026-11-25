#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Self-test for virtuelle_knotenpunkte.py (registry of 2025 and the output file of step 3).

    .venv/bin/python data/test_virtuelle_knotenpunkte.py
"""

import sys
import tempfile
import unittest
from pathlib import Path

import geopandas as gpd
from shapely.geometry import Point

sys.path.append(str(Path(__file__).resolve().parent))

import virtuelle_knotenpunkte as vk  # noqa: E402


def frame(rows):
    columns = vk.COLUMNS + ["herkunft", "app_eintrag"]
    return gpd.GeoDataFrame([{**{c: None for c in columns}, **row} for row in rows],
                            geometry=[Point(392000 + i, 5815000) for i in range(len(rows))], crs=vk.CRS)


class VirtualNodesTest(unittest.TestCase):
    def test_registry_is_the_frozen_53(self):
        registry = vk.read_all(vk.REGISTRY_PATH)
        self.assertEqual(vk.check(registry), [])
        self.assertEqual(vk.check_registry_frozen(registry), [])
        self.assertEqual(vk.old_to_new()["V1112"], "0001")

    def test_translate_element_nr(self):
        self.assertEqual(vk.translate_element_nr("V6475_V4789.01"), "0039_0022.01")
        self.assertEqual(vk.translate_element_nr("10000001_10000002.01"), "10000001_10000002.01")

    def test_read_active_without_output_says_run_step_3(self):
        with self.assertRaises(SystemExit) as raised:
            vk.read_all(vk.OUTPUT_PATH.with_name("does-not-exist.gpkg"))
        self.assertIn("does-not-exist", str(raised.exception))
        self.assertIn("step 3", vk.MISSING_OUTPUT_MESSAGE)

    def test_read_active_filters_deleted_and_checks_rules(self):
        rows = [{vk.ID_COLUMN: "0001", "ist_virtuell": 1, "status": "aktiv", "id_rvn_2025": "V1"},
                {vk.ID_COLUMN: "0054", "ist_virtuell": 1, "status": "geloescht", "geloescht_am": "2026-11-19",
                 "grund": "in der App gelöscht", "app_eintrag": "a"},
                {vk.ID_COLUMN: "0055", "ist_virtuell": 1, "status": "aktiv", "app_eintrag": "b"}]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "virtuelle_knoten.gpkg"
            frame(rows).to_file(path, layer=vk.LAYER, driver="GPKG")
            active = vk.read_active(path)
            self.assertEqual(list(active[vk.ID_COLUMN]), ["0001", "0055"])
            frame(rows + [{vk.ID_COLUMN: "0055", "ist_virtuell": 1, "status": "aktiv", "app_eintrag": "c"}]).to_file(
                path, layer=vk.LAYER, driver="GPKG")
            with self.assertRaises(ValueError):
                vk.read_active(path)

    def test_frozen_check_rejects_a_new_node(self):
        registry = vk.read_all(vk.REGISTRY_PATH)
        extra = frame([{vk.ID_COLUMN: "0054", "ist_virtuell": 1, "status": "aktiv"}])
        errors = vk.check_registry_frozen(gpd.GeoDataFrame(
            __import__("pandas").concat([registry, extra[registry.columns]], ignore_index=True), crs=vk.CRS))
        self.assertTrue(errors)


if __name__ == "__main__":
    unittest.main()
