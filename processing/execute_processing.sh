#!/bin/bash
# execute_processing.sh
# 
# Dieses Script führt den gesamten infraVelo Radnetz Verarbeitungsprozess für Neukölln aus.
# Es löscht temporäre/zwischengespeicherte Dateien und führt dann alle Prozessierungsschritte in der richtigen Reihenfolge durch.
# Am Ende werden die finalen Ergebnisse zusätzlich als GeoJSON-Dateien exportiert.
#
# Verarbeitungsschritte:
# 1. TILDA Attribut-Übersetzung
# 2. OSM-Wege mit Radvorrangsnetz matchen
# 3. Snapping und Attribut-Übernahme  
# 4. Finale Aggregation
# 5. GeoJSON-Konvertierung (für TILDA Static Data)
#
# Verwendung: ./execute_processing.sh
# 
# Voraussetzung: Python venv ist bereits erstellt und requirements.txt wurde installiert

set -e  # Script bei Fehlern beenden

echo "🚀 Starte infraVelo Radnetz Verarbeitungsprozess..."

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

echo "🧹 Lösche temporäre und zwischengespeicherte Dateien..."

# Lösche Cache- und Zwischendateien aus output/matching/
if [ -d "output/matching" ]; then
    echo "  - Lösche Buffer-Cache und orthogonale Filter-Dateien..."
    rm -f output/matching/osm_*_in_buffering.fgb
    rm -f output/matching/osm_*_manual_interventions.fgb
    rm -f output/matching/osm_*_orthogonal_all_ways.fgb
    rm -f output/matching/osm_*_orthogonal_removed.fgb
fi

# Lösche Snapping Zwischendateien
if [ -d "output/snapping" ]; then
    echo "  - Lösche segmentierte Netzwerk-Dateien..."
    rm -f output/snapping/rvn-segmented-attributed*.fgb
    rm -f output/snapping/osm_candidates_per_edge*.txt
fi

# Lösche finale Ausgabedateien um sauberen Neustart zu gewährleisten  
echo "  - Lösche finale Ausgabedateien..."
rm -f output/snapping_network_enriched*.fgb
rm -f output/snapping_network_enriched*.geojson
rm -f output/aggregated_rvn_final*.gpkg
rm -f output/aggregated_rvn_final*.fgb
rm -f output/aggregated_rvn_final*.geojson

echo "✅ Temporäre Dateien erfolgreich gelöscht."
echo ""

echo "🔄 Starte Verarbeitungsprozess..."

# Schritt 1: TILDA Attribut-Übersetzung
echo "📝 Schritt 1/5: TILDA Attribute übersetzen..."
./.venv/bin/python processing/translate_attributes_tilda_to_rvn.py --clip-neukoelln
if [ $? -ne 0 ]; then
    echo "❌ Fehler in Schritt 1: translate_attributes_tilda_to_rvn.py"
    exit 1
fi
echo "✅ Schritt 1 abgeschlossen."
echo ""

# Schritt 2: Matching
echo "🔍 Schritt 2/5: OSM-Wege mit Radvorrangsnetz matchen..."
./.venv/bin/python processing/start_matching.py --clip-neukoelln
if [ $? -ne 0 ]; then
    echo "❌ Fehler in Schritt 2: start_matching.py"
    exit 1
fi
echo "✅ Schritt 2 abgeschlossen."
echo ""

# Schritt 3: Snapping
echo "📍 Schritt 3/5: Snapping und Attribut-Übernahme..."
./.venv/bin/python processing/start_snapping.py --clip-neukoelln
if [ $? -ne 0 ]; then
    echo "❌ Fehler in Schritt 3: start_snapping.py"
    exit 1
fi
echo "✅ Schritt 3 abgeschlossen."
echo ""

# Schritt 4: Finale Aggregation
echo "🎯 Schritt 4/5: Finale Aggregation..."
./.venv/bin/python processing/aggregate_final_model.py --input ./output/snapping_network_enriched_neukoelln.fgb
if [ $? -ne 0 ]; then
    echo "❌ Fehler in Schritt 4: aggregate_final_model.py"
    exit 1
fi
echo "✅ Schritt 4 abgeschlossen."
echo ""

# # Schritt 5: GeoJSON-Konvertierung
# echo "🗺️  Schritt 5/5: Konvertiere finale Ergebnisse zu GeoJSON..."

# # Konvertiere aggregierte Ergebnisse (GeoPackage mit zwei Layern)
# echo "  📦 Konvertiere aggregated_rvn_final.gpkg..."
# ./.venv/bin/python scripts/convert_to_geojson.py --input ./output/aggregated_rvn_final_neukoelln.gpkg
# if [ $? -ne 0 ]; then
#     echo "❌ Fehler bei der Konvertierung von aggregated_rvn_final_neukoelln.gpkg"
#     exit 1
# fi

# # Konvertiere angereichertes Netzwerk (FlatGeoBuf)
# echo "  📍 Konvertiere snapping_network_enriched_neukoelln.fgb..."
# ./.venv/bin/python scripts/convert_to_geojson.py --input ./output/snapping_network_enriched_neukoelln.fgb
# if [ $? -ne 0 ]; then
#     echo "❌ Fehler bei der Konvertierung von snapping_network_enriched_neukoelln.fgb"
#     exit 1
# fi

# # Konvertiere gematchte TILDA Ways (FlatGeoBuf)
# echo "  🛣️  Konvertiere matched_tilda_ways.fgb..."
# ./.venv/bin/python scripts/convert_to_geojson.py --input ./output/matched/matched_tilda_ways.fgb --output ./output/matched_tilda_ways.geojson
# if [ $? -ne 0 ]; then
#     echo "❌ Fehler bei der Konvertierung von matched_tilda_ways.fgb"
#     exit 1
# fi

echo "✅ Schritt 5 abgeschlossen."
echo ""

echo "🎉 Verarbeitungsprozess erfolgreich abgeschlossen!"
echo ""
echo "📁 Ausgabedateien verfügbar in:"
echo "   - output/aggregated_rvn_final_neukoelln.gpkg (finale Ergebnisse als GeoPackage)"
echo "   - output/aggregated_rvn_final_neukoelln.geojson (finale Ergebnisse als GeoJSON)"
echo "   - output/snapping_network_enriched_neukoelln.fgb (angereichertes Netzwerk als FlatGeoBuf)"
echo "   - output/snapping_network_enriched_neukoelln.geojson (angereichertes Netzwerk als GeoJSON)"
echo "   - output/matched/ (gematchte OSM-Wege)"
echo ""
echo "🔍 Für QA-Zwecke:"
echo "   - Verwende den Inspector: cd inspector && npm run dev"
echo "   - Oder öffne das QGIS Projekt: QGIS QA Processing.qgz"
