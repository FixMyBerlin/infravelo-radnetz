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
from shapely.geometry import Point, MultiLineString
from .progressbar import print_progressbar
from .schutzstreifen_conversion_helper import (
    get_endpoints, 
    find_adjacent_radfahrstreifen_simple,
    find_schutzstreifen_adjacent_to_radfahrstreifen
)

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
    # TODO Sollten beide DEFAULT_CRS aus globals.py sein.
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

def find_adjacent_radfahrstreifen(schutzstreifen_row, all_ways_gdf, tolerance=1.0):
    """Prüfe ob ein Schutzstreifen an Radfahrstreifen angrenzt."""
    return find_adjacent_radfahrstreifen_simple(schutzstreifen_row, all_ways_gdf, tolerance)

def find_schutzstreifen_adjacent_to_radfahrstreifen_local(schutzstreifen_near_stops, all_ways_gdf, tolerance=1.0):
    """Finde Schutzstreifen die an Radfahrstreifen angrenzen."""
    logger.info("Prüfe welche Schutzstreifen an Radfahrstreifen angrenzen...")
    
    # Verwende die ausgelagerte Funktion mit Progress-Callback
    return find_schutzstreifen_adjacent_to_radfahrstreifen(
        schutzstreifen_near_stops, 
        all_ways_gdf, 
        tolerance, 
        progress_callback=print_progressbar
    )


def convert_schutzstreifen_at_bus_stops_with_gdf(gdf, bus_stops_gdf, 
                                               buffer_distance=20.0, tolerance=1.0):
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
    schutzstreifen_to_convert = find_schutzstreifen_adjacent_to_radfahrstreifen_local(
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
                                            buffer_distance=20.0, tolerance=1.0):
    """
    Wrapper-Funktion für die Integration in den Processing-Pipeline.
    
    Args:
        gdf: GeoDataFrame mit Straßennetzwerk-Daten
        bus_stops_gdf: Optional - bereits geladenes GeoDataFrame mit Bushaltestellen
        bus_stops_path: Pfad zu Bushaltestellen-Datei (falls bus_stops_gdf nicht gegeben)
        buffer_distance: Suchradius um Bushaltestellen (Standard: 20m)
        tolerance: Toleranz für Angrenzung (Standard: 1.0m)
    
    Returns:
        GeoDataFrame: Modifizierte Daten mit konvertierten Schutzstreifen
    """
    return convert_schutzstreifen_at_bus_stops_with_gdf(gdf, bus_stops_gdf, buffer_distance, tolerance)