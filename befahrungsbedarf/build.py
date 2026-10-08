#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build.py
--------
Ermittelt die OSM-Wege (TILDA) entlang des REN+-Netzes, für die neue Fotos
aufgenommen werden müssen (Befahrungsbedarf).

Eingabe (befahrungsbedarf/data/, siehe download_data.sh):
- ren_netz_gesamt.gpkg  (Ausgabe von ren-network/unify_networks.py)
- bikelanes.fgb, roads.fgb, roadsPathClasses.fgb  (TILDA-Export)

Ausgabe (befahrungsbedarf/output/):
- befahrungsbedarf.geojson  Wege mit Befahrungsbedarf
- pruefung_einzelwege.geojson      alle Wege am Netz inkl. Klassifizierung
- befahrung_strecken.geojson  Wege mit Befahrungsbedarf, zu Strecken verbunden (merge_lines.py)
- entfernt_kurz.geojson     Strecken, die nach dem Verbinden zu kurz sind
- statistik.json            Kilometer je Klasse und Datenstände

Zusätzlich wird der Abschnitt "Stand des letzten Laufs" in der README.md aktualisiert.

Verwendung:
    python befahrungsbedarf/build.py
"""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

from merge_lines import MAX_ANGLE_DEG, MAX_GAP_M, MAX_LATERAL_M, MIN_LENGTH_M as MIN_LINE_LENGTH_M, merge_lines

logging.basicConfig(stream=sys.stdout, level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / 'data'
OUTPUT_DIR = BASE_DIR / 'output'

CRS = 'EPSG:25833'

# Ein Weg liegt "am Netz", wenn mindestens MIN_SHARE seiner Länge im Puffer um
# die Netzkanten liegt. Der Puffer hängt von der Straßenklasse der Kante ab
# (Attribut strassenklasse): Er deckt rund 95 % der Radwege im Seitenraum
# ab, gemessen am Abstand der TILDA-Radwege zur Netzkante je Klasse.
BUFFER_M_BY_CLASS = {'0': 22, 'I': 22, 'II': 20, 'III': 15, 'IV': 12, 'V': 10}
BUFFER_M_DEFAULT = 10  # Kanten ohne Straßenklasse, meist eigenständige Wege
MIN_SHARE = 0.5
# Kürzere Wege entfallen: Sie machen die Hälfte der Wege, aber kaum Länge aus.
MIN_LENGTH_M = 20

# --- Regel: Busspur mit Radfreigabe schlägt unbeschilderten Radweg -----------
# Wie im Abgleich 2025 (processing/map-matching/config/default.toml): Liegt
# neben einem Radweg ohne Z 237, 240 oder 241 eine Busspur mit Radfreigabe für
# dieselbe Fahrtrichtung, wird die Busspur erfasst und der Radweg nicht befahren.
BUS_LANE_PREFIX = 'sharedBusLane'
BUS_LANE_LOSER_PREFIXES = ('cycleway_adjoining', 'cycleway_isolated', 'footAndCyclewayShared',
                           'footAndCyclewaySegregated')
BUS_LANE_LOSER_SIGNS = ('237', '240', '241')
# Die Busspur liegt in TILDA auf der Straßen-Mittellinie; der Radweg liegt in
# Fahrtrichtung rechts davon, höchstens so weit entfernt
BUS_LANE_MAX_DISTANCE_M = 20
BUS_LANE_MAX_ANGLE_DEG = 30
BUS_LANE_SAMPLE_M = 5
# Anteil des Radwegs, neben dem die Busspur verlaufen muss
BUS_LANE_MIN_SHARE = 0.8

# Vereinfachung der Ausgabegeometrie (Douglas-Peucker, in Metern)
SIMPLIFY_M = 1.0

# Der Mapillary-Abgleich (vizsim) zählt Sequenzen der letzten 30 Monate vor
# dem Verarbeitungstag (freshness_lookback_months in dessen config/default.toml).
MAPILLARY_LOOKBACK_MONTHS = 30

README_PATH = BASE_DIR / 'README.md'
README_START = '<!-- stand:start -->'
README_END = '<!-- stand:end -->'

# Reihenfolge = Priorität beim Entfernen doppelter IDs zwischen den Layern
LAYERS = ['bikelanes', 'roads', 'roadsPathClasses']

# --- Regeln: Ist der Weg auf den Kfz-Befahrungsfotos (2025) sichtbar? ---------
# Befahren wurden öffentliche Straßen, keine Zufahrten/Wirtschaftswege und
# keine Privatstraßen. Führungen auf der Fahrbahn sind sichtbar, Führungen im
# Seitenraum nur unsicher (parkende Fahrzeuge), eigenständige Wege gar nicht.

# roads: Straßenklassen ohne Kfz-Befahrung (Präfix-Vergleich)
ROADS_NOT_DRIVEN_PREFIXES = ('service', 'pedestrian', 'track')

# roadsPathClasses: Querungen liegen auf der Fahrbahn
PATHS_ON_CARRIAGEWAY = {'footway_crossing', 'cycleway_crossing', 'footway_cycleway_crossing'}

# bikelanes: Kategorien auf der Fahrbahn
BIKELANES_ON_CARRIAGEWAY_PREFIXES = (
    'cyclewayOnHighway', 'sharedBusLane', 'sharedMotorVehicleLane', 'bicycleRoad', 'crossing',
)
# bikelanes: eigenständige Führungen abseits der Fahrbahn
BIKELANES_ISOLATED = {'pedestrianAreaBicycleYes'}
BIKELANES_ISOLATED_SUFFIX = '_isolated'

NETWORK_COLUMNS = ['element_nr', 'radverkehrsnetz', 'strassenklasse', 'bezirksnummer', 'strassenname']
WAY_COLUMNS = ['id', 'osm_id', 'quelle', 'road', 'category', 'name', 'lifecycle', 'operator_type',
               'traffic_sign', 'offset', 'mapillary_coverage', 'geometry']


def load_network() -> gpd.GeoDataFrame:
    """Lädt das Netz und legt die Pufferbreite je Kante fest."""
    network = gpd.read_file(DATA_DIR / 'ren_netz_gesamt.gpkg').to_crs(CRS)
    # Kartierungs-Netz: Kanten, die 2025 schon bearbeitet wurden, entfallen
    network = network[network['bearbeitet_2025'] != 'ja'].reset_index(drop=True)
    network['puffer_m'] = network['strassenklasse'].map(BUFFER_M_BY_CLASS).fillna(BUFFER_M_DEFAULT)
    logging.info(f'Netz: {len(network)} Kanten, {network.length.sum() / 1000:.0f} km')
    return network


def load_ways() -> gpd.GeoDataFrame:
    """Lädt die drei TILDA-Layer in ein gemeinsames Schema."""
    frames = []
    for layer in LAYERS:
        path = DATA_DIR / f'{layer}.fgb'
        logging.info(f'Lade {path.name}')
        gdf = gpd.read_file(path).to_crs(CRS)
        gdf['quelle'] = layer
        for column in WAY_COLUMNS:
            if column not in gdf.columns:
                gdf[column] = None
        frames.append(gdf[WAY_COLUMNS])
    ways = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=CRS)
    # Eigenständige Wege stehen in mehreren Layern; der erste Layer gewinnt.
    ways = ways.drop_duplicates(subset='id', keep='first').reset_index(drop=True)
    logging.info(f'{len(ways)} TILDA-Wege geladen')
    return ways


def select_ways_along_network(ways: gpd.GeoDataFrame, network: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Behält Wege, die zu mindestens MIN_SHARE im Puffer um das Netz liegen."""
    buffers = gpd.GeoDataFrame(geometry=network.buffer(network['puffer_m']).values, crs=CRS)
    pairs = gpd.sjoin(ways[['geometry']], buffers, predicate='intersects')
    # Je Weg die berührten Puffer vereinigen und den Längenanteil darin messen
    merged = (
        pd.Series(buffers.geometry.values[pairs['index_right'].values], index=pairs.index)
        .groupby(level=0)
        .agg(shapely.union_all)
    )
    candidates = ways.loc[merged.index].copy()
    inside = shapely.length(shapely.intersection(candidates.geometry.values, merged.values))
    candidates['anteil_am_netz'] = (inside / candidates.length).round(2)
    selected = candidates[
        (candidates['anteil_am_netz'] >= MIN_SHARE) & (candidates.length >= MIN_LENGTH_M)
    ].copy()
    logging.info(f'{len(selected)} Wege am Netz '
                 f'(Anteil im Puffer >= {MIN_SHARE}, Länge >= {MIN_LENGTH_M} m)')
    return selected


