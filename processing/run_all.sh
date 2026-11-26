#!/bin/bash
# run_all.sh
#
# Komplette Prozessierung TILDA -> REN+ mit den neusten TILDA-Daten in einem Aufruf:
#   1. ../data/download_tilda.sh processing        TILDA-Exporte und Routing-Export laden
#   2. scripts/prepare_tilda_routing.py --netz ren Routing-Netz mit den TILDA-Attributen verbinden und übersetzen
#   3. ./process_radnetz.sh --netz ren             Zielnetz vorbereiten
#   4. ./execute_processing.sh --netz ren          HMM-Map-Matching, Schutzstreifen, Aggregation
#   5. scripts/convert_to_geojson.py --netz ren    GeoJSON der Datensätze A, B, C
#   6. ./run_validation.sh --netz ren              Validierung
# Bricht beim ersten Fehler ab. Schlägt nur die Validierung fehl, liegen alle Ausgaben trotzdem vor.
# Schritt 2 entfällt, wenn seine Ausgaben neuer sind als die TILDA-Dateien und der Code der Übersetzung
# (prepare_tilda_routing.py und die genutzten helpers/), also wenn heute nichts Neues geladen wurde.
#
# Voraussetzung: ein Lauf von ../run_pipeline.sh (ren-network/output/ren_netz*.gpkg,
# netzanpassungen/output/virtuelle_knoten.gpkg). Das Kopieren nach tilda-static-data
# (./copy_to_tilda_static.sh --netz ren) bleibt ein eigener Schritt von Hand.
#
# Verwendung (von überall):
#   processing/run_all.sh                  # mit Download, außer er lief heute schon (TILDA rechnet nachts neu)
#   processing/run_all.sh --neu-laden      # Download auch, wenn heute schon geladen
#   processing/run_all.sh --ohne-download  # mit den vorhandenen Dateien in data-raw-tilda/
#   processing/run_all.sh --neu-uebersetzen  # Schritt 2 auch, wenn seine Ausgaben aktuell sind
#   processing/run_all.sh --clean-cache    # an execute_processing.sh durchgereicht

set -euo pipefail

SCRIPT="$(realpath "$0")"
cd "$(dirname "$SCRIPT")"
PYTHON="${PYTHON:-$(cd .. && pwd)/.venv/bin/python}"
DOWNLOAD=true
DOWNLOAD_ARGS=()
FORCE_TRANSLATE=false
EXECUTE_ARGS=()

while [[ $# -gt 0 ]]; do
    case $1 in
        --ohne-download) DOWNLOAD=false; shift ;;
        --neu-laden) DOWNLOAD_ARGS+=(--neu); shift ;;
        --neu-uebersetzen) FORCE_TRANSLATE=true; shift ;;
        --clean-cache) EXECUTE_ARGS+=(--clean-cache); shift ;;
        -h|--help) sed -n '4,25p' "$SCRIPT" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "❌ Unbekanntes Argument: $1 (erlaubt: --ohne-download, --neu-laden, --neu-uebersetzen, --clean-cache)" >&2; exit 1 ;;
    esac
done

if [[ ! -x "$PYTHON" ]]; then
    echo "❌ Python nicht gefunden: $PYTHON (.venv anlegen, siehe README.md)" >&2
    exit 1
fi

START=$(date +%s)
ROOT="$(cd .. && pwd)"
# Gibt die Skript-Datei eines Aufrufs (erstes Argument mit Endung .sh oder .py) relativ zum Projekt aus
script_file() {
    local arg
    for arg in "$@"; do
        if [[ "$arg" == *.sh || "$arg" == *.py ]]; then
            echo "Datei: $(realpath --relative-to="$ROOT" "$arg")"
            return
        fi
    done
}
step() {
    local label=$1 t0
    shift
    echo ""
    echo "=== $label"
    script_file "$@"
    t0=$(date +%s)
    "$@"
    echo "✓ $label ($(( ($(date +%s) - t0) / 60 )) min)"
}

if [[ "$DOWNLOAD" == true ]]; then
    step "1. TILDA-Daten laden" ../data/download_tilda.sh "${DOWNLOAD_ARGS[@]}" processing
else
    echo "=== 1. TILDA-Daten laden: übersprungen (--ohne-download)"
fi
[[ -f data-raw-tilda/tilda_export.json ]] && echo "Datenstände: $(cat data-raw-tilda/tilda_export.json)"

# Schritt 2 ist aktuell, wenn jede Ausgabe neuer ist als jede Eingabe (TILDA-Dateien und Code der Übersetzung)
TRANSLATE_INPUTS=(
    data-raw-tilda/bikelanes.fgb data-raw-tilda/roads.fgb data-raw-tilda/roadsPathClasses.fgb
    "data/TILDA Routing Berlin.gpkg" scripts/prepare_tilda_routing.py
    helpers/construction_comments.py helpers/globals.py helpers/netz.py helpers/progressbar.py
    helpers/traffic_signs.py helpers/width_parser.py
)
TRANSLATE_OUTPUTS=(output/TILDA-routing-ren/"TILDA Routing "{Bikelanes,Streets,Paths}" Translated.fgb")
translation_up_to_date() {
    local out in
    for out in "${TRANSLATE_OUTPUTS[@]}"; do
        [[ -f "$out" ]] || return 1
        for in in "${TRANSLATE_INPUTS[@]}"; do
            [[ "$in" -nt "$out" ]] && return 1
        done
    done
    return 0
}

if [[ "$FORCE_TRANSLATE" == false ]] && translation_up_to_date; then
    echo ""
    echo "=== 2. TILDA-Routing vorbereiten: übersprungen, Ausgaben in output/TILDA-routing-ren/ sind aktuell (--neu-uebersetzen erzwingt)"
else
    step "2. TILDA-Routing vorbereiten" "$PYTHON" scripts/prepare_tilda_routing.py --netz ren
fi
step "3. Zielnetz vorbereiten" ./process_radnetz.sh --netz ren
step "4. Hauptverarbeitung" ./execute_processing.sh --netz ren "${EXECUTE_ARGS[@]}"
step "5. GeoJSON-Export" "$PYTHON" scripts/convert_to_geojson.py --netz ren

echo ""
echo "=== 6. Validierung"
script_file ./run_validation.sh
if ./run_validation.sh --netz ren; then
    echo "✓ 6. Validierung"
else
    echo "❌ Validierung mit Fehlern (Ausgaben liegen trotzdem vor, Details oben)" >&2
    exit 1
fi

echo ""
echo "Fertig in $(( ($(date +%s) - START) / 60 )) min. Kopie nach tilda-static-data von Hand: ./copy_to_tilda_static.sh --netz ren"
