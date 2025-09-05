#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
schutzstreifen_conversion_helper.py
--------------------------------------------------------------------
Gemeinsame Funktionen für die Konvertierung von Schutzstreifen zu Radfahrstreifen.

Diese Funktionen werden von convert_schutzstreifen.py verwendet und 
berücksichtigen dabei immer die Fahrtrichtung (ri-Attribut) für korrekte 
Konvertierungen.

Wichtige Funktionen:
- get_endpoints(): Extrahiert äußere Start- und Endpunkte einer Geometrie
- get_all_endpoints(): Extrahiert alle Endpunkte (auch interne bei MultiLineString)
- find_adjacent_ways(): Findet angrenzende Wege mit Richtungsberücksichtigung
"""

import logging
import pandas as pd
from shapely.geometry import Point, LineString, MultiLineString

logger = logging.getLogger(__name__)

def get_endpoints(geometry):
    """
    Extrahiere Start- und Endpunkte einer Geometrie.
    
    Bei MultiLineString werden nur die äußeren Endpunkte zurückgegeben:
    - Start der ersten Teil-Geometrie
    - Ende der letzten Teil-Geometrie
    
    Args:
        geometry: LineString oder MultiLineString
        
    Returns:
        tuple: (start_point, end_point) als Point-Objekte oder (None, None)
    """
    if isinstance(geometry, MultiLineString):
        # Bei MultiLineString nehme ersten Punkt der ersten Linie und letzten Punkt der letzten Linie
        if len(geometry.geoms) == 0:
            return None, None
        
        first_line = geometry.geoms[0]
        last_line = geometry.geoms[-1]
        
        first_coords = list(first_line.coords)
        last_coords = list(last_line.coords)
        
        if len(first_coords) < 2 or len(last_coords) < 2:
            return None, None
        
        return Point(first_coords[0]), Point(last_coords[-1])
    else:
        coords = list(geometry.coords)
        if len(coords) < 2:
            return None, None
        
        return Point(coords[0]), Point(coords[-1])

def get_all_endpoints(geometry):
    """
    Extrahiere alle Endpunkte einer Geometrie (auch interne bei MultiLineString).
    
    Bei MultiLineString werden alle Endpunkte aller Teil-Geometrien zurückgegeben.
    Dies ist wichtig für korrekte Verbindungserkennung bei aufgeteilten Geometrien.
    
    Args:
        geometry: LineString oder MultiLineString
        
    Returns:
        list: Liste von Point-Objekten mit allen Endpunkten
    """
    if isinstance(geometry, MultiLineString):
        endpoints = []
        for line in geometry.geoms:
            coords = list(line.coords)
            if len(coords) >= 2:
                endpoints.append(Point(coords[0]))   # Start der Teil-Linie
                endpoints.append(Point(coords[-1]))  # Ende der Teil-Linie
        return endpoints
    else:
        coords = list(geometry.coords)
        if len(coords) < 2:
            return []
        return [Point(coords[0]), Point(coords[-1])]

def find_adjacent_ways(segment_geometry, segment_indices, schutzstreifen_gdf, all_ways_gdf, tolerance=0.1):
    """
    Finde alle angrenzenden Wege zu einem Segment mit räumlichem Index und Richtungscheck.
    
    Diese Funktion verwendet get_all_endpoints() für korrekte MultiLineString-Behandlung
    und berücksichtigt Fahrtrichtungen bei der Verbindungsprüfung.
    
    Args:
        segment_geometry: Geometrie des Segments
        segment_indices: Liste der Indizes der Wege im Segment
        schutzstreifen_gdf: GeoDataFrame mit Schutzstreifen-Daten
        all_ways_gdf: GeoDataFrame mit allen Wegen
        tolerance: Toleranz für räumliche Verbindungen in Metern
        
    Returns:
        list: Liste von Dictionaries mit angrenzenden Wegen
    """
    adjacent_ways = []
    
    # Ermittle die Richtung des Schutzstreifen-Segments
    segment_ri = None
    if len(segment_indices) > 0:
        # Nimm die Richtung des ersten Schutzstreifens im Segment (alle sollten gleich sein)
        first_idx = segment_indices[0]
        segment_ri = schutzstreifen_gdf.loc[first_idx, 'ri'] if 'ri' in schutzstreifen_gdf.columns else None
    
    # Extrahiere alle Endpunkte des Segments
    segment_endpoints = get_all_endpoints(segment_geometry)
    
    if not segment_endpoints:
        return adjacent_ways
    
    # Verwende räumlichen Index für erste Filterung
    for endpoint in segment_endpoints:
        search_buffer = endpoint.buffer(tolerance * 2)
        possible_matches = all_ways_gdf[all_ways_gdf.geometry.intersects(search_buffer)]
        
        # Suche nach angrenzenden Wegen in der gefilterten Menge
        for idx, way in possible_matches.iterrows():
            if way['fuehr'] == 'Schutzstreifen':
                continue  # Skip andere Schutzstreifen
                
            way_endpoints = get_all_endpoints(way.geometry)
            if not way_endpoints:
                continue
            
            # Prüfe Verbindung zu allen Way-Endpunkten
            min_distance = float('inf')
            for way_endpoint in way_endpoints:
                distance = endpoint.distance(way_endpoint)
                min_distance = min(min_distance, distance)
            
            if min_distance <= tolerance:
                # Zusätzlich: Prüfe Richtung bei Radfahrstreifen (alle Varianten)
                way_ri = way.get('ri', None) if 'ri' in all_ways_gdf.columns else None
                
                # Bei allen Radfahrstreifen-Typen: Nur akzeptieren wenn Richtung übereinstimmt
                if 'Radfahrstreifen' in way['fuehr']:
                    if segment_ri is not None and way_ri is not None and segment_ri != way_ri:
                        logger.debug(f"{way['fuehr']} {idx} (ri:{way_ri}) hat andere Richtung als Schutzstreifen-Segment (ri:{segment_ri}) - nicht berücksichtigt")
                        continue
                
                # Vermeide Duplikate
                way_id = way.get('sfid', idx)
                if not any(adj['way_id'] == way_id for adj in adjacent_ways):
                    adjacent_ways.append({
                        'way_id': way_id,
                        'fuehr': way['fuehr'],
                        'element_nr': way.get('element_nr', 'unknown'),
                        'ri': way_ri,
                        'distance': min_distance
                    })
    
    return adjacent_ways

def find_adjacent_radfahrstreifen_simple(schutzstreifen_row, all_ways_gdf, tolerance=1.0):
    """
    Prüfe ob ein einzelner Schutzstreifen an Radfahrstreifen angrenzt.
    
    Diese Version berücksichtigt KEINE Fahrtrichtung, da sie für Bus-Haltestellen
    verwendet wird, wo die Richtung weniger kritisch ist.
    
    Args:
        schutzstreifen_row: Pandas Series mit Schutzstreifen-Daten
        all_ways_gdf: GeoDataFrame mit allen Wegen
        tolerance: Toleranz für räumliche Verbindungen in Metern
        
    Returns:
        bool: True wenn angrenzende Radfahrstreifen gefunden wurden
    """
    # Extrahiere Endpunkte des Schutzstreifens
    start_point, end_point = get_endpoints(schutzstreifen_row.geometry)
    
    if not start_point or not end_point:
        return False
    
    # Erstelle Puffer um Endpunkte für räumliche Suche
    search_buffer_start = start_point.buffer(tolerance * 2)
    search_buffer_end = end_point.buffer(tolerance * 2)
    
    # Verwende räumlichen Index für erste Filterung
    possible_matches_start = all_ways_gdf[all_ways_gdf.geometry.intersects(search_buffer_start)]
    possible_matches_end = all_ways_gdf[all_ways_gdf.geometry.intersects(search_buffer_end)]
    
    # Kombiniere beide Mengen
    possible_matches = pd.concat([possible_matches_start, possible_matches_end]).drop_duplicates()
    
    # Suche nach angrenzenden Radfahrstreifen
    for idx, way in possible_matches.iterrows():
        # Skip den Schutzstreifen selbst
        if way.get('sfid') == schutzstreifen_row.get('sfid'):
            continue
            
        # Prüfe ob es sich um einen Radfahrstreifen handelt
        if way['fuehr'] not in ['Radfahrstreifen', 'Geschützter Radfahrstreifen']:
            continue
            
        way_start, way_end = get_endpoints(way.geometry)
        if not way_start or not way_end:
            continue
        
        # Prüfe Verbindung zu Schutzstreifen-Endpunkten
        distances = [
            start_point.distance(way_start),
            start_point.distance(way_end),
            end_point.distance(way_start),
            end_point.distance(way_end)
        ]
        min_distance = min(distances)
        
        if min_distance <= tolerance:
            return True
    
    return False

def find_schutzstreifen_adjacent_to_radfahrstreifen(schutzstreifen_near_stops, all_ways_gdf, tolerance=1.0, progress_callback=None):
    """
    Finde Schutzstreifen die an Radfahrstreifen angrenzen.
    
    Diese Funktion iteriert über eine Liste von Schutzstreifen und prüft für jeden,
    ob er an Radfahrstreifen angrenzt. Richtung wird dabei NICHT berücksichtigt.
    
    Args:
        schutzstreifen_near_stops: GeoDataFrame mit zu prüfenden Schutzstreifen
        all_ways_gdf: GeoDataFrame mit allen Wegen
        tolerance: Toleranz für räumliche Verbindungen in Metern
        progress_callback: Optional - Funktion für Progress-Updates
        
    Returns:
        GeoDataFrame: Gefilterte Schutzstreifen die an Radfahrstreifen angrenzen
    """
    adjacent_schutzstreifen = []
    total = len(schutzstreifen_near_stops)
    
    for i, (idx, schutzstreifen) in enumerate(schutzstreifen_near_stops.iterrows()):
        # Progress anzeigen (falls Callback verfügbar)
        if progress_callback and (i % 50 == 0 or i == total - 1):
            progress_callback(i + 1, total, "Prüfe Angrenzung: ")
        
        # Prüfe Angrenzung an Radfahrstreifen
        has_adjacent = find_adjacent_radfahrstreifen_simple(schutzstreifen, all_ways_gdf, tolerance)
        if has_adjacent:
            logger.debug(f"Schutzstreifen {schutzstreifen.get('sfid', idx)} hat angrenzende Radfahrstreifen")
            adjacent_schutzstreifen.append(idx)
    
    result_gdf = schutzstreifen_near_stops.loc[adjacent_schutzstreifen].copy()
    logger.info(f"Schutzstreifen an Haltestellen die an Radfahrstreifen angrenzen: {len(result_gdf)}")
    
    return result_gdf
