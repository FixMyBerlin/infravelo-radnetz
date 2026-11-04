#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tagesstand.py
--------------------------------------------------------------------
Tagesbericht zur Kartierung des REN+-Netzes (nur Standardbibliothek, läuft
auch in der Cloud): erledigte Kilometer gesamt, neu in den letzten 24 Stunden
und je Person der Anteil an den Bezirken.

Eingaben:
  netz_laengen.csv  lfd_nr -> laenge_m, bezirk (aus mapping-zuteilung/output/zuteilung_netz.geojson)
  key-value-db      Projekt infravelo-tracker, ein Eintrag je erledigter Kante (id = lfd_nr)

Die CSV ändert sich nur, wenn assign_accounts.py das Netz neu zuteilt.
"""

import csv
import json
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE_URL = 'https://key-value-store.fixmycity.workers.dev'
ORIGIN = 'https://radnetz-mapping.netlify.app'
PROJECT = 'infravelo-tracker'
API_KEY = 'kv_b11a83b26cb009abb622f111fdfb2ebef171c7d9'  # öffentlich, kein Geheimnis
PAGE_SIZE = 500
CSV_PATH = Path(__file__).resolve().parent / 'netz_laengen.csv'

BEZIRKE = ['Neukölln', 'Treptow-Köpenick', 'Tempelhof-Schöneberg',
           'Steglitz-Zehlendorf', 'Spandau', 'Charlottenburg-Wilmersdorf']
BAR_WIDTH = 20


def fetch_entries() -> list:
    entries, cursor = [], None
    while True:
        query = {'limit': PAGE_SIZE, **({'cursor': cursor} if cursor else {})}
        request = urllib.request.Request(
            f'{BASE_URL}/v1/projects/{PROJECT}/entries?{urllib.parse.urlencode(query)}',
            headers={'X-Api-Key': API_KEY, 'Origin': ORIGIN, 'User-Agent': 'infravelo-radnetz'})
        with urllib.request.urlopen(request, timeout=30) as response:
            page = json.load(response)
        entries.extend(page['items'])
        cursor = page.get('next_cursor')
        if not cursor:
            return entries


def load_netz() -> dict:
    with open(CSV_PATH, encoding='utf-8', newline='') as f:
        return {row['lfd_nr']: (float(row['laenge_m']), row['bezirk'].split(' - ', 1)[-1])
                for row in csv.DictReader(f)}


def bar(share: float) -> str:
    filled = round(min(share, 1) * BAR_WIDTH)
    return '█' * filled + '░' * (BAR_WIDTH - filled)


def main():
    netz = load_netz()
    netz_m = defaultdict(float)
    for laenge, bezirk in netz.values():
        netz_m[bezirk] += laenge

    seit = datetime.now(timezone.utc) - timedelta(hours=24)
    gesamt_m = neu_m = 0.0
    je_bezirk = defaultdict(float)
    je_person = defaultdict(lambda: defaultdict(float))
    unbekannt = []
    for entry in fetch_entries():
        if entry['id'] not in netz:
            unbekannt.append(entry['id'])
            continue
        laenge, bezirk = netz[entry['id']]
        gesamt_m += laenge
        je_bezirk[bezirk] += laenge
        je_person[entry['updated_by']['display_name']][bezirk] += laenge
        if datetime.fromisoformat(entry['updated_at'].replace('Z', '+00:00')) >= seit:
            neu_m += laenge

    total_m = sum(netz_m.values())
    print(f"Kartierung REN+ Netz, Stand {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f'Erledigt gesamt: {gesamt_m / 1000:.1f} km von {total_m / 1000:.1f} km '
          f'({gesamt_m / total_m:.1%}), neu in 24 h: {neu_m / 1000:.1f} km')

    breite = max(len(b) for b in BEZIRKE)
    print('\nBezirke (alle Personen)')
    for bezirk in BEZIRKE:
        share = je_bezirk[bezirk] / netz_m[bezirk]
        print(f'  {bezirk:<{breite}} {bar(share)} {share:5.1%}  {je_bezirk[bezirk] / 1000:5.1f} von {netz_m[bezirk] / 1000:.1f} km')

    print('\nJe Person: Anteil am Bezirk, den diese Person erledigt hat')
    for person in sorted(je_person, key=lambda p: -sum(je_person[p].values())):
        km = sum(je_person[person].values()) / 1000
        print(f'\n{person} ({km:.1f} km insgesamt)')
        for bezirk in BEZIRKE:
            share = je_person[person][bezirk] / netz_m[bezirk]
            print(f'  {bezirk:<{breite}} {bar(share)} {share:5.1%}')

    if unbekannt:
        print(f'\nHinweis: {len(unbekannt)} erledigte ids stehen nicht in netz_laengen.csv '
              f'(Netz neu zugeteilt?), z. B. {", ".join(unbekannt[:5])}')


if __name__ == '__main__':
    main()
