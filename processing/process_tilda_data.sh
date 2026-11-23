#!/bin/bash
# -*- coding: utf-8 -*-
# process_tilda_data.sh
# ---------------------
# Verarbeitet die TILDA Rohdaten aus data-raw-tilda/ und schneidet sie auf Berlin zu.
# Anschließend werden die TILDA-Attribute zu RVN-Attributen übersetzt.
#
# Die drei Datensätze sind unabhängig voneinander und laufen parallel, je in einem eigenen Prozess:
# 1. clip_tilda_data.py schneidet die Rohdatei auf die Berliner Bezirksgrenzen zu (-> data/).
# 2. translate_attributes_tilda_to_rvn.py --source <datensatz> übersetzt die TILDA-Attribute
#    in RVN-Attribute (-> output/TILDA-translated/).
#
# Im Terminal steht je Datensatz nur eine Statuszeile. Die vollständige Ausgabe jedes Prozesses
# (inkl. aller Warnungen je osm_id) steht in output/logs/process_tilda_data_<zeit>_<datensatz>.log.
#
# Eingabedateien (data-raw-tilda/):
# - bikelanes.fgb -> TILDA Radwege Berlin.fgb -> TILDA Bikelanes Translated.fgb
# - roads.fgb -> TILDA Straßen Berlin.fgb -> TILDA Streets Translated.fgb
# - roadsPathClasses.fgb -> TILDA Wege Berlin.fgb -> TILDA Paths Translated.fgb
#
# Ausgabedateien (data/):
# - TILDA Radwege Berlin.fgb
# - TILDA Straßen Berlin.fgb
# - TILDA Wege Berlin.fgb
#
# Ausgabedateien (output/TILDA-translated/):
# - TILDA Bikelanes Translated.fgb
# - TILDA Streets Translated.fgb
# - TILDA Paths Translated.fgb
# (Bei --clip: Dateien mit " Neukoelln", " Norden" oder " Sueden" Suffix)
#
# Verwendung:
#     ./process_tilda_data.sh [--translate-only] [--clip <region>]
#
# Argumente:
#     --translate-only    Überspringt das Clipping und führt nur die TILDA-Attribut-Übersetzung durch
#                        (Voraussetzung: geclippte Dateien in data/ sind bereits vorhanden)
#     --clip <region>     Regionaler Zuschnitt: neukoelln, norden oder sueden

set -e  # Beende das Skript bei Fehlern

# Argumentverarbeitung
TRANSLATE_ONLY=false
CLIP_REGION=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --translate-only)
            TRANSLATE_ONLY=true
            shift
            ;;
        --clip)
            CLIP_REGION="$2"
            shift 2
            ;;
        -h|--help)
            echo "Verwendung: $0 [--translate-only] [--clip <region>]"
            echo ""
            echo "Optionen:"
            echo "  --translate-only    Überspringt das Clipping und führt nur die TILDA-Attribut-Übersetzung durch"
            echo "  --clip <region>     Regionaler Zuschnitt: neukoelln, norden oder sueden"
            echo "  -h, --help         Zeigt diese Hilfe an"
            exit 0
            ;;
        *)
            echo "❌ Unbekanntes Argument: $1"
            echo "Verwende --help für Hilfe"
            exit 1
            ;;
    esac
done

# Validiere CLIP_REGION
if [[ -n "$CLIP_REGION" ]]; then
    if [[ ! "$CLIP_REGION" =~ ^(neukoelln|norden|sueden)$ ]]; then
        echo "❌ Ungültige Region: $CLIP_REGION. Erlaubt sind: neukoelln, norden, sueden"
        exit 1
    fi
fi

# Variablen definieren
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"
VENV="$(cd "$PROJECT_ROOT/.." && pwd)/.venv"
CLIP_SCRIPT="$PROJECT_ROOT/scripts/clip_tilda_data.py"
TRANSLATE_SCRIPT="$PROJECT_ROOT/scripts/translate_attributes_tilda_to_rvn.py"
INPUT_DIR="$PROJECT_ROOT/data-raw-tilda"
OUTPUT_DIR="$PROJECT_ROOT/data"
TRANSLATE_OUTPUT_DIR="$PROJECT_ROOT/output/TILDA-translated"
CLIP_FEATURES="$PROJECT_ROOT/data/Berlin Bezirke.gpkg"

