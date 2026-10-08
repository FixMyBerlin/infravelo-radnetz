#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extract_centerline_tracks.py
--------------------------------------------------------------------
Extrahiert aus den TILDA-Bikelanes die Radwege im Seitenraum, die in OSM an der
Straßen-Mittellinie erfasst sind (z. B. cycleway:right=track) und entlang des
REN+-Netzes liegen. Ergebnis ist eine Aufgabenliste für eine MapRoulette-
Kampagne, in der diese Radwege separat nachgezeichnet werden.

TILDA leitet für solche Radwege eine eigene Geometrie aus der Straße ab
("Transformierte Geometrie" im Inspektor). Erkennbar sind sie am Attribut
'prefix' (cycleway bzw. sidewalk). Die Geometrie liegt auf der Mittellinie und
wird hier um das Attribut 'offset' (halbe Straßenbreite, + links / - rechts)
zur Seite versetzt, so wie es der TILDA-Kartenstil visuell macht.

Ablauf:
1. Bikelanes auf transformierte Geometrien mit Track-Kategorie filtern
2. Auf Wege entlang des Netzes filtern (Puffer, Mindestanteil im Puffer)
3. Nach Verbundenheit gruppieren (gemeinsame Endpunkte der Mittellinien)
4. Geometrie versetzen und vereinfachen
5. GeoJSON und MapRoulette-Datei schreiben (eine Aufgabe pro Gruppe)

Jeder Lauf landet in einem eigenen Ordner mit dem Tagesdatum, frühere Läufe bleiben
erhalten. Die Dateien für Netlify in public/ zeigen immer den letzten Lauf.

INPUT:
- data/bikelanes.fgb (TILDA-Export "bikelanes")
- data/ren_netz_gesamt.gpkg (Layer: ren_netz)

OUTPUT:
- output/<Datum>/centerline_tracks.geojson
- output/<Datum>/centerline_tracks_maproulette.json
- output/<Datum>/centerline_tracks_stats.json
- public/centerline_tracks.geojson (Kopie des letzten Laufs)
- public/centerline_tracks_maproulette.json (Kopie des letzten Laufs)
"""

import argparse
import json
import logging
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

import geopandas as gpd
import pandas as pd
import shapely

BASE_DIR = Path(__file__).resolve().parent
BIKELANES_PATH = BASE_DIR / 'data' / 'bikelanes.fgb'
NETWORK_PATH = BASE_DIR / 'data' / 'ren_netz_gesamt.gpkg'
OUTPUT_DIR = BASE_DIR / 'output'
PUBLIC_DIR = BASE_DIR / 'public'

CRS_METRIC = 'EPSG:25833'
CRS_OUTPUT = 'EPSG:4326'

# An der Mittellinie erfasste Radwege im Seitenraum (cycleway:*=track)
TRACK_CATEGORIES = {
    'cycleway_adjoining',
    'footAndCyclewaySegregated_adjoining',
    'footAndCyclewayShared_adjoining',
}
# An der Mittellinie erfasste Gehwege (sidewalk:*:bicycle=yes), nur mit Verkehrszeichen
SIDEWALK_CATEGORIES = {
    'footwayBicycleYes_adjoining',
    'footAndCyclewayShared_adjoining',
}

# Busspur mit Radfreigabe schlägt unbeschilderten Radweg (wie im Abgleich 2025):
# Liegt auf derselben Seite desselben OSM-Wegs eine Busspur mit Radfreigabe und
# hat der Radweg kein Z 237, 240 oder 241, muss er nicht nachgezeichnet werden.
BUS_LANE_PREFIX = 'sharedBusLane'
BUS_LANE_LOSER_PREFIXES = ('cycleway_adjoining', 'footAndCyclewayShared', 'footAndCyclewaySegregated')
BUS_LANE_LOSER_SIGNS = re.compile(r'(^|[,;])\s*(DE:)?(237|240|241)([.\[,;]|$)')

# Attribute, die neben id und Gruppe in die MapRoulette-Aufgaben übernommen werden
MAPROULETTE_PROPERTIES = ['category', 'name', 'road', 'traffic_sign', 'width', 'oneway', 'surface']

# iD-Variante, mit der die Kampagne bearbeitet wird
EDITOR_URL = 'https://deploy-preview-10--tordans-id-experiments.netlify.app/'
EDITOR_ZOOM = 19

SIDE_LABELS = {'left': 'links', 'right': 'rechts'}

logging.basicConfig(stream=sys.stdout, level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')


def filter_centerline_tracks(bikelanes: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Behält nur transformierte Geometrien, die einen Radweg im Seitenraum beschreiben."""
    has_traffic_sign = bikelanes['traffic_sign'].notna() & (bikelanes['traffic_sign'] != 'none')
    is_track = (bikelanes['prefix'] == 'cycleway') & bikelanes['category'].isin(TRACK_CATEGORIES)
    is_signed_sidewalk = (
        (bikelanes['prefix'] == 'sidewalk')
        & bikelanes['category'].isin(SIDEWALK_CATEGORIES)
        & has_traffic_sign
    )
    tracks = bikelanes[is_track | is_signed_sidewalk].copy()
    # Die Seite steht nur in der id, z. B. way/4068011/cycleway/left
    tracks['side'] = tracks['id'].str.split('/').str[-1]

    bus_lanes = bikelanes[bikelanes['category'].fillna('').str.startswith(BUS_LANE_PREFIX)]
    bus_sides = set(zip(bus_lanes['osm_id'], bus_lanes['id'].str.split('/').str[-1]))
    unsigned = ~tracks['traffic_sign'].fillna('').str.contains(BUS_LANE_LOSER_SIGNS)
    beside_bus_lane = (
        tracks['category'].str.startswith(BUS_LANE_LOSER_PREFIXES) & unsigned
        & pd.Series(list(zip(tracks['osm_id'], tracks['side'])), index=tracks.index).isin(bus_sides)
    )
    logging.info(f"{beside_bus_lane.sum()} unbeschilderte Radwege neben einer Busspur mit Radfreigabe entfallen")
    tracks = tracks[~beside_bus_lane]
    # Sind auf einer Seite Radweg und Gehweg erfasst, reicht eine Linie: beide werden
    # in derselben Aufgabe bearbeitet. 'cycleway' sortiert vor 'sidewalk' und bleibt.
    tracks = tracks.sort_values('prefix').drop_duplicates(['osm_id', 'side'])
    logging.info(f"{len(tracks)} transformierte Track-Geometrien in ganz Berlin")
    return tracks


