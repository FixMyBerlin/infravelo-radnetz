#!/bin/bash
# execute_processing.sh
# 
# Dieses Script führt den gesamten infraVelo Radnetz Verarbeitungsprozess aus.
# Es sichert finale Dateien vom vorherigen Lauf in output-last-run/
#
# Verarbeitungsschritte:
# 1. OSM-Wege mit Radvorrangsnetz matchen
# 2. Snapping und Attribut-Übernahme  
# 3. Schutzstreifen-Konvertierung
# 4. Finale Aggregation
# 5. Qualitätssicherungstests
#
# Dateiverwaltung:
# - Finale Dateien (snapping_converted_bikelanes*, aggregated_rvn_final*) werden in output-last-run/ gesichert
# - Temporäre Dateien werden vor dem entsprechenden Verarbeitungsschritt gelöscht
# - Zwischendateien bleiben zwischen Schritten erhalten (für --start-step Funktionalität)
#
# Verwendung: ./execute_processing.sh [--clip <region> | --view z/lat/lon] [--start-step <1-5>] [--clean-cache]
# 
# Argumente:
#   --clip <region>     Regionaler Zuschnitt: neukoelln, norden oder sueden
#   --view z/lat/lon     Viewport Zuschnitt (WGS84, z.B. 18/52.488306/13.425140) – schreibt nach output-bbox
#   --start-step <1-5>  Startet die Verarbeitung ab dem angegebenen Schritt
#                       1: OSM-Wege Matching
#                       2: Snapping und Attribut-Übernahme
#                       3: Schutzstreifen-Konvertierung
#                       4: Finale Aggregation
#                       5: Qualitätssicherungstests
#   --clean-cache       Vollständige Bereinigung aller Cache-Dateien vor der Verarbeitung
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
CLIP_REGION=""
START_STEP=1
VIEW=""
CLEAN_CACHE=""

# Verarbeite alle Argumente
while [[ $# -gt 0 ]]; do
    case $1 in
        --clip)
            CLIP_REGION="$2"
            shift 2
            ;;
        --start-step)
            START_STEP="$2"
            shift 2
            ;;
        --view)
            VIEW="$2"
            shift 2
            ;;
        --clean-cache)
            CLEAN_CACHE="--clean-cache"
            shift
            ;;
        *)
            echo "❌ Unbekanntes Argument: $1"
            echo "Verwendung: $0 [--clip neukoelln|norden|sueden] [--view z/lat/lon] [--start-step <1-5>] [--clean-cache]"
            exit 1
            ;;
    esac
done

# Validiere START_STEP
if [[ ! "$START_STEP" =~ ^[1-5]$ ]]; then
    echo "❌ Ungültiger Schritt: $START_STEP. Erlaubt sind: 1-5"
    exit 1
fi

# Validiere CLIP_REGION
if [[ -n "$CLIP_REGION" ]]; then
    if [[ ! "$CLIP_REGION" =~ ^(neukoelln|norden|sueden)$ ]]; then
        echo "❌ Ungültige Region: $CLIP_REGION. Erlaubt sind: neukoelln, norden, sueden"
        exit 1
    fi
fi

if [[ -n "$CLIP_REGION" && -n "$VIEW" ]]; then
    echo "❌ --clip und --view dürfen nicht kombiniert werden"
    exit 1
fi
if [[ -n "$CLIP_REGION" ]]; then
    echo "🌍 Verarbeitung wird auf Region $CLIP_REGION beschränkt."
elif [[ -n "$VIEW" ]]; then
    echo "🌍 Verarbeitung mit Viewport $VIEW (output-bbox)"
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
if [[ -n "$CLIP_REGION" ]]; then
    SUFFIX="_${CLIP_REGION}"
elif [[ -n "$VIEW" ]]; then
    SUFFIX="_view"
else
    SUFFIX=""
fi

BASE_OUT_DIR="output"
if [[ -n "$VIEW" && -z "$CLIP_REGION" ]]; then
    BASE_OUT_DIR="output-bbox"
fi
mkdir -p "$BASE_OUT_DIR"

# Zusätzliche Cache-Bereinigung falls --clean-cache gesetzt ist
if [[ -n "$CLEAN_CACHE" ]]; then
    echo "🧹 Vollständige Cache-Bereinigung aktiviert..."
    echo "  - Lösche alle Zwischendateien aus output/ und output-bbox/"
    
    # Bereinige alle Zwischendateien aus beiden Verzeichnissen
    for dir in "output" "output-bbox"; do
        if [ -d "$dir" ]; then
            echo "    Bereinige $dir/..."
            rm -rf $dir/matching/ $dir/matched/ $dir/snapping/ 2>/dev/null || true
            rm -f $dir/snapping_network_enriched*.fgb 2>/dev/null || true
            rm -f $dir/snapping_converted_bikelanes*.fgb 2>/dev/null || true
            rm -f $dir/aggregated_rvn_final*.gpkg 2>/dev/null || true
            rm -f $dir/aggregated_rvn_final*.fgb 2>/dev/null || true
        fi
    done
    
    # Recreate necessary directories
    mkdir -p ${BASE_OUT_DIR}/matching ${BASE_OUT_DIR}/matched ${BASE_OUT_DIR}/snapping
    echo "  ✅ Cache vollständig bereinigt und Verzeichnisse neu erstellt"
