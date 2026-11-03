#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
update_assignment.py
--------------------------------------------------------------------
REGELMÄSSIGER LAUF: Überträgt die Zuteilung auf das aktuelle Netz, ohne sie neu
zu schneiden.

Die Zuteilung steht in zwei eingecheckten Tabellen:
- assignment.csv      je Kante lfd_nr, element_nr, account, plr_id, aufgenommen
- assignment_plr.csv  je LOR-Planungsraum der Account; daraus entstehen die Gebiete

1. Jede Kante des aktuellen Kartierungsnetzes bekommt über ihre element_nr die
   lfd_nr, den Account und den Planungsraum (damit den Bezirk) aus assignment.csv.
   Zeilen ohne element_nr werden über Anfangs- und Endpunkt wiedergefunden.
2. Neue Kanten bekommen den Account ihres Planungsraums und eine neue lfd_nr hinter
   der höchsten. Sie werden in assignment.csv aufgenommen, damit ihre Nummer beim
   nächsten Lauf gleich bleibt.
3. Kanten aus assignment.csv, die nicht mehr im Netz sind, fehlen in der Ausgabe;
   ihre Nummer wird nicht wieder vergeben.
4. Bearbeitungsstand aus dem Editor, Statistik und Ausgabe wie bei der Ersterfassung
   (assignment_output.py).

Gebiete, Accounts und die Nummern vorhandener Kanten ändern sich dabei nie.

Aufruf (im Projekt-Root):
    .venv/bin/python mapping-zuteilung/update_assignment.py
    .venv/bin/python mapping-zuteilung/update_assignment.py --dry-run   # assignment.csv nicht ändern
