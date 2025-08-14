#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze_snapping_candidates.py
--------------------------------------------------------------------
Analysiert TILDA-Kandidaten für eine spezifische SFID und zeigt alle
gefundenen Kandidaten mit detaillierten Prioritätsinformationen an.

Dieses Skript hilft bei der Analyse, warum bestimmte TILDA-Kandidaten
ausgewählt oder nicht ausgewählt wurden.

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

# Importiere Funktionen aus dem Snapping-Modul
sys.path.append('./processing')
from helpers.globals import DEFAULT_CRS
from helpers.traffic_signs import has_traffic_sign
from start_snapping import (
    calculate_line_angle, 
    angle_difference, 
    calculate_angle_priority,
    calculate_osm_priority_detailed,
    find_best_candidate_for_direction,
    determine_segment_direction,
    SnappingPriorities,
    CONFIG_BUFFER_DEFAULT
)


def analyze_snapping_candidates_for_sfid(sfid, network_path, tilda_path, output_dir="./output/analysis", 
                                       buffer=CONFIG_BUFFER_DEFAULT, crs=DEFAULT_CRS):
    """
    Analysiert alle TILDA-Kandidaten für eine spezifische SFID.
    
    Args:
        sfid: Die zu analysierende SFID
        network_path: Pfad zur angereicherten Netzwerkdatei
        tilda_path: Pfad zu den TILDA-übersetzten Daten
        output_dir: Ausgabeverzeichnis für die Analyse
        buffer: Puffergröße für die Kandidatensuche
        crs: Koordinatensystem
    """
    
    # Lade Daten
    logging.info(f"Lade angereicherte Netzwerkdaten aus {network_path}...")
    network_gdf = gpd.read_file(network_path).to_crs(crs)
    
    logging.info(f"Lade TILDA-übersetzte Daten aus {tilda_path}...")
    tilda_gdf = gpd.read_file(tilda_path).to_crs(crs)
    
    # Finde das Segment mit der angegebenen SFID
    segment_rows = network_gdf[network_gdf['sfid'] == sfid]
    if len(segment_rows) == 0:
        logging.error(f"Keine Segmente mit SFID {sfid} gefunden!")
        return None
        
    if len(segment_rows) > 1:
        logging.warning(f"Mehrere Segmente mit SFID {sfid} gefunden ({len(segment_rows)}). Verwende das erste.")
    
    segment = segment_rows.iloc[0]
    segment_geom = segment.geometry
    
    logging.info(f"Analysiere Segment SFID {sfid}:")
    logging.info(f"  Element-Nr: {segment.get('element_nr', 'N/A')}")
    logging.info(f"  Straßenname: {segment.get('strassenname', 'N/A')}")
    logging.info(f"  Länge: {segment.get('Länge', 'N/A')} m")
    logging.info(f"  Aktueller fuehr-Wert: {segment.get('fuehr', 'N/A')}")
    
    # Erstelle räumlichen Index für TILDA-Daten
    tilda_sidx = tilda_gdf.sindex
    
    # Finde alle TILDA-Kandidaten im Buffer
    buffer_geom = segment_geom.buffer(buffer, cap_style='flat')
    cand_idx = list(tilda_sidx.intersection(buffer_geom.bounds))
    
    if not cand_idx:
        logging.warning(f"Keine TILDA-Kandidaten im Buffer von {buffer}m gefunden!")
        return None
    
    # Filtere Kandidaten nach tatsächlicher Entfernung
    candidates = tilda_gdf.iloc[cand_idx].copy()
    candidates["distance"] = candidates.geometry.distance(segment_geom)
    candidates = candidates[candidates["distance"] <= buffer]
    
    if len(candidates) == 0:
        logging.warning(f"Keine TILDA-Kandidaten nach Entfernungsfilter im Buffer von {buffer}m!")
        return None
    
    logging.info(f"Gefundene TILDA-Kandidaten im Buffer: {len(candidates)}")
    
    # Berechne Segment-Winkel
    segment_angle = calculate_line_angle(segment_geom)
    logging.info(f"Segment-Winkel: {segment_angle:.1f}°")
    
    # Erstelle Segment-Dictionary für Prioritätsberechnung
    seg_dict = {
        'element_nr': segment.get('element_nr'),
        'strassenname': segment.get('strassenname'),
        'geometry': segment_geom,
        'beginnt_bei_vp': segment.get('beginnt_bei_vp'),
        'endet_bei_vp': segment.get('endet_bei_vp')
    }
    
    # Analysiere alle Kandidaten
    candidate_analysis = []
    
    for idx, candidate in candidates.iterrows():
        analysis = analyze_single_candidate(candidate, seg_dict, segment_angle, buffer)
        candidate_analysis.append(analysis)
    
    # Sortiere Kandidaten nach Gesamtpriorität (absteigend)
    candidate_analysis.sort(key=lambda x: x['total_priority'], reverse=True)
    
    # Finde beste Kandidaten für beide Richtungen
    best_ri0 = find_best_candidate_for_direction(candidates, seg_dict, 0, segment_angle)
    best_ri1 = find_best_candidate_for_direction(candidates, seg_dict, 1, segment_angle)
    
    # Schreibe Analyse in Textdatei
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, f"sfid_{sfid}_kandidaten_analyse.txt")
    
    with open(output_file, 'w', encoding='utf-8') as f:
        write_candidate_analysis(f, sfid, segment, seg_dict, segment_angle, 
                               candidate_analysis, best_ri0, best_ri1, buffer)
    
    logging.info(f"Analyse gespeichert: {output_file}")
    return output_file


