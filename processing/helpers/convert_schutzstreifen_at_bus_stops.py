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
from shapely.geometry import Point, LineString, MultiLineString
from .progressbar import print_progressbar

logger = logging.getLogger(__name__)

def load_bus_stops(bus_stops_path="output/bus_stops_on_rvn.fgb"):
    """Lade Bushaltestellen auf RVN."""
    try:
        if not os.path.exists(bus_stops_path):
            logger.warning(f"Bushaltestellen-Datei nicht gefunden: {bus_stops_path}")
            return None
            
        bus_stops_gdf = gpd.read_file(bus_stops_path)
        logger.info(f"Bushaltestellen geladen: {len(bus_stops_gdf)} Haltestellen")
        return bus_stops_gdf
    except Exception as e:
        logger.error(f"Fehler beim Laden der Bushaltestellen: {e}")
        return None

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

def find_schutzstreifen_near_bus_stops(gdf, bus_stops_gdf, buffer_distance=20.0):
    """Finde Schutzstreifen in der Nähe von Bushaltestellen."""
    if bus_stops_gdf is None or len(bus_stops_gdf) == 0:
        logger.warning("Keine Bushaltestellen verfügbar")
        return gdf[gdf['fuehr'] == 'Schutzstreifen'].copy()  # Fallback: alle Schutzstreifen
    
    logger.info(f"Suche Schutzstreifen im {buffer_distance}m Umkreis von Bushaltestellen...")
    
    # Filtere zunächst nur Schutzstreifen
    schutzstreifen_gdf = gdf[gdf['fuehr'] == 'Schutzstreifen'].copy()
    logger.info(f"Gefundene Schutzstreifen gesamt: {len(schutzstreifen_gdf)}")
    
    if len(schutzstreifen_gdf) == 0:
        logger.info("Keine Schutzstreifen gefunden")
        return schutzstreifen_gdf
    
    # Stelle sicher, dass beide GeoDataFrames das gleiche CRS haben
    if schutzstreifen_gdf.crs != bus_stops_gdf.crs:
        bus_stops_gdf = bus_stops_gdf.to_crs(schutzstreifen_gdf.crs)
    
    # Erstelle Puffer um Bushaltestellen
    bus_stops_buffered = bus_stops_gdf.copy()
    bus_stops_buffered['geometry'] = bus_stops_buffered.geometry.buffer(buffer_distance)
    
    # Räumlicher Join: Finde Schutzstreifen die Bushaltestellen-Puffer schneiden
    schutzstreifen_near_stops = gpd.sjoin(
        schutzstreifen_gdf, 
        bus_stops_buffered[['geometry']], 
        how='inner', 
        predicate='intersects'
    )
    
    # Entferne Duplikate (falls ein Schutzstreifen mehrere Haltestellen trifft)
    original_columns = schutzstreifen_gdf.columns.tolist()
    schutzstreifen_near_stops = schutzstreifen_near_stops[original_columns].drop_duplicates()
    
    logger.info(f"Schutzstreifen in {buffer_distance}m Umkreis von Haltestellen: {len(schutzstreifen_near_stops)}")
    
    return schutzstreifen_near_stops

def find_adjacent_radfahrstreifen(schutzstreifen_row, all_ways_gdf, tolerance=0.1):
    """Prüfe ob ein Schutzstreifen an Radfahrstreifen angrenzt."""
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

def find_schutzstreifen_adjacent_to_radfahrstreifen(schutzstreifen_near_stops, all_ways_gdf, tolerance=0.1):
    """Finde Schutzstreifen die an Radfahrstreifen angrenzen."""
    logger.info("Prüfe welche Schutzstreifen an Radfahrstreifen angrenzen...")
    
    adjacent_schutzstreifen = []
    total = len(schutzstreifen_near_stops)
    
    for i, (idx, schutzstreifen) in enumerate(schutzstreifen_near_stops.iterrows()):
        # Progress anzeigen
        if i % 50 == 0 or i == total - 1:
            print_progressbar(i + 1, total, "Prüfe Angrenzung: ")
        
        if find_adjacent_radfahrstreifen(schutzstreifen, all_ways_gdf, tolerance):
            adjacent_schutzstreifen.append(idx)
    
    result_gdf = schutzstreifen_near_stops.loc[adjacent_schutzstreifen].copy()
    logger.info(f"Schutzstreifen an Haltestellen die an Radfahrstreifen angrenzen: {len(result_gdf)}")
    
    return result_gdf

