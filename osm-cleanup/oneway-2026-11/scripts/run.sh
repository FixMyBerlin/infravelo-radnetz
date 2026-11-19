#!/usr/bin/env bash
# Builds everything from scratch: Berlin extract with user names, rules, history, decision, osmChange, MAID file.
# Usage: scripts/run.sh   (from the project folder; needs docker, osmium, uv, OHSOME_API_KEY)
# Run it right before an upload: the .osc files carry way versions and go stale.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
DATA="$HERE/data"
OUT="$HERE/output"
mkdir -p "$DATA" "$OUT"
df -h "$DATA" | tail -1

# 1. Internal Geofabrik extract (with user names) from the tilda-geo docker volume, mounted read-only.
#    For a fresher extract, run the tilda-geo processing download first.
docker run --rm -v tilda-geo_osmfiles:/data:ro -v "$DATA":/out alpine \
  cp /data/downloads/brandenburg-latest-internal.osm.pbf /out/
osmium fileinfo -e "$DATA/brandenburg-latest-internal.osm.pbf" | grep -E '^\s+timestamp='
osmium getid -r "$DATA/brandenburg-latest-internal.osm.pbf" r62422 -o "$DATA/berlin-boundary.osm.pbf" --overwrite
osmium extract -p "$DATA/berlin-boundary.osm.pbf" "$DATA/brandenburg-latest-internal.osm.pbf" \
  -s complete_ways -o "$DATA/berlin-internal.osm.pbf" --overwrite
rm "$DATA/brandenburg-latest-internal.osm.pbf"
osmium tags-filter -R "$DATA/berlin-internal.osm.pbf" w/highway -o "$DATA/hw.osm.pbf" --overwrite
osmium cat "$DATA/hw.osm.pbf" -t way -f opl -o "$DATA/hw.opl" --overwrite

# 2. Tag rules (R1–R5, risk exclusions), 3. history via ohsome, 4. decision + files, 5. checks.
python3 -I "$HERE/scripts/rules.py" "$DATA/hw.opl" "$OUT" "$HERE/g2_bikelanes_diff_ids.txt"
rm -rf "$OUT/history"
uvx --from duckdb==1.4.1 --with pytz python -I "$HERE/scripts/history_check.py" "$OUT"
uvx --from duckdb==1.4.1 --with pytz python -I "$HERE/scripts/build_cleanup.py" "$DATA/hw.opl" "$DATA/berlin-internal.osm.pbf" "$OUT"
python3 -I "$HERE/scripts/validate_osc.py" "$DATA/hw.opl" "$OUT"/auto__*.osc
echo "MAID check: cd ~/Development/OSM/Maid && bun run tasks-check $OUT/maid__oneway-check.json"