def analyze_single_candidate(candidate, seg_dict, segment_angle, buffer):
    """
    Analysiert einen einzelnen TILDA-Kandidaten und berechnet alle Prioritäten.
    """
    candidate_geom = candidate.geometry
    candidate_angle = calculate_line_angle(candidate_geom)
    
    # Berechne detaillierte Prioritäten
    total_priority, priority_details = calculate_osm_priority_detailed(candidate, seg_dict)
    
    # Berechne geometrische Prioritäten
    angle_priority = calculate_angle_priority(seg_dict["geometry"], candidate_geom)
    angle_diff = angle_difference(segment_angle, candidate_angle)
    
    # Berechne Entfernung zum Segmentmittelpunkt
    segment_mid = seg_dict["geometry"].interpolate(0.5, normalized=True)
    dist_to_mid = candidate_geom.distance(segment_mid)
    
    # Berechne Richtungskompatibilität für beide Richtungen
    ri0_direction = determine_segment_direction(seg_dict["geometry"], candidate_geom)
    ri1_direction = 1 - ri0_direction
    
    verkehrsri = candidate.get('verkehrsri', '')
    
    # Richtungskompatibilität berechnen
    if verkehrsri == 'Einrichtungsverkehr':
        ri0_compatibility = SnappingPriorities.DIRECTION_PERFECT_MATCH if ri0_direction == 0 else SnappingPriorities.DIRECTION_WRONG_WAY
        ri1_compatibility = SnappingPriorities.DIRECTION_PERFECT_MATCH if ri1_direction == 1 else SnappingPriorities.DIRECTION_WRONG_WAY
    else:
        ri0_compatibility = SnappingPriorities.DIRECTION_BIDIRECTIONAL  # Zweirichtungsverkehr
        ri1_compatibility = SnappingPriorities.DIRECTION_BIDIRECTIONAL
    
    return {
        'tilda_id': candidate.get('tilda_id', 'N/A'),
        'tilda_name': candidate.get('tilda_name', 'N/A'),
        'tilda_category': candidate.get('tilda_category', 'N/A'),
        'tilda_traffic_sign': candidate.get('tilda_traffic_sign', 'N/A'),
        'verkehrsri': verkehrsri,
        'fuehr': candidate.get('fuehr', 'N/A'),
        'ofm': candidate.get('ofm', 'N/A'),
        'protek': candidate.get('protek', 'N/A'),
        'breite': candidate.get('breite', 'N/A'),
        'farbe': candidate.get('farbe', 'N/A'),
        'distance': candidate.get('distance', 0),
        'dist_to_mid': dist_to_mid,
        'candidate_angle': candidate_angle,
        'angle_diff': angle_diff,
        'angle_priority': angle_priority,
        'total_priority': total_priority,
        'priority_details': priority_details,
        'ri0_direction': ri0_direction,
        'ri1_direction': ri1_direction,
        'ri0_compatibility': ri0_compatibility,
        'ri1_compatibility': ri1_compatibility
    }


