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
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
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

# Ziel: die BEZIRKE sind am ZIEL_TAG vollständig bearbeitet; Tempo wird ab START_TAG gemessen
START_TAG = date(2026, 10, 29)
ZIEL_TAG = date(2027, 3, 1)
ZEITZONE = ZoneInfo('Europe/Berlin')


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


def print_prognose(erledigt_m: float, soll_m: float, seit_start_m: float):
    jetzt = datetime.now(ZEITZONE)
    start = datetime.combine(START_TAG, datetime.min.time(), ZEITZONE)
    ziel = datetime.combine(ZIEL_TAG, datetime.min.time(), ZEITZONE)
    vergangen = (jetzt - start).total_seconds() / 86400
    verbleibend = (ziel - jetzt).total_seconds() / 86400
    rest_km = (soll_m - erledigt_m) / 1000
    tempo = seit_start_m / 1000 / vergangen
    nötig = rest_km / verbleibend
    print(f'\nPrognose: 6 Bezirke vollständig bis {ZIEL_TAG:%d.%m.%Y}')
    print(f'  Erledigt {erledigt_m / 1000:.1f} von {soll_m / 1000:.1f} km, noch offen {rest_km:.1f} km')
    plan = vergangen / (ziel - start).total_seconds() * 86400
    print(f'  Zeit    {bar(plan)} {plan:5.1%}  Tag {vergangen:.1f} von {(ziel - start).days} seit {START_TAG:%d.%m.}')
    print(f'  Netz    {bar(erledigt_m / soll_m)} {erledigt_m / soll_m:5.1%}')
    print(f'  Tempo seit {START_TAG:%d.%m.}: {tempo:.1f} km/Tag ({tempo * 7:.1f} km/Woche), nötig: {nötig:.1f} km/Tag ({nötig * 7:.1f} km/Woche)')
    if tempo <= 0:
        print('  Mit diesem Tempo wird das Ziel nicht erreicht (kein Fortschritt seit Start).')
        return
    fertig = jetzt + timedelta(days=rest_km / tempo)
    differenz = (fertig.date() - ZIEL_TAG).days
    print(f'  Fertig bei diesem Tempo: {fertig:%d.%m.%Y}')
    if differenz <= 0:
        print(f'  Ergebnis: on track, {-differenz} Tage vor dem Ziel.')
    else:
        print(f'  Ergebnis: nicht on track, {differenz} Tage nach dem Ziel; '
              f'nötig wären {nötig / tempo:.1f}× das bisherige Tempo.')


def main():
    netz = load_netz()
    netz_m = defaultdict(float)
    for laenge, bezirk in netz.values():
        netz_m[bezirk] += laenge

    seit = datetime.now(timezone.utc) - timedelta(hours=24)
    start = datetime.combine(START_TAG, datetime.min.time(), ZEITZONE)
    gesamt_m = neu_m = seit_start_6_m = 0.0
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
        at = datetime.fromisoformat(entry['updated_at'].replace('Z', '+00:00'))
        if at >= seit:
            neu_m += laenge
        if at >= start and bezirk in BEZIRKE:
            seit_start_6_m += laenge

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

    print_prognose(sum(je_bezirk[b] for b in BEZIRKE), sum(netz_m[b] for b in BEZIRKE), seit_start_6_m)

    if unbekannt:
        print(f'\nHinweis: {len(unbekannt)} erledigte ids stehen nicht in netz_laengen.csv '
              f'(Netz neu zugeteilt?), z. B. {", ".join(unbekannt[:5])}')


if __name__ == '__main__':
    main()
