#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
clipping.py
-----------
Helper-Funktionen für das Zuschneiden von Geodaten auf bestimmte Gebiete.
"""

import logging
import os
import math
from typing import Tuple
import geopandas as gpd
from shapely.geometry import box, Polygon
from pyproj import Transformer
from pyproj import Transformer


def clip_to_neukoelln(gdf: gpd.GeoDataFrame, data_dir: str, crs: str, boundary_file: str = "Bezirk Neukölln Grenze.fgb") -> gpd.GeoDataFrame:
    """
    Schneidet die Geodaten auf die Grenzen von Neukölln zu.
    
    Args:
        gdf: GeoDataFrame mit den zu zuschneidenden Daten
        data_dir: Verzeichnis mit den Eingabedateien
        crs: Ziel-Koordinatensystem
        boundary_file: Name der Grenzendatei (default: "Bezirk Neukölln Grenze.fgb")
    
    Returns:
        Zugeschnittenes GeoDataFrame
    """
    
    # Pfad zur Neukölln-Grenzendatei
    boundary_path = os.path.join(data_dir, boundary_file)
    
    if not os.path.exists(boundary_path):
        logging.warning(f"Neukölln-Grenzendatei nicht gefunden: {boundary_path}")
        logging.warning("Überspringe Clipping - verwende vollständige Daten")
        return gdf
    
    try:
        logging.info(f"Lade Neukölln-Grenzen: {boundary_path}")
        clip_polygons = gpd.read_file(boundary_path)
        
        # Koordinatensystem vereinheitlichen
        if gdf.crs != clip_polygons.crs:
            logging.info("Transformiere Koordinatensystem für Clipping")
            gdf = gdf.to_crs(clip_polygons.crs)
        
        # Fasse alle Polygone zu einer einzigen Geometrie zusammen
        logging.info("Schneide Daten auf Neukölln zu")
        clip_boundary = clip_polygons.unary_union
        
        # Führe den Zuschnitt durch
        clipped_gdf = gdf.clip(clip_boundary)
        
        # Zurück zum gewünschten CRS
        if clipped_gdf.crs != crs:
            clipped_gdf = clipped_gdf.to_crs(crs)
        
        logging.info(f"Clipping abgeschlossen: {len(gdf)} → {len(clipped_gdf)} Features")
        return clipped_gdf
        
    except Exception as e:
        logging.error(f"Fehler beim Clipping: {e}")
        logging.warning("Überspringe Clipping - verwende vollständige Daten")
        return gdf


def parse_view_string(view: str) -> Tuple[int, float, float]:
    """Parst eine View-String Angabe im Format 'zoom/lat/lon'.

    Args:
        view: String wie aus einer OSM URL z.B. "18/52.488306/13.425140"

    Returns:
        Tuple (zoom, lat, lon)

    Raises:
        ValueError bei ungültigem Format oder Werten.
    """
    parts = view.strip().split('/')
    if len(parts) != 3:
        raise ValueError("Viewport muss Format 'zoom/lat/lon' haben (z.B. 18/52.4883/13.42514)")
    try:
        zoom = int(parts[0])
        lat = float(parts[1])
        lon = float(parts[2])
    except ValueError as e:
        raise ValueError("Viewport Werte konnten nicht geparst werden (erwartet int/float)") from e
    if not (-85 <= lat <= 85):  # Web Mercator Begrenzung
        raise ValueError("Latitude außerhalb des gültigen Bereichs für Web Mercator (-85..85)")
    if not (-180 <= lon <= 180):
        raise ValueError("Longitude muss zwischen -180 und 180 liegen")
    if not (0 <= zoom <= 23):
        raise ValueError("Zoom muss zwischen 0 und 23 liegen")
    return zoom, lat, lon


def viewport_to_polygon(view: str, screen_width: int = 1920, screen_height: int = 1080) -> Polygon:
    """Erzeugt ein Bounding-Box Polygon (EPSG:4326) aus einer OSM View Angabe.

    Es wird ein Standard-Viewport von screen_width x screen_height Pixeln angenommen.
    Berechnung basiert auf Web Mercator (EPSG:3857) Metrik und konvertiert zurück nach WGS84.

    Args:
        view: String 'zoom/lat/lon'
        screen_width: Bildschirmbreite in Pixeln (Default 1920)
        screen_height: Bildschirmhöhe in Pixeln (Default 1080)

    Returns:
        Shapely Polygon in EPSG:4326
    """
    z, lat, lon = parse_view_string(view)

    # Web Mercator Konstanten
    origin_shift = 20037508.342789244
    initial_resolution = 2 * math.pi * 6378137 / 256.0  # Meter / Pixel bei Zoom 0
    res = initial_resolution / (2 ** z)

    half_w_m = (screen_width / 2.0) * res
    half_h_m = (screen_height / 2.0) * res

    # WGS84 -> Web Mercator
    def lonlat_to_merc(lon_deg: float, lat_deg: float) -> Tuple[float, float]:
        x_m = lon_deg * origin_shift / 180.0
        # Clamp lat für numerische Stabilität
        lat_deg = max(min(lat_deg, 89.9), -89.9)
        y_m = math.log(math.tan((90 + lat_deg) * math.pi / 360.0)) * origin_shift / math.pi
        return x_m, y_m

    cx, cy = lonlat_to_merc(lon, lat)
    minx_m = cx - half_w_m
    maxx_m = cx + half_w_m
    miny_m = cy - half_h_m
    maxy_m = cy + half_h_m

    # Web Mercator -> WGS84 Transformer (präziser als die umgekehrte Formeln hier selbst zu implementieren)
    transformer = Transformer.from_crs(3857, 4326, always_xy=True)
    # Eckpunkte transformieren
    bl_lon, bl_lat = transformer.transform(minx_m, miny_m)
    tr_lon, tr_lat = transformer.transform(maxx_m, maxy_m)

    # Box normalisieren (min < max)
    min_lon, max_lon = sorted([bl_lon, tr_lon])
    min_lat, max_lat = sorted([bl_lat, tr_lat])

    return box(min_lon, min_lat, max_lon, max_lat)


def clip_to_view(gdf: gpd.GeoDataFrame, view: str, target_crs: str, screen_width: int = 1920, screen_height: int = 1080) -> gpd.GeoDataFrame:
    """Schneidet ein GeoDataFrame auf einen Viewport (zoom/lat/lon) zu.

    Workflow:
      1. Erzeuge Bounding Box in EPSG:4326
      2. Transformiere gdf (falls nötig) nach 4326
      3. Clip
      4. Transformiere zurück in target_crs

    Args:
        gdf: Eingangs GeoDataFrame
        view: String "z/lat/lon"
        target_crs: Ausgabekoordinatensystem (z.B. EPSG:25833)
        screen_width: angenommene Bildschirmbreite
        screen_height: angenommene Bildschirmhöhe

    Returns:
        Zugeschnittenes GeoDataFrame
    """
    try:
        bbox_wgs84 = viewport_to_polygon(view, screen_width, screen_height)
    except ValueError as e:
        logging.error(f"Ungültiger Viewport: {e}")
        raise

    # Transformiere Daten nach WGS84 für Clip wenn nötig
    original_crs = gdf.crs
    if original_crs is None:
        logging.warning("GeoDataFrame hat kein CRS – Clip kann zu falschen Ergebnissen führen")
    if original_crs != 'EPSG:4326':
        gdf = gdf.to_crs('EPSG:4326')

    clipped = gdf.clip(bbox_wgs84)

    # Transformiere zurück
    if target_crs and clipped.crs != target_crs:
        clipped = clipped.to_crs(target_crs)

    logging.info(f"Viewport-Clipping ({view}) abgeschlossen: {len(gdf)} → {len(clipped)} Features")
    return clipped
