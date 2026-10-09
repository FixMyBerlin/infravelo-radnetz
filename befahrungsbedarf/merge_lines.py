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
Fortsetzung. Lücken werden mit einer geraden Linie geschlossen. An der
Straßen-Mittellinie erfasste Wege kommen schon auf ihre Seite versetzt an.

Kurze Wege ohne Bedarf (Spalte bruecke, z.B. Querungen an Einmündungen) schließen
Lücken zwischen zwei Wegen mit Bedarf, wenn sie zusammen höchstens BRIDGE_MAX_M
lang sind. Welche Strecken am Ende entfallen, entscheidet build.py.

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
MAX_GAP_M = 40
# Größter Knick zwischen zwei verbundenen Wegen
MAX_ANGLE_DEG = 30
# Größter seitlicher Versatz, damit die Straßenseite nicht wechselt
MAX_LATERAL_M = 5
# Kürzere Strecken entfallen nach dem Verbinden
MIN_LENGTH_M = 30
# Wege ohne Bedarf dürfen zwei Wege mit Bedarf verbinden, zusammen bis zu dieser Länge
BRIDGE_MAX_M = 50
# Länge des Stücks am Wegende, aus dem die Richtung bestimmt wird
DIRECTION_SAMPLE_M = 10
# Ab diesem Abstand gelten zwei Enden als Lücke und nicht als gemeinsamer Punkt
TOUCHING_M = 0.5

# Wege aller Prioritäten werden verbunden. Ausnahme: Ein zusammenhängendes
# Stück derselben Priorität ab dieser Länge bleibt eine eigene Strecke, damit
# lange Abschnitte mit geringerer Dringlichkeit getrennt geplant werden können.
SEPARATE_FROM_M = {2: 2000, 3: 1000}

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