def filter_along_network(tracks: gpd.GeoDataFrame, network: gpd.GeoDataFrame,
                         buffer_m: float, min_share: float) -> gpd.GeoDataFrame:
    """Behält Wege, die zu mindestens min_share ihrer Länge im Puffer um das Netz liegen."""
    network_buffer = network.geometry.buffer(buffer_m).union_all()
    shapely.prepare(network_buffer)
    candidates = tracks[tracks.intersects(network_buffer)]
    share = candidates.geometry.intersection(network_buffer).length / candidates.length
    along = candidates[share >= min_share].copy()
    logging.info(f"{len(along)} davon entlang des Netzes "
                 f"(Puffer {buffer_m} m, Mindestanteil {min_share})")
    return along


def assign_groups(tracks: gpd.GeoDataFrame) -> pd.Series:
    """
    Gruppiert Wege mit gleichem Straßennamen, die über gemeinsame Endpunkte der
    Mittellinie zusammenhängen. Linke und rechte Seite derselben Straße landen so in
    derselben Gruppe. Ohne den Straßennamen würden ganze Straßenzüge über Kreuzungen
    hinweg zu Aufgaben von vielen Kilometern zusammenwachsen.
    Die Gruppen sind nach Länge absteigend nummeriert.
    """
    parent: dict = {}

    def find(node):
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    endpoints = []
    for geometry, name in zip(tracks.geometry, tracks['name'].fillna('')):
        start, end = geometry.coords[0], geometry.coords[-1]
        # Auf Dezimeter runden, damit identische OSM-Knoten sicher zusammenfallen
        nodes = ((name, round(start[0], 1), round(start[1], 1)),
                 (name, round(end[0], 1), round(end[1], 1)))
        for node in nodes:
            parent.setdefault(node, node)
        parent[find(nodes[0])] = find(nodes[1])
        endpoints.append(nodes[0])

    roots = pd.Series([find(node) for node in endpoints], index=tracks.index)
    length_per_root = tracks.length.groupby(roots).sum().sort_values(ascending=False)
    group_number = {root: number for number, root in enumerate(length_per_root.index, start=1)}
    return roots.map(group_number)


