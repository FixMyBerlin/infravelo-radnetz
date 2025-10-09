#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bus_stop_side_detection.py
--------------------------------------------------------------------
Funktionen zur Bestimmung auf welcher Seite einer Straße sich eine Bushaltestelle befindet.

In Deutschland haben wir Rechtsverkehr, daher befinden sich Bushaltestellen
auf der rechten Seite in Fahrtrichtung. Diese Funktion ermittelt, ob eine
Haltestelle rechts von einer gerichteten Kante liegt.

Verwendung:
- Für die Schutzstreifen-Konvertierung an Bushaltestellen
- Berücksichtigt die Fahrtrichtung (ri-Attribut: 0=HIN, 1=RÜCK)
"""

import logging
import numpy as np
from shapely.geometry import LineString, MultiLineString

logger = logging.getLogger(__name__)


def get_line_direction_vector(geometry, at_position=0.5):
    """
    Ermittelt den Richtungsvektor einer Linie an einer bestimmten Position.
    
    Args:
        geometry: LineString oder MultiLineString
        at_position: Position entlang der Linie (0.0 = Start, 1.0 = Ende)
        
    Returns:
        tuple: (dx, dy) Richtungsvektor, oder None bei Fehler
    """
    try:
        if isinstance(geometry, MultiLineString):
            # Bei MultiLineString: Verwende die erste Teil-Linie
            if len(geometry.geoms) == 0:
                return None
            line = geometry.geoms[0]
        else:
            line = geometry
        
        # Interpoliere Position entlang der Linie
        point_on_line = line.interpolate(at_position, normalized=True)
        
        # Finde nächsten Punkt vorwärts (kleines Delta)
        delta = 0.01  # 1% der Linienlänge
        next_position = min(at_position + delta, 1.0)
        next_point = line.interpolate(next_position, normalized=True)
        
        # Berechne Richtungsvektor
        dx = next_point.x - point_on_line.x
        dy = next_point.y - point_on_line.y
        
        # Normalisiere
        length = np.sqrt(dx**2 + dy**2)
        if length > 0:
            dx /= length
            dy /= length
            
        return (dx, dy)
        
    except Exception as e:
        logger.warning(f"Fehler beim Ermitteln des Richtungsvektors: {e}")
        return None


def is_point_on_right_side(point_geometry, line_geometry, tolerance=20.0):
    """
    Prüft ob ein Punkt rechts von einer gerichteten Linie liegt.
    
    Verwendet das Kreuzprodukt um die Seite zu bestimmen:
    - Kreuzprodukt > 0: Punkt liegt links
    - Kreuzprodukt < 0: Punkt liegt rechts
    - Kreuzprodukt ≈ 0: Punkt liegt auf der Linie
    
    Args:
        point_geometry: Point-Geometrie der Bushaltestelle
        line_geometry: LineString/MultiLineString der Straßenkante
        tolerance: Maximale Entfernung zum Betrachten (in Metern)
        
    Returns:
        bool: True wenn Punkt rechts der Linie liegt, False sonst
    """
    try:
        # Prüfe ob Punkt nah genug ist
        distance = point_geometry.distance(line_geometry)
        if distance > tolerance:
            return False
        
        # Finde nächsten Punkt auf der Linie
        nearest_point_on_line = line_geometry.interpolate(
            line_geometry.project(point_geometry)
        )
        
        # Ermittle Richtungsvektor an dieser Stelle
        # Verwende normalisierte Position
        position = line_geometry.project(point_geometry, normalized=True)
        direction = get_line_direction_vector(line_geometry, position)
        
        if direction is None:
            return False
        
        dx, dy = direction
        
        # Vektor vom Linienpunkt zum Haltestellen-Punkt
        to_point_x = point_geometry.x - nearest_point_on_line.x
        to_point_y = point_geometry.y - nearest_point_on_line.y
        
        # Kreuzprodukt: z-Komponente von (direction × to_point)
        # In 2D: cross_z = dx * to_point_y - dy * to_point_x
        cross_product = dx * to_point_y - dy * to_point_x
        
        # Rechts = negatives Kreuzprodukt (in mathematisch positiver Drehrichtung)
        is_right = cross_product < 0
        
        logger.debug(f"Punkt-Linien-Distanz: {distance:.2f}m, "
                    f"Kreuzprodukt: {cross_product:.6f}, "
                    f"Seite: {'rechts' if is_right else 'links'}")
        
        return is_right
        
    except Exception as e:
        logger.warning(f"Fehler bei Seitenprüfung: {e}")
        return False


def has_bus_stop_on_right_side(geometry, bus_stops_gdf, ri, buffer_distance=20.0):
    """
    Prüft ob eine Geometrie Bushaltestellen auf der rechten Seite hat.
    
    Wichtig: Bei ri=1 ist die Fahrtrichtung entgegengesetzt zur Geometrie-Richtung,
    daher invertieren wir die Seitendefinition (was geometrisch links ist, ist
    fahrtrichtungsmäßig rechts).
    
    Args:
        geometry: LineString (oder MultiLineString bei Gesamtprüfung)
        bus_stops_gdf: GeoDataFrame mit Bushaltestellen
        ri: Richtung (0=HIN, 1=RÜCK)
        buffer_distance: Puffer-Distanz für Haltestellen-Suche
        
    Returns:
        bool: True wenn mindestens eine Haltestelle auf rechter Seite liegt
    """
    # Finde Haltestellen im Umkreis
    buffer = geometry.buffer(buffer_distance)
    nearby_stops = bus_stops_gdf[bus_stops_gdf.geometry.intersects(buffer)]
    
    if len(nearby_stops) == 0:
        return False
    
    # Prüfe ob mindestens eine Haltestelle auf rechter Seite liegt
    # Bei ri=1: Invertiere das Ergebnis, da Fahrtrichtung entgegengesetzt
    for _, stop in nearby_stops.iterrows():
        is_right = is_point_on_right_side(stop.geometry, geometry, buffer_distance)
        
        # Bei ri=1 (RÜCK): Was geometrisch links ist, ist fahrtrichtungsmäßig rechts
        if ri == 1:
            is_right = not is_right
        
        if is_right:
            return True
    
    return False


def filter_bus_stops_by_side(schutzstreifen_row, bus_stops_gdf, buffer_distance=20.0):
    """
    Filtert Bushaltestellen die auf der rechten Seite (Fahrtrichtung) 
    eines Schutzstreifens liegen.
    
    Bei ri=1 ist die Fahrtrichtung entgegengesetzt zur Geometrie-Richtung,
    daher invertieren wir die Seitendefinition.
    
    Args:
        schutzstreifen_row: Pandas Series mit Schutzstreifen-Daten (inkl. geometry, ri)
        bus_stops_gdf: GeoDataFrame mit allen Bushaltestellen
        buffer_distance: Maximale Entfernung für Haltestellen (in Metern)
        
    Returns:
        GeoDataFrame: Gefilterte Bushaltestellen auf der richtigen Seite
    """
    try:
        geometry = schutzstreifen_row.geometry
        ri = schutzstreifen_row.get('ri', None)
        
        # Finde Haltestellen im Umkreis
        buffer = geometry.buffer(buffer_distance)
        nearby_stops = bus_stops_gdf[bus_stops_gdf.geometry.intersects(buffer)].copy()
        
        if len(nearby_stops) == 0:
            return nearby_stops
        
        # Prüfe für jede Haltestelle, ob sie rechts liegt
        # Bei ri=1: Invertiere das Ergebnis, da Fahrtrichtung entgegengesetzt
        def check_side(point):
            is_right = is_point_on_right_side(point, geometry, buffer_distance)
            # Bei ri=1 (RÜCK): Was geometrisch links ist, ist fahrtrichtungsmäßig rechts
            if ri == 1:
                is_right = not is_right
            return is_right
        
        right_side_mask = nearby_stops.geometry.apply(check_side)
        
        filtered_stops = nearby_stops[right_side_mask].copy()
        
        logger.debug(f"Schutzstreifen sfid={schutzstreifen_row.get('sfid', '?')}, ri={ri}: "
                    f"{len(nearby_stops)} Haltestellen im Umkreis, "
                    f"{len(filtered_stops)} auf der rechten Seite")
        
        return filtered_stops
        
    except Exception as e:
        logger.warning(f"Fehler beim Filtern von Bushaltestellen nach Seite: {e}")
        return bus_stops_gdf.iloc[0:0]  # Leeres GeoDataFrame
