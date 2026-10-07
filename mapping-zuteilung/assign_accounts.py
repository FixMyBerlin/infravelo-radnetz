#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
assign_accounts.py
--------------------------------------------------------------------
Teilt die Kanten des REN+-Netzes auf die Mapping-Accounts auf.

Die Bezirke werden nacheinander bearbeitet. Innerhalb eines Bezirks bekommt jeder
Account ein zusammenhängendes Gebiet aus LOR-Planungsräumen (PLR), damit alle
Accounts gleichzeitig arbeiten können, ohne sich in die Quere zu kommen. Die
Gebiete eines Bezirks sollen ähnlich viele Netz-Kilometer enthalten.

Ablauf:
1. Jede Kante über ihren Mittelpunkt einem PLR und damit einem Bezirk zuordnen
2. Pro Bezirk die PLR zu einem Gebiet je Account zusammenfassen: Gebiete wachsen
   von Startpunkten über benachbarte PLR, danach werden PLR an den Gebietsgrenzen
   getauscht, bis die Kilometer möglichst ausgeglichen sind
3. Bezirke ab dem Startbezirk gegen den Uhrzeigersinn nummerieren
4. Kanten, Gebiete und Statistik schreiben

Das Ergebnis ist deterministisch: Gleiche Eingangsdaten und gleiche Account-Liste
ergeben dieselbe Zuteilung.

INPUT:
- data/ren_netz_vereinheitlicht.gpkg (Layer: ren_netz)
- data/lor_plr_2021.geojson (LOR-Planungsräume 2021)
- accounts.txt (ein Account pro Zeile)

OUTPUT:
- output/zuteilung_netz.geojson
- output/zuteilung_gebiete.geojson
- output/zuteilung_statistik.csv
"""

import argparse
import logging
import math
import random
import sys
from pathlib import Path

import geopandas as gpd
import networkx as nx
import pandas as pd
import shapely

BASE_DIR = Path(__file__).resolve().parent
NETWORK_PATH = BASE_DIR / 'data' / 'ren_netz_vereinheitlicht.gpkg'
LOR_PATH = BASE_DIR / 'data' / 'lor_plr_2021.geojson'
ACCOUNTS_PATH = BASE_DIR / 'accounts.txt'
OUTPUT_DIR = BASE_DIR / 'output'

CRS_METRIC = 'EPSG:25833'
CRS_OUTPUT = 'EPSG:4326'

# PLR gelten als benachbart, wenn sie mindestens so viele Meter Grenze teilen
MIN_SHARED_BORDER_M = 10
# Anzahl der Startpunkt-Varianten, aus denen pro Bezirk die beste Aufteilung gewählt wird
ATTEMPTS = 200

logging.basicConfig(stream=sys.stdout, level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')


def read_accounts() -> list:
    lines = ACCOUNTS_PATH.read_text(encoding='utf-8').splitlines()
    accounts = [line.strip() for line in lines if line.strip() and not line.startswith('#')]
    if not accounts:
        raise ValueError(f"Keine Accounts in {ACCOUNTS_PATH}")
    return accounts


def attach_plr(network: gpd.GeoDataFrame, lor: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Ordnet jede Kante über ihren Mittelpunkt einem PLR zu, außerhalb liegende dem nächsten."""
    midpoints = gpd.GeoDataFrame(geometry=network.geometry.interpolate(0.5, normalized=True),
                                 index=network.index, crs=network.crs)
    plr_columns = lor[['plr_id', 'plr_name', 'bez', 'geometry']]
    joined = gpd.sjoin_nearest(midpoints, plr_columns, how='left')
    joined = joined[~joined.index.duplicated()]
    return network.join(joined[['plr_id', 'plr_name', 'bez']])


def build_plr_graph(plr: gpd.GeoDataFrame, km_per_plr: pd.Series) -> nx.Graph:
    """Nachbarschaftsgraph der PLR eines Bezirks mit Netz-Kilometern als Knotengewicht."""
    graph = nx.Graph()
    for plr_id, geometry in zip(plr['plr_id'], plr.geometry):
        centroid = geometry.centroid
        graph.add_node(plr_id, km=float(km_per_plr.get(plr_id, 0.0)), xy=(centroid.x, centroid.y))
    pairs = plr.sindex.query(plr.geometry, predicate='intersects')
    for left, right in zip(*pairs):
        if left >= right:
            continue
        shared = plr.geometry.iloc[left].intersection(plr.geometry.iloc[right]).length
        if shared >= MIN_SHARED_BORDER_M:
            graph.add_edge(plr['plr_id'].iloc[left], plr['plr_id'].iloc[right])
    # Durch Wasser oder Bahn abgetrennte PLR an den nächstgelegenen PLR anbinden,
    # damit jeder PLR erreichbar ist
    components = sorted(nx.connected_components(graph), key=len, reverse=True)
    for component in components[1:]:
        main = components[0]
        source, target = min(
            ((a, b) for a in component for b in main),
            key=lambda pair: math.dist(graph.nodes[pair[0]]['xy'], graph.nodes[pair[1]]['xy']),
        )
        graph.add_edge(source, target)
        components[0] = main | component
    return graph


