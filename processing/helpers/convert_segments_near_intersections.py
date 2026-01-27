#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
convert_segments_near_intersections.py
--------------------------------------------------------------------
Konvertierung von kurzen Segmenten an Knotenpunkten zu Kreuzungswegen.

Diese Funktion konvertiert bestimmte Führungsformen an Knotenpunkten zu "Kreuzungsweg":
- Alle Radfahrstreifen-Typen
- Bussonderfahrstreifen  
- Schutzstreifen
- Gemeinsamer Geh- und Radweg mit Z240
- Radweg

Bedingungen für Konvertierung:
1. Knotenpunkt hat KP_Nichtbetrachten = 0 (wird betrachtet)
2. Segment liegt mindestens 60% innerhalb vom Radius um Knotenpunkt
3. Segment ist kürzer als 50m
4. Segment hat eine der relevanten Führungsformen

"""

import sys
import os
import logging
import geopandas as gpd
import pandas as pd
from shapely.geometry import Point, LineString
from .progressbar import print_progressbar

logger = logging.getLogger(__name__)


# ============================================================================
# KONFIGURATION
# ============================================================================

# Führungsformen die zu Kreuzungsweg konvertiert werden sollen
CONVERTIBLE_FUEHRUNGSFORMEN = [
    "Radfahrstreifen",
    "Radfahrstreifen (OSM:Kurzer Schutzstreifen)",
    "Geschützter Radfahrstreifen", 
    "Radfahrstreifen mit Linienverkehr frei (Z237 mit Z1026-32)",
    "Bussonderfahrstreifen mit Radverkehr frei (Z245 mit Z1022‐10)",
    "Schutzstreifen",
    "Gemeinsamer Geh- und Radweg mit Z240",
    "Radweg"
]

# Radius um Knotenpunkte in Metern
DEFAULT_BUFFER_RADIUS = 25.0

# Mindestanteil des Segments der im Buffer liegen muss (0.0 - 1.0)
DEFAULT_MIN_OVERLAP_RATIO = 0.6  # 60%

# Maximale Segmentlänge für Konvertierung in Metern
DEFAULT_MAX_SEGMENT_LENGTH = 50.0

# Label für konvertierte Segmente
DEFAULT_OUTPUT_LABEL = "Kreuzungsweg (Konvertiert)"

# ============================================================================


def calculate_segment_overlap_with_buffer(segment_geometry, buffer_geometry):
    """
    Berechnet den Anteil eines Segments, der innerhalb eines Puffers liegt.
    
    Args:
        segment_geometry: LineString Geometrie des Segments
        buffer_geometry: Polygon Geometrie des Puffers
        
    Returns:
        float: Anteil des Segments im Puffer (0.0 bis 1.0)
    """
    if segment_geometry.length == 0:
        return 0.0
    
    # Berechne Überschneidung
    intersection = segment_geometry.intersection(buffer_geometry)
    
    # Überschneidungslänge berechnen
    if intersection.is_empty:
        return 0.0
    elif intersection.geom_type == 'LineString':
        overlap_length = intersection.length
    elif intersection.geom_type == 'MultiLineString':
        overlap_length = sum(line.length for line in intersection.geoms)
    else:
        # Punkt oder andere Geometrie
        return 0.0
    
    return overlap_length / segment_geometry.length


def append_conversion_comment(gdf, idx, old_fuehr, new_fuehr):
    """
    Fügt einen Kommentar hinzu, der die Führungsform-Konvertierung dokumentiert.
    
    Args:
        gdf: GeoDataFrame mit Segmenten
        idx: Index des Segments
        old_fuehr: Alte Führungsform
        new_fuehr: Neue Führungsform
    """
    if 'Kommentar' not in gdf.columns:
        # Wenn Kommentar-Spalte nicht existiert, erstelle sie
        gdf['Kommentar'] = None
    
    current_comment = gdf.loc[idx, 'Kommentar']
    conversion_note = f"Führungsform geändert: '{old_fuehr}' → '{new_fuehr}'"
    
    if pd.isna(current_comment) or current_comment is None or str(current_comment).strip() == '':
        # Kein vorheriger Kommentar
        gdf.loc[idx, 'Kommentar'] = conversion_note
    else:
        # Füge zum existierenden Kommentar hinzu
        gdf.loc[idx, 'Kommentar'] = str(current_comment) + "; " + conversion_note


def convert_segments_near_intersections(
    gdf,
    knotenpunkte_gdf,
    buffer_radius=DEFAULT_BUFFER_RADIUS,
    min_overlap_ratio=DEFAULT_MIN_OVERLAP_RATIO,
    max_segment_length=DEFAULT_MAX_SEGMENT_LENGTH,
    output_label=DEFAULT_OUTPUT_LABEL
):
    """
    Konvertiert kurze Segmente an Knotenpunkten zu Kreuzungswegen.
    
    Erstellt automatisch die Datei output/knotenpunkte/betrachtete_knotenpunkt_radius_<radius>m.fgb
    mit den Radius-Flächen, falls sie noch nicht existiert.
    
    Args:
        gdf: GeoDataFrame mit Radnetz-Segmenten (muss 'fuehr' Spalte haben)
        knotenpunkte_gdf: GeoDataFrame mit Knotenpunkten (muss 'KP_Nichtbetrachten' haben)
        buffer_radius: Radius um Knotenpunkte in Metern (Standard: DEFAULT_BUFFER_RADIUS)
        min_overlap_ratio: Mindestanteil des Segments im Buffer (Standard: 0.6 = 60%)
        max_segment_length: Maximale Segmentlänge für Konvertierung in Metern (Standard: 50m)
        output_label: Label für konvertierte Segmente
        
    Returns:
        GeoDataFrame: Kopie von gdf mit konvertierten Führungsformen
    """
    logger.info("=" * 80)
    logger.info("Konvertiere Segmente an Knotenpunkten zu Kreuzungswegen")
    logger.info("=" * 80)
    
    # Validierung
    if 'fuehr' not in gdf.columns:
        raise ValueError("GeoDataFrame muss 'fuehr' Spalte enthalten")
    if 'KP_Nichtbetrachten' not in knotenpunkte_gdf.columns:
        raise ValueError("Knotenpunkte GeoDataFrame muss 'KP_Nichtbetrachten' Spalte enthalten")
    
    # Kopie erstellen
    result_gdf = gdf.copy()
    
    # Filtere Knotenpunkte: nur die mit KP_Nichtbetrachten = 0
    active_knotenpunkte = knotenpunkte_gdf[
        knotenpunkte_gdf['KP_Nichtbetrachten'] == 0
    ].copy()
    
    logger.info(f"Knotenpunkte total: {len(knotenpunkte_gdf)}")
    logger.info(f"Knotenpunkte zu betrachten (KP_Nichtbetrachten=0): {len(active_knotenpunkte)}")
    logger.info(f"Buffer-Radius: {buffer_radius}m")
    logger.info(f"Minimale Überlappung: {min_overlap_ratio * 100}%")
    logger.info(f"Maximale Segmentlänge: {max_segment_length}m")
    
    # WICHTIG: Löse MultiLineStrings ZUERST auf, bevor Längenfilter angewendet wird
    # Grund: Ein 100m MultiLineString kann einen 4m Teil haben, der konvertiert werden sollte!
    logger.info(f"\nLöse MultiLineStrings in einzelne Teile auf (VOR Längenfilter)...")
    
    # Filtere nur nach Führungsform, nicht nach Länge
    fuehr_mask = result_gdf['fuehr'].isin(CONVERTIBLE_FUEHRUNGSFORMEN)
    fuehr_candidates = result_gdf[fuehr_mask].copy()
    logger.info(f"Segmente mit konvertierbaren Führungsformen: {len(fuehr_candidates)}")
    
    multiline_count = (fuehr_candidates.geometry.geom_type == 'MultiLineString').sum()
    logger.info(f"  Davon MultiLineStrings: {multiline_count}")
    
    # Sammle neue Zeilen für aufgelöste MultiLineStrings
    rows_to_remove = []
    rows_to_add = []
    
    for idx, row in fuehr_candidates.iterrows():
        if row.geometry.geom_type == 'MultiLineString':
            # Löse MultiLineString in einzelne LineStrings auf
            for part_idx, line_geom in enumerate(row.geometry.geoms):
                # Kopiere alle Attribute und ersetze nur die Geometrie
                new_row = row.copy()
                new_row.geometry = line_geom
                
                # Füge Info hinzu, dass dies ein aufgelöster Teil ist
                if 'Kommentar' not in new_row or pd.isna(new_row['Kommentar']) or str(new_row['Kommentar']).strip() == '':
                    new_row['Kommentar'] = f'MultiLineString aufgelöst (Teil {part_idx + 1}/{len(row.geometry.geoms)})'
                else:
                    new_row['Kommentar'] = str(new_row['Kommentar']) + f'; MultiLineString aufgelöst (Teil {part_idx + 1}/{len(row.geometry.geoms)})'
                
                rows_to_add.append((idx, new_row))
            
            rows_to_remove.append(idx)
    
    # Entferne Original-MultiLineStrings aus result_gdf
    if len(rows_to_remove) > 0:
        result_gdf = result_gdf.drop(index=rows_to_remove)
    
    # Füge aufgelöste Teile zu result_gdf hinzu
    if len(rows_to_add) > 0:
        # Erstelle neue GeoDataFrame aus aufgelösten Teilen
        new_rows_gdf = gpd.GeoDataFrame(
            [row for _, row in rows_to_add],
            crs=result_gdf.crs
        )
        # WICHTIG: Reset index für neue Zeilen, um Duplikate zu vermeiden
        new_rows_gdf = new_rows_gdf.reset_index(drop=True)
        result_gdf = pd.concat([result_gdf, new_rows_gdf], ignore_index=True)
        
        logger.info(f"  {len(rows_to_remove)} MultiLineStrings in {len(rows_to_add)} Teile aufgelöst")
    
    # JETZT erst Längenfilter anwenden auf alle Segmente (inkl. aufgelöste Teile)
    result_gdf['segment_length'] = result_gdf.geometry.length
    
    candidate_mask = (
        result_gdf['fuehr'].isin(CONVERTIBLE_FUEHRUNGSFORMEN) &
        (result_gdf['segment_length'] < max_segment_length)
    )
    
    candidates = result_gdf[candidate_mask].copy()
    logger.info(f"\nKandidaten nach Führungsform + Längenfilter < {max_segment_length}m: {len(candidates)}")
    
    if len(candidates) == 0:
        logger.info("Keine Kandidaten gefunden - keine Konvertierung notwendig")
        return result_gdf
    
    # Statistik pro Führungsform
    logger.info("\nKandidaten nach Führungsform:")
    for fuehr in CONVERTIBLE_FUEHRUNGSFORMEN:
        count = (candidates['fuehr'] == fuehr).sum()
        if count > 0:
            logger.info(f"  - {fuehr}: {count}")
    
    # Erstelle Puffer um Knotenpunkte
    logger.info(f"\nErstelle {buffer_radius}m Puffer um {len(active_knotenpunkte)} Knotenpunkte...")
    kp_buffers = active_knotenpunkte.copy()
    kp_buffers['buffer_geom'] = kp_buffers.geometry.buffer(buffer_radius)
    kp_buffers['kp_point'] = kp_buffers.geometry  # Behalte Original-Punkt für Distanzsuche
    
    # Spatial Index für effiziente Suche - Index auf Punkt-Geometrien für Distanzsuche
    kp_spatial_idx = kp_buffers.sindex
    
    # Speichere Radius-Flächen für Visualisierung (optional)
    # Die buffer_geom wird später gespeichert falls save_radius_file gesetzt ist
    
    # Zähler für Konvertierungen
    conversion_count = 0
    
    logger.info(f"\nPrüfe {len(candidates)} Kandidaten...")
    
    # Iteriere über Kandidaten
    for idx, row in candidates.iterrows():
        segment_geom = row.geometry
        segment_length = row['segment_length']
        
        # Finde potentielle Knotenpunkte in der Nähe (mit Spatial Index)
        # Nutze nearest() mit Distanz-Limit, um alle KPs im Radius zu finden
        # Dies findet sowohl Intersection als auch Contains-Fälle
        possible_matches_idx = list(kp_spatial_idx.query(segment_geom, predicate='dwithin', distance=buffer_radius))
        
        if not possible_matches_idx:
            continue
        
        possible_kp = kp_buffers.iloc[possible_matches_idx]
        
        # Prüfe Überlappung mit jedem Knotenpunkt-Buffer
        for _, kp_row in possible_kp.iterrows():
            buffer_geom = kp_row['buffer_geom']
            
            # Berechne Überlappungs-Anteil
            overlap_ratio = calculate_segment_overlap_with_buffer(segment_geom, buffer_geom)
            
            # Konvertiere wenn >= Mindestüberlappung im Buffer
            if overlap_ratio >= min_overlap_ratio:
                old_fuehr = result_gdf.loc[idx, 'fuehr']
                result_gdf.loc[idx, 'fuehr'] = output_label
                
                # Füge Kommentar zur Konvertierung hinzu
                append_conversion_comment(result_gdf, idx, old_fuehr, output_label)
                
                conversion_count += 1
                
                logger.debug(
                    f"Konvertiert: {old_fuehr} -> {output_label} "
                    f"(Länge: {segment_length:.1f}m, Überlappung: {overlap_ratio*100:.1f}%)"
                )
                
                # Ein Segment kann nur einmal konvertiert werden
                break
        
        # Progress-Anzeige
        if (idx + 1) % 100 == 0:
            print_progressbar(idx + 1, len(candidates), prefix='Fortschritt:', length=50)
    
    # Final Progress
    print_progressbar(len(candidates), len(candidates), prefix='Fortschritt:', length=50)
    
    # Aufräumen
    result_gdf.drop(columns=['segment_length'], inplace=True)
    
    # Speichere Radius-Flächen automatisch, falls Datei noch nicht existiert
    radius_filename = f"betrachtete_knotenpunkt_radius_{int(buffer_radius)}m.fgb"
    radius_output_path = os.path.join("output", "knotenpunkte", radius_filename)
    
    if not os.path.exists(radius_output_path):
        logger.info(f"\nErstelle Radius-Flächen-Datei: {radius_output_path}")
        radius_gdf = kp_buffers.copy()
        # Setze buffer_geom als Geometrie für Export
        radius_gdf = radius_gdf.set_geometry('buffer_geom')
        radius_gdf = radius_gdf.drop(columns=['geometry', 'kp_point'])
        
        # Stelle sicher, dass Verzeichnis existiert
        os.makedirs(os.path.dirname(radius_output_path), exist_ok=True)
        
        # Speichere als FlatGeobuf
        radius_gdf.to_file(radius_output_path, driver='FlatGeobuf')
        logger.info(f"✓ {len(radius_gdf)} Radius-Flächen gespeichert")
    else:
        logger.info(f"\n✓ Radius-Flächen-Datei existiert bereits: {radius_output_path}")
    
    # Zusammenfassung
    logger.info("\n" + "=" * 80)
    logger.info("ZUSAMMENFASSUNG: Konvertierung an Knotenpunkten")
    logger.info("=" * 80)
    logger.info(f"Kandidaten geprüft: {len(candidates)}")
    logger.info(f"Segmente konvertiert: {conversion_count}")
    logger.info(f"Konvertierungsrate: {conversion_count / len(candidates) * 100:.1f}%")
    
    if conversion_count > 0:
        logger.info(f"\n✓ {conversion_count} Segmente wurden zu '{output_label}' konvertiert")
    else:
        logger.info("\nℹ Keine Segmente erfüllten alle Konvertierungsbedingungen")
    
    return result_gdf


def main():
    """Standalone Ausführung für Tests"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Pfade
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    input_file = os.path.join(base_dir, 'output', 'snapping_network_enriched.fgb')
    knotenpunkte_file = os.path.join(base_dir, 'data-raw-tilda', 'knotenpunkte_mit_id_und_bezirken.gpkg')
    output_file = os.path.join(base_dir, 'output', 'snapping_converted_at_intersections.fgb')
    
    logger.info(f"Lese Segmente von: {input_file}")
    gdf = gpd.read_file(input_file)
    
    logger.info(f"Lese Knotenpunkte von: {knotenpunkte_file}")
    knotenpunkte_gdf = gpd.read_file(knotenpunkte_file)
    
    # Konvertierung
    result_gdf = convert_segments_near_intersections(
        gdf=gdf,
        knotenpunkte_gdf=knotenpunkte_gdf
    )
    
    # Speichern
    logger.info(f"\nSpeichere Ergebnis nach: {output_file}")
    result_gdf.to_file(output_file, driver='FlatGeobuf')
    logger.info("✓ Fertig!")


if __name__ == '__main__':
    main()
