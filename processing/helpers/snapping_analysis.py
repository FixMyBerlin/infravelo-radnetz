#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
snapping_analysis.py
--------------------------------------------------------------------
Gemeinsame Funktionen für Snapping-Algorithmus und Analyse.
Modularisierte Funktionen aus start_snapping.py für Wiederverwendung.

Diese Funktionen werden sowohl vom Snapping-Algorithmus als auch vom
Analyse-Skript verwendet.
"""

import numpy as np
import logging
from shapely.geometry import LineString, MultiLineString
from .traffic_signs import has_traffic_sign


class SnappingPriorities:
    """
    Zentrale Konfiguration für alle Prioritätswerte beim Snapping.
    Alle Werte sind als Klassenvariablen definiert und können einfach angepasst werden.
    
    Diese Konfiguration wird sowohl vom Snapping-Algorithmus als auch vom
    Analyse-Skript (analyze_snapping_candidates.py) verwendet.
    """
    
    # Verkehrszeichen-Prioritäten (höhere Zahl = höhere Priorität)
    TRAFFIC_SIGN_PRIORITIES = {
        "237": 3,  # Radweg
        "240": 3,  # Gemeinsamer Geh- und Radweg
        "241": 3,  # Getrennter Rad- und Gehweg
    }
    
    # Kategorie-Prioritäten (höhere Zahl = höhere Priorität)
    CATEGORY_PRIORITIES = {
        "bicycleRoad*": 15,  # Fahrradstraße
        "cycleway*": 15,  # Radweg
        "footAndCycleway*": 12,  # Fußweg mit Radverkehr
        "crossing": 10,
        "sharedBusLaneBikeWithBus": 8,  # Gemeinsame Busspur mit Radverkehr
        "sharedBusLaneBusWithBike": 8,
        "footwayBicycle*": 5,  # Fußweg mit Radverkehr
        "pedestrianAreaBicycleYes": 5,  # Fußgängerzone mit Radverkehr
        "sharedMotorVehicleLane": 1,  # Niedrigste Priorität
    }
    
    # Straßennamen-Match Prioritäten
    STREET_NAME_MATCH_REWARD = 10     # Belohnung für exakte Straßennamen-Übereinstimmung
    STREET_NAME_MISMATCH_PENALTY = -20  # Strafe für Straßennamen-Mismatch
    
    # Richtungskompatibilität Prioritäten
    DIRECTION_PERFECT_MATCH = 10     # Einrichtungsverkehr mit passender Richtung
    DIRECTION_BIDIRECTIONAL = 8      # Zweirichtungsverkehr (beide Richtungen möglich)
    DIRECTION_WRONG_WAY = -10        # Einrichtungsverkehr mit falscher Richtung
    
    # Winkel-Priorität Konfiguration (kontinuierliche Funktion)
    ANGLE_PARALLEL_REWARD = 10       # Belohnung für parallele Wege (0°, 180°) - maximaler Wert
    ANGLE_ORTHOGONAL_PENALTY = -20   # Strafe für orthogonale Wege (90°) - minimaler Wert der kontinuierlichen Funktion
    
    # Entfernungs-Priorität Konfiguration
    DISTANCE_MAX_PRIORITY = 20       # Maximale Priorität bei Entfernung 0m
    DISTANCE_REFERENCE = 10.0        # Referenz-Entfernung in Metern (bei dieser Entfernung = halbe Priorität)
    DISTANCE_WEIGHT_FACTOR = 1.0     # Gewichtungsfaktor für Entfernungseinfluss (1.0 = volle Gewichtung)


def calculate_line_angle(geom):
    """
    Berechnet den Winkel einer Linie in Grad (0-360°).
    Behandelt MultiLineString korrekt.
    """
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
            return 0.0
    elif hasattr(geom, 'coords'):
        coords = list(geom.coords)
        if len(coords) >= 2:
            p1, p2 = coords[0], coords[-1]
        else:
            return 0.0
    else:
        return 0.0

    # Berechne Winkel
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    
    # Arctan2 gibt Winkel in Radians zurück (-π bis π)
    angle_rad = np.arctan2(dy, dx)
    # Konvertiere zu Grad und normalisiere auf 0-360°
    angle_deg = np.degrees(angle_rad)
    if angle_deg < 0:
        angle_deg += 360
        
    return angle_deg


def angle_difference(angle1, angle2):
    """
    Berechnet die kleinste Winkeldifferenz zwischen zwei Winkeln.
    Berücksichtigt die 360°-Periodizität.
    
    Returns:
        float: Winkeldifferenz in Grad (0-180°)
    """
    # Normalisiere beide Winkel auf 0-360°
    angle1 = angle1 % 360
    angle2 = angle2 % 360
    
    # Berechne Differenz
    diff = abs(angle1 - angle2)
    
    # Nimm den kleineren Winkel (berücksichtige 360°-Wrap)
    return min(diff, 360 - diff)


def calculate_angle_priority(segment_geom, candidate_geom):
    """
    Berechnet die Winkel-Priorität basierend auf der Ausrichtung zwischen Segment und Kandidat.
    Verwendung einer kontinuierlichen Sinusfunktion für weiche Übergänge.
    
    Args:
        segment_geom: Geometrie des Netzwerksegments
        candidate_geom: Geometrie des Kandidaten
        
    Returns:
        float: Winkel-Priorität (-20 bis +10)
    """
    segment_angle = calculate_line_angle(segment_geom)
    candidate_angle = calculate_line_angle(candidate_geom)
    
    angle_diff = angle_difference(segment_angle, candidate_angle)
    
    # Verwende sin²(angle_diff/2) für kontinuierliche Übergang
    # 0° → sin²(0) = 0 → beste Priorität (+10)
    # 90° → sin²(45°) ≈ 0.5 
    # 180° → sin²(90°) = 1 → etwas schlechtere Priorität als 0°
    # Normalisiere auf 0-90° für sin² Berechnung
    normalized_angle = min(angle_diff, 180 - angle_diff)
    
    # sin² von halbem Winkel für weicheren Übergang
    sin_squared = np.sin(np.radians(normalized_angle / 2)) ** 2
    
    # Linear interpolieren zwischen PARALLEL_REWARD (beste) und ORTHOGONAL_PENALTY (schlechteste)
    angle_priority = SnappingPriorities.ANGLE_PARALLEL_REWARD + (SnappingPriorities.ANGLE_ORTHOGONAL_PENALTY - SnappingPriorities.ANGLE_PARALLEL_REWARD) * sin_squared
    
    logging.debug(f"Winkel-Priorität: {angle_diff:.1f}° → sin²={sin_squared:.3f} → {angle_priority:.2f} Punkte (kontinuierlich 10 bis -20)")
    return angle_priority


def calculate_distance_priority(distance):
    """
    Berechnet die Entfernungs-Priorität basierend auf der Entfernung zum Segmentmittelpunkt.
    Verwendet eine hyperbolische Abnahme für weiche Übergänge.
    
    Args:
        distance: Entfernung in Metern
        
    Returns:
        float: Entfernungs-Priorität (0 bis DISTANCE_MAX_PRIORITY)
    """
    # Verwende hyperbolische Funktion: priority = max_priority / (1 + distance/reference)
    # Bei distance=0m → priority = max_priority
    # Bei distance=reference → priority = max_priority/2
    # Bei distance=∞ → priority → 0
    distance_priority = (SnappingPriorities.DISTANCE_MAX_PRIORITY / 
                        (1 + distance / SnappingPriorities.DISTANCE_REFERENCE)) * SnappingPriorities.DISTANCE_WEIGHT_FACTOR
    
    logging.debug(f"Entfernungs-Priorität: {distance:.1f}m → {distance_priority:.2f} Punkte")
    return distance_priority


def determine_segment_direction(segment_geom, osm_geom) -> int:
    """
    Bestimmt die Richtung (ri) eines Segments basierend auf der Ausrichtung
    zwischen dem Segment und dem passenden OSM-Weg.
    
    Args:
        segment_geom: Geometrie des Netzwerksegments
        osm_geom: Geometrie des OSM-Wegs
        
    Returns:
        int: 0 für Hinrichtung (gleiche Richtung), 1 für Rückrichtung (entgegengesetzte Richtung)
    """
    segment_angle = calculate_line_angle(segment_geom)
    osm_angle = calculate_line_angle(osm_geom)
    
    angle_diff = angle_difference(segment_angle, osm_angle)
    
    # Wenn der Winkelunterschied kleiner als 90° ist, haben beide die gleiche Richtung (ri=0)
    # Wenn größer als 90°, haben sie entgegengesetzte Richtungen (ri=1)
    return 0 if angle_diff < 90 else 1


def calculate_osm_priority_detailed(row, seg_dict=None) -> tuple:
    """
    Berechnet die Priorität eines OSM-Wegs mit detailliertem Breakdown.
    
    Returns:
        tuple: (total_priority, {traffic_priority, category_priority, street_name_priority, details})
    """
    priority = 0
    tilda_id = row.get("tilda_id", "unknown")
    
    # Priorität basierend auf Verkehrszeichen (mit tilda_ Präfix)
    traffic_sign = row.get("tilda_traffic_sign", "")
    traffic_priority = 0
    traffic_sign_matched = None
    if traffic_sign:
        for sign, prio in SnappingPriorities.TRAFFIC_SIGN_PRIORITIES.items():
            if has_traffic_sign(traffic_sign, sign):
                traffic_priority = max(traffic_priority, prio)
                traffic_sign_matched = sign
        priority += traffic_priority
    
    # Priorität basierend auf Kategorie (mit tilda_ Präfix)
    category = row.get("tilda_category", "")
    category_priority = 0
    matched_pattern = None
    if category:
        category_str = str(category)
        for pattern, prio in SnappingPriorities.CATEGORY_PRIORITIES.items():
            # Prüfe ob Pattern mit * endet (Wildcard-Match)
            if pattern.endswith("*"):
                # Entferne das * und prüfe ob Kategorie mit dem Präfix beginnt
                prefix = pattern[:-1]
                if category_str.startswith(prefix):
                    if prio > category_priority:
                        category_priority = prio
                        matched_pattern = pattern
            else:
                # Exakter Match
                if category_str == pattern:
                    if prio > category_priority:
                        category_priority = prio
                        matched_pattern = pattern
        priority += category_priority
    
    # Priorität basierend auf Straßennamen-Match
    street_name_priority = 0
    street_name_detail = "kein_segment"
    if seg_dict is not None:
        segment_strassenname = seg_dict.get("strassenname", "")
        tilda_name = row.get("tilda_name", "")
        # Wenn beide leer sind, keine Punkte vergeben
        if not segment_strassenname and not tilda_name:
            street_name_detail = "beide_leer"
        elif segment_strassenname and tilda_name:
            # Normalisiere die Namen für Vergleich (Leerzeichen trimmen, Case-Insensitive)
            segment_name_norm = str(segment_strassenname).strip().lower()
            tilda_name_norm = str(tilda_name).strip().lower()
            if segment_name_norm == tilda_name_norm:
                street_name_priority = SnappingPriorities.STREET_NAME_MATCH_REWARD
                street_name_detail = f"match('{segment_strassenname}')"
            else:
                street_name_priority = SnappingPriorities.STREET_NAME_MISMATCH_PENALTY
                street_name_detail = f"mismatch('{segment_strassenname}'!='{tilda_name}')"
        # Wenn nur einer leer ist, als Mismatch werten
        else:
            street_name_priority = 0
            street_name_detail = f"einer_leer('{segment_strassenname}'vs'{tilda_name}')"
        priority += street_name_priority
    
    # Detailliertes Breakdown zurückgeben
    details = {
        'traffic_priority': traffic_priority,
        'traffic_sign': traffic_sign or "None",
        'traffic_sign_matched': traffic_sign_matched,
        'category_priority': category_priority, 
        'category': category or "None",
        'category_pattern': matched_pattern,
        'street_name_priority': street_name_priority,
        'street_name_detail': street_name_detail,
        'total_priority': priority
    }
    
    return priority, details


def calculate_osm_priority(row, seg_dict=None) -> int:
    """
    Berechnet die Priorität eines OSM-Wegs basierend auf traffic_sign, category und Straßennamen-Match.
    Höhere Zahl = höhere Priorität.
    Unterstützt Wildcard-Matching: Kategorien mit '*' am Ende verwenden Präfix-Match.
    
    Args:
        row: TILDA-Kandidat Zeile mit den zu bewertenden Attributen
        seg_dict: Segment-Dictionary mit strassenname für Straßennamen-Vergleich
        
    Returns:
        int: Prioritätswert (höher = besser)
    """
    priority, details = calculate_osm_priority_detailed(row, seg_dict)
    
    # Logging für Debug-Zwecke (falls aktiviert)
    tilda_id = row.get("tilda_id", "unknown")
    components = []
    
    if details['traffic_sign'] != "None":
        components.append(f"Traffic_Sign({details['traffic_sign']})={details['traffic_priority']}")
    else:
        components.append("Traffic_Sign(None)=0")
        
    if details['category'] != "None":
        if details['category_pattern']:
            components.append(f"Category({details['category']}~{details['category_pattern']})={details['category_priority']}")
        else:
            components.append(f"Category({details['category']})=0")
    else:
        components.append("Category(None)=0")
    
    components.append(f"StreetName({details['street_name_detail']})={details['street_name_priority']}")
    
    components_str = " + ".join(components)
    logging.debug(f"Kandidat {tilda_id}: {components_str} = GESAMT:{priority}")
    
    return priority


def find_best_candidate_for_direction(candidates, seg_dict, ri_value, segment_angle=None):
    """
    Findet den besten TILDA-Kandidaten für eine spezifische Richtung.
    Berücksichtigt verkehrsri und Richtungsausrichtung.
    
    Args:
        candidates: GeoDataFrame mit TILDA-Kandidaten
        seg_dict: Dictionary des Segments
        ri_value: Richtung (0=Hinrichtung, 1=Rückrichtung)
        segment_angle: Optional vorberechneter Segmentwinkel
        
    Returns:
        dict oder None: Bester Kandidat für die gegebene Richtung
    """
    
    if candidates is None or len(candidates) == 0:
        logging.debug(f"Keine Kandidaten für ri={ri_value}")
        return None
    
    candidates = candidates.copy()
    segment_geom = seg_dict["geometry"]
    element_nr = seg_dict.get("element_nr", "unknown")
    
    logging.debug(f"Bewerte {len(candidates)} Kandidaten für ri={ri_value}, element_nr={element_nr}")
    
    # Berechne Priorität für alle Kandidaten (inkl. Straßennamen-Match) mit Details
    candidates["priority"] = candidates.apply(lambda row: calculate_osm_priority(row, seg_dict), axis=1)
    
    # Berechne detaillierte Prioritätsinformationen für Logging
    priority_details = {}
    for idx, candidate in candidates.iterrows():
        _, details = calculate_osm_priority_detailed(candidate, seg_dict)
        priority_details[idx] = details
    
    # Berechne Winkel-Priorität für alle Kandidaten
    candidates["angle_priority"] = 0.0
    for idx, candidate in candidates.iterrows():
        angle_prio = calculate_angle_priority(segment_geom, candidate.geometry)
        candidates.at[idx, "angle_priority"] = angle_prio
    
    # Berechne Entfernung zum Segmentmittelpunkt und Entfernungs-Priorität
    mid = segment_geom.interpolate(0.5, normalized=True)
    candidates["dist_to_mid"] = candidates.geometry.distance(mid)
    
    # Berechne Entfernungs-Priorität für alle Kandidaten
    candidates["distance_priority"] = candidates["dist_to_mid"].apply(calculate_distance_priority)
    
    # Berechne Gesamt-Priorität: TILDA-Inhalt + Winkel + Entfernung + Richtung
    # Richtungskompatibilität wird separat behandelt, da sie binär ist (positiv/negativ)
    candidates["total_priority_weighted"] = (
        candidates["priority"] +           # TILDA-Priorität (Inhalt)
        candidates["angle_priority"] +     # Winkel-Priorität 
        candidates["distance_priority"]    # Entfernungs-Priorität
    )
    
    # Berechne Richtungskompatibilität für jeden Kandidaten
    candidates["direction_compatibility"] = 0
    
    # Logge Segmentwinkel für Debugging - verwende übergebenen Winkel falls vorhanden
    if segment_angle is None:
        segment_angle = calculate_line_angle(segment_geom)
    logging.debug(f"Segment element_nr={element_nr}: Winkel={segment_angle:.1f}°")
    
    for idx, candidate in candidates.iterrows():
        candidate_verkehrsri = candidate.get('verkehrsri', '')
        candidate_tilda_id = candidate.get('tilda_id', f'idx_{idx}')
        # Verwende bereits berechneten Winkel falls vorhanden
        if 'angle' in candidate:
            candidate_angle = candidate['angle']
        else:
            candidate_angle = calculate_line_angle(candidate.geometry)
        
        if candidate_verkehrsri == 'Einrichtungsverkehr':
            # Bei Einrichtungsverkehr: Prüfe Richtungsausrichtung
            segment_direction = determine_segment_direction(segment_geom, candidate.geometry)
            
            logging.debug(f"  Kandidat {candidate_tilda_id}: Einrichtungsverkehr, "
                         f"Winkel={candidate_angle:.1f}°, segment_direction={segment_direction}, "
                         f"ri_value={ri_value}")
            
            if segment_direction == ri_value:
                # Richtung passt perfekt
                candidates.at[idx, "direction_compatibility"] = SnappingPriorities.DIRECTION_PERFECT_MATCH
                logging.debug(f"    → Richtung passt perfekt! direction_compatibility={SnappingPriorities.DIRECTION_PERFECT_MATCH}")
            else:
                # Richtung passt nicht - NEGATIVE Priorität für gegenläufige Wege
                candidates.at[idx, "direction_compatibility"] = SnappingPriorities.DIRECTION_WRONG_WAY
                logging.debug(f"    → Richtung passt NICHT! direction_compatibility={SnappingPriorities.DIRECTION_WRONG_WAY} (gegenläufig)")
        else:
            # Bei Zweirichtungsverkehr: Kann für beide Richtungen verwendet werden
            candidates.at[idx, "direction_compatibility"] = SnappingPriorities.DIRECTION_BIDIRECTIONAL
            logging.debug(f"  Kandidat {candidate_tilda_id}: Zweirichtungsverkehr, "
                         f"Winkel={candidate_angle:.1f}°, direction_compatibility={SnappingPriorities.DIRECTION_BIDIRECTIONAL}")
    
    # Filtere gegenläufige Kandidaten mit negativer direction_compatibility aus
    positive_candidates = candidates[candidates["direction_compatibility"] >= 0]
    
    if len(positive_candidates) == 0:
        logging.debug(f"Alle Kandidaten für ri={ri_value} haben negative direction_compatibility - nehme besten trotzdem")
        # Fallback: Wenn alle Kandidaten negativ sind, nehme den am wenigsten negativen
    else:
        candidates = positive_candidates
        logging.debug(f"Filtere {len(candidates.index) - len(positive_candidates)} gegenläufige Kandidaten aus")
    
    # Sortiere nach Richtungskompatibilität (erst positive), dann nach gewichteter Gesamtpriorität
    # Richtungskompatibilität wird zuerst sortiert, um gegenläufige Wege zu filtern
    # Dann nach der gewichteten Gesamtpriorität (TILDA + Winkel + Entfernung)
    candidates = candidates.sort_values(
        ["direction_compatibility", "total_priority_weighted"], 
        ascending=[False, False]
    )
    
    # Logge die Sortierreihenfolge mit detaillierten Prioritäten
    if len(candidates) > 0:
        best_candidate = candidates.iloc[0]
        logging.debug(f"=== BESTE KANDIDATEN-BEWERTUNG für ri={ri_value} ===")
        logging.debug(f"Bester Kandidat: {best_candidate.get('tilda_id', 'unknown')}")
        logging.debug(f"  → Direction_Compatibility: {best_candidate.get('direction_compatibility', -1)}")
        logging.debug(f"  → Gewichtete_Gesamtpriorität: {best_candidate.get('total_priority_weighted', -1):.2f}")
        logging.debug(f"    ├─ TILDA_Priority: {best_candidate.get('priority', -1)}")
        logging.debug(f"    ├─ Angle_Priority: {best_candidate.get('angle_priority', -1):.2f}")
        logging.debug(f"    └─ Distance_Priority: {best_candidate.get('distance_priority', -1):.2f} (bei {best_candidate.get('dist_to_mid', -1):.1f}m)")
        
        # Logge auch die anderen Kandidaten zur Nachvollziehbarkeit
        if len(candidates) > 1:
            logging.debug("=== ALLE KANDIDATEN (sortiert nach gewichteter Priorität) ===")
            for i, (_, cand) in enumerate(candidates.iterrows()):
                marker = "★ GEWÄHLT" if i == 0 else f"  {i+1}."
                logging.debug(f"{marker} {cand.get('tilda_id', 'unknown')}: "
                             f"dir_compat={cand.get('direction_compatibility', -1)}, "
                             f"total_weighted={cand.get('total_priority_weighted', -1):.2f} "
                             f"(tilda={cand.get('priority', -1)}, angle={cand.get('angle_priority', -1):.2f}, "
                             f"dist={cand.get('distance_priority', -1):.2f}@{cand.get('dist_to_mid', -1):.1f}m)")
    
    # Wähle den besten Kandidaten und füge detaillierte Prioritätsinformationen hinzu
    if len(candidates) > 0:
        best_candidate_dict = candidates.iloc[0].to_dict()
        best_idx = candidates.iloc[0].name  # Index des besten Kandidaten
        if best_idx in priority_details:
            best_candidate_dict['priority_details'] = priority_details[best_idx]
        return best_candidate_dict
    else:
        return None
