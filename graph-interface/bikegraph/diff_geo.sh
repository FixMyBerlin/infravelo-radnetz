#!/usr/bin/env bash
# diff_geo.sh – geometrischer Vergleich zweier Datensätze B oder C, unabhängig von element_nr und der Teilung der Kanten
# (sql/80_diff_geo.sql). Für Vergleiche über RVN-Stände hinweg, in denen Kanten umbenannt oder anders geteilt sind
# (z. B. Lieferung 2025 gegen einen Lauf von heute).
#
#   MATCHING_PG=… PGPASSWORD=… ./graph-interface/bikegraph/diff_geo.sh <a> <b> <name> [<ausgabe-ordner>]
#
#   <a>, <b>   Datensatz B oder C, jedes OGR-Format; .gz wird über /vsigzip gelesen. Alle Ebenen der Datei werden geladen
#              (aggregated.gpkg: hinrichtung, gegenrichtung). Nötige Spalten: element_nr, ri, fuehr, pflicht, breite, ofm,
#              farbe, protek, trennstreifen, nutz_beschr.
#   <name>     a-z, 0-9, _; Tabellen diff.<name>_*, Dateien <name>.*
#
# Umgebung: LABEL_A, LABEL_B (Namen der Seiten in Text und Spalten, Standard a und b), SAMPLE_M (Stücklänge, Standard 5),
# TOL_M (Abstand zum Gegenstück, Standard 2), MAX_WINKEL (Richtungsabweichung in Grad, Standard 45).
#
# Verfahren: beide Datensätze in Stücke von SAMPLE_M m mit Fahrtrichtung (ri 0 in Digitalisierungsrichtung, ri 1
# umgekehrt); je Stück das nächste Stück der anderen Seite bis TOL_M m mit höchstens MAX_WINKEL Grad Richtungsabweichung.
# Gepaarte Stücke werden in den acht Attributen verglichen (Breite als Zahl, 2 = 2.0), gleiche Nachbarstücke je Kante und
# Richtung von A zu Abschnitten zusammengefasst.
#
# Ausgang (Ordner): <name>.geojson (WGS84, simplestyle-Farben: orange Attribute anders, rot nur in A, blau nur in B;
# für Placemark, geojson.io), <name>.gpkg (EPSG:25833), <name>_zusammenfassung.csv, <name>_unterschiede.csv
# (km je Unterschied). Tabellen diff.<name>_stuecke, _paare, _diff, _zusammenfassung.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
[ $# -ge 3 ] || { sed -n '2,24p' "$0" >&2; exit 1; }
A="$1"; B="$2"; NAME="$3"; DIR="${4:-.}"
LABEL_A="${LABEL_A:-a}"; LABEL_B="${LABEL_B:-b}"
SAMPLE_M="${SAMPLE_M:-5}"; TOL_M="${TOL_M:-2}"; MAX_WINKEL="${MAX_WINKEL:-45}"
[[ "$NAME" =~ ^[a-z_][a-z0-9_]*$ ]] || { echo "Name nur a-z, 0-9, _" >&2; exit 1; }
for l in "$LABEL_A" "$LABEL_B"; do [[ "$l" =~ ^[a-z0-9_]+$ ]] || { echo "LABEL_A/LABEL_B nur a-z, 0-9, _" >&2; exit 1; }; done
[ "$LABEL_A" != "$LABEL_B" ] || { echo "LABEL_A und LABEL_B müssen verschieden sein" >&2; exit 1; }
: "${MATCHING_PG:?MATCHING_PG fehlt}"
mkdir -p "$DIR"
PSQL=(psql "$MATCHING_PG" -v ON_ERROR_STOP=1 -q -P pager=off)
"${PSQL[@]}" -c "CREATE SCHEMA IF NOT EXISTS diff"

ogr_pfad() { case "$1" in *.gz) echo "/vsigzip/$1" ;; *) echo "$1" ;; esac; }

