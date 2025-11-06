#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze_null_attributes.py
--------------------------------------------------------------------
Analysiert Snapping- und Aggregationsdaten auf NULL-Werte in bestimmten Attributen.
"""

import geopandas as gpd
import pandas as pd
from pathlib import Path

# Zu prüfende Attribute
ATTRIBUTES_TO_CHECK = ["fuehr", "ofm", "protek", "pflicht", "breite", "farbe", "ri", "verkehrsri", "trennstreifen"]

def analyze_file(filepath, file_description):
    """Analysiert eine Datei auf NULL-Werte in den angegebenen Attributen."""
    print(f"\n{'='*80}")
    print(f"ANALYSE: {file_description}")
    print(f"Datei: {filepath}")
    print(f"{'='*80}\n")
    
    if not Path(filepath).exists():
        print(f"⚠️  Datei nicht gefunden: {filepath}\n")
        return None
    
    # Datei einlesen
    try:
        if filepath.endswith('.gpkg'):
            # GeoPackage kann mehrere Layer haben
            # Versuche die bekannten Layer zu lesen
            layers_to_try = ["hinrichtung", "gegenrichtung"]
            
            for layer in layers_to_try:
                try:
                    print(f"\n--- Layer: {layer} ---")
                    gdf = gpd.read_file(filepath, layer=layer)
                    analyze_gdf(gdf, ATTRIBUTES_TO_CHECK)
                except Exception as layer_error:
                    print(f"⚠️  Layer '{layer}' nicht gefunden oder Fehler: {layer_error}")
        else:
            gdf = gpd.read_file(filepath)
            analyze_gdf(gdf, ATTRIBUTES_TO_CHECK)
            
    except Exception as e:
        print(f"❌ Fehler beim Lesen der Datei: {e}\n")
        return None

def analyze_gdf(gdf, attributes):
    """Analysiert ein GeoDataFrame auf NULL-Werte."""
    print(f"Anzahl Features: {len(gdf)}")
    print(f"Vorhandene Spalten: {list(gdf.columns)}\n")
    
    # Prüfe welche Attribute vorhanden sind
    missing_attrs = [attr for attr in attributes if attr not in gdf.columns]
    if missing_attrs:
        print(f"⚠️  Folgende Attribute fehlen komplett: {missing_attrs}\n")
    
    present_attrs = [attr for attr in attributes if attr in gdf.columns]
    
    if not present_attrs:
        print("❌ Keine der zu prüfenden Attribute vorhanden!\n")
        return
    
    print(f"Analysiere folgende Attribute: {present_attrs}\n")
    
    # Analysiere jedes Attribut
    results = []
    for attr in present_attrs:
        null_count = gdf[attr].isna().sum()
        null_percentage = (null_count / len(gdf)) * 100 if len(gdf) > 0 else 0
        
        # Eindeutige Werte (ohne NULL)
        unique_values = gdf[attr].dropna().unique()
        
        results.append({
            'Attribut': attr,
            'NULL-Anzahl': null_count,
            'NULL-Prozent': f"{null_percentage:.2f}%",
            'Eindeutige Werte (ohne NULL)': len(unique_values),
            'Beispielwerte': list(unique_values[:5]) if len(unique_values) > 0 else []
        })
    
    # Ergebnisse als Tabelle
    df_results = pd.DataFrame(results)
    print(df_results.to_string(index=False))
    print()
    
    # Detaillierte Wertverteilung für Attribute mit NULL-Werten
    for attr in present_attrs:
        null_count = gdf[attr].isna().sum()
        if null_count > 0:
            print(f"\n📊 Detaillierte Analyse für '{attr}' (mit {null_count} NULL-Werten):")
            value_counts = gdf[attr].value_counts(dropna=False)
            print(value_counts.to_string())
            print()

def main():
    """Hauptfunktion."""
    base_path = Path(__file__).parent.parent
    
    # Liste der zu analysierenden Dateien
    files_to_analyze = [
        # Snapping-Daten
        (base_path / "output" / "snapping_network_enriched.fgb", 
         "Snapping Network Enriched (Gesamt)"),
        (base_path / "output" / "snapping_network_enriched_neukoelln.fgb", 
         "Snapping Network Enriched (Neukölln)"),
        (base_path / "output" / "snapping_network_enriched_norden.fgb", 
         "Snapping Network Enriched (Norden)"),
        
        # Konvertierte Bikelanes (Input für Aggregation)
        (base_path / "output" / "snapping_converted_bikelanes.fgb", 
         "Snapping Converted Bikelanes (Gesamt)"),
        (base_path / "output" / "snapping_converted_bikelanes_neukoelln.fgb", 
         "Snapping Converted Bikelanes (Neukölln)"),
        (base_path / "output" / "snapping_converted_bikelanes_norden.fgb", 
         "Snapping Converted Bikelanes (Norden)"),
        
        # Aggregierte Daten (mehrere Layer pro Datei)
        (base_path / "output" / "aggregated_rvn_final_neukoelln.gpkg", 
         "Aggregated RVN Final (Neukölln)"),
        (base_path / "output" / "aggregated_rvn_final_norden.gpkg", 
         "Aggregated RVN Final (Norden)"),
    ]
    
    print("="*80)
    print("NULL-WERT ANALYSE FÜR SNAPPING UND AGGREGATIONSDATEN")
    print("="*80)
    print(f"\nZu prüfende Attribute: {ATTRIBUTES_TO_CHECK}\n")
    
    for filepath, description in files_to_analyze:
        analyze_file(str(filepath), description)
    
    print("\n" + "="*80)
    print("ANALYSE ABGESCHLOSSEN")
    print("="*80 + "\n")

if __name__ == "__main__":
    main()
