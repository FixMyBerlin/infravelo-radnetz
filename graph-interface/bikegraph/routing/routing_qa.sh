#!/bin/bash
# Routing-Matcher als zweite Matching-Option zur Qualitätssicherung (README.md in diesem Ordner): das RVN als gewichtete
# Wege durch den Routing-Graphen, verglichen mit dem Ergebnis von v7 (Datensatz C), und ein Bericht mit den auffälligen
# Stellen: unbequeme Verbindungen (Treppen, Erschließungsstraßen, Baustellen, Brücken über Netzlücken), lange
# Kreuzungsstücke, Abbrüche (Abschnitte ohne durchgehenden Weg) und die Unterschiede zu v7 mit Urteil aus den Belegen.
# Schritte: Eingänge laden (v7, Baseline, Bushaltestellen), Graph (graph.sql), Routing (abschnitte.sh), Lücken (luecken.sql),
# Martin-Ebenen (martin.sql, Schema routing_martin), Bericht (qa_bericht.sql und Dateien in AUSGABE).
# Aufruf: MATCHING_PG=... PGPASSWORD=... graph-interface/bikegraph/routing/routing_qa.sh [psql-Optionen für abschnitte.sh]
# Umgebung:
#   MATCHING_PG    libpq-Verbindung (z. B. "host=127.0.0.1 port=5433 dbname=postgres user=postgres"), Passwort aus PGPASSWORD
#   V7_C           Datensatz C von v7 (aggregated.gpkg mit den Ebenen hinrichtung und gegenrichtung), Standard
#                  processing/output/mm-datensatz-c-a/post/aggregated.gpkg; fehlt die Datei, bleibt eine schon geladene
#                  Tabelle bikegraph.c_v7, sonst entfällt der Vergleich
#   BASE_C         Baseline (Datensatz C, z. B. processing/output/post-baseline/aggregated.gpkg), wahlweise -> bikegraph.c_base
#   HALTESTELLEN   Bushaltestellen (Standard processing/output/bus_stops_on_rvn.fgb, aus processing/scripts/prepare_bus_stops.py)
#   AUSGABE        Ordner des Berichts (Standard processing/output/routing-qa)
#   OHNE_GRAPH     1 = Routing-Graph nicht neu bauen
#   LANG_M         lange Kreuzungsstücke ab so vielen Metern (Standard 50)
#   dazu die Schalter von abschnitte.sh (TEILE, STEINER, STEINER_PY, STEINER_LAMBDA, ZWEITLAUF, KANDIDATEN, VERSATZ)
# Braucht: psql, ogr2ogr, pgRouting, Python mit scipy und psycopg2 (Teil 2s).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
: "${MATCHING_PG:?MATCHING_PG fehlt}"
V7_C="${V7_C:-$REPO/processing/output/mm-datensatz-c-a/post/aggregated.gpkg}"
HALTESTELLEN="${HALTESTELLEN:-$REPO/processing/output/bus_stops_on_rvn.fgb}"
AUSGABE="${AUSGABE:-$REPO/processing/output/routing-qa}"
P=(psql "$MATCHING_PG" -v ON_ERROR_STOP=1 -q -P pager=off)
start=$(date +%s)
schritt() { echo "== $1 ($(( $(date +%s) - start )) s)"; }
# Ausgabe filtern, ohne Fehler des Schritts zu verschlucken (pipefail: der Status des Schritts zählt, grep kann nicht scheitern)
filter() { { grep -v "$1" || true; }; }

schritt "Eingänge"
# Tabellen der Graph-Pipeline, die der Routing-Graph braucht (Tabelle:Skript, das sie baut)
fehlt=0
for paar in bikegraph.edges:graph.sh bikegraph.osm_ways:graph.sh bikegraph.input_edges:graph.sh bikegraph.bl_input:radweg_faltung.sh \
            bikegraph.bl_faltung:radweg_faltung.sh "bikegraph.dc_input:datensatz_c.sh (Schritt sql/104_datensatz_c_eingang.sql)" \
            "matching.reference_edges:dem Laden des RVN fürs Matching"; do
    t="${paar%%:*}"
    if [ "$("${P[@]}" -At -c "SELECT to_regclass('$t') IS NOT NULL")" != t ]; then
        echo "FEHLER: $t fehlt, wird gebaut von graph-interface/bikegraph/${paar#*:}"; fehlt=1
    fi
