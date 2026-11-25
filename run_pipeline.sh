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
# Stops at the first error. In a terminal the bottom line shows the running step with a spinner and its time;
# with the output redirected (file, pipe) the script prints plain text only.
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
            sed -n '4,22p' "$0"
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

# Status line: the terminal scrolls only above the bottom line (scroll region), a background loop redraws
# that line every 0.1 s. The step itself runs in the foreground, so Ctrl+C reaches it as before.
STEPS_TOTAL=5
STEP_NO=0
SPINNER_PID=""
STATUS_UI=0
if [[ -t 1 && "${TERM:-dumb}" != "dumb" ]] && stty size </dev/tty >/dev/null 2>&1; then
    STATUS_UI=1
fi

now() { date +%s; }

duration() {
    local seconds=$1
    printf '%d:%02d' $((seconds / 60)) $((seconds % 60))
}

term_size() {
    stty size </dev/tty 2>/dev/null || echo "24 80"
}

spinner_loop() {
    local label=$1 start=$2 frames=(⠋ ⠙ ⠹ ⠸ ⠼ ⠴ ⠦ ⠧ ⠇ ⠏) i=0 rows cols last_rows=0 text
    trap 'exit 0' TERM
    while :; do
        read -r rows cols < <(term_size)
        if (( rows != last_rows )); then
            printf '\0337\033[1;%dr\0338' $((rows - 1))
            last_rows=$rows
        fi
        text=" ${frames[i % ${#frames[@]}]} $(duration $(($(now) - start)))  [$STEP_NO/$STEPS_TOTAL] $label"
        printf '\0337\033[%d;1H\033[2K%s\0338' "$rows" "${text:0:cols-1}"
        i=$((i + 1))
        sleep 0.1
    done
}

stop_spinner() {
    if [[ -n "$SPINNER_PID" ]]; then
        kill "$SPINNER_PID" 2>/dev/null || true
        wait "$SPINNER_PID" 2>/dev/null || true
        SPINNER_PID=""
    fi
}

status_setup() {
    (( STATUS_UI )) || return 0
    local rows cols
    read -r rows cols < <(term_size)
    # Free the bottom line, keep the cursor inside the scroll region
    printf '\n\033[1A\0337\033[1;%dr\0338' $((rows - 1))
}

status_cleanup() {
    stop_spinner
    (( STATUS_UI )) || return 0
    local rows cols
    read -r rows cols < <(term_size)
    printf '\0337\033[r\033[%d;1H\033[2K\0338' "$rows"
}

trap status_cleanup EXIT
status_setup
PIPELINE_START=$(now)

run() {
    local label=$1 start rc=0
    shift
    STEP_NO=$((STEP_NO + 1))
    echo ""
    echo "=== $label"
    start=$(now)
    if (( STATUS_UI )); then
        spinner_loop "$label" "$start" &
        SPINNER_PID=$!
    fi
    "$@" || rc=$?
    stop_spinner
    if (( rc != 0 )); then
        echo "✗ $label: failed with exit code $rc after $(duration $(($(now) - start)))" >&2
        exit "$rc"
    fi
    echo "✓ $label ($(duration $(($(now) - start))))"
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
echo "Done in $(duration $(($(now) - PIPELINE_START))). Outputs for TILDA and the Mapper only by hand: ./run_mapper_outputs.sh"
