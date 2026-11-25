#!/bin/bash
# compare_c.sh – fallweiser Vergleich zweier Ergebnisse (Datensatz C, aggregated.gpkg) gegen die OSM-Daten.
#
#   MATCHING_PG=… PGPASSWORD=… ./graph-interface/bikegraph/compare_c.sh <baseline.gpkg> <kandidat.gpkg> <faelle.csv>
#
# Lädt beide nach bikegraph.c_base / bikegraph.c_cand, bewertet jede Kanten-Richtung mit anderer Führungsform
# (sql/70_compare_c.sql) und schreibt die Fälle mit Urteil, Kennzahlen und Lage (lat/lon, TILDA-Link) als CSV.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BASE="$1"; CAND="$2"; CSV="$3"
: "${MATCHING_PG:?MATCHING_PG fehlt}"
for pair in "c_base:$BASE" "c_cand:$CAND"; do
    t="${pair%%:*}"; f="${pair#*:}"
    ogr2ogr -f PostgreSQL "PG:$MATCHING_PG" "$f" hinrichtung -nln "bikegraph.$t" -lco GEOMETRY_NAME=geom -nlt MULTILINESTRING -t_srs EPSG:25833 -overwrite
    ogr2ogr -f PostgreSQL "PG:$MATCHING_PG" "$f" gegenrichtung -nln "bikegraph.$t" -nlt MULTILINESTRING -t_srs EPSG:25833 -append
done
psql "$MATCHING_PG" -v ON_ERROR_STOP=1 -q -P pager=off -v base=bikegraph.c_base -v cand=bikegraph.c_cand \
    -v out=bikegraph.c_faelle -v lage_m=20 -f "$SCRIPT_DIR/sql/70_compare_c.sql"
psql "$MATCHING_PG" -v ON_ERROR_STOP=1 -q -c "\copy (SELECT *, 'http://127.0.0.1:5173/regionen/infravelo?map=18/' || round(lat::numeric, 5) || '/' || round(lon::numeric, 5) AS lokal FROM bikegraph.c_faelle ORDER BY urteil, m DESC) TO '$CSV' WITH CSV HEADER"
echo "$CSV"
