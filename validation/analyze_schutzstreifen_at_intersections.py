#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze_schutzstreifen_at_intersections.py
--------------------------------------------------------------------
Analysiert Schutzstreifen im Umkreis von Knotenpunkten zur Validierung
der Konvertierungsparameter.
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


def analyze_schutzstreifen_coverage(
    gdf,
    knotenpunkte_gdf,
    analysis_radius=75.0,
    current_buffer_radius=25.0,
    current_min_overlap_ratio=0.7,
    max_segment_length=50.0
):
    """
    Analysiert Schutzstreifen im Umkreis von Knotenpunkten.
    
    Args:
        gdf: GeoDataFrame mit Radnetz-Segmenten
        knotenpunkte_gdf: GeoDataFrame mit Knotenpunkten
        analysis_radius: Radius für Analyse-Bereich (75m)
        current_buffer_radius: Aktueller Buffer-Radius (25m)
        current_min_overlap_ratio: Aktuelle Mindestüberlappung (0.7)
        max_segment_length: Maximale Segmentlänge (50m)
    """
    logger.info("=" * 80)
    logger.info("ANALYSE: Schutzstreifen an Knotenpunkten")
    logger.info("=" * 80)
    
    # Filtere aktive Knotenpunkte
    active_knotenpunkte = knotenpunkte_gdf[
        knotenpunkte_gdf['KP_Nichtbetrachten'] == 0
    ].copy()
    
    logger.info(f"Aktive Knotenpunkte (KP_Nichtbetrachten=0): {len(active_knotenpunkte)}")
    
    # Filtere nur Schutzstreifen
    schutzstreifen = gdf[gdf['fuehr'] == 'Schutzstreifen'].copy()
    schutzstreifen['segment_length'] = schutzstreifen.geometry.length
    
    logger.info(f"Schutzstreifen total: {len(schutzstreifen)}")
    logger.info(f"Schutzstreifen < {max_segment_length}m: {(schutzstreifen['segment_length'] < max_segment_length).sum()}")
    
    # Statistiken über alle Schutzstreifen
    logger.info("\n" + "-" * 80)
    logger.info("LÄNGEN-STATISTIKEN: Alle Schutzstreifen")
    logger.info("-" * 80)
    logger.info(f"Anzahl: {len(schutzstreifen)}")
    logger.info(f"Median: {schutzstreifen['segment_length'].median():.1f}m")
    logger.info(f"Mittelwert: {schutzstreifen['segment_length'].mean():.1f}m")
    logger.info(f"Minimum: {schutzstreifen['segment_length'].min():.1f}m")
    logger.info(f"Maximum: {schutzstreifen['segment_length'].max():.1f}m")
    logger.info(f"25%-Perzentil: {schutzstreifen['segment_length'].quantile(0.25):.1f}m")
    logger.info(f"75%-Perzentil: {schutzstreifen['segment_length'].quantile(0.75):.1f}m")
    logger.info(f"90%-Perzentil: {schutzstreifen['segment_length'].quantile(0.90):.1f}m")
    
    # Erstelle Analyse-Buffer (75m) um Knotenpunkte
    logger.info(f"\n" + "-" * 80)
    logger.info(f"ANALYSE-BEREICH: {analysis_radius}m um Knotenpunkte")
    logger.info("-" * 80)
    
    analysis_buffers = active_knotenpunkte.copy()
    analysis_buffers['analysis_buffer'] = analysis_buffers.geometry.buffer(analysis_radius)
    
    # Erstelle auch aktuelle Buffer (25m)
    analysis_buffers['current_buffer'] = analysis_buffers.geometry.buffer(current_buffer_radius)
    
    # Spatial Index
    analysis_spatial_idx = analysis_buffers.sindex
    
    # Finde Schutzstreifen im Analyse-Bereich
    results = []
    
    for idx, ss_row in schutzstreifen.iterrows():
        segment_geom = ss_row.geometry
        segment_length = ss_row['segment_length']
        
        # Finde Knotenpunkte im Analyse-Bereich
        possible_kp_idx = list(analysis_spatial_idx.intersection(segment_geom.bounds))
        
        if not possible_kp_idx:
            continue
        
        possible_kp = analysis_buffers.iloc[possible_kp_idx]
        
        for _, kp_row in possible_kp.iterrows():
            analysis_buffer_geom = kp_row['analysis_buffer']
            current_buffer_geom = kp_row['current_buffer']
            
            # Prüfe ob Segment im Analyse-Bereich liegt
            if not segment_geom.intersects(analysis_buffer_geom):
                continue
            
            # Berechne Überlappungen
            intersection_analysis = segment_geom.intersection(analysis_buffer_geom)
            intersection_current = segment_geom.intersection(current_buffer_geom)
            
            # Berechne Längen
            if intersection_analysis.is_empty:
                overlap_length_analysis = 0.0
            elif intersection_analysis.geom_type == 'LineString':
                overlap_length_analysis = intersection_analysis.length
            elif intersection_analysis.geom_type == 'MultiLineString':
                overlap_length_analysis = sum(line.length for line in intersection_analysis.geoms)
            else:
                overlap_length_analysis = 0.0
            
            if intersection_current.is_empty:
                overlap_length_current = 0.0
            elif intersection_current.geom_type == 'LineString':
                overlap_length_current = intersection_current.length
            elif intersection_current.geom_type == 'MultiLineString':
                overlap_length_current = sum(line.length for line in intersection_current.geoms)
            else:
                overlap_length_current = 0.0
            
            # Berechne Ratios
            overlap_ratio_analysis = overlap_length_analysis / segment_length if segment_length > 0 else 0
            overlap_ratio_current = overlap_length_current / segment_length if segment_length > 0 else 0
            
            # Prüfe ob aktuell konvertiert würde
            would_convert = (
                segment_length < max_segment_length and
                overlap_ratio_current >= current_min_overlap_ratio
            )
            
            # Prüfe ob Segment im Analyse-Bereich ist und < 50m
            is_candidate = segment_length < max_segment_length
            
            results.append({
                'segment_idx': idx,
                'segment_length': segment_length,
                'overlap_length_75m': overlap_length_analysis,
                'overlap_ratio_75m': overlap_ratio_analysis,
                'overlap_length_25m': overlap_length_current,
                'overlap_ratio_25m': overlap_ratio_current,
                'would_convert_current': would_convert,
                'is_candidate': is_candidate
            })
    
    # Erstelle DataFrame
    results_df = pd.DataFrame(results)
    
    if len(results_df) == 0:
        logger.warning("Keine Schutzstreifen im Analyse-Bereich gefunden!")
        return
    
    # Entferne Duplikate (ein Segment kann mehrere Knotenpunkte haben)
    results_df = results_df.drop_duplicates(subset=['segment_idx'])
    
    logger.info(f"Schutzstreifen im {analysis_radius}m-Bereich: {len(results_df)}")
    logger.info(f"Davon < {max_segment_length}m (Kandidaten): {results_df['is_candidate'].sum()}")
    
    # Analysiere Kandidaten
    candidates = results_df[results_df['is_candidate']]
    
    logger.info("\n" + "-" * 80)
    logger.info(f"LÄNGEN-STATISTIKEN: Schutzstreifen-Kandidaten (< {max_segment_length}m) im {analysis_radius}m-Bereich")
    logger.info("-" * 80)
    logger.info(f"Anzahl: {len(candidates)}")
    logger.info(f"Median: {candidates['segment_length'].median():.1f}m")
    logger.info(f"Mittelwert: {candidates['segment_length'].mean():.1f}m")
    logger.info(f"Minimum: {candidates['segment_length'].min():.1f}m")
    logger.info(f"Maximum: {candidates['segment_length'].max():.1f}m")
    logger.info(f"25%-Perzentil: {candidates['segment_length'].quantile(0.25):.1f}m")
    logger.info(f"75%-Perzentil: {candidates['segment_length'].quantile(0.75):.1f}m")
    logger.info(f"90%-Perzentil: {candidates['segment_length'].quantile(0.90):.1f}m")
    
    # Längen-Verteilung in Bins
    logger.info("\nVerteilung der Längen (Kandidaten):")
    bins = [0, 10, 20, 30, 40, 50]
    hist, _ = np.histogram(candidates['segment_length'], bins=bins)
    for i in range(len(bins) - 1):
        logger.info(f"  {bins[i]}-{bins[i+1]}m: {hist[i]} ({hist[i]/len(candidates)*100:.1f}%)")
    
    # Analysiere aktuelle Parameter
    logger.info("\n" + "-" * 80)
    logger.info(f"AKTUELLE PARAMETER: {current_buffer_radius}m Radius, {current_min_overlap_ratio*100:.0f}% Überlappung")
    logger.info("-" * 80)
    
    converted = candidates[candidates['would_convert_current']]
    not_converted = candidates[~candidates['would_convert_current']]
    
    logger.info(f"Würden konvertiert: {len(converted)} ({len(converted)/len(candidates)*100:.1f}%)")
    logger.info(f"Würden NICHT konvertiert: {len(not_converted)} ({len(not_converted)/len(candidates)*100:.1f}%)")
    
    if len(not_converted) > 0:
        logger.info(f"\nNicht konvertierte - Überlappung mit 25m-Buffer:")
        logger.info(f"  Median: {not_converted['overlap_ratio_25m'].median()*100:.1f}%")
        logger.info(f"  Mittelwert: {not_converted['overlap_ratio_25m'].mean()*100:.1f}%")
        logger.info(f"  Minimum: {not_converted['overlap_ratio_25m'].min()*100:.1f}%")
        logger.info(f"  Maximum: {not_converted['overlap_ratio_25m'].max()*100:.1f}%")
    
    # Analysiere verschiedene Überlappungs-Ratios
    logger.info("\n" + "-" * 80)
    logger.info("OPTIMIERUNGSANALYSE: Verschiedene Parameter-Kombinationen")
    logger.info("-" * 80)
    
    for test_radius in [25, 30, 35, 40]:
        for test_overlap in [0.5, 0.6, 0.7]:
            # Berechne für jeden Radius die Überlappung neu
            test_buffers = active_knotenpunkte.copy()
            test_buffers['test_buffer'] = test_buffers.geometry.buffer(test_radius)
            test_spatial_idx = test_buffers.sindex
            
            converted_count = 0
            
            for _, candidate_row in candidates.iterrows():
                segment_idx = candidate_row['segment_idx']
                segment_geom = schutzstreifen.loc[segment_idx, 'geometry']
                segment_length = candidate_row['segment_length']
                
                # Finde Knotenpunkte
                possible_kp_idx = list(test_spatial_idx.intersection(segment_geom.bounds))
                if not possible_kp_idx:
                    continue
                
                possible_kp = test_buffers.iloc[possible_kp_idx]
                
                for _, kp_row in possible_kp.iterrows():
                    buffer_geom = kp_row['test_buffer']
                    
                    intersection = segment_geom.intersection(buffer_geom)
                    
                    if intersection.is_empty:
                        overlap_length = 0.0
                    elif intersection.geom_type == 'LineString':
                        overlap_length = intersection.length
                    elif intersection.geom_type == 'MultiLineString':
                        overlap_length = sum(line.length for line in intersection.geoms)
                    else:
                        overlap_length = 0.0
                    
                    overlap_ratio = overlap_length / segment_length if segment_length > 0 else 0
                    
                    if overlap_ratio >= test_overlap:
                        converted_count += 1
                        break  # Ein Segment nur einmal zählen
            
            coverage = converted_count / len(candidates) * 100 if len(candidates) > 0 else 0
            logger.info(
                f"  Radius {test_radius}m + {test_overlap*100:.0f}% Überlappung: "
                f"{converted_count}/{len(candidates)} = {coverage:.1f}% Abdeckung"
            )
    
    # Empfehlungen
    logger.info("\n" + "=" * 80)
    logger.info("EMPFEHLUNGEN")
    logger.info("=" * 80)
    
    # Berechne optimale Parameter
    # Für 95% Abdeckung
    target_coverage = 0.95
    
    logger.info(f"\nZiel: Mindestens {target_coverage*100:.0f}% der Schutzstreifen-Kandidaten erfassen\n")
    
    best_params = []
    
    for test_radius in range(25, 51, 5):
        for test_overlap in [0.4, 0.5, 0.6, 0.7]:
            test_buffers = active_knotenpunkte.copy()
            test_buffers['test_buffer'] = test_buffers.geometry.buffer(test_radius)
            test_spatial_idx = test_buffers.sindex
            
            converted_count = 0
            
            for _, candidate_row in candidates.iterrows():
                segment_idx = candidate_row['segment_idx']
                segment_geom = schutzstreifen.loc[segment_idx, 'geometry']
                segment_length = candidate_row['segment_length']
                
                possible_kp_idx = list(test_spatial_idx.intersection(segment_geom.bounds))
                if not possible_kp_idx:
                    continue
                
                possible_kp = test_buffers.iloc[possible_kp_idx]
                
                for _, kp_row in possible_kp.iterrows():
                    buffer_geom = kp_row['test_buffer']
                    intersection = segment_geom.intersection(buffer_geom)
                    
                    if intersection.is_empty:
                        overlap_length = 0.0
                    elif intersection.geom_type == 'LineString':
                        overlap_length = intersection.length
                    elif intersection.geom_type == 'MultiLineString':
                        overlap_length = sum(line.length for line in intersection.geoms)
                    else:
                        overlap_length = 0.0
                    
                    overlap_ratio = overlap_length / segment_length if segment_length > 0 else 0
                    
                    if overlap_ratio >= test_overlap:
                        converted_count += 1
                        break
            
            coverage = converted_count / len(candidates) if len(candidates) > 0 else 0
            
            if coverage >= target_coverage:
                best_params.append({
                    'radius': test_radius,
                    'overlap': test_overlap,
                    'coverage': coverage,
                    'converted': converted_count
                })
    
    if best_params:
        # Sortiere nach kleinstem Radius, dann höchster Überlappung
        best_params.sort(key=lambda x: (x['radius'], -x['overlap']))
        
        logger.info(f"Parameter-Kombinationen mit ≥{target_coverage*100:.0f}% Abdeckung:")
        for i, params in enumerate(best_params[:5], 1):
            logger.info(
                f"  {i}. Radius: {params['radius']}m, Überlappung: {params['overlap']*100:.0f}% "
                f"→ {params['converted']}/{len(candidates)} = {params['coverage']*100:.1f}%"
            )
        
        recommended = best_params[0]
        logger.info(f"\n✓ EMPFEHLUNG (kleinster Radius):")
        logger.info(f"  - buffer_radius = {recommended['radius']}")
        logger.info(f"  - min_overlap_ratio = {recommended['overlap']}")
        logger.info(f"  - Abdeckung: {recommended['coverage']*100:.1f}%")
    else:
        logger.warning(f"Keine Parameter-Kombination erreicht {target_coverage*100:.0f}% Abdeckung!")
        logger.info("Erwäge größeren Radius (>50m) oder niedrigere Überlappung (<0.4)")


def main():
    """Hauptfunktion"""
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    
    # Pfade - nutze die vorhandenen regionalen Dateien
    input_file = os.path.join(base_dir, 'output', 'snapping_with_overrides.fgb')
    knotenpunkte_file = os.path.join(base_dir, 'data-raw-tilda', 'knotenpunkte_mit_id_und_bezirken.gpkg')
    
    logger.info(f"Lese Segmente: {input_file}")
    gdf = gpd.read_file(input_file)
    
    logger.info(f"Lese Knotenpunkte: {knotenpunkte_file}")
    knotenpunkte_gdf = gpd.read_file(knotenpunkte_file)
    
    # Analyse
    analyze_schutzstreifen_coverage(
        gdf=gdf,
        knotenpunkte_gdf=knotenpunkte_gdf
    )


if __name__ == '__main__':
    main()