# Datensätze: Schlüssel = --source von translate_attributes_tilda_to_rvn.py
SOURCES=(bikelanes streets paths)
# Mit Leerzeichen auf gleiche Breite gebracht (printf %-8s zählt Bytes, "ß" hat zwei)
declare -A LABEL=([bikelanes]="Radwege " [streets]="Straßen " [paths]="Wege    ")
declare -A RAW_FILE=([bikelanes]="bikelanes.fgb" [streets]="roads.fgb" [paths]="roadsPathClasses.fgb")
declare -A CLIPPED_FILE=([bikelanes]="TILDA Radwege Berlin.fgb" [streets]="TILDA Straßen Berlin.fgb" [paths]="TILDA Wege Berlin.fgb")
declare -A TRANSLATED_NAME=([bikelanes]="Bikelanes" [streets]="Streets" [paths]="Paths")

# Prüfe ob .venv existiert
if [ ! -d "$VENV" ]; then
    echo "❌ Fehler: .venv Verzeichnis im Projekt-Root nicht gefunden!"
    echo "Bitte erstelle zuerst im Projekt-Root die virtuelle Umgebung mit:"
    echo "python3 -m venv .venv"
    echo "source .venv/bin/activate"
    echo "pip install -r requirements.txt"
    exit 1
fi

source "$VENV/bin/activate"

# Setze PYTHONPATH damit die helper Module gefunden werden; ungepuffert, damit die Logs live mitlaufen
export PYTHONPATH="$PROJECT_ROOT:$PYTHONPATH"
export PYTHONUNBUFFERED=1

# Log-Dateien: eine Übersicht plus eine je Datensatz
LOG_DIR="$PROJECT_ROOT/output/logs"
mkdir -p "$LOG_DIR"
RUN_ID="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/process_tilda_data_${RUN_ID}.log"
declare -A SOURCE_LOG
for s in "${SOURCES[@]}"; do
    SOURCE_LOG[$s]="$LOG_DIR/process_tilda_data_${RUN_ID}_${s}.log"
done

# Schreibt ins Terminal und in die Übersichts-Log-Datei
log() {
    echo "$@" | tee -a "$LOG_FILE"
}

# Prüfe Voraussetzungen
for script in "$CLIP_SCRIPT" "$TRANSLATE_SCRIPT"; do
    if [ ! -f "$script" ]; then
        echo "❌ Fehler: Skript nicht gefunden: $script"
        exit 1
    fi
done

if [ "$TRANSLATE_ONLY" = false ]; then
    if [ ! -d "$INPUT_DIR" ]; then
        echo "❌ Fehler: Eingabeverzeichnis nicht gefunden: $INPUT_DIR"
        exit 1
    fi
    if [ ! -f "$CLIP_FEATURES" ]; then
        echo "❌ Fehler: Berlin Bezirke Datei nicht gefunden: $CLIP_FEATURES"
        exit 1
    fi
else
    for s in "${SOURCES[@]}"; do
        if [ ! -f "$OUTPUT_DIR/${CLIPPED_FILE[$s]}" ]; then
            echo "❌ Fehler: Benötigte geclippte Datei nicht gefunden: $OUTPUT_DIR/${CLIPPED_FILE[$s]}"
            echo "Bitte führe zuerst das Clipping ohne --translate-only aus."
            exit 1
        fi
    done
fi

mkdir -p "$OUTPUT_DIR" "$TRANSLATE_OUTPUT_DIR"

TRANSLATE_CLIP_ARG=()
REGION_SUFFIX=""
if [[ -n "$CLIP_REGION" ]]; then
    TRANSLATE_CLIP_ARG=(--clip "$CLIP_REGION")
    REGION_SUFFIX=" ${CLIP_REGION^}"
fi

# Statusdateien der Hintergrundprozesse: <datensatz>.step (aktueller Schritt), <datensatz>.exit (Exit-Code)
STATUS_DIR="$(mktemp -d)"
trap 'rm -rf "$STATUS_DIR"' EXIT

# Ein Datensatz: zuschneiden (außer bei --translate-only), dann übersetzen
run_source() {
    local s="$1"
    if [ "$TRANSLATE_ONLY" = false ]; then
        echo "zuschneiden" > "$STATUS_DIR/$s.step"
        python3 "$CLIP_SCRIPT" \
            --input "$INPUT_DIR/${RAW_FILE[$s]}" \
            --clip-features "$CLIP_FEATURES" \
            --output "$OUTPUT_DIR/${CLIPPED_FILE[$s]}" || return 1
    fi
    echo "übersetzen" > "$STATUS_DIR/$s.step"
    python3 "$TRANSLATE_SCRIPT" --source "$s" --data-dir "$OUTPUT_DIR" \
        --output-dir "$TRANSLATE_OUTPUT_DIR" --crs 25833 "${TRANSLATE_CLIP_ARG[@]}"
}

fmt_duration() {
    printf "%d:%02d" $(($1 / 60)) $(($1 % 60))
}

