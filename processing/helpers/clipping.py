#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
clipping.py
-----------
Helper-Funktionen für das Zuschneiden von Geodaten auf bestimmte Gebiete.
"""

import logging
import os
import geopandas as gpd


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
