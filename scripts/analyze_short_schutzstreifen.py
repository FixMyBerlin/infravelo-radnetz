#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze_short_schutzstreifen.py
--------------------------------------------------------------------
Analysiert kurze Schutzstreifen (< 50m) aus dem berlin_snapping_network_enriched.fgb und
identifiziert angrenzende Führungsformen. Zusätzlich analysiert Schutzstreifen an Bushaltestellen.

INPUT:
- output/berlin_snapping_network_enriched.fgb
- output/bus_stops_on_rvn.fgb (Bushaltestellen auf RVN)

OUTPUT:
- output/analysis/short_schutzstreifen_segments.fgb (Geometrien der kurzen Segmente)
- output/analysis/schutzstreifen_analysis.csv (Detailanalyse)
- output/analysis/transitions_summary.csv (Häufigkeitsanalyse der Übergänge)
- output/analysis/schutzstreifen_an_radfahrstreifen.csv (Kurze Schutzstreifen die an Radfahrstreifen angrenzen)
- output/analysis/schutzstreifen_an_haltestellen.csv (Schutzstreifen an Bushaltestellen - ohne Längenbegrenzung)
- output/analysis/schutzstreifen_an_haltestellen_analysis.csv (Detailanalyse der Führungsformen an Haltestellen)
"""

import sys
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point, LineString, MultiLineString
from shapely.ops import linemerge
import logging
from collections import defaultdict, Counter
from pathlib import Path

# Import der Progressbar und Helper aus processing
sys.path.append(str(Path(__file__).parent.parent / 'processing'))
from helpers.progressbar import print_progressbar
from helpers.schutzstreifen_conversion_helper import get_endpoints, find_adjacent_ways
from helpers.schutzstreifen_conversion_helper import calculate_segment_length, merge_segment_geometries
from helpers.schutzstreifen_conversion_helper import find_connected_schutzstreifen

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
        logger.error(f"{\033[91m}❌ Fehler beim Laden der Daten: {e}{\033[0m}")
        sys.exit(1)

def filter_schutzstreifen(gdf):
    """Filtere alle Schutzstreifen aus den Daten."""
    schutzstreifen = gdf[gdf['fuehr'] == 'Schutzstreifen'].copy()
    logger.info(f"Gefundene Schutzstreifen: {len(schutzstreifen)}")
    return schutzstreifen

def load_bus_stops():
    """Lade Bushaltestellen auf RVN."""
    bus_stops_path = "output/bus_stops_on_rvn.fgb"
    try:
        bus_stops_gdf = gpd.read_file(bus_stops_path)
        logger.info(f"Bushaltestellen geladen: {len(bus_stops_gdf)} Haltestellen")
        return bus_stops_gdf
    except Exception as e:
        logger.warning(f"Bushaltestellen konnten nicht geladen werden: {e}")
        logger.warning("Bushaltestellen-Analyse wird übersprungen.")
        return None

def find_schutzstreifen_near_bus_stops(schutzstreifen_gdf, bus_stops_gdf, buffer_distance=50.0):
    """Finde Schutzstreifen in der Nähe von Bushaltestellen."""
    if bus_stops_gdf is None or len(bus_stops_gdf) == 0:
        return []
    
    logger.info(f"Suche Schutzstreifen in {buffer_distance}m Umkreis von Bushaltestellen...")
    
    # Stelle sicher, dass beide GeoDataFrames das gleiche CRS haben
    if schutzstreifen_gdf.crs != bus_stops_gdf.crs:
        bus_stops_gdf = bus_stops_gdf.to_crs(schutzstreifen_gdf.crs)
    
    # Erstelle Puffer um Bushaltestellen
    bus_stops_buffered = bus_stops_gdf.copy()
    bus_stops_buffered['geometry'] = bus_stops_buffered.geometry.buffer(buffer_distance)
    
    # Räumlicher Join: Finde Schutzstreifen die Bushaltestellen-Puffer schneiden
    schutzstreifen_near_stops = gpd.sjoin(
        schutzstreifen_gdf, 
        bus_stops_buffered[['geometry']], 
        how='inner', 
        predicate='intersects'
    )
    
    # Entferne Duplikate (falls ein Schutzstreifen mehrere Haltestellen trifft)
    original_columns = schutzstreifen_gdf.columns.tolist()
    schutzstreifen_near_stops = schutzstreifen_near_stops[original_columns].drop_duplicates()
    
    logger.info(f"Schutzstreifen an Bushaltestellen gefunden: {len(schutzstreifen_near_stops)}")
    
    return schutzstreifen_near_stops

def analyze_schutzstreifen_at_bus_stops(schutzstreifen_at_stops, all_ways_gdf):
    """Analysiere Schutzstreifen an Bushaltestellen und deren angrenzende Führungsformen."""
    if len(schutzstreifen_at_stops) == 0:
        return [], {}
    
    logger.info("Analysiere Schutzstreifen an Bushaltestellen...")
    
    results = []
    transitions_counter = Counter()
    
    for idx, schutzstreifen in schutzstreifen_at_stops.iterrows():
        # Finde angrenzende Wege (ohne Richtungscheck für Analyse)
        adjacent_ways = find_adjacent_ways(
            geometry=schutzstreifen.geometry, 
            all_ways_gdf=all_ways_gdf,
            check_direction=False
        )
        
        # Analysiere Führungsformen vor und nach dem Schutzstreifen
        adjacent_fuehr = [way['fuehr'] for way in adjacent_ways]
        unique_adjacent_fuehr = list(set(adjacent_fuehr))
        
        # Erstelle Übergangsbeschreibung
        if adjacent_fuehr:
            transition_description = " ↔ ".join(sorted(unique_adjacent_fuehr))
            transitions_counter[transition_description] += 1
        else:
            transition_description = "keine angrenzenden Wege"
        
        result = {
            'sfid': schutzstreifen.get('sfid', idx),
            'element_nr': schutzstreifen.get('element_nr', 'unknown'),
            'tilda_id': schutzstreifen.get('tilda_id', 'unknown'),
            'length_m': round(schutzstreifen.geometry.length, 2),
            'adjacent_ways_count': len(adjacent_ways),
            'adjacent_fuehr': '; '.join(adjacent_fuehr),
            'unique_adjacent_fuehr': '; '.join(unique_adjacent_fuehr),
            'transition_description': transition_description,
            'has_radfahrstreifen_adjacent': 'Radfahrstreifen' in adjacent_fuehr,
            'has_mischverkehr_adjacent': any('Mischverkehr' in fuehr for fuehr in adjacent_fuehr),
            'has_radweg_adjacent': any('Radweg' in fuehr for fuehr in adjacent_fuehr)
        }
        
        results.append(result)
    
    return results, transitions_counter


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
        
        # Finde angrenzende Wege (ohne Richtungscheck für Analyse)
        adjacent_ways = find_adjacent_ways(
            geometry=merged_geometry, 
            all_ways_gdf=all_ways_gdf,
            check_direction=False
        )
        
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

def save_results(results, short_segments_geometries, summary, transitions, output_dir, 
                bus_stops_results=None, bus_stops_transitions=None):
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
    
    # 5. NEUE: Bushaltestellen-Analyse speichern
    if bus_stops_results is not None and len(bus_stops_results) > 0:
        # CSV mit Schutzstreifen an Bushaltestellen (ohne Längenbegrenzung)
        df_bus_stops = pd.DataFrame(bus_stops_results)
        df_bus_stops.to_csv(output_dir / "schutzstreifen_an_haltestellen.csv", index=False, encoding='utf-8')
        
        # Detailanalyse der Führungsformen an Haltestellen
        bus_analysis_data = []
        if bus_stops_transitions:
            for transition, count in bus_stops_transitions.most_common():
                bus_analysis_data.append({
                    'transition': transition,
                    'count': count,
                    'percentage': round(count / len(bus_stops_results) * 100, 1)
                })
        
        df_bus_analysis = pd.DataFrame(bus_analysis_data)
        df_bus_analysis.to_csv(output_dir / "schutzstreifen_an_haltestellen_analysis.csv", index=False, encoding='utf-8')
        
        logger.info(f"Schutzstreifen an Bushaltestellen: {len(bus_stops_results)}")
        
        # Zusätzliche Statistiken für Bushaltestellen
        radfahrstreifen_count = sum(1 for r in bus_stops_results if r['has_radfahrstreifen_adjacent'])
        mischverkehr_count = sum(1 for r in bus_stops_results if r['has_mischverkehr_adjacent'])
        radweg_count = sum(1 for r in bus_stops_results if r['has_radweg_adjacent'])
        
        logger.info(f"  - Mit angrenzenden Radfahrstreifen: {radfahrstreifen_count}")
        logger.info(f"  - Mit angrenzenden Mischverkehr: {mischverkehr_count}")
        logger.info(f"  - Mit angrenzenden Radwegen: {radweg_count}")
    else:
        logger.info("Keine Bushaltestellen-Analyse durchgeführt")
    
    # 6. Zusammenfassung als Text (erweitert)
    with open(output_dir / "summary.txt", 'w', encoding='utf-8') as f:
        f.write("SCHUTZSTREIFEN-ANALYSE ZUSAMMENFASSUNG\n")
        f.write("=" * 50 + "\n\n")
        f.write("KURZE SCHUTZSTREIFEN (< 50m):\n")
        f.write(f"Gesamt Segmente: {summary['total_segments']}\n")
        f.write(f"Kurze Segmente (< 50m): {summary['short_segments_count']} ({summary['short_segments_percentage']}%)\n")
        f.write(f"Durchschnittslänge kurzer Segmente: {summary['avg_length_short_segments']}m\n\n")
        f.write("HÄUFIGSTE ÜBERGÄNGE (kurze Segmente):\n")
        for transition, count in summary['most_common_transitions']:
            percentage = round(count / max(1, summary['short_segments_count']) * 100, 1)
            f.write(f"  {transition}: {count} ({percentage}%)\n")
            
        # Bushaltestellen-Statistiken hinzufügen
        if bus_stops_results is not None and len(bus_stops_results) > 0:
            f.write(f"\n\nSCHUTZSTREIFEN AN BUSHALTESTELLEN (alle Längen):\n")
            f.write(f"Anzahl Schutzstreifen an Haltestellen: {len(bus_stops_results)}\n")
            
            avg_length_bus = sum(r['length_m'] for r in bus_stops_results) / len(bus_stops_results)
            f.write(f"Durchschnittslänge: {avg_length_bus:.1f}m\n")
            
            radfahrstreifen_count = sum(1 for r in bus_stops_results if r['has_radfahrstreifen_adjacent'])
            mischverkehr_count = sum(1 for r in bus_stops_results if r['has_mischverkehr_adjacent'])
            radweg_count = sum(1 for r in bus_stops_results if r['has_radweg_adjacent'])
            
            f.write(f"Mit angrenzenden Radfahrstreifen: {radfahrstreifen_count} ({radfahrstreifen_count/len(bus_stops_results)*100:.1f}%)\n")
            f.write(f"Mit angrenzenden Mischverkehr: {mischverkehr_count} ({mischverkehr_count/len(bus_stops_results)*100:.1f}%)\n")
            f.write(f"Mit angrenzenden Radwegen: {radweg_count} ({radweg_count/len(bus_stops_results)*100:.1f}%)\n")
            
            f.write(f"\nHÄUFIGSTE ÜBERGÄNGE (an Haltestellen):\n")
            if bus_stops_transitions:
                for transition, count in bus_stops_transitions.most_common(10):
                    percentage = round(count / len(bus_stops_results) * 100, 1)
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
    
    # TEIL 1: Analyse kurzer Schutzstreifen (< 50m) - bestehende Funktionalität
    logger.info("=" * 60)
    logger.info("TEIL 1: ANALYSE KURZER SCHUTZSTREIFEN (< 50m)")
    logger.info("=" * 60)
    
    # Finde zusammenhängende Segmente
    segments = find_connected_schutzstreifen(schutzstreifen_gdf)
    
    # Analysiere Segmente
    results, short_segments_geometries = analyze_segments(segments, schutzstreifen_gdf, all_ways_gdf)
    
    # Erstelle Statistiken
    summary, transitions = create_summary_statistics(results)
    
    # TEIL 2: Neue Analyse - Schutzstreifen an Bushaltestellen (alle Längen)
    logger.info("\n" + "=" * 60)
    logger.info("TEIL 2: ANALYSE SCHUTZSTREIFEN AN BUSHALTESTELLEN")
    logger.info("=" * 60)
    
    # Lade Bushaltestellen
    bus_stops_gdf = load_bus_stops()
    bus_stops_results = None
    bus_stops_transitions = None
    
    if bus_stops_gdf is not None:
        # Finde Schutzstreifen an Bushaltestellen (ohne Längenbegrenzung)
        schutzstreifen_at_stops = find_schutzstreifen_near_bus_stops(
            schutzstreifen_gdf, bus_stops_gdf, buffer_distance=20.0
        )
        
        if len(schutzstreifen_at_stops) > 0:
            # Analysiere angrenzende Führungsformen
            bus_stops_results, bus_stops_transitions = analyze_schutzstreifen_at_bus_stops(
                schutzstreifen_at_stops, all_ways_gdf
            )
        else:
            logger.info("Keine Schutzstreifen in der Nähe von Bushaltestellen gefunden")
    
    # Speichere alle Ergebnisse
    logger.info("\n" + "=" * 60)
    logger.info("ERGEBNISSE SPEICHERN")
    logger.info("=" * 60)
    
    save_results(results, short_segments_geometries, summary, transitions, output_dir,
                bus_stops_results, bus_stops_transitions)
    
    # Log Zusammenfassung
    logger.info("\n" + "=" * 60)
    logger.info("ANALYSE ABGESCHLOSSEN - ZUSAMMENFASSUNG:")
    logger.info("=" * 60)
    logger.info("KURZE SCHUTZSTREIFEN (< 50m):")
    logger.info(f"  - Gesamt Segmente: {summary['total_segments']}")
    logger.info(f"  - Kurze Segmente: {summary['short_segments_count']} ({summary['short_segments_percentage']}%)")
    logger.info(f"  - Durchschnittslänge: {summary['avg_length_short_segments']}m")
    
    if bus_stops_results:
        logger.info("SCHUTZSTREIFEN AN BUSHALTESTELLEN (alle Längen):")
        logger.info(f"  - Anzahl: {len(bus_stops_results)}")
        avg_length_bus = sum(r['length_m'] for r in bus_stops_results) / len(bus_stops_results)
        logger.info(f"  - Durchschnittslänge: {avg_length_bus:.1f}m")
        
        radfahrstreifen_count = sum(1 for r in bus_stops_results if r['has_radfahrstreifen_adjacent'])
        logger.info(f"  - Mit angrenzenden Radfahrstreifen: {radfahrstreifen_count} ({radfahrstreifen_count/len(bus_stops_results)*100:.1f}%)")
    
    logger.info("=" * 60)

if __name__ == "__main__":
    main()
