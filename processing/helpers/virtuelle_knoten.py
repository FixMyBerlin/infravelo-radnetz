# -*- coding: utf-8 -*-
"""
virtuelle_knoten.py
Location of the virtual nodes. Three kinds end up in one file:
- the 53 nodes of the 2025 delivery (data/virtuelle_knoten_2025.gpkg, fixed names),
- the nodes step 1 sets automatically (ren-network/output/virtuelle_knoten_roh.gpkg),
- the nodes drawn in the Netzanpassungen app (KV database, export "alle Einträge").
netzanpassungen/apply_app_result.py (step 3) merges them into
netzanpassungen/output/virtuelle_knoten.gpkg (layer Virtuelle-Knotenpunkte, column Knotenpunkt-ID,
column `quelle` = 2025 | auto | app); every script that needs virtual nodes reads the file through
virtual_nodes_path().
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VIRTUAL_NODES_PATH = ROOT / "netzanpassungen" / "output" / "virtuelle_knoten.gpkg"
VIRTUAL_NODES_LAYER = "Virtuelle-Knotenpunkte"
MISSING_MESSAGE = (f"Virtual nodes missing: {VIRTUAL_NODES_PATH} does not exist. "
                   "Run netzanpassungen/apply_app_result.py with the app export first.")


def virtual_nodes_path():
    """Path of the file with the virtual nodes; stops with a clear message if it is missing."""
    if not VIRTUAL_NODES_PATH.exists():
        raise SystemExit(MISSING_MESSAGE)
    return VIRTUAL_NODES_PATH