fi

# Verschiebe finale Dateien (falls vorhanden)
for f in "snapping_converted_bikelanes${SUFFIX}.fgb" \
                 "snapping_converted_bikelanes${SUFFIX}.geojson" \
                 "aggregated_rvn_final${SUFFIX}.gpkg" \
                 "aggregated_rvn_final${SUFFIX}.fgb" \
                 "aggregated_rvn_final${SUFFIX}.geojson"; do
    if [ -f "${BASE_OUT_DIR}/$f" ]; then
        echo "  - Sichere $f"
        mv "${BASE_OUT_DIR}/$f" output-last-run/ || true
    fi
done

echo "✅ Finale Dateien erfolgreich gesichert."
echo ""

echo "🔄 Starte Verarbeitungsprozess..."

# Schritt 1: Matching
if [[ $START_STEP -le 1 ]]; then
    echo "🧹 Bereinigte temporäre Dateien für Schritt 1..."
    # Lösche Cache- und Zwischendateien aus dem entsprechenden Verzeichnis
    if [ -d "${BASE_OUT_DIR}/matching" ]; then
        rm -f ${BASE_OUT_DIR}/matching/osm_*_in_buffering.fgb
        rm -f ${BASE_OUT_DIR}/matching/osm_*_manual_interventions.fgb
        rm -f ${BASE_OUT_DIR}/matching/osm_*_orthogonal_all_ways.fgb
        rm -f ${BASE_OUT_DIR}/matching/osm_*_orthogonal_removed.fgb
        echo "  - Gelöscht: ${BASE_OUT_DIR}/matching/ Zwischendateien"
    fi
    # Lösche matched Dateien (werden in Schritt 1 erstellt)
    rm -f ${BASE_OUT_DIR}/matched/matched_tilda_*.fgb
    rm -f ${BASE_OUT_DIR}/matched/matched_tilda_*.txt
    echo "  - Gelöscht: ${BASE_OUT_DIR}/matched/ TILDA Dateien"
    
    echo "🔍 Schritt 1/4: OSM-Wege mit Radvorrangsnetz matchen..."
    STEP1_START=$(date +%s)
    if [[ -n "$CLIP_REGION" ]]; then
        ./.venv/bin/python processing/start_matching.py --clip "$CLIP_REGION"
    elif [[ -n "$VIEW" ]]; then
        ./.venv/bin/python processing/start_matching.py --view "$VIEW"
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
    if [ -d "${BASE_OUT_DIR}/snapping" ]; then
        rm -f ${BASE_OUT_DIR}/snapping/rvn-segmented*.fgb
        rm -f ${BASE_OUT_DIR}/snapping/osm_candidates_per_edge*.txt
        echo "  - Gelöscht: ${BASE_OUT_DIR}/snapping/ Zwischendateien"
    fi
    # Lösche snapping_network_enriched Dateien (werden in Schritt 2 erstellt)
    rm -f "${BASE_OUT_DIR}/snapping_network_enriched${SUFFIX}.fgb"
    echo "  - Gelöscht: ${BASE_OUT_DIR}/snapping_network_enriched${SUFFIX}.fgb"
    
    echo "📍 Schritt 2/4: Snapping und Attribut-Übernahme..."
    STEP2_START=$(date +%s)
    if [[ -n "$CLIP_REGION" ]]; then
        ./.venv/bin/python processing/start_snapping.py --clip "$CLIP_REGION"
    elif [[ -n "$VIEW" ]]; then
        ./.venv/bin/python processing/start_snapping.py --view "$VIEW"
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

# Schritt 3: Schutzstreifen-Konvertierung
if [[ $START_STEP -le 3 ]]; then
    echo "🧹 Bereinigte temporäre Dateien für Schritt 3..."
    # Lösche snapping_converted_bikelanes Dateien (werden in Schritt 3 erstellt)
    rm -f "${BASE_OUT_DIR}/snapping_converted_bikelanes${SUFFIX}.fgb"
    echo "  - Gelöscht: ${BASE_OUT_DIR}/snapping_converted_bikelanes${SUFFIX}.fgb"
    
    echo "🚲 Schritt 3/5: Schutzstreifen-Konvertierung..."
    STEP3_START=$(date +%s)
    if [[ -n "$CLIP_REGION" ]]; then
        ./.venv/bin/python processing/start_bikelane_conversion.py --clip "$CLIP_REGION"
    elif [[ -n "$VIEW" ]]; then
        ./.venv/bin/python processing/start_bikelane_conversion.py --view "$VIEW"
    else
        ./.venv/bin/python processing/start_bikelane_conversion.py
    fi
    if [ $? -ne 0 ]; then
        echo "❌ Fehler in Schritt 3: start_bikelane_conversion.py"
        exit 1
    fi
    show_elapsed_time $STEP3_START "Schritt 3"
    echo "✅ Schritt 3 abgeschlossen."
    echo ""
