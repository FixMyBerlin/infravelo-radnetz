#!/bin/bash
# Routing-Matcher (QA): das RVN als gewichtete Wege durch den Routing-Graphen (graph.sql). Teil 1 Vorbereitung (Abschnitte,
# Routen, Korridore), Teil 2 Wegsuche in TEILE parallelen Verbindungen (je rid modulo TEILE) mit Kaskade über Zusatzkanten
# und Brücken, Teil 2s Steiner-Wald je Kreuzung (MILP), Teil 3 Auswertung (ganze Routen auf das RVN, Abstimmung je Stelle),
# Teil 4 Kandidaten, Teil 5 Versatz der Radstreifen (nur Geometrie). Schema über -v schema=... (Standard routing_abschnitte).
# Aufruf: abschnitte.sh [psql-Optionen wie -v radius_m=0 -v schema=routing_abschnitte_test]
# Umgebung: MATCHING_PG (Verbindung, z. B. "host=127.0.0.1 port=5433 dbname=postgres user=postgres"), TEILE (Standard 4),
#           ZWEITLAUF (1 = letzte Option über Zusatzkanten in Teil 2: ganze Route, Teilrouten, Brücken; Standard 1),
#           STEINER (1 = Teil 2s, Standard 1), KANDIDATEN (1 = Teil 4, Standard 1), VERSATZ (Faktor des Versatzes in Teil 5,
#           0 = ohne, Standard 0)
# Teil 2 als Kette (abschnitte_2_kette.sql): -v kette=true, Fenster -v kette_m=300 (Standard aus).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
TEILE="${TEILE:-4}"
if [ "${ZWEITLAUF:-1}" = 1 ]; then ZWEIT=true; else ZWEIT=false; fi
P=(psql "${MATCHING_PG:?MATCHING_PG fehlt}" -v ON_ERROR_STOP=1 -q -P pager=off)
"${P[@]}" "$@" -f "$HERE/abschnitte_1_vorbereitung.sql"
pids=()
for t in $(seq 0 $((TEILE - 1))); do
    "${P[@]}" "$@" -v teil="$t" -v teile="$TEILE" -v zweitlauf="$ZWEIT" -f "$HERE/abschnitte_2_routing.sql" > /dev/null &
    pids+=($!)
done
for p in "${pids[@]}"; do wait "$p"; done
# Teil 2s (STEINER=1): Wege je Kreuzung gemeinsam als Steiner-Wald (MILP), ersetzt die Wege aus Teil 2 der durchgehenden
# Routen; Python mit scipy und psycopg2 aus STEINER_PY (Standard python3), lambda aus STEINER_LAMBDA (Standard 0.3).
# Schema wie für psql über STEINER_SCHEMA (Standard routing_abschnitte). Die Vereinigung ist über alle Kreuzungen gemeinsam
# (Kanten anderer Routen gelten als bezahlt); STEINER_RUNDEN Runden (Standard 3, Ende früher, wenn sich nichts ändert);
# STEINER_ALLEIN=1: jede Kreuzung für sich (eine Runde, ohne bezahlte Kanten); STEINER_NACHBAR=1: Enden der Routen am Netz
# der Nachbarkreuzungen (--nachbar, Kreuzungen gefärbt und Farbe für Farbe gelöst; Standard aus).
if [ "${STEINER:-1}" = 1 ]; then
    SS="\"${STEINER_SCHEMA:-routing_abschnitte}\""
    "${P[@]}" -c "DROP TABLE IF EXISTS $SS.steiner; CREATE TABLE $SS.steiner (b bigint, routen int, kanten int, boegen int,
        status text, sekunden float8, ziel float8, ziel_teil2 float8, vereinigung_m float8, vereinigung_teil2_m float8, geaendert int,
        runde int, bezahlt int);
        CREATE INDEX IF NOT EXISTS pfad_rid_seq ON $SS.pfad (rid, seq); CREATE INDEX IF NOT EXISTS pfad_edge ON $SS.pfad (edge);
        CREATE INDEX IF NOT EXISTS pfad_rid_node ON $SS.pfad (rid, node)"
    ALLEIN=(); RUNDEN="${STEINER_RUNDEN:-3}"; NACHBAR=(); FARBEN=1
    if [ "${STEINER_ALLEIN:-0}" = 1 ]; then ALLEIN=(--allein); RUNDEN=1; fi
    if [ "${STEINER_NACHBAR:-0}" = 1 ]; then
        NACHBAR=(--nachbar)
        FARBEN=$("${STEINER_PY:-python3}" "$HERE/abschnitte_2s_steiner.py" --schema "${STEINER_SCHEMA:-routing_abschnitte}" --faerben)
    fi
    for runde in $(seq 1 "$RUNDEN"); do
      for farbe in $(seq 0 $((FARBEN - 1))); do
        FARBE=(); [ "${STEINER_NACHBAR:-0}" = 1 ] && FARBE=(--farbe "$farbe")
        pids=()
        for t in $(seq 0 $((TEILE - 1))); do
            "${STEINER_PY:-python3}" "$HERE/abschnitte_2s_steiner.py" --schema "${STEINER_SCHEMA:-routing_abschnitte}" --teil "$t" \
                --teile "$TEILE" --lambda "${STEINER_LAMBDA:-0.3}" --runde "$runde" "${ALLEIN[@]}" "${NACHBAR[@]}" "${FARBE[@]}" &
            pids+=($!)
        done
        for p in "${pids[@]}"; do wait "$p"; done
      done
        geaendert=$("${P[@]}" -At -c "SELECT coalesce(sum(geaendert), 0) FROM $SS.steiner WHERE runde = $runde")
        echo "Teil 2s Runde $runde: $geaendert Routen geändert"
        [ "$geaendert" = 0 ] && break
    done
fi
"${P[@]}" "$@" -f "$HERE/abschnitte_3_auswertung.sql"
if [ "${KANDIDATEN:-1}" = 1 ]; then
    "${P[@]}" "$@" -f "$HERE/abschnitte_4_kandidaten.sql"
fi
# Teil 5: Nachbearbeitung, Radstreifen der Wege um den TILDA-Versatz auf ihre Seite verschieben (geom_versetzt)
"${P[@]}" "$@" -v versatz_faktor="${VERSATZ:-0}" -f "$HERE/abschnitte_5_versatz.sql"
