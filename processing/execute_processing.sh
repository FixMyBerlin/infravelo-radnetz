#!/bin/bash
# execute_processing.sh
# 
# Dieses Script führt den gesamten infraVelo Radnetz Verarbeitungsprozess aus.
# Es sichert finale Dateien vom vorherigen Lauf in output-last-run/
#
# Verarbeitungsschritte:
# 1. OSM-Wege mit Radvorrangsnetz matchen
# 2. Snapping und Attribut-Übernahme  
# 3. Finale Aggregation
# 4. Qualitätssicherungstests
#
# Dateiverwaltung:
# - Finale Dateien (snapping_network_enriched*, aggregated_rvn_final*) werden in output-last-run/ gesichert
# - Temporäre Dateien werden vor dem entsprechenden Verarbeitungsschritt gelöscht
# - Zwischendateien bleiben zwischen Schritten erhalten (für --start-step Funktionalität)
#
# Verwendung: ./execute_processing.sh [--clip-neukoelln] [--start-step <1-4>]
# 
# Argumente:
#   --clip-neukoelln    Beschränkt die Verarbeitung auf den Bezirk Neukölln
#   --start-step <1-4>  Startet die Verarbeitung ab dem angegebenen Schritt
#                       1: OSM-Wege Matching
#                       2: Snapping und Attribut-Übernahme
#                       3: Finale Aggregation
#                       4: Qualitätssicherungstests
# 
# Voraussetzung: Python venv ist bereits erstellt und requirements.txt wurde installiert
#               TILDA Daten sind bereits prozessiert (./scripts/process_tilda_data.sh)

set -e  # Script bei Fehlern beenden

# Zeiterfassung initialisieren
SCRIPT_START_TIME=$(date +%s)

# Funktion zur Berechnung und Anzeige der verstrichenen Zeit
show_elapsed_time() {
    local start_time=$1
    local step_name=$2
    local end_time=$(date +%s)
    local elapsed=$((end_time - start_time))
    local minutes=$((elapsed / 60))
    local seconds=$((elapsed % 60))
    
    if [ $minutes -gt 0 ]; then
        echo "⏱️  $step_name dauerte: ${minutes}m ${seconds}s"
    else
        echo "⏱️  $step_name dauerte: ${seconds}s"
    fi
}

# Funktion zur Anzeige der Gesamtzeit
show_total_time() {
    local start_time=$1
    local end_time=$(date +%s)
    local total_elapsed=$((end_time - start_time))
    local total_minutes=$((total_elapsed / 60))
    local total_seconds=$((total_elapsed % 60))
    
    echo ""
    echo "⏱️  =========================================="
    if [ $total_minutes -gt 0 ]; then
        echo "⏱️  Gesamte Verarbeitungszeit: ${total_minutes}m ${total_seconds}s"
    else
        echo "⏱️  Gesamte Verarbeitungszeit: ${total_seconds}s"
    fi
    echo "⏱️  =========================================="
}

# CLI-Argumente verarbeiten
CLIP_NEUKOELLN=""
START_STEP=1

# Verarbeite alle Argumente
while [[ $# -gt 0 ]]; do
    case $1 in
        --clip-neukoelln)
            CLIP_NEUKOELLN="--clip-neukoelln"
            shift
            ;;
        --start-step)
            START_STEP="$2"
            shift 2
            ;;
        *)
            echo "❌ Unbekanntes Argument: $1"
            echo "Verwendung: $0 [--clip-neukoelln] [--start-step <1-5>]"
            exit 1
            ;;
    esac
done

# Validiere START_STEP
if [[ ! "$START_STEP" =~ ^[1-5]$ ]]; then
    echo "❌ Ungültiger Schritt: $START_STEP. Erlaubt sind: 1-5"
    exit 1
fi

if [[ "$CLIP_NEUKOELLN" == "--clip-neukoelln" ]]; then
    echo "🌍 Verarbeitung wird auf Neukölln beschränkt."
else
    echo "🌍 Vollständige Verarbeitung für ganz Berlin."
fi

echo "🚀 Starte infraVelo Radnetz Verarbeitungsprozess ab Schritt $START_STEP..."

# Wechsle ins Hauptverzeichnis des Projekts
cd "$(dirname "$0")/.."

# Prüfe ob .venv existiert
if [ ! -d ".venv" ]; then
    echo "❌ Fehler: .venv Verzeichnis nicht gefunden!"
    echo "Bitte erstelle zuerst die virtuelle Umgebung mit:"
    echo "python3 -m venv .venv"
    echo "source .venv/bin/activate"
    echo "pip install -r processing/requirements.txt"
    exit 1
fi

# Sichere finale Ausgabedateien von vorherigem Lauf in output-last-run
echo "💾 Sichere finale Dateien von vorherigem Lauf..."
if [[ "$CLIP_NEUKOELLN" == "--clip-neukoelln" ]]; then
    SUFFIX="_neukoelln"
