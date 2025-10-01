#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze_snapping_candidates.py
--------------------------------------------------------------------
Analysiert TILDA-Kandidaten für eine spezifische SFID und zeigt alle
gefundenen Kandidaten mit detaillierten Prioritätsinformationen an.

Verwendet dieselbe Methodik wie start_snapping.py und snapping_analysis.py
für exakte Nachvollziehbarkeit der Kandidatenauswahl.

INPUT:
- output/snapping_network_enriched.fgb (angereicherte Netzwerkdaten)
- output/matched/matched_tilda_ways.fgb (TILDA-übersetzte Daten)

OUTPUT:
- Textdatei mit detaillierter Kandidatenanalyse
"""

import argparse
import logging
import os
import sys
from pathlib import Path
import geopandas as gpd
import numpy as np
import pandas as pd
from datetime import datetime

# Füge das processing Verzeichnis zum Pfad hinzu
processing_dir = os.path.join(os.path.dirname(__file__), '..', 'processing')
sys.path.insert(0, processing_dir)

# Importiere gemeinsame Snapping-Funktionen - verwende dieselben wie start_snapping.py
from helpers.globals import DEFAULT_CRS
from helpers.snapping_analysis import (
    SnappingPriorities,
    calculate_line_angle,
    angle_difference, 
    calculate_angle_priority,
    calculate_distance_priority,
    determine_segment_direction,
    calculate_osm_priority_detailed,
    find_best_candidate_for_direction
)


def analyze_candidates_for_sfid(sfid, network_gdf, tilda_gdf, buffer_distance=25):
    """
    Analysiert alle TILDA-Kandidaten für eine spezifische SFID unter Verwendung 
    der aktuellen Snapping-Methodik aus snapping_analysis.py.
    
    Args:
        sfid (int): SFID des zu analysierenden Segments
        network_gdf (GeoDataFrame): Netzwerkdaten
        tilda_gdf (GeoDataFrame): TILDA-Daten
        buffer_distance (float): Pufferentfernung in Metern
        
    Returns:
        dict: Analyseergebnisse mit Kandidateninformationen
    """
    # Finde das entsprechende Segment im Netzwerk
    segment = network_gdf[network_gdf['sfid'] == sfid]
    if segment.empty:
        logging.error(f"SFID {sfid} nicht im Netzwerk gefunden!")
        return None
    
    segment = segment.iloc[0]
    logging.info(f"Analysiere SFID {sfid}: {segment.get('strassenname', 'Unbekannt')} ({segment.get('strklasse', 'N/A')})")
    
    # Bestimme Segment-Richtung
    segment_direction = calculate_line_angle(segment.geometry)
    logging.info(f"Segment-Richtung: {segment_direction:.2f}°")
    
    buffer_geom = segment.geometry.buffer(buffer_distance)
    
    # Finde alle TILDA-Kandidaten im Buffer
    candidates = tilda_gdf[tilda_gdf.geometry.intersects(buffer_geom)].copy()
    
    if candidates.empty:
        logging.warning(f"Keine TILDA-Kandidaten im {buffer_distance}m Buffer für SFID {sfid} gefunden!")
        return {"segment": segment, "candidates": [], "selected": None}
    
    logging.info(f"Gefundene TILDA-Kandidaten im Buffer: {len(candidates)}")
    
    candidate_list = []
    
    # Erstelle seg_dict wie in start_snapping.py
    seg_dict = {
        'sfid': segment['sfid'],
        'strassenname': segment.get('strassenname', ''),
        'geometry': segment.geometry,
        'ri': segment.get('ri', 0)
    }
    
    # Analysiere jeden Kandidaten - ähnlich wie in start_snapping.py
    for idx, candidate in candidates.iterrows():
        # Berechne OSM-Priorität MIT seg_dict für korrekte Straßennamen-Bewertung
        osm_priority_result = calculate_osm_priority_detailed(candidate, seg_dict)
        if isinstance(osm_priority_result, tuple):
            osm_priority = osm_priority_result[0]  # Nimm den ersten Wert des Tupels
        else:
            osm_priority = osm_priority_result
        
        # Berechne Distanz
        distance = segment.geometry.distance(candidate.geometry)
        distance_priority = calculate_distance_priority(distance)
        
        # Berechne Winkel-Priorität
        candidate_direction = calculate_line_angle(candidate.geometry)
        angle_diff = angle_difference(segment_direction, candidate_direction)
        angle_priority = calculate_angle_priority(segment.geometry, candidate.geometry)
        
        # Berechne Richtungskompatibilität (exakt wie in snapping_analysis.py)
        candidate_verkehrsri = candidate.get('verkehrsri', '')
        priorities = SnappingPriorities()
        
        if candidate_verkehrsri == 'Einrichtungsverkehr':
            # Bei Einrichtungsverkehr: Prüfe Richtungsausrichtung
            segment_direction_ri = determine_segment_direction(segment.geometry, candidate.geometry)
            
            # ri_value ist die Richtung des Segments (0=Hinrichtung, 1=Rückrichtung)
            ri_value = segment.get('ri', 0)
            
            if segment_direction_ri == ri_value:
                # Richtung passt perfekt
                direction_compatibility = priorities.DIRECTION_PERFECT_MATCH
            else:
                # Richtung passt nicht - NEGATIVE Priorität für gegenläufige Wege
                direction_compatibility = priorities.DIRECTION_WRONG_WAY
        else:
            # Bei Zweirichtungsverkehr: Kann für beide Richtungen verwendet werden
            direction_compatibility = priorities.DIRECTION_BIDIRECTIONAL
        
        # Berechne gewichtete Gesamtpriorität (exakt wie in snapping_analysis.py)
        total_priority_weighted = (
            osm_priority +                  # TILDA-Priorität (Inhalt)
            angle_priority +                # Winkel-Priorität (beinhaltet Richtungsausrichtung)  
            distance_priority +             # Entfernungs-Priorität
            direction_compatibility         # Richtungskompatibilität
        )
        
        # Hole detaillierte OSM-Priorität mit Breakdown-Informationen
        osm_priority_details = osm_priority_result[1] if isinstance(osm_priority_result, tuple) and len(osm_priority_result) > 1 else {}
        
        candidate_info = {
            'osmid': candidate.get('tilda_osm_id', 'N/A'),
            'TILDA_id': candidate.get('tilda_id', 'N/A'),
            'tilda_name': candidate.get('tilda_name', 'N/A'),
            'fuehr': candidate.get('fuehr', 'N/A'),
            'breite': candidate.get('breite', 'N/A'),
            'tilda_width': candidate.get('tilda_width', 'N/A'),
            'tilda_surface': candidate.get('tilda_surface', 'N/A'),
            'tilda_surface_color': candidate.get('tilda_surface_color', 'N/A'),
            'farbe': candidate.get('farbe', 'N/A'),
            'tilda_oneway': candidate.get('tilda_oneway', 'N/A'),
            'tilda_category': candidate.get('tilda_category', 'N/A'),
            'tilda_traffic_sign': candidate.get('tilda_traffic_sign', 'N/A'),
            'geometry_type': str(type(candidate.geometry).__name__),
            'candidate_direction': candidate_direction,
            'distance': distance,
            'angle_diff': angle_diff,
            'osm_priority': osm_priority,
            'osm_priority_details': osm_priority_details,
            'angle_priority': angle_priority,
            'distance_priority': distance_priority,
            'direction_compatibility': direction_compatibility,
            'total_priority_weighted': total_priority_weighted,
            'is_above_threshold': total_priority_weighted >= priorities.MINIMUM_TOTAL_PRIORITY
        }
        
        candidate_list.append(candidate_info)
    
    # Sortiere Kandidaten nach Gesamtpriorität (höchste zuerst)
    candidate_list.sort(key=lambda x: x['total_priority_weighted'], reverse=True)
    
    # Bestimme den besten Kandidaten - verwende dieselbe Funktion wie start_snapping.py
    ri_value = segment.get('ri', 0)  # Verwende die korrekte ri aus dem Segment
    best_candidate = find_best_candidate_for_direction(
        candidates, 
        seg_dict, 
        ri_value,  # Korrekte ri statt None
        segment_direction
    )
    
    selected_candidate = None
    if best_candidate is not None:
        # Prüfe sowohl tilda_osm_id als auch tilda_id für das Matching
        selected_tilda_osm_id = best_candidate.get('tilda_osm_id', None)
        selected_tilda_id = best_candidate.get('tilda_id', None)
        selected_candidate = next(
            (c for c in candidate_list 
             if c['osmid'] == selected_tilda_osm_id or c['TILDA_id'] == selected_tilda_id), 
            None
        )
    
    return {
        "segment": segment,
        "segment_direction": segment_direction,
        "candidates": candidate_list,
        "selected": selected_candidate,
        "total_candidates": len(candidate_list),
        "valid_candidates": len([c for c in candidate_list if c['is_above_threshold']])
    }


def write_analysis_report(analysis_result, output_path):
    """
    Schreibt einen detaillierten Analysebericht in eine Textdatei.
    
    Args:
        analysis_result (dict): Analyseergebnisse von analyze_candidates_for_sfid
        output_path (str): Pfad zur Ausgabedatei
    """
    if analysis_result is None:
        return
    
    segment = analysis_result["segment"]
    candidates = analysis_result["candidates"]
    selected = analysis_result["selected"]
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write("="*80 + "\n")
        f.write(f"SNAPPING-KANDIDATEN ANALYSE FÜR SFID {segment['sfid']}\n")
        f.write(f"Erstellt am: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("="*80 + "\n\n")
        
        # Segment-Informationen
        f.write("SEGMENT-INFORMATIONEN:\n")
        f.write("-"*40 + "\n")
        f.write(f"SFID: {segment['sfid']}\n")
        f.write(f"Straßenname: {segment.get('strassenname', 'N/A')}\n")
        f.write(f"Straßenklasse: {segment.get('strklasse', 'N/A')}\n")
        f.write(f"Segment-Richtung: {analysis_result['segment_direction']:.2f}°\n")
        f.write(f"Geometrie-Typ: {type(segment.geometry).__name__}\n")
        f.write(f"Aktuelle fuehr: {segment.get('fuehr', 'N/A')}\n")
        f.write(f"Aktuelle breite: {segment.get('breite', 'N/A')}\n")
        f.write(f"Aktuelle belag: {segment.get('belag', 'N/A')}\n")
        f.write(f"Aktuelle farbe: {segment.get('farbe', 'N/A')}\n")
        f.write("\n")
        
        # Zusammenfassung
        f.write("KANDIDATEN-ZUSAMMENFASSUNG:\n")
        f.write("-"*40 + "\n")
        f.write(f"Gesamt gefundene Kandidaten: {analysis_result['total_candidates']}\n")
        f.write(f"Kandidaten über Mindest-Priorität: {analysis_result['valid_candidates']}\n")
        
        if selected:
            f.write(f"Ausgewählter Kandidat: OSMID {selected['osmid']} (TILDA_id: {selected['TILDA_id']})\n")
            f.write(f"Ausgewählte Priorität: {selected['total_priority_weighted']:.2f}\n")
        else:
            f.write("Ausgewählter Kandidat: KEINE AUSWAHL\n")
        f.write("\n")
        
        # Schwellenwerte
        priorities = SnappingPriorities()
        f.write("SNAPPING-KONFIGURATION:\n")
        f.write("-"*40 + "\n")
        f.write(f"Mindest-Gesamtpriorität: {priorities.MINIMUM_TOTAL_PRIORITY}\n")
        f.write(f"Straßenname Match Belohnung: {priorities.STREET_NAME_MATCH_REWARD}\n")
        f.write(f"Straßenname Mismatch Strafe: {priorities.STREET_NAME_MISMATCH_PENALTY}\n")
        f.write(f"Perfekte Richtung: {priorities.DIRECTION_PERFECT_MATCH}\n")
        f.write(f"Bidirektionale Richtung: {priorities.DIRECTION_BIDIRECTIONAL}\n")
        f.write(f"Falsche Richtung: {priorities.DIRECTION_WRONG_WAY}\n")
        f.write("\n")
        
        # Detaillierte Kandidaten-Liste
        f.write("DETAILLIERTE KANDIDATEN-ANALYSE:\n")
        f.write("="*80 + "\n")
        
        for i, candidate in enumerate(candidates, 1):
            f.write(f"\nKANDIDAT #{i} {'(AUSGEWÄHLT)' if selected and candidate['osmid'] == selected['osmid'] else ''}\n")
            f.write("-"*50 + "\n")
            f.write(f"OSM ID: {candidate['osmid']}\n")
            f.write(f"TILDA_id: {candidate['TILDA_id']}\n")
            f.write(f"TILDA Name: {candidate['tilda_name']}\n")
            f.write(f"Führung: {candidate['fuehr']}\n")
            f.write(f"Breite (RVN): {candidate['breite']}\n")
            f.write(f"TILDA Breite: {candidate['tilda_width']}\n")
            f.write(f"TILDA Oberfläche: {candidate['tilda_surface']}\n")
            f.write(f"TILDA Oberflächenfarbe: {candidate['tilda_surface_color']}\n")
            f.write(f"Farbe (RVN): {candidate['farbe']}\n")
            f.write(f"TILDA Einbahnstraße: {candidate['tilda_oneway']}\n")
            f.write(f"TILDA Kategorie: {candidate['tilda_category']}\n")
            f.write(f"TILDA Verkehrszeichen: {candidate['tilda_traffic_sign']}\n")
            f.write(f"Geometrie-Typ: {candidate['geometry_type']}\n")
            f.write(f"Kandidaten-Richtung: {candidate['candidate_direction']:.2f}°\n")
            f.write(f"Entfernung: {candidate['distance']:.2f}m\n")
            f.write(f"Winkel-Unterschied: {candidate['angle_diff']:.2f}°\n")
            f.write("\n")
            f.write("PRIORITÄTS-BREAKDOWN:\n")
            f.write(f"  TILDA-Priorität: {candidate['osm_priority']:.2f}\n")
            
            # Detailliertes Breakdown der TILDA-Priorität anzeigen
            if 'osm_priority_details' in candidate and candidate['osm_priority_details']:
                details = candidate['osm_priority_details']
                f.write(f"    ├─ Verkehrszeichen-Priorität: {details.get('traffic_priority', 0)}\n")
                f.write(f"    │  (Zeichen: {details.get('traffic_sign', 'None')}, Match: {details.get('traffic_sign_matched', 'None')})\n")
                f.write(f"    ├─ Kategorie-Priorität: {details.get('category_priority', 0)}\n")
                f.write(f"    │  (Kategorie: {details.get('category', 'None')}, Pattern: {details.get('category_pattern', 'None')})\n")
                f.write(f"    └─ Straßenname-Priorität: {details.get('street_name_priority', 0)}\n")
                f.write(f"       (Detail: {details.get('street_name_detail', 'N/A')})\n")
            
            f.write(f"  Winkel-Priorität: {candidate['angle_priority']:.2f}\n")
            f.write(f"  Distanz-Priorität: {candidate['distance_priority']:.2f}\n")
            f.write(f"  Richtungskompatibilität: {candidate['direction_compatibility']:.2f}\n")
            f.write(f"  GESAMT-PRIORITÄT: {candidate['total_priority_weighted']:.2f}\n")
            f.write(f"  Über Schwellenwert: {'JA' if candidate['is_above_threshold'] else 'NEIN'}\n")
    
    logging.info(f"Analysebericht geschrieben nach: {output_path}")


def main():
    """Hauptfunktion für die Kommandozeilen-Nutzung."""
    parser = argparse.ArgumentParser(
        description='Analysiert TILDA-Kandidaten für eine spezifische SFID'
    )
    parser.add_argument('sfid', type=int, help='SFID des zu analysierenden Segments')
    parser.add_argument('--bezirk', default='', 
                       help='Bezirk für die Analyse (default: None)')
    parser.add_argument('--buffer', type=float, default=25,
                       help='Pufferentfernung in Metern (default: 25)')
    parser.add_argument('--output-dir', 
                       default='output/analysis',
                       help='Ausgabeverzeichnis (default: output/analysis)')
    
    args = parser.parse_args()
    
    # Logging konfigurieren
    logging.basicConfig(
        level=logging.DEBUG,  # DEBUG statt INFO für detaillierte Ausgabe
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    # Dateipfade konfigurieren
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    
    if args.bezirk == 'neukoelln':
        network_file = project_root / 'output' / 'snapping_network_enriched_neukoelln.fgb'
        tilda_file = project_root / 'output' / 'matched' / 'matched_tilda_ways.fgb'
        output_suffix = '_neukoelln'
    else:
        network_file = project_root / 'output' / 'snapping_network_enriched.fgb'
        tilda_file = project_root / 'output' / 'matched' / 'matched_tilda_ways.fgb'
        output_suffix = ''
    
    # Ausgabeverzeichnis erstellen
    output_dir = project_root / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        # Lade Geodaten
        logging.info(f"Lade Netzwerkdaten: {network_file}")
        network_gdf = gpd.read_file(network_file)
        logging.info(f"Netzwerk geladen: {len(network_gdf)} Segmente")
        
        logging.info(f"Lade TILDA-Daten: {tilda_file}")
        tilda_gdf = gpd.read_file(tilda_file)
        logging.info(f"TILDA geladen: {len(tilda_gdf)} Features")
        
        # Führe Analyse durch
        analysis_result = analyze_candidates_for_sfid(
            args.sfid, 
            network_gdf, 
            tilda_gdf, 
            args.buffer
        )
        
        if analysis_result is None:
            logging.error("Analyse fehlgeschlagen!")
            return 1
        
        # Schreibe Bericht
        output_file = output_dir / f'snapping_candidates_analysis_SFID_{args.sfid}{output_suffix}.txt'
        write_analysis_report(analysis_result, output_file)
        
        logging.info(f"Analyse abgeschlossen für SFID {args.sfid}")
        return 0
        
    except Exception as e:
        logging.error(f"Fehler bei der Analyse: {e}")
        return 1


if __name__ == "__main__":
    exit(main())