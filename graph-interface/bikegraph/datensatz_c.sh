#!/usr/bin/env bash
# Datensatz C aus Straßen (mit gefalteten Radwegen als Kandidaten) und Wegen, gematcht auf das RVN (Variante A).
#   1  Eingang (sql/104): trace_group strassen (Faltungsnetz bl_strassen1) und wege (TILDA-Wege, ungefaltete
#      Radwege, ungefaltete Reste ab REST_MIN_M); alles aus dem TILDA-Routing-Export
#   2  Matching auf matching.reference_edges (map-matching run --pg, Einstellungen wie die Baseline; Traces folgen
#      zusätzlich Knicken ohne Abzweigung über den Abknickwinkel hinaus, KNICK_OHNE_ABZWEIG)
#   3  Intervalle (sql/105): Wege mit ihrem eigenen Objekt, Straßen mit allen Kandidaten ihrer Kante und Richtung
#   4  assemble, Konvertierung, Aggregation -> <OUT_DIR>/post/aggregated.gpkg
#   5  Vergleich mit der Baseline (compare_c.sh)
# Voraussetzung: radweg_faltung.sh gelaufen; bikegraph.input_edges (graph.sh, Schritt 0); gebauter Matcher; Python-Umgebung
# mit geopandas (PY). Umgebung: MATCHING_PG, PGPASSWORD; REST_MIN_M (Standard 10), OUT_DIR (relativ zu PROCESSING,
# Standard output/mm-datensatz-c-a), BASELINE (Standard processing/output/post-baseline/aggregated.gpkg des
# Hauptcheckouts), JOBS (Standard 8), MAX_TURN_DEG (größte Richtungsänderung beim Verketten der Traces an
# Abzweigungen, Standard 45 wie die Baseline), KNICK_OHNE_ABZWEIG (Standard true: an Knoten ohne Abzweigung setzt die
# Trace auch über MAX_TURN_DEG hinaus fort; false wie die Baseline)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PROCESSING="${PROCESSING:-$(cd "$HERE/../.." && pwd)/processing}"
MATCHER="${MATCHER:-$PROCESSING/map-matching/target/release/map-matching}"
PY="${PY:-$HOME/Documents/infravelo-radnetz/.venv/bin/python}"
REST_MIN_M="${REST_MIN_M:-10}"
MAX_TURN_DEG="${MAX_TURN_DEG:-45}"
KNICK_OHNE_ABZWEIG="${KNICK_OHNE_ABZWEIG:-true}"
OUT_DIR="${OUT_DIR:-output/mm-datensatz-c-a}"
BASELINE="${BASELINE:-$HOME/Documents/infravelo-radnetz/processing/output/post-baseline/aggregated.gpkg}"
JOBS="${JOBS:-8}"
PSQL=(psql "${MATCHING_PG:?MATCHING_PG fehlt}" -v ON_ERROR_STOP=1 -q -P pager=off)
LOG="$PROCESSING/$OUT_DIR/logs"
mkdir -p "$LOG" "$PROCESSING/$OUT_DIR/post"
sql() { "${PSQL[@]}" "$@" 2>&1 | { grep -v NOTICE || true; }; }

echo "== 1. Eingang (Reste ab $REST_MIN_M m)"
sql -v rest_min_m="$REST_MIN_M" -f "$HERE/sql/104_datensatz_c_eingang.sql"

echo "== 2. Matching auf das RVN"
(cd "$PROCESSING" && "$MATCHER" --pg run --set paths.root="\"$PROCESSING\"" \
    --set postgres.input_edges=bikegraph.dc_input --set postgres.reference_edges=matching.reference_edges \
    --set postgres.intervals=bikegraph.dc_iv_raw --set postgres.intervals_only=true --set network.topology_report=false \
    --set trace.max_turn_deg="$MAX_TURN_DEG" --set trace.knick_ohne_abzweig="$KNICK_OHNE_ABZWEIG" \
    --set 'paths.tilda=[{data_source="strassen", path="-"}, {data_source="wege", path="-"}]' \
    --set paths.output_dir="\"$OUT_DIR/matching\"" > "$LOG/matching.log" 2>&1)