else
    SUFFIX=""
fi

# Verschiebe finale Dateien in output-last-run (überschreibt vorherige)
if [ -f "output/snapping_network_enriched${SUFFIX}.fgb" ]; then
    echo "  - Sichere snapping_network_enriched${SUFFIX}.fgb"
    mv "output/snapping_network_enriched${SUFFIX}.fgb" "output-last-run/"
fi
if [ -f "output/snapping_network_enriched${SUFFIX}.geojson" ]; then
    echo "  - Sichere snapping_network_enriched${SUFFIX}.geojson"
    mv "output/snapping_network_enriched${SUFFIX}.geojson" "output-last-run/"
fi
if [ -f "output/aggregated_rvn_final${SUFFIX}.gpkg" ]; then
    echo "  - Sichere aggregated_rvn_final${SUFFIX}.gpkg"
    mv "output/aggregated_rvn_final${SUFFIX}.gpkg" "output-last-run/"
fi
if [ -f "output/aggregated_rvn_final${SUFFIX}.fgb" ]; then
    echo "  - Sichere aggregated_rvn_final${SUFFIX}.fgb"
    mv "output/aggregated_rvn_final${SUFFIX}.fgb" "output-last-run/"
fi
if [ -f "output/aggregated_rvn_final${SUFFIX}.geojson" ]; then
    echo "  - Sichere aggregated_rvn_final${SUFFIX}.geojson"
    mv "output/aggregated_rvn_final${SUFFIX}.geojson" "output-last-run/"
fi

echo "✅ Finale Dateien erfolgreich gesichert."
echo ""

echo "🔄 Starte Verarbeitungsprozess..."

# Schritt 1: Matching
if [[ $START_STEP -le 1 ]]; then
    echo "🧹 Bereinigte temporäre Dateien für Schritt 1..."
    # Lösche Cache- und Zwischendateien aus output/matching/ (werden in Schritt 1 erstellt)
    if [ -d "output/matching" ]; then
        rm -f output/matching/osm_*_in_buffering.fgb
        rm -f output/matching/osm_*_manual_interventions.fgb
        rm -f output/matching/osm_*_orthogonal_all_ways.fgb
        rm -f output/matching/osm_*_orthogonal_removed.fgb
        echo "  - Gelöscht: Matching Zwischendateien"
    fi
    # Lösche matched Dateien (werden in Schritt 1 erstellt)
    rm -f output/matched/matched_tilda_*.fgb
    rm -f output/matched/matched_tilda_*.txt
    echo "  - Gelöscht: Matched TILDA Dateien"
    
    echo "🔍 Schritt 1/4: OSM-Wege mit Radvorrangsnetz matchen..."
    STEP1_START=$(date +%s)
    if [[ "$CLIP_NEUKOELLN" == "--clip-neukoelln" ]]; then
        ./.venv/bin/python processing/start_matching.py --clip-neukoelln
    else
        ./.venv/bin/python processing/start_matching.py
    fi
    if [ $? -ne 0 ]; then
        echo "❌ Fehler in Schritt 1: start_matching.py"
        exit 1
    fi
    show_elapsed_time $STEP1_START "Schritt 1"
    echo "✅ Schritt 1 abgeschlossen."
    echo ""
else
    echo "⏭️  Überspringe Schritt 1 (OSM-Wege Matching)"
    echo ""
fi

# Schritt 2: Snapping
if [[ $START_STEP -le 2 ]]; then
    echo "🧹 Bereinigte temporäre Dateien für Schritt 2..."
    # Lösche Snapping Zwischendateien (werden in Schritt 2 erstellt)
    if [ -d "output/snapping" ]; then
        rm -f output/snapping/rvn-segmented*.fgb
        rm -f output/snapping/rvn-segmented-attributed*.fgb
        rm -f output/snapping/osm_candidates_per_edge*.txt
        echo "  - Gelöscht: Snapping Zwischendateien"
    fi
    # Lösche snapping_network_enriched Dateien (werden in Schritt 2 erstellt)
    if [[ "$CLIP_NEUKOELLN" == "--clip-neukoelln" ]]; then
        SUFFIX="_neukoelln"
    else
        SUFFIX=""
    fi
    rm -f "output/snapping_network_enriched${SUFFIX}.fgb"
    echo "  - Gelöscht: snapping_network_enriched${SUFFIX}.fgb"
    
    echo "📍 Schritt 2/4: Snapping und Attribut-Übernahme..."
    STEP2_START=$(date +%s)
    if [[ "$CLIP_NEUKOELLN" == "--clip-neukoelln" ]]; then
        ./.venv/bin/python processing/start_snapping.py --clip-neukoelln
    else
        ./.venv/bin/python processing/start_snapping.py
    fi
    if [ $? -ne 0 ]; then
        echo "❌ Fehler in Schritt 2: start_snapping.py"
        exit 1
    fi
    show_elapsed_time $STEP2_START "Schritt 2"
    echo "✅ Schritt 2 abgeschlossen."
    echo ""
