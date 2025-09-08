#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
convert_schutzstreifen_at_bus_stops.py
--------------------------------------------------------------------
Funktionen für die Konvertierung von Schutzstreifen zu Radfahrstreifen an Bushaltestellen.

Diese Funktionen konvertieren Schutzstreifen, die:
1. Im 20m Umkreis von Bushaltestellen liegen UND 
2. An Radfahrstreifen angrenzen

Neue Führungsform: "Radfahrstreifen (OSM:Schutzstreifen an Haltestelle)"
"""

import logging
import pandas as pd
import geopandas as gpd
import os
from .progressbar import print_progressbar
from .schutzstreifen_conversion_helper import (
    find_schutzstreifen_adjacent_to_radfahrstreifen
)

logger = logging.getLogger(__name__)

def load_bus_stops(path, return_gdf=True):
    """
    Lädt die Bus-Haltestellen-Daten.
    
    Args:
        path: Pfad zur Bus-Haltestellen-Datei (.fgb)
        return_gdf: Wenn True, gibt GeoDataFrame zurück, sonst Pfad
        
    Returns:
        GeoDataFrame oder str: Bus-Haltestellen-Daten oder Pfad
    """
    if not os.path.exists(path):
        logger.error(f"Bus-Haltestellen-Datei nicht gefunden: {path}")
        return gpd.GeoDataFrame() if return_gdf else None
    
    if return_gdf:
        logger.info(f"Lade Bus-Haltestellen aus {path}")
        return gpd.read_file(path)
    else:
        return path

def identify_schutzstreifen_near_bus_stops(all_ways_gdf, bus_stops_gdf, buffer_distance=20):
    """
    Identifiziere Schutzstreifen im Umkreis von Bushaltestellen.
    
    Args:
        all_ways_gdf: GeoDataFrame mit allen Wegen
        bus_stops_gdf: GeoDataFrame mit Bushaltestellen
        buffer_distance: Pufferabstand in Metern
        
    Returns:
        GeoDataFrame: Schutzstreifen in der Nähe von Bushaltestellen
    """
    if bus_stops_gdf.empty:
        logger.warning("Keine Bus-Haltestellen verfügbar")
        return gpd.GeoDataFrame()
    
    logger.info(f"Identifiziere Schutzstreifen im {buffer_distance}m Umkreis von {len(bus_stops_gdf)} Bushaltestellen")
    
    # Filtere nur Schutzstreifen
    schutzstreifen_gdf = all_ways_gdf[all_ways_gdf['fuehr'] == 'Schutzstreifen'].copy()
    logger.info(f"Gesamt Schutzstreifen im Netzwerk: {len(schutzstreifen_gdf)}")
    
    if schutzstreifen_gdf.empty:
        logger.warning("Keine Schutzstreifen im Netzwerk gefunden")
        return gpd.GeoDataFrame()
    
    # Erstelle Puffer um Bushaltestellen
    bus_buffer = bus_stops_gdf.geometry.buffer(buffer_distance).unary_union
    
    # Finde Schutzstreifen die den Puffer schneiden
    schutzstreifen_near_stops = schutzstreifen_gdf[
        schutzstreifen_gdf.geometry.intersects(bus_buffer)
    ].copy()
    
    logger.info(f"Schutzstreifen im {buffer_distance}m Umkreis von Bushaltestellen: {len(schutzstreifen_near_stops)}")
    return schutzstreifen_near_stops

def find_schutzstreifen_adjacent_to_radfahrstreifen_local(schutzstreifen_near_stops, all_ways_gdf, tolerance=1.0):
    """
    Wrapper-Funktion für find_schutzstreifen_adjacent_to_radfahrstreifen.
    """
    def progress_callback(current, total, prefix=""):
        print_progressbar(current, total, prefix)
    
    return find_schutzstreifen_adjacent_to_radfahrstreifen(
        schutzstreifen_near_stops, 
        all_ways_gdf, 
        tolerance, 
        progress_callback
    )

def convert_schutzstreifen_at_bus_stops_with_gdf(all_ways_gdf, bus_stops_gdf, 
                                                buffer_distance=20, tolerance=1.0):
    """
    Konvertiere Schutzstreifen an Bushaltestellen mit direktem GeoDataFrame.
    
    Args:
        all_ways_gdf: GeoDataFrame mit allen Wegen
        bus_stops_gdf: GeoDataFrame mit Bushaltestellen 
        buffer_distance: Pufferabstand für Haltestellen in Metern
        tolerance: Toleranz für Angrenzungscheck in Metern
        
    Returns:
        GeoDataFrame: Aktualisierte Wege-Daten
    """
    logger.info("=== Schutzstreifen-Konvertierung an Bushaltestellen ===")
    
    if bus_stops_gdf.empty:
        logger.warning("Keine Bus-Haltestellen verfügbar - keine Konvertierung möglich")
        return all_ways_gdf.copy()
    
    result_gdf = all_ways_gdf.copy()
    
    # 1. Identifiziere Schutzstreifen im Umkreis von Bushaltestellen
    schutzstreifen_near_stops = identify_schutzstreifen_near_bus_stops(
        result_gdf, bus_stops_gdf, buffer_distance
    )
    
    if schutzstreifen_near_stops.empty:
        logger.info("Keine Schutzstreifen in der Nähe von Bushaltestellen gefunden")
        return result_gdf
    
    # 2. Prüfe welche Schutzstreifen an Radfahrstreifen angrenzen
    logger.info("Prüfe Angrenzung an Radfahrstreifen...")
    schutzstreifen_to_convert = find_schutzstreifen_adjacent_to_radfahrstreifen_local(
        schutzstreifen_near_stops, result_gdf, tolerance
    )
    
    if schutzstreifen_to_convert.empty:
        logger.info("Keine Schutzstreifen an Bushaltestellen grenzen an Radfahrstreifen an")
        return result_gdf
    
    # 3. Konvertiere die identifizierten Schutzstreifen
    logger.info(f"Konvertiere {len(schutzstreifen_to_convert)} Schutzstreifen an Bushaltestellen")
    
    converted_count = 0
    for idx, row in schutzstreifen_to_convert.iterrows():
        old_fuehr = result_gdf.loc[idx, 'fuehr']
        result_gdf.loc[idx, 'fuehr'] = 'Radfahrstreifen (OSM:Schutzstreifen an Haltestelle)'
        converted_count += 1
        
        sfid = row.get('sfid', idx)
        logger.debug(f"Konvertiert: sfid={sfid}, {old_fuehr} → {result_gdf.loc[idx, 'fuehr']}")
    
    logger.info(f"✅ {converted_count} Schutzstreifen an Bushaltestellen erfolgreich konvertiert")
    return result_gdf

def convert_schutzstreifen_at_bus_stops(all_ways_gdf, bus_stops_path, buffer_distance=20, tolerance=1.0):
    """
    Konvertiere Schutzstreifen an Bushaltestellen basierend auf einem Dateipfad.
    
    Args:
        all_ways_gdf: GeoDataFrame mit allen Wegen
        bus_stops_path: Pfad zu Bus-Haltestellen-Datei
        buffer_distance: Pufferabstand für Haltestellen in Metern
        tolerance: Toleranz für Angrenzungscheck in Metern
        
    Returns:
        GeoDataFrame: Aktualisierte Wege-Daten
    """
    bus_stops_gdf = load_bus_stops(bus_stops_path, return_gdf=True)
    return convert_schutzstreifen_at_bus_stops_with_gdf(
        all_ways_gdf, bus_stops_gdf, buffer_distance, tolerance
    )