sed 's/\x1b\[[0-9;]*m//g' "$LOG/matching.log" | grep -E "Topologie-Traces|Traces:" | sed 's/^.*INFO /   /'

echo "== 3. Intervalle je TILDA-Objekt"
sql -f "$HERE/sql/105_datensatz_c_intervalle.sql"

echo "== 4. assemble, Konvertierung, Aggregation"
# Konfiguration für assemble: Standard plus Vorrang konkreter Führungsformen vor "[TODO] Klärung notwendig"
# (sonst gleichrangig im Tier RVA); default.toml und die Baseline bleiben unverändert
CFG="$PROCESSING/$OUT_DIR/assemble.toml"
cat "$PROCESSING/map-matching/config/default.toml" - > "$CFG" <<'TOML'

[[rules.prefer]]
name = "Konkrete Führungsform vor Klärung notwendig"
winner = { fuehr = [
  "Radfahrstreifen", "Radfahrstreifen mit Linienverkehr frei (Z237 mit Z1026-32)",
  "Bussonderfahrstreifen mit Radverkehr frei (Z245 mit Z1022‐10)", "Geschützter Radfahrstreifen", "Schutzstreifen",
  "Fahrradstraße /-zone (Z 244)", "Radweg", "Gemeinsamer Geh- und Radweg mit Z240",
  "Gehweg mit Zusatzzeichen \"Radverkehr frei\" (Z239 mit Z1022-10)", "Fußgängerzone \"Radverkehr frei\" (Z242 mit Z1022-10)",
] }
loser = { fuehr = ["[TODO] Klärung notwendig"] }
TOML
(cd "$PROCESSING" && "$MATCHER" --config "$CFG" --pg assemble --set paths.root="\"$PROCESSING\"" --set postgres.input_edges=bikegraph.input_edges \
    --set postgres.reference_edges=matching.reference_edges --set postgres.intervals=bikegraph.intervals_dc \
    --set paths.output_dir="$OUT_DIR" > "$LOG/assemble.log" 2>&1)
sed 's/\x1b\[[0-9;]*m//g' "$LOG/assemble.log" | grep -E "Intervalle|Fertig" | sed 's/^.*INFO /   /'
(cd "$PROCESSING" && "$PY" start_bikelane_conversion.py --netz rvn --input "$OUT_DIR/network_enriched_hmm.fgb" \
    --output "$OUT_DIR/post/converted.fgb" > "$LOG/conv.log" 2>&1)
(cd "$PROCESSING" && "$PY" "$HERE/aggregate_parallel.py" --input "$OUT_DIR/post/converted.fgb" \
    --output "$OUT_DIR/post/aggregated.gpkg" --jobs "$JOBS" > "$LOG/agg.log" 2>&1)
echo "   -> $PROCESSING/$OUT_DIR/post/aggregated.gpkg"

echo "== 5. Vergleich mit der Baseline"
"$HERE/compare_c.sh" "$BASELINE" "$PROCESSING/$OUT_DIR/post/aggregated.gpkg" "$PROCESSING/$OUT_DIR/vergleich_baseline.csv"

echo "== 6. Datensatz B und C (Baseline, neu, Abweichungen) für Martin"
# Datensatz B wie konvertiert, ohne die Mapillary- und Quellfelder
ogr2ogr -f PostgreSQL "PG:$MATCHING_PG" "$PROCESSING/$OUT_DIR/post/converted.fgb" -overwrite -lco SCHEMA=datensatz_c -lco OVERWRITE=YES \
    -lco GEOMETRY_NAME=geom -lco FID=id -nln new_b -nlt LINESTRING -t_srs EPSG:25833 \
    -sql "SELECT element_nr, ri, strassenname, fuehr, pflicht, breite, ofm, farbe, protek, trennstreifen, nutz_beschr, verkehrsri,
          tilda_id, tilda_name, tilda_category, tilda_ids, data_source, hmm_regel, hmm_konfidenz FROM converted"
sql -f "$HERE/sql/106_datensatz_c_martin.sql"
