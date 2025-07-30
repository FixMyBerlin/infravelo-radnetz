#!/bin/bash
# -*- coding: utf-8 -*-
"""
process_tilda_data.sh
---------------------
Verarbeitet die TILDA Rohdaten aus data-raw-tilda/ und schneidet sie auf Berlin zu.

Dieses Skript verwendet clip_tilda_data.py, um die drei FGB-Dateien aus dem 
data-raw-tilda Verzeichnis zu verarbeiten und auf die Berliner Bezirksgrenzen 
zuzuschneiden. Die Ergebnisse werden im data/ Verzeichnis gespeichert.

Eingabedateien (data-raw-tilda/):
- bikelanes.fgb -> TILDA Radwege Berlin.fgb
- roads.fgb -> TILDA Straßen Berlin.fgb  
- roadsPathClasses.fgb -> TILDA Wege Berlin.fgb

Ausgabedateien (data/):
- TILDA Radwege Berlin.fgb
- TILDA Straßen Berlin.fgb
- TILDA Wege Berlin.fgb

Verwendung:
    ./scripts/process_tilda_data.sh
"""

set -e  # Beende das Skript bei Fehlern

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

# Prüfe ob das Eingabeverzeichnis existiert
if [ ! -d "$INPUT_DIR" ]; then
    echo "❌ Fehler: Eingabeverzeichnis nicht gefunden: $INPUT_DIR"
    exit 1
fi

# Prüfe ob die Clip-Features existieren
if [ ! -f "$CLIP_FEATURES" ]; then
    echo "❌ Fehler: Berlin Bezirke Datei nicht gefunden: $CLIP_FEATURES"
    exit 1
fi

# Erstelle das Ausgabeverzeichnis falls es nicht existiert
mkdir -p "$OUTPUT_DIR"

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
echo "✅ Alle TILDA Daten erfolgreich verarbeitet!"
echo "📊 Ausgabedateien:"
echo "   - $OUTPUT_DIR/TILDA Radwege Berlin.fgb"
echo "   - $OUTPUT_DIR/TILDA Straßen Berlin.fgb"
echo "   - $OUTPUT_DIR/TILDA Wege Berlin.fgb"
