#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
snapping_calculations.py
--------------------------------------------------------------------
Gemeinsame Funktionen für Snapping-Algorithmus und Analyse.
Modularisierte Funktionen aus start_snapping.py für Wiederverwendung.

Diese Funktionen werden sowohl vom Snapping-Algorithmus als auch vom
Analyse-Skript verwendet.
"""

import numpy as np
import logging
from shapely.geometry import MultiLineString, Point, LineString
from shapely.ops import nearest_points
from .traffic_signs import has_traffic_sign


class SnappingPriorities:
    """
    Zentrale Konfiguration für alle Prioritätswerte beim Snapping.
    Alle Werte sind als Klassenvariablen definiert und können einfach angepasst werden.
    
    Diese Konfiguration wird sowohl vom Snapping-Algorithmus als auch vom
    Analyse-Skript (analyze_snapping_candidates.py) verwendet.
    
    Mindestpriorität (MINIMUM_TOTAL_PRIORITY):
    Kandidaten mit einer Gesamtpriorität (TILDA + geometrische + Richtungskompatibilität)
    unter diesem Wert werden komplett ausgeschlossen, auch wenn sie die einzigen verfügbaren 
    Kandidaten sind. Dies verhindert, dass Wege mit sehr schlechter Qualität oder falscher 
    Richtung ausgewählt werden.
    """
    
    # Verkehrszeichen-Prioritäten (höhere Zahl = höhere Priorität)
    TRAFFIC_SIGN_PRIORITIES = {
        "237": 5,  # Radweg
        "240": 5,  # Gemeinsamer Geh- und Radweg
        "241": 5,  # Getrennter Rad- und Gehweg
    }
    
    # Kategorie-Prioritäten (höhere Zahl = höhere Priorität)
    # Geht auch als Prozent in die Distanzberechnung ein.
    CATEGORY_PRIORITIES = {
        "cycleway*":                37,  # Radweg
        "footAndCycleway*":         35,  # Fußweg mit Radverkehr
        "footwayBicycle*":          32,  # Fußweg mit Radverkehr
        "bicycleRoad*":             27,  # Fahrradstraße
        "crossing":                 25, # Kreuzungsweg
        "sharedBusLaneBikeWithBus": 12,  # Radfahrstreifen mit Busverkehr frei
        "sharedBusLaneBusWithBike": 12, # Bussonderfahrstreifen mit Radverkehr frei
        "pedestrianAreaBicycleYes": 5,  # Fußgängerzone mit Radverkehr
        "sharedMotorVehicleLane":   1,  # Niedrigste Priorität
    }
    
    # Straßennamen-Match Prioritäten
    STREET_NAME_MATCH_REWARD = 20     # Belohnung für exakte Straßennamen-Übereinstimmung
    STREET_NAME_MISMATCH_PENALTY = -20  # Strafe für Straßennamen-Mismatch (reduziert von -30, da Segmente oft an Straßengrenzen liegen)
    
    # Richtungskompatibilität Prioritäten
    DIRECTION_PERFECT_MATCH = 15      # Einrichtungsverkehr mit passender Richtung
    DIRECTION_BIDIRECTIONAL = 10      # Zweirichtungsverkehr (beide Richtungen möglich)
    DIRECTION_WRONG_WAY = -100        # Einrichtungsverkehr mit falscher Richtung
    
    # Winkel-Priorität Konfiguration (kontinuierliche Funktion)
    ANGLE_PARALLEL_REWARD = 20       # Belohnung für parallele Wege (0°, 180°) - maximaler Wert
    ANGLE_ORTHOGONAL_PENALTY = -100   # Strafe für orthogonale Wege (90°) - minimaler Wert der kontinuierlichen Funktion
    
    # Entfernungs-Priorität Konfiguration
    DISTANCE_MAX_PRIORITY = 15       # Maximale Priorität bei Entfernung 0m
    DISTANCE_REFERENCE = 15          # Referenz-Entfernung in Metern (bei dieser Entfernung = halbe Priorität)
    DISTANCE_WEIGHT_FACTOR = 1.0     # Gewichtungsfaktor für Entfernungseinfluss (1.0 = volle Gewichtung)
    
    # Mindestpriorität für Kandidatenauswahl
    MINIMUM_TOTAL_PRIORITY = -10     # Kandidaten mit Gesamtpriorität unter diesem Wert werden komplett ausgeschlossen
    
    # Überlappungs-Priorität Konfiguration (geometrische Überlappung)
    OVERLAP_MAX_PRIORITY = 10        # Maximale Priorität bei 100% Überlappung (Kandidat passt perfekt zum Segment)
    OVERLAP_MIN_PRIORITY = -10       # Minimale Priorität bei 0% Überlappung (Overshoot: Kandidat ragt komplett am Segment vorbei)


def calculate_overlap_score(segment_geom, candidate_geom):
    """
    Berechnet die geometrische Überlappung zwischen Segment und Kandidat.
    
    Misst, wie viel Prozent des Segments vom Kandidaten "abgedeckt" wird.
    Dies hilft, "Overshoot"-Probleme zu erkennen, wo ein Kandidat zwar parallel verläuft,
    aber das Segment nicht wirklich überlappt (z.B. ein langer Radweg, der weit am Segment vorbeiragt).
    
    Methode:
    1. Projiziere beide Geometrien auf die Segment-Achse (Hauptrichtung)
    2. Berechne die Überlappung der projizierten Intervalle
    3. Normalisiere auf Segment-Länge
    
    Args:
        segment_geom: Geometrie des Netzwerksegments (LineString oder MultiLineString)
        candidate_geom: Geometrie des Kandidaten (LineString oder MultiLineString)
        
    Returns:
        float: Überlappungs-Score (0.0 = keine Überlappung, 1.0 = perfekte Überlappung)
    """
    try:
        from shapely.geometry import LineString, MultiLineString
        
        # Konvertiere MultiLineString zu LineString falls nötig
        if isinstance(segment_geom, MultiLineString):
            segment_coords = []
            for line in segment_geom.geoms:
                segment_coords.extend(list(line.coords))
            segment_line = LineString(segment_coords)
        else:
            segment_line = segment_geom
        
        if isinstance(candidate_geom, MultiLineString):
            candidate_coords = []
            for line in candidate_geom.geoms:
                candidate_coords.extend(list(line.coords))
            candidate_line = LineString(candidate_coords)
        else:
            candidate_line = candidate_geom
        
        # Hole Start- und Endpunkte
        seg_coords = list(segment_line.coords)
        cand_coords = list(candidate_line.coords)
        
        if len(seg_coords) < 2 or len(cand_coords) < 2:
            logging.debug("Zu wenige Koordinaten für Überlappungsberechnung")
            return 0.5  # Neutral
        
        seg_start = np.array(seg_coords[0])
        seg_end = np.array(seg_coords[-1])
        cand_start = np.array(cand_coords[0])
        cand_end = np.array(cand_coords[-1])
        
        # Berechne Segment-Achse (Hauptrichtung)
        seg_vector = seg_end - seg_start
        seg_length = np.linalg.norm(seg_vector)
        
        if seg_length < 0.01:  # Sehr kurzes Segment
            logging.debug("Segment zu kurz für Überlappungsberechnung")
            return 0.5  # Neutral
        
        # Normalisiere Segment-Vektor
        seg_unit = seg_vector / seg_length
        
        # Projiziere alle Punkte auf die Segment-Achse
        # Projektion von Punkt P auf Segment-Achse: (P - seg_start) · seg_unit
        seg_start_proj = 0.0  # Start ist bei 0
        seg_end_proj = seg_length  # Ende ist bei seg_length
        
        # Projiziere Kandidaten-Start und -Ende
        cand_start_proj = np.dot(cand_start - seg_start, seg_unit)
        cand_end_proj = np.dot(cand_end - seg_start, seg_unit)
        
        # Normalisiere: kleinerer Wert zuerst
        cand_min = min(cand_start_proj, cand_end_proj)
        cand_max = max(cand_start_proj, cand_end_proj)
        
        # Berechne Überlappungs-Intervall
        overlap_start = max(seg_start_proj, cand_min)
        overlap_end = min(seg_end_proj, cand_max)
        
        # Überlappungs-Länge (kann negativ sein, wenn keine Überlappung)
        overlap_length = max(0.0, overlap_end - overlap_start)
        
        # Normalisiere auf Segment-Länge
        overlap_score = overlap_length / seg_length
        
        # Begrenze auf [0.0, 1.0]
        overlap_score = max(0.0, min(1.0, overlap_score))
        
        logging.debug(f"Überlappungs-Berechnung: seg=[{seg_start_proj:.2f}, {seg_end_proj:.2f}], "
                     f"cand=[{cand_min:.2f}, {cand_max:.2f}], "
                     f"overlap=[{overlap_start:.2f}, {overlap_end:.2f}], "
                     f"overlap_length={overlap_length:.2f}m, score={overlap_score:.2f}")
        
        return overlap_score
        
    except Exception as e:
        logging.warning(f"Fehler bei Überlappungsberechnung: {e}")
        return 0.5  # Neutral bei Fehler


def is_closed_ring(geom, tolerance=0.01):
    """
    Prüft ob eine Geometrie ein geschlossener Ring ist (z.B. Kreisverkehr).
    
    Args:
        geom: LineString oder MultiLineString
        tolerance: Toleranz in Metern für den Vergleich von Start- und Endpunkt
        
    Returns:
        bool: True wenn es ein geschlossener Ring ist
    """
    try:
        if isinstance(geom, MultiLineString):
            # Bei MultiLineString: Prüfe erste und letzte Koordinate
            first_line = geom.geoms[0]
            last_line = geom.geoms[-1]
            first_coords = list(first_line.coords)
            last_coords = list(last_line.coords)
            
            if len(first_coords) >= 1 and len(last_coords) >= 1:
                p1 = first_coords[0]
                p2 = last_coords[-1]
            else:
                return False
        elif hasattr(geom, 'coords'):
            coords = list(geom.coords)
            if len(coords) >= 2:
                p1, p2 = coords[0], coords[-1]
            else:
                return False
        else:
            return False
        
        # Prüfe Distanz zwischen Start und Ende
        dx = abs(p2[0] - p1[0])
        dy = abs(p2[1] - p1[1])
        distance = np.sqrt(dx**2 + dy**2)
        
        return distance < tolerance
    except Exception as e:
        logging.debug(f"Fehler bei Ring-Erkennung: {e}")
        return False


def calculate_tangent_angle_at_nearest_point(ring_geom, reference_point):
    """
    Berechnet den Tangenten-Winkel an dem Punkt auf dem Ring,
    der dem Referenzpunkt am nächsten ist.
    
    Wird verwendet für Kreisverkehre und andere geschlossene Ringe.
    
    Args:
        ring_geom: Geometrie des Rings (LineString oder MultiLineString)
        reference_point: Punkt (Shapely Point oder Tuple), zu dem die Nähe berechnet wird
        
    Returns:
        float: Winkel der Tangente in Grad (0-360°)
    """
    try:
        # Konvertiere reference_point zu Shapely Point falls nötig
        if not isinstance(reference_point, Point):
            if hasattr(reference_point, '__iter__') and len(reference_point) == 2:
                reference_point = Point(reference_point)
            else:
                logging.warning("Ungültiger Referenzpunkt für Tangentenberechnung")
                return 0.0
        
        # Extrahiere alle Koordinaten vom Ring
        if isinstance(ring_geom, MultiLineString):
            # Sammle alle Koordinaten aus allen Teilen
            all_coords = []
            for line in ring_geom.geoms:
                all_coords.extend(list(line.coords))
        elif hasattr(ring_geom, 'coords'):
            all_coords = list(ring_geom.coords)
        else:
            return 0.0
        
        if len(all_coords) < 3:
            logging.warning("Ring hat zu wenige Koordinaten für Tangentenberechnung")
            return 0.0
        
        # Finde den nächsten Punkt auf dem Ring
        min_distance = float('inf')
        nearest_idx = 0
        
        for i, coord in enumerate(all_coords):
            point = Point(coord)
            dist = reference_point.distance(point)
            if dist < min_distance:
                min_distance = dist
                nearest_idx = i
        
        # Berechne Tangente: Verwende Punkte vor und nach dem nächsten Punkt
        # Für glattere Tangente: Nutze etwas weiter entfernte Punkte wenn möglich
        offset = min(5, len(all_coords) // 10)  # 5 Punkte oder 10% der Ringgröße
        offset = max(1, offset)  # Mindestens 1
        
        # Indizes mit Wrap-Around (Ring ist zyklisch)
        prev_idx = (nearest_idx - offset) % len(all_coords)
        next_idx = (nearest_idx + offset) % len(all_coords)
        
        prev_point = all_coords[prev_idx]
        next_point = all_coords[next_idx]
        
        # Berechne Winkel zwischen vorherigem und nächstem Punkt (Tangente)
        dx = next_point[0] - prev_point[0]
        dy = next_point[1] - prev_point[1]
        
        angle_rad = np.arctan2(dy, dx)
        angle_deg = np.degrees(angle_rad)
        if angle_deg < 0:
            angle_deg += 360
        
        logging.debug(f"Ring-Tangente: nächster Punkt idx={nearest_idx}, "
                     f"Tangente zwischen idx {prev_idx} und {next_idx}, Winkel={angle_deg:.2f}°")
        
        return angle_deg
        
    except Exception as e:
        logging.warning(f"Fehler bei Tangentenberechnung für Ring: {e}")
        return 0.0


def calculate_line_angle(geom, reference_geom=None):
    """
    Berechnet den Winkel einer Linie in Grad (0-360°).
    Behandelt MultiLineString und geschlossene Ringe (Kreisverkehre) korrekt.
    
    Args:
        geom: Geometrie (LineString oder MultiLineString)
        reference_geom: Optional - Referenzgeometrie für Kreisverkehre.
                       Bei geschlossenen Ringen wird die Tangente am nächsten Punkt berechnet.
    
    Returns:
        float: Winkel in Grad (0-360°)
    """
    # Prüfe ob es ein geschlossener Ring ist (z.B. Kreisverkehr)
    if is_closed_ring(geom):
        logging.debug("Geschlossener Ring erkannt (z.B. Kreisverkehr)")
        
        if reference_geom is not None:
            # Berechne Tangente am nächsten Punkt zum Referenz-Segment
            if isinstance(reference_geom, (LineString, MultiLineString)):
                # Nutze Mittelpunkt des Referenz-Segments
                reference_point = reference_geom.interpolate(0.5, normalized=True)
            elif isinstance(reference_geom, Point):
                reference_point = reference_geom
            else:
                # Fallback: Nutze Zentroid
                try:
                    reference_point = reference_geom.centroid
                except:
                    reference_point = None
            
            if reference_point is not None:
                angle = calculate_tangent_angle_at_nearest_point(geom, reference_point)
                logging.debug(f"Ring-Winkel mit Referenz: {angle:.2f}°")
                return angle
        
        # Fallback: Nutze Mittelpunkt des Rings als Referenz
        try:
            ring_centroid = geom.centroid
            # Finde einen Punkt auf dem Ring und berechne Tangente dort
            if isinstance(geom, MultiLineString):
                first_line = geom.geoms[0]
                if len(list(first_line.coords)) > 0:
                    reference_point = Point(list(first_line.coords)[len(list(first_line.coords))//2])
                else:
                    reference_point = ring_centroid
            else:
                coords = list(geom.coords)
                if len(coords) > 0:
                    reference_point = Point(coords[len(coords)//2])
                else:
                    reference_point = ring_centroid
            
            angle = calculate_tangent_angle_at_nearest_point(geom, reference_point)
            logging.debug(f"Ring-Winkel ohne Referenz (Mittelpunkt): {angle:.2f}°")
            return angle
        except Exception as e:
            logging.warning(f"Fehler bei Ring-Fallback-Berechnung: {e}")
            # Letzter Fallback: 0°
            return 0.0
    
    # Normale Linien: Standard-Berechnung (Start -> Ende)
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
    Verwendung einer progressiven quadratischen Funktion mit Nullpunkt bei 45°.
    
    Mathematische Funktion:
    prio_angle(θ) = { 20 · (1 - θ/45)           für 0° ≤ θ ≤ 45°
                    { -80 · ((θ-45)/45)²        für 45° < θ ≤ 90°
    
    wobei θ der normalisierte Winkel im Bereich [0°, 90°] ist.
    
    Bewertung:
    - 0° (parallel): +20 Punkte (ANGLE_PARALLEL_REWARD)
    - 45° (diagonal): 0 Punkte (Nullpunkt)
    - 50°: ca. -2 Punkte
    - 80°: ca. -45 Punkte
    - 90° (orthogonal): -80 Punkte (ANGLE_ORTHOGONAL_PENALTY)
    
    Args:
        segment_geom: Geometrie des Netzwerksegments
        candidate_geom: Geometrie des Kandidaten
        
    Returns:
        float: Winkel-Priorität (-80 bis +20)
    """
    segment_angle = calculate_line_angle(segment_geom)
    # Bei Kreisverkehren: Übergebe Segment als Referenz für Tangentenberechnung
    candidate_angle = calculate_line_angle(candidate_geom, reference_geom=segment_geom)
    
    angle_diff = angle_difference(segment_angle, candidate_angle)
    
    # Normalisiere auf 0-90° (wir betrachten nur den kleinsten Winkel)
    normalized_angle = min(angle_diff, 180 - angle_diff)
    
    # Berechne progressive Priorität mit Nullpunkt bei 45°
    # Für 0° bis 45°: Linear von PARALLEL_REWARD bis 0
    # Für 45° bis 90°: Quadratisch von 0 bis ORTHOGONAL_PENALTY
    
    if normalized_angle <= 45:
        # Bereich 0° - 45°: Linear abfallend von +20 bis 0
        # Bei 0° → +20, bei 45° → 0
        angle_priority = SnappingPriorities.ANGLE_PARALLEL_REWARD * (1 - normalized_angle / 45)
    else:
        # Bereich 45° - 90°: Quadratisch abfallend von 0 bis -40
        # Normalisiere auf 0-1 Bereich für den 45°-90° Abschnitt
        t = (normalized_angle - 45) / 45  # 0 bei 45°, 1 bei 90°
        # Quadratische Progression: t² macht den Abfall stärker bei größeren Winkeln
        angle_priority = SnappingPriorities.ANGLE_ORTHOGONAL_PENALTY * (t ** 2)
    
    # Runde auf zwei Nachkommastellen
    angle_priority = round(angle_priority, 2)
    
    logging.debug(f"Winkel-Priorität: {angle_diff:.2f}° → normalized={normalized_angle:.2f}° → {angle_priority:.2f} Punkte (progressiv: 0°=+20, 45°=0, 90°=-40)")
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
    
    # Runde auf zwei Nachkommastellen
    distance_priority = round(distance_priority, 2)
    
    logging.debug(f"Entfernungs-Priorität: {distance:.2f}m → {distance_priority:.2f} Punkte")
    return distance_priority