else
    echo "⏭️  Überspringe Schritt 3 (Schutzstreifen-Konvertierung)"
    echo ""
fi

# Schritt 4: Finale Aggregation
if [[ $START_STEP -le 4 ]]; then
    echo "🧹 Bereinigte temporäre Dateien für Schritt 4..."
    # Lösche aggregated_rvn_final Dateien (werden in Schritt 4 erstellt)
    rm -f "${BASE_OUT_DIR}/aggregated_rvn_final${SUFFIX}.gpkg"
    rm -f "${BASE_OUT_DIR}/aggregated_rvn_final${SUFFIX}.fgb"
    echo "  - Gelöscht: ${BASE_OUT_DIR}/aggregated_rvn_final${SUFFIX} Dateien"
    
    echo "🎯 Schritt 4/5: Finale Aggregation..."
    STEP4_START=$(date +%s)
    if [[ -n "$CLIP_NEUKOELLN" ]]; then
        ./.venv/bin/python processing/aggregate_final_model.py --clip-neukoelln --input ./output/snapping_converted_bikelanes_neukoelln.fgb
    elif [[ -n "$VIEW" ]]; then
        ./.venv/bin/python processing/aggregate_final_model.py --view "$VIEW" --input ./output-bbox/snapping_converted_bikelanes_view.fgb
    else
        ./.venv/bin/python processing/aggregate_final_model.py --input ./output/snapping_converted_bikelanes.fgb
    fi
    if [ $? -ne 0 ]; then
        echo "❌ Fehler in Schritt 4: aggregate_final_model.py"
        exit 1
    fi
    show_elapsed_time $STEP4_START "Schritt 4"
    echo "✅ Schritt 4 abgeschlossen."
    echo ""
else
    echo "⏭️  Überspringe Schritt 4 (Finale Aggregation)"
    echo ""
fi

# Schritt 5: Qualitätssicherungstests
# if [[ $START_STEP -le 5 ]]; then
#     if [[ -n "$VIEW" ]]; then
#         echo "🧪 Schritt 5/5: Überspringe Qualitätssicherungstests bei Viewport-Verarbeitung"
#         echo "   ℹ️  Tests werden bei --view Parameter nicht ausgeführt (kleine Datenmenge nicht repräsentativ)"
#         STEP5_START=$(date +%s)
#         STEP5_DURATION=0
#         echo "⏱️  Schritt 5 dauerte: ${STEP5_DURATION}s"
#         echo "✅ Schritt 5 übersprungen."
#     else
#         echo "🧪 Schritt 5/5: Führe Qualitätssicherungstests durch..."
#         STEP5_START=$(date +%s)
        
#         if [[ "$CLIP_NEUKOELLN" == "--clip-neukoelln" ]]; then
#             ./.venv/bin/python testing/run_tests.py --clip-neukoelln
#         else
#             ./.venv/bin/python testing/run_tests.py
#         fi
        
#         if [ $? -ne 0 ]; then
#             echo "❌ Qualitätssicherungstests fehlgeschlagen!"
#             echo "   Die Verarbeitung wurde zwar abgeschlossen, aber die erwarteten"
#             echo "   Attributwerte stimmen nicht mit den Test-Definitionen überein."
#             echo "   Bitte überprüfen Sie die Ausgabe der Tests und die Verarbeitung."
#             # Beende Script mit Fehlercode
#             exit 1
#         fi
        
#         show_elapsed_time $STEP5_START "Schritt 5"
#         echo "✅ Schritt 5 abgeschlossen."
#     fi
#     echo ""
# else
#     echo "⏭️  Überspringe Schritt 5 (Qualitätssicherungstests)"
#     echo ""
# fi
# echo ""

echo "🎉 Verarbeitungsprozess erfolgreich abgeschlossen!"

# Gesamtzeit anzeigen
show_total_time $SCRIPT_START_TIME

echo ""
echo "📁 Ausgabedateien verfügbar in:"
if [[ -n "$CLIP_REGION" ]]; then
    echo "   - output/aggregated_rvn_final_${CLIP_REGION}.gpkg"
    echo "   - output/snapping_converted_bikelanes_${CLIP_REGION}.fgb"
elif [[ -n "$VIEW" ]]; then
    echo "   - output-bbox/aggregated_rvn_final_view.gpkg"
    echo "   - output-bbox/snapping_converted_bikelanes_view.fgb"
else
    echo "   - output/aggregated_rvn_final.gpkg"
    echo "   - output/snapping_converted_bikelanes.fgb"
fi
echo "   - output/matched/ (gematchte OSM-Wege)"
echo "   - output-last-run/ (gesicherte Dateien vom vorherigen Lauf)"
echo ""
echo "🔍 Für QA-Zwecke:"
echo "   - Verwende den Inspector: cd inspector && npm run dev"
echo "   - Oder öffne das QGIS Projekt: QGIS QA Processing.qgz"
echo "   - Führe manuelle Tests durch: python testing/run_tests.py [--clip-neukoelln]"
