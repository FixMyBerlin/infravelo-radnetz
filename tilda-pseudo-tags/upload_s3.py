#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
upload_s3.py
--------------------------------------------------------------------
Lädt output/infravelo-netz.csv in den privaten S3-Bucket von TILDA, von wo die
TILDA-Prozessierung sie liest. Überschreibt die vorhandene Datei.

Zugang aus tilda-pseudo-tags/.env (siehe .env.example; Werte aus der .env von tilda-geo).

Aufruf (im Projekt-Root):
    .venv/bin/python tilda-pseudo-tags/upload_s3.py
"""

import logging
import sys
from pathlib import Path

import boto3

BASE_DIR = Path(__file__).resolve().parent
CSV_PATH = BASE_DIR / 'output' / 'infravelo-netz.csv'
ENV_PATH = BASE_DIR / '.env'
# Eine Datei für alle TILDA-Umgebungen; der Ordner pseudo-tags/ liegt neben
# data-schema/, region-uploads/ und uploads/
S3_KEY = 'pseudo-tags/infravelo-netz.csv'

logging.basicConfig(stream=sys.stdout, level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')


def read_env() -> dict:
    if not ENV_PATH.exists():
        raise SystemExit(f"Fehlt: {ENV_PATH}. Aus .env.example anlegen, Werte aus der .env von tilda-geo.")
    env = {}
    for line in ENV_PATH.read_text(encoding='utf-8').splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            env[key.strip()] = value.strip().strip('"').strip("'")
    missing = [key for key in ('S3_KEY', 'S3_SECRET', 'S3_REGION', 'S3_BUCKET') if not env.get(key)]
    if missing:
        raise SystemExit(f"In {ENV_PATH} fehlen: {', '.join(missing)}")
    return env


def main():
    if not CSV_PATH.exists():
        raise SystemExit(f"Fehlt: {CSV_PATH}. Erst build_csv.py ausführen.")
    env = read_env()
    s3 = boto3.client('s3', aws_access_key_id=env['S3_KEY'], aws_secret_access_key=env['S3_SECRET'],
                      region_name=env['S3_REGION'])
    s3.upload_file(str(CSV_PATH), env['S3_BUCKET'], S3_KEY, ExtraArgs={'ContentType': 'text/csv; charset=utf-8'})
    head = s3.head_object(Bucket=env['S3_BUCKET'], Key=S3_KEY)
    rows = sum(1 for _ in CSV_PATH.open(encoding='utf-8')) - 1
    logging.info(f"Hochgeladen: {S3_KEY} ({head['ContentLength']} Bytes, {rows} Zeilen, "
                 f"ETag {head['ETag']}, {head['LastModified']:%Y-%m-%d %H:%M} UTC)")


if __name__ == '__main__':
    main()
