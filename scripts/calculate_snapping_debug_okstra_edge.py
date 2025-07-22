#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
calculate_snapping_debug_okstra_edge.py
-----------------------------------------------------------------------
Debug-Skript für das Snapping einzelner okstra_id Kanten.
Berechnet OSM-Kandidaten und zeigt die ausgewählten Kandidaten pro Richtung.

Verwendet das start_snapping Modul als Basis für die Berechnungen.

INPUT:
- okstra_id (Kommandozeilen-Parameter)
- output/vorrangnetz_details_combined_rvn.fgb (Straßennetz)
- output/matched/matched_tilda_ways.fgb (TILDA-übersetzte Daten)

OUTPUT:
- Detaillierte Konsolen-Ausgabe der Kandidaten-Bewertung
- Ausgewählte Kandidaten pro Richtung (ri=0/ri=1)
"""

import argparse
import sys
import os
import logging
from pathlib import Path

# Füge das processing Verzeichnis zum Python Path hinzu
processing_dir = Path(__file__).parent.parent / "processing"
sys.path.insert(0, str(processing_dir))

# Import der benötigten Module aus start_snapping
from start_snapping import (
    CONFIG_BUFFER_DEFAULT,
    CONFIG_MAX_ANGLE_DIFFERENCE,
    calculate_line_angle,
    angle_difference,
    find_best_candidate_for_direction,
    create_directional_segment_variants_from_matched_tilda_ways,
    lines_from_geom
)
from helpers.globals import DEFAULT_CRS
from helpers.clipping import clip_to_neukoelln

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString


def debug_okstra_edge(okstra_id: str, net_path: str, osm_path: str, 
                     crs: int = DEFAULT_CRS, buf: float = CONFIG_BUFFER_DEFAULT,
                     clip_neukoelln: bool = False, data_dir: str = "./data"):
    """
    Debuggt das Snapping für eine spezifische okstra_id.
    
    Args:
        okstra_id: Die zu debuggende okstra_id
        net_path: Pfad zum Straßennetz
        osm_path: Pfad zu den TILDA-übersetzten Daten
        crs: Koordinatensystem (EPSG)
        buf: Puffergröße für Matching
        clip_neukoelln: Ob auf Neukölln zugeschnitten werden soll
        data_dir: Verzeichnis mit den Eingabedateien
    """
    
    # Logging konfigurieren für detaillierte Debug-Ausgabe
    logging.basicConfig(
        level=logging.DEBUG, 
        format='%(levelname)s: %(message)s'
    )
    
    # Hilfsfunktion zum Laden von Dateien
    def read(path):
        f, *layer = path.split(":")
        return gpd.read_file(f, layer=layer[0] if layer else None)

    print(f"🔍 DEBUG: Analysiere okstra_id = {okstra_id}")
    print(f"   Netzwerk: {net_path}")
    print(f"   TILDA-Daten: {osm_path}")
    print(f"   Puffergröße: {buf}m")
    print(f"   Max. Winkelunterschied: {CONFIG_MAX_ANGLE_DIFFERENCE}°")
    print("-" * 70)

    # Daten laden
    try:
        net = read(net_path).to_crs(crs)
        osm = read(osm_path).to_crs(crs)
    except Exception as e:
        print(f"❌ FEHLER beim Laden der Daten: {e}")
        return

    print(f"✅ Netzwerk: {len(net)} Features geladen")
    print(f"✅ TILDA-übersetzte Daten: {len(osm)} Features geladen")

    # Optional: Auf Neukölln zuschneiden
    if clip_neukoelln:
        print("🔄 Schneide Daten auf Neukölln zu...")
        try:
            net = clip_to_neukoelln(net, data_dir, crs)
            osm = clip_to_neukoelln(osm, data_dir, crs)
            print(f"✅ Nach Clipping - Netzwerk: {len(net)}, TILDA: {len(osm)} Features")
        except Exception as e:
            print(f"❌ FEHLER beim Clipping: {e}")
            return

    # Filtere nach der gewünschten okstra_id
    target_edges = net[net['okstra_id'] == okstra_id].copy()
    
    if target_edges.empty:
        print(f"❌ FEHLER: Keine Kante mit okstra_id '{okstra_id}' gefunden!")
        available_ids = net['okstra_id'].unique()
        print(f"   Verfügbare okstra_ids (erste 10): {list(available_ids[:10])}")
        return

    print(f"🎯 Gefunden: {len(target_edges)} Kante(n) mit okstra_id '{okstra_id}'")

    # Erzeuge einen räumlichen Index für die TILDA-Daten
    osm_sidx = osm.sindex

    # Analysiere jede Kante mit der gewünschten okstra_id
    for edge_idx, edge in target_edges.iterrows():
        print(f"\n📍 KANTE {edge_idx} (okstra_id: {okstra_id})")
        print(f"   element_nr: {edge.get('element_nr', 'N/A')}")
        print(f"   Geometrie: {edge.geometry.geom_type}, Länge: {edge.geometry.length:.1f}m")
        
        # Segmentiere die Kante in 1m-Abschnitte (wie im Original-Skript)
        segments = []
        for geom in lines_from_geom(edge.geometry):
            n_seg = max(1, int(round(geom.length)))  # 1m Segmente
            breakpoints = [i / n_seg for i in range(n_seg + 1)]
            
            for i in range(n_seg):
                start_point = geom.interpolate(breakpoints[i], normalized=True)
                end_point = geom.interpolate(breakpoints[i+1], normalized=True)
                
                # Prüfe ob Start- und Endpunkt unterschiedlich sind
                if start_point.distance(end_point) < 0.01:  # Sehr kurzes Segment
                    continue
                    
                seg = LineString([start_point, end_point])
                seg_data = edge.copy()
                seg_data['geometry'] = seg
                seg_data['segment_id'] = i
                segments.append(seg_data)

        print(f"   📊 {len(segments)} Segmente erzeugt")

        if not segments:
            print("   ⚠️  Keine verwertbaren Segmente erzeugt!")
            continue

        # Analysiere repräsentatives Segment (das mittlere)
        middle_idx = len(segments) // 2
        seg = segments[middle_idx]
        g = seg.geometry
        
        print(f"\n🔍 ANALYSIERE SEGMENT {seg.get('segment_id', middle_idx)} (repräsentativ):")
        print(f"   Segment-Länge: {g.length:.2f}m")
        
        # Berechne Segment-Winkel
        seg_angle = calculate_line_angle(g)
        print(f"   Segment-Winkel: {seg_angle:.1f}°")

        # Suche Kandidaten im Buffer
        cand_idx = list(osm_sidx.intersection(g.buffer(buf, cap_style='flat').bounds))
        if not cand_idx:
            print("   ❌ Keine TILDA-Kandidaten im räumlichen Index gefunden!")
            continue

        print(f"   🎯 {len(cand_idx)} potentielle Kandidaten im räumlichen Index")

        # Lade und filtere Kandidaten
        cand = osm.iloc[cand_idx].copy()
        cand["d"] = cand.geometry.distance(g)
        cand = cand[cand["d"] <= buf]
        
        if cand.empty:
            print("   ❌ Keine Kandidaten im Entfernungspuffer!")
            continue

        print(f"   ✅ {len(cand)} Kandidaten im {buf}m Puffer")

        # Berechne Winkel und Winkeldifferenz für alle Kandidaten
        cand["angle"] = cand.geometry.apply(calculate_line_angle)
        cand["angle_diff"] = cand["angle"].apply(lambda a: angle_difference(a, seg_angle))

        # Zeige alle Kandidaten
        print(f"\n   📋 ALLE KANDIDATEN:")
        for idx, candidate in cand.iterrows():
            tilda_id = candidate.get('tilda_id', f'idx_{idx}')
            distance = candidate.get('d', -1)
            angle = candidate.get('angle', -1)
            angle_diff = candidate.get('angle_diff', -1)
            verkehrsri = candidate.get('verkehrsri', 'unknown')
            fuehr = candidate.get('fuehr', 'unknown')
            
            print(f"      {tilda_id}: dist={distance:.1f}m, angle={angle:.1f}°, "
                  f"diff={angle_diff:.1f}°, verkehrsri={verkehrsri}, fuehr={fuehr}")

        # Verwende alle Kandidaten für die Richtungsanalyse
        # Die Richtungskompatibilität wird in find_best_candidate_for_direction intelligent bewertet
        print(f"\n   🎯 ALLE KANDIDATEN WERDEN FÜR RICHTUNGSANALYSE VERWENDET:")
        print(f"      ✅ {len(cand)} Kandidaten verfügbar für intelligente Bewertung")
        
        target_cand = cand

        # Analysiere für beide Richtungen
        print(f"\n   🔄 RICHTUNGS-ANALYSE:")
        
        seg_dict = seg.to_dict()
        seg_dict['geometry'] = g  # Stelle sicher, dass Geometrie korrekt ist
        
        results = {}
        for ri_value in [0, 1]:  # 0 = Hinrichtung, 1 = Rückrichtung
            ri_name = "Hinrichtung" if ri_value == 0 else "Rückrichtung"
            print(f"\n      📌 ri={ri_value} ({ri_name}):")
            
            # Finde besten Kandidaten für diese Richtung
            best_candidate = find_best_candidate_for_direction(target_cand, seg_dict, ri_value)
            
            if best_candidate:
                tilda_id = best_candidate.get('tilda_id', 'unknown')
                distance = best_candidate.get('d', -1)
                angle_diff = best_candidate.get('angle_diff', -1)
                dir_compat = best_candidate.get('direction_compatibility', -1)
                verkehrsri = best_candidate.get('verkehrsri', 'unknown')
                priority = best_candidate.get('priority', -1)
                
                print(f"         ✅ BESTER: {tilda_id}")
                print(f"            Entfernung: {distance:.1f}m")
                print(f"            Winkel-Diff: {angle_diff:.1f}°")
                print(f"            Dir-Compat: {dir_compat}")
                print(f"            Priorität: {priority}")
                print(f"            Verkehrsri: {verkehrsri}")
                
                results[ri_value] = best_candidate
            else:
                print(f"         ❌ KEIN KANDIDAT gefunden!")
                results[ri_value] = None

        # Erstelle finale Segment-Varianten
        print(f"\n   🏗️  SEGMENT-VARIANTEN:")
        variants = create_directional_segment_variants_from_matched_tilda_ways(
            seg_dict, target_cand, cand
        )
        
        for variant in variants:
            ri = variant.get('ri', 'unknown')
            tilda_id = variant.get('tilda_id', 'None')
            ri_name = "Hinrichtung" if ri == 0 else "Rückrichtung" if ri == 1 else f"ri={ri}"
            fuehr = variant.get('fuehr', 'None')
            
            print(f"      🎯 ri={ri} ({ri_name}): {tilda_id}")
            print(f"         Führung: {fuehr}")

        print(f"\n" + "="*70)

    print(f"\n✅ DEBUG-Analyse für okstra_id '{okstra_id}' abgeschlossen!")


def main():
    """Hauptfunktion - parst Kommandozeilenargumente und startet die Debug-Analyse."""
    parser = argparse.ArgumentParser(
        description="Debug-Tool für das Snapping einer spezifischen okstra_id",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Beispiele:
  python calculate_snapping_debug_okstra_edge.py --okstra-id "12345"
  python calculate_snapping_debug_okstra_edge.py --okstra-id "67890" --buffer 50 --clip-neukoelln
        """
    )
    
    parser.add_argument(
        "--okstra-id", 
        required=True,
        help="Die okstra_id der zu debuggenden Kante"
    )
    parser.add_argument(
        "--net", 
        default="./output/vorrangnetz_details_combined_rvn.fgb", 
        help="Netz-Layer (Pfad[:Layer]) - Default: ./output/vorrangnetz_details_combined_rvn.fgb"
    )
    parser.add_argument(
        "--osm", 
        default="./output/matched/matched_tilda_ways.fgb", 
        help="TILDA-übersetzte Daten (Pfad[:Layer]) - Default: ./output/matched/matched_tilda_ways.fgb"
    )
    parser.add_argument(
        "--crs", 
        type=int, 
        default=DEFAULT_CRS,
        help=f"Ziel-EPSG (default {DEFAULT_CRS})"
    )
    parser.add_argument(
        "--buffer", 
        type=float, 
        default=CONFIG_BUFFER_DEFAULT,
        help=f"Matching-Puffer in m (default {CONFIG_BUFFER_DEFAULT})"
    )
    parser.add_argument(
        "--clip-neukoelln", 
        action="store_true",
        help="Schneide Daten auf Neukölln zu (optional)"
    )
    parser.add_argument(
        "--data-dir", 
        default="../data", 
        help="Pfad zum Datenverzeichnis (default: ../data)"
    )
    
    args = parser.parse_args()

    # Prüfe ob Eingabedateien existieren
    net_path = Path(args.net).expanduser().resolve()
    osm_path = Path(args.osm).expanduser().resolve()
    
    if not net_path.exists():
        print(f"❌ FEHLER: Netzwerk-Datei nicht gefunden: {net_path}")
        sys.exit(1)
        
    if not osm_path.exists():
        print(f"❌ FEHLER: TILDA-Datei nicht gefunden: {osm_path}")
        sys.exit(1)

    # Starte Debug-Analyse
    debug_okstra_edge(
        okstra_id=args.okstra_id,
        net_path=str(net_path),
        osm_path=str(osm_path),
        crs=args.crs,
        buf=args.buffer,
        clip_neukoelln=args.clip_neukoelln,
        data_dir=args.data_dir
    )


if __name__ == "__main__":
    main()