def pick_seeds(graph: nx.Graph, count: int, first) -> list:
    """Wählt Startpunkte, die möglichst weit voneinander entfernt liegen."""
    seeds = [first]
    candidates = sorted(graph.nodes)
    while len(seeds) < count:
        seeds.append(max(
            (node for node in candidates if node not in seeds),
            key=lambda node: min(math.dist(graph.nodes[node]['xy'], graph.nodes[seed]['xy'])
                                 for seed in seeds),
        ))
    return seeds


def grow_regions(graph: nx.Graph, seeds: list) -> dict:
    """Lässt die Gebiete wachsen: Das jeweils leichteste Gebiet nimmt einen freien Nachbar-PLR."""
    region_of = {seed: index for index, seed in enumerate(seeds)}
    km = [graph.nodes[seed]['km'] for seed in seeds]
    while len(region_of) < graph.number_of_nodes():
        for region in sorted(range(len(seeds)), key=lambda index: (km[index], index)):
            free = sorted({
                neighbour
                for node, node_region in region_of.items() if node_region == region
                for neighbour in graph.neighbors(node) if neighbour not in region_of
            })
            if not free:
                continue
            seed_xy = graph.nodes[seeds[region]]['xy']
            chosen = min(free, key=lambda node: math.dist(graph.nodes[node]['xy'], seed_xy))
            region_of[chosen] = region
            km[region] += graph.nodes[chosen]['km']
            break
    return region_of


def region_km(graph: nx.Graph, region_of: dict, count: int) -> list:
    km = [0.0] * count
    for node, region in region_of.items():
        km[region] += graph.nodes[node]['km']
    return km


def imbalance(km: list) -> float:
    """Summe der quadrierten Abweichungen vom Mittelwert."""
    mean = sum(km) / len(km)
    return sum((value - mean) ** 2 for value in km)


def refine_regions(graph: nx.Graph, region_of: dict, count: int) -> dict:
    """
    Verschiebt PLR an den Gebietsgrenzen in ein Nachbargebiet, solange das die
    Kilometer ausgleicht und das abgebende Gebiet zusammenhängend bleibt.
    """
    km = region_km(graph, region_of, count)
    improved = True
    while improved:
        improved = False
        for node in sorted(region_of):
            source = region_of[node]
            members = [other for other, region in region_of.items() if region == source]
            if len(members) == 1:
                continue
            targets = sorted({region_of[neighbour] for neighbour in graph.neighbors(node)} - {source})
            for target in targets:
                moved = km.copy()
                moved[source] -= graph.nodes[node]['km']
                moved[target] += graph.nodes[node]['km']
                if imbalance(moved) >= imbalance(km) - 1e-9:
                    continue
                remaining = graph.subgraph(other for other in members if other != node)
                if not nx.is_connected(remaining):
                    continue
                region_of[node] = target
                km = moved
                improved = True
                break
    return region_of


def partition_district(graph: nx.Graph, count: int, rng: random.Random) -> dict:
    """Probiert mehrere Startpunkt-Varianten und behält die ausgeglichenste Aufteilung."""
    count = min(count, graph.number_of_nodes())
    nodes = sorted(graph.nodes)
    first_seeds = nodes if len(nodes) <= ATTEMPTS else rng.sample(nodes, ATTEMPTS)
    best, best_score = None, None
    for first in first_seeds:
        region_of = refine_regions(graph, grow_regions(graph, pick_seeds(graph, count, first)), count)
        km = region_km(graph, region_of, count)
        score = (round(max(km) - min(km), 3), round(imbalance(km), 3))
        if best_score is None or score < best_score:
            best, best_score = region_of, score
    return best


