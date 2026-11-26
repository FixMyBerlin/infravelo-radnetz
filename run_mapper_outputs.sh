#!/bin/bash
set -euo pipefail

# Outputs for TILDA and the Mapper, built on the result of ./run_pipeline.sh (docs/network-pipeline.md).
# Runs only by hand, on request: run_pipeline.sh never calls it.
#   1. ren-network/create_mask.py                                  mask of the network
#   2. mapping-zuteilung/update_assignment.py                     Zuteilung: areas and edges per Mapper
#   3. befahrungsbedarf/build.py                                   Befahrungsbedarf
#   4. maproulette-centerline-tracks/extract_centerline_tracks.py MapRoulette tracks
# Stops at the first error.
#
# Usage (repo root):
#   ./run_mapper_outputs.sh
#
# Needs the output of step 3 (ren-network/output/ren_netz.gpkg, ren_netz_kartierung.gpkg) and the inputs
# of the single scripts: befahrungsbedarf/data/ (data/download_tilda.sh befahrungsbedarf) and
# maproulette-centerline-tracks/data/ (symlinks, see the READMEs).
# Writes only into this repo. Nothing goes to tilda-static-data or TILDA; that stays a separate step
# (bearbeitungsstand/update.sh, processing/copy_to_tilda_static.sh).

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="${PYTHON:-$REPO_DIR/.venv/bin/python}"

case "${1:-}" in
    "") ;;
    -h|--help)
        sed -n '4,19p' "$0"
        exit 0
        ;;
    *)
        echo "Unknown argument: $1 (this script takes none)" >&2
        exit 1
        ;;
esac

if [[ ! -x "$PYTHON" ]]; then
    echo "Python not found: $PYTHON (create .venv, see README.md)" >&2
    exit 1
fi

cd "$REPO_DIR"

for input in ren-network/output/ren_netz.gpkg ren-network/output/ren_netz_kartierung.gpkg; do
    if [[ ! -f "$input" ]]; then
        echo "Missing $input: run ./run_pipeline.sh first." >&2
        exit 1
    fi
done
echo "Network of step 3 from $(date -r ren-network/output/ren_netz.gpkg '+%Y-%m-%d %H:%M')."

run() {
    echo ""
    echo "=== $1"
    shift
    "$@"
}

run "Mask" "$PYTHON" ren-network/create_mask.py
run "Zuteilung" "$PYTHON" mapping-zuteilung/update_assignment.py
run "Befahrungsbedarf" "$PYTHON" befahrungsbedarf/build.py
run "MapRoulette tracks" "$PYTHON" maproulette-centerline-tracks/extract_centerline_tracks.py
echo ""
echo "Done. If mapping-zuteilung/assignment.csv changed (new edges), commit it."
