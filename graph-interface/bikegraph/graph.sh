#!/bin/bash
# graph.sh – Radnetz-Graph: Eingang (TILDA-Objekte mit übersetzten Attributen) und Topologie (README.md).
#
#   MATCHING_PG="host=… port=… dbname=… user=…" PGPASSWORD=… ./graph-interface/bikegraph/graph.sh
#
# Voraussetzung in derselben Datenbank: tilda-geo public.routing, public.roads, public.bikelanes, public."roadsPathClasses".
# Danach: radweg_faltung.sh, datensatz_c.sh.
#
# Umgebungsvariablen (optional):
#   PBF         OSM-Auszug für die Knotenlisten (Standard ~/Documents/osm-data/berlin-latest.osm.pbf); muss zum
#               Datenstand der TILDA-Tabellen passen. SKIP_OSM=true behält die Knotenlisten aus dem letzten Lauf.
#   SKIP_INPUT  true: Eingang (bikegraph.input_edges) aus dem letzten Lauf behalten
#   JOBS        parallele Sitzungen der Eingangsübersetzung (Standard 8)
#   DIAG        true: zusätzliche Prüfung (tote Enden separater Wege, sql/25_dead_ends.sql)
#
# Schritte:
#   0. Eingang    sql/04, sql/05          je TILDA-Objekt (Weg oder Seitenobjekt) eine Zeile mit übersetzten Attributen
#                                         -> bikegraph.input_edges
#   1. Topologie  osm_nodes.py, sql/20    ein Graph aller highway-Wege aus den OSM-Knotenlisten; Netz und Richtungen aus
#                                         public.routing -> bikegraph.edges, tilda, side_objects
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PBF="${PBF:-$HOME/Documents/osm-data/berlin-latest.osm.pbf}"
JOBS="${JOBS:-8}"

: "${MATCHING_PG:?MATCHING_PG fehlt}"
PSQL=(psql "$MATCHING_PG" -v ON_ERROR_STOP=1 -q -P pager=off)
T=$(date +%s.%N)
# tick <Schritt>: Dauer seit dem letzten tick
tick() { local n; n=$(date +%s.%N); printf "   [%5.1f s] %s\n" "$(echo "$n - $T" | bc)" "$1"; T=$n; }

if [ "${SKIP_INPUT:-false}" != true ]; then
    echo "== 0. Eingang aus den TILDA-Tabellen"
    # Übersetzung auf JOBS Sitzungen verteilt (sql/04: vorbereiten, rechnen je Teil, abschluss)
    "${PSQL[@]}" -v schritt=vorbereiten -f "$SCRIPT_DIR/sql/04_input.sql" 2>&1 | grep -v NOTICE || true
    pids=()
    for ((i = 0; i < JOBS; i++)); do
        "${PSQL[@]}" -v schritt=rechnen -v teil="$i" -v teile="$JOBS" -f "$SCRIPT_DIR/sql/04_input.sql" &
        pids+=($!)
    done
    for p in "${pids[@]}"; do wait "$p" || { echo "sql/04: ein Teil ist fehlgeschlagen" >&2; exit 1; }; done
    "${PSQL[@]}" -v schritt=abschluss -f "$SCRIPT_DIR/sql/04_input.sql" 2>&1 | grep -v NOTICE
    "${PSQL[@]}" -f "$SCRIPT_DIR/sql/05_input.sql" 2>&1 | grep -v NOTICE
    tick "0 Eingang"
fi
if [ "${SKIP_OSM:-false}" != true ]; then
    echo "== 1. Topologie: Knotenlisten aus $PBF"
    python3 "$SCRIPT_DIR/osm_nodes.py" "$PBF" | "${PSQL[@]}" 2>&1 | grep -v NOTICE || true
    tick "1 Knotenlisten"
fi
echo "== 1. Topologie: Gesamtgraph"
"${PSQL[@]}" -f "$SCRIPT_DIR/sql/20_topology.sql" 2>&1 | grep -v NOTICE
tick "20 Topologie"
if [ "${DIAG:-false}" = true ]; then
    "${PSQL[@]}" -f "$SCRIPT_DIR/sql/25_dead_ends.sql"
    tick "25 tote Enden (Prüfung)"
fi