if [ "$TRANSLATE_ONLY" = false ]; then
    log "🚀 TILDA-Daten zuschneiden und übersetzen (parallel)"
else
    log "🚀 TILDA-Daten übersetzen (parallel, ohne Zuschneiden)"
fi
[[ -n "$CLIP_REGION" ]] && log "🌍 Regionaler Zuschnitt: $CLIP_REGION"
log ""

declare -A START
for s in "${SOURCES[@]}"; do
    START[$s]=$(date +%s)
    (
        run_source "$s" && rc=0 || rc=$?
        echo "$rc" > "$STATUS_DIR/$s.exit.tmp" && mv "$STATUS_DIR/$s.exit.tmp" "$STATUS_DIR/$s.exit"
    ) > "${SOURCE_LOG[$s]}" 2>&1 &
done

# Statuszeile eines Datensatzes (läuft in $(...), darf also nichts setzen)
declare -A END
status_line() {
    local s="$1" elapsed label
    label="${LABEL[$s]}"
    if [ -n "${END[$s]}" ]; then
        elapsed=$((END[$s] - START[$s]))
        if [ "$(cat "$STATUS_DIR/$s.exit")" = "0" ]; then
            local warnings
            warnings=$(grep -c "WARNING" "${SOURCE_LOG[$s]}" || true)
            echo "✅ $label fertig in $(fmt_duration $elapsed) ($warnings Warnungen)"
        else
            echo "❌ $label fehlgeschlagen nach $(fmt_duration $elapsed)"
        fi
    else
        elapsed=$(($(date +%s) - START[$s]))
        echo "$SPINNER_CHAR $label $(cat "$STATUS_DIR/$s.step" 2>/dev/null || echo "startet") … $(fmt_duration $elapsed)"
    fi
}

SPINNER=(⠋ ⠙ ⠹ ⠸ ⠼ ⠴ ⠦ ⠧ ⠇ ⠏)
FRAME=0
FIRST_DRAW=true
declare -A REPORTED
while :; do
    DONE_COUNT=0
    FAILED=()
    SPINNER_CHAR="${SPINNER[$((FRAME % ${#SPINNER[@]}))]}"
    FRAME=$((FRAME + 1))
    LINES=()
    for s in "${SOURCES[@]}"; do
        if [ -f "$STATUS_DIR/$s.exit" ]; then
            [ -n "${END[$s]}" ] || END[$s]=$(date +%s)
            DONE_COUNT=$((DONE_COUNT + 1))
            [ "$(cat "$STATUS_DIR/$s.exit")" = "0" ] || FAILED+=("$s")
        fi
        LINES+=("$(status_line "$s")")
    done

    if [ -t 1 ]; then
        # Im Terminal die drei Zeilen an Ort und Stelle neu zeichnen
        [ "$FIRST_DRAW" = true ] || printf "\033[%dA" "${#SOURCES[@]}"
        FIRST_DRAW=false
        for line in "${LINES[@]}"; do
            printf "\r\033[K%s\n" "$line"
        done
    else
        # Ohne Terminal nur abgeschlossene Datensätze melden
        for i in "${!SOURCES[@]}"; do
            s="${SOURCES[$i]}"
            if [ -n "${END[$s]}" ] && [ -z "${REPORTED[$s]}" ]; then
                echo "${LINES[$i]}"
                REPORTED[$s]=1
            fi
        done
    fi

    [ "$DONE_COUNT" -eq "${#SOURCES[@]}" ] && break
    sleep 0.1
done
wait

# Endstand in die Übersichts-Log-Datei
printf "%s\n" "${LINES[@]}" >> "$LOG_FILE"

log ""
log "📊 Ergebnisse:"
for s in "${SOURCES[@]}"; do
    if [ "$TRANSLATE_ONLY" = false ]; then
        log "   - $OUTPUT_DIR/${CLIPPED_FILE[$s]} -> $TRANSLATE_OUTPUT_DIR/TILDA ${TRANSLATED_NAME[$s]}${REGION_SUFFIX} Translated.fgb"
    else
        log "   - $TRANSLATE_OUTPUT_DIR/TILDA ${TRANSLATED_NAME[$s]}${REGION_SUFFIX} Translated.fgb"
    fi
done
log ""
log "📝 Logs mit allen Warnungen je Datensatz:"
for s in "${SOURCES[@]}"; do
    log "   - ${SOURCE_LOG[$s]}"
done

if [ "${#FAILED[@]}" -gt 0 ]; then
    log ""
    log "❌ Fehlgeschlagen: ${FAILED[*]} – Details im jeweiligen Log (siehe oben)"
    exit 1
fi

log ""
log "🎉 TILDA-Datenverarbeitung erfolgreich abgeschlossen!"
