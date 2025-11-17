#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tilda_link_generator.py
--------------------------------------------------------------------
Hilfsfunktionen zum Generieren von TILDA-Links.

TILDA URL Struktur:
https://tilda-geo.de/regionen/infravelo?map=11.4/<lat>/<lng>&data=infravelo-datensatz-b-fortlaufend

Die URL verwendet den Mittelpunkt der Geometrie und einen festen Zoom-Level von 11.4,
ohne ein spezifisches Feature auszuwählen.

Beispiel:
https://tilda-geo.de/regionen/infravelo?map=11.4/52.434453/13.342577&data=infravelo-datensatz-b-fortlaufend
"""

import logging
from shapely.geometry import LineString, MultiLineString


def calculate_geometry_centroid(geometry) -> tuple:
    """
    Berechnet den Mittelpunkt einer Geometrie.
    
    Args:
        geometry: LineString oder MultiLineString
        
    Returns:
        tuple: (lng, lat) mit 6 Dezimalstellen gerundet, oder None bei Fehler
    """
    try:
        if isinstance(geometry, MultiLineString):
            # Bei MultiLineString alle Koordinaten sammeln
            all_coords = []
            for line in geometry.geoms:
                all_coords.extend(list(line.coords))
        elif hasattr(geometry, 'coords'):
            all_coords = list(geometry.coords)
        else:
            logging.warning("Ungültige Geometrie für Mittelpunkt-Berechnung")
            return None
        
        if len(all_coords) < 1:
            logging.warning("Geometrie hat keine Koordinaten")
            return None
        
        # Berechne Mittelpunkt als Durchschnitt aller Koordinaten
        lngs = [coord[0] for coord in all_coords]
        lats = [coord[1] for coord in all_coords]
        
        center_lng = round(sum(lngs) / len(lngs), 6)
        center_lat = round(sum(lats) / len(lats), 6)
        
        return (center_lng, center_lat)
        
    except Exception as e:
        logging.warning(f"Fehler bei Mittelpunkt-Berechnung: {e}")
        return None


def generate_tilda_link(geometry, zoom: float = 17.4, dataset: str = "infravelo-datensatz-b-fortlaufend") -> str:
    """
    Generiert einen TILDA-Link basierend auf der Geometrie.
    
    Args:
        geometry: LineString oder MultiLineString Geometrie
        zoom: Zoom-Level für die Karte (Standard: 17.4)
        dataset: Datensatz-Identifier (Standard: "infravelo-datensatz-b-fortlaufend")
        
    Returns:
        str: Vollständiger TILDA-Link oder None bei Fehlern
    """
    # Berechne Mittelpunkt der Geometrie
    centroid = calculate_geometry_centroid(geometry)
    if not centroid:
        return None
    
    center_lng, center_lat = centroid
    
    # Baue vollständigen URL
    base_url = "https://tilda-geo.de/regionen/infravelo"
    # Format: map=zoom/lat/lng
    map_param = f"map={zoom}/{center_lat}/{center_lng}"
    data_param = f"data={dataset}"
    full_url = f"{base_url}?{map_param}&{data_param}"
    
    return full_url


def generate_snapping_tilda_link(tilda_id: str, geometry) -> str:
    """
    Generiert einen TILDA-Link für den Snapping-Datensatz.
    
    Args:
        tilda_id: TILDA-ID (wird für Kompatibilität beibehalten, aber nicht verwendet)
        geometry: LineString oder MultiLineString
        
    Returns:
        str: TILDA-Link oder None
    """
    return generate_tilda_link(geometry, dataset="infravelo-datensatz-b-fortlaufend")


def generate_aggregation_tilda_link(tilda_id: str, geometry) -> str:
    """
    Generiert einen TILDA-Link für den Aggregations-Datensatz.
    
    Args:
        tilda_id: TILDA-ID (wird für Kompatibilität beibehalten, aber nicht verwendet)
        geometry: LineString oder MultiLineString
        
    Returns:
        str: TILDA-Link oder None
    """
    return generate_tilda_link(geometry, dataset="infravelo-datensatz-c-fortlaufend")
