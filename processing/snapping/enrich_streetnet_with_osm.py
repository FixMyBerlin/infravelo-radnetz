#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
enrich_streetnet_with_osm.py
--------------------------------------------------------------------
Überträgt OSM-Attribute auf ein topologisches Richtungs-Straßennetz
– MultiLineStrings werden korrekt behandelt
– feste Feldnamen:
      element_nr         = Edge-ID
      beginnt_bei_vp     = From-Node
      endet_bei_vp       = To-Node
      verkehrsrichtung   = R / G / B
--------------------------------------------------------------------
"""
import argparse, sys
from pathlib import Path

import numpy as np
import geopandas as gpd
from shapely.geometry import LineString, MultiLineString, Point, MultiPoint
from helpers.progressbar import print_progressbar
from helpers.globals import DEFAULT_CRS
import math


# -------------------------------------------------------------- Konstanten --
BUFFER_DEFAULT = 20.0     # Standard-Puffergröße in Metern für Matching

# Feldnamen für das Netz
FLD_EDGE = "element_nr"           # Kanten-ID
FLD_FROM = "beginnt_bei_vp"       # Startknoten-ID
FLD_TO   = "endet_bei_vp"         # Endknoten-ID
FLD_DIR  = "verkehrsrichtung"     # Werte: R / G / B (Richtung)


# --------------------------------------------------------- Hilfsfunktionen --
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


def reverse_geom(g):
    """
    Kehrt die Richtung einer Geometrie um.
    """
    if isinstance(g, LineString):
        return LineString(reversed(g.coords))
    if isinstance(g, MultiLineString):
        return MultiLineString([reverse_geom(line) for line in g.geoms])
    raise TypeError(f"Geometry {g.geom_type} nicht unterstützt")


def direction_from_verkehrsrichtung(verkehrsrichtung):
    """
    Ermittelt die Richtung aus dem Verkehrsrichtungs-Attribut.
    R = Richtung der Geometrie, G = Gegenrichtung, B = Beide Richtungen
    """
    if verkehrsrichtung == 'R':
        return 'forward'
    elif verkehrsrichtung == 'G':
        return 'backward'
    elif verkehrsrichtung == 'B':
        return 'both'
    else:
        return 'unknown'


def build_spatial_index(gdf):
    """
    Erstellt einen räumlichen Index für ein GeoDataFrame.
    """
    return gdf.sindex


def find_matching_osm_features(network_geom, osm_gdf, osm_sindex, buffer_distance):
    """
    Findet OSM-Features, die mit einer Netzwerk-Geometrie übereinstimmen.
    """
    # Puffer um Netzwerk-Geometrie
    buffered_geom = network_geom.buffer(buffer_distance)
    
    # Räumliche Abfrage über Index
    possible_matches_idx = list(osm_sindex.intersection(buffered_geom.bounds))
    
    if not possible_matches_idx:
        return gpd.GeoDataFrame()
    
    # Prüfe tatsächliche Intersection
    possible_matches = osm_gdf.iloc[possible_matches_idx]
    intersecting_features = possible_matches[possible_matches.intersects(buffered_geom)]
    
    return intersecting_features


def transfer_osm_attributes(network_row, osm_matches, max_angle_diff=35.0):
    """
    Überträgt OSM-Attribute auf eine Netzwerk-Kante.
    Berücksichtigt dabei sowohl die Überschneidungslänge als auch die Ausrichtung der Segmente.
    """
    if osm_matches.empty:
        return network_row
    
    # Sammle alle kompatiblen Matches mit ihren Bewertungen
    compatible_matches = []
    network_geom = network_row.geometry
    
    for _, osm_row in osm_matches.iterrows():
        osm_geom = osm_row.geometry
        intersection = network_geom.intersection(osm_geom)
        
        if intersection.is_empty:
            continue
        
        # Berechne Überschneidungslänge
        if hasattr(intersection, 'length'):
            intersection_length = intersection.length
        else:
            intersection_length = 0
        
        # Prüfe Ausrichtungskompatibilität
        is_compatible, angle_diff = is_alignment_compatible(network_geom, osm_geom, max_angle_diff)
        
        if is_compatible:
            # Bewertung: Kombination aus Überschneidungslänge und Winkelgenauigkeit
            # Je kleiner der Winkelunterschied, desto besser die Bewertung
            angle_score = (max_angle_diff - angle_diff) / max_angle_diff  # 0-1, höher ist besser
            
            # Kombiniere Länge und Winkel-Score (beide gleichgewichtet)
            combined_score = intersection_length * (1 + angle_score)
            
            compatible_matches.append({
                'osm_row': osm_row,
                'intersection_length': intersection_length,
                'angle_diff': angle_diff,
                'combined_score': combined_score
            })
    
    # Wähle das beste Match basierend auf der kombinierten Bewertung
    if compatible_matches:
        best_match_info = max(compatible_matches, key=lambda x: x['combined_score'])
        best_match = best_match_info['osm_row']
        
        enriched_row = network_row.copy()
        
        # Übertrage relevante OSM-Attribute
        osm_attributes = ['highway', 'name', 'maxspeed', 'lanes', 'surface', 'cycleway', 'cycleway:left', 'cycleway:right']
        
        for attr in osm_attributes:
            if attr in best_match.index:
                enriched_row[f'osm_{attr}'] = best_match[attr]
        
        # Zusätzliche Metadaten für Debugging
        enriched_row['match_length'] = best_match_info['intersection_length']
        enriched_row['match_angle_diff'] = best_match_info['angle_diff']
        enriched_row['match_score'] = best_match_info['combined_score']
        
        return enriched_row
    
    return network_row


def process_network_edges(network_gdf, osm_gdf, buffer_distance=BUFFER_DEFAULT, max_angle_diff=35.0):
    """
    Verarbeitet alle Kanten des Netzwerks und reichert sie mit OSM-Attributen an.
    
    Args:
        network_gdf: Netzwerk-GeoDataFrame
        osm_gdf: OSM-GeoDataFrame
        buffer_distance: Puffergröße für räumliche Suche
        max_angle_diff: Maximaler erlaubter Winkelunterschied in Grad
    """
    print(f"Verarbeite {len(network_gdf)} Netzwerk-Kanten...")
    print(f"Verwende Puffergröße: {buffer_distance}m, max. Winkelunterschied: {max_angle_diff}°")
    
    # Räumlicher Index für OSM-Daten
    osm_sindex = build_spatial_index(osm_gdf)
    
    enriched_rows = []
    
    for idx, (_, network_row) in enumerate(network_gdf.iterrows()):
        # Fortschrittsanzeige
        if idx % 100 == 0:
            print_progressbar(idx + 1, len(network_gdf), prefix='Anreicherung: ', length=50)
        
        # Finde passende OSM-Features
        osm_matches = find_matching_osm_features(
            network_row.geometry, 
            osm_gdf, 
            osm_sindex, 
            buffer_distance
        )
        
        # Übertrage Attribute mit Winkelprüfung
        enriched_row = transfer_osm_attributes(network_row, osm_matches, max_angle_diff)
        enriched_rows.append(enriched_row)
    
    # Abschluss der Fortschrittsanzeige
    print_progressbar(len(network_gdf), len(network_gdf), prefix='Anreicherung: ', length=50)
    
    # Erstelle angereichertes GeoDataFrame
    enriched_gdf = gpd.GeoDataFrame(enriched_rows, crs=network_gdf.crs)
    
    return enriched_gdf


def enrich_network_with_osm(network_path, osm_path, output_path, buffer_distance=BUFFER_DEFAULT, max_angle_diff=35.0):
    """
    Hauptfunktion zur Anreicherung des Straßennetzes mit OSM-Daten.
    
    Args:
        network_path: Pfad zur Netzwerk-Datei
        osm_path: Pfad zur OSM-Datei
        output_path: Pfad für die Ausgabe-Datei
        buffer_distance: Puffergröße für räumliche Suche
        max_angle_diff: Maximaler erlaubter Winkelunterschied in Grad
    """
    print(f"Lade Straßennetz aus: {network_path}")
    network_gdf = gpd.read_file(network_path)
    print(f"Geladen: {len(network_gdf)} Netzwerk-Kanten")
    
    print(f"Lade OSM-Daten aus: {osm_path}")
    osm_gdf = gpd.read_file(osm_path)
    print(f"Geladen: {len(osm_gdf)} OSM-Features")
    
    # Koordinatensystem prüfen
    target_crs = f"EPSG:{DEFAULT_CRS}"
    if network_gdf.crs != target_crs:
        network_gdf = network_gdf.to_crs(target_crs)
    if osm_gdf.crs != target_crs:
        osm_gdf = osm_gdf.to_crs(target_crs)
    
    # Anreicherung durchführen
    enriched_gdf = process_network_edges(network_gdf, osm_gdf, buffer_distance, max_angle_diff)
    
    # Ergebnis speichern
    print(f"Speichere angereichertes Netz: {output_path}")
    enriched_gdf.to_file(output_path, driver='FlatGeobuf')
    
    print("Anreicherung abgeschlossen.")
    return enriched_gdf


def main():
    """
    Hauptfunktion für die Kommandozeilenanwendung.
    """
    parser = argparse.ArgumentParser(description='Anreicherung des Straßennetzes mit OSM-Attributen')
    parser.add_argument('network_path', help='Pfad zur Netzwerk-Datei')
    parser.add_argument('osm_path', help='Pfad zur OSM-Datei')
    parser.add_argument('output_path', help='Pfad für die Ausgabe-Datei')
    parser.add_argument('--buffer', type=float, default=BUFFER_DEFAULT, 
                        help=f'Puffergröße in Metern (Standard: {BUFFER_DEFAULT})')
    parser.add_argument('--max-angle', type=float, default=35.0,
                        help='Maximaler erlaubter Winkelunterschied in Grad (Standard: 35.0)')
    
    args = parser.parse_args()
    
    # Prüfe Eingabedateien
    if not Path(args.network_path).exists():
        print(f"Fehler: Netzwerk-Datei nicht gefunden: {args.network_path}")
        sys.exit(1)
    
    if not Path(args.osm_path).exists():
        print(f"Fehler: OSM-Datei nicht gefunden: {args.osm_path}")
        sys.exit(1)
    
    # Führe Anreicherung durch
    enrich_network_with_osm(args.network_path, args.osm_path, args.output_path, 
                           args.buffer, args.max_angle)


if __name__ == "__main__":
    main()


def calculate_line_bearing(line_geom):
    """
    Berechnet die Ausrichtung (Bearing) einer Linie in Grad.
    
    Args:
        line_geom: LineString-Geometrie
        
    Returns:
        float: Ausrichtung in Grad (0-360)
    """
    if isinstance(line_geom, MultiLineString):
        # Für MultiLineString nimm die erste Linie
        if len(line_geom.geoms) > 0:
            line_geom = line_geom.geoms[0]
        else:
            return 0.0
    
    if not isinstance(line_geom, LineString) or len(line_geom.coords) < 2:
        return 0.0
    
    # Nimm Start- und Endpunkt der Linie
    start_point = line_geom.coords[0]
    end_point = line_geom.coords[-1]
    
    # Berechne Differenzen
    dx = end_point[0] - start_point[0]
    dy = end_point[1] - start_point[1]
    
    # Berechne Winkel in Radiant und konvertiere zu Grad
    angle_rad = math.atan2(dy, dx)
    angle_deg = math.degrees(angle_rad)
    
    # Normalisiere auf 0-360 Grad
    if angle_deg < 0:
        angle_deg += 360
    
    return angle_deg


def calculate_angle_difference(bearing1, bearing2):
    """
    Berechnet den minimalen Winkelunterschied zwischen zwei Ausrichtungen.
    Berücksichtigt dabei auch die umgekehrte Richtung (bearing + 180°).
    
    Args:
        bearing1: Ausrichtung 1 in Grad
        bearing2: Ausrichtung 2 in Grad
        
    Returns:
        float: Minimaler Winkelunterschied in Grad (0-90)
    """
    # Berechne direkte Differenz
    diff = abs(bearing1 - bearing2)
    
    # Normalisiere auf 0-180 Grad
    if diff > 180:
        diff = 360 - diff
    
    # Berechne auch die umgekehrte Richtung (bearing2 + 180°)
    bearing2_reversed = (bearing2 + 180) % 360
    diff_reversed = abs(bearing1 - bearing2_reversed)
    
    if diff_reversed > 180:
        diff_reversed = 360 - diff_reversed
    
    # Nimm den kleineren Winkel
    min_diff = min(diff, diff_reversed)
    
    return min_diff


def is_alignment_compatible(network_geom, osm_geom, max_angle_diff=35.0):
    """
    Prüft, ob die Ausrichtung zweier Geometrien kompatibel ist.
    
    Args:
        network_geom: Netzwerk-Geometrie
        osm_geom: OSM-Geometrie
        max_angle_diff: Maximaler erlaubter Winkelunterschied in Grad
        
    Returns:
        tuple: (is_compatible, angle_difference)
    """
    network_bearing = calculate_line_bearing(network_geom)
    osm_bearing = calculate_line_bearing(osm_geom)
    
    angle_diff = calculate_angle_difference(network_bearing, osm_bearing)
    
    is_compatible = angle_diff <= max_angle_diff
    
    return is_compatible, angle_diff