def add_network_attributes(ways: gpd.GeoDataFrame, network: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Übernimmt die Attribute der Netzkante, die dem Wegmittelpunkt am nächsten liegt."""
    midpoints = gpd.GeoDataFrame(geometry=ways.geometry.interpolate(0.5, normalized=True), crs=CRS)
    nearest = gpd.sjoin_nearest(midpoints, network[NETWORK_COLUMNS + ['geometry']], how='left')
    nearest = nearest[~nearest.index.duplicated(keep='first')]
    return ways.join(nearest[NETWORK_COLUMNS])


def classify_car_imagery(row) -> str:
    """ja / unsicher / nein: Sichtbarkeit auf den Kfz-Befahrungsfotos."""
    road = row['road'] or ''
    if row['operator_type'] == 'private':
        return 'nein'

    if row['quelle'] == 'roads':
        return 'nein' if road.startswith(ROADS_NOT_DRIVEN_PREFIXES) else 'ja'

    if row['quelle'] == 'roadsPathClasses':
        return 'ja' if road in PATHS_ON_CARRIAGEWAY else 'nein'

    category = row['category'] or ''
    if category in BIKELANES_ISOLATED or category.endswith(BIKELANES_ISOLATED_SUFFIX):
        return 'nein'
    if category.startswith(BIKELANES_ON_CARRIAGEWAY_PREFIXES):
        return 'nein' if road.startswith(ROADS_NOT_DRIVEN_PREFIXES) else 'ja'
    return 'unsicher'


def classify_need(row) -> pd.Series:
    """
    Befahrungsbedarf und Priorität.
    Kein Bedarf: auf Kfz-Fotos sichtbar oder Mapillary-Panoramen vorhanden.
    Priorität 1: gar keine Fotos, 2: nur unsichere Kfz-Fotos, 3: nur Mapillary-Fotos ohne Panorama.
    """
    car = row['kfz_bild']
    mapillary = row['mapillary_coverage']
    if car == 'ja':
        return pd.Series(['nein', None, 'Kfz-Befahrung 2025'])
    if mapillary == 'pano':
        return pd.Series(['nein', None, 'Mapillary-Panoramen'])
    if mapillary == 'regular':
        return pd.Series(['ja', 3, 'nur Mapillary-Fotos ohne Panorama'])
    if car == 'unsicher':
        return pd.Series(['ja', 2, 'Seitenraum, Sichtbarkeit auf Kfz-Fotos unsicher'])
    return pd.Series(['ja', 1, 'keine Fotos'])


def side_of_way(way_id: str) -> str | None:
    """Seite eines an der Mittellinie erfassten Wegs (way/123/cycleway/left), sonst None."""
    side = way_id.rsplit('/', 1)[-1]
    return side if side in ('left', 'right') else None


def has_traffic_sign(value, signs) -> bool:
    """Prüft, ob ein OSM-traffic_sign-Wert (z.B. "DE:237,1022-10") eines der Zeichen enthält."""
    tokens = [token.strip().removeprefix('DE:') for token in str(value or '').replace(';', ',').split(',')]
    return any(token == sign or token.startswith((f'{sign}.', f'{sign}[')) for token in tokens for sign in signs)


def _bearings(line, distances):
    """Richtung der Linie (Grad) an den Positionen distances."""
    ahead = shapely.get_coordinates(shapely.line_interpolate_point(line, np.minimum(distances + 1, line.length)))
    behind = shapely.get_coordinates(shapely.line_interpolate_point(line, np.maximum(distances - 1, 0)))
    return np.degrees(np.arctan2(ahead[:, 1] - behind[:, 1], ahead[:, 0] - behind[:, 0]))


def find_ways_beside_bus_lane(ways: gpd.GeoDataFrame) -> pd.Series:
    """
    Markiert unbeschilderte Radwege, neben denen eine Busspur mit Radfreigabe
    für dieselbe Fahrtrichtung verläuft.
    """
    category = ways['category'].fillna('')
    side = ways['id'].map(side_of_way)
    bus = ways[category.str.startswith(BUS_LANE_PREFIX)]
    # Busspur in Fahrtrichtung drehen: links erfasste Spuren laufen gegen die OSM-Richtung
    bus_lines = [geom.reverse() if side[index] == 'left' else geom for index, geom in bus.geometry.items()]
    bus_tree = shapely.STRtree(bus_lines)
    bus_sides = set(zip(bus['osm_id'], side[bus.index]))

    unsigned = ~ways['traffic_sign'].map(lambda value: has_traffic_sign(value, BUS_LANE_LOSER_SIGNS))
    candidates = ways[category.str.startswith(BUS_LANE_LOSER_PREFIXES) & unsigned]
    beside = pd.Series(False, index=ways.index)
    for index, geom in candidates.geometry.items():
        if pd.notna(side[index]):
            # An der Mittellinie erfasst: dieselbe Straße und Seite wie die Busspur
            beside[index] = (ways.at[index, 'osm_id'], side[index]) in bus_sides
            continue
        distances = np.arange(BUS_LANE_SAMPLE_M / 2, geom.length, BUS_LANE_SAMPLE_M)
        points = shapely.line_interpolate_point(geom, distances)
        way_bearings = _bearings(geom, distances)
        covered = np.zeros(len(points), dtype=bool)
        for bus_index in bus_tree.query(geom, predicate='dwithin', distance=BUS_LANE_MAX_DISTANCE_M):
            line = bus_lines[bus_index]
            along = shapely.line_locate_point(line, points)
            foot = shapely.get_coordinates(shapely.line_interpolate_point(line, along))
            bus_bearings = np.radians(_bearings(line, along))
            offset = shapely.get_coordinates(points) - foot
            # Kreuzprodukt < 0: Punkt liegt in Fahrtrichtung rechts der Busspur
            right = np.cos(bus_bearings) * offset[:, 1] - np.sin(bus_bearings) * offset[:, 0] < 0
            near = np.hypot(offset[:, 0], offset[:, 1]) <= BUS_LANE_MAX_DISTANCE_M
            # Stirnseitig hinter dem Ende der Busspur zählt nicht als daneben
            abreast = (along > 0) & (along < line.length)
            angle = np.abs((way_bearings - np.degrees(bus_bearings) + 90) % 180 - 90)
            covered |= right & near & abreast & (angle <= BUS_LANE_MAX_ANGLE_DEG)
        beside[index] = covered.mean() >= BUS_LANE_MIN_SHARE
    logging.info(f'{beside.sum()} unbeschilderte Radwege neben einer Busspur mit Radfreigabe '
                 f'({len(bus)} Busspur-Wege am Netz)')
    return beside


def offset_to_side(ways: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Versetzt an der Mittellinie erfasste Wege um 'offset' (+ links / - rechts in
    OSM-Richtung) auf ihre Straßenseite. Linke Seiten werden umgedreht und laufen
    dann in Fahrtrichtung. So bleibt sichtbar, ob eine oder beide Seiten zu befahren sind.
    """
    ways = ways.copy()
    side = ways['id'].map(side_of_way)
    for index in ways.index[side.notna() & ways['offset'].notna()]:
        geom = ways.geometry[index]
        moved = shapely.simplify(geom, SIMPLIFY_M).offset_curve(float(ways.at[index, 'offset']), join_style='mitre')
        # Schlägt das Versetzen fehl (z.B. bei engen Schleifen), bleibt die Mittellinie
        if moved.is_empty or moved.geom_type != 'LineString':
            moved = geom
        ways.at[index, 'geometry'] = moved.reverse() if side[index] == 'left' else moved
    return ways


def km_by(ways: gpd.GeoDataFrame, column: str) -> dict:
    grouped = ways.groupby(ways[column].astype('object').fillna('keine'))['laenge_m'].sum() / 1000
    return {str(key): round(value, 1) for key, value in grouped.items()}


def read_json(path: Path):
    return json.loads(path.read_text()) if path.exists() else None


def mapillary_window(ml_data_from: str | None) -> dict | None:
    """Zeitraum der berücksichtigten Mapillary-Fotos für diesen Datenstand."""
    if not ml_data_from:
        return None
    until = pd.Timestamp(ml_data_from).tz_localize(None).normalize()
    since = until - pd.DateOffset(months=MAPILLARY_LOOKBACK_MONTHS)
    return {'von': since.date().isoformat(), 'bis': until.date().isoformat()}


def update_readme(statistik: dict):
    """Schreibt Datenstände und Kennzahlen des Laufs in die README.md."""
    stand = statistik['datenstand']
    fotos = stand['mapillary_fotos'] or {'von': 'unbekannt', 'bis': 'unbekannt'}
    tilda = (stand['tilda_export'] or {}).get('bikelanes', 'unbekannt')
    bedarf = statistik['befahrungsbedarf']
    strecken = statistik['strecken']
    prio = bedarf['km_je_prioritaet']
    lines = [
        '| | |',
        '|---|---|',
        f"| Lauf | {statistik['erstellt'][:10]} |",
        f"| Mapillary-Fotos berücksichtigt | **{fotos['von']}** bis {fotos['bis']} |",
        f"| OSM-Stand des Mapillary-Abgleichs | {(stand['osm_mapillary_abgleich'] or 'unbekannt')[:10]} |",
        f"| TILDA-Export | {tilda} |",
        f"| Netz | {statistik['netz_km']} km |",
        f"| Wege am Netz | {statistik['wege_am_netz']['anzahl']} Wege, {statistik['wege_am_netz']['km']} km |",
        f"| Befahrungsbedarf | {bedarf['anzahl']} Wege, {bedarf['km']} km |",
        f"| davon Priorität 1 / 2 / 3 | {prio.get('1', 0)} / {prio.get('2', 0)} / {prio.get('3', 0)} km |",
        f"| Wegen Busspur mit Radfreigabe entfallen | {bedarf['entfallen_wegen_busspur']['anzahl']} Wege, {bedarf['entfallen_wegen_busspur']['km']} km |",
        f"| Strecken zum Befahren | {strecken['anzahl']} Strecken, {strecken['km']} km, Median {strecken['median_m']} m |",
        f"| Strecken unter {MIN_LINE_LENGTH_M} m entfernt | {strecken['entfernt_kurz']['anzahl']} Strecken, {strecken['entfernt_kurz']['km']} km |",
    ]
    readme = README_PATH.read_text()
    start = readme.index(README_START) + len(README_START)
    end = readme.index(README_END)
    README_PATH.write_text(readme[:start] + '\n' + '\n'.join(lines) + '\n' + readme[end:])


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)

    network = load_network()

    ways = select_ways_along_network(load_ways(), network)
    ways = add_network_attributes(ways, network)

    ways['laenge_m'] = ways.length.round(1)
    ways['kfz_bild'] = ways.apply(classify_car_imagery, axis=1)
    ways[['bedarf', 'prioritaet', 'grund']] = ways.apply(classify_need, axis=1)
    beside_bus_lane = find_ways_beside_bus_lane(ways) & (ways['bedarf'] == 'ja')
    ways.loc[beside_bus_lane, ['bedarf', 'prioritaet', 'grund']] = ['nein', None, 'Busspur mit Radfreigabe']
    ways['prioritaet'] = ways['prioritaet'].astype('Int64')

    needed = ways[ways['bedarf'] == 'ja']
    lines, short_lines = merge_lines(offset_to_side(needed), SIMPLIFY_M)
    ml_data_from = (read_json(DATA_DIR / 'ml_metadata.json') or {}).get('ml_data_from')
    statistik = {
        'erstellt': datetime.now().isoformat(timespec='seconds'),
        'parameter': {'buffer_m_by_class': BUFFER_M_BY_CLASS, 'buffer_m_default': BUFFER_M_DEFAULT,
                      'min_length_m': MIN_LENGTH_M, 'simplify_m': SIMPLIFY_M,
                      'strecken': {'max_gap_m': MAX_GAP_M, 'max_angle_deg': MAX_ANGLE_DEG,
                                   'max_lateral_m': MAX_LATERAL_M, 'min_length_m': MIN_LINE_LENGTH_M}},
        'datenstand': {
            'tilda_export': read_json(DATA_DIR / 'tilda_export.json'),
            'mapillary': ml_data_from,
            'mapillary_fotos': mapillary_window(ml_data_from),
            'osm_mapillary_abgleich': (read_json(DATA_DIR / 'osm_metadata.json') or {}).get('osm_data_from'),
        },
        'netz_km': round(network.length.sum() / 1000, 1),
        'wege_am_netz': {'anzahl': len(ways), 'km': round(ways['laenge_m'].sum() / 1000, 1)},
        'befahrungsbedarf': {
            'anzahl': len(needed),
            'km': round(needed['laenge_m'].sum() / 1000, 1),
            'entfallen_wegen_busspur': {'anzahl': int(beside_bus_lane.sum()),
                                        'km': round(ways.loc[beside_bus_lane, 'laenge_m'].sum() / 1000, 1)},
            'km_je_prioritaet': km_by(needed, 'prioritaet'),
            'km_je_quelle': km_by(needed, 'quelle'),
            'km_je_road': km_by(needed, 'road'),
            'km_je_radverkehrsnetz': km_by(needed, 'radverkehrsnetz'),
        },
        'strecken': {
            'anzahl': len(lines),
            'km': round(lines['laenge_m'].sum() / 1000, 1),
            'median_m': round(lines['laenge_m'].median()),
            'km_je_prioritaet': km_by(lines, 'prioritaet'),
            'entfernt_kurz': {'anzahl': len(short_lines), 'km': round(short_lines['laenge_m'].sum() / 1000, 1)},
        },
        'km_je_kfz_bild': km_by(ways, 'kfz_bild'),
        'km_je_mapillary_coverage': km_by(ways, 'mapillary_coverage'),
    }
    (OUTPUT_DIR / 'statistik.json').write_text(json.dumps(statistik, indent=2, ensure_ascii=False))
    update_readme(statistik)

    outputs = [('pruefung_einzelwege', ways), ('befahrungsbedarf', ways[ways['bedarf'] == 'ja'])]
    for name, gdf in outputs:
        gdf = gdf.set_geometry(gdf.geometry.simplify(SIMPLIFY_M)).to_crs('EPSG:4326')
        path = OUTPUT_DIR / f'{name}.geojson'
        gdf.to_file(path, driver='GeoJSON', COORDINATE_PRECISION=6)
        logging.info(f'{path.name}: {len(gdf)} Features')

    # Strecken sind schon vereinfacht
    for name, gdf in [('befahrung_strecken', lines), ('entfernt_kurz', short_lines)]:
        path = OUTPUT_DIR / f'{name}.geojson'
        gdf.to_crs('EPSG:4326').to_file(path, driver='GeoJSON', COORDINATE_PRECISION=6)
        logging.info(f'{path.name}: {len(gdf)} Features')

    logging.info(json.dumps(statistik['strecken'], indent=2, ensure_ascii=False))
    logging.info(json.dumps(statistik['befahrungsbedarf'], indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
