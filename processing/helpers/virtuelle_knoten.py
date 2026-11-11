# -*- coding: utf-8 -*-
"""
virtuelle_knoten.py
Ort der virtuellen Knoten. Sie leben in der App Netzanpassungen (KV-Datenbank), nicht mehr in data/.
netzanpassungen/import_app_export.py schreibt sie aus dem App-Export nach
netzanpassungen/output/virtuelle_knoten.gpkg (Layer Virtuelle-Knotenpunkte, Spalte Knotenpunkt-ID);
alle Skripte, die virtuelle Knoten brauchen, lesen die Datei über virtual_nodes_path().
Die einmalige Übernahme der 53 Knoten von 2025: netzanpassungen/einmalige_uebernahme/.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VIRTUAL_NODES_PATH = ROOT / "netzanpassungen" / "output" / "virtuelle_knoten.gpkg"
VIRTUAL_NODES_LAYER = "Virtuelle-Knotenpunkte"
MISSING_MESSAGE = (f"Virtuelle Knoten fehlen: {VIRTUAL_NODES_PATH} existiert nicht. "
                   "Erst netzanpassungen/import_app_export.py mit dem App-Export laufen lassen.")


def virtual_nodes_path():
    """Pfad der Datei mit den virtuellen Knoten; bricht mit einer klaren Meldung ab, wenn sie fehlt."""
    if not VIRTUAL_NODES_PATH.exists():
        raise SystemExit(MISSING_MESSAGE)
    return VIRTUAL_NODES_PATH
