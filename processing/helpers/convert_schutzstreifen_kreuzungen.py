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
from .progressbar import print_progressbar
from .schutzstreifen_conversion_helper import get_endpoints, get_all_endpoints
from .schutzstreifen_conversion_helper import find_adjacent_ways
from .schutzstreifen_conversion_helper import find_connected_schutzstreifen, calculate_segment_length
from .schutzstreifen_conversion_helper import merge_segment_geometries

logger = logging.getLogger(__name__)


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