def calculate_overlap_priority(segment_geom, candidate_geom):
    """
    Berechnet die Überlappungs-Priorität basierend auf der geometrischen Überlappung.
    
    Verwendet calculate_overlap_score() um zu messen, wie gut der Kandidat zum Segment passt.
    Hohe Überlappung = hohe Priorität (der Kandidat "gehört" zum Segment)
    Niedrige Überlappung = niedrige Priorität (Overshoot: Kandidat ragt am Segment vorbei)
    
    Mathematische Funktion (lineare Skalierung):
    overlap_priority = OVERLAP_MIN_PRIORITY + overlap_score × (OVERLAP_MAX_PRIORITY - OVERLAP_MIN_PRIORITY)
    overlap_priority = -20 + overlap_score × 40
    
    Bewertung:
    - 0% Überlappung (score=0.0): -20 Punkte (kompletter Overshoot)
    - 50% Überlappung (score=0.5): 0 Punkte (neutral)  
    - 100% Überlappung (score=1.0): +20 Punkte (perfekte Abdeckung)
    
    Args:
        segment_geom: Geometrie des Netzwerksegments
        candidate_geom: Geometrie des Kandidaten
        
    Returns:
        float: Überlappungs-Priorität (OVERLAP_MIN_PRIORITY bis OVERLAP_MAX_PRIORITY)
    """
    overlap_score = calculate_overlap_score(segment_geom, candidate_geom)
    
    # Lineare Skalierung von overlap_score (0.0-1.0) auf Prioritätsbereich
    # overlap_score = 0.0 → OVERLAP_MIN_PRIORITY
    # overlap_score = 1.0 → OVERLAP_MAX_PRIORITY
    overlap_priority = (SnappingPriorities.OVERLAP_MIN_PRIORITY + 
                       overlap_score * (SnappingPriorities.OVERLAP_MAX_PRIORITY - 
                                       SnappingPriorities.OVERLAP_MIN_PRIORITY))
    
    # Runde auf zwei Nachkommastellen
    overlap_priority = round(overlap_priority, 2)
    
    logging.debug(f"Überlappungs-Priorität: score={overlap_score:.2f} → {overlap_priority:.2f} Punkte "
                 f"(0%={SnappingPriorities.OVERLAP_MIN_PRIORITY}, 100%={SnappingPriorities.OVERLAP_MAX_PRIORITY})")
    return overlap_priority


