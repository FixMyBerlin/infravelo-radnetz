#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
district_assignment.py
--------------------------------------------------------------------
Hilfsfunktionen für die Zuweisung von Bezirksnummern zu Kanten
basierend auf räumlichen Überschneidungen.

Diese Funktionen werden sowohl im Snapping- als auch im Aggregations-Prozess verwendet.
"""
import logging
import pandas as pd
import geopandas as gpd
from helpers.progressbar import print_progressbar


def assign_district_to_edges(edges_gdf, districts_path, crs):
    """
    Weist den Kanten Bezirksnummern basierend auf dem größten räumlichen Anteil zu.
    Kanten, die sich über mehrere Bezirke erstrecken, erhalten den Bezirk,
    in dem sie den größten Anteil haben.
    
    Args:
        edges_gdf: GeoDataFrame mit den Kanten
        districts_path: Pfad zur Bezirks-Datei
        crs: Koordinatensystem für Berechnungen
        
    Returns:
        GeoDataFrame mit zusätzlicher 'Bezirksnummer'-Spalte
    """
    logging.info(f"Lade Bezirksgrenzen von {districts_path}")
    districts_gdf = gpd.read_file(districts_path).to_crs(crs)
    
    # Sicherstellen, dass die CRS übereinstimmen
    if edges_gdf.crs != districts_gdf.crs:
        logging.info("Projiziere Bezirke auf das CRS der Kanten")
        districts_gdf = districts_gdf.to_crs(edges_gdf.crs)
    
    logging.info("Berechne Bezirkszuweisungen basierend auf größtem räumlichen Anteil...")
    
    # Initialisiere Bezirksnummer-Spalte
    edges_gdf['Bezirksnummer'] = None
    
    total_edges = len(edges_gdf)
    processed_edges = 0
    
    for idx, edge in edges_gdf.iterrows():
        edge_geom = edge.geometry
        max_intersection_length = 0
        assigned_district = None
        
        # Prüfe Überschneidung mit allen Bezirken
        for _, district in districts_gdf.iterrows():
            try:
                # Berechne Überschneidung zwischen Kante und Bezirk
                intersection = edge_geom.intersection(district.geometry)
                
                if intersection.is_empty:
                    continue
                
                # Berechne Länge der Überschneidung
                if hasattr(intersection, 'length'):
                    intersection_length = intersection.length
                else:
                    # Falls Punkt oder andere Geometrie
                    intersection_length = 0
                
                # Speichere Bezirk mit größter Überschneidung
                if intersection_length > max_intersection_length:
                    max_intersection_length = intersection_length
                    # Extrahiere zweistellige Bezirksnummer aus 'gem'-Spalte
                    if 'gem' in district and pd.notna(district['gem']):
                        assigned_district = str(district['gem'])[-2:]
                    else:
                        assigned_district = None
                        
            except Exception as e:
                logging.warning(f"Fehler bei Überschneidungsberechnung für Kante {idx}: {e}")
                continue
        
        # Weise Bezirksnummer zu
        edges_gdf.at[idx, 'Bezirksnummer'] = assigned_district
        
        processed_edges += 1
        if processed_edges % 100 == 0:
            print_progressbar(processed_edges, total_edges, prefix="Bezirkszuweisung: ")
    
    # Finale Fortschrittsanzeige
    print_progressbar(total_edges, total_edges, prefix="Bezirkszuweisung: ")
    
    # Statistiken
    assigned_count = edges_gdf['Bezirksnummer'].notna().sum()
    logging.info(f"Bezirkszuweisung abgeschlossen: {assigned_count}/{total_edges} Kanten haben eine Bezirksnummer erhalten")
    
    if assigned_count > 0:
        district_counts = edges_gdf['Bezirksnummer'].value_counts()
        logging.info(f"Verteilung nach Bezirken: {dict(district_counts)}")
    
    return edges_gdf
