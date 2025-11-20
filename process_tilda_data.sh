#!/bin/bash
# -*- coding: utf-8 -*-
"""
process_tilda_data.sh
---------------------
Verarbeitet die TILDA Rohdaten aus data-raw-tilda/ und schneidet sie auf Berlin zu.
Anschließend werden die TILDA-Attribute zu RVN-Attributen übersetzt.

Dieses Skript führt zwei Hauptschritte aus:
1. Verwendet clip_tilda_data.py, um die drei FGB-Dateien aus dem 
   data-raw-tilda Verzeichnis zu verarbeiten und auf die Berliner 
   Bezirksgrenzen zuzuschneiden. Die Ergebnisse werden im data/ Verzeichnis gespeichert.
2. Verwendet translate_attributes_tilda_to_rvn.py, um die TILDA-Attribute 
   in RVN-Attribute zu übersetzen. Die Ergebnisse werden im output/TILDA-translated/ 
   Verzeichnis gespeichert.

Eingabedateien (data-raw-tilda/):
- bikelanes.fgb -> TILDA Radwege Berlin.fgb -> TILDA Bikelanes Translated.fgb
- roads.fgb -> TILDA Straßen Berlin.fgb -> TILDA Streets Translated.fgb
- roadsPathClasses.fgb -> TILDA Wege Berlin.fgb -> TILDA Paths Translated.fgb

Ausgabedateien (data/):
- TILDA Radwege Berlin.fgb
- TILDA Straßen Berlin.fgb
- TILDA Wege Berlin.fgb

Ausgabedateien (output/TILDA-translated/):
- TILDA Bikelanes Translated.fgb
- TILDA Streets Translated.fgb
- TILDA Paths Translated.fgb
(Bei --clip: Dateien mit " Neukoelln", " Norden" oder " Sueden" Suffix)

Verwendung:
    ./process_tilda_data.sh [--translate-only] [--clip <region>]

Argumente:
    --translate-only    Überspringt das Clipping und führt nur die TILDA-Attribut-Übersetzung durch
                       (Voraussetzung: geclippte Dateien in data/ sind bereits vorhanden)
    --clip <region>     Regionaler Zuschnitt: neukoelln, norden oder sueden
"""

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
CLIP_SCRIPT="$PROJECT_ROOT/scripts/clip_tilda_data.py"
INPUT_DIR="$PROJECT_ROOT/data-raw-tilda"
OUTPUT_DIR="$PROJECT_ROOT/data"
CLIP_FEATURES="$PROJECT_ROOT/data/Berlin Bezirke.gpkg"

# Prüfe ob .venv existiert
if [ ! -d ".venv" ]; then
    echo "❌ Fehler: .venv Verzeichnis nicht gefunden!"
    echo "Bitte erstelle zuerst die virtuelle Umgebung mit:"
    echo "python3 -m venv .venv"
    echo "source .venv/bin/activate"
    echo "pip install -r requirements.txt"
    exit 1
fi

# Aktiviere virtuelles Environment automatisch
echo "🔧 Aktiviere virtuelles Environment..."
source "$PROJECT_ROOT/.venv/bin/activate"

# Setze PYTHONPATH damit die helper Module gefunden werden
export PYTHONPATH="$PROJECT_ROOT/processing:$PYTHONPATH"

# Prüfe ob das clip_tilda_data.py Skript existiert
if [ ! -f "$CLIP_SCRIPT" ]; then
    echo "❌ Fehler: clip_tilda_data.py wurde nicht gefunden: $CLIP_SCRIPT"
    exit 1
fi

# Prüfe ob das Eingabeverzeichnis existiert (nur wenn Clipping durchgeführt wird)
if [ "$TRANSLATE_ONLY" = false ] && [ ! -d "$INPUT_DIR" ]; then
    echo "❌ Fehler: Eingabeverzeichnis nicht gefunden: $INPUT_DIR"
    exit 1
fi

# Prüfe ob die Clip-Features existieren (nur wenn Clipping durchgeführt wird)
if [ "$TRANSLATE_ONLY" = false ] && [ ! -f "$CLIP_FEATURES" ]; then
    echo "❌ Fehler: Berlin Bezirke Datei nicht gefunden: $CLIP_FEATURES"
    exit 1
