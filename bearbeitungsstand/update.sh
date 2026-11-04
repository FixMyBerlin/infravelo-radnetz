#!/bin/bash
set -euo pipefail

# Aktualisiert den Bearbeitungsstand in TILDA mit einem Befehl:
#   1. liest die Markierungen "erledigt" aus der key-value-db (über die beiden Skripte),
#   2. schreibt das Datum des Abrufs in die drei Datensätze in tilda-static-data,
#   3. committet und pusht tilda-static-data,
#   4. lädt die drei Datensätze nach TILDA hoch.
#
# Verwendung: bearbeitungsstand/update.sh [--env production|staging]
#   --env  Ziel in TILDA (Standard: production)
#
# Erwartet tilda-static-data und tilda-geo als Geschwister-Ordner dieses Repos
# (abweichend: TILDA_STATIC_DATA_DIR, TILDA_GEO_DIR).

ENV="production"
while [[ $# -gt 0 ]]; do
    case $1 in
        --env)
            ENV="$2"
            shift 2
            ;;
        *)
            echo "Unbekanntes Argument: $1 (erlaubt: --env production|staging)"
            exit 1
            ;;
    esac
done
if [[ "$ENV" != "production" && "$ENV" != "staging" ]]; then
    echo "Ungültiges Ziel: $ENV. Erlaubt sind: production, staging"
    exit 1
fi

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
STATIC_DIR="${TILDA_STATIC_DATA_DIR:-$REPO_DIR/../tilda-static-data}"
TILDA_DIR="${TILDA_GEO_DIR:-$REPO_DIR/../tilda-geo}"
DATASETS_DIR="geojson/region-infravelo"
NETZ_DATASETS=(infravelo-ren-netz-zuteilung-netz infravelo-ren-netz-zuteilung-gebiete)
TRACK_DATASET=infravelo-ren-kartierung-tracks
PYTHON="$REPO_DIR/.venv/bin/python"

# Vorbedingungen prüfen, bevor etwas geschrieben wird.
for d in "$STATIC_DIR" "$TILDA_DIR/app"; do
    [[ -d "$d" ]] || { echo "Ordner fehlt: $d"; exit 1; }
done
[[ -x "$PYTHON" ]] || { echo "Python-venv fehlt: $PYTHON"; exit 1; }
if [[ -n "$(git -C "$STATIC_DIR" status --porcelain -- "$DATASETS_DIR")" ]]; then
    echo "tilda-static-data hat offene Änderungen in $DATASETS_DIR. Bitte erst committen oder verwerfen."
    exit 1
fi
ASSIGNMENT="mapping-zuteilung/assignment.csv"
if [[ -n "$(git -C "$REPO_DIR" status --porcelain -- "$ASSIGNMENT")" ]]; then
    echo "$ASSIGNMENT hat offene Änderungen. Bitte erst committen."
    exit 1
fi
git -C "$STATIC_DIR" pull --ff-only --quiet

echo "== Bearbeitungsstand lesen und Daten schreiben"
cd "$REPO_DIR"
"$PYTHON" mapping-zuteilung/update_assignment.py
# Neue Kanten haben neue Nummern bekommen: Erst committen, sonst vergibt ein Lauf
# anderswo dieselben Nummern neu und die Markierungen landen auf falschen Kanten.
if [[ -n "$(git -C "$REPO_DIR" status --porcelain -- "$ASSIGNMENT")" ]]; then
    echo "Neue Kanten in $ASSIGNMENT aufgenommen. Bitte committen und pushen, dann erneut starten."
    exit 1
fi
"$PYTHON" maproulette-centerline-tracks/extract_centerline_tracks.py

# Zeitpunkt des Abrufs, wie ihn bearbeitungsstand/load_status.py im Cache ablegt (YYYY-MM-DDTHH:MM).
fetched_at() {
    "$PYTHON" -c "import json,sys; print(json.load(open(sys.argv[1]))['abgerufen'])" "$REPO_DIR/bearbeitungsstand/cache/$1.json"
}
MAPPING_AT="$(fetched_at mapping)"
TRACK_AT="$(fetched_at track)"

# Setzt Datum und Uhrzeit in der description und das Datum in dataUpdatedNote.
set_date() {
    local meta="$STATIC_DIR/$DATASETS_DIR/$1/meta.ts"
    local at="$2"
    local day="${at%%T*}"
    local time="${at##*T}"
    perl -pi -e "s/(Bearbeitungsstand aus dem Editor vom )\d{4}-\d{2}-\d{2} \d{2}:\d{2}\./\${1}$day $time./; s/(dataUpdatedNote: ')[^']*(')/\${1}$day\${2}/" "$meta"
    grep -q "Bearbeitungsstand aus dem Editor vom $day $time\." "$meta" || { echo "Datum in der description nicht gefunden: $meta"; exit 1; }
}

echo "== Datum eintragen (Netz: $MAPPING_AT, Tracks: $TRACK_AT)"
for ds in "${NETZ_DATASETS[@]}"; do
    set_date "$ds" "$MAPPING_AT"
done
set_date "$TRACK_DATASET" "$TRACK_AT"

echo "== tilda-static-data committen und pushen"
META_FILES=()
for ds in "${NETZ_DATASETS[@]}" "$TRACK_DATASET"; do
    META_FILES+=("$DATASETS_DIR/$ds/meta.ts")
done
if [[ -n "$(git -C "$STATIC_DIR" status --porcelain -- "${META_FILES[@]}")" ]]; then
    git -C "$STATIC_DIR" add -- "${META_FILES[@]}"
    git -C "$STATIC_DIR" commit --quiet -m "infraVelo: Update the editing status of the mapping network and the track ways"
    git -C "$STATIC_DIR" push --quiet
else
    echo "Datum unverändert, nichts zu committen."
fi

echo "== Nach TILDA hochladen ($ENV)"
cd "$TILDA_DIR/app"
bun run static-datasets-update -- --env="$ENV" --folder-filter=infravelo-ren-netz-zuteilung
bun run static-datasets-update -- --env="$ENV" --folder-filter="$TRACK_DATASET"

echo "== Fertig. Bearbeitungsstand Netz $MAPPING_AT, Tracks $TRACK_AT, hochgeladen nach $ENV."
