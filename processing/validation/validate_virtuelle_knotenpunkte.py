#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
validate_virtuelle_knotenpunkte.py
--------------------------------------------------------------------
Prüft das Verzeichnis der virtuellen Knotenpunkte gegen die Regeln in
data/VIRTUELLE-KNOTENPUNKTE.md:

- Nummer 4-stellig, eindeutig über alle Zeilen einschließlich der gelöschten
- status aktiv oder geloescht, Gelöschte mit geloescht_am und grund
- alte_id passt zu data/virtuelle_knotenpunkte_alt_neu.csv
- jeder aktive Knoten liegt auf einer Kante des REN+ (Warnung, z. B. nach einem neuen
  Detailnetz; Knoten auf neuen Kanten der Netzanpassungen-App liegen dort erst, wenn die
  Kanten im REN+ sind). Gegen das Detailnetz wird nicht geprüft: Viele Knoten von 2025
  liegen auf der Geometrie des Radvorrangnetzes, die bis zu 300 m davon abweicht.

INPUT:
- data/Virtuelle-Knotenpunkte.gpkg
- data/virtuelle_knotenpunkte_alt_neu.csv
- ren-network/output/ren_netz_gesamt.gpkg

OUTPUT:
- Konsolenausgabe; Rückgabe 1 bei Regelverstößen
"""

import logging
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[2] / "data"))
import virtuelle_knotenpunkte as vk  # noqa: E402

REN_PATH = vk.DATA_DIR.parent / "ren-network" / "output" / "ren_netz_gesamt.gpkg"
REN_LAYER = "ren_netz"
ON_EDGE_TOLERANCE_M = 3.0  # wie VIRTUAL_NODE_TOLERANCE in split_rvn_at_virtual_nodes.py

ORANGE = '\033[38;5;214m'
RED = '\033[91m'
RESET = '\033[0m'

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def check_old_to_new(gdf):
    """Die Zuordnungstabelle alt -> neu darf sich nie ändern; sie muss zu alte_id passen."""
    if not vk.OLD_TO_NEW_PATH.exists():
        return [f"{vk.OLD_TO_NEW_PATH.name} fehlt"]
    table = pd.read_csv(vk.OLD_TO_NEW_PATH, dtype=str)
    in_registry = dict(zip(gdf["alte_id"], gdf[vk.ID_COLUMN]))
    wrong = [f"{row.alte_id} -> {row.neue_id}" for row in table.itertuples()
             if in_registry.get(row.alte_id) != row.neue_id]
    return [f"Zuordnung alt -> neu passt nicht zum Verzeichnis: {wrong}"] if wrong else []


def check_on_network(active):
    if not REN_PATH.exists():
        logger.warning(f"{ORANGE}REN+ fehlt ({REN_PATH.name}), Lageprüfung übersprungen{RESET}")
        return []
    network = gpd.read_file(REN_PATH, layer=REN_LAYER, columns=["element_nr"]).to_crs(vk.CRS)
    near = gpd.sjoin(active[[vk.ID_COLUMN, "geometry"]].set_geometry(active.buffer(ON_EDGE_TOLERANCE_M)),
                     network[["geometry"]], predicate="intersects")
    off = active[~active[vk.ID_COLUMN].isin(near[vk.ID_COLUMN])]
    return [f"{row[vk.ID_COLUMN]} ({row['quelle']})" for _, row in off.iterrows()]


def main():
    logger.info("=" * 80)
    logger.info("VALIDIERUNG: Virtuelle Knotenpunkte (data/VIRTUELLE-KNOTENPUNKTE.md)")
    logger.info("=" * 80)

    if not vk.PATH.exists():
        logger.error(f"{RED}❌ Datei nicht gefunden: {vk.PATH}{RESET}")
        return 1
    gdf = vk.read_all()
    active = gdf[gdf["status"] == vk.STATUS_ACTIVE]
    logger.info(f"{len(gdf)} Zeilen, {len(active)} aktiv, nächste Nummer "
                f"{str(vk.next_number(gdf)).zfill(vk.ID_DIGITS)}")

    errors = vk.check(gdf) + check_old_to_new(gdf)
    for error in errors:
        logger.error(f"{RED}❌ {error}{RESET}")

    off = check_on_network(active)
    if off:
        logger.warning(f"{ORANGE}⚠️ {len(off)} aktive Knoten liegen weiter als {ON_EDGE_TOLERANCE_M} m "
                       f"von jeder Kante des REN+: {off}{RESET}")

    logger.info("=" * 80)
    if errors:
        logger.warning(f"{ORANGE}⚠️ VALIDIERUNG FEHLGESCHLAGEN{RESET}")
        return 1
    logger.info("✓ VALIDIERUNG ERFOLGREICH")
    return 0


if __name__ == "__main__":
    sys.exit(main())