def write_candidate_analysis(f, sfid, segment, seg_dict, segment_angle, 
                           candidate_analysis, best_ri0, best_ri1, buffer):
    """
    Schreibt die detaillierte Kandidatenanalyse in eine Textdatei.
    """
    f.write("=" * 80 + "\n")
    f.write(f"TILDA-KANDIDATEN ANALYSE FÜR SFID {sfid}\n")
    f.write("=" * 80 + "\n")
    f.write(f"Erstellt am: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
    
    # Segment-Informationen
    f.write("SEGMENT-INFORMATIONEN:\n")
    f.write("-" * 40 + "\n")
    f.write(f"SFID:           {sfid}\n")
    f.write(f"Element-Nr:     {segment.get('element_nr', 'N/A')}\n")
    f.write(f"Straßenname:    {segment.get('strassenname', 'N/A')}\n")
    f.write(f"Länge:          {segment.get('Länge', 'N/A')} m\n")
    f.write(f"Winkel:         {segment_angle:.1f}°\n")
    f.write(f"Aktueller fuehr: {segment.get('fuehr', 'N/A')}\n")
    f.write(f"ri:             {segment.get('ri', 'N/A')}\n")
    f.write(f"Buffer:         {buffer} m\n")
    f.write("\n")
    
    # Zusammenfassung der gefundenen Kandidaten
    f.write("KANDIDATEN-ÜBERSICHT:\n")
    f.write("-" * 40 + "\n")
    f.write(f"Anzahl gefundene Kandidaten: {len(candidate_analysis)}\n")
    
    if best_ri0:
        f.write(f"Bester Kandidat ri=0:        {best_ri0.get('tilda_id', 'N/A')}\n")
    else:
        f.write("Bester Kandidat ri=0:        Keiner gefunden\n")
        
    if best_ri1:
        f.write(f"Bester Kandidat ri=1:        {best_ri1.get('tilda_id', 'N/A')}\n")
    else:
        f.write("Bester Kandidat ri=1:        Keiner gefunden\n")
    
    f.write("\n")

    
    # Detaillierte Kandidatenanalyse
    f.write("DETAILLIERTE KANDIDATEN-ANALYSE:\n")
    f.write("=" * 80 + "\n")
    
    for i, analysis in enumerate(candidate_analysis, 1):
        f.write(f"KANDIDAT {i}: {analysis['tilda_id']}\n")
        f.write("-" * 50 + "\n")
        
        # Grundinformationen
        f.write("Grunddaten:\n")
        f.write(f"  TILDA-ID:         {analysis['tilda_id']}\n")
        f.write(f"  Name:             {analysis['tilda_name']}\n")
        f.write(f"  Kategorie:        {analysis['tilda_category']}\n")
        f.write(f"  Verkehrszeichen:  {analysis['tilda_traffic_sign']}\n")
        f.write(f"  Verkehrsrichtung: {analysis['verkehrsri']}\n")
        
        # Attribute
        f.write("\nTILDA-Attribute:\n")
        f.write(f"  fuehr:    {analysis['fuehr']}\n")
        f.write(f"  ofm:      {analysis['ofm']}\n")
        f.write(f"  protek:   {analysis['protek']}\n")
        f.write(f"  breite:   {analysis['breite']}\n")
        f.write(f"  farbe:    {analysis['farbe']}\n")
        
        # Geometrische Daten
        f.write("\nGeometrische Daten:\n")
        f.write(f"  Entfernung:       {analysis['distance']:.2f} m\n")
        f.write(f"  Entf. zu Mitte:   {analysis['dist_to_mid']:.2f} m\n")
        f.write(f"  Kandidat-Winkel:  {analysis['candidate_angle']:.1f}°\n")
        f.write(f"  Winkel-Diff:      {analysis['angle_diff']:.1f}°\n")
        
        # Richtungsanalyse
        f.write("\nRichtungsanalyse:\n")
        f.write(f"  ri=0 Richtung:    {analysis['ri0_direction']} ({'passend' if analysis['ri0_direction'] == 0 else 'gegenläufig'})\n")
        f.write(f"  ri=1 Richtung:    {analysis['ri1_direction']} ({'passend' if analysis['ri1_direction'] == 1 else 'gegenläufig'})\n")
        f.write(f"  ri=0 Kompatib.:   {analysis['ri0_compatibility']:+d} Punkte\n")
        f.write(f"  ri=1 Kompatib.:   {analysis['ri1_compatibility']:+d} Punkte\n")
        
        # Prioritäts-Breakdown
        details = analysis['priority_details']
        f.write("\nPrioritäts-Breakdown:\n")
        f.write(f"  Traffic Sign:     {details['traffic_priority']:+d} Punkte ({details['traffic_sign']})\n")
        if details['traffic_sign_matched']:
            f.write(f"    → Erkannt:      {details['traffic_sign_matched']}\n")
        f.write(f"  Kategorie:        {details['category_priority']:+d} Punkte ({details['category']})\n")
        if details['category_pattern']:
            f.write(f"    → Pattern:      {details['category_pattern']}\n")
        f.write(f"  Straßenname:      {details['street_name_priority']:+d} Punkte ({details['street_name_detail']})\n")
        f.write(f"  Winkel:           {analysis['angle_priority']:+.2f} Punkte\n")
        f.write(f"  GESAMT PRIORITÄT: {analysis['total_priority']:+d} Punkte\n")
        
        # Bewertung
        f.write("\nBewertung:\n")
        if analysis['total_priority'] > 10:
            f.write("  → HOCH: Sehr guter Kandidat\n")
        elif analysis['total_priority'] > 5:
            f.write("  → MITTEL: Guter Kandidat\n")
        elif analysis['total_priority'] > 0:
            f.write("  → NIEDRIG: Durchschnittlicher Kandidat\n")
        else:
            f.write("  → SCHLECHT: Ungeeigneter Kandidat\n")
        
        # Prüfe ob dieser Kandidat als bester ausgewählt wurde
        is_best_ri0 = best_ri0 and best_ri0.get('tilda_id') == analysis['tilda_id']
        is_best_ri1 = best_ri1 and best_ri1.get('tilda_id') == analysis['tilda_id']
        
        if is_best_ri0 or is_best_ri1:
            directions = []
            if is_best_ri0:
                directions.append("ri=0")
            if is_best_ri1:
                directions.append("ri=1")
            f.write(f"  *** AUSGEWÄHLT für {', '.join(directions)} ***\n")
        
        f.write("\n")
    
    # Zusammenfassung
    f.write("ZUSAMMENFASSUNG:\n")
    f.write("=" * 50 + "\n")
    if len(candidate_analysis) == 0:
        f.write("Keine Kandidaten gefunden.\n")
    else:
        best_candidate = candidate_analysis[0]
        f.write(f"Bester Gesamtkandidat: {best_candidate['tilda_id']} ({best_candidate['total_priority']:+d} Punkte)\n")
        f.write(f"Schlechtester Kandidat: {candidate_analysis[-1]['tilda_id']} ({candidate_analysis[-1]['total_priority']:+d} Punkte)\n")
        
        # Statistiken
        priorities = [c['total_priority'] for c in candidate_analysis]
        f.write(f"\nPrioritäts-Statistiken:\n")
        f.write(f"  Durchschnitt: {np.mean(priorities):.1f} Punkte\n")
        f.write(f"  Median:       {np.median(priorities):.1f} Punkte\n")
        f.write(f"  Bereich:      {min(priorities)} bis {max(priorities)} Punkte\n")


def main():
    """Hauptfunktion für CLI-Nutzung"""
    parser = argparse.ArgumentParser(description="Analysiere TILDA-Kandidaten für eine spezifische SFID")
    parser.add_argument("sfid", type=int, help="Die zu analysierende SFID")
    parser.add_argument("--network", default="./output/snapping_network_enriched_neukoelln.fgb",
                       help="Pfad zur angereicherten Netzwerkdatei")
    parser.add_argument("--tilda", default="./output/matched/matched_tilda_ways.fgb", 
                       help="Pfad zu den TILDA-übersetzten Daten")
    parser.add_argument("--output-dir", default="./output/analysis",
                       help="Ausgabeverzeichnis für die Analyse")
    parser.add_argument("--buffer", type=float, default=CONFIG_BUFFER_DEFAULT,
                       help=f"Puffergröße für Kandidatensuche (default: {CONFIG_BUFFER_DEFAULT}m)")
    parser.add_argument("--crs", type=int, default=DEFAULT_CRS,
                       help=f"Koordinatensystem EPSG-Code (default: {DEFAULT_CRS})")
    
    args = parser.parse_args()
    
    # Logging konfigurieren
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s: %(message)s',
        datefmt='%H:%M:%S'
    )
    
    # Prüfe ob Eingabedateien existieren
    if not os.path.exists(args.network):
        logging.error(f"Netzwerkdatei nicht gefunden: {args.network}")
        sys.exit(1)
        
    if not os.path.exists(args.tilda):
        logging.error(f"TILDA-Datei nicht gefunden: {args.tilda}")
        sys.exit(1)
    
    # Führe Analyse durch
    try:
        output_file = analyze_snapping_candidates_for_sfid(
            args.sfid, args.network, args.tilda, args.output_dir, 
            args.buffer, args.crs
        )
        
        if output_file:
            print(f"✔  Analyse abgeschlossen: {output_file}")
        else:
            print("✗  Analyse fehlgeschlagen")
            sys.exit(1)
            
    except Exception as e:
        logging.error(f"Fehler bei der Analyse: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
