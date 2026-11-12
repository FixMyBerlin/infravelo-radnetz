#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
download_inputs.py
--------------------------------------------------------------------
Lädt die Eingangsdaten, die nicht im Repo liegen, aus dem gemeinsamen
Google-Drive-Ordner und legt sie an ihre Stelle im Repo. So rechnen alle mit
denselben Dateien.

Der Ordner im Drive ist flach: INPUT_FILES ordnet jedem Dateinamen dort seinen
Pfad im Repo zu.
data/inputs.json (eingecheckt) hält Größe und Prüfsumme jeder Datei fest.
Geladen werden nur Dateien, die lokal fehlen oder davon abweichen; stimmen alle,
braucht das Skript weder Netz noch Link. Der Freigabe-Link steht in .env
(INPUTS_DRIVE_FOLDER_URL, siehe .env.example); fehlt er, bricht das Skript ab.
Weicht eine heruntergeladene Datei ab, bricht es ebenfalls ab, bevor es etwas
überschreibt.

Aufruf (im Projekt-Root):
    .venv/bin/python data/download_inputs.py                    # herunterladen und prüfen
    .venv/bin/python data/download_inputs.py --stage <ordner>   # Dateien zum Hochladen ins Drive sammeln
    .venv/bin/python data/download_inputs.py --write-manifest   # inputs.json aus den lokalen Dateien schreiben

Wird außerdem zu Beginn von ren-network/merge_networks.py und
netzanpassungen/write_app_input.py aufgerufen.
"""

import argparse
import hashlib
import json
import logging
import shutil
import sys
import tempfile
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / '.env'
MANIFEST_PATH = ROOT / 'data' / 'inputs.json'
ENV_KEY = 'INPUTS_DRIVE_FOLDER_URL'

# Eingangsdaten, die weder im Repo liegen noch von einem Skript geladen werden:
# Dateiname im Drive (flach) → Pfad im Repo
INPUT_FILES = {
    'netzquellen_hauptstrassennetz.gpkg': 'data/netzquellen/hauptstrassennetz.gpkg',
    'netzquellen_radverkehrsnetz.gpkg': 'data/netzquellen/radverkehrsnetz.gpkg',
    'netzquellen_radschnellverbindungen.gpkg': 'data/netzquellen/radschnellverbindungen.gpkg',
    'netzquellen_touristisches_radnetz.gpkg': 'data/netzquellen/touristisches_radnetz.gpkg',
    'detailnetz_strassenabschnitte_2026-10-06.fgb': 'data/Berlin Straßenabschnitte Detailnetz 2026-10-06.fgb',
    'detailnetz_verbindungspunkte.fgb': 'data/Berlin Verbindungspunkte Detailnetz.fgb',
    'lor_planungsraeume_2021.geojson': 'mapping-zuteilung/data/lor_plr_2021.geojson',
}

logging.basicConfig(stream=sys.stdout, level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')


def read_folder_url() -> str:
    values = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding='utf-8').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key, value = line.split('=', 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
    if not values.get(ENV_KEY):
        raise SystemExit(f"{ENV_KEY} fehlt in {ENV_PATH}. Aus .env.example anlegen und den Freigabe-Link "
                         "des Google-Drive-Ordners eintragen (von Tobias oder Henri).")
    return values[ENV_KEY]


def file_info(path: Path) -> dict:
    digest = hashlib.sha256()
    with open(path, 'rb') as file:
        for block in iter(lambda: file.read(1 << 20), b''):
            digest.update(block)
    return {'size': path.stat().st_size, 'sha256': digest.hexdigest()}


def write_manifest():
    missing = [relative for relative in INPUT_FILES.values() if not (ROOT / relative).exists()]
    if missing:
        raise SystemExit(f"Fehlen lokal: {missing}")
    manifest = {name: file_info(ROOT / relative) for name, relative in INPUT_FILES.items()}
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    logging.info(f"Geschrieben: {MANIFEST_PATH} ({len(manifest)} Dateien)")


def stage(target: Path):
    """Kopiert die Eingangsdaten unter ihrem Drive-Namen in einen flachen Ordner, der ins Drive kommt."""
    target.mkdir(parents=True, exist_ok=True)
    for name, relative in INPUT_FILES.items():
        shutil.copy2((ROOT / relative).resolve(), target / name)
    logging.info(f"{len(INPUT_FILES)} Dateien in {target}; den Inhalt dieses Ordners ins Drive kopieren")


def download():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding='utf-8'))
    # Nur laden, was lokal fehlt oder von inputs.json abweicht
    outdated = [name for name, relative in INPUT_FILES.items()
                if not (ROOT / relative).exists() or file_info(ROOT / relative) != manifest.get(name)]
    if not outdated:
        logging.info(f"{len(INPUT_FILES)} Eingangsdaten lokal vorhanden und wie in data/inputs.json")
        return

    import gdown

    url = read_folder_url()
    with tempfile.TemporaryDirectory() as temp:
        gdown.download_folder(url, output=temp, quiet=True)
        # Drive und macOS schreiben Umlaute unterschiedlich zusammengesetzt (NFC/NFD)
        found = {unicodedata.normalize('NFC', path.name): path for path in Path(temp).rglob('*') if path.is_file()}
        missing = [name for name in outdated if name not in found]
        if missing:
            raise SystemExit(f"Fehlen im Drive-Ordner: {missing}")
        # Erst alle prüfen, dann kopieren: Ein Abbruch soll keine gemischten Eingangsdaten hinterlassen
        differing = [name for name in outdated if file_info(found[name]) != manifest.get(name)]
        if differing:
            raise SystemExit(f"{differing} im Drive weicht von data/inputs.json ab. Ist das Drive neuer als "
                             "das Repo, inputs.json mit --write-manifest neu schreiben und committen.")
        for name in outdated:
            destination = ROOT / INPUT_FILES[name]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(found[name], destination)
    logging.info(f"{len(outdated)} von {len(INPUT_FILES)} Eingangsdaten aus dem Drive geladen und geprüft")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--stage', type=Path, help='Dateien zum Hochladen in diesen Ordner kopieren')
    parser.add_argument('--write-manifest', action='store_true', help='data/inputs.json neu schreiben')
    args = parser.parse_args()
    if args.write_manifest:
        write_manifest()
    elif args.stage:
        stage(args.stage)
    else:
        download()


if __name__ == '__main__':
    main()
