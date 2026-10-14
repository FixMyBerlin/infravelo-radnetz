#!/bin/bash
# Erzeugt die CSV für den TILDA-Pseudo-Tag infravelo_netz und lädt sie nach S3.
# Optional: Pfad zum Endergebnis (Standard: Lieferung 2025, Datensatz C).
set -e
cd "$(dirname "$0")/.."
if [ -n "$1" ]; then
    .venv/bin/python tilda-pseudo-tags/build_csv.py --input "$1"
else
    .venv/bin/python tilda-pseudo-tags/build_csv.py
fi
.venv/bin/python tilda-pseudo-tags/upload_s3.py
