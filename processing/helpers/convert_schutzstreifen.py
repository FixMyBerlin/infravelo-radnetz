#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
convert_schutzstreifen.py
--------------------------------------------------------------------
Funktionen für die Konvertierung von kurzen Schutzstreifen zu Radfahrstreifen.

Diese Funktionen werden im Processing-Pipeline verwendet um kurze Schutzstreifen 
(<50m), die an Radfahrstreifen angrenzen, automatisch zu Radfahrstreifen zu konvertieren.
"""

import logging
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point, LineString, MultiLineString
from shapely.ops import linemerge
from collections import defaultdict
from .progressbar import print_progressbar

logger = logging.getLogger(__name__)

def get_endpoints(geometry):
    """Extrahiere Start- und Endpunkte einer Geometrie."""
    if isinstance(geometry, MultiLineString):
        # Bei MultiLineString nehme ersten und letzten Punkt der ersten/letzten Linie
        coords = []
        for geom in geometry.geoms:
            coords.extend(list(geom.coords))
    else:
        coords = list(geometry.coords)
    
    if len(coords) < 2:
        return None, None
    
    return Point(coords[0]), Point(coords[-1])

def find_connected_schutzstreifen(schutzstreifen_gdf, tolerance=0.1):
    """Finde zusammenhängende Schutzstreifen-Segmente mit optimiertem räumlichem Index."""
    logger.info("Suche zusammenhängende Schutzstreifen-Segmente...")
    
    # Erstelle Index für Endpunkte
    endpoints = {}
    for idx, row in schutzstreifen_gdf.iterrows():
        start, end = get_endpoints(row.geometry)
        if start and end:
            endpoints[idx] = {'start': start, 'end': end, 'geometry': row.geometry}
    
    # Optimierte Verbindungssuche
    connections = defaultdict(set)
    indices = list(endpoints.keys())
    
    logger.debug(f"Verarbeite {len(indices)} Schutzstreifen...")
    
    for i, idx1 in enumerate(indices):
        if i % 500 == 0 and i > 0:  # Progress logging (weniger häufig als im Analyse-Script)
            logger.debug(f"Fortschritt: {i}/{len(indices)}")
            
        data1 = endpoints[idx1]
        
        # Erstelle Suchpuffer um Endpunkte
        search_buffer_start = data1['start'].buffer(tolerance * 2)
        search_buffer_end = data1['end'].buffer(tolerance * 2)
        
        for j, idx2 in enumerate(indices[i+1:], i+1):
            data2 = endpoints[idx2]
            
            # Erste räumliche Filterung
            if not (search_buffer_start.intersects(data2['start']) or 
                   search_buffer_start.intersects(data2['end']) or
                   search_buffer_end.intersects(data2['start']) or
                   search_buffer_end.intersects(data2['end'])):
                continue
            
            # Prüfe exakte Distanzen
            distances = [
                data1['start'].distance(data2['start']),
                data1['start'].distance(data2['end']),
                data1['end'].distance(data2['start']),
                data1['end'].distance(data2['end'])
            ]
            
            if min(distances) <= tolerance:
                connections[idx1].add(idx2)
                connections[idx2].add(idx1)
    
    # Erstelle zusammenhängende Komponenten (Segmente)
    visited = set()
    segments = []
    
    for start_idx in endpoints.keys():
        if start_idx in visited:
            continue
            
        # DFS für zusammenhängende Komponente
        component = []
        stack = [start_idx]
        
        while stack:
            current = stack.pop()
            if current in visited:
                continue
                
            visited.add(current)
            component.append(current)
            
            # Füge alle verbundenen Knoten hinzu
            for neighbor in connections[current]:
                if neighbor not in visited:
                    stack.append(neighbor)
        
        segments.append(component)
    
    logger.debug(f"Gefundene Segmente: {len(segments)}")
    return segments

def calculate_segment_length(segment_indices, schutzstreifen_gdf):
    """Berechne Gesamtlänge eines Segments."""
    total_length = 0
    geometries = []
    
    for idx in segment_indices:
        geom = schutzstreifen_gdf.loc[idx, 'geometry']
        geometries.append(geom)
        total_length += geom.length
    
    return total_length, geometries

def merge_segment_geometries(geometries):
    """Versuche Geometrien zu einem zusammenhängenden Segment zu verbinden."""
    try:
        # Normalisiere alle Geometrien zu LineStrings
        lines = []
        for geom in geometries:
            if isinstance(geom, MultiLineString):
                # MultiLineString zu einzelnen LineStrings aufbrechen
                for line in geom.geoms:
                    lines.append(line)
            elif isinstance(geom, LineString):
                lines.append(geom)
            else:
                continue  # Andere Geometrietypen überspringen
        
        if len(lines) == 0:
            return None
        elif len(lines) == 1:
            return lines[0]
        else:
            # Versuche LineString-Merger
            merged = linemerge(lines)
            return merged
    except Exception as e:
        logger.warning(f"Fehler beim Merger von Geometrien: {e}")
        # Fallback: MultiLineString aus allen verfügbaren LineStrings
        lines = []
        for geom in geometries:
            if isinstance(geom, MultiLineString):
                lines.extend(list(geom.geoms))
            elif isinstance(geom, LineString):
                lines.append(geom)
        
        if lines:
            return MultiLineString(lines)
        else:
            return None

def find_adjacent_ways(segment_geometry, all_ways_gdf, tolerance=0.1):
    """Finde alle angrenzenden Wege zu einem Segment mit räumlichem Index."""
    adjacent_ways = []
    
    # Extrahiere Endpunkte des Segments
    start_point, end_point = get_endpoints(segment_geometry)
    
    if not start_point or not end_point:
        return adjacent_ways
    
    # Erstelle Puffer um Endpunkte für räumliche Suche
    search_buffer_start = start_point.buffer(tolerance * 2)
    search_buffer_end = end_point.buffer(tolerance * 2)
    
    # Verwende räumlichen Index für erste Filterung
    possible_matches_start = all_ways_gdf[all_ways_gdf.geometry.intersects(search_buffer_start)]
    possible_matches_end = all_ways_gdf[all_ways_gdf.geometry.intersects(search_buffer_end)]
    
    # Kombiniere beide Mengen
    possible_matches = pd.concat([possible_matches_start, possible_matches_end]).drop_duplicates()
    
    # Suche nach angrenzenden Wegen in der gefilterten Menge
    for idx, way in possible_matches.iterrows():
        if way['fuehr'] == 'Schutzstreifen (OSM:Radfahrstreifen)':
            continue  # Skip andere Schutzstreifen
            
        way_start, way_end = get_endpoints(way.geometry)
        if not way_start or not way_end:
            continue
        
        # Prüfe Verbindung zu Segment-Endpunkten
        distances = [
            start_point.distance(way_start),
            start_point.distance(way_end),
            end_point.distance(way_start),
            end_point.distance(way_end)
        ]
        min_distance = min(distances)
        
        if min_distance <= tolerance:
            adjacent_ways.append({
                'way_id': way.get('sfid', idx),
                'fuehr': way['fuehr'],
                'element_nr': way.get('element_nr', 'unknown'),
                'distance': min_distance
            })
    
    return adjacent_ways

def convert_short_schutzstreifen_to_radfahrstreifen(gdf, length_threshold=50.0, tolerance=0.1):
    """
    Konvertiere kurze Schutzstreifen zu Radfahrstreifen, wenn sie an Radfahrstreifen angrenzen.
    
    Args:
        gdf: GeoDataFrame mit allen Wegen nach dem Snapping
        length_threshold: Maximale Länge für "kurze" Schutzstreifen in Metern (default: 50.0)
        tolerance: Toleranz für räumliche Verbindungen in Metern (default: 0.1)
    
    Returns:
        GeoDataFrame mit konvertierten Attributen
    """
    logger.info("Starte Konvertierung kurzer Schutzstreifen zu Radfahrstreifen...")
    
    # Kopiere DataFrame um Original nicht zu verändern
    result_gdf = gdf.copy()
    
    # Filtere alle Schutzstreifen
    schutzstreifen_mask = result_gdf['fuehr'] == 'Schutzstreifen'
    schutzstreifen_gdf = result_gdf[schutzstreifen_mask].copy()
    
    if len(schutzstreifen_gdf) == 0:
        logger.info("Keine Schutzstreifen gefunden - keine Konvertierung nötig")
        return result_gdf
    
    logger.info(f"Analysiere {len(schutzstreifen_gdf)} Schutzstreifen...")
    
    # Finde zusammenhängende Schutzstreifen-Segmente
    segments = find_connected_schutzstreifen(schutzstreifen_gdf, tolerance)
    
    converted_count = 0
    converted_segments = []
    
    logger.info(f"Prüfe {len(segments)} Schutzstreifen-Segmente...")
    
    # Analysiere jedes Segment
    for i, segment_indices in enumerate(segments):
        if i % 100 == 0 and i > 0:
            logger.debug(f"Fortschritt: {i}/{len(segments)}")
        
        # Berechne Gesamtlänge des Segments
        total_length, geometries = calculate_segment_length(segment_indices, schutzstreifen_gdf)
        
        # Prüfe ob Segment kurz genug ist
        if total_length >= length_threshold:
            continue
        
        # Erstelle merged Geometrie für räumliche Analyse
        merged_geometry = merge_segment_geometries(geometries)
        if merged_geometry is None:
            continue
        
        # Finde angrenzende Wege
        adjacent_ways = find_adjacent_ways(merged_geometry, result_gdf, tolerance)
        
        # Prüfe ob Radfahrstreifen unter den angrenzenden Wegen sind
        adjacent_fuehr = [way['fuehr'] for way in adjacent_ways]
        has_radfahrstreifen = 'Radfahrstreifen' in adjacent_fuehr
        
        if has_radfahrstreifen:
            # Konvertiere alle Wege in diesem Segment
            for idx in segment_indices:
                result_gdf.loc[idx, 'fuehr'] = 'Radfahrstreifen (OSM:Kurzer Schutzstreifen)'
            
            converted_count += len(segment_indices)
            converted_segments.append({
                'segment_length': round(total_length, 2),
                'way_count': len(segment_indices),
                'adjacent_fuehr': adjacent_fuehr
            })
    
    # Logging der Ergebnisse
    if converted_count > 0:
        logger.info(f"✔ {converted_count} kurze Schutzstreifen in {len(converted_segments)} Segmenten zu Radfahrstreifen konvertiert")
        
        # Detaillierte Statistiken
        total_converted_length = sum(seg['segment_length'] for seg in converted_segments)
        avg_length = total_converted_length / len(converted_segments)
        
        logger.info(f"  - Durchschnittliche Segmentlänge: {avg_length:.1f}m")
        logger.info(f"  - Gesamtlänge konvertiert: {total_converted_length:.1f}m")
        
        # Häufigste Übergänge (Debug-Info)
        transitions = {}
        for seg in converted_segments:
            # Filtere None-Werte heraus vor dem Sortieren
            valid_fuehr = [f for f in seg['adjacent_fuehr'] if f is not None]
            transition = " ↔ ".join(sorted(set(valid_fuehr)))
            transitions[transition] = transitions.get(transition, 0) + 1
        
        logger.debug("Häufigste Übergänge:")
        for transition, count in sorted(transitions.items(), key=lambda x: x[1], reverse=True)[:5]:
            logger.debug(f"  {transition}: {count}")
    else:
        logger.info("Keine kurzen Schutzstreifen an Radfahrstreifen gefunden - keine Konvertierung durchgeführt")
    
    return result_gdf
