#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
assignment_output.py
--------------------------------------------------------------------
Gemeinsame Ausgabe von Ersterfassung (assign_accounts.py) und Update
(update_assignment.py): die beiden eingecheckten Tabellen der Zuteilung,
Bearbeitungsstand, Statistik, Editor-Links und die drei Dateien in output/.
"""

import logging
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import shapely

BASE_DIR = Path(__file__).resolve().parent
sys.path.append(str(BASE_DIR.parent / 'bearbeitungsstand'))

from load_status import STATUS_DONE, add_status  # noqa: E402

OUTPUT_DIR = BASE_DIR / 'output'
CRS_METRIC = 'EPSG:25833'
CRS_OUTPUT = 'EPSG:4326'

# Eingecheckte Zuteilung: je Kante der Account, je Planungsraum der Account (daraus die Gebiete).
# Anfangs- und Endpunkt (CRS_METRIC) nur für Kanten ohne element_nr, um sie wiederzufinden.
ASSIGNMENT_PATH = BASE_DIR / 'assignment.csv'
PLR_ASSIGNMENT_PATH = BASE_DIR / 'assignment_plr.csv'
ASSIGNMENT_COLUMNS = ['lfd_nr', 'element_nr', 'account', 'plr_id', 'aufgenommen',
                      'anfang_x', 'anfang_y', 'ende_x', 'ende_y']

# Link in den Mapping-Editor: Maske des Kartierungsnetzes und die Zuteilung,
# gefiltert auf den Account der Kante bzw. des Gebiets
EDITOR_URL = (
    'https://radnetz-mapping.netlify.app/'
    '#disable_features=address_points,building_parts,indoor,boundaries,water,pistes,aerialways,power'
    '&notes=tilda&map={zoom}/{lat:.5f}/{lon:.5f}&background=Berlin-2026'
    '&data_layers=https://tilda-geo.de/api/uploads/infravelo-ren-netz-kartierung-mask.pmtiles'
    '%7CMaske%7Cff26d4%7C%7Co'
    '%3Bhttps://tilda-geo.de/api/uploads/infravelo-ren-netz-zuteilung-netz.pmtiles'
    '%7CZuteilung+Netz%7Cc800ff%7Caccount%3D{account}%7C%7Cmapping'
    '&readonly_features=points,buildings,landuse,rail,past_future,others'
)
EDITOR_ZOOM_EDGE = 19
EDITOR_ZOOM_AREA = 15

NETWORK_COLUMNS = ['lfd_nr', 'element_nr', 'strassenname', 'radverkehrsnetz', 'hauptverkehrsstrasse',
                   'laenge_m', 'reihenfolge', 'bezirk', 'plr_id', 'plr_name', 'account', 'bearbeitungsstand',
                   'erledigt_von', 'erledigt_am', 'editor_markdown', 'geometry']


def endpoints(geometries) -> list:
    """Je Geometrie (anfang_x, anfang_y, ende_x, ende_y): erste und letzte Koordinate."""
    coordinates = [shapely.get_coordinates(geometry) for geometry in geometries]
    return [(*points[0], *points[-1]) for points in coordinates]


def assignment_rows(edges: gpd.GeoDataFrame, added_on: str) -> pd.DataFrame:
    """Zeilen für assignment.csv aus Kanten (CRS_METRIC) mit lfd_nr, element_nr, account und plr_id."""
    rows = edges[['lfd_nr', 'element_nr', 'account', 'plr_id']].copy()
    rows['aufgenommen'] = added_on
    without_number = rows['element_nr'].isna()
    endpoint_columns = ['anfang_x', 'anfang_y', 'ende_x', 'ende_y']
    rows[endpoint_columns] = pd.DataFrame(endpoints(edges.geometry[without_number]), columns=endpoint_columns,
                                          index=rows.index[without_number], dtype=float).round(1)
    return rows[ASSIGNMENT_COLUMNS]


def read_assignment() -> tuple:
    """Rückgabe: assignment.csv als Tabelle und je plr_id der Account aus assignment_plr.csv."""
    if not ASSIGNMENT_PATH.exists() or not PLR_ASSIGNMENT_PATH.exists():
        raise SystemExit(f"Fehlt: {ASSIGNMENT_PATH.name} oder {PLR_ASSIGNMENT_PATH.name}.")
    assignment = pd.read_csv(ASSIGNMENT_PATH, dtype={'element_nr': str, 'plr_id': str, 'aufgenommen': str})
    plr_account = pd.read_csv(PLR_ASSIGNMENT_PATH, dtype=str).set_index('plr_id')['account']
    return assignment, plr_account


def write_assignment(assignment: pd.DataFrame, plr_account: pd.Series):
    assignment[ASSIGNMENT_COLUMNS].sort_values('lfd_nr').to_csv(ASSIGNMENT_PATH, index=False)
    plr_account.rename_axis('plr_id').rename('account').sort_index().to_csv(PLR_ASSIGNMENT_PATH)


def editor_markdown(features: gpd.GeoDataFrame, zoom: int) -> list:
    """Markdown-Link in den Editor je Feature; TILDA zeigt Attribute mit der Endung _markdown als Link an."""
    points = features.geometry.representative_point().to_crs(CRS_OUTPUT)
    return [
        f"[Im Editor öffnen]({EDITOR_URL.format(zoom=zoom, lat=point.y, lon=point.x, account=account)})"
        for point, account in zip(points, features['account'])
    ]


def write_outputs(network: gpd.GeoDataFrame, areas: gpd.GeoDataFrame, simplify_m: float):
    """
    network: Kanten (CRS_METRIC) mit lfd_nr, account, bezirk, reihenfolge, plr_id,
    plr_name und den Netzattributen. areas: ein Gebiet je Bezirk und Account (CRS_METRIC).
    Liest den Bearbeitungsstand aus dem Editor und schreibt output/.
    """
    network = network.copy()
    network['km'] = network.length / 1000
    status_fetched_at = add_status(network, 'lfd_nr', 'mapping')
    network['km_erledigt'] = network['km'].where(network['bearbeitungsstand'] == STATUS_DONE, 0)

    # Statistik je Bezirk und Account
    grouped = network.groupby(['reihenfolge', 'bezirk', 'account'])
    stats = grouped.agg(km=('km', 'sum'), kanten=('km', 'size'), plr=('plr_id', 'nunique'),
                        km_erledigt=('km_erledigt', 'sum'))
    stats['erledigt_prozent'] = stats['km_erledigt'] / stats['km'] * 100
    for column, values in (('radverkehrsnetz', None), ('hauptverkehrsstrasse', ['ja'])):
        shares = network.pivot_table(index=['reihenfolge', 'bezirk', 'account'], columns=column,
                                     values='km', aggfunc='sum', fill_value=0)
        if values:
            shares = shares[values]
        stats = stats.join(shares.add_prefix('km_' if not values else 'km_hauptverkehrsstrasse_'))
    district_mean = stats.groupby(level='bezirk')['km'].transform('mean')
    stats['abweichung_prozent'] = (stats['km'] / district_mean - 1) * 100
    stats = stats.round(1).reset_index()

    OUTPUT_DIR.mkdir(exist_ok=True)
    stats.to_csv(OUTPUT_DIR / 'zuteilung_statistik.csv', index=False)

    areas = areas[['bezirk', 'account', 'geometry']].merge(stats, on=['bezirk', 'account'])
    areas['editor_markdown'] = editor_markdown(areas, EDITOR_ZOOM_AREA)
    areas.sort_values(['reihenfolge', 'account']).to_crs(CRS_OUTPUT).to_file(
        OUTPUT_DIR / 'zuteilung_gebiete.geojson', driver='GeoJSON', COORDINATE_PRECISION=6)

    network['geometry'] = shapely.simplify(network.geometry.values, simplify_m)
    network['editor_markdown'] = editor_markdown(network, EDITOR_ZOOM_EDGE)
    network[NETWORK_COLUMNS].sort_values(['reihenfolge', 'account', 'lfd_nr']).to_crs(CRS_OUTPUT).to_file(
        OUTPUT_DIR / 'zuteilung_netz.geojson', driver='GeoJSON', COORDINATE_PRECISION=6)

    summary = stats.groupby(['reihenfolge', 'bezirk']).agg(
        km=('km', 'sum'), min_km=('km', 'min'), max_km=('km', 'max'),
        max_abweichung_prozent=('abweichung_prozent', lambda values: values.abs().max()))
    logging.info(f"Zuteilung je Bezirk:\n{summary.round(1).to_string()}")
    logging.info(f"Bearbeitungsstand vom {status_fetched_at}: {network['km_erledigt'].sum():.1f} von "
                 f"{network['km'].sum():.1f} km erledigt")
    logging.info(f"Ausgabe geschrieben nach {OUTPUT_DIR}")
    return status_fetched_at
