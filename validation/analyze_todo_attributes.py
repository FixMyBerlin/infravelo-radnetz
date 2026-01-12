#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze_todo_attributes.py
--------------------------------------------------------------------
Analysiert den Snapping-Datensatz auf Segmente mit TODO-Werten in Attributen.

Prüft:
1. Anzahl der Segmente pro Führungsform, die mindestens ein TODO in einem Attribut haben
2. Detaillierte Aufschlüsselung welche Attribute TODO-Werte enthalten
3. Beispiele für betroffene Segmente
"""

import sys
from pathlib import Path
import geopandas as gpd
import pandas as pd

# ANSI Farb-Codes
ORANGE = '\033[38;5;214m'
RED = '\033[91m'
RESET = '\033[0m'

# Füge processing-Verzeichnis zum Python-Pfad hinzu
script_dir = Path(__file__).parent
processing_dir = script_dir.parent / "processing"
sys.path.insert(0, str(processing_dir))

# Importiere die Attributlisten aus start_snapping.py
from start_snapping import FINAL_DATASET_SEGMENT_MERGE_ATTRIBUTES, FINAL_DATASET_SEGMENT_ADDITIONAL_ATTRIBUTES

# Pfad zum Snapping-Datensatz
SNAPPING_FILE = script_dir.parent / "output" / "snapping_network_enriched.fgb"

# Attribute die auf TODO geprüft werden sollen (hauptsächlich die Merge-Attribute)
ATTRIBUTES_TO_CHECK = [
    'fuehr', 'ofm', 'protek', 'pflicht', 'breite', 'farbe', 
    'trennstreifen', 'nutz_beschr', 'Kommentar'
]

def contains_todo(value):
    """Prüft ob ein Wert TODO enthält (case-insensitive)."""
    if pd.isna(value) or value is None:
        return False
    return 'TODO' in str(value).upper()

def main():
    print("=" * 80)
    print("ANALYSE: Segmente mit TODO-Werten in Attributen")
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
    
    # Erstelle eine Maske für Segmente mit mindestens einem TODO
    has_todo_mask = pd.Series([False] * len(gdf), index=gdf.index)
    
    # Dictionary um zu tracken welche Attribute TODO enthalten
    todo_by_attribute = {attr: [] for attr in ATTRIBUTES_TO_CHECK}
    
    for attr in ATTRIBUTES_TO_CHECK:
        if attr in gdf.columns:
            attr_has_todo = gdf[attr].apply(contains_todo)
            has_todo_mask |= attr_has_todo
            
            # Speichere Indices für dieses Attribut
            todo_indices = gdf[attr_has_todo].index.tolist()
            todo_by_attribute[attr] = todo_indices
    
    todo_segments = gdf[has_todo_mask].copy()
    total_todo = len(todo_segments)
    
    print(f"\n📊 Segmente mit TODO: {total_todo:,} ({total_todo/total_segments*100:.2f}%)")
    
    if total_todo == 0:
        print("\n✅ ERGEBNIS: Keine Segmente mit TODO-Werten gefunden!")
        return 0
    
    # Analysiere nach Führungsform
    print("\n" + "=" * 80)
    print("VERTEILUNG NACH FÜHRUNGSFORM (mit TODO)")
    print("=" * 80)
    
    fuehr_counts = todo_segments['fuehr'].value_counts()
    fuehr_counts_sorted = fuehr_counts.sort_values(ascending=False)
    
    print(f"\n{'Führungsform':<70} {'Anzahl':>8}")
    print("-" * 80)
    
    for fuehr, count in fuehr_counts_sorted.items():
        fuehr_display = fuehr if fuehr else "(None)"
        percentage = count / total_todo * 100
        print(f"{fuehr_display:<70} {count:>7,} ({percentage:>5.1f}%)")
    
    print("-" * 80)
    print(f"{'GESAMT':<70} {total_todo:>7,}")
    
    # Detaillierte Attribut-Analyse
    print("\n" + "=" * 80)
    print("TODO-WERTE PRO ATTRIBUT")
    print("=" * 80)
    
    print(f"\n{'Attribut':<30} {'Anzahl Segmente':>20} {'% von allen TODO':>20}")
    print("-" * 80)
    
    for attr in ATTRIBUTES_TO_CHECK:
        if attr in gdf.columns:
            todo_count = len(todo_by_attribute[attr])
            if todo_count > 0:
                percentage = todo_count / total_todo * 100
                print(f"{attr:<30} {todo_count:>19,} {percentage:>19.1f}%")
    
    # Detaillierte Analyse pro Führungsform
    print("\n" + "=" * 80)
    print("DETAILLIERTE ANALYSE PRO FÜHRUNGSFORM")
    print("=" * 80)
    
    for fuehr in fuehr_counts_sorted.index[:10]:  # Top 10 Führungsformen
        fuehr_segments = todo_segments[todo_segments['fuehr'] == fuehr]
        fuehr_display = fuehr if fuehr else "(None)"
        
        print(f"\n{'─' * 80}")
        print(f"📋 {fuehr_display}")
        print(f"   Gesamt: {len(fuehr_segments):,} Segment(e)")
        print(f"{'─' * 80}")
        
        # Zähle TODO pro Attribut für diese Führungsform
        attr_todos = {}
        for attr in ATTRIBUTES_TO_CHECK:
            if attr in fuehr_segments.columns:
                count = fuehr_segments[attr].apply(contains_todo).sum()
                if count > 0:
                    attr_todos[attr] = count
        
        if attr_todos:
            print(f"\n   TODO in Attributen:")
            for attr, count in sorted(attr_todos.items(), key=lambda x: x[1], reverse=True):
                print(f"     • {attr:<25} {count:>5,} Segment(e)")
        
        # Zeige bis zu 3 Beispiel-Segmente
        examples = fuehr_segments.head(3)
        print(f"\n   Beispiele:")
        for idx, row in examples.iterrows():
            element_nr = row.get('element_nr', 'unknown')
            ri = row.get('ri', 'unknown')
            strassenname = row.get('strassenname', 'unknown')
            
            # Finde welche Attribute TODO enthalten
            todo_attrs = []
            for attr in ATTRIBUTES_TO_CHECK:
                if attr in row.index and contains_todo(row[attr]):
                    todo_attrs.append(f"{attr}={row[attr]}")
            
            print(f"     • element_nr={element_nr}, ri={ri}")
            print(f"       Straße: {strassenname}")
            if todo_attrs:
                print(f"       TODOs: {'; '.join(todo_attrs[:3])}")
                if len(todo_attrs) > 3:
                    print(f"              ... und {len(todo_attrs) - 3} weitere")
    
    # Zusammenfassung
    print("\n" + "=" * 80)
    print("ZUSAMMENFASSUNG")
    print("=" * 80)
    
    print(f"\n📊 Segmente mit TODO-Werten:")
    print(f"   Gesamt: {total_todo:,} von {total_segments:,} ({total_todo/total_segments*100:.1f}%)")
    print(f"\n📋 Betroffene Führungsformen: {len(fuehr_counts)}")
    print(f"🔧 Betroffene Attribute: {sum(1 for attr, indices in todo_by_attribute.items() if len(indices) > 0)}")
    
    if total_todo > 0:
        print("\n" + "=" * 80)
        print("⚠️  HINWEIS: Es gibt noch TODO-Werte in den Daten!")
        print("=" * 80)
        return 1
    else:
        print("\n" + "=" * 80)
        print("✅ FAZIT: Keine TODO-Werte gefunden!")
        print("=" * 80)
        return 0

if __name__ == "__main__":
    sys.exit(main())
