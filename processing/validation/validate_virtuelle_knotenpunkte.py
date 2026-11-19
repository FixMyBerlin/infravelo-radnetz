#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
validate_virtuelle_knotenpunkte.py
--------------------------------------------------------------------
Prüft die virtuellen Knotenpunkte gegen die Regeln in data/VIRTUELLE-KNOTENPUNKTE.md: das
Archiv der 53 von 2025 (die Datei in one_time_import/2025/; die App hat sie übernommen, die
Pipeline liest sie aus der App) und die Ausgabe von Schritt 3 (alle Knoten):

- Nummer 4-stellig, eindeutig über alle Zeilen einschließlich der gelöschten
- status aktiv oder geloescht, Gelöschte mit geloescht_am und grund
- id_rvn_2025 passt zu data/virtuelle_knotenpunkte_alt_neu.csv; die 53 sind unverändert
- jeder aktive Knoten liegt auf einer Kante des REN+ (Warnung, z. B. nach einem neuen
  Detailnetz; Knoten auf neuen Kanten der Netzanpassungen-App liegen dort erst, wenn die
  Kanten im REN+ sind). Gegen das Detailnetz wird nicht geprüft: Viele Knoten von 2025
  liegen auf der Geometrie des Radvorrangnetzes, die bis zu 300 m davon abweicht.

INPUT:
- netzanpassungen/one_time_import/2025/Virtuelle-Knotenpunkte.gpkg (Archiv, vk.ARCHIVE_PATH)
- netzanpassungen/output/virtuelle_knoten.gpkg (Schritt 3)
- data/virtuelle_knotenpunkte_alt_neu.csv
- ren-network/output/ren_netz.gpkg

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

REN_PATH = vk.DATA_DIR.parent / "ren-network" / "output" / "ren_netz.gpkg"
REN_LAYER = "ren_netz"
ON_EDGE_TOLERANCE_M = 3.0  # wie VIRTUAL_NODE_TOLERANCE in split_rvn_at_virtual_nodes.py

ORANGE = '\033[38;5;214m'
RED = '\033[91m'
RESET = '\033[0m'

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def check_old_to_new(gdf):
    """Die Zuordnungstabelle alt -> neu darf sich nie ändern; sie muss zu id_rvn_2025 passen."""
    if not vk.OLD_TO_NEW_PATH.exists():
        return [f"{vk.OLD_TO_NEW_PATH.name} fehlt"]
    table = pd.read_csv(vk.OLD_TO_NEW_PATH, dtype=str)
    in_registry = dict(zip(gdf["id_rvn_2025"], gdf[vk.ID_COLUMN]))
    wrong = [f"{row.id_rvn_2025} -> {row.neue_id}" for row in table.itertuples()
             if in_registry.get(row.id_rvn_2025) != row.neue_id]
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

    registry = vk.read_all(vk.ARCHIVE_PATH)
    errors = [f"{vk.ARCHIVE_PATH.name}: {error}"
              for error in vk.check(registry) + vk.check_registry_frozen(registry) + check_old_to_new(registry)]
    if not vk.OUTPUT_PATH.exists():
        logger.error(f"{RED}❌ {vk.MISSING_OUTPUT_MESSAGE}{RESET}")
        return 1
    gdf = vk.read_all(vk.OUTPUT_PATH)
    active = gdf[gdf["status"] == vk.STATUS_ACTIVE]
    logger.info(f"{vk.OUTPUT_PATH.name}: {len(gdf)} Zeilen, {len(active)} aktiv, höchste Nummer "
                f"{str(vk.highest_number(gdf)).zfill(vk.ID_DIGITS)}")
    errors += [f"{vk.OUTPUT_PATH.name}: {error}" for error in vk.check(gdf)]
    missing_2025 = sorted(set(registry[vk.ID_COLUMN]) - set(gdf[vk.ID_COLUMN]))
    if missing_2025:
        errors.append(f"{vk.OUTPUT_PATH.name}: Knoten von 2025 fehlen: {missing_2025}")
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