done
[ "$fehlt" = 0 ] || exit 1
lade_c() {  # Datensatz C (Ebenen hinrichtung, gegenrichtung) -> Tabelle
    ogr2ogr -f PostgreSQL "PG:$MATCHING_PG" "$1" hinrichtung -nln "$2" -lco GEOMETRY_NAME=geom -nlt MULTILINESTRING -t_srs EPSG:25833 -overwrite
    ogr2ogr -f PostgreSQL "PG:$MATCHING_PG" "$1" gegenrichtung -nln "$2" -nlt MULTILINESTRING -t_srs EPSG:25833 -append
}
if [ -f "$V7_C" ]; then lade_c "$V7_C" bikegraph.c_v7; echo "v7: $V7_C"; else echo "v7: $V7_C fehlt, Vergleich mit vorhandener bikegraph.c_v7 oder ohne"; fi
if [ -n "${BASE_C:-}" ] && [ -f "$BASE_C" ]; then lade_c "$BASE_C" bikegraph.c_base; echo "Baseline: $BASE_C"; fi
if [ -f "$HALTESTELLEN" ]; then
    ogr2ogr -f PostgreSQL "PG:$MATCHING_PG" "$HALTESTELLEN" -nln bikegraph.bus_stops -t_srs EPSG:25833 -lco GEOMETRY_NAME=geom -overwrite
    echo "Haltestellen: $HALTESTELLEN"
else
    echo "Haltestellen: $HALTESTELLEN fehlt, ohne Umwandlung der Schutzstreifen an Haltestellen"
fi

if [ "${OHNE_GRAPH:-0}" != 1 ]; then
    schritt "Graph"
    "${P[@]}" -f "$HERE/graph.sql" 2>&1 | filter NOTICE
fi
schritt "Routing"
"$HERE/abschnitte.sh" -v radius_m=0 "$@" 2>&1 | filter 'NOTICE\|^INSERT\|DETAIL\|drop cascades'
schritt "Lücken"
"${P[@]}" -f "$HERE/luecken.sql" > /dev/null
schritt "Martin"
"${P[@]}" -f "$HERE/martin.sql" 2>&1 | filter 'NOTICE\|DETAIL\|drop cascades'

schritt "Bericht"
mkdir -p "$AUSGABE"
export_fgb() {  # Name, SQL
    rm -f "$AUSGABE/$1.fgb"
    ogr2ogr -f FlatGeobuf "$AUSGABE/$1.fgb" "PG:$MATCHING_PG" -sql "$2" -nln "$1"
}
export_fgb unbequem "SELECT * FROM routing_martin.routing_unbequem ORDER BY art, m DESC"
export_fgb kreuzungen_lang "SELECT * FROM routing_martin.routing_crossings WHERE m >= ${LANG_M:-50} ORDER BY m DESC"
export_fgb luecken "SELECT * FROM routing_martin.routing_luecken ORDER BY len DESC"
export_fgb abweichungen_v7 "SELECT * FROM routing_martin.routing_urteil_routing UNION ALL SELECT * FROM routing_martin.routing_urteil_v7
    UNION ALL SELECT * FROM routing_martin.routing_urteil_grenzfall ORDER BY urteil, grund, laenge_m DESC"
"${P[@]}" -c "\copy (SELECT urteil, grund, element_nr, ri, rvn_id, strasse, laenge_m, routing, v7, m_routing, abstand_routing, m_v7, abstand_v7,
    rueckfall, unbequem, kandidat, belege, viewer FROM (SELECT * FROM routing_martin.routing_urteil_routing UNION ALL SELECT * FROM routing_martin.routing_urteil_v7
    UNION ALL SELECT * FROM routing_martin.routing_urteil_grenzfall) x
    ORDER BY CASE urteil WHEN 'v7 richtig' THEN 1 WHEN 'Routing richtig' THEN 2 WHEN 'Grenzfall' THEN 3 ELSE 4 END, grund, laenge_m DESC) TO '$AUSGABE/abweichungen_v7.csv' CSV HEADER"
"${P[@]}" -v lang_m="${LANG_M:-50}" -f "$HERE/qa_bericht.sql" | tee "$AUSGABE/zusammenfassung.txt"
schritt "fertig, Bericht in $AUSGABE"
