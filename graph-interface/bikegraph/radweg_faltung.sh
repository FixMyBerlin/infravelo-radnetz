#!/usr/bin/env bash
# Radwege (alle TILDA bikelanes: separate Wege und Seitenobjekte) auf die Straßen falten (HMM/Viterbi, map-matching run --pg).
#   1  Eingang und Netze (sql/100_radweg_eingang.sql)
#   2  Durchgang 1: alle Straßen aus dem TILDA-Routing-Export, ohne Tunnel (bikegraph.bl_strassen1)
#   3  Durchgang 2: separate Radwege (auch Seitenobjekte außerhalb des Straßennetzes) mit < 50 % Faltung in
#      Durchgang 1, getrennt nach Richtung des Radwegs:
#      2b Zweirichtungs-Radwege auf Straßen in beide Richtungen (bikegraph.bl_strassen_beide)
#      2e Einrichtungs-Radwege auf Straßen mit umgedrehten Einbahnen (bikegraph.bl_strassen2; dual_carriageway und
#         Kreisverkehre bleiben einrichtig); beide Ergebnisse vereinigt in bikegraph.bl_iv2 (+ _traces, _stubs)
#   4  Ergebnis, Plausibilitätswerte (ohne Filter) und Export für Martin (sql/101_radweg_ergebnis.sql)
# Matcher wie das RVN-Matching (Richtung beachtet, kein Namens-Term, Verkettung bis 70 Grad), aber mit Null-Zustand:
# ein Radweg ohne Straße daneben darf ungefaltet bleiben.
# Voraussetzung: bikegraph.edges/tilda/side_objects (graph.sh), public.routing (TILDA, mit tunnel, dual_carriageway, roundabout),
#   matching.reference_edges (../load.sh, nur für die Martin-Ebene rvn), gebauter Matcher. Umgebung: MATCHING_PG, PGPASSWORD; MAX_TURN_DEG (Standard 70);
#   NULL_SWITCH_PENALTY (Strafe je Wechsel in den/aus dem Null-Zustand, Standard 8: ein Sprung zwischen zwei
#   unverbundenen Straßen über den Null-Zustand soll teurer sein als ein etwas weiterer, aber topologisch passender Weg);
#   CANDIDATE_RADIUS (Suchradius für Kandidatenkanten je Beobachtung, Standard 40 m: sehr breite Fahrbahnen wie der
#   Große Stern liegen bis ~45 m vom Radweg); SAMPLE_M (Abstand der Beobachtungen entlang der Traces, Standard 5 m);
#   CONTEXT_M (Kontext je Trace: Anlauf/Auslauf aus Wegen anderer Traces, stützt nur das Matching; Standard 0 = aus);
#   ISOLIERT_FALTEN (Standard false: separate Radwege mit TILDA-Kategorie *_isolated werden nicht gefaltet und
#   gehen ungefaltet in den RVN-Schritt); TRACE_STRATEGIE (Standard topology; kreuzungen: Abschnitte zwischen
#   Verzweigungen und je Verzweigung jeder Übergang als eigene Trace, siehe map-matching trace.strategy) und KREUZUNG_M
#   (kreuzungen: Länge je Seite eines Übergangs in m, Standard 0 = ganze Abschnitte)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PROCESSING="${PROCESSING:-$(cd "$HERE/../.." && pwd)/processing}"
MATCHER="${MATCHER:-$PROCESSING/map-matching/target/release/map-matching}"
MAX_TURN_DEG="${MAX_TURN_DEG:-70}"
NULL_SWITCH_PENALTY="${NULL_SWITCH_PENALTY:-8}"
CANDIDATE_RADIUS="${CANDIDATE_RADIUS:-40}"
SAMPLE_M="${SAMPLE_M:-5}"
CONTEXT_M="${CONTEXT_M:-0}"
ISOLIERT_FALTEN="${ISOLIERT_FALTEN:-false}"
TRACE_STRATEGIE="${TRACE_STRATEGIE:-topology}"
KREUZUNG_M="${KREUZUNG_M:-0}"
OUT="${OUT:-/tmp/radweg_faltung}"
PSQL=(psql "${MATCHING_PG:?MATCHING_PG fehlt}" -v ON_ERROR_STOP=1 -q -P pager=off)
mkdir -p "$OUT"
sql() { "${PSQL[@]}" "$@" 2>&1 | { grep -v NOTICE || true; }; }

match() { # input reference intervals log
    (cd "$PROCESSING" && "$MATCHER" --pg run --set paths.root="\"$PROCESSING\"" \
        --set postgres.input_edges="$1" --set postgres.reference_edges="$2" --set postgres.intervals="$3" \
        --set network.respect_direction=true --set 'paths.tilda=[{data_source="bikelanes", path="-"}]' \
        --set hmm.name_mismatch_penalty=0 --set hmm.null_switch_penalty="$NULL_SWITCH_PENALTY" --set hmm.candidate_radius_m="$CANDIDATE_RADIUS" --set trace.sample_interval_m="$SAMPLE_M" --set trace.context_m="$CONTEXT_M" --set trace.max_turn_deg="$MAX_TURN_DEG" \
        --set trace.strategy="\"$TRACE_STRATEGIE\"" --set trace.kreuzung_m="$KREUZUNG_M" \
        --set network.topology_report=false --set postgres.intervals_only=true --set paths.output_dir="\"$OUT\"" \
        > "$OUT/$4.log" 2>&1)
    sed 's/\x1b\[[0-9;]*m//g' "$OUT/$4.log" | grep -E "Topologie-Traces|Traces:" | sed 's/^.*INFO /   /'
}

