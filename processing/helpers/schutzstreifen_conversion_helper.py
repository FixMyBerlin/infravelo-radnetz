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

def find_adjacent_ways(geometry, all_ways_gdf, tolerance=0.1, check_direction=True, 
                      filter_fuehr=None, schutzstreifen_ri=None, segment_indices=None, schutzstreifen_gdf=None):
    """
    Universelle Funktion zum Finden angrenzender Wege mit flexiblen Optionen.
    
    Diese Funktion kann sowohl für richtungsbewusste Konvertierungen als auch für
    richtungsunabhängige Analysen verwendet werden.
    
    Args:
        geometry: Geometrie des zu prüfenden Segments/Schutzstreifens
        all_ways_gdf: GeoDataFrame mit allen Wegen
        tolerance: Toleranz für räumliche Verbindungen in Metern
        check_direction: Ob Fahrtrichtung (ri) berücksichtigt werden soll
        filter_fuehr: Optional - Filtere nur nach bestimmten Führungsformen (z.B. ['Radfahrstreifen'])
        schutzstreifen_ri: Optional - ri-Wert des Schutzstreifens (für Richtungscheck)
        segment_indices: Optional - Indizes der Segmente (für Richtungsermittlung)
        schutzstreifen_gdf: Optional - GeoDataFrame für Richtungsermittlung
        
    Returns:
        list: Liste von Dictionaries mit angrenzenden Wegen
    """
    adjacent_ways = []
    
    # Ermittle die Richtung wenn nötig
    segment_ri = schutzstreifen_ri
    if check_direction and segment_ri is None and segment_indices and schutzstreifen_gdf is not None:
        if len(segment_indices) > 0:
            first_idx = segment_indices[0]
            segment_ri = schutzstreifen_gdf.loc[first_idx, 'ri'] if 'ri' in schutzstreifen_gdf.columns else None
    
    # Extrahiere Endpunkte - verwende get_all_endpoints für MultiLineString-Unterstützung
    if hasattr(geometry, '__iter__') and not isinstance(geometry, (str, Point, LineString, MultiLineString)):
        # Falls geometry eine Sammlung ist (z.B. für Segmente)
        endpoints = []
        for geom in geometry:
            endpoints.extend(get_all_endpoints(geom))
    else:
        endpoints = get_all_endpoints(geometry)
    
    if not endpoints:
        return adjacent_ways
    
    # Verwende räumlichen Index für erste Filterung
    for endpoint in endpoints:
        search_buffer = endpoint.buffer(tolerance * 2)
        possible_matches = all_ways_gdf[all_ways_gdf.geometry.intersects(search_buffer)]
        
        # Suche nach angrenzenden Wegen in der gefilterten Menge
        for idx, way in possible_matches.iterrows():
            if way['fuehr'] is not None and way['fuehr'] == 'Schutzstreifen':
                continue  # Skip andere Schutzstreifen
            
            # Optional: Filtere nach bestimmten Führungsformen
            if filter_fuehr and way['fuehr'] is not None and way['fuehr'] not in filter_fuehr:
                continue
                
            way_endpoints = get_all_endpoints(way.geometry)
            if not way_endpoints:
                continue
            
            # Prüfe Verbindung zu allen Way-Endpunkten
            min_distance = float('inf')
            for way_endpoint in way_endpoints:
                distance = endpoint.distance(way_endpoint)
                min_distance = min(min_distance, distance)
            
            if min_distance <= tolerance:
                # Richtungscheck nur wenn gewünscht
                way_ri = way.get('ri', None) if 'ri' in all_ways_gdf.columns else None
                
                if check_direction and way['fuehr'] is not None and 'Radfahrstreifen' in way['fuehr']:
                    if segment_ri is not None and way_ri is not None and segment_ri != way_ri:
                        logger.debug(f"{way['fuehr']} {idx} (ri:{way_ri}) hat andere Richtung als Schutzstreifen (ri:{segment_ri}) - nicht berücksichtigt")
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

def find_adjacent_radfahrstreifen(schutzstreifen_row, all_ways_gdf, tolerance=1.0, check_direction=False):
    """
    Prüfe ob ein einzelner Schutzstreifen an Radfahrstreifen angrenzt.
    
    Args:
        schutzstreifen_row: Pandas Series mit Schutzstreifen-Daten
        all_ways_gdf: GeoDataFrame mit allen Wegen
        tolerance: Toleranz für räumliche Verbindungen in Metern
        check_direction: Ob Fahrtrichtung berücksichtigt werden soll
        
    Returns:
        bool: True wenn angrenzende Radfahrstreifen gefunden wurden
    """
    schutzstreifen_ri = schutzstreifen_row.get('ri', None) if check_direction else None
    
    adjacent_ways = find_adjacent_ways(
        geometry=schutzstreifen_row.geometry,
        all_ways_gdf=all_ways_gdf,
        tolerance=tolerance,
        check_direction=check_direction,
        filter_fuehr=['Radfahrstreifen', 'Radfahrstreifen (Mittellinie)', 'Radfahrstreifen (breite Mittellinie)'],
        schutzstreifen_ri=schutzstreifen_ri
    )
    
    return len(adjacent_ways) > 0

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
        
        # Prüfe Angrenzung an Radfahrstreifen (ohne Richtungscheck)
        has_adjacent = find_adjacent_radfahrstreifen(schutzstreifen, all_ways_gdf, tolerance, check_direction=False)
        if has_adjacent:
            logger.debug(f"Schutzstreifen {schutzstreifen.get('sfid', idx)} hat angrenzende Radfahrstreifen")
            adjacent_schutzstreifen.append(idx)
    
    result_gdf = schutzstreifen_near_stops.loc[adjacent_schutzstreifen].copy()
    logger.info(f"Schutzstreifen an Haltestellen die an Radfahrstreifen angrenzen: {len(result_gdf)}")
    
    return result_gdf
