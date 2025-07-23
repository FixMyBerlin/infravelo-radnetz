# -*- coding: utf-8 -*-
"""
buffer_utils.py
Hilfsfunktionen für das Erstellen von Buffern um Geodaten.

INPUT:
- Beliebiges GeoDataFrame mit Geometrien

OUTPUT:
- Gebufferte Geometrien als GeoDataFrame oder unified buffer geometry
"""

import geopandas as gpd
import os
import logging


def create_unified_buffer(vorrangnetz_gdf, buffer_meters, target_crs, cache_dir="./output/matching", cap_style='flat'):
    """
    Erzeugt einen vereinheitlichten Buffer um das Vorrangnetz.
    Verwendet Caching basierend auf der Buffer-Größe um mehrfache Berechnungen zu vermeiden.
    
    Args:
        vorrangnetz_gdf (GeoDataFrame): Das Vorrangnetz als GeoDataFrame
        buffer_meters (int): Buffer-Radius in Metern
        target_crs (str): Ziel-Koordinatensystem (z.B. 'EPSG:25833')
        cache_dir (str): Verzeichnis für Cache-Dateien
        cap_style (str): Cap-Style für Buffer ('flat' oder 'round')
        
    Returns:
        tuple: (unified_buffer, buffered_gdf) - Die vereinte Buffer-Geometrie und das GeoDataFrame
    """
    # Erstelle Cache-Pfad mit Buffer-Größe und Cap-Style im Dateinamen
    cache_file = os.path.join(cache_dir, f'vorrangnetz_buffered_{buffer_meters}m_{cap_style}.fgb')
    os.makedirs(cache_dir, exist_ok=True)
    
    # Prüfe, ob Buffer bereits existiert
    if os.path.exists(cache_file):
        logging.info(f'Lade bereits berechneten {buffer_meters}m Buffer aus {cache_file}...')
        buffered_gdf = gpd.read_file(cache_file)
        
        # Stelle sicher, dass das CRS des geladenen Buffers korrekt ist
        if buffered_gdf.crs != target_crs:
            logging.info(f'Transformiere Buffer-CRS von {buffered_gdf.crs} zu {target_crs}...')
            buffered_gdf = buffered_gdf.to_crs(target_crs)
        
        unified_buffer = buffered_gdf.geometry.iloc[0]
        logging.info(f'Buffer von {buffer_meters}m erfolgreich geladen.')
        return unified_buffer, buffered_gdf
    
    # Buffer muss neu berechnet werden
    logging.info(f'Erzeuge Buffer von {buffer_meters}m um Vorrangnetz-Kanten (cap_style: {cap_style})...')
    vorrangnetz_buffer = vorrangnetz_gdf.buffer(buffer_meters, cap_style=cap_style)
    logging.info('Vereine alle Buffer zu einer einzigen Geometrie...')
    unified_buffer = vorrangnetz_buffer.union_all()
    
    # Speichere den berechneten Buffer für zukünftige Verwendung
    buffered_gdf = gpd.GeoDataFrame(geometry=[unified_buffer], crs=target_crs)
    buffered_gdf.to_file(cache_file, driver='FlatGeobuf')
    logging.info(f'Gebuffertes Vorrangnetz gespeichert als {cache_file}')
    
    return unified_buffer, buffered_gdf
