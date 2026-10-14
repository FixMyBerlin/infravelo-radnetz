#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_csv.py
--------------------------------------------------------------------
Schreibt die CSV für den TILDA-Pseudo-Tag infravelo_netz: welche OSM-Wege und
abgeleiteten Seitenwege zum infraVelo-Radnetz gehören und mit welcher Klasse.

Quelle ist das Endergebnis der Prozessierung (Format von Datensatz C: je
Netzkante die TILDA-IDs in tilda_ids, mit ";" getrennt). Es gibt nur eine CSV
für das Projekt; jede neue Lieferung ersetzt sie.

Ausgabe: tilda-pseudo-tags/output/infravelo-netz.csv
    osm_id,id_suffix,infravelo_netz
    812944114,,V
    4425411,cycleway/left,V

Aufruf (im Projekt-Root):
    .venv/bin/python tilda-pseudo-tags/build_csv.py
    .venv/bin/python tilda-pseudo-tags/build_csv.py --input processing/output/aggregated_rvn_final.geojson.gz
"""

import argparse
import csv
import gzip
import json
import logging
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = ROOT / 'data' / 'netzquellen' / 'ergebnis_2025_datensatz_c.geojson.gz'
OUTPUT_PATH = Path(__file__).resolve().parent / 'output' / 'infravelo-netz.csv'

# Netzklasse je Kante: Spalte radverkehrsnetz, falls das Ergebnis sie hat.
# Die Lieferung 2025 hat sie nicht; sie enthält nur das Radvorrangnetz.
NETZ_CODES = {
    'Radvorrangnetz': 'V',
    'Radergänzungsnetz': 'E',
    'Kein Radverkehrsnetz vorhanden': 'S',
}
# Gehört eine ID zu Kanten verschiedener Klassen, gilt die erste dieser Liste
NETZ_RANK = ['V', 'E', 'S']
DEFAULT_NETZ = 'V'

TILDA_ID = re.compile(r'^way/(\d+)(?:/(.+))?$')

logging.basicConfig(stream=sys.stdout, level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')


def read_features(path: Path) -> list:
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rt', encoding='utf-8') as file:
        return json.load(file)['features']


def build_rows(features: list) -> dict:
    """{(osm_id, id_suffix): netz}"""
    rows, edges_without_ids, edges_without_class = {}, 0, 0
    for feature in features:
        properties = feature['properties']
        tilda_ids = [value for value in (properties.get('tilda_ids') or '').split(';') if value]
        if not tilda_ids:
            edges_without_ids += 1
            continue
        network = properties.get('radverkehrsnetz')
        netz = NETZ_CODES.get(network) if network else DEFAULT_NETZ
        if netz is None:
            raise SystemExit(f"Unbekannte Netzklasse: {network!r}")
        edges_without_class += network is None
        for tilda_id in tilda_ids:
            match = TILDA_ID.match(tilda_id.strip())
            if not match:
                raise SystemExit(f"Unerwartete TILDA-ID: {tilda_id!r}")
            key = (int(match.group(1)), match.group(2) or '')
            if key not in rows or NETZ_RANK.index(netz) < NETZ_RANK.index(rows[key]):
                rows[key] = netz
    logging.info(f"{len(features)} Kanten, davon {edges_without_ids} ohne TILDA-ID")
    if edges_without_class:
        logging.info(f"{edges_without_class} Kanten ohne Spalte radverkehrsnetz, als {DEFAULT_NETZ} übernommen")
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--input', type=Path, default=DEFAULT_INPUT,
                        help=f'Endergebnis im Format von Datensatz C (Standard: {DEFAULT_INPUT.relative_to(ROOT)})')
    args = parser.parse_args()

    logging.info(f"Lese {args.input}")
    rows = build_rows(read_features(args.input))
    OUTPUT_PATH.parent.mkdir(exist_ok=True)
    with open(OUTPUT_PATH, 'w', encoding='utf-8', newline='') as file:
        writer = csv.writer(file, lineterminator='\n')
        writer.writerow(['osm_id', 'id_suffix', 'infravelo_netz'])
        for (osm_id, suffix), netz in sorted(rows.items()):
            writer.writerow([osm_id, suffix, netz])

    suffixes = {}
    for _, suffix in rows:
        suffixes[suffix or '(Weg selbst)'] = suffixes.get(suffix or '(Weg selbst)', 0) + 1
    classes = {code: list(rows.values()).count(code) for code in NETZ_RANK}
    logging.info(f"{len(rows)} Zeilen, {len({osm_id for osm_id, _ in rows})} OSM-Wege")
    logging.info(f"id_suffix: {suffixes}")
    logging.info(f"infravelo_netz: {classes}")
    logging.info(f"Geschrieben: {OUTPUT_PATH}")


if __name__ == '__main__':
    main()
