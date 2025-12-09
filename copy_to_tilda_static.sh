#!/bin/bash
set -e

# Script to copy processed GeoJSON files to tilda-static-data repository
# and update the updatedAt field in meta.ts files

# Color output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
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
TILDA_STATIC_BASE="../tilda-static-data/geojson/region-berlin"

# File mappings: source -> destination
declare -A FILE_MAP=(
    ["output/snapping_with_overrides.geojson.gz"]="$TILDA_STATIC_BASE/infravelo-datensatz-b-fortlaufend"
    ["output/matched_tilda_ways.geojson.gz"]="$TILDA_STATIC_BASE/infravelo-datensatz-a-fortlaufend"
    ["output/aggregated_rvn_final.geojson.gz"]="$TILDA_STATIC_BASE/infravelo-datensatz-c-fortlaufend"
)

# Copy files
echo -e "${BLUE}Copying files...${NC}"
for src in "${!FILE_MAP[@]}"; do
    dest="${FILE_MAP[$src]}"
    filename=$(basename "$src")
    
    if [ ! -f "$src" ]; then
        echo "ERROR: Source file not found: $src"
        exit 1
    fi
    
    if [ ! -d "$dest" ]; then
        echo "ERROR: Destination directory not found: $dest"
        exit 1
    fi
    
    cp "$src" "$dest/$filename"
    echo -e "${GREEN}✓${NC} Copied $filename to $dest"
done

# Update meta.ts files
echo -e "${BLUE}Updating meta.ts files...${NC}"
for dest in "${FILE_MAP[@]}"; do
    meta_file="$dest/meta.ts"
    
    if [ ! -f "$meta_file" ]; then
        echo "WARNING: meta.ts not found at $meta_file"
        continue
    fi
    
    # Update the updatedAt line using sed
    sed -i "s/updatedAt: '[0-9]\{2\}\.[0-9]\{2\}\.[0-9]\{4\}',/updatedAt: '${UPDATE_DATE}',/" "$meta_file"
    echo -e "${GREEN}✓${NC} Updated updatedAt in $(basename $(dirname $meta_file))/meta.ts"
done

echo -e "${GREEN}Done! All files copied and meta.ts files updated.${NC}"
