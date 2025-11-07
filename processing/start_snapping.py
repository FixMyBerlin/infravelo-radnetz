#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
start_snapping.py
--------------------------------------------------------------------
Überträgt TILDA-übersetzte Attribute auf ein topologisches Richtungs-Straßennetz
– MultiLineStrings werden korrekt behandelt
– feste Feldnamen:
      element_nr         = Edge-ID
      beginnt_bei_vp     = From-Node
      endet_bei_vp       = To-Node
– Verwendet übersetzte TILDA-Attribute: fuehr, ofm, protek, pflicht, breite, farbe
– Bei fehlenden TILDA-Daten wird fuehr="Keine Radinfrastruktur vorhanden" gesetzt
– Berechnet die Länge jedes Segments in Metern (gerundet, ohne Nachkommastellen)
– Weist Bezirksnummern zu (basierend auf größtem räumlichen Anteil)
– Enthält Datenaufbereitung: Spaltenordnung für finale Ausgabe

INPUT:
- output/rvn/vorrangnetz_details_combined_rvn.fgb (Straßennetz)
- output/matched/matched_tilda_ways.fgb (TILDA-übersetzte Daten)
- data/Berlin Bezirke.gpkg (Berliner Bezirksgrenzen für Bezirkszuweisung)
- data/opposite_edge_overwrite_element_nr.txt (Optional: Liste von element_nr für manuelles Entfernen der Rückrichtung)

OUTPUT:
- output/snapping_network_enriched.fgb (angereicherte Netzwerkdaten)
(Bei Neukölln-Clipping: snapping_network_enriched_neukoelln.fgb)

