#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
convert_schutzstreifen_kreuzungen.py
--------------------------------------------------------------------
Funktionen für die Konvertierung von Schutzstreifen zu Mischverkehr an Kreuzungen.

Diese Funktionen werden im Processing-Pipeline verwendet um kurze Schutzstreifen 
(<50m), die an Mischverkehr angrenzen, automatisch zu Mischverkehr zu konvertieren.

Wichtige Richtungsberücksichtigung:
- Schutzstreifen werden nur mit anderen Schutzstreifen derselben Richtung (ri-Attribut) zu Segmenten zusammengefasst
- Angrenzender Mischverkehr wird unabhängig von der Richtung berücksichtigt
- Dies verhindert fälschliche Konvertierungen bei entgegengesetzten Fahrrichtungen
"""

import logging
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point, LineString, MultiLineString
from shapely.ops import linemerge
from collections import defaultdict
from .progressbar import print_progressbar
from .schutzstreifen_conversion_helper import get_endpoints, get_all_endpoints
from .schutzstreifen_conversion_helper import find_adjacent_ways

logger = logging.getLogger(__name__)


def find_connected_schutzstreifen(schutzstreifen_gdf, tolerance=0.1):
    """
    Finde zusammenhängende Schutzstreifen-Segmente mit optimiertem räumlichem Index und Richtungscheck.
    
    Diese Funktion ist identisch zur Funktion in convert_schutzstreifen.py und berücksichtigt
    die Fahrtrichtung bei der Segmentbildung.
    
    Args:
        schutzstreifen_gdf: GeoDataFrame mit Schutzstreifen
        tolerance: Toleranz für räumliche Verbindungen in Metern
        
    Returns:
        list: Liste von Listen mit Indizes zusammenhängender Schutzstreifen
    """
    logger.info("Suche zusammenhängende Schutzstreifen-Segmente...")
    
    # Erstelle Index für Endpunkte (alle Endpunkte, auch interne bei MultiLineString)
    endpoints = {}
    for idx, row in schutzstreifen_gdf.iterrows():
        all_endpoints = get_all_endpoints(row.geometry)
        if all_endpoints:
            endpoints[idx] = {
                'endpoints': all_endpoints,
                'geometry': row.geometry,
                'ri': row.get('ri', None)  # Richtungsattribut hinzufügen
            }
    
    # Optimierte Verbindungssuche
    connections = defaultdict(set)
    indices = list(endpoints.keys())
    
    logger.debug(f"Verarbeite {len(indices)} Schutzstreifen...")
    
    for i, idx1 in enumerate(indices):
        if i % 500 == 0 and i > 0:  # Progress logging
            logger.debug(f"Fortschritt: {i}/{len(indices)}")
            
        data1 = endpoints[idx1]
        
        for j, idx2 in enumerate(indices[i+1:], i+1):
            data2 = endpoints[idx2]
            
            # Prüfe alle Kombinationen von Endpunkten
            min_distance = float('inf')
            for endpoint1 in data1['endpoints']:
                for endpoint2 in data2['endpoints']:
                    distance = endpoint1.distance(endpoint2)
                    min_distance = min(min_distance, distance)
            
            if min_distance <= tolerance:
                # Zusätzlich: Prüfe ob beide Schutzstreifen die gleiche Richtung haben
                ri1 = data1.get('ri')
                ri2 = data2.get('ri')
                
                # Nur verbinden wenn Richtung identisch ist (oder eine der Richtungen unbekannt ist)
                if ri1 is None or ri2 is None or ri1 == ri2:
                    connections[idx1].add(idx2)
                    connections[idx2].add(idx1)
                else:
                    logger.debug(f"Schutzstreifen {idx1} (ri:{ri1}) und {idx2} (ri:{ri2}) haben unterschiedliche Richtungen - nicht verbunden")
    
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
    """
    Berechne Gesamtlänge eines Segments.
    
    Args:
        segment_indices: Liste von Indizes der Segmente
        schutzstreifen_gdf: GeoDataFrame mit Schutzstreifen
        
    Returns:
        tuple: (total_length, geometries)
    """
    total_length = 0
    geometries = []
    
    for idx in segment_indices:
        geom = schutzstreifen_gdf.loc[idx, 'geometry']
        geometries.append(geom)
        total_length += geom.length
    
    return total_length, geometries


def merge_segment_geometries(geometries):
    """
    Versuche Geometrien zu einem zusammenhängenden Segment zu verbinden.
    
    Args:
        geometries: Liste von LineString oder MultiLineString Objekten
        
    Returns:
        LineString oder MultiLineString: Verbundene Geometrie oder None
    """
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


def has_adjacent_mixed_traffic(segment_indices, schutzstreifen_gdf, all_ways_gdf, 
                               merged_geometry, tolerance=1.0):
    """
    Prüfe ob ein Schutzstreifen-Segment an Mischverkehr angrenzt.
    
    Berücksichtigt die Fahrtrichtung - Schutzstreifen muss an Mischverkehr mit
    derselben Richtung (ri-Attribut) angrenzen.
    
    Args:
        segment_indices: Liste von Indizes der Segmente
        schutzstreifen_gdf: GeoDataFrame mit Schutzstreifen
        all_ways_gdf: GeoDataFrame mit allen Wegen
        merged_geometry: Verbundene Geometrie des Segments
        tolerance: Toleranz für räumliche Verbindungen in Metern
        
    Returns:
        bool: True wenn Mischverkehr mit gleicher Richtung angrenzt
    """
    # Ermittle Segment-Richtung (für Richtungscheck)
    segment_ri = schutzstreifen_gdf.loc[segment_indices[0], 'ri'] if len(segment_indices) > 0 and 'ri' in schutzstreifen_gdf.columns else None
    
    # Finde angrenzende Wege MIT Richtungscheck
    adjacent_ways = find_adjacent_ways(
        geometry=merged_geometry,
        all_ways_gdf=all_ways_gdf,
        tolerance=tolerance,
        check_direction=True,  # WICHTIG: Richtungscheck für korrekte Zuordnung
        filter_fuehr=None,  # Alle Führungsformen berücksichtigen
        schutzstreifen_ri=segment_ri,
        segment_indices=segment_indices,
        schutzstreifen_gdf=schutzstreifen_gdf
    )
    
    # Prüfe ob Mischverkehr unter den angrenzenden Wegen ist
    adjacent_fuehr = [way['fuehr'] for way in adjacent_ways if way['fuehr'] is not None]
    has_mischverkehr = any('Mischverkehr' in fuehr for fuehr in adjacent_fuehr)
    
    if has_mischverkehr:
        logger.debug(f"Segment (ri={segment_ri}) grenzt an Mischverkehr mit gleicher Richtung: {adjacent_fuehr}")
    
    return has_mischverkehr


def convert_schutzstreifen_at_mixed_traffic(gdf, length_threshold=50.0, tolerance=1.0):
    """
    Konvertiere kurze Schutzstreifen zu Mischverkehr, wenn sie an Mischverkehr angrenzen.
    
    Diese Funktion berücksichtigt das Richtungsattribut 'ri':
    - Schutzstreifen werden nur mit anderen Schutzstreifen derselben Richtung zu Segmenten zusammengefasst
    - Angrenzender Mischverkehr wird MIT Richtungscheck geprüft (nur gleiche Fahrtrichtung)
    
    Args:
        gdf: GeoDataFrame mit allen Wegen nach dem Snapping
        length_threshold: Maximale Länge für "kurze" Schutzstreifen in Metern (default: 50.0)
        tolerance: Toleranz für räumliche Verbindungen in Metern (default: 1.0)
    
    Returns:
        GeoDataFrame mit konvertierten Attributen
    """
    logger.info("Starte Konvertierung kurzer Schutzstreifen an Mischverkehr...")
    
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
        
        # Prüfe ob Mischverkehr mit gleicher Richtung angrenzt
        if has_adjacent_mixed_traffic(segment_indices, schutzstreifen_gdf, result_gdf, 
                                      merged_geometry, tolerance):
            # Ermittle Segment-Richtung für Logging
            segment_ri = schutzstreifen_gdf.loc[segment_indices[0], 'ri'] if len(segment_indices) > 0 and 'ri' in schutzstreifen_gdf.columns else 'unbekannt'
            
            # Konvertiere alle Wege in diesem Segment
            for idx in segment_indices:
                result_gdf.loc[idx, 'fuehr'] = 'Mischverkehr (OSM:Schutzstreifen)'
            
            converted_count += len(segment_indices)
            
            converted_segments.append({
                'segment_length': round(total_length, 2),
                'way_count': len(segment_indices),
                'segment_ri': segment_ri
            })
            
            logger.debug(f"Konvertiert: {len(segment_indices)} Schutzstreifen ({total_length:.1f}m, ri={segment_ri}) zu Mischverkehr")
    
    # Logging der Ergebnisse
    if converted_count > 0:
        logger.info(f"✔ {converted_count} kurze Schutzstreifen in {len(converted_segments)} Segmenten zu Mischverkehr konvertiert")
        
        # Detaillierte Statistiken
        total_converted_length = sum(seg['segment_length'] for seg in converted_segments)
        avg_length = total_converted_length / len(converted_segments)
        
        logger.info(f"  - Durchschnittliche Segmentlänge: {avg_length:.1f}m")
        logger.info(f"  - Gesamtlänge konvertiert: {total_converted_length:.1f}m")
        
        # Richtungsstatistiken
        direction_stats = {}
        for seg in converted_segments:
            ri = seg['segment_ri']
            direction_stats[ri] = direction_stats.get(ri, 0) + 1
        
        logger.info("  - Richtungsverteilung der konvertierten Segmente:")
        for ri, count in sorted(direction_stats.items()):
            logger.info(f"    {ri}: {count}")
    else:
        logger.info("Keine kurzen Schutzstreifen an Mischverkehr gefunden - keine Konvertierung durchgeführt")
    
    return result_gdf
