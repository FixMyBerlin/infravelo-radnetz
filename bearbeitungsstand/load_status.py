#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
load_status.py
--------------------------------------------------------------------
Liest, welche Linien im Mapping-Editor als erledigt markiert sind.

Der Editor (radnetz-mapping.netlify.app) speichert die Markierung "Done" je
Linie in der key-value-db, ein Projekt je Aufgabe (TRACKERS). Ein Eintrag
bedeutet erledigt; wird die Markierung zurückgenommen, ist der Eintrag weg.
Die id des Eintrags ist die id der Linie im Datensatz.

Jeder Abruf wird in cache/<tracker>.json abgelegt. Ist die API nicht
erreichbar, wird der letzte Stand aus dem Cache verwendet.

Wird von mapping-zuteilung/assign_accounts.py und
maproulette-centerline-tracks/extract_centerline_tracks.py aufgerufen.
"""

import json
import logging
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

import pandas as pd

BASE_URL = 'https://key-value-store.fixmycity.workers.dev'
# Die API verlangt einen erlaubten Origin; das ist die Adresse des Editors
ORIGIN = 'https://radnetz-mapping.netlify.app'
# Die Projekt-Schlüssel sind öffentlich (wie im Editor, modules/progress/tracker.ts)
TRACKERS = {
    # id = lfd_nr der Netzkante
    'mapping': {'project': 'infravelo-tracker', 'api_key': 'kv_b11a83b26cb009abb622f111fdfb2ebef171c7d9'},
    # id = id des Wegs, z.B. way/123/cycleway/right
    'track': {'project': 'infravelo-track-tracker', 'api_key': 'kv_d7c690c2b2a55df1721bbc3022d255073c2380c8'},
}
PAGE_SIZE = 500
CACHE_DIR = Path(__file__).resolve().parent / 'cache'

STATUS_DONE = 'erledigt'
STATUS_OPEN = 'offen'


def _fetch(tracker: str) -> list:
    config = TRACKERS[tracker]
    entries, cursor = [], None
    while True:
        query = {'limit': PAGE_SIZE, **({'cursor': cursor} if cursor else {})}
        request = urllib.request.Request(
            f"{BASE_URL}/v1/projects/{config['project']}/entries?{urllib.parse.urlencode(query)}",
            headers={'X-Api-Key': config['api_key'], 'Origin': ORIGIN, 'User-Agent': 'infravelo-radnetz'})
        with urllib.request.urlopen(request, timeout=30) as response:
            page = json.load(response)
        entries.extend(page['items'])
        cursor = page.get('next_cursor')
        if not cursor:
            return entries


def load_done(tracker: str) -> tuple[dict, str]:
    """
    Rückgabe: erledigte Linien als {id: {'von': Name, 'am': Datum}} und der
    Zeitpunkt, zu dem dieser Stand abgerufen wurde.
    """
    cache_path = CACHE_DIR / f'{tracker}.json'
    try:
        cache = {'abgerufen': datetime.now().isoformat(timespec='minutes'), 'entries': _fetch(tracker)}
        CACHE_DIR.mkdir(exist_ok=True)
        cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding='utf-8')
    except OSError as error:
        if not cache_path.exists():
            raise SystemExit(f"Bearbeitungsstand '{tracker}' nicht abrufbar und kein Cache vorhanden: {error}")
        cache = json.loads(cache_path.read_text(encoding='utf-8'))
        logging.warning(f"Bearbeitungsstand '{tracker}' nicht abrufbar ({error}), "
                        f"verwende den Cache vom {cache['abgerufen']}")
    done = {entry['id']: {'von': entry['updated_by']['display_name'], 'am': entry['updated_at'][:10]}
            for entry in cache['entries']}
    logging.info(f"Bearbeitungsstand '{tracker}' vom {cache['abgerufen']}: {len(done)} Linien erledigt")
    return done, cache['abgerufen']


def add_status(features: pd.DataFrame, id_column: str, tracker: str) -> str:
    """
    Ergänzt bearbeitungsstand (erledigt / offen), erledigt_von und erledigt_am.
    Rückgabe: Zeitpunkt des Abrufs.
    """
    done, fetched_at = load_done(tracker)
    ids = features[id_column].astype(str)
    features['bearbeitungsstand'] = ids.map(lambda value: STATUS_DONE if value in done else STATUS_OPEN)
    features['erledigt_von'] = ids.map(lambda value: done.get(value, {}).get('von'))
    features['erledigt_am'] = ids.map(lambda value: done.get(value, {}).get('am'))
    unknown = set(done) - set(ids)
    if unknown:
        logging.warning(f"{len(unknown)} erledigte Linien stehen nicht mehr im Datensatz, z.B. {sorted(unknown)[:3]}")
    return fetched_at
