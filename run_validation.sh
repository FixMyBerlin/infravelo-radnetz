#!/bin/bash
# -*- coding: utf-8 -*-
# run_validation.sh
# ----------------------------------------------------------------
# Führt alle Validierungsskripte im validation/ Ordner aus und
# gibt eine Zusammenfassung der Ergebnisse aus.
#
# Eingabedateien:
# - data/Virtuelle-Knotenpunkte.gpkg (validate_virtuelle_knotenpunkte.py)
# - data-raw-tilda/knotenpunkte_mit_id_und_bezirken.gpkg (validate_knotenpunkte.py)
# - output/snapping_converted_bikelanes*.fgb (validate_datensatz_b.py)
#
# Verwendung:
#   ./run_validation.sh [--clip <region>]
#
# Argumente:
#   --clip <region>     Regionaler Zuschnitt: neukoelln, norden oder sueden
#                       (Wird an validate_datensatz_b.py weitergegeben)
#
# Exit-Codes:
#   0 - Alle Validierungen bestanden
#   1 - Mindestens eine Validierung fehlgeschlagen

set -e  # Script bei Fehlern beenden

# Farben für die Ausgabe
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Argumentverarbeitung
CLIP_REGION=""
CLIP_ARG=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --clip)
            CLIP_REGION="$2"
            CLIP_ARG="--clip $2"
            shift 2
            ;;
        *)
            echo -e "${RED}Unbekanntes Argument: $1${NC}"
            echo "Verwendung: ./run_validation.sh [--clip <region>]"
            exit 1
            ;;
    esac
done

# Validiere clip-Region falls angegeben
if [[ -n "$CLIP_REGION" ]]; then
    if [[ "$CLIP_REGION" != "neukoelln" && "$CLIP_REGION" != "norden" && "$CLIP_REGION" != "sueden" ]]; then
        echo -e "${RED}Ungültige Region: $CLIP_REGION${NC}"
        echo "Erlaubte Regionen: neukoelln, norden, sueden"
        exit 1
    fi
fi

# Arrays für Ergebnisse
declare -a PASSED_VALIDATIONS=()
declare -a FAILED_VALIDATIONS=()

# Python-Executable bestimmen
if [ -f ".venv/bin/python" ]; then
    PYTHON=".venv/bin/python"
else
    PYTHON="python3"
fi

echo ""
echo -e "${BLUE}=================================================================================${NC}"
echo -e "${BLUE}                         VALIDIERUNG STARTEN                                     ${NC}"
echo -e "${BLUE}=================================================================================${NC}"
echo ""

if [[ -n "$CLIP_REGION" ]]; then
    echo -e "${YELLOW}Modus: Regionaler Zuschnitt (${CLIP_REGION})${NC}"
else
    echo -e "${YELLOW}Modus: Vollständiger Datensatz${NC}"
fi
echo ""

# ============================================================================
# Funktion zum Ausführen einer Validierung
# ============================================================================
run_validation() {
    local name="$1"
    local script="$2"
    local args="${3:-}"
    
    echo -e "${BLUE}─────────────────────────────────────────────────────────────────────────────────${NC}"
    echo -e "${BLUE}Validierung: ${name}${NC}"
    echo -e "${BLUE}─────────────────────────────────────────────────────────────────────────────────${NC}"
    echo ""
    
    # Führe das Skript aus und fange den Exit-Code ab
    set +e  # Temporär Fehler nicht abbrechen
    $PYTHON "$script" $args
    local exit_code=$?
    set -e  # Wieder aktivieren
    
    echo ""
    
    if [ $exit_code -eq 0 ]; then
        echo -e "${GREEN}✓ ${name}: BESTANDEN${NC}"
        PASSED_VALIDATIONS+=("$name")
    else
        echo -e "${RED}✗ ${name}: FEHLGESCHLAGEN${NC}"
        FAILED_VALIDATIONS+=("$name")
    fi
    
    echo ""
}

# ============================================================================
# Validierungen ausführen
# ============================================================================

# 1. Virtuelle Knotenpunkte - Eindeutigkeit der Knotenpunkt-IDs
run_validation "Virtuelle Knotenpunkte (Eindeutigkeit)" "validation/validate_virtuelle_knotenpunkte.py"

# 2. TILDA Knotenpunkte - Eindeutigkeit der okstra_id
run_validation "TILDA Knotenpunkte (Eindeutigkeit)" "validation/validate_knotenpunkte.py"

# 3. Datensatz B - NULL-Werte und TODO-Werte
run_validation "Datensatz B (Konvertierte Radverkehrsanlagen)" "validation/validate_datensatz_b.py" "$CLIP_ARG"

# 4. Datensatz C - Aggregierte RVN-Daten
run_validation "Datensatz C (Aggregierte RVN-Daten)" "validation/validate_datensatz_c.py" "$CLIP_ARG"

# ============================================================================
# Zusammenfassung
# ============================================================================
echo ""
echo -e "${BLUE}=================================================================================${NC}"
echo -e "${BLUE}                         ZUSAMMENFASSUNG                                         ${NC}"
echo -e "${BLUE}=================================================================================${NC}"
echo ""

total_passed=${#PASSED_VALIDATIONS[@]}
total_failed=${#FAILED_VALIDATIONS[@]}
total=$((total_passed + total_failed))

echo -e "Validierungen durchgeführt: ${total}"
echo -e "${GREEN}Bestanden: ${total_passed}${NC}"
echo -e "${RED}Fehlgeschlagen: ${total_failed}${NC}"
echo ""

# Liste der bestandenen Validierungen
if [ ${#PASSED_VALIDATIONS[@]} -gt 0 ]; then
    echo -e "${GREEN}Bestandene Validierungen:${NC}"
    for validation in "${PASSED_VALIDATIONS[@]}"; do
        echo -e "  ${GREEN}✓${NC} $validation"
    done
    echo ""
fi

# Liste der fehlgeschlagenen Validierungen
if [ ${#FAILED_VALIDATIONS[@]} -gt 0 ]; then
    echo -e "${RED}Fehlgeschlagene Validierungen:${NC}"
    for validation in "${FAILED_VALIDATIONS[@]}"; do
        echo -e "  ${RED}✗${NC} $validation"
    done
    echo ""
fi

echo -e "${BLUE}=================================================================================${NC}"

# Finales Ergebnis
if [ ${#FAILED_VALIDATIONS[@]} -eq 0 ]; then
    echo -e "${GREEN}✓ ALLE VALIDIERUNGEN BESTANDEN!${NC}"
    echo -e "${BLUE}=================================================================================${NC}"
    exit 0
else
    echo -e "${RED}✗ VALIDIERUNG FEHLGESCHLAGEN: ${total_failed} von ${total} Prüfungen nicht bestanden${NC}"
    echo -e "${BLUE}=================================================================================${NC}"
    exit 1
fi