fi

# Erstelle das Ausgabeverzeichnis falls es nicht existiert
mkdir -p "$OUTPUT_DIR"

if [ "$TRANSLATE_ONLY" = false ]; then
    echo "🚀 Starte Verarbeitung der TILDA Daten..."
    echo "📁 Eingabeverzeichnis: $INPUT_DIR"
    echo "📁 Ausgabeverzeichnis: $OUTPUT_DIR"
    echo "🗺️  Clip-Features: $CLIP_FEATURES"
    if [[ -n "$CLIP_REGION" ]]; then
        echo "🌍 Regionaler Zuschnitt: $CLIP_REGION"
    fi
    echo ""

    TRANSLATE_SCRIPT="$PROJECT_ROOT/scripts/translate_attributes_tilda_to_rvn.py"
    TRANSLATE_OUTPUT_DIR="$PROJECT_ROOT/output/TILDA-translated"
    mkdir -p "$TRANSLATE_OUTPUT_DIR"

    # Setze Clip-Argument für translate_attributes_tilda_to_rvn.py
    TRANSLATE_CLIP_ARG=""
    if [[ -n "$CLIP_REGION" ]]; then
        TRANSLATE_CLIP_ARG="--clip $CLIP_REGION"
    fi

    # Verarbeite bikelanes.fgb -> TILDA Radwege Berlin.fgb
    echo "🚴 Verarbeite Radwege (bikelanes.fgb)..."
    python3 "$CLIP_SCRIPT" \
        --input "$INPUT_DIR/bikelanes.fgb" \
        --clip-features "$CLIP_FEATURES" \
        --output "$OUTPUT_DIR/TILDA Radwege Berlin.fgb"
    echo "🔄 Übersetze TILDA Radwege Berlin.fgb..."
    python3 "$TRANSLATE_SCRIPT" --data-dir "$OUTPUT_DIR" --output-dir "$TRANSLATE_OUTPUT_DIR" --crs 25833 $TRANSLATE_CLIP_ARG

    # Verarbeite roads.fgb -> TILDA Straßen Berlin.fgb
    echo ""
    echo "🚗 Verarbeite Straßen (roads.fgb)..."
    python3 "$CLIP_SCRIPT" \
        --input "$INPUT_DIR/roads.fgb" \
        --clip-features "$CLIP_FEATURES" \
        --output "$OUTPUT_DIR/TILDA Straßen Berlin.fgb"
    echo "🔄 Übersetze TILDA Straßen Berlin.fgb..."
    python3 "$TRANSLATE_SCRIPT" --data-dir "$OUTPUT_DIR" --output-dir "$TRANSLATE_OUTPUT_DIR" --crs 25833 $TRANSLATE_CLIP_ARG

    # Verarbeite roadsPathClasses.fgb -> TILDA Wege Berlin.fgb
    echo ""
    echo "🚶 Verarbeite Wege (roadsPathClasses.fgb)..."
    python3 "$CLIP_SCRIPT" \
        --input "$INPUT_DIR/roadsPathClasses.fgb" \
        --clip-features "$CLIP_FEATURES" \
        --output "$OUTPUT_DIR/TILDA Wege Berlin.fgb"
    echo "🔄 Übersetze TILDA Wege Berlin.fgb..."
    python3 "$TRANSLATE_SCRIPT" --data-dir "$OUTPUT_DIR" --output-dir "$TRANSLATE_OUTPUT_DIR" --crs 25833 $TRANSLATE_CLIP_ARG

    echo ""
    echo "✅ Clipping und Übersetzung der TILDA Daten erfolgreich abgeschlossen!"
    echo "📊 Geclippte und übersetzte Dateien:"
    REGION_SUFFIX=""
    if [[ -n "$CLIP_REGION" ]]; then
        REGION_SUFFIX=" $(echo ${CLIP_REGION^})"  # Capitalize first letter
    fi
    echo "   - $OUTPUT_DIR/TILDA Radwege Berlin.fgb -> $TRANSLATE_OUTPUT_DIR/TILDA Bikelanes${REGION_SUFFIX} Translated.fgb"
    echo "   - $OUTPUT_DIR/TILDA Straßen Berlin.fgb -> $TRANSLATE_OUTPUT_DIR/TILDA Streets${REGION_SUFFIX} Translated.fgb"
    echo "   - $OUTPUT_DIR/TILDA Wege Berlin.fgb -> $TRANSLATE_OUTPUT_DIR/TILDA Paths${REGION_SUFFIX} Translated.fgb"