def determine_segment_direction(segment_geom, osm_geom) -> int:
    """
    Bestimmt die Richtung (ri) eines Segments basierend auf der Ausrichtung
    zwischen dem Segment und dem passenden OSM-Weg.
    
    Bei Kreisverkehren wird die Tangente am nächsten Punkt verwendet.
    
    Args:
        segment_geom: Geometrie des Netzwerksegments
        osm_geom: Geometrie des OSM-Wegs
        
    Returns:
        int: 0 für Hinrichtung (gleiche Richtung), 1 für Rückrichtung (entgegengesetzte Richtung)
    """
    segment_angle = calculate_line_angle(segment_geom)
    # Bei Kreisverkehren: Übergebe Segment als Referenz für Tangentenberechnung
    osm_angle = calculate_line_angle(osm_geom, reference_geom=segment_geom)
    
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
        # Wenn nur einer leer ist: Prüfe ob es Radinfrastruktur ist
        else:
            # Prüfe ob Kandidat Radinfrastruktur ist (diese haben oft keinen Namen in OSM)
            category_str = str(category) if category else ""
            is_radinfra = (
                category_str.startswith("cycleway") or 
                category_str.startswith("footAndCycleway") or
                category_str.startswith("footwayBicycle") or
                category_str.startswith("bicycleRoad")
            )
            
            if is_radinfra:
                # Radinfrastruktur ohne Namen: Neutral bewerten (keine Strafe)
                street_name_priority = 0
                street_name_detail = f"radinfra_ohne_name(segment:'{segment_strassenname}',tilda:'{tilda_name}')"
            else:
                # Andere Wege ohne Namen: Neutral bewerten (keine Strafe, aber auch keine Belohnung)
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
    
    # Info-Logging bei ri_value=None (normal bei Sonderfällen)
    if ri_value is None:
        logging.debug(f"find_best_candidate_for_direction mit ri_value=None aufgerufen - "
                     f"Suche besten Kandidaten unabhängig von Richtung (Sonderfall-Behandlung)")
    
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
    
    # Berechne Überlappungs-Priorität für alle Kandidaten
    candidates["priority_overlap"] = 0.0
    for idx, candidate in candidates.iterrows():
        overlap_prio = calculate_overlap_priority(segment_geom, candidate.geometry)
        candidates.at[idx, "priority_overlap"] = overlap_prio
        # Füge priority_overlap zu priority_details hinzu
        if idx in priority_details:
            priority_details[idx]['priority_overlap'] = overlap_prio
            priority_details[idx]['overlap_score'] = calculate_overlap_score(segment_geom, candidate.geometry)
    
    # Berechne Richtungskompatibilität für jeden Kandidaten
    candidates["direction_compatibility"] = 0
    
    # Logge Segmentwinkel für Debugging - verwende übergebenen Winkel falls vorhanden
    if segment_angle is None:
        segment_angle = calculate_line_angle(segment_geom)
    logging.debug(f"Segment element_nr={element_nr}: Winkel={segment_angle:.2f}°")
    
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
                         f"Winkel={candidate_angle:.2f}°, segment_direction={segment_direction}, "
                         f"ri_value={ri_value}")
            
            # Wenn ri_value None ist, behandle es als "beste verfügbare Richtung"
            if ri_value is None:
                # Für den Fall, dass wir den besten Kandidaten UNABHÄNGIG von der Richtung suchen
                # (z.B. bei Sonderfällen wo nur Mischverkehr vorhanden ist)
                # Vergeben wir die perfekte Bewertung, da die Richtung später richtig gesetzt wird
                candidates.at[idx, "direction_compatibility"] = SnappingPriorities.DIRECTION_PERFECT_MATCH
                logging.debug(f"    → ri_value=None (Sonderfall): Vergebe DIRECTION_PERFECT_MATCH={SnappingPriorities.DIRECTION_PERFECT_MATCH}, da Richtung später korrekt gesetzt wird")
            elif segment_direction == ri_value:
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
                         f"Winkel={candidate_angle:.2f}°, direction_compatibility={SnappingPriorities.DIRECTION_BIDIRECTIONAL}")
    
    # Berechne Gesamt-Priorität: TILDA-Inhalt + Winkel + Entfernung + Überlappung + Richtungskompatibilität
    candidates["total_priority_weighted"] = (
        candidates["priority"] +           # TILDA-Priorität (Inhalt)
        candidates["angle_priority"] +     # Winkel-Priorität (beinhaltet Richtungsausrichtung)
        candidates["distance_priority"] +  # Entfernungs-Priorität
        candidates["priority_overlap"] +   # Überlappungs-Priorität (verhindert Overshoot)
        candidates["direction_compatibility"] # Richtungskompatibilität
    ).round(2)  # Runde auf zwei Nachkommastellen
    
    # Sortiere ALLE Kandidaten nach gewichteter Gesamtpriorität (TILDA + Winkel + Entfernung)
    # Die Winkel-Priorität beinhaltet bereits die Richtungsausrichtung
    all_candidates_sorted = candidates.sort_values(
        ["total_priority_weighted"], 
        ascending=[False]
    )
    
    # Filtere Kandidaten mit zu niedriger Gesamtpriorität aus
    # Dies ist eine harte untere Grenze für die Wegqualität (inkl. geometrische und Richtungskompatibilität)
    initial_candidate_count = len(candidates)
    quality_candidates = all_candidates_sorted[all_candidates_sorted["total_priority_weighted"] >= SnappingPriorities.MINIMUM_TOTAL_PRIORITY]
    
    if len(quality_candidates) == 0:
        logging.debug(f"Alle {initial_candidate_count} Kandidaten für ri={ri_value} haben Gesamtpriorität < {SnappingPriorities.MINIMUM_TOTAL_PRIORITY} - KEIN WEG WIRD AUSGEWÄHLT")
        # Gib trotzdem alle Kandidaten mit ihren Prioritäten zurück (für Debugging)
        # aber signalisiere mit None-Result, dass kein Kandidat übernommen wird
        return None, all_candidates_sorted
    elif len(quality_candidates) < initial_candidate_count:
        filtered_count = initial_candidate_count - len(quality_candidates)
        logging.debug(f"Filtere {filtered_count} Kandidaten mit Gesamtpriorität < {SnappingPriorities.MINIMUM_TOTAL_PRIORITY} aus ({len(quality_candidates)} Kandidaten verbleiben)")
        candidates = quality_candidates
    else:
        candidates = quality_candidates
    
    # Logge die Sortierreihenfolge mit detaillierten Prioritäten
    if len(candidates) > 0:
        best_candidate = candidates.iloc[0]
        logging.debug(f"=== BESTE KANDIDATEN-BEWERTUNG für ri={ri_value} ===")
        logging.debug(f"Bester Kandidat: {best_candidate.get('tilda_id', 'unknown')}")
        logging.debug(f"  → Gewichtete_Gesamtpriorität: {best_candidate.get('total_priority_weighted', -1):.2f}")
        logging.debug(f"    ├─ TILDA_Priority: {best_candidate.get('priority', -1)}")
        logging.debug(f"    ├─ Angle_Priority: {best_candidate.get('angle_priority', -1):.2f}")
        logging.debug(f"    ├─ Distance_Priority: {best_candidate.get('distance_priority', -1):.2f} (bei {best_candidate.get('dist_to_mid', -1):.2f}m)")
        logging.debug(f"    ├─ Overlap_Priority: {best_candidate.get('priority_overlap', -1):.2f}")
        logging.debug(f"    └─ Direction_Compatibility: {best_candidate.get('direction_compatibility', -1)}")
        
        # Logge auch die anderen Kandidaten zur Nachvollziehbarkeit
        if len(candidates) > 1:
            logging.debug("=== ALLE KANDIDATEN (sortiert nach gewichteter Priorität) ===")
            for i, (_, cand) in enumerate(candidates.iterrows()):
                marker = "★ GEWÄHLT" if i == 0 else f"  {i+1}."
                logging.debug(f"{marker} {cand.get('tilda_id', 'unknown')}: "
                             f"total_weighted={cand.get('total_priority_weighted', -1):.2f} "
                             f"(tilda={cand.get('priority', -1)}, angle={cand.get('angle_priority', -1):.2f}, "
                             f"dist={cand.get('distance_priority', -1):.2f}@{cand.get('dist_to_mid', -1):.2f}m, "
                             f"overlap={cand.get('priority_overlap', -1):.2f}, "
                             f"dir={cand.get('direction_compatibility', -1)})")
    
    # Wähle den besten Kandidaten und füge detaillierte Prioritätsinformationen hinzu
    if len(candidates) > 0:
        best_candidate_dict = candidates.iloc[0].to_dict()
        best_idx = candidates.iloc[0].name  # Index des besten Kandidaten
        if best_idx in priority_details:
            best_candidate_dict['priority_details'] = priority_details[best_idx]
        return best_candidate_dict, all_candidates_sorted
    else:
        return None, all_candidates_sorted