def offset_geometry(geometry, offset: float, side: str, simplify_m: float):
    """
    Versetzt die Mittellinie um offset (+ links / - rechts in OSM-Richtung) und vereinfacht sie.
    Linke Seiten werden umgedreht, damit die Linie in Fahrtrichtung (Rechtsverkehr) läuft.
    Schlägt das Versetzen fehl (z. B. bei engen Schleifen), bleibt die Mittellinie erhalten.
    """
    moved = shapely.simplify(geometry, simplify_m).offset_curve(offset, join_style='mitre')
    if moved.is_empty or moved.geom_type != 'LineString':
        moved = geometry
    moved = shapely.simplify(moved, simplify_m)
    return moved.reverse() if side == 'left' else moved


def clean_properties(row: pd.Series, columns: list) -> dict:
    """Wandelt eine Zeile in JSON-Properties um und lässt leere Werte weg."""
    properties = {}
    for column in columns:
        value = row[column]
        if pd.isna(value):
            continue
        properties[column] = value.item() if hasattr(value, 'item') else value
    return properties


def editor_url(members: gpd.GeoDataFrame) -> str:
    """Link in den Editor: Karte auf der Mitte des längsten Wegs, alle Wege der Gruppe ausgewählt."""
    longest = max(members.geometry, key=lambda geometry: geometry.length)
    center = longest.interpolate(0.5, normalized=True)
    way_ids = ','.join(f"w{osm_id}" for osm_id in sorted(members['osm_id'].unique()))
    return (f"{EDITOR_URL}#disable_features=boundaries"
            f"&map={EDITOR_ZOOM}/{center.y:.5f}/{center.x:.5f}"
            f"&locale=en&photo_overlay=mapillary&id={way_ids}")


def task_markdown(members: gpd.GeoDataFrame, title: str) -> str:
    """Aufgabentext einer Gruppe: Straße, Link in den Editor und die betroffenen OSM-Wege."""
    lines = [
        f"**{title}**: {members['osm_id'].nunique()} OSM-Wege",
        '',
        f"[Im Editor öffnen]({editor_url(members)})",
        '',
        'OSM-Wege mit Radweg an der Mittellinie:',
        '',
    ]
    for osm_id, sides in members.groupby('osm_id')['side']:
        side_labels = ' und '.join(SIDE_LABELS[side] for side in sorted(sides))
        lines.append(f"- [way/{osm_id}](https://www.openstreetmap.org/way/{osm_id}) ({side_labels})")
    # Leerzeichen vor dem Zeilenumbruch, sonst verschluckt MapRoulette die Umbrüche
    return '\n'.join(lines).replace('\n', ' \n')


def write_maproulette(tracks: gpd.GeoDataFrame, path: Path, data_updated_at: str):
    """
    Schreibt zeilenweises GeoJSON im MapRoulette-Format wie die TILDA-API:
    pro Zeile ein Record-Separator (0x1E) und eine FeatureCollection. Jede Zeile wird
    eine Aufgabe, hier also eine Gruppe zusammenhängender Wege.

    Die Gruppennummer ändert sich von Lauf zu Lauf. Als stabile Kennung der Aufgabe
    dient deshalb die id des ersten Features, also der OSM-Weg mit der kleinsten id.
    """
    record_separator = chr(0x1E)
    task_updated_at = datetime.now().strftime('%Y-%m-%d %H:%M')
    with open(path, 'w', encoding='utf-8') as file:
        for group, members in tracks.groupby('group'):
            members = members.sort_values(['osm_id', 'side'])
            name = members['name'].dropna()
            title = name.iloc[0] if len(name) else 'Straße ohne Namen'
            task_properties = {
                'title': title,
                'task_markdown': task_markdown(members, title),
                'task_updated_at': task_updated_at,
                'data_updated_at': data_updated_at,
            }
            features = []
            for _, row in members.iterrows():
                osm_identifier = f"way/{row['osm_id']}"
                features.append({
                    'type': 'Feature',
                    'id': osm_identifier,
                    'properties': {
                        'id': osm_identifier,
                        'side': row['side'],
                        'group': group,
                        **clean_properties(row, MAPROULETTE_PROPERTIES),
                    },
                    'geometry': json.loads(shapely.to_geojson(row['geometry'])),
                })
            # Der Aufgabentext steht nur am ersten Feature; MapRoulette führt die
            # Properties aller Features einer Aufgabe zusammen.
            features[0]['properties'].update(task_properties)
            collection = {'type': 'FeatureCollection', 'features': features}
            file.write(f"{record_separator}{json.dumps(collection, ensure_ascii=False)}\n")


