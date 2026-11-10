#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# Netz-Verarbeitung: Zielnetz (Radvorrangnetz oder REN+) vorbereiten
# =============================================================================
# Dieses Skript führt die drei Vorverarbeitungsschritte des Zielnetzes aus:
# 1. Virtuelle Knotenpunkte verarbeiten
# 2. Element-Nummern zuweisen
# 3. Zielnetz mit Detailnetz anreichern
#
# Verwendung: ./process_radnetz.sh [--netz rvn|ren] [--quelle auto|korrigiert|original]
#   --netz rvn  Radvorrangnetz (Standard), Ausgabe in output/rvn/
#   --netz ren  REN+, alle Netzquellen gemeinsam (ren-network/output/ren_netz_gesamt.gpkg),
#               Ausgabe in output/ren/
#   --quelle    Nur für ren: Eingangsnetz. auto (Standard) nimmt ren_netz_gesamt_korrigiert.gpkg
#               (App Netzanpassungen, ren-network/import_app_export.py), wenn die Datei existiert,
#               sonst das Original. korrigiert bricht ohne die Datei ab, original ignoriert sie.
# =============================================================================

# Alle Pfade sind relativ zu processing/
cd "$(dirname "$0")"
PYTHON="$(cd .. && pwd)/.venv/bin/python"

NETZ="rvn"
QUELLE="auto"
while [[ $# -gt 0 ]]; do
    case $1 in
        --netz)
            NETZ="$2"
            shift 2
            ;;
        --quelle)
            QUELLE="$2"
            shift 2
            ;;
        *)
            echo "❌ Unbekanntes Argument: $1 (erlaubt: --netz rvn|ren, --quelle auto|korrigiert|original)"
            exit 1
            ;;
    esac
done
if [[ ! "$NETZ" =~ ^(rvn|ren)$ ]]; then
    echo "❌ Ungültiges Netz: $NETZ. Erlaubt sind: rvn, ren"
    exit 1
fi
if [[ ! "$QUELLE" =~ ^(auto|korrigiert|original)$ ]]; then
    echo "❌ Ungültige Quelle: $QUELLE. Erlaubt sind: auto, korrigiert, original"
    exit 1
fi

echo "🛤️  Netz-Verarbeitung gestartet (Netz: $NETZ)..."
echo ""

# Farben für die Ausgabe
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 1. Virtuelle Knotenpunkte verarbeiten
echo -e "${BLUE}[1/3]${NC} Virtuelle Knotenpunkte verarbeiten..."
"$PYTHON" scripts/split_rvn_at_virtual_nodes.py --netz "$NETZ" --quelle "$QUELLE"
echo -e "${GREEN}✓${NC} Virtuelle Knotenpunkte verarbeitet"
echo ""

# 2. Element-Nummern zuweisen
echo -e "${BLUE}[2/3]${NC} Element-Nummern zuweisen..."
"$PYTHON" scripts/assign_element_nr_to_rvn.py --netz "$NETZ"
echo -e "${GREEN}✓${NC} Element-Nummern zugewiesen"
echo ""

# 3. Zielnetz mit Detailnetz anreichern
echo -e "${BLUE}[3/3]${NC} Zielnetz mit Detailnetz anreichern..."
"$PYTHON" scripts/enrich_rvn_with_detailnetz.py --netz "$NETZ"
echo -e "${GREEN}✓${NC} Zielnetz mit Detailnetz angereichert"
echo ""

echo "🎉 Netz-Verarbeitung abgeschlossen!"
echo ""
echo "Nächster Schritt: ./execute_processing.sh --netz $NETZ"