echo "== Eingang und Netze"
sql -f "$HERE/sql/100_radweg_eingang.sql"

# Eingang der Durchgänge: bl_input, bei ISOLIERT_FALTEN=false ohne separate Radwege *_isolated (TILDA: nicht neben
# einer Straße); sie bleiben in bl_input, haben dann keine Faltung und gehen über radwege_abgelehnt in den RVN-Schritt
sql -v isoliert_falten="$ISOLIERT_FALTEN" <<'SQL'
DROP TABLE IF EXISTS bikegraph.bl_input1;
CREATE TABLE bikegraph.bl_input1 AS
SELECT * FROM bikegraph.bl_input
WHERE :isoliert_falten OR NOT (art IN ('separat', 'seitenobjekt_separat') AND kategorie LIKE '%\_isolated');
ALTER TABLE bikegraph.bl_input1 ADD PRIMARY KEY (id);
SELECT 'nicht gefaltet (isolated)' AS teil, count(*) AS wege, round((sum(cost) / 1000)::numeric) AS km
FROM bikegraph.bl_input i WHERE NOT EXISTS (SELECT 1 FROM bikegraph.bl_input1 j WHERE j.id = i.id);
SQL

echo "== Durchgang 1: Straßen mit OSM-Richtungen (ohne Tunnel)"
match bikegraph.bl_input1 bikegraph.bl_strassen1 bikegraph.bl_iv1 durchgang1

echo "== Durchgang 2: separate Radwege mit < 50 % Faltung (2b zweirichtig auf Straßen in beide Richtungen, 2e einrichtig auf umgedrehten Einbahnen)"
sql <<'SQL'
DROP TABLE IF EXISTS bikegraph.bl_input2, bikegraph.bl_input2b, bikegraph.bl_input2e;
CREATE TEMP TABLE g1 AS SELECT input_id, sum(to_m - from_m) AS m FROM bikegraph.bl_iv1 WHERE mirrored = 0 GROUP BY 1;
CREATE INDEX ON g1 (input_id);
ANALYZE g1;
CREATE TABLE bikegraph.bl_input2 AS
SELECT i.* FROM bikegraph.bl_input1 i LEFT JOIN g1 ON g1.input_id = i.id
WHERE i.art IN ('separat', 'seitenobjekt_separat') AND coalesce(g1.m, 0) < 0.5 * i.cost;
ALTER TABLE bikegraph.bl_input2 ADD PRIMARY KEY (id);
CREATE TABLE bikegraph.bl_input2b AS SELECT * FROM bikegraph.bl_input2 WHERE reverse_cost >= 0;
CREATE TABLE bikegraph.bl_input2e AS SELECT * FROM bikegraph.bl_input2 WHERE reverse_cost < 0;
ALTER TABLE bikegraph.bl_input2b ADD PRIMARY KEY (id);
ALTER TABLE bikegraph.bl_input2e ADD PRIMARY KEY (id);
SELECT 'zweirichtig (2b)' AS teil, count(*) AS wege, round((sum(cost) / 1000)::numeric) AS km FROM bikegraph.bl_input2b
UNION ALL SELECT 'einrichtig (2e)', count(*), round((sum(cost) / 1000)::numeric) FROM bikegraph.bl_input2e;
SQL
match bikegraph.bl_input2b bikegraph.bl_strassen_beide bikegraph.bl_iv2b durchgang2b
match bikegraph.bl_input2e bikegraph.bl_strassen2 bikegraph.bl_iv2e durchgang2e
sql <<'SQL'
DROP TABLE IF EXISTS bikegraph.bl_iv2, bikegraph.bl_iv2_traces, bikegraph.bl_iv2_stubs;
CREATE TABLE bikegraph.bl_iv2 AS
SELECT '2b'::text AS variante, * FROM bikegraph.bl_iv2b UNION ALL SELECT '2e', * FROM bikegraph.bl_iv2e;
CREATE TABLE bikegraph.bl_iv2_traces AS
SELECT '2b'::text AS variante, * FROM bikegraph.bl_iv2b_traces UNION ALL SELECT '2e', * FROM bikegraph.bl_iv2e_traces;
CREATE TABLE bikegraph.bl_iv2_stubs AS
SELECT '2b'::text AS variante, * FROM bikegraph.bl_iv2b_stubs UNION ALL SELECT '2e', * FROM bikegraph.bl_iv2e_stubs;
CREATE INDEX ON bikegraph.bl_iv2 (input_id);
SQL

echo "== Ergebnis und Export"
sql -f "$HERE/sql/101_radweg_ergebnis.sql"
