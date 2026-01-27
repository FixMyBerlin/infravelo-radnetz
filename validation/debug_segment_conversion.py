#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
debug_segment_conversion.py
--------------------------------------------------------------------
Debug-Tool zur Analyse warum ein spezifisches Segment nicht konvertiert wurde.
"""

import os
import sys
import logging
import geopandas as gpd
import pandas as pd
import numpy as np
from shapely.geometry import Point

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def calculate_segment_overlap_with_buffer(segment_geometry, buffer_geometry):
    """Berechnet Überlappungs-Anteil"""
    if segment_geometry.length == 0:
        return 0.0
    
    intersection = segment_geometry.intersection(buffer_geometry)
    
    if intersection.is_empty:
        return 0.0
    elif intersection.geom_type == 'LineString':
        overlap_length = intersection.length
    elif intersection.geom_type == 'MultiLineString':
        overlap_length = sum(line.length for line in intersection.geoms)
    else:
        return 0.0
    
    return overlap_length / segment_geometry.length


def debug_segment(gdf, knotenpunkte_gdf, sfid, old_buffer_radius=25.0, old_min_overlap=0.7):
    """
    Analysiert warum ein spezifisches Segment nicht konvertiert wurde.
    
    Args:
        gdf: GeoDataFrame mit allen Segmenten
        knotenpunkte_gdf: GeoDataFrame mit Knotenpunkten
        sfid: Die sfid des zu untersuchenden Segments
        old_buffer_radius: Alter Buffer-Radius (25m)
        old_min_overlap: Alte Mindestüberlappung (0.7)
    """
    logger.info("=" * 80)
    logger.info(f"DEBUG-ANALYSE für Segment sfid={sfid}")
    logger.info("=" * 80)
    
    # Finde das Segment (sfid kann String oder Int sein)
    segment_row = gdf[gdf['sfid'] == str(sfid)]
    
    if len(segment_row) == 0:
        logger.error(f"Segment mit sfid={sfid} nicht gefunden!")
        return
    
    segment_row = segment_row.iloc[0]
    segment_geom = segment_row.geometry
    segment_length = segment_geom.length
    segment_fuehr = segment_row['fuehr']
    
    logger.info(f"\nSEGMENT-INFORMATION:")
    logger.info(f"  sfid: {sfid}")
    logger.info(f"  Führungsform: {segment_fuehr}")
    logger.info(f"  Länge: {segment_length:.2f}m")
    logger.info(f"  Geometrie-Typ: {segment_geom.geom_type}")
    logger.info(f"  Bounds: {segment_geom.bounds}")
    
    # Prüfe ob es ein Schutzstreifen ist
    if segment_fuehr != 'Schutzstreifen':
        logger.warning(f"⚠ Segment ist KEIN Schutzstreifen, sondern: {segment_fuehr}")
    
    # Prüfe Länge
    if segment_length >= 50.0:
        logger.warning(f"⚠ Segment ist >= 50m lang ({segment_length:.2f}m), daher kein Kandidat")
    
    # Filtere aktive Knotenpunkte
    active_knotenpunkte = knotenpunkte_gdf[
        knotenpunkte_gdf['KP_Nichtbetrachten'] == 0
    ].copy()
    
    logger.info(f"\nKNOTENPUNKTE:")
    logger.info(f"  Total: {len(knotenpunkte_gdf)}")
    logger.info(f"  Aktiv (KP_Nichtbetrachten=0): {len(active_knotenpunkte)}")
    
    # Erstelle Buffer mit alten Parametern
    logger.info(f"\nALTE PARAMETER (aktuell in snapping_with_overrides.fgb):")
    logger.info(f"  Buffer-Radius: {old_buffer_radius}m")
    logger.info(f"  Min. Überlappung: {old_min_overlap * 100}%")
    
    kp_buffers = active_knotenpunkte.copy()
    kp_buffers['buffer_geom'] = kp_buffers.geometry.buffer(old_buffer_radius)
    
    # Finde Knotenpunkte in der Nähe
    segment_bounds = segment_geom.bounds
    search_radius = 100  # Suche im 100m Umkreis
    
    logger.info(f"\nSUCHE KNOTENPUNKTE im {search_radius}m Umkreis...")
    
    # Berechne Distanzen zu allen Knotenpunkten
    distances = []
    for idx, kp_row in active_knotenpunkte.iterrows():
        kp_geom = kp_row.geometry
        dist = segment_geom.distance(kp_geom)
        
        if dist <= search_radius:
            distances.append({
                'kp_idx': idx,
                'distance': dist,
                'kp_id': kp_row.get('KP_Nr', 'N/A'),
                'kp_geom': kp_geom
            })
    
    distances = sorted(distances, key=lambda x: x['distance'])
    
    logger.info(f"  Gefunden: {len(distances)} Knotenpunkte im {search_radius}m Umkreis")
    
    if len(distances) == 0:
        logger.warning("⚠ KEIN Knotenpunkt in der Nähe gefunden!")
        logger.info("\nMÖGLICHE URSACHEN:")
        logger.info("  1. Alle nahen Knotenpunkte haben KP_Nichtbetrachten=1")
        logger.info("  2. Segment liegt außerhalb der betrachteten Bereiche")
        return
    
    # Analysiere die nächsten Knotenpunkte
    logger.info(f"\nNÄHESTE KNOTENPUNKTE (Top 5):")
    
    for i, kp_info in enumerate(distances[:5], 1):
        kp_idx = kp_info['kp_idx']
        kp_geom = kp_info['kp_geom']
        kp_id = kp_info['kp_id']
        distance = kp_info['distance']
        
        # Hole Buffer
        buffer_geom = kp_buffers.loc[kp_idx, 'buffer_geom']
        
        # Berechne Überlappung
        overlap_ratio = calculate_segment_overlap_with_buffer(segment_geom, buffer_geom)
        overlap_length = overlap_ratio * segment_length
        
        # Prüfe ob konvertiert worden wäre
        would_convert = overlap_ratio >= old_min_overlap
        
        logger.info(f"\n  {i}. Knotenpunkt KP_Nr={kp_id} (idx={kp_idx}):")
        logger.info(f"     Distanz zum Segment: {distance:.2f}m")
        logger.info(f"     Segment im {old_buffer_radius}m-Buffer: {overlap_length:.2f}m ({overlap_ratio*100:.1f}%)")
        logger.info(f"     Erfüllt {old_min_overlap*100}% Kriterium: {'✓ JA' if would_convert else '✗ NEIN'}")
        
        if not would_convert:
            needed_overlap = old_min_overlap * segment_length
            missing = needed_overlap - overlap_length
            logger.info(f"     Benötigt: {needed_overlap:.2f}m ({old_min_overlap*100}%)")
            logger.info(f"     Fehlend: {missing:.2f}m")
    
    # Teste mit neuen Parametern
    logger.info("\n" + "=" * 80)
    logger.info("TEST MIT NEUEN PARAMETERN")
    logger.info("=" * 80)
    
    for new_radius, new_overlap in [(25, 0.4), (30, 0.5), (30, 0.4)]:
        logger.info(f"\nParameter: Radius={new_radius}m, Überlappung={new_overlap*100}%")
        
        # Erstelle neue Buffer
        test_buffers = active_knotenpunkte.copy()
        test_buffers['test_buffer'] = test_buffers.geometry.buffer(new_radius)
        
        # Prüfe die nächsten Knotenpunkte
        converted = False
        for kp_info in distances[:5]:
            kp_idx = kp_info['kp_idx']
            buffer_geom = test_buffers.loc[kp_idx, 'test_buffer']
            
            overlap_ratio = calculate_segment_overlap_with_buffer(segment_geom, buffer_geom)
            
            if overlap_ratio >= new_overlap:
                overlap_length = overlap_ratio * segment_length
                logger.info(f"  ✓ WÜRDE KONVERTIERT bei KP_Nr={kp_info['kp_id']}")
                logger.info(f"    Überlappung: {overlap_length:.2f}m ({overlap_ratio*100:.1f}%)")
                converted = True
                break
        
        if not converted:
            logger.info(f"  ✗ Würde NICHT konvertiert")
    
    # Fazit
    logger.info("\n" + "=" * 80)
    logger.info("ZUSAMMENFASSUNG")
    logger.info("=" * 80)
    
    best_overlap_old = max([
        calculate_segment_overlap_with_buffer(
            segment_geom, 
            kp_buffers.loc[kp_info['kp_idx'], 'buffer_geom']
        ) for kp_info in distances[:3]
    ]) if len(distances) > 0 else 0
    
    logger.info(f"Segment sfid={sfid}:")
    logger.info(f"  - Länge: {segment_length:.2f}m")
    logger.info(f"  - Führungsform: {segment_fuehr}")
    logger.info(f"  - Beste Überlappung (25m-Buffer): {best_overlap_old*100:.1f}%")
    logger.info(f"  - Erforderlich (alte Parameter): {old_min_overlap*100}%")
    
    if best_overlap_old < old_min_overlap:
        logger.info(f"\n⚠ GRUND: Überlappung {best_overlap_old*100:.1f}% < {old_min_overlap*100}% erforderlich")
        logger.info(f"  Fehlend: {(old_min_overlap - best_overlap_old)*100:.1f} Prozentpunkte")


def main():
    """Hauptfunktion"""
    import sys
    
    # Finde base_dir richtig (validation ist auf gleicher Ebene wie output)
    base_dir = os.path.dirname(os.path.dirname(__file__))
    
    # Pfade
    input_file = os.path.join(base_dir, 'output', 'snapping_with_overrides.fgb')
    knotenpunkte_file = os.path.join(base_dir, 'data-raw-tilda', 'knotenpunkte_mit_id_und_bezirken.gpkg')
    
    logger.info(f"Lese Segmente: {input_file}")
    gdf = gpd.read_file(input_file)
    
    logger.info(f"Lese Knotenpunkte: {knotenpunkte_file}\n")
    knotenpunkte_gdf = gpd.read_file(knotenpunkte_file)
    
    # Debug spezifisches Segment
    if len(sys.argv) > 1:
        sfid = int(sys.argv[1])
    else:
        # Finde ein Beispiel-Segment: Schutzstreifen < 50m der nicht konvertiert wurde
        schutz = gdf[gdf['fuehr'] == 'Schutzstreifen'].copy()
        schutz['len'] = schutz.geometry.length
        schutz_short = schutz[schutz['len'] < 50]
        
        if len(schutz_short) > 0:
            sfid = schutz_short.iloc[0]['sfid']
            logger.info(f"Kein sfid angegeben, nutze Beispiel: sfid={sfid}\n")
        else:
            logger.error("Keine Schutzstreifen < 50m gefunden!")
            return
    
    debug_segment(gdf, knotenpunkte_gdf, sfid)


if __name__ == '__main__':
    main()
