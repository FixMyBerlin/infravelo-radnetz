#!/bin/bash
set -euo pipefail

# REN+ network pipeline in one command (docs/network-pipeline.md):
#   1. ren-network/merge_networks.py         step 1: raw network, node proposals
#   2. netzanpassungen/match_cycle_routes.py step 2: Radfernwege assigned automatically
#   3. netzanpassungen/write_app_input.py    input file of the Netzanpassungen app
#   4. netzanpassungen/apply_app_result.py   step 3: app entries from the KV database (read-only),
#                                            ren_netz.gpkg, ren_netz_korrigiert.gpkg (with Kartierung),
#                                            netzanpassungen/output/virtuelle_knoten.gpkg
#   5. TILDA outputs: mask (ren-network/create_mask.py), Zuteilung (mapping-zuteilung/update_assignment.py),
#      Befahrungsbedarf (befahrungsbedarf/build.py), MapRoulette tracks
#      (maproulette-centerline-tracks/extract_centerline_tracks.py)
# Stops at the first error.
#
# Usage (repo root):
#   ./run_pipeline.sh                       # everything, app entries of area berlin from the KV database
#   ./run_pipeline.sh --gebiet neukoelln    # another area of the app
#   ./run_pipeline.sh --export <file>.json  # app export „Alle Einträge“ instead of the KV database
#   ./run_pipeline.sh --ohne-tilda          # only steps 1 to 3, no TILDA outputs
#
# Needs .env with INPUTS_DRIVE_FOLDER_URL (input data) and VITE_KV_BASE_URL, VITE_KV_PROJECT,
# VITE_KV_API_KEY (app entries), see .env.example. The TILDA outputs need their own inputs:
# befahrungsbedarf/data/ (befahrungsbedarf/download_data.sh) and maproulette-centerline-tracks/data/
# (symlinks, see the READMEs). Uploading to TILDA stays a separate step (bearbeitungsstand/update.sh,
# processing/copy_to_tilda_static.sh).

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="${PYTHON:-$REPO_DIR/.venv/bin/python}"
GEBIET="berlin"
EXPORT=""
TILDA=1

while [[ $# -gt 0 ]]; do
    case $1 in
        --gebiet)
            GEBIET="$2"
            shift 2
            ;;
        --export)
            EXPORT="$2"
            shift 2
            ;;
        --ohne-tilda)
            TILDA=0
            shift
            ;;
        -h|--help)
            sed -n '4,27p' "$0"
            exit 0
            ;;
        *)
            echo "Unknown argument: $1 (allowed: --gebiet <area>, --export <file>, --ohne-tilda)" >&2
            exit 1
            ;;
    esac
done

if [[ ! -x "$PYTHON" ]]; then
    echo "Python not found: $PYTHON (create .venv, see README.md)" >&2
    exit 1
fi

cd "$REPO_DIR"

run() {
    echo ""
    echo "=== $1"
    shift
    "$@"
}

run "Step 1: merge the network" "$PYTHON" ren-network/merge_networks.py
run "Step 2: assign Radfernwege" "$PYTHON" netzanpassungen/match_cycle_routes.py
run "App input" "$PYTHON" netzanpassungen/write_app_input.py
if [[ -n "$EXPORT" ]]; then
    run "Step 3: apply the app result (export $EXPORT)" "$PYTHON" netzanpassungen/apply_app_result.py --export "$EXPORT"
else
    run "Step 3: apply the app result (KV database, area $GEBIET)" "$PYTHON" netzanpassungen/apply_app_result.py --gebiet "$GEBIET"
fi
run "Check the virtual nodes" "$PYTHON" data/virtuelle_knotenpunkte.py pruefen

if [[ "$TILDA" == 1 ]]; then
    run "TILDA: mask" "$PYTHON" ren-network/create_mask.py
    run "TILDA: Zuteilung" "$PYTHON" mapping-zuteilung/update_assignment.py
    run "TILDA: Befahrungsbedarf" "$PYTHON" befahrungsbedarf/build.py
    run "TILDA: MapRoulette tracks" "$PYTHON" maproulette-centerline-tracks/extract_centerline_tracks.py
    echo ""
    echo "Done. If mapping-zuteilung/assignment.csv changed (new edges), commit it."
else
    echo ""
    echo "Done (without TILDA outputs)."
fi
