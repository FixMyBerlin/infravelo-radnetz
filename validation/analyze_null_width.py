#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze_null_width.py
--------------------------------------------------------------------
Analysiert den Snapping-Datensatz auf Segmente mit breite=NULL.

Prüft:
1. Ob es Segmente mit breite=NULL gibt, die NICHT in FUEHR_WITHOUT_WIDTH_REQUIREMENT sind
2. Gibt die Anzahl pro Führungsform zurück, wo breite=NULL ist
"""

import sys
from pathlib import Path
import geopandas as gpd
import pandas as pd

# Füge processing-Verzeichnis zum Python-Pfad hinzu
script_dir = Path(__file__).parent
processing_dir = script_dir.parent / "processing"
sys.path.insert(0, str(processing_dir))

# Importiere die FUEHR_WITHOUT_WIDTH_REQUIREMENT Liste aus start_snapping.py
from start_snapping import FUEHR_WITHOUT_WIDTH_REQUIREMENT

# Pfad zum Snapping-Datensatz
SNAPPING_FILE = script_dir.parent / "output" / "snapping_network_enriched.fgb"

def main():
    print("=" * 80)
    print("ANALYSE: Segmente mit breite=NULL")
    print("=" * 80)
    
    # Prüfe ob Datei existiert
    if not SNAPPING_FILE.exists():
        print(f"❌ FEHLER: Snapping-Datensatz nicht gefunden: {SNAPPING_FILE}")
        print("\nAlternative Dateien:")
        output_dir = SNAPPING_FILE.parent
        if output_dir.exists():
            for file in output_dir.glob("snapping_network_enriched*.fgb"):
                print(f"  - {file.name}")
        return 1
    
    print(f"\n📂 Lade Datensatz: {SNAPPING_FILE.name}")
    gdf = gpd.read_file(SNAPPING_FILE)
    
    total_segments = len(gdf)
    print(f"   Gesamt Segmente: {total_segments:,}")
    
    # Filtere Segmente mit breite=NULL
    null_width_mask = gdf['breite'].isna() | gdf['breite'].isnull()
    null_width_segments = gdf[null_width_mask].copy()
    
    total_null_width = len(null_width_segments)
    print(f"\n📊 Segmente mit breite=NULL: {total_null_width:,} ({total_null_width/total_segments*100:.2f}%)")
    
    if total_null_width == 0:
        print("\n✅ ERGEBNIS: Keine Segmente mit breite=NULL gefunden!")
        return 0
    
    # Analysiere nach Führungsform
    print("\n" + "=" * 80)
    print("VERTEILUNG NACH FÜHRUNGSFORM (breite=NULL)")
    print("=" * 80)
    
    fuehr_counts = null_width_segments['fuehr'].value_counts()
    
    # Sortiere nach Anzahl (absteigend)
    fuehr_counts_sorted = fuehr_counts.sort_values(ascending=False)
    
    print(f"\n{'Führungsform':<70} {'Anzahl':>8}")
    print("-" * 80)
    
    total_in_exception_list = 0
    total_not_in_exception_list = 0
    
    for fuehr, count in fuehr_counts_sorted.items():
        in_exception_list = fuehr in FUEHR_WITHOUT_WIDTH_REQUIREMENT
        marker = "✓" if in_exception_list else "⚠️"
        
        if in_exception_list:
            total_in_exception_list += count
        else:
            total_not_in_exception_list += count
        
        fuehr_display = fuehr if fuehr else "(None)"
        print(f"{marker} {fuehr_display:<68} {count:>7,}")
    
    print("-" * 80)
    print(f"{'GESAMT':<70} {total_null_width:>7,}")
    
    # Zusammenfassung
    print("\n" + "=" * 80)
    print("ZUSAMMENFASSUNG")
    print("=" * 80)
    
    print(f"\n✓ In FUEHR_WITHOUT_WIDTH_REQUIREMENT:     {total_in_exception_list:>7,} ({total_in_exception_list/total_null_width*100:.2f}%)")
    print(f"⚠️ NICHT in FUEHR_WITHOUT_WIDTH_REQUIREMENT: {total_not_in_exception_list:>7,} ({total_not_in_exception_list/total_null_width*100:.2f}%)")
    
    # Detaillierte Auflistung der problematischen Fälle
    if total_not_in_exception_list > 0:
        print("\n" + "=" * 80)
        print("⚠️  PROBLEMATISCHE FÜHRUNGSFORMEN (nicht in Ausnahmeliste)")
        print("=" * 80)
        
        problematic = null_width_segments[~null_width_segments['fuehr'].isin(FUEHR_WITHOUT_WIDTH_REQUIREMENT)]
        problematic_counts = problematic['fuehr'].value_counts()
        
        for fuehr, count in problematic_counts.items():
            fuehr_display = fuehr if fuehr else "(None)"
            print(f"\n{fuehr_display}: {count:,} Segment(e)")
            
            # Zeige bis zu 5 Beispiel-Segmente
            examples = problematic[problematic['fuehr'] == fuehr].head(5)
            for idx, row in examples.iterrows():
                element_nr = row.get('element_nr', 'unknown')
                ri = row.get('ri', 'unknown')
                strassenname = row.get('strassenname', 'unknown')
                print(f"  - element_nr={element_nr}, ri={ri}, Straße={strassenname}")
            
            if len(problematic[problematic['fuehr'] == fuehr]) > 5:
                remaining = len(problematic[problematic['fuehr'] == fuehr]) - 5
                print(f"  ... und {remaining} weitere")
        
        print("\n" + "=" * 80)
        print("❌ FAZIT: Es gibt Segmente mit breite=NULL außerhalb der Ausnahmeliste!")
        print("=" * 80)
        return 1
    else:
        print("\n" + "=" * 80)
        print("✅ FAZIT: Alle Segmente mit breite=NULL sind in FUEHR_WITHOUT_WIDTH_REQUIREMENT!")
        print("=" * 80)
        return 0

if __name__ == "__main__":
    sys.exit(main())
