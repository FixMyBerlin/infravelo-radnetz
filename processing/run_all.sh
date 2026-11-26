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
#
# Voraussetzung: ein Lauf von ../run_pipeline.sh (ren-network/output/ren_netz*.gpkg,
# netzanpassungen/output/virtuelle_knoten.gpkg). Das Kopieren nach tilda-static-data
# (./copy_to_tilda_static.sh --netz ren) bleibt ein eigener Schritt von Hand.
#
# Verwendung (von überall):
#   processing/run_all.sh                  # mit Download
#   processing/run_all.sh --ohne-download  # mit den vorhandenen Dateien in data-raw-tilda/
#   processing/run_all.sh --clean-cache    # an execute_processing.sh durchgereicht

set -euo pipefail

SCRIPT="$(realpath "$0")"
cd "$(dirname "$SCRIPT")"
PYTHON="${PYTHON:-$(cd .. && pwd)/.venv/bin/python}"
DOWNLOAD=true
EXECUTE_ARGS=()

while [[ $# -gt 0 ]]; do
    case $1 in
        --ohne-download) DOWNLOAD=false; shift ;;
        --clean-cache) EXECUTE_ARGS+=(--clean-cache); shift ;;
        -h|--help) sed -n '4,21p' "$SCRIPT" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "❌ Unbekanntes Argument: $1 (erlaubt: --ohne-download, --clean-cache)" >&2; exit 1 ;;
    esac
done

if [[ ! -x "$PYTHON" ]]; then
    echo "❌ Python nicht gefunden: $PYTHON (.venv anlegen, siehe README.md)" >&2
    exit 1
fi

START=$(date +%s)
step() {
    local label=$1 t0
    shift
    echo ""
    echo "=== $label"
    t0=$(date +%s)
    "$@"
    echo "✓ $label ($(( ($(date +%s) - t0) / 60 )) min)"
}

if [[ "$DOWNLOAD" == true ]]; then
    step "1. TILDA-Daten laden" ../data/download_tilda.sh processing
else
    echo "=== 1. TILDA-Daten laden: übersprungen (--ohne-download)"
fi
[[ -f data-raw-tilda/tilda_export.json ]] && echo "Datenstände: $(cat data-raw-tilda/tilda_export.json)"

step "2. TILDA-Routing vorbereiten" "$PYTHON" scripts/prepare_tilda_routing.py --netz ren
step "3. Zielnetz vorbereiten" ./process_radnetz.sh --netz ren
step "4. Hauptverarbeitung" ./execute_processing.sh --netz ren "${EXECUTE_ARGS[@]}"
step "5. GeoJSON-Export" "$PYTHON" scripts/convert_to_geojson.py --netz ren

echo ""
echo "=== 6. Validierung"
if ./run_validation.sh --netz ren; then
    echo "✓ 6. Validierung"
else
    echo "❌ Validierung mit Fehlern (Ausgaben liegen trotzdem vor, Details oben)" >&2
    exit 1
fi

echo ""
echo "Fertig in $(( ($(date +%s) - START) / 60 )) min. Kopie nach tilda-static-data von Hand: ./copy_to_tilda_static.sh --netz ren"
