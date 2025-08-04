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

Verwendung:
    ./scripts/process_tilda_data.sh [--translate-only]

Argumente:
    --translate-only    Überspringt das Clipping und führt nur die TILDA-Attribut-Übersetzung durch
                       (Voraussetzung: geclippte Dateien in data/ sind bereits vorhanden)
"""

set -e  # Beende das Skript bei Fehlern

# Argumentverarbeitung
TRANSLATE_ONLY=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --translate-only)
            TRANSLATE_ONLY=true
            shift
            ;;
        -h|--help)
            echo "Verwendung: $0 [--translate-only]"
            echo ""
            echo "Optionen:"
            echo "  --translate-only    Überspringt das Clipping und führt nur die TILDA-Attribut-Übersetzung durch"
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

# Variablen definieren
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
CLIP_SCRIPT="$SCRIPT_DIR/clip_tilda_data.py"
INPUT_DIR="$PROJECT_ROOT/data-raw-tilda"
OUTPUT_DIR="$PROJECT_ROOT/data"
CLIP_FEATURES="$PROJECT_ROOT/data/Berlin Bezirke.gpkg"

# Prüfe ob .venv existiert
if [ ! -d ".venv" ]; then
    echo "❌ Fehler: .venv Verzeichnis nicht gefunden!"
    echo "Bitte erstelle zuerst die virtuelle Umgebung mit:"
    echo "python3 -m venv .venv"
    echo "source .venv/bin/activate"
    echo "pip install -r processing/requirements.txt"
    exit 1
fi

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
    echo ""

    # Verarbeite bikelanes.fgb -> TILDA Radwege Berlin.fgb
    echo "🚴 Verarbeite Radwege (bikelanes.fgb)..."
    python3 "$CLIP_SCRIPT" \
        --input "$INPUT_DIR/bikelanes.fgb" \
        --clip-features "$CLIP_FEATURES" \
        --output "$OUTPUT_DIR/TILDA Radwege Berlin.fgb"

    # Verarbeite roads.fgb -> TILDA Straßen Berlin.fgb
    echo ""
    echo "🚗 Verarbeite Straßen (roads.fgb)..."
    python3 "$CLIP_SCRIPT" \
        --input "$INPUT_DIR/roads.fgb" \
        --clip-features "$CLIP_FEATURES" \
        --output "$OUTPUT_DIR/TILDA Straßen Berlin.fgb"

    # Verarbeite roadsPathClasses.fgb -> TILDA Wege Berlin.fgb
    echo ""
    echo "🚶 Verarbeite Wege (roadsPathClasses.fgb)..."
    python3 "$CLIP_SCRIPT" \
        --input "$INPUT_DIR/roadsPathClasses.fgb" \
        --clip-features "$CLIP_FEATURES" \
        --output "$OUTPUT_DIR/TILDA Wege Berlin.fgb"

    echo ""
    echo "✅ Clipping der TILDA Daten erfolgreich abgeschlossen!"
    echo "📊 Geclippte Dateien:"
    echo "   - $OUTPUT_DIR/TILDA Radwege Berlin.fgb"
    echo "   - $OUTPUT_DIR/TILDA Straßen Berlin.fgb"
    echo "   - $OUTPUT_DIR/TILDA Wege Berlin.fgb"
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
fi

# TILDA Attribut-Übersetzung nach dem Clipping
echo ""
echo "🔄 Starte TILDA Attribut-Übersetzung..."
TRANSLATE_SCRIPT="$PROJECT_ROOT/processing/translate_attributes_tilda_to_rvn.py"
TRANSLATE_OUTPUT_DIR="$PROJECT_ROOT/output/TILDA-translated"

# Prüfe ob das Übersetzungsskript existiert
if [ ! -f "$TRANSLATE_SCRIPT" ]; then
    echo "❌ Fehler: translate_attributes_tilda_to_rvn.py wurde nicht gefunden: $TRANSLATE_SCRIPT"
    exit 1
fi

# Erstelle das Ausgabeverzeichnis für die Übersetzung falls es nicht existiert
mkdir -p "$TRANSLATE_OUTPUT_DIR"

# Aktiviere die virtuelle Umgebung und führe die Übersetzung aus
echo "📝 Übersetze TILDA-Attribute zu RVN-Attributen..."
cd "$PROJECT_ROOT"
python3 "$TRANSLATE_SCRIPT" --data-dir "$OUTPUT_DIR"

if [ $? -ne 0 ]; then
    echo "❌ Fehler bei der TILDA Attribut-Übersetzung"
    exit 1
fi

echo ""
echo "✅ TILDA Attribut-Übersetzung erfolgreich abgeschlossen!"
echo "📊 Übersetzte Dateien:"
echo "   - $TRANSLATE_OUTPUT_DIR/TILDA Bikelanes Translated.fgb"
echo "   - $TRANSLATE_OUTPUT_DIR/TILDA Streets Translated.fgb"  
echo "   - $TRANSLATE_OUTPUT_DIR/TILDA Paths Translated.fgb"

echo ""
if [ "$TRANSLATE_ONLY" = false ]; then
    echo "🎉 Vollständige TILDA Datenverarbeitung (Clipping + Translation) erfolgreich abgeschlossen!"
else
    echo "🎉 TILDA Attribut-Übersetzung erfolgreich abgeschlossen!"
fi