def write_stats(tracks: gpd.GeoDataFrame, length_km: pd.Series, path: Path, data_updated_at: str):
    """Schreibt Kennzahlen zu Anzahl und Länge je Kategorie sowie zu den Gruppen."""
    per_category = (
        pd.DataFrame({'category': tracks['category'], 'km': length_km})
        .groupby('category')['km'].agg(['size', 'sum'])
    )
    km_per_group = length_km.groupby(tracks['group']).sum()
    stats = {
        'erstellt_am': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'tilda_export_vom': data_updated_at,
        'wege': len(tracks),
        'km': round(float(length_km.sum()), 1),
        'gruppen': int(tracks['group'].nunique()),
        'laengste_gruppe_km': round(float(km_per_group.max()), 1),
        'gruppen_median_km': round(float(km_per_group.median()), 2),
        'kategorien': {
            category: {'wege': int(row['size']), 'km': round(float(row['sum']), 1)}
            for category, row in per_category.iterrows()
        },
    }
    path.write_text(json.dumps(stats, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    logging.info(json.dumps(stats, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--buffer', type=float, default=25,
                        help='Puffer um das Netz in Metern (Standard: 25)')
    parser.add_argument('--min-share', type=float, default=0.5,
                        help='Mindestanteil der Weglänge im Puffer (Standard: 0.5)')
    parser.add_argument('--simplify', type=float, default=1.0,
                        help='Toleranz der Vereinfachung in Metern (Standard: 1.0)')
    args = parser.parse_args()

    logging.info(f"Lade {BIKELANES_PATH.name} und {NETWORK_PATH.name}")
    bikelanes = gpd.read_file(BIKELANES_PATH).to_crs(CRS_METRIC)
    network = gpd.read_file(NETWORK_PATH).to_crs(CRS_METRIC)
    # Kartierungs-Netz: Kanten, die 2025 schon bearbeitet wurden, entfallen
    network = network[network['bearbeitet_2025'] != 'ja']

    tracks = filter_centerline_tracks(bikelanes)
    tracks = filter_along_network(tracks, network, args.buffer, args.min_share)
    tracks['group'] = assign_groups(tracks)
    # Länge der Mittellinie, vor dem Versetzen
    length_km = tracks.length / 1000

    tracks['geometry'] = [
        offset_geometry(geometry, offset, side, args.simplify)
        for geometry, offset, side in zip(tracks.geometry, tracks['offset'], tracks['side'])
    ]
    tracks = tracks.sort_values(['group', 'id']).to_crs(CRS_OUTPUT)
    tracks['geometry'] = shapely.set_precision(tracks.geometry.values, 0.000001)
    # Spalten ohne Werte weglassen, damit das GeoJSON schlank bleibt
    tracks = tracks.dropna(axis='columns', how='all')

    # Datum der TILDA-Datei; über den Symlink hinweg das der eigentlichen Datei
    data_updated_at = datetime.fromtimestamp(BIKELANES_PATH.stat().st_mtime).strftime('%Y-%m-%d')
    run_dir = OUTPUT_DIR / datetime.now().strftime('%Y-%m-%d')
    run_dir.mkdir(parents=True, exist_ok=True)
    geojson_path = run_dir / 'centerline_tracks.geojson'
    tracks.to_file(geojson_path, driver='GeoJSON')
    logging.info(f"GeoJSON geschrieben: {geojson_path}")

    maproulette_path = run_dir / 'centerline_tracks_maproulette.json'
    write_maproulette(tracks, maproulette_path, data_updated_at)
    logging.info(f"MapRoulette-Datei geschrieben: {maproulette_path}")

    write_stats(tracks, length_km, run_dir / 'centerline_tracks_stats.json', data_updated_at)

    PUBLIC_DIR.mkdir(exist_ok=True)
    for path in (geojson_path, maproulette_path):
        shutil.copyfile(path, PUBLIC_DIR / path.name)
    logging.info(f"Letzter Lauf nach {PUBLIC_DIR} kopiert")


if __name__ == '__main__':
    main()
