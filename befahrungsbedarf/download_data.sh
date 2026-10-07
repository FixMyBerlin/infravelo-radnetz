#!/bin/bash
# download_data.sh
#
# Lädt die Eingangsdaten für den Befahrungsbedarf nach befahrungsbedarf/data/.
# Die Daten in ./data und ./data-raw-tilda des Hauptprojekts bleiben unberührt.
#
# - TILDA-Export (bikelanes, roads, roadsPathClasses) für die Berlin-Bounding-Box
# - Datenstände des Mapillary-Abgleichs (vizsim)
#
# Der API-Key kommt aus der Umgebungsvariable ATLAS_API_KEY oder aus
# ATLAS_API_KEY_PRODUCTION in der .env des tilda-geo Repos (TILDA_GEO_REPO).
#
# Das Netz (ren_netz_gesamt.gpkg) wird nicht geladen, sondern aus
# ren-network/output/ kopiert, falls es dort liegt.
#
# Verwendung: ./befahrungsbedarf/download_data.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DATA_DIR="$SCRIPT_DIR/data"
TILDA_GEO_REPO="${TILDA_GEO_REPO:-$SCRIPT_DIR/../../tilda-geo}"
BBOX="minlon=13.08&minlat=52.33&maxlon=13.77&maxlat=52.68"

mkdir -p "$DATA_DIR"

if [ -z "$ATLAS_API_KEY" ]; then
    ATLAS_API_KEY=$(grep '^ATLAS_API_KEY_PRODUCTION=' "$TILDA_GEO_REPO/.env" | cut -d= -f2- | tr -d '"')
fi
if [ -z "$ATLAS_API_KEY" ]; then
    echo "❌ Kein API-Key: ATLAS_API_KEY setzen oder TILDA_GEO_REPO auf das tilda-geo Repo zeigen lassen." >&2
    exit 1
fi

EXPORT_FILES=""
for table in bikelanes roads roadsPathClasses; do
    echo "⬇️  TILDA $table"
    curl -fsSL --retry 3 -D "$DATA_DIR/$table.headers" -o "$DATA_DIR/$table.fgb" \
        "https://tilda-geo.de/api/export/deutschland/$table?$BBOX&format=fgb&apiKey=$ATLAS_API_KEY"
    # Der Dateiname der Antwort enthält den Datenstand, z.B. bikelanes_2026-10-05.fgb
    filename=$(grep -i '^content-disposition' "$DATA_DIR/$table.headers" | sed -E 's/.*filename="([^"]+)".*/\1/' | tr -d '\r')
    EXPORT_FILES="$EXPORT_FILES\"$table\": \"$filename\", "
    rm -f "$DATA_DIR/$table.headers"
done
echo "{${EXPORT_FILES%, }, \"geladen\": \"$(date +%Y-%m-%dT%H:%M:%S)\"}" > "$DATA_DIR/tilda_export.json"

echo "⬇️  Datenstände Mapillary-Abgleich"
curl -fsSL --retry 3 -o "$DATA_DIR/ml_metadata.json" "https://data.vizsim.de/mapillary_coverage/ml_metadata.json"
curl -fsSL --retry 3 -o "$DATA_DIR/osm_metadata.json" "https://data.vizsim.de/mapillary_coverage/osm_metadata.json"

NETWORK="$SCRIPT_DIR/../ren-network/output/ren_netz_gesamt.gpkg"
if [ -f "$NETWORK" ]; then
    cp "$NETWORK" "$DATA_DIR/"
    echo "📋 Netz aus ren-network/output/ kopiert"
elif [ ! -f "$DATA_DIR/ren_netz_gesamt.gpkg" ]; then
    echo "⚠️  $DATA_DIR/ren_netz_gesamt.gpkg fehlt (siehe ren-network/README.md)" >&2
fi

echo "✅ Daten liegen in $DATA_DIR"