else
    echo "⏭️  Überspringe Clipping (--translate-only aktiviert)"
    
    # Prüfe ob die benötigten geclippten Dateien vorhanden sind
    REQUIRED_FILES=(
        "$OUTPUT_DIR/TILDA Radwege Berlin.fgb"
        "$OUTPUT_DIR/TILDA Straßen Berlin.fgb"
        "$OUTPUT_DIR/TILDA Wege Berlin.fgb"
    )
    
    for file in "${REQUIRED_FILES[@]}"; do
        if [ ! -f "$file" ]; then
            echo "❌ Fehler: Benötigte geclippte Datei nicht gefunden: $file"
            echo "Bitte führe zuerst das Clipping ohne --translate-only aus oder stelle sicher, dass alle Dateien vorhanden sind."
            exit 1
        fi
    done
    
    echo "✅ Alle benötigten geclippten Dateien sind vorhanden"
    
    echo ""
    echo "🔄 Starte TILDA Attribut-Übersetzung..."
    if [[ -n "$CLIP_REGION" ]]; then
        echo "🌍 Regionaler Zuschnitt: $CLIP_REGION"
    fi
    TRANSLATE_SCRIPT="$PROJECT_ROOT/scripts/translate_attributes_tilda_to_rvn.py"
    TRANSLATE_OUTPUT_DIR="$PROJECT_ROOT/output/TILDA-translated"

    # Prüfe ob das Übersetzungsskript existiert
    if [ ! -f "$TRANSLATE_SCRIPT" ]; then
        echo "❌ Fehler: translate_attributes_tilda_to_rvn.py wurde nicht gefunden: $TRANSLATE_SCRIPT"
        exit 1
    fi

    # Erstelle das Ausgabeverzeichnis für die Übersetzung falls es nicht existiert
    mkdir -p "$TRANSLATE_OUTPUT_DIR"

    # Setze Clip-Argument für translate_attributes_tilda_to_rvn.py
    TRANSLATE_CLIP_ARG=""
    if [[ -n "$CLIP_REGION" ]]; then
        TRANSLATE_CLIP_ARG="--clip $CLIP_REGION"
    fi

    # Aktiviere die virtuelle Umgebung und führe die Übersetzung aus
    echo "📝 Übersetze TILDA-Attribute zu RVN-Attributen..."
    cd "$PROJECT_ROOT"
    python3 "$TRANSLATE_SCRIPT" --data-dir "$OUTPUT_DIR" $TRANSLATE_CLIP_ARG

    if [ $? -ne 0 ]; then
        echo "❌ Fehler bei der TILDA Attribut-Übersetzung"
        exit 1
    fi

    echo ""
    echo "✅ TILDA Attribut-Übersetzung erfolgreich abgeschlossen!"
    echo "📊 Übersetzte Dateien:"
    REGION_SUFFIX=""
    if [[ -n "$CLIP_REGION" ]]; then
        REGION_SUFFIX=" $(echo ${CLIP_REGION^})"  # Capitalize first letter
    fi
    echo "   - $TRANSLATE_OUTPUT_DIR/TILDA Bikelanes${REGION_SUFFIX} Translated.fgb"
    echo "   - $TRANSLATE_OUTPUT_DIR/TILDA Streets${REGION_SUFFIX} Translated.fgb"  
    echo "   - $TRANSLATE_OUTPUT_DIR/TILDA Paths${REGION_SUFFIX} Translated.fgb"
fi

echo ""
if [ "$TRANSLATE_ONLY" = false ]; then
    echo "🎉 Vollständige TILDA Datenverarbeitung (Clipping + Translation) erfolgreich abgeschlossen!"
else
    echo "🎉 TILDA Attribut-Übersetzung erfolgreich abgeschlossen!"
fi