def convert_schutzstreifen_at_bus_stops(gdf, bus_stops_path="output/bus_stops_on_rvn.fgb", 
                                       buffer_distance=20.0, tolerance=0.1):
    """
    Hauptfunktion: Konvertiert Schutzstreifen zu Radfahrstreifen an Bushaltestellen.
    
    Args:
        gdf: GeoDataFrame mit allen Straßendaten
        bus_stops_path: Pfad zu den Bushaltestellen
        buffer_distance: Suchradius um Bushaltestellen in Metern
        tolerance: Toleranz für Angrenzungsprüfung in Metern
    
    Returns:
        GeoDataFrame: Bearbeitete Daten mit konvertierten Schutzstreifen
    """
    logger.info("=" * 60)
    logger.info("KONVERTIERUNG: SCHUTZSTREIFEN ZU RADFAHRSTREIFEN AN BUSHALTESTELLEN")
    logger.info("=" * 60)
    
    # Kopie erstellen um Original nicht zu verändern
    result_gdf = gdf.copy()
    
    # 1. Bushaltestellen laden
    bus_stops_gdf = load_bus_stops(bus_stops_path)
    if bus_stops_gdf is None:
        logger.warning("Konvertierung übersprungen: Keine Bushaltestellen verfügbar")
        return result_gdf
    
    # 2. Schutzstreifen in der Nähe von Bushaltestellen finden
    schutzstreifen_near_stops = find_schutzstreifen_near_bus_stops(
        result_gdf, bus_stops_gdf, buffer_distance
    )
    
    if len(schutzstreifen_near_stops) == 0:
        logger.info("Keine Schutzstreifen in der Nähe von Bushaltestellen gefunden")
        return result_gdf
    
    # 3. Schutzstreifen finden, die an Radfahrstreifen angrenzen
    schutzstreifen_to_convert = find_schutzstreifen_adjacent_to_radfahrstreifen(
        schutzstreifen_near_stops, result_gdf, tolerance
    )
    
    if len(schutzstreifen_to_convert) == 0:
        logger.info("Keine Schutzstreifen gefunden, die beide Bedingungen erfüllen")
        return result_gdf
    
    # 4. Konvertierung durchführen
    logger.info(f"Konvertiere {len(schutzstreifen_to_convert)} Schutzstreifen...")
    
    converted_count = 0
    for idx in schutzstreifen_to_convert.index:
        if result_gdf.loc[idx, 'fuehr'] == 'Schutzstreifen':
            result_gdf.loc[idx, 'fuehr'] = 'Radfahrstreifen (OSM:Schutzstreifen an Haltestelle)'
            converted_count += 1
    
    # 5. Statistiken ausgeben
    logger.info("=" * 60)
    logger.info("KONVERTIERUNG ABGESCHLOSSEN:")
    logger.info(f"Bushaltestellen: {len(bus_stops_gdf)}")
    logger.info(f"Schutzstreifen in {buffer_distance}m Umkreis: {len(schutzstreifen_near_stops)}")
    logger.info(f"Davon an Radfahrstreifen angrenzend: {len(schutzstreifen_to_convert)}")
    logger.info(f"Erfolgreich konvertiert: {converted_count}")
    logger.info("Neue Führungsform: 'Radfahrstreifen (OSM:Schutzstreifen an Haltestelle)'")
    logger.info("=" * 60)
    
    return result_gdf