def find_links(ways: gpd.GeoDataFrame, groups: np.ndarray, bridges_fit_all: bool = False) -> list[tuple[int, int]]:
    """
    Sucht die Verbindungen zwischen Wegenden; verbunden werden nur Wege derselben
    Gruppe. Mit bridges_fit_all passen Wege ohne Bedarf (bruecke) zu jeder Gruppe.
    Ein Ende ist 2 * Wegposition + 0 (Anfang) bzw. + 1 (Ende).
    Rückgabe: Paare verbundener Enden.
    """
    is_bridge = ways['bruecke'].to_numpy()
    coords = [shapely.get_coordinates(geom) for geom in ways.geometry]
    points = np.array([xy for way in coords for xy in (way[0], way[-1])])
    directions = np.array([d for geom in ways.geometry for d in _end_directions(geom)])

    tree = shapely.STRtree(shapely.points(points))
    first, second = tree.query(shapely.points(points), predicate='dwithin', distance=MAX_GAP_M)
    candidates = []
    for a, b in zip(first, second):
        if a >= b or a // 2 == b // 2:
            continue
        over_bridge = is_bridge[a // 2] or is_bridge[b // 2]
        if groups[a // 2] != groups[b // 2] and not (bridges_fit_all and over_bridge):
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
            # Versetzte Wege schließen seitlich leicht verschoben an: bis TOUCHING_M Überlappung
            if forward_a < -TOUCHING_M or forward_b < -TOUCHING_M or lateral > MAX_LATERAL_M:
                continue
        # Eine direkte Fortsetzung mit Bedarf geht immer vor dem Weg über eine Brücke
        penalty = MAX_GAP_M + MAX_ANGLE_DEG / 3 if over_bridge else 0
        candidates.append((distance + angle / 3 + penalty, a, b))

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


def _drop_unused_bridges(ways: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Behält von den Wegen ohne Bedarf nur die, die in einer Strecke zwischen zwei
    Wegen mit Bedarf liegen und dort zusammen höchstens BRIDGE_MAX_M lang sind.
    """
    while True:
        is_bridge = ways['bruecke'].to_numpy()
        lengths = ways.geometry.length.to_numpy()
        keep = ~is_bridge
        for chain in _chains(len(ways), find_links(ways, np.zeros(len(ways)))):
            run, after_needed = [], False
            for way, _ in chain:
                if is_bridge[way]:
                    run.append(way)
                    continue
                if after_needed and run and lengths[run].sum() <= BRIDGE_MAX_M:
                    keep[run] = True
                run, after_needed = [], True
        if keep.all():
            return ways
        # Ohne die entfallenen Brücken können sich andere Verbindungen ergeben
        ways = ways[keep].reset_index(drop=True)


def _merge_groups(ways: gpd.GeoDataFrame) -> np.ndarray:
    """
    Gruppe je Weg: Lange Stücke einer Priorität (SEPARATE_FROM_M) bleiben unter
    sich, alle übrigen Wege dürfen miteinander verbunden werden. Brücken zählen
    zu dem Stück, das sie fortsetzen.
    """
    is_bridge = ways['bruecke'].to_numpy()
    priorities = ways['prioritaet'].fillna(0).astype(int).to_numpy()
    lengths = ways.geometry.length.to_numpy()
    groups = np.full(len(ways), 'gemischt', dtype=object)
    for chain in _chains(len(ways), find_links(ways, priorities, bridges_fit_all=True)):
        runs = []
        for way, _ in chain:
            if is_bridge[way]:
                if runs:
                    runs[-1][1].append(way)
            elif runs and runs[-1][0] == priorities[way]:
                runs[-1][1].append(way)
            else:
                runs.append((priorities[way], [way]))
        for priority, members in runs:
            if lengths[members].sum() >= SEPARATE_FROM_M.get(priority, np.inf):
                groups[members] = f'prio_{priority}_lang'
    return groups


def _german(value: float) -> str:
    return f'{value:.2f}'.replace('.', ',')


def _priority_stats(parts: pd.DataFrame) -> str:
    km = parts[~parts['bruecke']].groupby('prioritaet')['laenge_m'].sum() / 1000
    shares = [f'{_german(value)} km Prio {priority}' for priority, value in km.items()]
    if parts['bruecke'].any():
        shares.append(f"{_german(parts.loc[parts['bruecke'], 'laenge_m'].sum() / 1000)} km ohne Bedarf")
    if len(shares) == 1:
        return shares[0]
    return f"{_german(parts['laenge_m'].sum() / 1000)} km, davon {', '.join(shares)}"


def _links_markdown(line_wgs84) -> str:
    def position(point) -> str:
        return quote(f'{point.y:.5f}/{point.x:.5f}', safe='')

    start, middle, end = (line_wgs84.interpolate(share, normalized=True) for share in (0, 0.5, 1))
    map_position = quote(f'{LINKS_ZOOM}/', safe='') + position(middle)
    return (f'[Mapillary-Abdeckung]({MAPILLARY_MAP_URL.format(map=map_position)})'
            f' · [Routing]({ROUTING_URL.format(map=map_position, start=position(start), end=position(end))})')


def merge_lines(ways: gpd.GeoDataFrame, simplify_m: float) -> gpd.GeoDataFrame:
    """
    Verbindet die Wege zu Strecken, im CRS der Eingabe. Die Spalte bruecke
    markiert Wege ohne Bedarf, die nur Lücken schließen dürfen.
    """
    ways = _drop_unused_bridges(ways.reset_index(drop=True))
    is_bridge = ways['bruecke'].to_numpy()
    links = find_links(ways, _merge_groups(ways))
    rows = []
    for chain in _chains(len(ways), links):
        # Brücken am Anfang und Ende einer Strecke verbinden nichts
        while chain and is_bridge[chain[0][0]]:
            chain = chain[1:]
        while chain and is_bridge[chain[-1][0]]:
            chain = chain[:-1]
        if not chain:
            continue
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
    # Linke und rechte Seite derselben Straße haben dieselben OSM-IDs
    duplicate_number = lines.groupby('id').cumcount()
    lines.loc[duplicate_number > 0, 'id'] += '-' + (duplicate_number[duplicate_number > 0] + 1).astype(str)
    lines['befahrung_links_markdown'] = lines.geometry.to_crs('EPSG:4326').map(_links_markdown)
    lines = lines[['id', 'osm_ids', 'name', 'prioritaet', 'prioritaet_stats', 'laenge_m', 'anzahl_teile',
                   'befahrung_links_markdown', 'geometry']]

    logging.info(f'{(~is_bridge).sum()} Wege mit Bedarf und {is_bridge.sum()} Brücken '
                 f'zu {len(lines)} Strecken verbunden')
    return lines