# lade <datei> <tabelle>: alle Ebenen, nur die verglichenen Spalten, als Text
lade() {
    local src; src="$(ogr_pfad "$1")"
    local erste=1
    "${PSQL[@]}" -c "DROP TABLE IF EXISTS diff.$2"
    while IFS= read -r layer; do
        local mode=(-overwrite); [ $erste = 1 ] || mode=(-append)
        ogr2ogr -f PostgreSQL "PG:$MATCHING_PG" "$src" -nln "diff.$2" "${mode[@]}" -nlt MULTILINESTRING -t_srs EPSG:25833 \
            -lco GEOMETRY_NAME=geom -lco SPATIAL_INDEX=NONE -dialect OGRSQL -sql "SELECT CAST(element_nr AS character(254)) AS element_nr,
              CAST(ri AS integer) AS ri, CAST(fuehr AS character(254)) AS fuehr, CAST(pflicht AS character(254)) AS pflicht,
              CAST(breite AS character(254)) AS breite, CAST(ofm AS character(254)) AS ofm, CAST(farbe AS character(254)) AS farbe,
              CAST(protek AS character(254)) AS protek, CAST(trennstreifen AS character(254)) AS trennstreifen,
              CAST(nutz_beschr AS character(254)) AS nutz_beschr FROM \"$layer\""
        erste=0
    done < <(ogrinfo -ro -q "$src" | sed -n 's/^[0-9]*: \(.*\) (.*)$/\1/p; s/^[0-9]*: \([^(]*\)$/\1/p')
}

echo "== Laden: A ($LABEL_A) $A"
lade "$A" "${NAME}_a"
echo "== Laden: B ($LABEL_B) $B"
lade "$B" "${NAME}_b"

echo "== Vergleich (Stücke ${SAMPLE_M} m, Gegenstück bis ${TOL_M} m, Richtung bis ${MAX_WINKEL}°)"
vars=(-v a="diff.${NAME}_a" -v b="diff.${NAME}_b" -v pre_stuecke="${NAME}_stuecke" -v pre_paare="${NAME}_paare"
      -v pre_diff="${NAME}_diff" -v pre_zusammenfassung="${NAME}_zusammenfassung"
      -v sample_m="$SAMPLE_M" -v tol_m="$TOL_M" -v max_winkel="$MAX_WINKEL" -v label_a="$LABEL_A" -v label_b="$LABEL_B")
for c in element_nr fuehr breite pflicht ofm farbe protek trennstreifen nutz_beschr; do
    vars+=(-v "col_${c}_a=${c}_${LABEL_A}" -v "col_${c}_b=${c}_${LABEL_B}")
done
"${PSQL[@]}" "${vars[@]}" -f "$HERE/sql/80_diff_geo.sql" 2>&1 | { grep -v NOTICE || true; }

echo "== Ausgabe nach $DIR"
rm -f "$DIR/$NAME.geojson" "$DIR/$NAME.gpkg"
ogr2ogr -f GeoJSON "$DIR/$NAME.geojson" "PG:$MATCHING_PG" "diff.${NAME}_diff" -t_srs EPSG:4326 -lco COORDINATE_PRECISION=6 \
    -lco RFC7946=YES -nln "$NAME"
ogr2ogr -f GPKG "$DIR/$NAME.gpkg" "PG:$MATCHING_PG" "diff.${NAME}_diff" -nln "$NAME"
"${PSQL[@]}" -c "\\copy (SELECT * FROM diff.${NAME}_zusammenfassung) TO '$DIR/${NAME}_zusammenfassung.csv' WITH CSV HEADER"
"${PSQL[@]}" -c "\\copy (SELECT art, unterschied, count(*) AS abschnitte, round(sum(laenge_m) / 1000, 2) AS km FROM diff.${NAME}_diff GROUP BY 1, 2 ORDER BY 4 DESC) TO '$DIR/${NAME}_unterschiede.csv' WITH CSV HEADER"
echo "== $NAME (A: $LABEL_A, B: $LABEL_B)"
"${PSQL[@]}" -c "SELECT * FROM diff.${NAME}_zusammenfassung"
"${PSQL[@]}" -c "SELECT unterschied, count(*) AS abschnitte, round(sum(laenge_m) / 1000, 2) AS km FROM diff.${NAME}_diff WHERE art = 'Attribute anders' GROUP BY 1 ORDER BY 3 DESC LIMIT 15"
