#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
assign_element_nr_to_rvn.py
--------------------------------------------------------------------
Erstellt element_nr-Attribute für das Berliner Radvorrangsnetz basierend
auf den Verbindungspunkten. Die element_nr besteht aus beginnt_bei_vp und
endet_bei_vp im Format: (beginnt_bei_vp)_(endet_bei_vp).01

Das Modul sucht an den Endpunkten der Kanten nach Knotenpunkten und weist
die entsprechenden IDs zu. Falls kein direkter Knotenpunkt gefunden wird,
werden Linien in die entsprechende Richtung gemergt und die Suche wiederholt.

INPUT:
- data/Berlin Radvorrangsnetz.fgb
- output/knotenpunkte/knotenpunkte_mit_id.gpkg

OUTPUT:
- output/rvn/Berlin Vorrangnetz_with_element_nr.fgb
"""

import geopandas as gpd
import pandas as pd
import logging
import os
from shapely.geometry import Point, LineString
from shapely.ops import linemerge
import networkx as nx
from helpers.globals import DEFAULT_CRS, DEFAULT_OUTPUT_DIR

# TODO Some element_nr have UNKOWN or NONE in the ID, this should be fixed

# Logging konfigurieren
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def load_data(radvorrangsnetz_path, knotenpunkte_path):
    """
    Lädt das Radvorrangsnetz und die Knotenpunkte.
    
    Args:
        radvorrangsnetz_path (str): Pfad zum Radvorrangsnetz
        knotenpunkte_path (str): Pfad zu den Knotenpunkten mit IDs
        
    Returns:
        tuple: (rvn_gdf, nodes_gdf) GeoDataFrames
    """
    logging.info(f"Lade Radvorrangsnetz von {radvorrangsnetz_path}")
    rvn_gdf = gpd.read_file(radvorrangsnetz_path)
    
    logging.info(f"Lade Knotenpunkte von {knotenpunkte_path}")
    nodes_gdf = gpd.read_file(knotenpunkte_path)
    
    # Sicherstellen, dass beide Datensätze das gleiche CRS haben
    target_crs = f'EPSG:{DEFAULT_CRS}'
    if rvn_gdf.crs != target_crs:
        logging.info(f"Projiziere Radvorrangsnetz auf {target_crs}")
        rvn_gdf = rvn_gdf.to_crs(target_crs)
        
    if nodes_gdf.crs != target_crs:
        logging.info(f"Projiziere Knotenpunkte auf {target_crs}")
        nodes_gdf = nodes_gdf.to_crs(target_crs)
    
    logging.info(f"Radvorrangsnetz geladen: {len(rvn_gdf)} Segmente")
    logging.info(f"Knotenpunkte geladen: {len(nodes_gdf)} Punkte")
    
    return rvn_gdf, nodes_gdf


def find_node_at_point(point, nodes_gdf, tolerance=1.0):
    """
    Findet den nächstgelegenen Knotenpunkt zu einem gegebenen Punkt.
    
    Args:
        point (Point): Punkt, an dem nach einem Knotenpunkt gesucht wird
        nodes_gdf (GeoDataFrame): GeoDataFrame mit Knotenpunkten
        tolerance (float): Suchtoleranz in Metern
        
    Returns:
        str or None: Knotenpunkt-ID falls gefunden, sonst None
    """
    # Erstelle einen Buffer um den Punkt
    point_buffer = point.buffer(tolerance)
    
    # Finde alle Knotenpunkte innerhalb des Buffers
    intersecting_nodes = nodes_gdf[nodes_gdf.geometry.intersects(point_buffer)]
    
    if len(intersecting_nodes) > 0:
        # Nimm den nächstgelegenen Knotenpunkt
        distances = intersecting_nodes.geometry.distance(point)
        closest_idx = distances.idxmin()
        node_id = intersecting_nodes.loc[closest_idx, 'Knotenpunkt‐ID']
        return str(node_id)
    
    return None


def get_line_endpoints(line_geom):
    """
    Extrahiert Start- und Endpunkt einer Linie.
    Behandelt sowohl SingleLineString als auch MultiLineString-Geometrien.
    
    Args:
        line_geom (LineString oder MultiLineString): Liniengeometrie
        
    Returns:
        tuple: (start_point, end_point) als Point-Objekte
    """
    from shapely.geometry import MultiLineString
    
    if isinstance(line_geom, MultiLineString):
        # Bei MultiLineString nehme den ersten und letzten Punkt aller Teillinien
        all_coords = []
        for line_part in line_geom.geoms:
            all_coords.extend(list(line_part.coords))
        
        start_point = Point(all_coords[0])
        end_point = Point(all_coords[-1])
    else:
        # SingleLineString
        coords = list(line_geom.coords)
        start_point = Point(coords[0])
        end_point = Point(coords[-1])
    
    return start_point, end_point


def create_network_graph(rvn_gdf):
    """
    Erstellt einen NetworkX-Graph aus dem Radvorrangsnetz für die Pfadfindung.
    Behandelt sowohl SingleLineString als auch MultiLineString-Geometrien.
    
    Args:
        rvn_gdf (GeoDataFrame): Radvorrangsnetz
        
    Returns:
        nx.Graph: NetworkX-Graph
    """
    from shapely.geometry import MultiLineString
    
    G = nx.Graph()
    
    for idx, row in rvn_gdf.iterrows():
        try:
            start_point, end_point = get_line_endpoints(row.geometry)
            
            # Konvertiere Punkte zu Tupeln für NetworkX
            start_coord = (start_point.x, start_point.y)
            end_coord = (end_point.x, end_point.y)
            
            # Füge Kante zum Graph hinzu
            G.add_edge(start_coord, end_coord, segment_id=idx, geometry=row.geometry)
        except Exception as e:
            logging.warning(f"Fehler beim Verarbeiten von Segment {idx}: {e}")
            continue
    
    logging.info(f"NetworkX-Graph erstellt mit {len(G.nodes)} Knoten und {len(G.edges)} Kanten")
    return G



def assign_element_numbers(rvn_gdf, nodes_gdf):
    """
    Weist jedem Segment im Radvorrangsnetz eine element_nr zu.
    Optimierte Version, die den Graph nur einmal erstellt.
    
    Args:
        rvn_gdf (GeoDataFrame): Radvorrangsnetz
        nodes_gdf (GeoDataFrame): Knotenpunkte mit IDs
        
    Returns:
        GeoDataFrame: Anreichertes Radvorrangsnetz mit element_nr
    """
    logging.info("Starte Zuweisung der Element-Nummern (optimiert)...")
    
    # Kopiere das DataFrame
    result_gdf = rvn_gdf.copy()
    
    # Initialisiere neue Spalten
    result_gdf['beginnt_bei_vp'] = None
    result_gdf['endet_bei_vp'] = None
    result_gdf['element_nr'] = None
    
    # Erstelle NetworkX-Graph nur einmal
    logging.info("Erstelle NetworkX-Graph...")
    G = create_network_graph(rvn_gdf)
    
    processed_segments = set()
    element_counter = 1
    
    for idx in range(len(result_gdf)):
        if idx in processed_segments:
            continue
            
        if idx % 100 == 0:
            logging.info(f"Verarbeite Segment {idx + 1} von {len(result_gdf)}")
        
        # Finde Endpunkte des aktuellen Segments
        current_segment = rvn_gdf.iloc[idx]
        start_point, end_point = get_line_endpoints(current_segment.geometry)
        
        # Prüfe beide Endpunkte auf Knotenpunkte
        start_node_id = find_node_at_point(start_point, nodes_gdf)
        end_node_id = find_node_at_point(end_point, nodes_gdf)
        
        # Initialisiere die verbundenen Segmente mit dem aktuellen Segment
        connected_segments = [idx]
        beginnt_bei_vp = start_node_id
        endet_bei_vp = end_node_id
        
        # Wenn am Startpunkt kein Knotenpunkt ist, gehe rückwärts
        if not start_node_id:
            start_coord = (start_point.x, start_point.y)
            backward_segments, backward_node = explore_direction(
                G, start_coord, idx, rvn_gdf, nodes_gdf, processed_segments
            )
            connected_segments.extend(backward_segments)
            beginnt_bei_vp = backward_node
        
        # Wenn am Endpunkt kein Knotenpunkt ist, gehe vorwärts
        if not end_node_id:
            end_coord = (end_point.x, end_point.y)
            forward_segments, forward_node = explore_direction(
                G, end_coord, idx, rvn_gdf, nodes_gdf, processed_segments
            )
            connected_segments.extend(forward_segments)
            endet_bei_vp = forward_node
        
        # Erstelle element_nr
        if beginnt_bei_vp and endet_bei_vp:
            element_nr = f"{beginnt_bei_vp}_{endet_bei_vp}.01"
        elif beginnt_bei_vp:
            element_nr = f"{beginnt_bei_vp}_UNKNOWN.01"
        elif endet_bei_vp:
            element_nr = f"UNKNOWN_{endet_bei_vp}.01"
        else:
            element_nr = f"UNKNOWN_UNKNOWN_{element_counter:03d}.01"
            element_counter += 1
        
        # Weise Werte allen verbundenen Segmenten zu
        for segment_idx in set(connected_segments):
            if segment_idx < len(result_gdf):
                result_gdf.loc[segment_idx, 'beginnt_bei_vp'] = beginnt_bei_vp
                result_gdf.loc[segment_idx, 'endet_bei_vp'] = endet_bei_vp
                result_gdf.loc[segment_idx, 'element_nr'] = element_nr
                processed_segments.add(segment_idx)
    
    logging.info(f"Element-Nummern zugewiesen. {len(processed_segments)} Segmente verarbeitet.")
    
    return result_gdf


def explore_direction(G, start_coord, exclude_idx, rvn_gdf, nodes_gdf, processed_segments, max_depth=50):
    """
    Erkundet eine Richtung im Graph bis zu einem Knotenpunkt.
    
    Args:
        G (nx.Graph): NetworkX-Graph
        start_coord (tuple): Startkoordinate
        exclude_idx (int): Index des Segments, das ausgeschlossen werden soll
        rvn_gdf (GeoDataFrame): Radvorrangsnetz
        nodes_gdf (GeoDataFrame): Knotenpunkte
        processed_segments (set): Bereits verarbeitete Segmente
        max_depth (int): Maximale Suchtiefe
        
    Returns:
        tuple: (segment_indices, found_node_id)
    """
    found_segments = []
    visited_coords = set()
    queue = [(start_coord, 0)]  # (coord, depth)
    
    while queue and len(found_segments) < max_depth:
        current_coord, depth = queue.pop(0)
        
        if current_coord in visited_coords or depth >= max_depth:
            continue
            
        visited_coords.add(current_coord)
        
        # Prüfe Nachbarn
        if current_coord in G:
            neighbors = list(G.neighbors(current_coord))
            
            for neighbor_coord in neighbors:
                edge_data = G.get_edge_data(current_coord, neighbor_coord)
                neighbor_idx = edge_data['segment_id']
                
                # Überspringe das ursprüngliche Segment und bereits verarbeitete
                if neighbor_idx == exclude_idx or neighbor_idx in processed_segments:
                    continue
                
                # Prüfe, ob an dieser Position ein Knotenpunkt ist
                neighbor_point = Point(neighbor_coord)
                node_id = find_node_at_point(neighbor_point, nodes_gdf)
                
                if node_id:
                    # Knotenpunkt gefunden!
                    return found_segments, node_id
                
                # Füge Segment zur Liste hinzu und setze Suche fort
                if neighbor_idx not in found_segments:
                    found_segments.append(neighbor_idx)
                    queue.append((neighbor_coord, depth + 1))
    
    return found_segments, None


def create_element_numbers_for_rvn():
    """
    Hauptfunktion zur Erstellung der Element-Nummern für das Radvorrangsnetz.
    """
    # Dateipfade definieren
    radvorrangsnetz_path = 'data/Berlin Radvorrangsnetz.fgb'
    knotenpunkte_path = 'output/knotenpunkte/knotenpunkte_mit_id.gpkg'
    output_path = 'output/rvn/Berlin Vorrangnetz_with_element_nr.fgb'
    
    # Stelle sicher, dass das Ausgabeverzeichnis existiert
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    try:
        # Lade Daten
        rvn_gdf, nodes_gdf = load_data(radvorrangsnetz_path, knotenpunkte_path)
        
        # Weise Element-Nummern zu
        enriched_rvn = assign_element_numbers(rvn_gdf, nodes_gdf)
        
        # Speichere Ergebnis
        logging.info(f"Speichere anreichertes Radvorrangsnetz nach {output_path}")
        enriched_rvn.to_file(output_path, driver='FlatGeobuf')
        
        # Statistiken ausgeben
        total_segments = len(enriched_rvn)
        segments_with_both_vp = len(enriched_rvn[
            (enriched_rvn['beginnt_bei_vp'].notna()) & 
            (enriched_rvn['endet_bei_vp'].notna())
        ])
        segments_with_one_vp = len(enriched_rvn[
            (enriched_rvn['beginnt_bei_vp'].notna()) | 
            (enriched_rvn['endet_bei_vp'].notna())
        ]) - segments_with_both_vp
        segments_without_vp = total_segments - segments_with_both_vp - segments_with_one_vp
        
        logging.info(f"Verarbeitung abgeschlossen:")
        logging.info(f"  Gesamt: {total_segments} Segmente")
        logging.info(f"  Mit beiden VPs: {segments_with_both_vp} Segmente")
        logging.info(f"  Mit einem VP: {segments_with_one_vp} Segmente")
        logging.info(f"  Ohne VP: {segments_without_vp} Segmente")
        
    except Exception as e:
        logging.error(f"Fehler bei der Verarbeitung: {e}")
        raise


if __name__ == '__main__':
    create_element_numbers_for_rvn()
