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


def clip_to_region(gdf: gpd.GeoDataFrame, data_dir: str, crs: str, region: str) -> gpd.GeoDataFrame:
    """
    Schneidet die Geodaten auf eine bestimmte Region zu.
    
    Args:
        gdf: GeoDataFrame mit den zu zuschneidenden Daten
        data_dir: Verzeichnis mit den Eingabedateien
        crs: Ziel-Koordinatensystem
        region: Name der Region ('neukoelln', 'norden', 'sueden')
    
    Returns:
        Zugeschnittenes GeoDataFrame
    """
    # Mapping von Region zu Dateiname
    region_files = {
        'neukoelln': 'Bezirk Neukölln Grenze.fgb',
        'norden': 'Berlin_Gebiet_Norden.gpkg',
        'sueden': 'Berlin_Gebiet_Süden.gpkg'
    }
    
    if region not in region_files:
        logging.error(f"Unbekannte Region: {region}. Erlaubt sind: {', '.join(region_files.keys())}")
        return gdf
    
    boundary_file = region_files[region]
    boundary_path = os.path.join(data_dir, boundary_file)
    
    if not os.path.exists(boundary_path):
        logging.warning(f"Grenzendatei für {region} nicht gefunden: {boundary_path}")
        logging.warning("Überspringe Clipping - verwende vollständige Daten")
        return gdf
    
    try:
        logging.info(f"Lade Grenzen für {region}: {boundary_path}")
        clip_polygons = gpd.read_file(boundary_path)
        
        # Koordinatensystem vereinheitlichen
        if gdf.crs != clip_polygons.crs:
            logging.info("Transformiere Koordinatensystem für Clipping")
            gdf = gdf.to_crs(clip_polygons.crs)
        
        # Fasse alle Polygone zu einer einzigen Geometrie zusammen
        logging.info(f"Schneide Daten auf {region} zu")
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
