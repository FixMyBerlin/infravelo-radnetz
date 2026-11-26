#!/bin/bash
# download_tilda.sh
#
# Lädt die TILDA-Exporte (bikelanes, roads, roadsPathClasses) aus der TILDA-API für einen Zweck:
#
#   processing        Region infravelo -> processing/data-raw-tilda/{bikelanes,roads,roadsPathClasses}.fgb,
#                     dazu der Export routing -> data/TILDA Routing Berlin.gpkg (für prepare_tilda_routing.py)
#   befahrungsbedarf  Region deutschland mit Berlin-Bounding-Box -> befahrungsbedarf/data/,
#                     dazu die Datenstände des Mapillary-Abgleichs (vizsim) und eine Kopie von
#                     ren-network/output/ren_netz.gpkg, falls vorhanden
#
# Alle Dateien werden erst in einen temporären Ordner geladen und erst nach dem letzten erfolgreichen
# Download an ihren Platz verschoben. Bricht ein Download ab, bleiben die vorhandenen Dateien unverändert.
#
# Den Datenstand jedes Exports liefert TILDA im Dateinamen der Antwort (Content-Disposition, z. B.
# infravelo_bikelanes_2026-11-03.fgb). Das Skript schreibt ihn je Zielordner nach tilda_export.json.
# Die Datenstände der einzelnen Exporte dürfen sich unterscheiden.
#
# TILDA rechnet die Daten einmal pro Nacht neu. Steht in tilda_export.json schon ein Download von heute,
# überspringt das Skript den Zweck. --neu lädt trotzdem.
#
# Der API-Key kommt aus der Umgebungsvariable ATLAS_API_KEY oder aus ATLAS_API_KEY_PRODUCTION in der
# .env des tilda-geo Repos (TILDA_GEO_REPO, Standard: Schwesterordner ../tilda-geo).
#
# Verwendung (von überall):
#   data/download_tilda.sh processing
#   data/download_tilda.sh befahrungsbedarf
#   data/download_tilda.sh processing befahrungsbedarf   # beide nacheinander
#   data/download_tilda.sh --neu processing              # auch wenn heute schon geladen

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TILDA_GEO_REPO="${TILDA_GEO_REPO:-$REPO_DIR/../tilda-geo}"
API="https://tilda-geo.de/api/export"
TABLES=(bikelanes roads roadsPathClasses)

usage() {
    sed -n '4,29p' "$0" | sed 's/^# \{0,1\}//'
}

FORCE=false
TARGETS=()
for arg in "$@"; do
    case "$arg" in
        processing|befahrungsbedarf) TARGETS+=("$arg") ;;
        --neu) FORCE=true ;;
        -h|--help) usage; exit 0 ;;
        *) echo "❌ Unbekanntes Argument: $arg (erlaubt: processing, befahrungsbedarf, --neu)" >&2; exit 1 ;;
    esac
