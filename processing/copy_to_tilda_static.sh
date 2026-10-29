#!/bin/bash
set -e

# Alle Pfade sind relativ zu processing/
cd "$(dirname "$0")"

# Script to copy processed GeoJSON files to tilda-static-data repository
# and update the dataUpdatedNote field in meta.ts files

# Color output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}Starting copy to tilda-static-data...${NC}"

# Default: use today's date
USE_TILDA_DATE=false

# Check for CLI parameter
for arg in "$@"; do
    if [[ "$arg" == "--use-tilda-date" ]]; then
        USE_TILDA_DATE=true
    fi
done

if [ "$USE_TILDA_DATE" = true ]; then
    # Determine the update date from the most recent data-raw-tilda file
    TILDA_DATE=$(stat -c %y data-raw-tilda/bikelanes.fgb | cut -d' ' -f1)
    ROADS_DATE=$(stat -c %y data-raw-tilda/roads.fgb | cut -d' ' -f1)
    ROADS_PATH_DATE=$(stat -c %y data-raw-tilda/roadsPathClasses.fgb | cut -d' ' -f1)

    # Find the most recent date
    LATEST_DATE=$TILDA_DATE
    if [[ "$ROADS_DATE" > "$LATEST_DATE" ]]; then
            LATEST_DATE=$ROADS_DATE
    fi
    if [[ "$ROADS_PATH_DATE" > "$LATEST_DATE" ]]; then
            LATEST_DATE=$ROADS_PATH_DATE
    fi

    # Convert from YYYY-MM-DD to DD.MM.YYYY
    UPDATE_DATE=$(date -d "$LATEST_DATE" +"%d.%m.%Y")
    echo -e "${GREEN}Update date determined from TILDA files: ${UPDATE_DATE}${NC}"
else
    # Use today's date
    UPDATE_DATE=$(date +"%d.%m.%Y")
    echo -e "${GREEN}Update date set to today: ${UPDATE_DATE}${NC}"
fi

# Define relative paths
TILDA_STATIC_BASE="../../tilda-static-data/geojson/region-infravelo"

# File mappings: source -> destination directory. The file names in tilda-static-data stay
# as they are (Datensatz B was snapping_with_overrides before the overrides step was removed).
declare -A FILE_MAP=(
    ["output/matched_tilda_ways.geojson.gz"]="$TILDA_STATIC_BASE/infravelo-datensatz-a-fortlaufend"
    ["output/snapping_converted_bikelanes.geojson.gz"]="$TILDA_STATIC_BASE/infravelo-datensatz-b-fortlaufend"
    ["output/aggregated_rvn_final.geojson.gz"]="$TILDA_STATIC_BASE/infravelo-datensatz-c-fortlaufend"
)
declare -A DEST_NAME=(
    ["output/matched_tilda_ways.geojson.gz"]="matched_tilda_ways.geojson.gz"
    ["output/snapping_converted_bikelanes.geojson.gz"]="snapping_with_overrides.geojson.gz"
    ["output/aggregated_rvn_final.geojson.gz"]="aggregated_rvn_final.geojson.gz"
)

# Check everything before copying anything
for src in "${!FILE_MAP[@]}"; do
    dest="${FILE_MAP[$src]}"
    if [ ! -f "$src" ]; then
        echo -e "${RED}ERROR: Source file not found: $src${NC}"
        exit 1
    fi
    if [ ! -d "$dest" ]; then
        echo -e "${RED}ERROR: Destination directory not found: $dest${NC}"
        exit 1
    fi
done

# Copy files
echo -e "${BLUE}Copying files...${NC}"
for src in "${!FILE_MAP[@]}"; do
    dest="${FILE_MAP[$src]}"
    filename="${DEST_NAME[$src]}"
    cp "$src" "$dest/$filename"
    echo -e "${GREEN}✓${NC} Copied $src to $dest/$filename"
done

# Update meta.ts files
echo -e "${BLUE}Updating meta.ts files...${NC}"
for dest in "${FILE_MAP[@]}"; do
    meta_file="$dest/meta.ts"
    
    if [ ! -f "$meta_file" ]; then
        echo "WARNING: meta.ts not found at $meta_file"
        continue
    fi
    
    # Update the dataUpdatedNote line using sed
    sed -i "s/dataUpdatedNote: '[^']*',/dataUpdatedNote: '${UPDATE_DATE}',/" "$meta_file"
    echo -e "${GREEN}✓${NC} Updated dataUpdatedNote in $(basename $(dirname $meta_file))/meta.ts"
done

echo -e "${GREEN}Done! All files copied and meta.ts files updated.${NC}"

# CSV für den TILDA-Pseudo-Tag infravelo_netz aus dem neuen Ergebnis (danach einchecken)
echo -e "${BLUE}Updating TILDA pseudo tag CSV...${NC}"
../.venv/bin/python ../tilda-pseudo-tags/build_csv.py --input output/aggregated_rvn_final.geojson.gz
