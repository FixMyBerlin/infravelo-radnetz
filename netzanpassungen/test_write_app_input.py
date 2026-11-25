#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Self-test for write_app_input.py: the node proposals of step 1 reach the app with their number of arms (arme)."""

import sys
import tempfile
import unittest
from pathlib import Path

import geopandas as gpd
from shapely.geometry import Point

sys.path.insert(0, str(Path(__file__).resolve().parent))

import write_app_input as wai  # noqa: E402


class ProposalArmsTest(unittest.TestCase):
    def test_arme_is_passed_through_to_the_knoten_features(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "vorschlaege.gpkg"
            proposals = gpd.GeoDataFrame(
                {"id": ["P392000-5815000", "P392100-5815000"], "art": ["junction", "dead_end"], "arme": [3, 1],
                 "traeger_element_nr": ["1_P392000-5815000.01", "2_P392100-5815000.01"], "station_m": [10.0, 5.0]},
                geometry=[Point(392000, 5815000), Point(392100, 5815000)], crs="EPSG:25833")
            proposals["arme"] = proposals["arme"].astype("Int64")
            proposals.to_file(path, layer=wai.ren.PROPOSALS_LAYER, driver="GPKG")
            features = wai.feature_collection(wai.load_virtual_nodes(path))["features"]
        self.assertEqual({f["properties"]["id"]: f["properties"]["arme"] for f in features},
                         {"P392000-5815000": 3, "P392100-5815000": 1})


if __name__ == "__main__":
    unittest.main()
