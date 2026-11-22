#!/bin/bash
set -euo pipefail

# REN+ network pipeline in one command (docs/network-pipeline.md):
#   1. ren-network/merge_networks.py         step 1: raw network, node proposals
#   2. netzanpassungen/match_cycle_routes.py step 2: Radfernwege assigned automatically
#   3. netzanpassungen/write_app_input.py    input file of the Netzanpassungen app
#   4. netzanpassungen/apply_app_result.py   step 3: app entries from the KV database (read-only),
#                                            ren_netz.gpkg, ren_netz_korrigiert.gpkg (with Kartierung),
#                                            netzanpassungen/output/virtuelle_knoten.gpkg
# The outputs for TILDA and the Mapper (mask, Zuteilung, Befahrungsbedarf, MapRoulette tracks) are not part
# of it: they run only by hand with ./run_mapper_outputs.sh, after this script.
# Stops at the first error.
#
# Usage (repo root):
#   ./run_pipeline.sh                       # steps 1 to 3, app entries of area berlin from the KV database
#   ./run_pipeline.sh --gebiet neukoelln    # another area of the app
#   ./run_pipeline.sh --export <file>.json  # app export „Alle Einträge“ instead of the KV database
#
# Needs .env with INPUTS_DRIVE_FOLDER_URL (input data) and VITE_KV_BASE_URL, VITE_KV_PROJECT,
# VITE_KV_API_KEY (app entries), see .env.example. Uploading to TILDA stays a separate step
# (bearbeitungsstand/update.sh, processing/copy_to_tilda_static.sh).

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="${PYTHON:-$REPO_DIR/.venv/bin/python}"
GEBIET="berlin"
EXPORT=""

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
            # Earlier option; the TILDA outputs are now ./run_mapper_outputs.sh and never part of this script.
            shift
            ;;
        -h|--help)
            sed -n '4,21p' "$0"
            exit 0
            ;;
        *)
            echo "Unknown argument: $1 (allowed: --gebiet <area>, --export <file>)" >&2
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

echo ""
echo "Done. Outputs for TILDA and the Mapper only by hand: ./run_mapper_outputs.sh"
