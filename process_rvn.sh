#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# RVN-Verarbeitung: Radvorrangsnetz vorbereiten
# =============================================================================
# Dieses Skript führt die drei wichtigen RVN-Vorverarbeitungsschritte aus:
# 1. Virtuelle Knotenpunkte verarbeiten
# 2. Element-Nummern zuweisen
# 3. RVN mit Detailnetz anreichern
# =============================================================================

echo "🛤️  RVN-Verarbeitung gestartet..."
echo ""

# Farben für die Ausgabe
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 1. Virtuelle Knotenpunkte verarbeiten
echo -e "${BLUE}[1/3]${NC} Virtuelle Knotenpunkte verarbeiten..."
python scripts/split_rvn_at_virtual_nodes.py
echo -e "${GREEN}✓${NC} Virtuelle Knotenpunkte verarbeitet"
echo ""

# 2. Element-Nummern zuweisen
echo -e "${BLUE}[2/3]${NC} Element-Nummern zuweisen..."
python scripts/assign_element_nr_to_rvn.py
echo -e "${GREEN}✓${NC} Element-Nummern zugewiesen"
echo ""

# 3. RVN mit Detailnetz anreichern
echo -e "${BLUE}[3/3]${NC} RVN mit Detailnetz anreichern..."
python scripts/enrich_rvn_with_detailnetz.py
echo -e "${GREEN}✓${NC} RVN mit Detailnetz angereichert"
echo ""

echo "🎉 RVN-Verarbeitung abgeschlossen!"
echo ""
echo "Nächster Schritt: ./execute_processing.sh"
