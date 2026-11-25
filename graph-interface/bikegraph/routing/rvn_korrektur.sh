#!/bin/bash
# Korrigierte Kopie der RVN-Daten: rvn_korrektur.sql (Datenbank, matching_korr) und Export als FlatGeobuf neben die
# Rohdaten (…_korrigiert.fgb, gleiche Felder und Ebene wie vorrangnetz_details_combined_rvn.fgb) sowie die
# Korrekturliste als CSV (neben das Ziel). Die Rohdaten bleiben unverändert. Wahlweise: der QA-Lauf (routing_qa.sh) prüft
# gegen das RVN von v7; wer gegen die korrigierte Kopie prüfen will, lädt sie wie die Rohdaten nach matching.reference_edges.
# Aufruf: rvn_korrektur.sh [Ziel-fgb]
# Umgebung: MATCHING_PG (libpq-Verbindung, z. B. "host=127.0.0.1 port=5433 dbname=postgres user=postgres")
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ZIEL="${1:-$HERE/../../../processing/output/rvn/vorrangnetz_details_combined_rvn_korrigiert.fgb}"
psql "${MATCHING_PG:?MATCHING_PG fehlt}" -v ON_ERROR_STOP=1 -q -P pager=off -f "$HERE/rvn_korrektur.sql"
rm -f "$ZIEL"
ogr2ogr -f FlatGeobuf "$ZIEL" "PG:$MATCHING_PG" -nln vorrangnetz_details_combined_rvn -nlt MULTILINESTRING -a_srs EPSG:25833 \
    -sql "SELECT element_nr, strassenname, strassenklasse, verkehrsrichtung, beginnt_bei_vp, endet_bei_vp, edge_source, geom
          FROM matching_korr.reference_raw ORDER BY ogc_fid"
psql "$MATCHING_PG" -q -c "\copy (SELECT element_nr, art, element_darunter, beschreibung FROM matching_korr.korrektur ORDER BY art, element_nr) TO '${ZIEL%.fgb}_korrekturen.csv' CSV HEADER"
echo "geschrieben: $ZIEL"