BEACHTE: Die attributierten Segmente (rvn-segmented-attributed-osm.fgb) müssen gelöscht werden,
sofern ein neues Ergebnis erzielt werden soll.
"""
import argparse, sys
from pathlib import Path
import os, logging
import time
import tempfile
import pickle
import multiprocessing as mp
import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import linemerge
from helpers.progressbar import print_progressbar
from helpers.globals import DEFAULT_CRS
from helpers.clipping import clip_to_region, clip_to_view
from helpers.district_assignment import assign_district_to_edges
from helpers.snapping_calculations import (
    calculate_line_angle,
    angle_difference, 
    determine_segment_direction,
    find_best_candidate_for_direction,
    SnappingPriorities
)

# -------------------------------------------------------------- Konstanten --
CONFIG_BUFFER_DEFAULT = 30     # Standard-Puffergröße in Metern zum Suchraum
CONFIG_SEGMENT_LENGTH = 2.5    # Segmentlänge in Metern für die Netz-Aufteilung
CONFIG_PROGRESS_UPDATE_INTERVAL = 100  # Fortschritt alle N Segmente aktualisieren
CONFIG_BATCH_SIZE = 750        # Anzahl Segmente pro Batch für bessere Performance
CONFIG_CPU_CORES = mp.cpu_count() - 2  # Anzahl CPU-Kerne für Parallelisierung (alle minus 1)

# Neukölln Grenzendatei
INPUT_NEUKOELLN_BOUNDARY_FILE = "Bezirk Neukölln Grenze.fgb"

# Datei mit element_nr für manuelles Überschreiben der Rückrichtung (ri=1)
OPPOSITE_EDGE_OVERWRITE_FILE = "opposite_edge_overwrite_element_nr.txt"

# Feldnamen für das Netz
RVN_ATTRIBUT_ELEMENT_NR = "element_nr"           # Kanten-ID
RVN_ATTRIBUT_BEGINN_VP = "beginnt_bei_vp"       # Startknoten-ID
RVN_ATTRIBUT_ENDE_VP   = "endet_bei_vp"         # Endknoten-ID

# Attribute an denen die Kanten getrennt werden bzw. verschmolzen werden
# Diese Attribute müssen in den übersetzten TILDA Daten vorhanden sein
FINAL_DATASET_SEGMENT_MERGE_ATTRIBUTES = ["fuehr", "ofm", "protek", "pflicht", "breite", "farbe", "ri", "verkehrsri", "trennstreifen", "nutz_beschr", "Kommentar"]
FINAL_DATASET_SEGMENT_ADDITIONAL_ATTRIBUTES=["data_source", "tilda_id", "tilda_name","tilda_oneway", "tilda_category", "tilda_traffic_sign", "tilda_mapillary", "tilda_mapillary_traffic_sign", "tilda_mapillary_backward", "tilda_mapillary_forward", "prio_traffic_sign", "prio_category", "prio_streetname_equality", "prio_total", "prio_angle", "prio_distance_meter", "prio_distance", "prio_direction_compatibility", "prio_candidates", "angle_diff", "angle_segment", "angle_tilda"]

# Gewünschte Spaltenreihenfolge für Datenaufbereitung (finale Ausgabe)
COLUMN_ORDER = [
    "sfid",                   # 1. Snapping FID
    "element_nr",             # 2. element_nr
    "beginnt_bei_vp",         # 3. beginnt_bei_vp
    "endet_bei_vp",           # 4. endet_bei_vp
    "Länge",                  # 5. Länge (gerundet, ohne Nachkommastellen)
    "ri",                     # 6. ri
    "verkehrsri",             # 7. verkehrsri
    "Bezirksnummer",          # 8. Bezirksnummer
    "strassenname",           # 9. Straßenname
    "fuehr",                  # 10. fuehr
    "pflicht",                # 11. pflicht
    "breite",                 # 12. breite
    "ofm",                    # 13. ofm
    "farbe",                  # 14. farbliche beschichtung
    "protek",                 # 15. protek
    "trennstreifen",          # 16. trennstreifen
    "nutz_beschr",            # 17. nutzungsbeschränkung
    "Kommentar",
    # TILDA-Spalten (geprefixte Spalten)
    "tilda_id",
    "tilda_name",
    "tilda_oneway",
    "tilda_category",
    "tilda_traffic_sign",
    "tilda_mapillary",
    "tilda_mapillary_traffic_sign",
    "tilda_mapillary_backward",
    "tilda_mapillary_forward",
    # Prioritäts-Spalten für die Kandidatenauswahl
    "prio_traffic_sign",           # Priorität basierend auf Verkehrszeichen
    "prio_category",          # Priorität basierend auf Kategorie
    "prio_streetname_equality",            # Priorität basierend auf Straßennamen-Match
    "prio_angle",             # Priorität basierend auf Winkelausrichtung
    "prio_distance_meter",          # Entfernung zum Segmentmittelpunkt (in Metern)
    "prio_distance", # Gewichtete Entfernungs-Priorität (hyperbolisch)
    "prio_direction_compatibility", # Priorität für Richtungskompatibilität (Einrichtungs-/Zweirichtungsverkehr)
    "prio_total",             # Gesamtpriorität
    "angle_diff",             # Winkeldifferenz zwischen Segment und TILDA-Weg (in Grad)
    "angle_segment",          # Winkel des Segments (in Grad)
    "angle_tilda",            # Winkel des TILDA-Wegs (in Grad)
    # Weitere Standardspalten
    "data_source",
    "edge_source",
    "geometry"                # Geometrie immer als letzte Spalte
]

# -------------------------------------------------------- PRIORITÄTS-KONFIGURATION --
# Zentrale Konfiguration aller Prioritäten, Belohnungen und Strafen für die Kandidatenauswahl
# Diese Werte werden sowohl im Snapping als auch in der Analyse verwendet
#
# ANPASSUNG DER WERTE:
# Um die Prioritäten zu ändern, passen Sie die Werte in der helpers/snapping_analysis.py SnappingPriorities-Klasse an.
# Höhere Werte = höhere Priorität bei der Kandidatenauswahl.
# Negative Werte = Strafen, die Kandidaten weniger wahrscheinlich machen.
#
# Die SnappingPriorities-Klasse ist jetzt in helpers/snapping_analysis.py modularisiert
# und wird sowohl hier als auch im analyze_snapping_candidates.py Skript verwendet.


def calculate_angles_vectorized(geometries):
    """
    Berechnet Winkel für alle Geometrien vektorisiert.
    Deutlich schneller als einzelne apply()-Aufrufe.
    """
    angles = np.zeros(len(geometries))
    
    for i, geom in enumerate(geometries):
        if isinstance(geom, MultiLineString):
            # Bei MultiLineString den ersten Punkt der ersten Linie und 
            # den letzten Punkt der letzten Linie verwenden
            first_line = geom.geoms[0]
            last_line = geom.geoms[-1]
            
            first_coords = list(first_line.coords)
            last_coords = list(last_line.coords)
            
            if len(first_coords) >= 1 and len(last_coords) >= 1:
                p1 = first_coords[0]  # Erster Punkt der ersten Linie
                p2 = last_coords[-1]  # Letzter Punkt der letzten Linie
            else:
                angles[i] = 0.0
                continue
        elif hasattr(geom, 'coords'):
            coords = list(geom.coords)
            if len(coords) >= 2:
                p1, p2 = coords[0], coords[-1]
            else:
                angles[i] = 0.0
                continue
        else:
            angles[i] = 0.0
            continue
            
        angle = np.degrees(np.arctan2(p2[1] - p1[1], p2[0] - p1[0]))
        angles[i] = angle if angle >= 0 else angle + 360
    
    return angles


def unpack_candidate_result(result):
    """
    Entpackt das Ergebnis von find_best_candidate_for_direction.
    
    Args:
        result: Rückgabewert von find_best_candidate_for_direction (Tupel oder einzelner Wert)
        
    Returns:
        tuple: (best_candidate, all_candidates_sorted) - beide können None sein
    """
    if isinstance(result, tuple):
        return result
    else:
        # Fallback für alte Version oder None
        return result, None


def extract_candidates_priorities(all_candidates_sorted):
    """
    Extrahiert Kandidaten-IDs und Prioritäten aus sortierten Kandidaten.
    
    Args:
        all_candidates_sorted: GeoDataFrame mit sortierten Kandidaten oder None
        
    Returns:
        list: Liste von Tupeln (tilda_id, total_priority_weighted)
    """
    candidates_priorities = []
    if all_candidates_sorted is not None and len(all_candidates_sorted) > 0:
        for _, cand in all_candidates_sorted.iterrows():
            tilda_id = cand.get('tilda_id', 'unknown')
            total_prio = cand.get('total_priority_weighted', 0)
            candidates_priorities.append((tilda_id, total_prio))
    return candidates_priorities


def get_best_below_threshold(all_candidates_sorted):
    """
    Holt den besten Kandidaten auch wenn unter Schwellenwert, für Debugging.
    
    Args:
        all_candidates_sorted: GeoDataFrame mit sortierten Kandidaten oder None
        
    Returns:
        dict oder None: Bester Kandidat als Dictionary
    """
    if all_candidates_sorted is not None and len(all_candidates_sorted) > 0:
        return all_candidates_sorted.iloc[0].to_dict()
    return None


def format_candidates_priorities(candidates_with_priorities):
    """
    Formatiert alle Kandidaten mit ihren Prioritäten für das prio_candidates Attribut.
    
    Args:
        candidates_with_priorities: Liste von Tupeln (tilda_id, total_priority_weighted)
        
    Returns:
        str: Formatierter String mit allen Kandidaten, z.B. "(way/123: 48.0, way/456: -54.5)"
    """
    if not candidates_with_priorities or len(candidates_with_priorities) == 0:
        return None
    
    # Formatiere jeden Kandidaten als "osm_id: prio"
    formatted = [f"{tid}: {prio:.1f}" for tid, prio in candidates_with_priorities]
    
    # Verbinde alle Kandidaten mit Komma und umschließe mit Klammern
    return f"({', '.join(formatted)})"


def set_priority_values(variant, best_osm, segment_angle, candidates_with_priorities=None):
    """
    Hilfsfunktion: Setzt alle Prioritätswerte in einer Variante basierend auf dem besten OSM-Kandidaten.
    
    Args:
        variant: Das Segment-Dictionary, in das die Prioritäten geschrieben werden
        best_osm: Der beste OSM-Kandidat mit allen berechneten Prioritäten
        segment_angle: Der Winkel des Segments
        candidates_with_priorities: Liste von Tupeln (tilda_id, total_priority_weighted) aller Kandidaten
    """
    # Setze prio_candidates mit allen Kandidaten und ihren Prioritäten
    variant["prio_candidates"] = format_candidates_priorities(candidates_with_priorities)
    
    if best_osm is not None:
        # Übertrage TILDA-Prioritätswerte
        priority_details = best_osm.get('priority_details', {})
        variant["prio_traffic_sign"] = priority_details.get('traffic_priority', 0)
        variant["prio_category"] = priority_details.get('category_priority', 0)
        variant["prio_streetname_equality"] = priority_details.get('street_name_priority', 0)

        # Übertrage geometrische und räumliche Prioritäten
        variant["prio_angle"] = best_osm.get('angle_priority', 0)
        variant["prio_distance_meter"] = best_osm.get('dist_to_mid', None)
        variant["prio_distance"] = best_osm.get('distance_priority', 0)  # Gewichtete Entfernungs-Priorität
        variant["prio_overlap"] = best_osm.get('priority_overlap', 0)  # Überlappungs-Priorität (verhindert Overshoot)
        # Speichere auch den Rohwert (0.0-1.0) aus priority_details falls verfügbar
        variant["overlap_score"] = priority_details.get('overlap_score', None)
        variant["prio_total"] = best_osm.get('total_priority_weighted', 0)  # Gesamtpriorität
        # Richtungskompatibilität explizit speichern
        variant["prio_direction_compatibility"] = best_osm.get('direction_compatibility', 0)

        # Berechne und speichere Winkelinformationen
        tilda_geom = best_osm.get('geometry')
        if tilda_geom is not None:
            tilda_angle = calculate_line_angle(tilda_geom)
            variant["angle_segment"] = segment_angle
            variant["angle_tilda"] = tilda_angle
            variant["angle_diff"] = angle_difference(segment_angle, tilda_angle)
        else:
            variant["angle_segment"] = segment_angle
            variant["angle_tilda"] = None
            variant["angle_diff"] = None
    else:
        # Keine OSM-Kandidaten: Alle Prioritätswerte auf Standardwerte setzen
        variant["prio_traffic_sign"] = 0
        variant["prio_category"] = 0
        variant["prio_streetname_equality"] = 0
        variant["prio_angle"] = 0
        variant["prio_distance_meter"] = None
        variant["prio_distance"] = 0
        variant["prio_total"] = 0
        variant["prio_direction_compatibility"] = 0
        variant["angle_segment"] = segment_angle
        variant["angle_tilda"] = None
        variant["angle_diff"] = None


def create_base_variant_optimized(seg_dict: dict, ri_value: int) -> dict:
    """
    Erstellt eine Basis-Variante ohne redundante Kopieroperationen.
    Optimiert für bessere Performance.
    """
    # Nur die notwendigen Felder kopieren statt seg_dict.copy()
    variant = {
        'geometry': seg_dict['geometry'],
        'ri': ri_value,
        'element_nr': seg_dict.get('element_nr'),
        'beginnt_bei_vp': seg_dict.get('beginnt_bei_vp'),
        'endet_bei_vp': seg_dict.get('endet_bei_vp'),
        'Länge': int(round(seg_dict['geometry'].length)),
        'Bezirksnummer': seg_dict.get('Bezirksnummer'),
        'strassenname': seg_dict.get('strassenname'),
        'data_source': seg_dict.get('data_source'),
        'edge_source': seg_dict.get('edge_source')
    }
    
    return variant


def process_segments_batch_parallel(batch_data):
    """
    Parallelisierte Version der Batch-Verarbeitung für multiprocessing.
    Jeder Worker-Prozess lädt die OSM-Daten aus einer temporären Pickle-Datei.
    
    Args:
        batch_data: Tuple mit (segments_batch, osm_temp_path, buffer, batch_start_idx)
    
    Returns:
        List[dict]: Liste der verarbeiteten Segment-Varianten
    """
    segments_batch, osm_temp_path, buffer, batch_start_idx = batch_data
    
    # Lade OSM-Daten aus temporärer Pickle-Datei
    with open(osm_temp_path, 'rb') as f:
        osm_gdf = pickle.load(f)
    osm_sidx = osm_gdf.sindex
    
    batch_results = []
    
    for local_idx, seg_dict in enumerate(segments_batch):
        global_idx = batch_start_idx + local_idx + 1
        g = seg_dict['geometry']
        
        # Buffer einmal berechnen und cachen
        buffer_geom = g.buffer(buffer, cap_style='flat')
        cand_idx = list(osm_sidx.intersection(buffer_geom.bounds))
        
        if not cand_idx:
            # Keine TILDA-Kandidaten gefunden
            variants = create_directional_segment_variants_optimized(seg_dict, None)
            batch_results.extend(variants)
            continue
            
        # Kopiere die TILDA-Kandidaten, die im räumlichen Buffer gefunden wurden
        cand = osm_gdf.iloc[cand_idx].copy()

        # Vektorisierte Entfernungsberechnung
        cand["d"] = cand.geometry.distance(g)
        cand = cand[cand["d"] <= buffer]
        
        if cand.empty:
            # Keine TILDA-Kandidaten im Buffer
            variants = create_directional_segment_variants_optimized(seg_dict, None)
            batch_results.extend(variants)
            continue

        # Berechne Winkel vektorisiert statt mit apply()
        seg_angle = calculate_line_angle(g)
        cand_angles = calculate_angles_vectorized(cand.geometry)
        cand["angle"] = cand_angles
        
        # Berechne Winkeldifferenzen vektorisiert
        angle_diffs = np.array([angle_difference(a, seg_angle) for a in cand_angles])
        cand["angle_diff"] = angle_diffs

        # Erzeuge Segment-Varianten basierend auf TILDA-Daten (optimiert)
        # Wenn trotz vorhandener Kandidaten KEIN Kandidat die Mindest-Schwelle erreicht,
        # versuche einmalig, den Buffer zu verdoppeln und suche erneut nach Ausreißern.
        # Das ist modular inlined hier (kleiner Helfer wäre Overhead bei Parallel-Load).
        try:
            # Prüfe kurz ob mindestens ein Kandidat die Mindest-Schwelle erfüllt
            best0, _ = find_best_candidate_for_direction(cand, seg_dict, 0, seg_angle)
            best1, _ = find_best_candidate_for_direction(cand, seg_dict, 1, seg_angle)
            need_retry = (best0 is None and best1 is None)
        except Exception:
            need_retry = False

        if need_retry:
            # Doublen des Buffers einmalig
            buffer2 = buffer * 2
            logging.warning(f"Kein Kandidat über Schwelle für segment element_nr={seg_dict.get('element_nr','unknown')} gefunden. Versuche nochmal mit verdoppeltem Buffer={buffer2}m")
            # candidates_log falls vorhanden informieren
            if batch_data and len(batch_data) >= 4:
                # batch_data may not include candidates_log in parallel mode; ignore
                pass

            buffer_geom2 = g.buffer(buffer2, cap_style='flat')
            cand_idx2 = list(osm_sidx.intersection(buffer_geom2.bounds))
            if cand_idx2:
                cand2 = osm_gdf.iloc[cand_idx2].copy()
                cand2["d"] = cand2.geometry.distance(g)
                cand2 = cand2[cand2["d"] <= buffer2]
                if not cand2.empty:
                    cand_angles2 = calculate_angles_vectorized(cand2.geometry)
                    cand2["angle"] = cand_angles2
                    angle_diffs2 = np.array([angle_difference(a, seg_angle) for a in cand_angles2])
                    cand2["angle_diff"] = angle_diffs2

                    # Prüfe ob jetzt ein Kandidat die Mindest-Schwelle überschreitet
                    best0b, _ = find_best_candidate_for_direction(cand2, seg_dict, 0, seg_angle)
                    best1b, _ = find_best_candidate_for_direction(cand2, seg_dict, 1, seg_angle)
                    accepted = False
                    for best in (best0b, best1b):
                        if best is not None and best.get('total_priority_weighted', -999) >= SnappingPriorities.MINIMUM_TOTAL_PRIORITY:
                            accepted = True
                            break
                    if accepted:
                        # Verwende die erweiterte Kandidatenmenge
                        cand = cand2
                        # Optionally write to a small progress log in parallel mode
                        logging.info(f"Gefundenes Ausreißer-Kandidat mit erweitertem Buffer für element_nr={seg_dict.get('element_nr','unknown')}")

        variants = create_directional_segment_variants_optimized(seg_dict, cand, cand)
        batch_results.extend(variants)
    
    return batch_results


def process_segments_batch(segments_batch, osm_gdf, osm_sidx, buffer, candidates_log=None, batch_start_idx=0):
    """
    Verarbeitet eine Batch von Segmenten gleichzeitig.
    Reduziert Overhead durch Batch-Operationen.
    """
    batch_results = []
    
    for local_idx, seg_dict in enumerate(segments_batch):
        element_nr = seg_dict.get('element_nr', 'unknown')  # Verwende sfid statt global_idx
        g = seg_dict['geometry']
        
        # Buffer einmal berechnen und cachen
        buffer_geom = g.buffer(buffer, cap_style='flat')
        cand_idx = list(osm_sidx.intersection(buffer_geom.bounds))
        
        if not cand_idx:
            # Keine TILDA-Kandidaten gefunden
            variants = create_directional_segment_variants_optimized(seg_dict, None)
            batch_results.extend(variants)
            
            if candidates_log:
                candidates_log.write(f"  Segment element_nr={element_nr}: KEINE KANDIDATEN GEFUNDEN\n")
            continue
            
        # Kopiere die TILDA-Kandidaten, die im räumlichen Buffer gefunden wurden
        cand = osm_gdf.iloc[cand_idx].copy()

        # Vektorisierte Entfernungsberechnung
        cand["d"] = cand.geometry.distance(g)
        cand = cand[cand["d"] <= buffer]
        
        if cand.empty:
            # Keine TILDA-Kandidaten im Buffer
            variants = create_directional_segment_variants_optimized(seg_dict, None)
            batch_results.extend(variants)
            
            if candidates_log:
                candidates_log.write(f"  Segment element_nr={element_nr}: KEINE KANDIDATEN IM PUFFER\n")
            continue

        # Berechne Winkel vektorisiert statt mit apply()
        seg_angle = calculate_line_angle(g)
        cand_angles = calculate_angles_vectorized(cand.geometry)
        cand["angle"] = cand_angles
        
        # Berechne Winkeldifferenzen vektorisiert
        angle_diffs = np.array([angle_difference(a, seg_angle) for a in cand_angles])
        cand["angle_diff"] = angle_diffs

        # Kandidaten-Logging (falls aktiviert)
        if candidates_log:
            all_tilda_ids = [c.get('tilda_id', 'unknown') for _, c in cand.iterrows()]
            candidates_log.write(f"  Segment element_nr={element_nr}:\n")
            
            for ri_value in [0, 1]:
                ri_name = "Hinrichtung" if ri_value == 0 else "Rückrichtung"
                result = find_best_candidate_for_direction(cand, seg_dict, ri_value, seg_angle)
                
                # Entpacke das Tupel mit Hilfsfunktion
                best_candidate, all_candidates_sorted = unpack_candidate_result(result)
                
                if best_candidate:
                    best_tilda_id = best_candidate.get('tilda_id', 'unknown')
                    verkehrsri = best_candidate.get('verkehrsri', 'unknown')
                    
                    # Neue Prioritätswerte aus snapping_analysis.py
                    total_priority = best_candidate.get('total_priority_weighted', -1)
                    tilda_prio = best_candidate.get('priority', -1)
                    angle_prio = best_candidate.get('angle_priority', -1)
                    distance_prio = best_candidate.get('distance_priority', -1)
                    direction_compat = best_candidate.get('direction_compatibility', 0)
                    distance_meter = best_candidate.get('dist_to_mid', -1)
                    angle_diff = best_candidate.get('angle_diff', -1)
                    
                    # Extrahiere detaillierte TILDA-Prioritätsinformationen falls verfügbar
                    priority_details = best_candidate.get('priority_details', {})
                    
                    candidates_log.write(f"    ri={ri_value} ({ri_name}): {best_tilda_id}\n")
                    candidates_log.write(f"      → GESAMT-PRIORITÄT: {total_priority:.2f}\n")
                    candidates_log.write(f"        ├─ TILDA-Priorität: {tilda_prio}\n")
                    candidates_log.write(f"        ├─ Winkel-Priorität: {angle_prio:.2f}\n")
                    candidates_log.write(f"        ├─ Distanz-Priorität: {distance_prio:.2f} (bei {distance_meter:.1f}m)\n")
                    candidates_log.write(f"        └─ Richtungskompatibilität: {direction_compat}\n")
                    
                    # Detaillierte TILDA-Prioritäten einzeln aufführen (falls verfügbar)
                    if priority_details:
                        traffic_prio = priority_details.get('traffic_priority', 0)
                        category_prio = priority_details.get('category_priority', 0)
                        street_prio = priority_details.get('street_name_priority', 0)
                        traffic_sign = priority_details.get('traffic_sign', 'none')
                        category = priority_details.get('category', 'None')
                        category_pattern = priority_details.get('category_pattern', '')
                        street_detail = priority_details.get('street_name_detail', '')
                        
                        candidates_log.write(f"      → TILDA-PRIORITÄTEN:\n")
                        candidates_log.write(f"        • Traffic_Sign({traffic_sign}): {traffic_prio}\n")
                        if category_pattern:
                            candidates_log.write(f"        • Category({category}~{category_pattern}): {category_prio}\n")
                        else:
                            candidates_log.write(f"        • Category({category}): {category_prio}\n")
                        candidates_log.write(f"        • StreetName({street_detail}): {street_prio}\n")
                        candidates_log.write(f"        • GESAMT: {tilda_prio}\n")
                    
                    candidates_log.write(f"      → DETAILS: angle_diff={angle_diff:.1f}°, verkehrsri={verkehrsri}\n")
                    
                    if len(all_tilda_ids) > 1:
                        candidates_log.write(f"      → VERFÜGBARE: {all_tilda_ids}\n")
                else:
                    candidates_log.write(f"    ri={ri_value} ({ri_name}): KEIN BESTER KANDIDAT\n")
                    if all_tilda_ids:
                        candidates_log.write(f"      → VERFÜGBARE: {all_tilda_ids}\n")

        # Erzeuge Segment-Varianten basierend auf TILDA-Daten (optimiert)
        variants = create_directional_segment_variants_optimized(seg_dict, cand, cand)
        batch_results.extend(variants)
        
        # Logge ausgewählte Kandidaten
        if candidates_log:
            candidates_log.write(f"    AUSGEWÄHLT für Segment element_nr={element_nr}:\n")
            for variant in variants:
                ri = variant.get('ri', 'unknown')
                tilda_id = variant.get('tilda_id', 'None')
                ri_name = "Hinrichtung" if ri == 0 else "Rückrichtung" if ri == 1 else f"ri={ri}"
                candidates_log.write(f"      ri={ri} ({ri_name}): {tilda_id}\n")
    
    return batch_results


# --------------------------------------------------------- Hilfsfunktionen --
def calculate_segment_length(geometry):
    """
    Berechnet die Länge eines Segments in Metern.
    """
    return geometry.length


def lines_from_geom(g):
    """
    Gibt alle Linien einer Geometrie als Liste von LineStrings zurück.
    Falls MultiLineString, werden alle Teile einzeln zurückgegeben.
    Falls LineString, wird eine Liste mit diesem einen Element zurückgegeben.
    """
    if isinstance(g, LineString):
        return [g]
    if isinstance(g, MultiLineString):
        return list(g.geoms)
    raise TypeError(f"Geometry {g.geom_type} nicht unterstützt")


# TODO Why is this not used anymore?
def is_left(line: LineString, p: Point) -> bool:
    """Prüft, ob ein Punkt links der Linie liegt (für Richtungsprüfung)."""
    a_x, a_y = line.coords[0]
    b_x, b_y = line.coords[-1]
    return ((b_x - a_x) * (p.y - a_y) - (b_y - a_y) * (p.x - a_x)) > 0


def split_network_into_segments(net_gdf, crs, segment_length=CONFIG_SEGMENT_LENGTH):
    """
    Teilt alle Linien im Netz in Segmente auf.
    Gibt ein neues GeoDataFrame mit Segmenten zurück.
    """
    start_time = time.time()
    segmente = []
    total = len(net_gdf)
    for idx, (_, row) in enumerate(net_gdf.iterrows(), 1):
        for geom in lines_from_geom(row.geometry):
            n_seg = max(1, int(np.ceil(geom.length / segment_length)))
            breakpoints = np.linspace(0, geom.length, n_seg + 1)
            for i in range(n_seg):
                seg = LineString([
                    geom.interpolate(breakpoints[i]),
                    geom.interpolate(breakpoints[i+1])
                ])
                seg_row = row.copy()
                seg_row["geometry"] = seg
                segmente.append(seg_row)
        print_progressbar(idx, total, prefix="Segmentiere: ", start_time=start_time)
    return gpd.GeoDataFrame(segmente, crs=crs)


def normalize_merge_attributes_batch(df, fields):
    """
    Normalisiert alle Merge-Attribute in einem Durchgang (vektorisiert).
    Behandelt None/NaN-Werte und Floating-Point-Präzision korrekt.
    Deutlich schneller als einzelne apply()-Operationen.
    """
    normalized = {}
    
    for field in fields:
        if field in df.columns:
            series = df[field].copy()
            result = pd.Series(index=series.index, dtype=object)
            
            # None/NaN behandeln
            null_mask = series.isna() | series.isnull()
            result.loc[null_mask] = "NULL"
            
            # Bearbeite nur nicht-null Werte
            non_null_series = series[~null_mask]
            
            if len(non_null_series) > 0:
                # Float-Werte identifizieren und behandeln
                float_mask = non_null_series.apply(lambda x: isinstance(x, (int, float)) and not isinstance(x, bool))
                
                if float_mask.any():
                    float_indices = non_null_series[float_mask].index
                    float_values = non_null_series[float_mask].apply(lambda x: str(round(float(x), 1)))
                    result.loc[float_indices] = float_values
                
                # Boolean zu String
                bool_mask = non_null_series.apply(lambda x: isinstance(x, bool))
                if bool_mask.any():
                    bool_indices = non_null_series[bool_mask].index
                    bool_values = non_null_series[bool_mask].astype(str)
                    result.loc[bool_indices] = bool_values
                
                # String normalisieren (alles was weder float noch bool ist)
                string_mask = ~float_mask & ~bool_mask
                if string_mask.any():
                    string_indices = non_null_series[string_mask].index
                    string_values = non_null_series[string_mask].astype(str).str.strip()
                    result.loc[string_indices] = string_values
            
            normalized[f"{field}_normalized"] = result
        else:
            logging.warning(f"Merge-Attribut '{field}' nicht in den Daten gefunden!")
            normalized[f"{field}_normalized"] = pd.Series(["NULL"] * len(df), index=df.index)
    
    return pd.DataFrame(normalized, index=df.index)


def load_opposite_edge_overwrite_list(data_dir):
    """
    Lädt die Liste der element_nr, für die die Rückrichtung (ri=1) entfernt werden soll.
    
    Args:
        data_dir: Verzeichnis mit der Datei opposite_edge_overwrite_element_nr.txt
    
    Returns:
        set: Menge der element_nr (als Strings), für die ri=1 entfernt werden soll
    """
    file_path = Path(data_dir) / OPPOSITE_EDGE_OVERWRITE_FILE
    
    if not file_path.exists():
        logging.info(f"Keine Opposite-Edge-Overwrite-Liste gefunden: {file_path}")
        return set()
    
    element_nrs = set()
    
    with open(file_path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            # Entferne Whitespace und Kommentare
            line = line.strip()
            
            # Überspringe leere Zeilen und Kommentare
            if not line or line.startswith('#'):
                continue
            
            # Füge element_nr als String hinzu (keine Integer-Konvertierung)
            element_nrs.add(line)
            logging.debug(f"  Zeile {line_num}: '{line}' hinzugefügt")
    
    if element_nrs:
        logging.info(f"✔  Opposite-Edge-Overwrite-Liste geladen: {len(element_nrs)} element_nr(s) aus {file_path}")
    else:
        logging.info(f"Opposite-Edge-Overwrite-Liste ist leer: {file_path}")
    
    return element_nrs


def apply_opposite_edge_overwrite(gdf, opposite_edge_element_nrs):
    """
    Entfernt die Rückrichtung (ri=1) für die angegebenen element_nr.
    Gibt Warnungen aus, wenn ri=0 verkehrsri="Zweirichtungsverkehr" hat.
    
    Args:
        gdf: GeoDataFrame mit den Kanten
        opposite_edge_element_nrs: Set von element_nr, für die ri=1 entfernt werden soll
    
    Returns:
        GeoDataFrame: Gefiltertes GeoDataFrame ohne die entfernten ri=1 Kanten
    """
    if not opposite_edge_element_nrs:
        logging.info("Keine Opposite-Edge-Overwrites zu verarbeiten")
        return gdf
    
    logging.info(f"Verarbeite Opposite-Edge-Overwrites für {len(opposite_edge_element_nrs)} element_nr(s)...")
    
    # Zähler für Statistiken
    removed_count = 0
    warning_count = 0
    not_found_count = 0
    
    # Prüfe jede element_nr
    for element_nr in opposite_edge_element_nrs:
        # Finde alle Kanten mit dieser element_nr
        matching_edges = gdf[gdf['element_nr'] == element_nr]
        
        if len(matching_edges) == 0:
            logging.warning(f"  element_nr={element_nr}: NICHT GEFUNDEN in Daten")
            not_found_count += 1
            continue
        
        # Prüfe ri=0 Kante auf Zweirichtungsverkehr
        ri0_edges = matching_edges[matching_edges['ri'] == 0]
        if len(ri0_edges) > 0:
            for _, edge in ri0_edges.iterrows():
                verkehrsri = edge.get('verkehrsri', None)
                if verkehrsri == 'Zweirichtungsverkehr':
                    logging.warning(
                        f"  ⚠️  element_nr={element_nr} (ri=0): Verkehrsrichtung ist 'Zweirichtungsverkehr' "
                        f"- BITTE MANUELL PRÜFEN ob Rückrichtung wirklich entfernt werden soll!"
                    )
                    warning_count += 1
        
        # Entferne ri=1 Kanten
        ri1_edges = matching_edges[matching_edges['ri'] == 1]
        if len(ri1_edges) > 0:
            logging.info(f"  element_nr={element_nr}: Entferne {len(ri1_edges)} ri=1 Kante(n)")
            removed_count += len(ri1_edges)
    
    # Filtere das GeoDataFrame
    original_count = len(gdf)
    mask = ~((gdf['element_nr'].isin(opposite_edge_element_nrs)) & (gdf['ri'] == 1))
    gdf_filtered = gdf[mask].copy()
    
    logging.info(
        f"✔  Opposite-Edge-Overwrite abgeschlossen: "
        f"{removed_count} ri=1 Kante(n) entfernt, "
        f"{warning_count} Warnung(en), "
        f"{not_found_count} nicht gefunden"
    )
    logging.info(f"   Kanten vorher: {original_count}, nachher: {len(gdf_filtered)}")
    
    return gdf_filtered


def normalize_merge_attribute(value):
    """
    Normalisiert einzelne Attributwerte für das Merging.
    Behandelt None/NaN-Werte und Floating-Point-Präzision.
    """
    if pd.isna(value) or value is None:
        return "NULL"  # Einheitlicher Wert für fehlende Daten
    if isinstance(value, float):
        # Runde Float-Werte auf eine Dezimalstelle für konsistentes Grouping
        return round(value, 1)
    if isinstance(value, bool):
        return str(value)  # Boolean zu String für konsistentes Grouping
    return str(value).strip()  # String normalisieren


def merge_segments(gdf, id_field, osm_fields):
    """
    Verschmilzt benachbarte Segmente mit gleicher element_nr und identischen OSM-Attributen.
    Behandelt None/NaN-Werte und Floating-Point-Präzision korrekt.
    Zeigt einen Fortschrittsbalken an.
    """
    
    # Erstelle eine Kopie für die Bearbeitung
    gdf_work = gdf.copy()
    
    # Normalisiere alle Merge-Attribute in einem Durchgang (vektorisiert - deutlich schneller)
    normalized_df = normalize_merge_attributes_batch(gdf_work, osm_fields)
    gdf_work = pd.concat([gdf_work, normalized_df], axis=1)
    
    # Verwende die normalisierten Felder für das Grouping
    normalized_fields = [f"{field}_normalized" for field in osm_fields]
    groupby_fields = [id_field] + normalized_fields
    
    # Debug-Output: Zeige die Anzahl einzigartiger Kombinationen
    unique_combinations = gdf_work[groupby_fields].drop_duplicates()
    logging.info(f"Anzahl einzigartiger Attributkombinationen: {len(unique_combinations)}")
    
    gruppen = []
    # Gruppiere die Segmente nach element_nr und den normalisierten OSM-Attributen (ohne Sortierung für bessere Performance)
    grouped = list(gdf_work.groupby(groupby_fields, sort=False))
    total = len(grouped)
    
    logging.info(f"Anzahl Gruppen zum Verschmelzen: {total}")
    
    # Starte Zeitmessung für ETA
    merge_start_time = time.time()
    
    for idx, (group_key, gruppe) in enumerate(grouped, 1):
        # Extrahiere die Geometrien der aktuellen Gruppe
        geoms = list(gruppe.geometry)
        if not geoms:
            continue
        
        # Debug: Zeige Gruppengröße
        if len(geoms) > 1:
            logging.debug(f"Verschmelze {len(geoms)} Segmente in Gruppe {group_key}")
        
        # Verschmelze die Geometrien zu einer Linie (MultiLineStrings werden zusammengeführt)
        merged = linemerge(geoms)
        
        # Übernehme die Attribute der ersten Zeile der Gruppe für das verschmolzene Segment
        # Aber verwende die Original-Werte, nicht die normalisierten
        merged_row = gruppe.iloc[0].copy()
        merged_row["geometry"] = merged
        
        # Berechne die Länge basierend auf der Anzahl der Segmente (jedes Segment ist CONFIG_SEGMENT_LENGTH Meter lang)
        # Dies ist effizienter als geometry.length zu berechnen, da die Segmente immer gleich lang sind
        merged_row["Länge"] = int(round(len(geoms) * CONFIG_SEGMENT_LENGTH))
        
        # Entferne die temporären normalisierten Felder
        for field in normalized_fields:
            if field in merged_row.index:
                merged_row = merged_row.drop(field)
        
        gruppen.append(merged_row)
        
        # Zeige Fortschritt für den Nutzer
        print_progressbar(idx, total, prefix="Verschmelze: ", start_time=merge_start_time)
    
    if not gruppen:
        # Fehlerfall: Es wurden keine Gruppen gefunden
        raise ValueError("No segments to merge. Check input data and grouping fields.")
    
    # Erzeuge ein neues GeoDataFrame aus den verschmolzenen Segmenten
    result_gdf = gpd.GeoDataFrame(gruppen, geometry="geometry", crs=gdf.crs)
    
    logging.info(f"Verschmelzung abgeschlossen: {len(gdf)} → {len(result_gdf)} Segmente")
    
    # Prüfe und logge die Längenberechnung
    if 'Länge' in result_gdf.columns:
        total_length = result_gdf['Länge'].sum()
        avg_length = result_gdf['Länge'].mean()
        logging.info(f"Längenstatistiken nach Verschmelzung: Gesamtlänge={total_length:.0f}m, Durchschnitt={avg_length:.0f}m")
    
    return result_gdf


def debug_merge_attributes(gdf, id_field, osm_fields, sample_element_nr=None):
    """
    Debug-Funktion: Analysiert die Attributwerte für das Merging.
    Zeigt potenzielle Probleme bei der Gruppierung auf.
    """
    
    # Wähle eine element_nr zum Debuggen (falls nicht angegeben, nimm die erste)
    if sample_element_nr is None:
        sample_element_nr = gdf[id_field].iloc[0]
    
    # Filtere Segmente mit der gewählten element_nr
    sample_segments = gdf[gdf[id_field] == sample_element_nr].copy()
    
    logging.info(f"\n=== DEBUG: Attributanalyse für element_nr = {sample_element_nr} ===")
    logging.info(f"Anzahl Segmente mit dieser element_nr: {len(sample_segments)}")
    
    if len(sample_segments) <= 1:
        logging.info("Nur ein Segment - kein Merging möglich.")
        return
    
    # Analysiere jeden Merge-Attribut
    for field in osm_fields:
        if field not in sample_segments.columns:
            logging.warning(f"Feld '{field}' nicht in den Daten!")
            continue
            
        unique_values = sample_segments[field].value_counts(dropna=False)
        logging.info(f"\nAttribut '{field}':")
        logging.info(f"  Einzigartige Werte: {len(unique_values)}")
        
        for value, count in unique_values.items():
            logging.info(f"    {repr(value)}: {count} Segmente")
        
        # Zeige erste paar Werte im Detail
        first_few = sample_segments[field].head(5)
        logging.info(f"  Erste 5 Werte: {list(first_few)}")
        logging.info(f"  Datentypen: {[type(x) for x in first_few]}")
    
    # Zeige die Kombinationen der Merge-Attribute
    if len(osm_fields) > 1:
        combinations = sample_segments[osm_fields].drop_duplicates()
        logging.info(f"\nEinzigartige Attributkombinationen: {len(combinations)}")
        for idx, row in combinations.iterrows():
            logging.info(f"  Kombination {idx}: {dict(row)}")


def create_directional_segment_variants_optimized(seg_dict: dict, target_candidates, original_candidates=None) -> list[dict]:
    """
    Memory-optimierte Version der Varianten-Erstellung.
    Reduziert Memory-Allokationen und redundante Operationen für bessere Performance.
    Verwendet create_base_variant_optimized() für effizientere Variant-Erstellung.
    """
    variants = []
    
    # Berechne Segmentwinkel nur einmal für alle Verwendungen
    segment_angle = calculate_line_angle(seg_dict["geometry"])
    
    # Prüfe auf Einrichtungsverkehr und Dual Carriageway Kandidaten
    einrichtung_candidates = []
    dual_carriageway_candidates = []
    
    if target_candidates is not None and len(target_candidates) > 0:
        einrichtung_candidates = target_candidates[
            target_candidates.get('verkehrsri', '') == 'Einrichtungsverkehr'
        ]
        dual_carriageway_candidates = target_candidates[
            target_candidates.get('tilda_oneway', '') == 'yes_dual_carriageway'
        ]
    
    # Sonderfall: Keine TILDA-Kandidaten gefunden
    if target_candidates is None or len(target_candidates) == 0:
        for ri_value in [0, 1]:
            variant = create_base_variant_optimized(seg_dict, ri_value)
            variant["fuehr"] = 'Keine Radinfrastruktur vorhanden'
            # Setze alle anderen Merge-Attribute auf None
            for attr in FINAL_DATASET_SEGMENT_MERGE_ATTRIBUTES:
                if attr not in ['ri', 'fuehr'] and attr not in variant:
                    variant[attr] = None
            for attr in FINAL_DATASET_SEGMENT_ADDITIONAL_ATTRIBUTES:
                variant[attr] = None
            # Setze Prioritätswerte auf 0 da keine Kandidaten vorhanden
            set_priority_values(variant, None, segment_angle)
            variants.append(variant)
    
    # Sonderfall: Nur Einrichtungsverkehr-Kandidaten mit Mischverkehr
    elif (len(einrichtung_candidates) > 0 and 
        len(einrichtung_candidates) == len(target_candidates) and
        len(dual_carriageway_candidates) == 0 and
        all(cand.get('fuehr') == 'Mischverkehr mit motorisiertem Verkehr' 
            for _, cand in einrichtung_candidates.iterrows())):
        
        result = find_best_candidate_for_direction(einrichtung_candidates, seg_dict, None, segment_angle)
        
        # Entpacke das Tupel und extrahiere Kandidaten-Prioritäten
        best_osm, all_candidates_sorted = unpack_candidate_result(result)
        candidates_priorities = extract_candidates_priorities(all_candidates_sorted)
        
        if best_osm:
            variant = create_base_variant_optimized(seg_dict, 
                determine_segment_direction(seg_dict["geometry"], best_osm["geometry"]))
            
            # Übertrage Attribute effizienter
            for attr in FINAL_DATASET_SEGMENT_MERGE_ATTRIBUTES:
                if attr != 'ri' and attr in best_osm:
                    variant[attr] = best_osm.get(attr)
            for attr in FINAL_DATASET_SEGMENT_ADDITIONAL_ATTRIBUTES:
                variant[attr] = best_osm.get(attr)
            
            # Übertrage Prioritätswerte falls vorhanden (mit Kandidaten-Liste)
            set_priority_values(variant, best_osm, segment_angle, candidates_priorities)
                
            variants.append(variant)
    else:
        # Standardfall: Erstelle zwei Varianten
        candidates_to_use = target_candidates
        
        # Dual Carriageway Behandlung
        if (len(dual_carriageway_candidates) > 0 and 
            len(dual_carriageway_candidates) == len(target_candidates) and
            all(cand.get('verkehrsri') == 'Einrichtungsverkehr' 
                for _, cand in dual_carriageway_candidates.iterrows())):
            candidates_to_use = dual_carriageway_candidates
        
        for ri_value in [0, 1]:
            variant = create_base_variant_optimized(seg_dict, ri_value)
            result = find_best_candidate_for_direction(candidates_to_use, seg_dict, ri_value, segment_angle)
            
            # Entpacke das Tupel und extrahiere Kandidaten-Prioritäten
            best_osm, all_candidates_sorted = unpack_candidate_result(result)
            candidates_priorities = extract_candidates_priorities(all_candidates_sorted)

            if best_osm:
                # Übertrage Attribute ohne redundante Schleifen
                for attr in FINAL_DATASET_SEGMENT_MERGE_ATTRIBUTES:
                    if attr != 'ri' and attr in best_osm:
                        variant[attr] = best_osm.get(attr)
                for attr in FINAL_DATASET_SEGMENT_ADDITIONAL_ATTRIBUTES:
                    variant[attr] = best_osm.get(attr)
                
                # Übertrage Prioritätswerte falls vorhanden (mit Kandidaten-Liste)
                set_priority_values(variant, best_osm, segment_angle, candidates_priorities)
            else:
                # Kein Kandidat über Schwellenwert, aber schreibe trotzdem die Prioritäten des besten Kandidaten
                # für Debugging-Zwecke (falls Kandidaten vorhanden)
                best_below_threshold = get_best_below_threshold(all_candidates_sorted)
                
                # Setze fehlende Attribute auf None
                for attr in FINAL_DATASET_SEGMENT_MERGE_ATTRIBUTES:
                    if attr not in variant:
                        variant[attr] = None
                for attr in FINAL_DATASET_SEGMENT_ADDITIONAL_ATTRIBUTES:
                    variant[attr] = None
                
                # Setze Prioritätswerte - auch wenn kein Kandidat übernommen wird, 
                # schreibe die Prioritäten des besten Kandidaten (für Debugging)
                set_priority_values(variant, best_below_threshold, segment_angle, candidates_priorities)

            variants.append(variant)
    
    return variants


def create_directional_segment_variants_from_matched_tilda_ways(seg_dict: dict, target_candidates, original_candidates=None) -> list[dict]:
    """
    Erstellt für jedes Segment gerichtete Varianten basierend auf den TILDA-Attributen.
    Die Attribute werden richtungsabhängig basierend auf den besten gematchten TILDA-Wegen gesetzt.
    Führt die Bewertung und Priorisierung der Kandidaten für jede Richtung durch.
    
    Keine Kandidaten: Wenn keine TILDA-Kandidaten gefunden werden, werden zwei Kanten
    erzeugt mit fuehr="Keine Radinfrastruktur vorhanden" (für geplante Infrastruktur).
    
    Sonderfall: Bei verkehrsri=Einrichtungsverkehr wird nur eine Kante erzeugt,
    wobei das ri basierend auf der Richtungsausrichtung zwischen Segment und OSM-Weg bestimmt wird.
    
    Standardfall: Es werden zwei Kanten erzeugt, eine für die Hin- (ri=0) und eine für die
    Rückrichtung (ri=1). Für jede Richtung wird der passendste TILDA-Weg gewählt.

    Args:
        seg_dict (dict): Dictionary des ursprünglichen Straßensegments.
        target_candidates: GeoDataFrame mit TILDA-Kandidaten oder None/leere Liste.
        original_candidates: GeoDataFrame mit ursprünglichen TILDA-Kandidaten für DEBUG-Ausgabe.

    Returns:
        list[dict]: Eine Liste mit ein oder zwei Dictionaries, die die gerichteten
                    Segment-Varianten repräsentieren.
    """
    variants = []
    
    # Berechne Segmentwinkel einmal für alle Verwendungen
    segment_angle = calculate_line_angle(seg_dict["geometry"])
    
    # DEBUG: Wenn es mehr als einen ursprünglichen Kandidaten gibt, logge das Objekt
    if original_candidates is not None and len(original_candidates) > 1:
        candidate_ids = original_candidates["tilda_id"].tolist() if "tilda_id" in original_candidates.columns else original_candidates.index.tolist()
        # Prüfe, ob mindestens eine tilda_id "cycleway" enthält
        if any("cycleway" in str(tid) for tid in candidate_ids):
            candidate_links = [f"https://osm.org/{tid}" for tid in candidate_ids]
            logging.debug(f"Seg:{seg_dict.get('element_nr', 'unknown')}: {len(original_candidates)} Kandidaten, tilda_id: {candidate_ids}/Links: {candidate_links}")
    
    # Prüfe, ob wir einen eindeutigen Einrichtungsverkehr-Kandidaten haben
    einrichtung_candidates = []
    if target_candidates is not None and len(target_candidates) > 0:
        einrichtung_candidates = target_candidates[
            target_candidates.get('verkehrsri', '') == 'Einrichtungsverkehr'
        ]
    
    # Prüfe auf Dual Carriageway Kandidaten
    dual_carriageway_candidates = []
    if target_candidates is not None and len(target_candidates) > 0:
        dual_carriageway_candidates = target_candidates[
            target_candidates.get('tilda_oneway', '') == 'yes_dual_carriageway'
        ]
    
    # Sonderfall: Keine TILDA-Kandidaten gefunden
    if target_candidates is None or len(target_candidates) == 0:
        # Erstelle zwei Varianten ohne OSM-Daten, aber mit speziellem fuehr-Attribut
        for ri_value in [0, 1]:  # 0 = Hinrichtung, 1 = Rückrichtung
            variant = seg_dict.copy()
            variant["ri"] = ri_value
            
            # Setze alle Merge-Attribute auf None, außer fuehr
            for attr in FINAL_DATASET_SEGMENT_MERGE_ATTRIBUTES:
                if attr == 'ri':  # ri wird explizit durch die Schleife gesetzt
                    continue
                elif attr == 'fuehr':
                    variant[attr] = 'Keine Radinfrastruktur vorhanden'
                elif attr not in variant:  # Behalte existierende Spalten wie 'geometry' etc.
                    variant[attr] = None
            
            # Zusätzliche OSM-Attribute für Debugging/Referenz auf None setzen
            for attr in FINAL_DATASET_SEGMENT_ADDITIONAL_ATTRIBUTES:
                variant[attr] = None
            
            # Setze Prioritätswerte auf 0 da keine Kandidaten vorhanden  
            set_priority_values(variant, None, segment_angle)
                
            variants.append(variant)
    
    # Sonderfall: Nur Einrichtungsverkehr-Kandidaten mit Mischverkehr (aber NICHT dual carriageway)
    elif (len(einrichtung_candidates) > 0 and 
        len(einrichtung_candidates) == len(target_candidates) and
        len(dual_carriageway_candidates) == 0 and  # KEINE dual carriageway Kandidaten
        all(cand.get('fuehr') == 'Mischverkehr mit motorisiertem Verkehr' 
            for _, cand in einrichtung_candidates.iterrows())):
        
        # BUGFIX: Bestimme erst ri für den besten Kandidaten, um korrekte direction_compatibility zu berechnen
        # Finde den besten Kandidaten ohne ri-Filter (als wäre es Zweirichtungsverkehr)
        result_temp = find_best_candidate_for_direction(einrichtung_candidates, seg_dict, None, segment_angle)
        temp_best, _ = unpack_candidate_result(result_temp)
            
        if temp_best:
            # Berechne ri basierend auf dem besten Kandidaten
            calculated_ri = determine_segment_direction(seg_dict["geometry"], temp_best["geometry"])
            
            # Jetzt rufe find_best_candidate_for_direction mit dem korrekten ri auf
            result = find_best_candidate_for_direction(einrichtung_candidates, seg_dict, calculated_ri, segment_angle)
            
            # Entpacke das Tupel und extrahiere Kandidaten-Prioritäten
            best_osm, all_candidates_sorted = unpack_candidate_result(result)
            candidates_priorities = extract_candidates_priorities(all_candidates_sorted)
            
            if best_osm:
                variant = seg_dict.copy()
                variant["ri"] = calculated_ri
            
            # Übertrage alle relevanten Attribute vom besten OSM-Match
            for attr in FINAL_DATASET_SEGMENT_MERGE_ATTRIBUTES:
                if attr == 'ri':  # ri wurde bereits explizit gesetzt
                    continue
                if attr in best_osm:
                    variant[attr] = best_osm.get(attr)

            # Zusätzliche OSM-Attribute für Debugging/Referenz
            for attr in FINAL_DATASET_SEGMENT_ADDITIONAL_ATTRIBUTES:
                variant[attr] = best_osm.get(attr)
            
            # Übertrage Prioritätswerte falls vorhanden (mit Kandidaten-Liste)
            set_priority_values(variant, best_osm, segment_angle, candidates_priorities)
                
            variants.append(variant)
    else:
        # Bestimme welche Kandidaten verwendet werden sollen
        candidates_to_use = target_candidates
        
        # Sonderfall: Dual Carriageway mit Einrichtungsverkehr
        if (len(dual_carriageway_candidates) > 0 and 
            len(dual_carriageway_candidates) == len(target_candidates) and
            all(cand.get('verkehrsri') == 'Einrichtungsverkehr' 
                for _, cand in dual_carriageway_candidates.iterrows())):
            
            logging.debug(f"Dual carriageway erkannt für element_nr={seg_dict.get('element_nr', 'unknown')}: "
                         f"{len(dual_carriageway_candidates)} Kandidaten")
            candidates_to_use = dual_carriageway_candidates
        
        # Standardfall/Dual Carriageway: Erstelle zwei Varianten, eine für jede Richtung
        # Bei dual carriageway werden beide Richtungen erstellt, auch wenn OSM-Wege Einrichtungsverkehr sind
        # Dies repräsentiert die Tatsache, dass beide Fahrbahnen physisch vorhanden sind
        for ri_value in [0, 1]:  # 0 = Hinrichtung, 1 = Rückrichtung
            variant = seg_dict.copy()
            variant["ri"] = ri_value

            # Finde den besten Kandidaten für diese spezifische Richtung
            result = find_best_candidate_for_direction(candidates_to_use, seg_dict, ri_value, segment_angle)
            
            # Entpacke das Tupel und extrahiere Kandidaten-Prioritäten
            best_osm, all_candidates_sorted = unpack_candidate_result(result)
            candidates_priorities = extract_candidates_priorities(all_candidates_sorted)

            if best_osm:
                # Übertrage alle relevanten Attribute vom besten OSM-Match
                for attr in FINAL_DATASET_SEGMENT_MERGE_ATTRIBUTES:
                    if attr == 'ri':  # ri wird explizit durch die Schleife gesetzt
                        continue
                    if attr in best_osm:
                        variant[attr] = best_osm.get(attr)

                # Zusätzliche OSM-Attribute für Debugging/Referenz
                for attr in FINAL_DATASET_SEGMENT_ADDITIONAL_ATTRIBUTES:
                    variant[attr] = best_osm.get(attr)
                
                # Übertrage Prioritätswerte falls vorhanden (mit Kandidaten-Liste)
                set_priority_values(variant, best_osm, segment_angle, candidates_priorities)
            else:
                # Kein Kandidat über Schwellenwert, aber schreibe trotzdem die Prioritäten des besten Kandidaten
                # für Debugging-Zwecke (falls Kandidaten vorhanden)
                best_below_threshold = get_best_below_threshold(all_candidates_sorted)
                
                # Keine OSM-Daten: Standardwerte setzen
                for attr in FINAL_DATASET_SEGMENT_MERGE_ATTRIBUTES:
                    if attr == 'ri':  # ri wird explizit durch die Schleife gesetzt
                        continue
                    if attr not in variant:  # Behalte existierende Spalten wie 'geometry' etc.
                        variant[attr] = None
                
                # Zusätzliche OSM-Attribute für Debugging/Referenz auf None setzen
                for attr in FINAL_DATASET_SEGMENT_ADDITIONAL_ATTRIBUTES:
                    variant[attr] = None
                
                # Setze Prioritätswerte - auch wenn kein Kandidat übernommen wird, 
                # schreibe die Prioritäten des besten Kandidaten (für Debugging)
                set_priority_values(variant, best_below_threshold, segment_angle, candidates_priorities)

            variants.append(variant)
    
    # Berechne die Länge für alle Varianten einmalig am Ende (gerundet, ohne Nachkommastellen)
    for variant in variants:
        variant["Länge"] = int(round(calculate_segment_length(variant["geometry"])))
    
    return variants


# -------------------------------------------------- Datenaufbereitung --
def reorder_columns_for_output(gdf):
    """
    Ordnet die Spalten gemäß der definierten Reihenfolge für die finale Ausgabe.
    Diese Funktion ist Teil der Datenaufbereitung, nicht der Hauptverarbeitung.
    
    Args:
        gdf: GeoDataFrame mit den angereicherten Kanten
        
    Returns:
        GeoDataFrame mit geordneten Spalten
    """
    # Arbeite mit einer Kopie
    gdf = gdf.copy()
    
    # Bestimme verfügbare Spalten in der gewünschten Reihenfolge (ohne geometry)
    available_columns = []
    for col in COLUMN_ORDER:
        if col in gdf.columns and col != 'geometry':
            available_columns.append(col)
    
    # Füge alle anderen Spalten hinzu, die nicht in COLUMN_ORDER definiert sind (ohne geometry)
    for col in gdf.columns:
        if col not in available_columns and col != 'geometry':
            available_columns.append(col)
    
    # Erstelle neues GeoDataFrame mit geordneten Spalten
    # Behalte die originale geometry-Spalte bei
    ordered_data = {}
    for col in available_columns:
        ordered_data[col] = gdf[col]
    
    # Erstelle GeoDataFrame mit originaler geometry
    result_gdf = gpd.GeoDataFrame(ordered_data, geometry=gdf.geometry, crs=gdf.crs)
    
    logging.info(f"Spalten für Ausgabe geordnet: {len(available_columns) + 1} Spalten (inkl. geometry)")
    logging.debug(f"Spaltenreihenfolge: {available_columns + ['geometry']}")
    
    return result_gdf


# ------------------------------------------------------------- Hauptablauf --
def process(net_path, osm_path, out_path, crs, buffer, data_dir="./data", log_candidates=False, view=None, clip_region=None):
    """
    Hauptfunktion: Segmentiert das Netz, führt das Snapping durch und verschmilzt die Segmente wieder.
    net_path: Pfad zum Netz (mit Layer)
    osm_path: Pfad zu TILDA-übersetzten Daten (mit Layer)
    out_path: Ausgabepfad (mit Layer)
    crs: Ziel-Koordinatensystem (EPSG)
    buffer: Puffergröße für Matching
    data_dir: Verzeichnis mit den Eingabedateien
    view: Viewport Zuschnitt ('zoom/lat/lon')
    clip_region: Regionaler Zuschnitt ('neukoelln', 'norden', 'sueden')
    """
    # ---------- Daten laden -------------------------------------------------
    # Logging konfigurieren mit detaillierteren Informationen
    logging.basicConfig(
        level=logging.INFO, 
        format='%(asctime)s - %(levelname)s: %(message)s',
        datefmt='%H:%M:%S'
    )
    
    def read(path):
        f, *layer = path.split(":")
        return gpd.read_file(f, layer=layer[0] if layer else None)

    logging.info("Lade Netzwerk- und TILDA-übersetzte Daten ...")
    net = read(net_path).to_crs(crs)
    osm = read(osm_path).to_crs(crs)
    
    logging.info(f"Netzwerk: {len(net)} Features geladen")
    logging.info(f"TILDA-übersetzte Daten: {len(osm)} Features geladen")
    
    # Räumliche Filter: Entweder Region oder View (nicht beides erlaubt – wird vorher geprüft)
    if clip_region:
        from helpers.clipping import clip_to_region
        logging.info(f"Schneide Netzwerk auf Region {clip_region} zu")
        net = clip_to_region(net, data_dir, crs, clip_region)
        logging.info(f"Schneide TILDA-übersetzte Daten auf Region {clip_region} zu")
        osm = clip_to_region(osm, data_dir, crs, clip_region)
    elif view:
        logging.info(f"Schneide Daten auf Viewport {view} (WGS84, Standard 1920x1080) zu")
        net = clip_to_view(net, view, crs)
        osm = clip_to_view(osm, view, crs)

    # Abort wenn eine der Quellen leer ist
    if len(net) == 0:
        logging.error("Abbruch: Netzwerk nach Clipping leer – keine weitere Verarbeitung möglich")
        sys.exit(1)
    if len(osm) == 0:
        logging.error("Abbruch: TILDA-Daten nach Clipping leer – keine weitere Verarbeitung möglich")
        sys.exit(1)

    # Prüfen, ob alle Pflichtfelder im Netz vorhanden sind
    for fld in (RVN_ATTRIBUT_ELEMENT_NR, RVN_ATTRIBUT_BEGINN_VP, RVN_ATTRIBUT_ENDE_VP):
        if fld not in net.columns:
            sys.exit(f"Pflichtfeld “{fld}” fehlt im Netz!")

    # ---------- Netz segmentieren und speichern -----------------------------
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    
    # Stelle sicher, dass das segmentierte Detailnetz und das Ausgabeverzeichnis existiert
    # Zielverzeichnis je nach Modus
    if view and not clip_region:
        base_output_dir = "./output-bbox"
    else:
        base_output_dir = "./output"

    filename_suffix = f"_{clip_region}" if clip_region else ("_view" if view else "")
    seg_path = f"{base_output_dir}/snapping/rvn-segmented{filename_suffix}.fgb"
    os.makedirs(os.path.dirname(seg_path), exist_ok=True)
    
    if os.path.exists(seg_path):
        logging.info(f"Lade bereits segmentiertes Netz aus {seg_path} ...")
        net_segmented = gpd.read_file(seg_path)
        # Stelle sicher, dass das CRS korrekt ist
        if net_segmented.crs != crs:
            logging.info(f"Transformiere CRS von {net_segmented.crs} zu {crs}")
            net_segmented = net_segmented.to_crs(crs)
    else:
        logging.info("Segmentiere Netz in Segmente ...")
        net_segmented = split_network_into_segments(net, crs, segment_length=CONFIG_SEGMENT_LENGTH)
        net_segmented.to_file(seg_path, driver="FlatGeobuf")
        logging.info(f"✔  Segmentiertes Netz gespeichert als {seg_path}")

    # ---------- Snapping/Attributübernahme auf Segmente ---------------------
    seg_attr_path = f"{base_output_dir}/snapping/rvn-segmented-attributed-osm{filename_suffix}.fgb"
    os.makedirs(os.path.dirname(seg_attr_path), exist_ok=True)
    
    if os.path.exists(seg_attr_path):
        logging.info(f"Lade bereits attributierte Segmente aus {seg_attr_path} ...")
        net_segmented = gpd.read_file(seg_attr_path)
        # Stelle sicher, dass das CRS korrekt ist
        if net_segmented.crs != crs:
            logging.info(f"Transformiere CRS von {net_segmented.crs} zu {crs}")
            net_segmented = net_segmented.to_crs(crs)
    else:
        logging.info("Führe Snapping und TILDA-Attributübernahme durch ...")
        # Erzeuge einen räumlichen Index für die TILDA-Daten, um schnelle räumliche Abfragen zu ermöglichen
        osm_sidx = osm.sindex  # Räumlicher Index für TILDA-Daten

        # Optional: Öffne Kandidaten-Log-Datei für QA-Zwecke
        candidates_log = None
        if log_candidates:
            qa_dir = f"{base_output_dir}/snapping"
            os.makedirs(qa_dir, exist_ok=True)
            candidates_log_file = os.path.join(qa_dir, f"osm_candidates_per_edge{filename_suffix}.txt")
            
            # Benenne alte Datei um falls sie existiert
            if os.path.exists(candidates_log_file):
                old_file = candidates_log_file.replace('.txt', '_OLD.txt')
                # Entferne eventuell vorhandene alte _OLD Datei
                if os.path.exists(old_file):
                    os.remove(old_file)
                os.rename(candidates_log_file, old_file)
                logging.info(f"Alte Kandidaten-Log-Datei umbenannt: {old_file}")
            
            candidates_log = open(candidates_log_file, 'w', encoding='utf-8')
            candidates_log.write("# TILDA-Kandidaten pro element_nr und Richtung\n")
            candidates_log.write("# Generiert von start_snapping.py\n")
            candidates_log.write(f"# Puffergröße: {buffer}m\n")
            candidates_log.write("#\n")
            candidates_log.write("# Format: element_nr -> Segment #X -> ri=0/1: bester_kandidat [Details] verfügbare: [alle_kandidaten]\n")
            candidates_log.write("#\n\n")

        # Verarbeite alle Segmente
        total = len(net_segmented)
        snapped_records = []
        
        logging.info(f"Starte Snapping von {total} Segmenten mit CPU-Parallelisierung ({CONFIG_CPU_CORES} Kerne)...")
        start_time = time.time()
        
        # Konvertiere zu Liste für Batch-Verarbeitung
        segments_list = []
        for _, row in net_segmented.iterrows():
            seg_dict = row.to_dict()
            segments_list.append(seg_dict)
        
        # Entscheide zwischen paralleler und sequenzieller Verarbeitung
        if log_candidates or total < CONFIG_BATCH_SIZE * 2:
            # Sequenzielle Verarbeitung für Kandidaten-Logging oder kleine Datenmengen
            logging.info("Verwende sequenzielle Verarbeitung (Kandidaten-Logging aktiviert oder kleine Datenmenge)")
            for batch_start in range(0, total, CONFIG_BATCH_SIZE):
                batch_end = min(batch_start + CONFIG_BATCH_SIZE, total)
                segments_batch = segments_list[batch_start:batch_end]
                
                # Verarbeite aktuelle Batch
                batch_results = process_segments_batch(
                    segments_batch, osm, osm.sindex, buffer, 
                    candidates_log, batch_start
                )
                snapped_records.extend(batch_results)
                
                # Aktualisiere Fortschritt nur periodisch (deutlich schneller)
                if batch_end % CONFIG_PROGRESS_UPDATE_INTERVAL == 0 or batch_end == total:
                    elapsed = time.time() - start_time
                    rate = batch_end / elapsed if elapsed > 0 else 0
                    
                    print_progressbar(batch_end, total, 
                        prefix=f"Snapping ({rate:.1f}/s): ", start_time=start_time)
        else:
            # Parallelisierte Verarbeitung für bessere Performance
            logging.info(f"Verwende parallelisierte Verarbeitung mit {CONFIG_CPU_CORES} Kernen")
            
            # Erstelle temporäre Pickle-Datei für OSM-Daten (für Worker-Prozesse)
            with tempfile.NamedTemporaryFile(suffix='.pkl', delete=False) as temp_file:
                osm_temp_path = temp_file.name
            
            # Speichere OSM-Daten als Pickle (unterstützt alle Python-Objekte)
            with open(osm_temp_path, 'wb') as f:
                pickle.dump(osm, f)
            
            try:
                # Bereite Batches für Parallelverarbeitung vor
                batch_data_list = []
                
                for batch_start in range(0, total, CONFIG_BATCH_SIZE):
                    batch_end = min(batch_start + CONFIG_BATCH_SIZE, total)
                    segments_batch = segments_list[batch_start:batch_end]
                    batch_data_list.append((segments_batch, osm_temp_path, buffer, batch_start))
                
                # Verwende multiprocessing Pool für parallele Verarbeitung mit Progress-Balken
                with mp.Pool(processes=CONFIG_CPU_CORES) as pool:
                    # Verwende imap für iterative Verarbeitung mit Progress-Updates
                    batch_count = len(batch_data_list)
                    processed_segments = 0
                    
                    # Starte parallele Verarbeitung mit imap (behält Reihenfolge bei)
                    for i, batch_results in enumerate(pool.imap(process_segments_batch_parallel, batch_data_list)):
                        snapped_records.extend(batch_results)
                        
                        # Zähle verarbeitete EINGABE-Segmente (nicht Ausgabe-Kanten)
                        # Jede Batch verarbeitet CONFIG_BATCH_SIZE Segmente (außer der letzten)
                        batch_size = len(batch_data_list[i][0])  # Anzahl Segmente in dieser Batch
                        processed_segments += batch_size
                        
                        # Aktualisiere Progress-Balken basierend auf verarbeiteten EINGABE-Segmenten
                        elapsed = time.time() - start_time
                        rate = processed_segments / elapsed if elapsed > 0 else 0
                        
                        print_progressbar(processed_segments, total, 
                            prefix=f"Snapping ({rate:.1f}/s, parallel): ", start_time=start_time)
                    
                    # Finale Statistiken
                    elapsed = time.time() - start_time
                    rate = total / elapsed if elapsed > 0 else 0
                    output_edges = len(snapped_records)
                    logging.info(f"Parallelverarbeitung abgeschlossen: {total} Segmente → {output_edges} Kanten in {elapsed:.1f}s ({rate:.1f} seg/s)")
                    
            finally:
                # Aufräumen: Lösche temporäre Datei
                if os.path.exists(osm_temp_path):
                    os.unlink(osm_temp_path)
        
        elapsed_total = time.time() - start_time
        final_rate = total / elapsed_total
        logging.info(f"Snapping abgeschlossen: {total} Segmente in {elapsed_total:.1f}s "
                    f"(Durchschnitt: {final_rate:.1f} Segmente/s)")
        # Schließe die Kandidaten-Log-Datei falls geöffnet
        if candidates_log:
            candidates_log.close()
            logging.info(f"✔  Kandidaten-Log erstellt: {candidates_log_file}")
        else:
            logging.info("Kandidaten-Logging deaktiviert (verwende --log-candidates zum Aktivieren)")

        # Erstelle GeoDataFrame aus allen bearbeiteten Segmenten
        net_segmented = gpd.GeoDataFrame(snapped_records, crs=crs)
        net_segmented.to_file(seg_attr_path, driver="FlatGeobuf")
        logging.info(f"✔  Attributierte Segmente gespeichert als {seg_attr_path}")

    # ---------- Opposite-Edge-Overwrite anwenden ----------------------------
    logging.info("Lade Opposite-Edge-Overwrite-Liste...")
    opposite_edge_element_nrs = load_opposite_edge_overwrite_list(data_dir)
    
    if opposite_edge_element_nrs:
        net_segmented = apply_opposite_edge_overwrite(net_segmented, opposite_edge_element_nrs)
    
    # ---------- Segmente verschmelzen ---------------------------------------
    logging.info("Fasse Segmente mit gleicher element_nr und TILDA-Attributen zusammen ...")
    
    # Debug: Analysiere Merge-Attribute vor dem Verschmelzen
    logging.info(f"Zu verwendende Merge-Attribute: {FINAL_DATASET_SEGMENT_MERGE_ATTRIBUTES}")
    debug_merge_attributes(net_segmented, "element_nr", FINAL_DATASET_SEGMENT_MERGE_ATTRIBUTES)
    
    out_gdf = merge_segments(net_segmented, "element_nr", FINAL_DATASET_SEGMENT_MERGE_ATTRIBUTES)
    if len(out_gdf) == 0:
        logging.error("Abbruch: Keine Ausgabesegmente nach Merging entstanden")
        sys.exit(1)

    # ---------- Finale Datenbereinigung ------------------------------------
    # Entferne Breite-Attribut bei allen Kanten mit Mischverkehr mit motorisiertem Verkehr
    mischverkehr_mask = out_gdf['fuehr'] == 'Mischverkehr mit motorisiertem Verkehr'
    mischverkehr_count = mischverkehr_mask.sum()
    if mischverkehr_count > 0:
        logging.info(f"Entferne Breite-Attribut bei {mischverkehr_count} Kanten mit Mischverkehr")
        out_gdf.loc[mischverkehr_mask, 'breite'] = None

    # Setze Breite auf '[TODO] Breite fehlt' für alle Segmente mit NULL-Breite 
    # (außer Mischverkehr und "Keine Radinfrastruktur vorhanden")
    nicht_mischverkehr_mask = out_gdf['fuehr'] != 'Mischverkehr mit motorisiertem Verkehr'
    keine_radinfra_mask = out_gdf['fuehr'] != 'Keine Radinfrastruktur vorhanden'
    breite_null_mask = out_gdf['breite'].isna()
    combined_mask = nicht_mischverkehr_mask & keine_radinfra_mask & breite_null_mask
    breite_todo_count = combined_mask.sum()
    if breite_todo_count > 0:
        logging.info(f"Setze breite='[TODO] Breite fehlt' für {breite_todo_count} Kanten ohne Breite (exkl. Mischverkehr und 'Keine Radinfrastruktur')")
        out_gdf.loc[combined_mask, 'breite'] = '[TODO] Breite fehlt'

    # ---------- SFID hinzufügen ---------------------------------------------
    logging.info("Füge SFID-Spalte (Snapping FID) hinzu...")
    out_gdf['sfid'] = range(1, len(out_gdf) + 1)
    logging.info(f"SFID-Spalte hinzugefügt: {len(out_gdf)} Kanten nummeriert")
    
    # ---------- Bezirkszuweisung durchführen -------------------------------
    districts_path = os.path.join(data_dir, "Berlin Bezirke.gpkg")
    if os.path.exists(districts_path):
        logging.info("Starte Bezirkszuweisung...")
        out_gdf = assign_district_to_edges(out_gdf, districts_path, crs)
    else:
        logging.warning(f"Bezirksdatei nicht gefunden: {districts_path}. Überspringe Bezirkszuweisung.")
    
    # ---------- Datenaufbereitung: Spaltenordnung --------------------------
    logging.info("Bereite Daten für Ausgabe vor: Ordne Spalten...")
    out_gdf = reorder_columns_for_output(out_gdf)

    # ---------- Finale Datenbereinigung: fuehr=null beheben ---------------
    # Wenn kein passender Weg gefunden wurde (prio_total < -10), ist fuehr=null
    # Diese Wege erhalten die korrekte Zuweisung: "Keine Radinfrastruktur vorhanden"
    fuehr_null_mask = out_gdf['fuehr'].isna()
    fuehr_null_count = fuehr_null_mask.sum()
    if fuehr_null_count > 0:
        logging.info(f"Setze fuehr='Keine Radinfrastruktur vorhanden' für {fuehr_null_count} Kanten ohne TILDA-Match (prio_total < -10)")
        out_gdf.loc[fuehr_null_mask, 'fuehr'] = 'Keine Radinfrastruktur vorhanden'

    # ---------- Ergebnis speichern ------------------------------------------
    p, *layer = out_path.split(":")
    layer = layer[0] if layer else "edges_enriched"
    
    # Stelle sicher, dass das Ausgabeverzeichnis existiert
    os.makedirs(os.path.dirname(p), exist_ok=True)
    
    # Füge Suffix für regionale Dateien hinzu
    if clip_region:
        # Extrahiere Dateiname und Erweiterung
        p_parts = p.split('.')
        if len(p_parts) > 1:
            p_base = '.'.join(p_parts[:-1])
            p_ext = p_parts[-1]
            p = f"{p_base}_{clip_region}.{p_ext}"
        else:
            p = f"{p}_{clip_region}"
    
    # Lösche existierende Ausgabedatei NACH dem Suffix-Handling, um Write-Access-Fehler zu vermeiden
    Path(p).unlink(missing_ok=True)
    
    out_gdf.to_file(p, layer=layer, driver="FlatGeoBuf")
    print(f"✔  {len(out_gdf)} Kanten → {p}:{layer}")


# ------------------------------------------------------------- CLI Wrapper --
if __name__ == "__main__":
    # Kommandozeilenargumente parsen
    ap = argparse.ArgumentParser(description="Snapping von TILDA-übersetzten Attributen auf Straßennetz")
    ap.add_argument("--net", default="./output/rvn/vorrangnetz_details_combined_rvn.fgb", 
                    help="Netz-Layer (Pfad[:Layer]) - Default: ./output/vorrangnetz_details_combined_rvn.fgb")
    ap.add_argument("--osm", default="./output/matched/matched_tilda_ways.fgb", 
                    help="TILDA-übersetzte Daten (Pfad[:Layer]) - Default: ../output/matching/matched_tilda_ways.fgb")
    ap.add_argument("--out", default="./output/snapping_network_enriched.fgb", 
                    help="Ausgabe (Pfad[:Layer]) - Default: ./output/snapping_network_enriched.fgb (Bei --view automatisch nach output-bbox umgeleitet)")
    ap.add_argument("--crs",  type=int,   default=DEFAULT_CRS,
                    help=f"Ziel-EPSG (default {DEFAULT_CRS})")
    ap.add_argument("--buffer", type=float, default=CONFIG_BUFFER_DEFAULT,
                    help=f"Matching-Puffer in m (default {CONFIG_BUFFER_DEFAULT})")
    ap.add_argument("--clip", type=str, choices=['neukoelln', 'norden', 'sueden'],
                    help="Regionaler Zuschnitt: 'neukoelln', 'norden' oder 'sueden'. Nicht mit --view kombinierbar.")
    ap.add_argument("--data-dir", default="./data", 
                    help="Pfad zum Datenverzeichnis (default: ./data)")
    ap.add_argument("--view", type=str, help="Viewport Zuschnitt 'zoom/lat/lon' (WGS84, z.B. 18/52.488306/13.425140). Nicht zusammen mit --clip verwenden.")
    ap.add_argument("--log-candidates", action="store_true",
                    help="Erstelle detaillierte Kandidaten-Log-Datei für Debugging (optional)")
    ap.add_argument("--cpu-cores", type=int, default=CONFIG_CPU_CORES,
                    help=f"Anzahl CPU-Kerne für Parallelisierung (default: {CONFIG_CPU_CORES})")
    args = ap.parse_args()

    # Konfliktprüfung
    if args.clip and args.view:
        logging.error("--clip und --view können nicht gemeinsam verwendet werden")
        sys.exit(1)

    # Bei View Standard-Eingabepfad in output-bbox umlenken falls unverändert
    if args.view:
        if args.osm == "./output/matched/matched_tilda_ways.fgb":
            args.osm = "./output-bbox/matched/matched_tilda_ways.fgb"
        if args.out == "./output/snapping_network_enriched.fgb":
            args.out = "./output-bbox/snapping_network_enriched_view.fgb"

    # CPU-Kerne-Konfiguration übernehmen (validiere Eingabe)
    cpu_cores = max(1, min(args.cpu_cores, mp.cpu_count()))
    if cpu_cores != CONFIG_CPU_CORES:
        logging.info(f"CPU-Kerne konfiguriert: {cpu_cores} (Standard: {CONFIG_CPU_CORES})")
    
    # Überschreibe globale Konfiguration
    CONFIG_CPU_CORES = cpu_cores
    
    # Hauptfunktion aufrufen
    process(args.net, args.osm, args.out, args.crs, args.buffer, args.data_dir, args.log_candidates, args.view, args.clip)

