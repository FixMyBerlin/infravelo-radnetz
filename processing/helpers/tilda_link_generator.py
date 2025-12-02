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
        geometry: LineString oder MultiLineString Geometrie (in beliebigem CRS)
        zoom: Zoom-Level für die Karte (Standard: 17.4)
        dataset: Datensatz-Identifier (Standard: "infravelo-datensatz-b-fortlaufend")
        
    Returns:
        str: Vollständiger TILDA-Link oder None bei Fehlern
    """
    try:
        # Transformiere Geometrie nach WGS84 (EPSG:4326) falls nötig
        # TILDA-Links benötigen Lat/Lng Koordinaten
        import geopandas as gpd
        from shapely.geometry import mapping
        
        # Erstelle temporäres GeoDataFrame um CRS-Transformation zu nutzen
        temp_gdf = gpd.GeoDataFrame([{'geometry': geometry}], crs=None)
        
        # Versuche das CRS zu ermitteln - wenn die Geometrie bereits aus einem GeoDataFrame kommt,
        # sollte sie ein CRS haben. Falls nicht, gehen wir davon aus, dass es schon WGS84 ist.
        # Typischerweise kommt die Geometrie hier aus EPSG:25833 (UTM Zone 33N)
        if hasattr(geometry, '__geo_interface__'):
            # Shapely-Geometrie ohne CRS-Info
            # Wir nehmen an, dass die Koordinaten in EPSG:25833 sind (Standard für Berlin)
            temp_gdf = gpd.GeoDataFrame([{'geometry': geometry}], crs='EPSG:25833')
        
        # Transformiere zu WGS84
        temp_gdf_wgs84 = temp_gdf.to_crs('EPSG:4326')
        geometry_wgs84 = temp_gdf_wgs84.iloc[0].geometry
        
        # Berechne Mittelpunkt der transformierten Geometrie
        centroid = calculate_geometry_centroid(geometry_wgs84)
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
        
    except Exception as e:
        logging.warning(f"Fehler bei TILDA-Link-Generierung: {e}")
        return None


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


def extract_mapillary_key(row: dict) -> str:
    """
    Extrahiert den Mapillary-Key aus den verfügbaren Attributen.
    Priorität: tilda_mapillary > tilda_width_source > tilda_mapillary_traffic_sign
    
    Args:
        row: Dictionary mit TILDA-Attributen
        
    Returns:
        str: Mapillary-Key oder None
    """
    # Priorität 1: tilda_mapillary (Hauptattribut)
    mapillary = row.get('tilda_mapillary')
    if mapillary and str(mapillary).strip() and str(mapillary).strip().lower() not in ['none', 'nan', '']:
        return str(mapillary).strip()
    
    # Priorität 2: tilda_width_source (Mapillary-Key von Breitenquelle)
    width_source = row.get('tilda_width_source')
    if width_source and str(width_source).strip() and str(width_source).strip().lower() not in ['none', 'nan', '']:
        return str(width_source).strip()
    
    # Priorität 3: tilda_mapillary_traffic_sign (Mapillary-Key von Verkehrszeichen)
    traffic_sign = row.get('tilda_mapillary_traffic_sign')
    if traffic_sign and str(traffic_sign).strip() and str(traffic_sign).strip().lower() not in ['none', 'nan', '']:
        return str(traffic_sign).strip()
    
    return None


def generate_tilda_mapillary_link(row: dict, geometry) -> str:
    """
    Generiert einen TILDA-Mapillary-Link basierend auf dem Mapillary-Key und der Geometrie.
    
    URL-Struktur:
    https://tilda-geo.de/regionen/infravelo?map=18.8/<lat>/<lng>&config=l6jzgk.5ount5.5&f=21|<mapillary_key>|<lng>|<lat>&bg=areal2025-summer&v=2
    
    Args:
        row: Dictionary mit TILDA-Attributen (tilda_mapillary, tilda_width_source, tilda_mapillary_traffic_sign)
        geometry: LineString oder MultiLineString Geometrie
        
    Returns:
        str: Vollständiger TILDA-Mapillary-Link oder None
    """
    try:
        # Extrahiere Mapillary-Key
        mapillary_key = extract_mapillary_key(row)
        if not mapillary_key:
            return None
        
        # Transformiere Geometrie nach WGS84 (EPSG:4326)
        import geopandas as gpd
        
        temp_gdf = gpd.GeoDataFrame([{'geometry': geometry}], crs='EPSG:25833')
        temp_gdf_wgs84 = temp_gdf.to_crs('EPSG:4326')
        geometry_wgs84 = temp_gdf_wgs84.iloc[0].geometry
        
        # Berechne Mittelpunkt
        centroid = calculate_geometry_centroid(geometry_wgs84)
        if not centroid:
            return None
        
        center_lng, center_lat = centroid
        
        # Baue vollständigen URL
        # Format: map=zoom/lat/lng, f=21|mapillary_key|lng|lat
        base_url = "https://tilda-geo.de/regionen/infravelo"
        map_param = f"map=18.8/{center_lat}/{center_lng}"
        config_param = "config=l6jzgk.5ount5.5"
        feature_param = f"f=21|{mapillary_key}|{center_lng}|{center_lat}"
        bg_param = "bg=areal2025-summer"
        version_param = "v=2"
        
        full_url = f"{base_url}?{map_param}&{config_param}&{feature_param}&{bg_param}&{version_param}"
        
        return full_url
        
    except Exception as e:
        logging.warning(f"Fehler bei TILDA-Mapillary-Link-Generierung: {e}")
        return None