else
    echo "⏭️  Überspringe Schritt 2 (Snapping und Attribut-Übernahme)"
    echo ""
fi

# Schritt 3: Finale Aggregation
if [[ $START_STEP -le 3 ]]; then
    echo "🧹 Bereinigte temporäre Dateien für Schritt 3..."
    # Lösche aggregated_rvn_final Dateien (werden in Schritt 3 erstellt)
    if [[ "$CLIP_NEUKOELLN" == "--clip-neukoelln" ]]; then
        SUFFIX="_neukoelln"
    else
        SUFFIX=""
    fi
    rm -f "output/aggregated_rvn_final${SUFFIX}.gpkg"
    rm -f "output/aggregated_rvn_final${SUFFIX}.fgb"
    echo "  - Gelöscht: aggregated_rvn_final${SUFFIX} Dateien"
    
    echo "🎯 Schritt 3/4: Finale Aggregation..."
    STEP3_START=$(date +%s)
    if [[ "$CLIP_NEUKOELLN" == "--clip-neukoelln" ]]; then
        ./.venv/bin/python processing/aggregate_final_model.py --input ./output/snapping_network_enriched_neukoelln.fgb
    else
        ./.venv/bin/python processing/aggregate_final_model.py --input ./output/snapping_network_enriched.fgb
    fi
    if [ $? -ne 0 ]; then
        echo "❌ Fehler in Schritt 3: aggregate_final_model.py"
        exit 1
    fi
    show_elapsed_time $STEP3_START "Schritt 3"
    echo "✅ Schritt 3 abgeschlossen."
    echo ""
else
    echo "⏭️  Überspringe Schritt 3 (Finale Aggregation)"
    echo ""
fi

# Schritt 4: Qualitätssicherungstests
if [[ $START_STEP -le 4 ]]; then
    echo "🧪 Schritt 4/4: Führe Qualitätssicherungstests durch..."
    STEP4_START=$(date +%s)
    
    if [[ "$CLIP_NEUKOELLN" == "--clip-neukoelln" ]]; then
        ./.venv/bin/python testing/run_tests.py --clip-neukoelln
    else
        ./.venv/bin/python testing/run_tests.py
    fi
    
    if [ $? -ne 0 ]; then
        echo "❌ Qualitätssicherungstests fehlgeschlagen!"
        echo "   Die Verarbeitung wurde zwar abgeschlossen, aber die erwarteten"
        echo "   Attributwerte stimmen nicht mit den Test-Definitionen überein."
        echo "   Bitte überprüfen Sie die Ausgabe der Tests und die Verarbeitung."
        # Beende Script mit Fehlercode
        exit 1
    fi
    
    show_elapsed_time $STEP4_START "Schritt 4"
    echo "✅ Schritt 4 abgeschlossen."
    echo ""
else
    echo "⏭️  Überspringe Schritt 4 (Qualitätssicherungstests)"
    echo ""
fi
echo ""

echo "🎉 Verarbeitungsprozess erfolgreich abgeschlossen!"

# Gesamtzeit anzeigen
show_total_time $SCRIPT_START_TIME

echo ""
echo "📁 Ausgabedateien verfügbar in:"
if [[ "$CLIP_NEUKOELLN" == "--clip-neukoelln" ]]; then
    echo "   - output/aggregated_rvn_final_neukoelln.gpkg (finale Ergebnisse als GeoPackage)"
    echo "   - output/aggregated_rvn_final_neukoelln.geojson (finale Ergebnisse als GeoJSON)"
    echo "   - output/snapping_network_enriched_neukoelln.fgb (angereichertes Netzwerk als FlatGeoBuf)"
    echo "   - output/snapping_network_enriched_neukoelln.geojson (angereichertes Netzwerk als GeoJSON)"
else
    echo "   - output/aggregated_rvn_final.gpkg (finale Ergebnisse als GeoPackage)"
    echo "   - output/aggregated_rvn_final.geojson (finale Ergebnisse als GeoJSON)"
    echo "   - output/snapping_network_enriched.fgb (angereichertes Netzwerk als FlatGeoBuf)"
    echo "   - output/snapping_network_enriched.geojson (angereichertes Netzwerk als GeoJSON)"
fi
echo "   - output/matched/ (gematchte OSM-Wege)"
echo "   - output-last-run/ (gesicherte Dateien vom vorherigen Lauf)"
echo ""
echo "🔍 Für QA-Zwecke:"
echo "   - Verwende den Inspector: cd inspector && npm run dev"
echo "   - Oder öffne das QGIS Projekt: QGIS QA Processing.qgz"
echo "   - Führe manuelle Tests durch: python testing/run_tests.py [--clip-neukoelln]"