done
if [[ ${#TARGETS[@]} -eq 0 ]]; then
    usage
    exit 1
fi

# true, wenn <ordner>/tilda_export.json einen Download von heute verzeichnet (dann nichts laden)
loaded_today() {
    local json="$1/tilda_export.json"
    [[ "$FORCE" == false && -f "$json" ]] && grep -q "\"geladen\": \"$(date +%Y-%m-%d)T" "$json"
}

if [[ -z "${ATLAS_API_KEY:-}" && -f "$TILDA_GEO_REPO/.env" ]]; then
    ATLAS_API_KEY=$(grep '^ATLAS_API_KEY_PRODUCTION=' "$TILDA_GEO_REPO/.env" | cut -d= -f2- | tr -d '"' || true)
fi
if [[ -z "${ATLAS_API_KEY:-}" ]]; then
    echo "❌ Kein API-Key: ATLAS_API_KEY setzen oder TILDA_GEO_REPO auf das tilda-geo Repo zeigen lassen." >&2
    exit 1
fi

TMP_DIR=""
cleanup() { if [[ -n "$TMP_DIR" ]]; then rm -rf "$TMP_DIR"; fi; }
trap cleanup EXIT

# Lädt einen Export nach $TMP_DIR/<name> und hängt "<tabelle>": "<Dateiname mit Datenstand>" an EXPORT_JSON an.
# download_export <tabelle> <url> <name>
EXPORT_JSON=""
download_export() {
    local table=$1 url=$2 name=$3 filename
    echo "⬇️  TILDA $table"
    curl -fsSL --retry 3 -D "$TMP_DIR/$name.headers" -o "$TMP_DIR/$name" "$url"
    filename=$(grep -i '^content-disposition' "$TMP_DIR/$name.headers" | sed -E 's/.*filename="?([^";]+)"?.*/\1/' | tr -d '\r' || true)
    rm -f "$TMP_DIR/$name.headers"
    echo "    Datenstand: ${filename:-unbekannt}"
    EXPORT_JSON="$EXPORT_JSON\"$table\": \"${filename:-unbekannt}\", "
}

write_export_json() {
    echo "{${EXPORT_JSON}\"geladen\": \"$(date +%Y-%m-%dT%H:%M:%S)\"}" > "$TMP_DIR/tilda_export.json"
}

download_processing() {
    local raw_dir="$REPO_DIR/processing/data-raw-tilda"
    local routing_file="$REPO_DIR/data/TILDA Routing Berlin.gpkg"
    echo "=== processing (Region infravelo)"
    if loaded_today "$raw_dir"; then
        echo "⏭️  Heute schon geladen, übersprungen (--neu lädt trotzdem): $(cat "$raw_dir/tilda_export.json")"
        return
    fi
    TMP_DIR="$(mktemp -d "$raw_dir/.download.XXXXXX")"
    EXPORT_JSON=""
    for table in "${TABLES[@]}"; do
        download_export "$table" "$API/infravelo/$table?format=fgb&apiKey=$ATLAS_API_KEY" "$table.fgb"
    done
    download_export routing "$API/infravelo/routing?format=gpkg&apiKey=$ATLAS_API_KEY" routing.gpkg
    write_export_json

    for table in "${TABLES[@]}"; do
        mv -f "$TMP_DIR/$table.fgb" "$raw_dir/$table.fgb"
    done
    mv -f "$TMP_DIR/routing.gpkg" "$routing_file"
    mv -f "$TMP_DIR/tilda_export.json" "$raw_dir/tilda_export.json"
    rm -rf "$TMP_DIR"; TMP_DIR=""
    echo "✅ $raw_dir, $routing_file (Datenstände: $raw_dir/tilda_export.json)"
}

download_befahrungsbedarf() {
    local data_dir="$REPO_DIR/befahrungsbedarf/data"
    local bbox="minlon=13.08&minlat=52.33&maxlon=13.77&maxlat=52.68"
    local network="$REPO_DIR/ren-network/output/ren_netz.gpkg"
    echo "=== befahrungsbedarf (Region deutschland, Berlin-Bounding-Box)"
    if loaded_today "$data_dir"; then
        echo "⏭️  Heute schon geladen, übersprungen (--neu lädt trotzdem): $(cat "$data_dir/tilda_export.json")"
        return
    fi
    mkdir -p "$data_dir"
    TMP_DIR="$(mktemp -d "$data_dir/.download.XXXXXX")"
    EXPORT_JSON=""
    for table in "${TABLES[@]}"; do
        download_export "$table" "$API/deutschland/$table?$bbox&format=fgb&apiKey=$ATLAS_API_KEY" "$table.fgb"
    done
    write_export_json

    echo "⬇️  Datenstände Mapillary-Abgleich"
    curl -fsSL --retry 3 -o "$TMP_DIR/ml_metadata.json" "https://data.vizsim.de/mapillary_coverage/ml_metadata.json"
    curl -fsSL --retry 3 -o "$TMP_DIR/osm_metadata.json" "https://data.vizsim.de/mapillary_coverage/osm_metadata.json"

    for file in "${TABLES[@]/%/.fgb}" tilda_export.json ml_metadata.json osm_metadata.json; do
        mv -f "$TMP_DIR/$file" "$data_dir/$file"
    done
    rm -rf "$TMP_DIR"; TMP_DIR=""

    if [[ -f "$network" ]]; then
        cp "$network" "$data_dir/"
        echo "📋 Netz aus ren-network/output/ kopiert"
    elif [[ ! -f "$data_dir/ren_netz.gpkg" ]]; then
        echo "⚠️  $data_dir/ren_netz.gpkg fehlt (siehe ren-network/README.md)" >&2
    fi
    echo "✅ $data_dir"
}

for target in "${TARGETS[@]}"; do
    "download_$target"
done
