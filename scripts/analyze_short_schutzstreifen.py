#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze_short_schutzstreifen.py
--------------------------------------------------------------------
Analysiert kurze Schutzstreifen (< 50m) aus dem berlin_snapping_network_enriched.fgb und
identifiziert angrenzende Führungsformen.

INPUT:
- output/berlin_snapping_network_enriched.fgb

OUTPUT:
- output/analysis/short_schutzstreifen_segments.fgb (Geometrien der kurzen Segmente)
- output/analysis/schutzstreifen_analysis.csv (Detailanalyse)
- output/analysis/transitions_summary.csv (Häufigkeitsanalyse der Übergänge)
- output/analysis/schutzstreifen_an_radfahrstreifen.csv (Kurze Schutzstreifen die an Radfahrstreifen angrenzen)
"""

import sys
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point, LineString, MultiLineString
from shapely.ops import linemerge
import logging
from collections import defaultdict, Counter
from pathlib import Path

# Import der Progressbar aus helpers
sys.path.append(str(Path(__file__).parent.parent / 'processing'))
from helpers.progressbar import print_progressbar

# Logging konfigurieren
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def setup_output_directory():
    """Erstelle Output-Verzeichnis falls es nicht existiert."""
    output_dir = Path("output/analysis")
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir

def load_snapping_network(file_path):
    """Lade berlin snapping network enriched Daten."""
    logger.info(f"Lade Daten aus {file_path}")
    try:
        gdf = gpd.read_file(file_path)
        logger.info(f"Daten geladen: {len(gdf)} Features")
        logger.info(f"Verfügbare Spalten: {list(gdf.columns)}")
        return gdf
    except Exception as e:
        logger.error(f"Fehler beim Laden der Daten: {e}")
        sys.exit(1)

def filter_schutzstreifen(gdf):
    """Filtere alle Schutzstreifen aus den Daten."""
    schutzstreifen = gdf[gdf['fuehr'] == 'Schutzstreifen'].copy()
    logger.info(f"Gefundene Schutzstreifen: {len(schutzstreifen)}")
    return schutzstreifen

def get_endpoints(geometry):
    """Extrahiere Start- und Endpunkte einer Geometrie."""
    if isinstance(geometry, MultiLineString):
        # Bei MultiLineString nehme ersten und letzten Punkt der ersten/letzten Linie
        coords = []
        for geom in geometry.geoms:
            coords.extend(list(geom.coords))
    else:
        coords = list(geometry.coords)
    
    if len(coords) < 2:
        return None, None
    
    return Point(coords[0]), Point(coords[-1])

def find_connected_schutzstreifen(schutzstreifen_gdf, tolerance=0.1):
    """Finde zusammenhängende Schutzstreifen-Segmente mit optimiertem räumlichem Index."""
    logger.info("Suche zusammenhängende Schutzstreifen-Segmente...")
    
    # Erstelle Index für Endpunkte
    endpoints = {}
    for idx, row in schutzstreifen_gdf.iterrows():
        start, end = get_endpoints(row.geometry)
        if start and end:
            endpoints[idx] = {'start': start, 'end': end, 'geometry': row.geometry}
    
    # Optimierte Verbindungssuche
    connections = defaultdict(set)
    indices = list(endpoints.keys())
    
    logger.info(f"Verarbeite {len(indices)} Schutzstreifen...")
    
    for i, idx1 in enumerate(indices):
        if i % 100 == 0:  # Progress logging
            logger.info(f"Fortschritt: {i}/{len(indices)}")
            
        data1 = endpoints[idx1]
        
        # Erstelle Suchpuffer um Endpunkte
        search_buffer_start = data1['start'].buffer(tolerance * 2)
        search_buffer_end = data1['end'].buffer(tolerance * 2)
        
        for j, idx2 in enumerate(indices[i+1:], i+1):
            data2 = endpoints[idx2]
            
            # Erste räumliche Filterung
            if not (search_buffer_start.intersects(data2['start']) or 
                   search_buffer_start.intersects(data2['end']) or
                   search_buffer_end.intersects(data2['start']) or
                   search_buffer_end.intersects(data2['end'])):
                continue
            
            # Prüfe exakte Distanzen
            distances = [
                data1['start'].distance(data2['start']),
                data1['start'].distance(data2['end']),
                data1['end'].distance(data2['start']),
                data1['end'].distance(data2['end'])
            ]
            
            if min(distances) <= tolerance:
                connections[idx1].add(idx2)
                connections[idx2].add(idx1)
    
    # Erstelle zusammenhängende Komponenten (Segmente)
    visited = set()
    segments = []
    
    for start_idx in endpoints.keys():
        if start_idx in visited:
            continue
            
        # DFS für zusammenhängende Komponente
        component = []
        stack = [start_idx]
        
        while stack:
            current = stack.pop()
            if current in visited:
                continue
                
            visited.add(current)
            component.append(current)
            
            # Füge alle verbundenen Knoten hinzu
            for neighbor in connections[current]:
                if neighbor not in visited:
                    stack.append(neighbor)
        
        segments.append(component)
    
    logger.info(f"Gefundene Segmente: {len(segments)}")
    return segments

def calculate_segment_length(segment_indices, schutzstreifen_gdf):
    """Berechne Gesamtlänge eines Segments."""
    total_length = 0
    geometries = []
    
    for idx in segment_indices:
        geom = schutzstreifen_gdf.loc[idx, 'geometry']
        geometries.append(geom)
        total_length += geom.length
    
    return total_length, geometries

def merge_segment_geometries(geometries):
    """Versuche Geometrien zu einem zusammenhängenden Segment zu verbinden."""
    try:
        # Normalisiere alle Geometrien zu LineStrings
        lines = []
        for geom in geometries:
            if isinstance(geom, MultiLineString):
                # MultiLineString zu einzelnen LineStrings aufbrechen
                for line in geom.geoms:
                    lines.append(line)
            elif isinstance(geom, LineString):
                lines.append(geom)
            else:
                continue  # Andere Geometrietypen überspringen
        
        if len(lines) == 0:
            return None
        elif len(lines) == 1:
            return lines[0]
        else:
            # Versuche LineString-Merger
            merged = linemerge(lines)
            return merged
    except Exception as e:
        logger.warning(f"Fehler beim Merger von Geometrien: {e}")
        # Fallback: MultiLineString aus allen verfügbaren LineStrings
        lines = []
        for geom in geometries:
            if isinstance(geom, MultiLineString):
                lines.extend(list(geom.geoms))
            elif isinstance(geom, LineString):
                lines.append(geom)
        
        if lines:
            return MultiLineString(lines)
        else:
            return None

def find_adjacent_ways(segment_geometry, all_ways_gdf, tolerance=0.1):
    """Finde alle angrenzenden Wege zu einem Segment mit räumlichem Index."""
    adjacent_ways = []
    
    # Extrahiere Endpunkte des Segments
    start_point, end_point = get_endpoints(segment_geometry)
    
    if not start_point or not end_point:
        return adjacent_ways
    
    # Erstelle Puffer um Endpunkte für räumliche Suche
    search_buffer_start = start_point.buffer(tolerance * 2)
    search_buffer_end = end_point.buffer(tolerance * 2)
    
    # Verwende räumlichen Index für erste Filterung
    possible_matches_start = all_ways_gdf[all_ways_gdf.geometry.intersects(search_buffer_start)]
    possible_matches_end = all_ways_gdf[all_ways_gdf.geometry.intersects(search_buffer_end)]
    
    # Kombiniere beide Mengen
    possible_matches = pd.concat([possible_matches_start, possible_matches_end]).drop_duplicates()
    
    # Suche nach angrenzenden Wegen in der gefilterten Menge
    for idx, way in possible_matches.iterrows():
        if way['fuehr'] == 'Schutzstreifen':
            continue  # Skip andere Schutzstreifen
            
        way_start, way_end = get_endpoints(way.geometry)
        if not way_start or not way_end:
            continue
        
        # Prüfe Verbindung zu Segment-Endpunkten
        distances = [
            start_point.distance(way_start),
            start_point.distance(way_end),
            end_point.distance(way_start),
            end_point.distance(way_end)
        ]
        min_distance = min(distances)
        
        if min_distance <= tolerance:
            adjacent_ways.append({
                'way_id': way.get('sfid', idx),
                'fuehr': way['fuehr'],
                'element_nr': way.get('element_nr', 'unknown'),
                'distance': min_distance
            })
    
    return adjacent_ways

def analyze_segments(segments, schutzstreifen_gdf, all_ways_gdf):
    """Analysiere alle Segmente und erstelle Ergebnisse."""
    logger.info("Analysiere Segmente...")
    
    results = []
    short_segments_geometries = []
    total_segments = len(segments)
    
    for i, segment_indices in enumerate(segments):
        # Progressbar anzeigen
        print_progressbar(i + 1, total_segments, "Analysiere Segmente: ")
        
        segment_id = f"segment_{i:03d}"
        
        # Berechne Länge
        total_length, geometries = calculate_segment_length(segment_indices, schutzstreifen_gdf)
        
        # Erstelle merged Geometrie
        merged_geometry = merge_segment_geometries(geometries)
        
        # Prüfe ob Segment kurz ist (< 50m)
        is_short = total_length < 50.0
        
        if is_short:
            short_segments_geometries.append({
                'segment_id': segment_id,
                'geometry': merged_geometry,
                'length_m': total_length,
                'way_count': len(segment_indices)
            })
        
        # Finde angrenzende Wege
        adjacent_ways = find_adjacent_ways(merged_geometry, all_ways_gdf)
        
        # Erstelle Übergangsbeschreibung
        adjacent_fuehr = [way['fuehr'] for way in adjacent_ways]
        transition_description = " ↔ ".join(sorted(set(adjacent_fuehr))) if adjacent_fuehr else "keine angrenzenden Wege"
        
        # Sammle OSM/TILDA IDs der Segment-Wege
        segment_tilda_ids = []
        for idx in segment_indices:
            tilda_id = schutzstreifen_gdf.loc[idx].get('tilda_id')
            element_nr = schutzstreifen_gdf.loc[idx].get('element_nr')
            if tilda_id:
                segment_tilda_ids.append(str(tilda_id))
            elif element_nr:
                segment_tilda_ids.append(str(element_nr))
            else:
                segment_tilda_ids.append(str(idx))
        
        result = {
            'segment_id': segment_id,
            'way_ids': segment_indices,
            'tilda_ids': '; '.join(segment_tilda_ids),
            'way_count': len(segment_indices),
            'length_m': round(total_length, 2),
            'is_short': is_short,
            'adjacent_ways_count': len(adjacent_ways),
            'adjacent_fuehr': adjacent_fuehr,
            'transition_description': transition_description
        }
        
        results.append(result)
    
    logger.info(f"Kurze Segmente (< 50m): {len(short_segments_geometries)}")
    
    return results, short_segments_geometries

def create_summary_statistics(results):
    """Erstelle Zusammenfassungsstatistiken."""
    logger.info("Erstelle Zusammenfassungsstatistiken...")
    
    # Filtere kurze Segmente
    short_segments = [r for r in results if r['is_short']]
    
    # Zähle Übergänge
    transitions = Counter()
    for result in short_segments:
        if result['transition_description']:
            transitions[result['transition_description']] += 1
    
    # Statistiken
    total_segments = len(results)
    short_segments_count = len(short_segments)
    avg_length = sum(r['length_m'] for r in short_segments) / max(1, len(short_segments))
    
    summary = {
        'total_segments': total_segments,
        'short_segments_count': short_segments_count,
        'short_segments_percentage': round(short_segments_count / max(1, total_segments) * 100, 1),
        'avg_length_short_segments': round(avg_length, 2),
        'most_common_transitions': transitions.most_common(10)
    }
    
    return summary, transitions

def save_results(results, short_segments_geometries, summary, transitions, output_dir):
    """Speichere alle Ergebnisse."""
    logger.info("Speichere Ergebnisse...")
    
    # 1. CSV mit detaillierter Analyse
    df_results = pd.DataFrame(results)
    df_results.to_csv(output_dir / "schutzstreifen_analysis.csv", index=False, encoding='utf-8')
    
    # 2. FGB mit kurzen Segmenten
    if short_segments_geometries:
        gdf_short = gpd.GeoDataFrame(short_segments_geometries, crs="EPSG:25833")
        gdf_short.to_file(output_dir / "short_schutzstreifen_segments.fgb", driver="FlatGeobuf")
    
    # 3. CSV mit Übergangshäufigkeiten
    transitions_data = []
    for transition, count in transitions.most_common():
        transitions_data.append({
            'transition': transition,
            'count': count,
            'percentage': round(count / max(1, summary['short_segments_count']) * 100, 1)
        })
    
    df_transitions = pd.DataFrame(transitions_data)
    df_transitions.to_csv(output_dir / "transitions_summary.csv", index=False, encoding='utf-8')
    
    # 4. CSV mit kurzen Schutzstreifen an Radfahrstreifen
    schutzstreifen_an_radfahrstreifen = []
    for result in results:
        # Nur kurze Segmente betrachten
        if result['is_short'] and result['adjacent_fuehr']:
            # Prüfen ob Radfahrstreifen in angrenzenden Führungsformen vorhanden
            if 'Radfahrstreifen' in result['adjacent_fuehr']:
                schutzstreifen_an_radfahrstreifen.append({
                    'segment_id': result['segment_id'],
                    'tilda_ids': result['tilda_ids'],
                    'way_count': result['way_count'],
                    'length_m': result['length_m'],
                    'adjacent_ways_count': result['adjacent_ways_count'],
                    'transition_description': result['transition_description'],
                    'adjacent_fuehr': '; '.join(result['adjacent_fuehr'])
                })
    
    if schutzstreifen_an_radfahrstreifen:
        df_schutz_rad = pd.DataFrame(schutzstreifen_an_radfahrstreifen)
        df_schutz_rad.to_csv(output_dir / "schutzstreifen_an_radfahrstreifen.csv", index=False, encoding='utf-8')
        logger.info(f"Kurze Schutzstreifen an Radfahrstreifen: {len(schutzstreifen_an_radfahrstreifen)}")
    else:
        logger.info("Keine kurzen Schutzstreifen an Radfahrstreifen gefunden")
    
    # 5. Zusammenfassung als Text
    with open(output_dir / "summary.txt", 'w', encoding='utf-8') as f:
        f.write("SCHUTZSTREIFEN-ANALYSE ZUSAMMENFASSUNG\n")
        f.write("=" * 50 + "\n\n")
        f.write(f"Gesamt Segmente: {summary['total_segments']}\n")
        f.write(f"Kurze Segmente (< 50m): {summary['short_segments_count']} ({summary['short_segments_percentage']}%)\n")
        f.write(f"Durchschnittslänge kurzer Segmente: {summary['avg_length_short_segments']}m\n\n")
        f.write("HÄUFIGSTE ÜBERGÄNGE:\n")
        for transition, count in summary['most_common_transitions']:
            percentage = round(count / max(1, summary['short_segments_count']) * 100, 1)
            f.write(f"  {transition}: {count} ({percentage}%)\n")
    
    logger.info(f"Ergebnisse gespeichert in {output_dir}")

def main():
    """Hauptfunktion."""
    logger.info("Starte Schutzstreifen-Analyse...")
    
    # Setup
    output_dir = setup_output_directory()
    snapping_network_path = "output/berlin_snapping_network_enriched.fgb"
    
    # Lade Daten
    all_ways_gdf = load_snapping_network(snapping_network_path)
    
    # Filtere Schutzstreifen
    schutzstreifen_gdf = filter_schutzstreifen(all_ways_gdf)
    
    if len(schutzstreifen_gdf) == 0:
        logger.error("Keine Schutzstreifen gefunden!")
        return
    
    # Finde zusammenhängende Segmente
    segments = find_connected_schutzstreifen(schutzstreifen_gdf)
    
    # Analysiere Segmente
    results, short_segments_geometries = analyze_segments(segments, schutzstreifen_gdf, all_ways_gdf)
    
    # Erstelle Statistiken
    summary, transitions = create_summary_statistics(results)
    
    # Speichere Ergebnisse
    save_results(results, short_segments_geometries, summary, transitions, output_dir)
    
    # Log Zusammenfassung
    logger.info("ANALYSE ABGESCHLOSSEN:")
    logger.info(f"  - Gesamt Segmente: {summary['total_segments']}")
    logger.info(f"  - Kurze Segmente: {summary['short_segments_count']} ({summary['short_segments_percentage']}%)")
    logger.info(f"  - Durchschnittslänge: {summary['avg_length_short_segments']}m")

if __name__ == "__main__":
    main()