def district_order(lor: gpd.GeoDataFrame, start: str) -> dict:
    """Nummeriert die Bezirke ab dem Startbezirk gegen den Uhrzeigersinn um die Stadtmitte."""
    districts = lor.dissolve('bez').geometry
    center = lor.geometry.union_all().centroid
    angle = {
        name: math.atan2(geometry.centroid.y - center.y, geometry.centroid.x - center.x)
        for name, geometry in districts.items()
    }
    start_name = next(name for name in angle if start.lower() in name.lower())
    turn = 2 * math.pi
    ordered = sorted(angle, key=lambda name: (angle[name] - angle[start_name]) % turn)
    return {name: number for number, name in enumerate(ordered, start=1)}


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--start-district', default='Neukölln',
                        help='Bezirk, mit dem die Bearbeitung beginnt (Standard: Neukölln)')
    parser.add_argument('--simplify', type=float, default=1.0,
                        help='Toleranz der Vereinfachung in Metern (Standard: 1.0)')
    args = parser.parse_args()

    accounts = read_accounts()
    logging.info(f"{len(accounts)} Accounts: {', '.join(accounts)}")
    network = gpd.read_file(NETWORK_PATH).to_crs(CRS_METRIC)
    # Kartierungs-Netz: Kanten, die 2025 schon bearbeitet wurden, entfallen
    network = network[network['bearbeitet_2025'] == 'nein'].reset_index(drop=True)
    lor = gpd.read_file(LOR_PATH).to_crs(CRS_METRIC)

    network = attach_plr(network, lor)
    network['km'] = network.length / 1000
    km_per_plr = network.groupby('plr_id')['km'].sum()
    order = district_order(lor, args.start_district)

    rng = random.Random(0)
    area_of_plr = {}
    for district in sorted(order, key=order.get):
        plr = lor[lor['bez'] == district].reset_index(drop=True)
        graph = build_plr_graph(plr, km_per_plr)
        region_of = partition_district(graph, len(accounts), rng)
        # Gebiete von West nach Ost den Accounts zuordnen, damit die Reihenfolge stabil ist
        regions = sorted(set(region_of.values()), key=lambda region: min(
            graph.nodes[node]['xy'] for node, node_region in region_of.items() if node_region == region))
        account_of_region = {region: accounts[index] for index, region in enumerate(regions)}
        area_of_plr.update({node: account_of_region[region] for node, region in region_of.items()})

    network['account'] = network['plr_id'].map(area_of_plr)
    network['bezirk'] = network['bez']
    network['reihenfolge'] = network['bezirk'].map(order)
    lor['account'] = lor['plr_id'].map(area_of_plr)

    # Statistik je Bezirk und Account
    grouped = network.groupby(['reihenfolge', 'bezirk', 'account'])
    stats = grouped.agg(km=('km', 'sum'), kanten=('km', 'size'), plr=('plr_id', 'nunique'))
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

    areas = lor.dissolve(['bez', 'account']).reset_index().rename(columns={'bez': 'bezirk'})
    areas = areas[['bezirk', 'account', 'geometry']].merge(stats, on=['bezirk', 'account'])
    areas['geometry'] = areas.geometry.simplify(args.simplify * 5)
    areas.sort_values(['reihenfolge', 'account']).to_crs(CRS_OUTPUT).to_file(
        OUTPUT_DIR / 'zuteilung_gebiete.geojson', driver='GeoJSON', COORDINATE_PRECISION=6)

    network['geometry'] = shapely.simplify(network.geometry.values, args.simplify)
    columns = ['lfd_nr', 'element_nr', 'strassenname', 'radverkehrsnetz', 'hauptverkehrsstrasse',
               'laenge_m', 'reihenfolge', 'bezirk', 'plr_id', 'plr_name', 'account', 'geometry']
    network[columns].sort_values(['reihenfolge', 'account', 'lfd_nr']).to_crs(CRS_OUTPUT).to_file(
        OUTPUT_DIR / 'zuteilung_netz.geojson', driver='GeoJSON', COORDINATE_PRECISION=6)

    summary = stats.groupby(['reihenfolge', 'bezirk']).agg(
        km=('km', 'sum'), min_km=('km', 'min'), max_km=('km', 'max'),
        max_abweichung_prozent=('abweichung_prozent', lambda values: values.abs().max()))
    logging.info(f"Zuteilung je Bezirk:\n{summary.round(1).to_string()}")
    logging.info(f"Ausgabe geschrieben nach {OUTPUT_DIR}")


if __name__ == '__main__':
    main()