def convert_schutzstreifen_at_bus_stops_with_gdf(gdf, bus_stops_gdf, 
                                               buffer_distance=20.0, tolerance=0.1):
    """
    Konvertiert Schutzstreifen zu Radfahrstreifen an Bushaltestellen.
    Verwendet ein bereits geladenes GeoDataFrame mit Bushaltestellen.
    
    Args:
        gdf: GeoDataFrame mit allen Straßendaten
        bus_stops_gdf: GeoDataFrame mit Bushaltestellen
        buffer_distance: Suchradius um Bushaltestellen in Metern
        tolerance: Toleranz für Angrenzungsprüfung in Metern
    
    Returns:
        GeoDataFrame: Bearbeitete Daten mit konvertierten Schutzstreifen
    """
    logger.info("=" * 60)
    logger.info("KONVERTIERUNG: SCHUTZSTREIFEN ZU RADFAHRSTREIFEN AN BUSHALTESTELLEN")
    logger.info("=" * 60)
    
    # Kopie erstellen um Original nicht zu verändern
    result_gdf = gdf.copy()
    
    if bus_stops_gdf is None or len(bus_stops_gdf) == 0:
        logger.warning("Konvertierung übersprungen: Keine Bushaltestellen verfügbar")
        return result_gdf
    
    logger.info(f"Bushaltestellen geladen: {len(bus_stops_gdf)} Haltestellen")
    
    # 2. Schutzstreifen in der Nähe von Bushaltestellen finden
    schutzstreifen_near_stops = find_schutzstreifen_near_bus_stops(
        result_gdf, bus_stops_gdf, buffer_distance
    )
    
    if len(schutzstreifen_near_stops) == 0:
        logger.info("Keine Schutzstreifen in der Nähe von Bushaltestellen gefunden")
        return result_gdf
    
    # 3. Schutzstreifen finden, die an Radfahrstreifen angrenzen
    schutzstreifen_to_convert = find_schutzstreifen_adjacent_to_radfahrstreifen(
        schutzstreifen_near_stops, result_gdf, tolerance
    )
    
    if len(schutzstreifen_to_convert) == 0:
        logger.info("Keine Schutzstreifen gefunden, die beide Bedingungen erfüllen")
        return result_gdf
    
    # 4. Konvertierung durchführen
    logger.info(f"Konvertiere {len(schutzstreifen_to_convert)} Schutzstreifen...")
    
    converted_count = 0
    for idx in schutzstreifen_to_convert.index:
        if result_gdf.loc[idx, 'fuehr'] == 'Schutzstreifen':
            result_gdf.loc[idx, 'fuehr'] = 'Radfahrstreifen (OSM:Schutzstreifen an Haltestelle)'
            converted_count += 1
    
    # 5. Statistiken ausgeben
    logger.info("=" * 60)
    logger.info("KONVERTIERUNG ABGESCHLOSSEN:")
    logger.info(f"Bushaltestellen: {len(bus_stops_gdf)}")
    logger.info(f"Schutzstreifen in {buffer_distance}m Umkreis: {len(schutzstreifen_near_stops)}")
    logger.info(f"Davon an Radfahrstreifen angrenzend: {len(schutzstreifen_to_convert)}")
    logger.info(f"Erfolgreich konvertiert: {converted_count}")
    logger.info("Neue Führungsform: 'Radfahrstreifen (OSM:Schutzstreifen an Haltestelle)'")
    logger.info("=" * 60)
    
    return result_gdf

# Hauptfunktion für externe Verwendung (analog zur bestehenden convert_short_schutzstreifen_to_radfahrstreifen)
def convert_schutzstreifen_at_bus_stops_main(gdf, bus_stops_gdf=None, bus_stops_path="output/bus_stops_on_rvn.fgb", 
                                            buffer_distance=20.0, tolerance=0.1):
    """
    Wrapper-Funktion für die Integration in den Processing-Pipeline.
    
    Args:
        gdf: GeoDataFrame mit Straßennetzwerk-Daten
        bus_stops_gdf: Optional - bereits geladenes GeoDataFrame mit Bushaltestellen
        bus_stops_path: Pfad zu Bushaltestellen-Datei (falls bus_stops_gdf nicht gegeben)
        buffer_distance: Suchradius um Bushaltestellen (Standard: 20m)
        tolerance: Toleranz für Angrenzung (Standard: 0.1m)
    
    Returns:
        GeoDataFrame: Modifizierte Daten mit konvertierten Schutzstreifen
    """
    if bus_stops_gdf is not None:
        # Verwende direkt übergebenes GeoDataFrame
        return convert_schutzstreifen_at_bus_stops_with_gdf(gdf, bus_stops_gdf, buffer_distance, tolerance)
    else:
        # Lade von Pfad
        return convert_schutzstreifen_at_bus_stops(gdf, bus_stops_path, buffer_distance, tolerance)