"""

import argparse
import logging
import sys
from datetime import date

import geopandas as gpd
import numpy as np
import pandas as pd

from assign_accounts import LOR_PATH, NETWORK_PATH, START_DISTRICT, attach_plr, build_areas, district_order
from assignment_output import (ASSIGNMENT_PATH, CRS_METRIC, PLR_ASSIGNMENT_PATH, assignment_rows, endpoints,
                               read_assignment, write_assignment, write_outputs)

# Eine Kante ohne element_nr gilt als dieselbe wie eine Zeile der Tabelle, wenn
# Anfangs- und Endpunkt (in beliebiger Richtung) höchstens so weit entfernt liegen
MATCH_DISTANCE_M = 3

logging.basicConfig(stream=sys.stdout, level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')


def match_endpoints(edges: gpd.GeoDataFrame, rows: pd.DataFrame) -> pd.Series:
    """Rückgabe: je Kante die lfd_nr der Zeile mit den nächsten Endpunkten, sonst fehlend. Jede Zeile höchstens einmal."""
    starts = rows[['anfang_x', 'anfang_y']].to_numpy()
    ends = rows[['ende_x', 'ende_y']].to_numpy()
    candidates = []
    for index, (start_x, start_y, end_x, end_y) in zip(edges.index, endpoints(edges.geometry)):
        start, end = np.array([start_x, start_y]), np.array([end_x, end_y])
        forward = np.maximum(np.hypot(*(starts - start).T), np.hypot(*(ends - end).T))
        backward = np.maximum(np.hypot(*(starts - end).T), np.hypot(*(ends - start).T))
        distance = np.minimum(forward, backward)
        candidates += [(distance[position], index, position)
                       for position in np.flatnonzero(distance <= MATCH_DISTANCE_M)]
    matched, used = {}, set()
    for _, index, position in sorted(candidates):
        if index in matched or position in used:
            continue
        matched[index] = rows['lfd_nr'].iloc[position]
        used.add(position)
    return pd.Series(matched, dtype='Int64').reindex(edges.index)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--simplify', type=float, default=1.0,
                        help='Toleranz der Vereinfachung in Metern (Standard: 1.0)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Ausgabe schreiben, assignment.csv aber nicht ändern')
    args = parser.parse_args()

    assignment, plr_account = read_assignment()
    lor = gpd.read_file(LOR_PATH).to_crs(CRS_METRIC)
    network = gpd.read_file(NETWORK_PATH).to_crs(CRS_METRIC)
    # Kartierungs-Netz: Kanten, die 2025 schon bearbeitet wurden, entfallen
    network = network[network['bearbeitet_2025'] != 'ja'].reset_index(drop=True)
    network = network.drop(columns='lfd_nr')
    if network['element_nr'].dropna().duplicated().any():
        raise SystemExit('element_nr ist im Netz nicht eindeutig')

    # Erst über die element_nr; was so nicht passt, über die Endpunkte der Zeilen ohne element_nr
    # (auch Kanten, die inzwischen eine element_nr haben)
    with_number = assignment.dropna(subset=['element_nr']).set_index('element_nr')['lfd_nr']
    network['lfd_nr'] = network['element_nr'].map(with_number).astype('Int64')
    unmatched = network['lfd_nr'].isna()
    without_number = assignment[assignment['element_nr'].isna()]
    network.loc[unmatched, 'lfd_nr'] = match_endpoints(network[unmatched], without_number)
    known = network['lfd_nr'].notna()
    by_lfd_nr = assignment.set_index('lfd_nr')
    network['account'] = network['lfd_nr'].map(by_lfd_nr['account'])
    network['plr_id'] = network['lfd_nr'].map(by_lfd_nr['plr_id'])

    # Neue Kanten: Planungsraum am Mittelpunkt, dessen Account, neue Nummer
    new = network[~known].sort_values('element_nr', na_position='last', kind='stable')
    highest = int(assignment['lfd_nr'].max())
    network.loc[new.index, 'lfd_nr'] = range(highest + 1, highest + 1 + len(new))
    network.loc[new.index, 'plr_id'] = attach_plr(new[['geometry']], lor)['plr_id']
    network.loc[new.index, 'account'] = network.loc[new.index, 'plr_id'].map(plr_account)
    network['lfd_nr'] = network['lfd_nr'].astype(int)
    without_account = network['account'].isna()
    if without_account.any():
        raise SystemExit(f"Planungsraum ohne Account in {PLR_ASSIGNMENT_PATH.name}: "
                         f"{sorted(network.loc[without_account, 'plr_id'].unique())}")

    plr = lor.set_index('plr_id')
    network['plr_name'] = network['plr_id'].map(plr['plr_name'])
    network['bezirk'] = network['plr_id'].map(plr['bez'])
    if network['bezirk'].isna().any():
        raise SystemExit(f"Planungsraum fehlt in den LOR-Daten: "
                         f"{sorted(network.loc[network['bezirk'].isna(), 'plr_id'].unique())}")
    network['reihenfolge'] = network['bezirk'].map(district_order(lor, START_DISTRICT))
    new = network.loc[new.index]

    gone =assignment[~assignment['lfd_nr'].isin(network['lfd_nr'])]
    logging.info(f"{known.sum()} Kanten wie zugeteilt, {len(new)} neu, "
                 f"{len(gone)} aus {ASSIGNMENT_PATH.name} nicht mehr im Netz")
    for _, row in new.iterrows():
        logging.info(f"  neu: lfd_nr {row['lfd_nr']} ({row['element_nr']}, {row['strassenname']}) → "
                     f"{row['account']}, {row['bezirk']}")
    if len(gone):
        logging.info(f"  nicht mehr im Netz: lfd_nr {', '.join(map(str, sorted(gone['lfd_nr'])[:30]))}"
                     f"{' …' if len(gone) > 30 else ''}")

    if len(new) and not args.dry_run:
        write_assignment(pd.concat([assignment, assignment_rows(new, date.today().isoformat())]), plr_account)
        logging.info(f"{len(new)} neue Kanten aufgenommen: {ASSIGNMENT_PATH} (committen!)")

    lor['account'] = lor['plr_id'].map(plr_account)
    write_outputs(network, build_areas(lor, args.simplify), args.simplify)


if __name__ == '__main__':
    main()
