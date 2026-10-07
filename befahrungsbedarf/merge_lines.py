#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
merge_lines.py
--------------------------------------------------------------------
Verbindet die Wege mit Befahrungsbedarf zu möglichst langen, geraden Strecken.

Zwei Wegenden werden verbunden, wenn das zweite in Verlängerung des ersten
liegt: höchstens MAX_GAP_M entfernt, höchstens MAX_ANGLE_DEG abgeknickt und
höchstens MAX_LATERAL_M seitlich versetzt. Jedes Ende wird nur einmal
verbunden; gibt es mehrere Kandidaten, gewinnt die geradeste und nächste
Fortsetzung. Lücken werden mit einer geraden Linie geschlossen. Strecken
unter MIN_LENGTH_M entfallen danach.

Wird von build.py aufgerufen.
"""

import logging
from urllib.parse import quote

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely.geometry import LineString

# Suchweite in Linienrichtung ab dem Wegende
MAX_GAP_M = 20
# Größter Knick zwischen zwei verbundenen Wegen
MAX_ANGLE_DEG = 30
# Größter seitlicher Versatz, damit die Straßenseite nicht wechselt
MAX_LATERAL_M = 5
# Kürzere Strecken entfallen nach dem Verbinden
MIN_LENGTH_M = 30
# Länge des Stücks am Wegende, aus dem die Richtung bestimmt wird
DIRECTION_SAMPLE_M = 10
# Ab diesem Abstand gelten zwei Enden als Lücke und nicht als gemeinsamer Punkt
TOUCHING_M = 0.5

# Wege verschiedener Gruppen werden nicht verbunden: 1 und 2 haben keine
# Mapillary-Fotos, 3 hat Fotos ohne Panorama und ist eine Nachbesserung.
PRIORITY_GROUPS = {1: 'ohne_fotos', 2: 'ohne_fotos', 3: 'ohne_panorama'}

LINKS_ZOOM = 16
MAPILLARY_MAP_URL = 'https://www.osm-verkehrswende.org/mapillary/map/?map={map}&anzeige=current_all'
ROUTING_URL = ('https://vizsim.de/missing_mapillary_gh-routing/?map={map}&start={start}'
               '&profile=bike_customizable&mapillary_weight=0.2&end={end}')


def _end_directions(geom) -> tuple[np.ndarray, np.ndarray]:
    """Einheitsvektoren, die am Anfang und am Ende aus der Linie herauszeigen."""
    sample = min(DIRECTION_SAMPLE_M, geom.length)
    points = shapely.get_coordinates(shapely.line_interpolate_point(geom, [0, sample, geom.length - sample, geom.length]))
    start = points[0] - points[1]
    end = points[3] - points[2]
    return start / np.hypot(*start), end / np.hypot(*end)


def _way_side(way_id: str) -> str:
    side = way_id.rsplit('/', 1)[-1]
    return side if side in ('left', 'right') else ''


def find_links(ways: gpd.GeoDataFrame) -> list[tuple[int, int]]:
    """
    Sucht die Verbindungen zwischen Wegenden. Ein Ende ist 2 * Wegposition + 0
    (Anfang) bzw. + 1 (Ende). Rückgabe: Paare verbundener Enden.
    """
    coords = [shapely.get_coordinates(geom) for geom in ways.geometry]
    points = np.array([xy for way in coords for xy in (way[0], way[-1])])
    directions = np.array([d for geom in ways.geometry for d in _end_directions(geom)])
    groups = ways['prioritaet'].map(PRIORITY_GROUPS).to_numpy()
    sides = ways['id'].map(_way_side).to_numpy()

    tree = shapely.STRtree(shapely.points(points))
    first, second = tree.query(shapely.points(points), predicate='dwithin', distance=MAX_GAP_M)
    candidates = []
    for a, b in zip(first, second):
        if a >= b or a // 2 == b // 2 or groups[a // 2] != groups[b // 2]:
            continue
        # Knick: b muss dorthin weiterlaufen, wohin a zeigt
        angle = np.degrees(np.arccos(np.clip(-directions[a] @ directions[b], -1, 1)))
        if angle > MAX_ANGLE_DEG:
            continue
        gap = points[b] - points[a]
        distance = np.hypot(*gap)
        if distance > TOUCHING_M:
            # Die Lücke liegt vor beiden Enden und kaum seitlich davon
            forward_a, forward_b = gap @ directions[a], -gap @ directions[b]
            lateral = max(abs(directions[a][0] * gap[1] - directions[a][1] * gap[0]),
                          abs(directions[b][0] * gap[1] - directions[b][1] * gap[0]))
            if forward_a <= 0 or forward_b <= 0 or lateral > MAX_LATERAL_M:
                continue
        # Links und rechts an der Mittellinie erfasste Wege liegen aufeinander:
        # dieselbe Seite fortsetzen
        side_change = 10 if sides[a // 2] != sides[b // 2] else 0
        candidates.append((distance + angle / 3 + side_change, a, b))

    # Beste Fortsetzung zuerst; jedes Ende nur einmal, keine Ringe
    parent = list(range(len(ways)))

    def find(way):
        while parent[way] != way:
            parent[way] = parent[parent[way]]
            way = parent[way]
        return way

    used, links = set(), []
    for _, a, b in sorted(candidates):
        if a in used or b in used or find(a // 2) == find(b // 2):
            continue
        used.update((a, b))
        parent[find(a // 2)] = find(b // 2)
        links.append((a, b))
    return links


def _chains(way_count: int, links: list[tuple[int, int]]) -> list[list[tuple[int, bool]]]:
    """Reiht die Wege entlang der Verbindungen auf: je Strecke (Wegposition, umgedreht)."""
    partner = {}
    for a, b in links:
        partner[a], partner[b] = b, a
    chains, seen = [], set()
    for way in range(way_count):
        if way in seen:
            continue
        # Bis zum freien Ende der Strecke zurücklaufen
        end = 2 * way
        while end in partner and partner[end] // 2 != way:
            end = partner[end] ^ 1
        # Vom freien Ende aus aufreihen; ein Weg wird umgedreht, wenn sein Ende vorn liegt
        chain, current = [], end
        while True:
            chain.append((current // 2, current % 2 == 1))
            seen.add(current // 2)
            exit_end = current ^ 1
            if exit_end not in partner:
                break
            current = partner[exit_end]
        chains.append(chain)
    return chains


def _german(value: float) -> str:
    return f'{value:.2f}'.replace('.', ',')


def _priority_stats(parts: pd.DataFrame) -> str:
    km = parts.groupby('prioritaet')['laenge_m'].sum() / 1000
    if len(km) == 1:
        return f'{_german(km.iloc[0])} km Prio {km.index[0]}'
    shares = ', '.join(f'{_german(value)} km Prio {priority}' for priority, value in km.items())
    return f'{_german(km.sum())} km, davon {shares}'


def _links_markdown(line_wgs84) -> str:
    def position(point) -> str:
        return quote(f'{point.y:.5f}/{point.x:.5f}', safe='')

    start, middle, end = (line_wgs84.interpolate(share, normalized=True) for share in (0, 0.5, 1))
    map_position = quote(f'{LINKS_ZOOM}/', safe='') + position(middle)
    return (f'[Mapillary-Abdeckung]({MAPILLARY_MAP_URL.format(map=map_position)})'
            f' · [Routing]({ROUTING_URL.format(map=map_position, start=position(start), end=position(end))})')


def merge_lines(ways: gpd.GeoDataFrame, simplify_m: float) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """
    Verbindet die Wege zu Strecken. Rückgabe: Strecken ab MIN_LENGTH_M und die
    entfernten kürzeren Strecken, beide im CRS der Eingabe.
    """
    ways = ways.reset_index(drop=True)
    links = find_links(ways)
    rows = []
    for chain in _chains(len(ways), links):
        parts = ways.iloc[[way for way, _ in chain]]
        coords = []
        for way, reverse in chain:
            way_coords = shapely.get_coordinates(ways.geometry.iloc[way])
            coords.extend(way_coords[::-1] if reverse else way_coords)
        osm_ids = list(dict.fromkeys(str(int(osm_id)) for osm_id in parts['osm_id']))
        names = parts.groupby('name')['laenge_m'].sum()
        rows.append({
            'id': f'w{osm_ids[0]}-w{osm_ids[-1]}-n{len(parts)}',
            'osm_ids': ';'.join(osm_ids),
            'name': names.idxmax() if len(names) else None,
            'prioritaet': int(parts['prioritaet'].min()),
            'prioritaet_stats': _priority_stats(parts),
            'anzahl_teile': len(parts),
            'geometry': LineString(coords).simplify(simplify_m),
        })
    lines = gpd.GeoDataFrame(rows, crs=ways.crs)
    lines['laenge_m'] = lines.length.round(1)
    # Links und rechts an der Mittellinie erfasste Wege ergeben dieselben OSM-IDs
    duplicate_number = lines.groupby('id').cumcount()
    lines.loc[duplicate_number > 0, 'id'] += '-' + (duplicate_number[duplicate_number > 0] + 1).astype(str)
    lines['befahrung_links_markdown'] = lines.geometry.to_crs('EPSG:4326').map(_links_markdown)
    lines = lines[['id', 'osm_ids', 'name', 'prioritaet', 'prioritaet_stats', 'laenge_m', 'anzahl_teile',
                   'befahrung_links_markdown', 'geometry']]

    long_enough = lines['laenge_m'] >= MIN_LENGTH_M
    logging.info(f'{len(ways)} Wege über {len(links)} Verbindungen zu {len(lines)} Strecken verbunden, '
                 f'{(~long_enough).sum()} unter {MIN_LENGTH_M} m entfernt')
    return lines[long_enough].reset_index(drop=True), lines[~long_enough].reset_index(drop=True)
