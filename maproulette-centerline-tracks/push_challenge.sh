#!/bin/bash
# push_challenge.sh
#
# Legt die MapRoulette-Challenge aus challenge.json an oder aktualisiert sie und
# lässt MapRoulette danach die Aufgaben aus remoteGeoJson neu einlesen.
#
# Steht in challenge.json noch keine "id", wird die Challenge angelegt und die neue
# id in die Datei geschrieben. Sonst wird die bestehende Challenge aktualisiert.
#
# Verwendung: MAPROULETTE_API_KEY=... ./push_challenge.sh [--no-rebuild]
#
# Voraussetzung: "parent" (Projekt-ID) und "remoteGeoJson" (Netlify-URL) sind in
#                challenge.json eingetragen, die Daten liegen auf Netlify.

set -e

cd "$(dirname "$0")"
API="https://maproulette.org/api/v2"
: "${MAPROULETTE_API_KEY:?MAPROULETTE_API_KEY ist nicht gesetzt}"

if [ "$(jq -r '.parent // empty' challenge.json)" = "" ] || [ "$(jq -r '.remoteGeoJson // empty' challenge.json)" = "" ]; then
    echo "❌ In challenge.json fehlen 'parent' oder 'remoteGeoJson'." >&2
    exit 1
fi

# Der Stand der Daten ist das Datum des letzten Laufs
BODY=$(jq --arg date "$(date -u +%Y-%m-%dT00:00:00.000Z)" '. + {dataOriginDate: $date}' challenge.json)
CHALLENGE_ID=$(jq -r '.id // empty' challenge.json)

if [ -z "$CHALLENGE_ID" ]; then
    echo "Lege Challenge an..."
    RESPONSE=$(curl --fail-with-body -sS -X POST "$API/challenge" \
        -H "apiKey: $MAPROULETTE_API_KEY" -H "Content-Type: application/json" -d "$BODY")
    CHALLENGE_ID=$(echo "$RESPONSE" | jq -r '.id')
    jq --argjson id "$CHALLENGE_ID" '{id: $id} + .' challenge.json > challenge.json.tmp
    mv challenge.json.tmp challenge.json
else
    echo "Aktualisiere Challenge $CHALLENGE_ID..."
    curl --fail-with-body -sS -o /dev/null -X PUT "$API/challenge/$CHALLENGE_ID" \
        -H "apiKey: $MAPROULETTE_API_KEY" -H "Content-Type: application/json" -d "$BODY"
fi

if [ "$1" != "--no-rebuild" ]; then
    echo "Lese Aufgaben neu ein..."
    curl --fail-with-body -sS -o /dev/null -X PUT \
        "$API/challenge/$CHALLENGE_ID/rebuild?removeUnmatched=true&skipSnapshot=true" \
        -H "apiKey: $MAPROULETTE_API_KEY"
fi

echo "✅ https://maproulette.org/browse/challenges/$CHALLENGE_ID"
