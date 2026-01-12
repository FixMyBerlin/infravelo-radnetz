#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze_missing_widths.py
--------------------------------------------------------------------
Analysiert Radinfrastruktur ohne Breite in den Snapping-Daten und exportiert
die zugehörigen originalen TILDA-Wege.

Prüft:
1. Findet alle Wege mit konfigurierten Führungsformen
2. Schließt temporäre Markierungen und Baustellen aus (Kommentar-Feld)
3. Filtert davon diejenigen ohne Breite (breite=NULL oder breite='Breite fehlt')
4. Extrahiert die tilda_id dieser Segmente
5. Lädt die originalen TILDA-Wege aus matched_tilda_ways.fgb
6. Exportiert die entsprechenden TILDA-Wege als tilda_missing_widths.fgb
"""

import sys
from pathlib import Path
import geopandas as gpd
import pandas as pd

# ANSI Farb-Codes
ORANGE = '\033[38;5;214m'
RED = '\033[91m'
RESET = '\033[0m'

# =============================================================================
# KONFIGURATION
# =============================================================================

# Führungsformen, die analysiert werden sollen
FUEHRUNGSFORMEN = [
    "Sonstige Wege (Gehwege, Wege durch Grünflächen, Plätze)",
    "Radweg",
    "Gehweg mit Zusatzzeichen \"Radverkehr frei\" (Z239 mit Z1022-10)",
    "Schutzstreifen",
    "Radfahrstreifen",
]

# Ausschlussbegriffe für Kommentar-Feld (case-insensitiv)
KOMMENTAR_AUSSCHLUSS = [
    "temporär",
    "baustelle",
]

# =============================================================================
# PFADE
# =============================================================================

script_dir = Path(__file__).parent
output_dir = script_dir.parent / "output"
analysis_dir = output_dir / "analysis"

SNAPPING_FILE = output_dir / "snapping_network_enriched.fgb"
MATCHED_TILDA_FILE = output_dir / "matched" / "matched_tilda_ways.fgb"
OUTPUT_FILE = analysis_dir / "tilda_missing_widths.geojson"

def main():
    print("=" * 80)
    print("ANALYSE: Fehlende Breiten bei Radinfrastruktur")
    print("=" * 80)
    
    # Zeige Konfiguration
    print("\n📋 Konfiguration:")
    print(f"   Analysierte Führungsformen ({len(FUEHRUNGSFORMEN)}):")
    for fuehr in FUEHRUNGSFORMEN:
        print(f"     - {fuehr}")
    print(f"\n   Ausschlussbegriffe im Kommentar ({len(KOMMENTAR_AUSSCHLUSS)}):")
    for term in KOMMENTAR_AUSSCHLUSS:
        print(f"     - {term}")
    
    # Prüfe ob Dateien existieren
    if not SNAPPING_FILE.exists():
        print(f"\n❌ FEHLER: Snapping-Datensatz nicht gefunden: {SNAPPING_FILE}")
        return 1
    
    if not MATCHED_TILDA_FILE.exists():
        print(f"\n❌ FEHLER: Matched TILDA-Datensatz nicht gefunden: {MATCHED_TILDA_FILE}")
        return 1
    
    # Erstelle analysis-Verzeichnis falls nicht vorhanden
    analysis_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"\n📂 Lade Snapping-Datensatz: {SNAPPING_FILE.name}")
    snapping_gdf = gpd.read_file(SNAPPING_FILE)
    
    total_segments = len(snapping_gdf)
    print(f"   Gesamt Segmente: {total_segments:,}")
    
    # Filtere nach konfigurierten Führungsformen
    fuehr_mask = snapping_gdf['fuehr'].isin(FUEHRUNGSFORMEN)
    filtered_gdf = snapping_gdf[fuehr_mask].copy()
    
    total_with_fuehr = len(filtered_gdf)
    print(f"\n📊 Segmente mit konfigurierten Führungsformen: {total_with_fuehr:,} ({total_with_fuehr/total_segments*100:.2f}%)")
    
    # Zeige Verteilung nach Führungsformen
    print("\n   Verteilung nach Führungsform:")
    for fuehr in FUEHRUNGSFORMEN:
        count = len(filtered_gdf[filtered_gdf['fuehr'] == fuehr])
        if count > 0:
            print(f"     {count:6,}x | {fuehr}")
    
    if total_with_fuehr == 0:
        print("\n✅ ERGEBNIS: Keine Segmente mit den konfigurierten Führungsformen gefunden!")
        return 0
    
    # Schließe temporäre Markierungen und Baustellen aus
    print(f"\n🚧 Schließe temporäre Markierungen und Baustellen aus...")
    
    # Erstelle Maske für Ausschluss (case-insensitiv)
    exclude_mask = pd.Series([False] * len(filtered_gdf), index=filtered_gdf.index)
    
    if 'Kommentar' in filtered_gdf.columns:
        kommentar_series = filtered_gdf['Kommentar'].fillna('').str.lower()
        for term in KOMMENTAR_AUSSCHLUSS:
            term_lower = term.lower()
            exclude_mask |= kommentar_series.str.contains(term_lower, na=False)
    
    excluded_count = exclude_mask.sum()
    print(f"   Ausgeschlossene Segmente: {excluded_count:,}")
    
    # Zeige Beispiele für ausgeschlossene Segmente
    if excluded_count > 0:
        print("   Beispiel-Kommentare (erste 5):")
        for kom in filtered_gdf[exclude_mask]['Kommentar'].head(5):
            print(f"     - {kom}")
    
    # Wende Ausschluss an
    filtered_gdf = filtered_gdf[~exclude_mask].copy()
    
    after_exclusion = len(filtered_gdf)
    print(f"   Verbleibende Segmente: {after_exclusion:,}")
    
    if after_exclusion == 0:
        print("\n✅ ERGEBNIS: Keine Segmente nach Ausschluss verblieben!")
        return 0
    
    # Filtere davon diejenigen ohne Breite
    # breite=NULL oder breite='Breite fehlt'
    no_width_mask = (
        filtered_gdf['breite'].isna() | 
        filtered_gdf['breite'].isnull() | 
        (filtered_gdf['breite'] == 'Breite fehlt')
    )
    no_width_gdf = filtered_gdf[no_width_mask].copy()
    
    total_no_width = len(no_width_gdf)
    print(f"\n📊 Segmente ohne Breite: {total_no_width:,} ({total_no_width/after_exclusion*100:.2f}%)")
    
    # Zeige Verteilung nach Führungsformen (ohne Breite)
    if total_no_width > 0:
        print("\n   Verteilung ohne Breite nach Führungsform:")
        for fuehr in FUEHRUNGSFORMEN:
            count = len(no_width_gdf[no_width_gdf['fuehr'] == fuehr])
            if count > 0:
                print(f"     {count:6,}x | {fuehr}")
    
    if total_no_width == 0:
        print("\n✅ ERGEBNIS: Alle Segmente haben eine Breite!")
        return 0
    
    # Extrahiere tilda_ids (alle zusammengeführten IDs)
    print(f"\n🔍 Extrahiere tilda_ids aus Snapping-Daten...")
    
    # Verwende die neue tilda_ids Spalte (mit Semikolon getrennte IDs) falls verfügbar
    # Ansonsten Fallback auf einzelne tilda_id
    all_tilda_ids = set()
    
    if 'tilda_ids' in no_width_gdf.columns:
        print(f"   Verwende 'tilda_ids' Spalte (alle zusammengeführten IDs)...")
        for tilda_ids_str in no_width_gdf['tilda_ids'].dropna():
            if pd.notna(tilda_ids_str) and str(tilda_ids_str).strip():
                # Splitte Semikolon-getrennte Werte
                ids = str(tilda_ids_str).split(';')
                for tid in ids:
                    tid_clean = tid.strip()
                    if tid_clean and tid_clean.lower() not in ['none', 'nan', '']:
                        all_tilda_ids.add(tid_clean)
    else:
        print(f"   Fallback auf 'tilda_id' Spalte (nur primäre IDs)...")
        if 'tilda_id' in no_width_gdf.columns:
            for tid in no_width_gdf['tilda_id'].dropna().unique():
                if pd.notna(tid) and str(tid).strip():
                    tid_clean = str(tid).strip()
                    if tid_clean.lower() not in ['none', 'nan', '']:
                        all_tilda_ids.add(tid_clean)
    
    tilda_ids = sorted(all_tilda_ids)
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
    
    filtered_tilda_count = len(filtered_tilda_gdf)
    print(f"   Gefilterte TILDA-Wege: {filtered_tilda_count:,}")
    
    if filtered_tilda_count == 0:
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
    
    # Transformiere zu WGS84 (EPSG:4326) für GeoJSON RFC-Konformität
    if filtered_tilda_gdf.crs != "EPSG:4326":
        print(f"   Transformiere CRS von {filtered_tilda_gdf.crs} nach EPSG:4326 (WGS84)...")
        filtered_tilda_gdf = filtered_tilda_gdf.to_crs("EPSG:4326")
    
    filtered_tilda_gdf.to_file(OUTPUT_FILE, driver="GeoJSON")
    
    print(f"\n✅ Export erfolgreich!")
    print(f"   Datei: {OUTPUT_FILE}")
    print(f"   Format: GeoJSON (EPSG:4326)")
    print(f"   Anzahl Features: {filtered_tilda_count:,}")
    
    # Statistik
    print("\n" + "=" * 80)
    print("ZUSAMMENFASSUNG")
    print("=" * 80)
    print(f"\nGesamt Segmente: {total_segments:,}")
    print(f"Segmente mit konfigurierten Führungsformen: {total_with_fuehr:,}")
    print(f"Ausgeschlossene Segmente (temporär/Baustelle): {excluded_count:,}")
    print(f"Verbleibende Segmente: {after_exclusion:,}")
    print(f"Segmente ohne Breite: {total_no_width:,}")
    print(f"Eindeutige tilda_ids: {total_tilda_ids:,}")
    print(f"Exportierte TILDA-Wege: {filtered_tilda_count:,}")
    
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
    
    if filtered_tilda_count > 10:
        print(f"\n   ... und {filtered_tilda_count - 10} weitere")
    
    print("\n" + "=" * 80)
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
