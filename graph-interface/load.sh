#!/bin/bash
# load.sh
#
# Lädt Referenz- und Eingangsnetz als pgRouting-Kantentabellen in PostGIS
# (Schema `matching`, siehe README.md).
#
# Verwendung:
#   MATCHING_PG="host=127.0.0.1 port=5432 dbname=… user=…" ./graph-interface/load.sh [--netz rvn|ren]
# Passwort über PGPASSWORD oder ~/.pgpass.
#
# Voraussetzung: processing/process_radnetz.sh und processing/scripts/prepare_tilda_routing.py
# sind für dasselbe Netz gelaufen.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROCESSING_DIR="$SCRIPT_DIR/../processing"
NETZ="rvn"
NODE_TOLERANCE_M="0.01"  # wie network.node_tolerance_m in map-matching/config/default.toml

while [[ $# -gt 0 ]]; do
    case $1 in
        --netz) NETZ="$2"; shift 2 ;;
        *) echo "Unbekanntes Argument: $1" >&2; exit 1 ;;
    esac
done

case "$NETZ" in
    rvn) REFERENCE="$PROCESSING_DIR/output/rvn/vorrangnetz_details_combined_rvn.fgb"
         ROUTING_DIR="$PROCESSING_DIR/output/TILDA-routing" ;;
    ren) REFERENCE="$PROCESSING_DIR/output/ren/ren_netz_details_combined.fgb"
         ROUTING_DIR="$PROCESSING_DIR/output/TILDA-routing-ren" ;;
    *) echo "--netz muss rvn oder ren sein" >&2; exit 1 ;;
esac

if [ -z "${MATCHING_PG:-}" ]; then
    echo "MATCHING_PG fehlt (libpq-Verbindung, z.B. \"host=127.0.0.1 port=5432 dbname=tilda user=postgres\")" >&2
    exit 1
fi
for f in "$REFERENCE" "$ROUTING_DIR/TILDA Routing Bikelanes Translated.fgb" \
         "$ROUTING_DIR/TILDA Routing Streets Translated.fgb" "$ROUTING_DIR/TILDA Routing Paths Translated.fgb"; do
    [ -f "$f" ] || { echo "Fehlt: $f" >&2; exit 1; }
done

PSQL=(psql "$MATCHING_PG" -v ON_ERROR_STOP=1 -q)

echo "Schema"
"${PSQL[@]}" -f "$SCRIPT_DIR/sql/00_schema.sql"

load() {  # load <fgb> <staging table>
    ogr2ogr -f PostgreSQL "PG:$MATCHING_PG" "$1" \
        -nln "matching_staging.$2" -overwrite \
        -lco GEOMETRY_NAME=geom -lco FID=ogc_fid -lco SPATIAL_INDEX=NONE -lco LAUNDER=NO
}

echo "Staging: Referenznetz ($NETZ)"
load "$REFERENCE" reference_raw
echo "Staging: Eingangsnetz"
load "$ROUTING_DIR/TILDA Routing Bikelanes Translated.fgb" input_bikelanes
load "$ROUTING_DIR/TILDA Routing Streets Translated.fgb" input_streets
load "$ROUTING_DIR/TILDA Routing Paths Translated.fgb" input_paths

echo "matching.reference_edges / reference_vertices"
"${PSQL[@]}" -v node_tolerance_m="$NODE_TOLERANCE_M" -f "$SCRIPT_DIR/sql/01_reference.sql"
echo "matching.input_edges / input_vertices"
"${PSQL[@]}" -f "$SCRIPT_DIR/sql/02_input.sql"

echo "Prüfungen"
"${PSQL[@]}" -P pager=off -f "$SCRIPT_DIR/sql/03_checks.sql"
