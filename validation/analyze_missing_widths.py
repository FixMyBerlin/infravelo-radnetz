#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze_missing_widths.py
--------------------------------------------------------------------
Analysiert "Sonstige Wege" ohne Breite in den Snapping-Daten und exportiert
die zugehörigen originalen TILDA-Wege.

Prüft:
1. Findet alle Wege mit Führungsform "Sonstige Wege (Gehwege, Wege durch Grünflächen, Plätze)"
2. Filtert davon diejenigen ohne Breite (breite=NULL oder breite='Breite fehlt')
3. Extrahiert die tilda_id dieser Segmente
4. Lädt die originalen TILDA-Wege aus matched_tilda_ways.fgb
5. Exportiert die entsprechenden TILDA-Wege als tilda_missing_widths_sonstige_wege.fgb
"""

import sys
from pathlib import Path
import geopandas as gpd
import pandas as pd

# Pfade
script_dir = Path(__file__).parent
output_dir = script_dir.parent / "output"
analysis_dir = output_dir / "analysis"

SNAPPING_FILE = output_dir / "snapping_network_enriched.fgb"
MATCHED_TILDA_FILE = output_dir / "matched" / "matched_tilda_ways.fgb"
OUTPUT_FILE = analysis_dir / "tilda_missing_widths_sonstige_wege.fgb"

# Führungsform für "Sonstige Wege"
FUEHR_SONSTIGE_WEGE = "Sonstige Wege (Gehwege, Wege durch Grünflächen, Plätze)"

def main():
    print("=" * 80)
    print("ANALYSE: Fehlende Breiten bei 'Sonstige Wege'")
    print("=" * 80)
    
    # Prüfe ob Dateien existieren
    if not SNAPPING_FILE.exists():
        print(f"❌ FEHLER: Snapping-Datensatz nicht gefunden: {SNAPPING_FILE}")
        return 1
    
    if not MATCHED_TILDA_FILE.exists():
        print(f"❌ FEHLER: Matched TILDA-Datensatz nicht gefunden: {MATCHED_TILDA_FILE}")
        return 1
    
    # Erstelle analysis-Verzeichnis falls nicht vorhanden
    analysis_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"\n📂 Lade Snapping-Datensatz: {SNAPPING_FILE.name}")
    snapping_gdf = gpd.read_file(SNAPPING_FILE)
    
    total_segments = len(snapping_gdf)
    print(f"   Gesamt Segmente: {total_segments:,}")
    
    # Filtere "Sonstige Wege"
    sonstige_mask = snapping_gdf['fuehr'] == FUEHR_SONSTIGE_WEGE
    sonstige_gdf = snapping_gdf[sonstige_mask].copy()
    
    total_sonstige = len(sonstige_gdf)
    print(f"\n📊 Segmente mit '{FUEHR_SONSTIGE_WEGE}': {total_sonstige:,} ({total_sonstige/total_segments*100:.2f}%)")
    
    if total_sonstige == 0:
        print("\n✅ ERGEBNIS: Keine 'Sonstige Wege' gefunden!")
        return 0
    
    # Filtere davon diejenigen ohne Breite
    # breite=NULL oder breite='Breite fehlt'
    no_width_mask = (
        sonstige_gdf['breite'].isna() | 
        sonstige_gdf['breite'].isnull() | 
        (sonstige_gdf['breite'] == 'Breite fehlt')
    )
    no_width_gdf = sonstige_gdf[no_width_mask].copy()
    
    total_no_width = len(no_width_gdf)
    print(f"   davon ohne Breite: {total_no_width:,} ({total_no_width/total_sonstige*100:.2f}%)")
    
    if total_no_width == 0:
        print("\n✅ ERGEBNIS: Alle 'Sonstige Wege' haben eine Breite!")
        return 0
    
    # Extrahiere tilda_id
    print(f"\n🔍 Extrahiere tilda_id aus Snapping-Daten...")
    tilda_ids = no_width_gdf['tilda_id'].dropna().unique()
    
    total_tilda_ids = len(tilda_ids)
    print(f"   Gefundene eindeutige tilda_ids: {total_tilda_ids:,}")
    
    if total_tilda_ids == 0:
        print("\n⚠️  WARNUNG: Keine tilda_id in den Snapping-Daten gefunden!")
        print("   Möglicherweise haben diese Segmente keinen TILDA-Match.")
        return 0
    
    # Lade matched TILDA-Wege
    print(f"\n📂 Lade TILDA-Wege: {MATCHED_TILDA_FILE.name}")
    tilda_gdf = gpd.read_file(MATCHED_TILDA_FILE)
    
    total_tilda_ways = len(tilda_gdf)
    print(f"   Gesamt TILDA-Wege: {total_tilda_ways:,}")
    
    # Stelle sicher, dass die ID-Spalte existiert
    # In matched_tilda_ways.fgb sollte die ID-Spalte 'id' heißen
    id_column = None
    for col in ['id', 'tilda_id', 'osm_id', 'fid']:
        if col in tilda_gdf.columns:
            id_column = col
            break
    
    if id_column is None:
        print(f"\n❌ FEHLER: Keine ID-Spalte in {MATCHED_TILDA_FILE.name} gefunden!")
        print(f"   Verfügbare Spalten: {list(tilda_gdf.columns)}")
        return 1
    
    print(f"   Verwende ID-Spalte: '{id_column}'")
    
    # Filtere TILDA-Wege basierend auf tilda_ids
    # Die tilda_id im Snapping-Datensatz könnte ein Format wie "way/123456" haben
    # In matched_tilda_ways könnte es nur "way/123456" oder eine numerische ID sein
    print(f"\n🔍 Filtere TILDA-Wege basierend auf tilda_ids...")
    
    # Erstelle eine Liste der IDs zum Filtern
    # Falls tilda_ids bereits im richtigen Format sind
    filtered_tilda_gdf = tilda_gdf[tilda_gdf[id_column].isin(tilda_ids)].copy()
    
    total_filtered = len(filtered_tilda_gdf)
    print(f"   Gefilterte TILDA-Wege: {total_filtered:,}")
    
    if total_filtered == 0:
        print("\n⚠️  WARNUNG: Keine übereinstimmenden TILDA-Wege gefunden!")
        print("   Möglicherweise stimmt das ID-Format nicht überein.")
        
        # Zeige Beispiel-IDs zur Diagnose
        print(f"\n   Beispiel tilda_ids aus Snapping-Daten (erste 5):")
        for tid in list(tilda_ids)[:5]:
            print(f"     - {tid}")
        
        print(f"\n   Beispiel IDs aus TILDA-Daten (erste 5):")
        for tid in tilda_gdf[id_column].head(5):
            print(f"     - {tid}")
        
        return 1
    
    # Exportiere gefilterte TILDA-Wege
    print(f"\n💾 Exportiere TILDA-Wege nach: {OUTPUT_FILE.name}")
    filtered_tilda_gdf.to_file(OUTPUT_FILE, driver="FlatGeobuf")
    
    print(f"\n✅ Export erfolgreich!")
    print(f"   Datei: {OUTPUT_FILE}")
    print(f"   Anzahl Features: {total_filtered:,}")
    
    # Statistik
    print("\n" + "=" * 80)
    print("ZUSAMMENFASSUNG")
    print("=" * 80)
    print(f"\nSegmente mit '{FUEHR_SONSTIGE_WEGE}' ohne Breite: {total_no_width:,}")
    print(f"Eindeutige tilda_ids: {total_tilda_ids:,}")
    print(f"Exportierte TILDA-Wege: {total_filtered:,}")
    
    # Zeige einige Beispiele
    print("\n" + "=" * 80)
    print("BEISPIELE (erste 10 TILDA-Wege)")
    print("=" * 80)
    
    for idx, (_, row) in enumerate(filtered_tilda_gdf.head(10).iterrows(), 1):
        row_id = row.get(id_column, 'unknown')
        
        # Versuche zusätzliche Informationen zu finden
        fuehr = row.get('fuehr', 'N/A')
        width = row.get('width', row.get('breite', 'N/A'))
        name = row.get('name', row.get('tilda_name', 'N/A'))
        
        print(f"\n{idx}. {id_column}={row_id}")
        print(f"   Name: {name}")
        print(f"   Führung: {fuehr}")
        print(f"   Breite: {width}")
    
    if total_filtered > 10:
        print(f"\n   ... und {total_filtered - 10} weitere")
    
    print("\n" + "=" * 80)
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
