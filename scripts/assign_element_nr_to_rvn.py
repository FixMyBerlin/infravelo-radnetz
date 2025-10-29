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
- output/rvn/Berlin Radvorrangsnetz_mit_virtuellen-knotenpunkten.fgb
- output/knotenpunkte/knotenpunkte_mit_id.gpkg
- data/Virtuelle-Knotenpunkte.gpkg

OUTPUT:
- output/rvn/Berlin Vorrangnetz_with_element_nr.fgb
"""

import geopandas as gpd
import pandas as pd
import logging
import os
from shapely.geometry import Point
import networkx as nx

# Konfiguration
DEFAULT_CRS = 25833  # EPSG:25833 (ETRS89 / UTM zone 33N) - aus helpers.globals
NODE_SEARCH_TOLERANCE = 3.0  # Suchtoleranz in Metern für Knotenpunkte (muss mit VIRTUAL_NODE_TOLERANCE übereinstimmen)

# Logging konfigurieren
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def load_data(radvorrangsnetz_path, knotenpunkte_path, virtuelle_knotenpunkte_path):
    """
    Lädt das Radvorrangsnetz und alle Knotenpunkte (normale + virtuelle).
    
    Args:
        radvorrangsnetz_path (str): Pfad zum Radvorrangsnetz
        knotenpunkte_path (str): Pfad zu den Knotenpunkten mit IDs
        virtuelle_knotenpunkte_path (str): Pfad zu den virtuellen Knotenpunkten
        
    Returns:
        tuple: (rvn_gdf, combined_nodes_gdf) GeoDataFrames
    """
    logging.info(f"Lade Radvorrangsnetz von {radvorrangsnetz_path}")
    rvn_gdf = gpd.read_file(radvorrangsnetz_path)
    
    logging.info(f"Lade Knotenpunkte von {knotenpunkte_path}")
    nodes_gdf = gpd.read_file(knotenpunkte_path)
    
    logging.info(f"Lade virtuelle Knotenpunkte von {virtuelle_knotenpunkte_path}")
    virtual_nodes_gdf = gpd.read_file(virtuelle_knotenpunkte_path)
    
    # Sicherstellen, dass alle Datensätze das gleiche CRS haben
    target_crs = f'EPSG:{DEFAULT_CRS}'
    if rvn_gdf.crs != target_crs:
        logging.info(f"Projiziere Radvorrangsnetz auf {target_crs}")
        rvn_gdf = rvn_gdf.to_crs(target_crs)
        
    if nodes_gdf.crs != target_crs:
        logging.info(f"Projiziere Knotenpunkte auf {target_crs}")
        nodes_gdf = nodes_gdf.to_crs(target_crs)
    
    if virtual_nodes_gdf.crs != target_crs:
        logging.info(f"Projiziere virtuelle Knotenpunkte auf {target_crs}")
        virtual_nodes_gdf = virtual_nodes_gdf.to_crs(target_crs)
    
    # Kombiniere normale und virtuelle Knotenpunkte
    # Normalisiere Spaltennamen (verschiedene Bindestriche)
    if 'Knotenpunkt-ID' in virtual_nodes_gdf.columns:
        virtual_nodes_gdf = virtual_nodes_gdf.rename(columns={'Knotenpunkt-ID': 'Knotenpunkt‐ID'})
        logging.info(f"Spaltennamen der virtuellen Knotenpunkte normalisiert")
    
    # Stelle sicher, dass beide die gleichen Spalten haben (zumindest geometry und Knotenpunkt‐ID)
    essential_columns = ['geometry', 'Knotenpunkt‐ID']
    nodes_subset = nodes_gdf[essential_columns].copy()
    virtual_subset = virtual_nodes_gdf[essential_columns].copy()
    
    combined_nodes_gdf = pd.concat([nodes_subset, virtual_subset], ignore_index=True)
    combined_nodes_gdf = gpd.GeoDataFrame(combined_nodes_gdf, crs=target_crs)
    
    logging.info(f"Radvorrangsnetz geladen: {len(rvn_gdf)} Segmente")
    logging.info(f"Normale Knotenpunkte: {len(nodes_gdf)} Punkte")
    logging.info(f"Virtuelle Knotenpunkte: {len(virtual_nodes_gdf)} Punkte")
    logging.info(f"Kombinierte Knotenpunkte: {len(combined_nodes_gdf)} Punkte")
    
    return rvn_gdf, combined_nodes_gdf


def find_node_at_point(point, nodes_gdf, tolerance=NODE_SEARCH_TOLERANCE):
    """
    Findet den nächstgelegenen Knotenpunkt zu einem gegebenen Punkt.
    
    Args:
        point (Point): Punkt, an dem nach einem Knotenpunkt gesucht wird
        nodes_gdf (GeoDataFrame): GeoDataFrame mit Knotenpunkten
        tolerance (float): Suchtoleranz in Metern (default: NODE_SEARCH_TOLERANCE)
        
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
    
    WICHTIG: Virtuelle Knotenpunkte (IDs beginnen mit "V") werden speziell behandelt:
    - Segmente MIT virtuellen Knotenpunkten: Jedes Segment bekommt seine eigenen,
      korrekten beginnt_bei_vp und endet_bei_vp Werte (keine Propagierung)
    - Segmente OHNE virtuelle Knotenpunkte: Verbundene Segmente können gemeinsame
      element_nr bekommen (alte Logik für zusammenhängende Abschnitte)
    
    Args:
        rvn_gdf (GeoDataFrame): Radvorrangsnetz
        nodes_gdf (GeoDataFrame): Knotenpunkte mit IDs (inkl. virtueller Knotenpunkte)
        
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
    segments_with_virtual_nodes = 0  # Zähler für Segmente mit virtuellen Knotenpunkten
    
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
        
        # Prüfe SOFORT, ob virtuelle Knotenpunkte direkt an den Endpunkten sind
        # Falls ja: explore_direction NICHT aufrufen (keine Propagierung über virtuelle Knotenpunkte hinweg)
        start_is_virtual = start_node_id and str(start_node_id).startswith('V')
        end_is_virtual = end_node_id and str(end_node_id).startswith('V')
        
        # Initialisiere die verbundenen Segmente mit dem aktuellen Segment
        connected_segments = [idx]
        beginnt_bei_vp = start_node_id
        endet_bei_vp = end_node_id
        
        # Wenn am Startpunkt kein Knotenpunkt ist, gehe rückwärts
        # ABER: Bei virtuellen Knotenpunkten KEINE Propagierung (sie sind echte Grenzen)
        if not start_is_virtual:
            if not start_node_id:
                start_coord = (start_point.x, start_point.y)
                backward_segments, backward_node = explore_direction(
                    G, start_coord, idx, rvn_gdf, nodes_gdf, processed_segments
                )
                connected_segments.extend(backward_segments)
                beginnt_bei_vp = backward_node
        
        # Wenn am Endpunkt kein Knotenpunkt ist, gehe vorwärts
        # ABER: Bei virtuellen Knotenpunkten KEINE Propagierung (sie sind echte Grenzen)
        if not end_is_virtual:
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
        
        # Prüfe ob virtuelle Knotenpunkte (IDs beginnen mit "V") beteiligt sind
        has_virtual_node = start_is_virtual or end_is_virtual
        
        # Weise Werte allen verbundenen Segmenten zu
        # (Bei virtuellen Knotenpunkten ist connected_segments garantiert nur [idx])
        for segment_idx in set(connected_segments):
            if segment_idx < len(result_gdf):
                result_gdf.loc[segment_idx, 'beginnt_bei_vp'] = beginnt_bei_vp
                result_gdf.loc[segment_idx, 'endet_bei_vp'] = endet_bei_vp
                result_gdf.loc[segment_idx, 'element_nr'] = element_nr
                processed_segments.add(segment_idx)
        
        # Zähle Segmente mit virtuellen Knotenpunkten
        if has_virtual_node:
            segments_with_virtual_nodes += 1
            logging.debug(f"Segment {idx}: Virtueller Knotenpunkt erkannt - keine Propagierung an verbundene Segmente")
    
    # Zähle nachträglich alle Segmente mit virtuellen Knotenpunkten
    segments_with_v_in_beginnt = result_gdf[result_gdf['beginnt_bei_vp'].notna() & result_gdf['beginnt_bei_vp'].astype(str).str.startswith('V')]
    segments_with_v_in_endet = result_gdf[result_gdf['endet_bei_vp'].notna() & result_gdf['endet_bei_vp'].astype(str).str.startswith('V')]
    segments_with_any_v = result_gdf[
        (result_gdf['beginnt_bei_vp'].notna() & result_gdf['beginnt_bei_vp'].astype(str).str.startswith('V')) |
        (result_gdf['endet_bei_vp'].notna() & result_gdf['endet_bei_vp'].astype(str).str.startswith('V'))
    ]
    
    logging.info(f"Element-Nummern zugewiesen. {len(processed_segments)} Segmente verarbeitet.")
    logging.info(f"  Davon {segments_with_virtual_nodes} Segmente mit virtuellen Knotenpunkten (keine Propagierung)")
    logging.info(f"\n📊 VIRTUELLE KNOTENPUNKTE STATISTIK:")
    logging.info(f"  Segmente mit V in beginnt_bei_vp: {len(segments_with_v_in_beginnt)}")
    logging.info(f"  Segmente mit V in endet_bei_vp: {len(segments_with_v_in_endet)}")
    logging.info(f"  Segmente mit mind. einem V: {len(segments_with_any_v)} ({len(segments_with_any_v)/len(result_gdf)*100:.2f}%)")
    
    return result_gdf


def explore_direction(G, start_coord, exclude_idx, rvn_gdf, nodes_gdf, processed_segments, max_depth=50):
    """
    Erkundet eine Richtung im Graph bis zu einem Knotenpunkt.
    
    WICHTIG: Diese Funktion prüft auch bereits verarbeitete Segmente auf Knotenpunkte,
    fügt sie aber nicht zur Rückgabeliste hinzu. Dadurch können Knotenpunkte gefunden
    werden, die durch bereits verarbeitete Segmente hindurch liegen.
    
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
                
                # Überspringe nur das ursprüngliche Segment
                if neighbor_idx == exclude_idx:
                    continue
                
                # Prüfe, ob an dieser Position ein Knotenpunkt ist
                neighbor_point = Point(neighbor_coord)
                node_id = find_node_at_point(neighbor_point, nodes_gdf)
                
                if node_id:
                    # Knotenpunkt gefunden!
                    return found_segments, node_id
                
                # Füge Segment zur Liste hinzu (nur wenn noch nicht verarbeitet)
                # und setze Suche fort (auch durch bereits verarbeitete Segmente)
                if neighbor_idx not in processed_segments and neighbor_idx not in found_segments:
                    found_segments.append(neighbor_idx)
                
                # Setze Suche fort, auch durch bereits verarbeitete Segmente
                if neighbor_coord not in visited_coords:
                    queue.append((neighbor_coord, depth + 1))
    
    return found_segments, None


def analyze_element_nr_quality(enriched_rvn):
    """
    Analysiert die Qualität der zugewiesenen element_nr Werte.
    
    Prüft auf UNKNOWN oder None Werte in element_nr, beginnt_bei_vp und endet_bei_vp.
    Gibt detaillierte Statistiken und Beispiele aus.
    
    Args:
        enriched_rvn (GeoDataFrame): Radvorrangsnetz mit zugewiesenen element_nr
        
    Returns:
        dict: Statistiken über problematische element_nr Werte
    """
    logging.info("\n" + "="*70)
    logging.info("QUALITÄTSANALYSE DER ELEMENT_NR")
    logging.info("="*70)
    
    total_segments = len(enriched_rvn)
    
    # Prüfe auf None in element_nr
    element_nr_none = enriched_rvn[enriched_rvn['element_nr'].isna()]
    
    # Prüfe auf UNKNOWN in element_nr
    element_nr_with_unknown = enriched_rvn[
        enriched_rvn['element_nr'].notna() & 
        enriched_rvn['element_nr'].str.contains('UNKNOWN', na=False)
    ]
    
    # Prüfe auf None in beginnt_bei_vp
    beginnt_none = enriched_rvn[enriched_rvn['beginnt_bei_vp'].isna()]
    
    # Prüfe auf None in endet_bei_vp
    endet_none = enriched_rvn[enriched_rvn['endet_bei_vp'].isna()]
    
    # Segmente mit beiden VPs als UNKNOWN oder None
    both_problematic = enriched_rvn[
        (enriched_rvn['beginnt_bei_vp'].isna() | (enriched_rvn['beginnt_bei_vp'] == 'None')) &
        (enriched_rvn['endet_bei_vp'].isna() | (enriched_rvn['endet_bei_vp'] == 'None'))
    ]
    
    logging.info(f"\n📊 STATISTIKEN:")
    logging.info(f"  Gesamte Segmente: {total_segments}")
    logging.info(f"\n  element_nr ist None: {len(element_nr_none)} ({len(element_nr_none)/total_segments*100:.2f}%)")
    logging.info(f"  element_nr enthält UNKNOWN: {len(element_nr_with_unknown)} ({len(element_nr_with_unknown)/total_segments*100:.2f}%)")
    logging.info(f"\n  beginnt_bei_vp ist None: {len(beginnt_none)} ({len(beginnt_none)/total_segments*100:.2f}%)")
    logging.info(f"  endet_bei_vp ist None: {len(endet_none)} ({len(endet_none)/total_segments*100:.2f}%)")
    logging.info(f"\n  Beide VPs problematisch: {len(both_problematic)} ({len(both_problematic)/total_segments*100:.2f}%)")
    
    # Zeige Beispiele für element_nr mit UNKNOWN
    if len(element_nr_with_unknown) > 0:
        logging.info(f"\n⚠️  BEISPIELE FÜR ELEMENT_NR MIT UNKNOWN (erste 10):")
        for idx, row in element_nr_with_unknown.head(10).iterrows():
            logging.info(f"  Index {idx}:")
            logging.info(f"    element_nr: {row['element_nr']}")
            logging.info(f"    beginnt_bei_vp: {row['beginnt_bei_vp']}")
            logging.info(f"    endet_bei_vp: {row['endet_bei_vp']}")
            
            # Zeige Geometrie-Info
            geom = row.geometry
            if hasattr(geom, 'length'):
                logging.info(f"    Länge: {geom.length:.2f} m")
    
    # Zeige Beispiele für element_nr mit None
    if len(element_nr_none) > 0:
        logging.info(f"\n⚠️  BEISPIELE FÜR ELEMENT_NR MIT NONE (erste 5):")
        for idx, row in element_nr_none.head(5).iterrows():
            logging.info(f"  Index {idx}:")
            logging.info(f"    element_nr: {row['element_nr']}")
            logging.info(f"    beginnt_bei_vp: {row['beginnt_bei_vp']}")
            logging.info(f"    endet_bei_vp: {row['endet_bei_vp']}")
    
    # Zeige Beispiele für beide VPs problematisch
    if len(both_problematic) > 0:
        logging.info(f"\n⚠️  SEGMENTE MIT BEIDEN VPs PROBLEMATISCH (erste 5):")
        for idx, row in both_problematic.head(5).iterrows():
            logging.info(f"  Index {idx}:")
            logging.info(f"    element_nr: {row['element_nr']}")
            logging.info(f"    beginnt_bei_vp: {row['beginnt_bei_vp']}")
            logging.info(f"    endet_bei_vp: {row['endet_bei_vp']}")
            
            # Zeige Startpunkt der Geometrie
            start_point, end_point = get_line_endpoints(row.geometry)
            logging.info(f"    Start: ({start_point.x:.2f}, {start_point.y:.2f})")
            logging.info(f"    Ende: ({end_point.x:.2f}, {end_point.y:.2f})")
    
    logging.info("\n" + "="*70)
    
    # Rückgabe Statistiken
    return {
        'total': total_segments,
        'element_nr_none': len(element_nr_none),
        'element_nr_unknown': len(element_nr_with_unknown),
        'beginnt_none': len(beginnt_none),
        'endet_none': len(endet_none),
        'both_problematic': len(both_problematic)
    }


def check_elem_nr_divergence(enriched_rvn):
    """
    Prüft ob die ursprüngliche elem_nr von der berechneten element_nr abweicht.
    
    Diese Funktion vergleicht die im Eingangsdatensatz vorhandene elem_nr mit der
    neu berechneten element_nr und gibt Divergenzen aus.
    
    Args:
        enriched_rvn (GeoDataFrame): Radvorrangsnetz mit berechneter element_nr und
                                     ursprünglicher elem_nr
                                     
    Returns:
        dict: Statistiken über Divergenzen
    """
    logging.info("\n" + "="*70)
    logging.info("DIVERGENZ-ANALYSE: elem_nr vs. element_nr")
    logging.info("="*70)
    
    total_segments = len(enriched_rvn)
    
    # Segmente mit elem_nr vorhanden
    has_elem_nr = enriched_rvn[enriched_rvn['elem_nr'].notna()].copy()
    logging.info(f"\nSegmente mit vorhandener elem_nr: {len(has_elem_nr)} von {total_segments}")
    
    if len(has_elem_nr) == 0:
        logging.info("  ℹ️  Keine elem_nr Werte im Datensatz vorhanden.")
        logging.info("="*70)
        return {
            'total': total_segments,
            'has_elem_nr': 0,
            'divergent': 0,
            'identical': 0
        }
    
    # Prüfe auf Divergenzen (nur bei Segmenten mit elem_nr)
    has_elem_nr['divergent'] = has_elem_nr['elem_nr'] != has_elem_nr['element_nr']
    divergent_segments = has_elem_nr[has_elem_nr['divergent']]
    identical_segments = has_elem_nr[~has_elem_nr['divergent']]
    
    logging.info(f"\n📊 STATISTIKEN:")
    logging.info(f"  Identisch (elem_nr == element_nr): {len(identical_segments)} ({len(identical_segments)/len(has_elem_nr)*100:.2f}%)")
    logging.info(f"  Divergent (elem_nr ≠ element_nr): {len(divergent_segments)} ({len(divergent_segments)/len(has_elem_nr)*100:.2f}%)")
    
    # Zeige Beispiele für divergente Fälle
    if len(divergent_segments) > 0:
        logging.info(f"\n⚠️  BEISPIELE FÜR DIVERGENTE ELEMENT_NR (erste 20):")
        for idx, row in divergent_segments.head(20).iterrows():
            logging.info(f"\n  Index {idx}:")
            logging.info(f"    Original elem_nr:    {row['elem_nr']}")
            logging.info(f"    Berechnete element_nr: {row['element_nr']}")
            logging.info(f"    beginnt_bei_vp: {row['beginnt_bei_vp']}")
            logging.info(f"    endet_bei_vp: {row['endet_bei_vp']}")
            
            # Zeige Geometrie-Info
            geom = row.geometry
            if hasattr(geom, 'length'):
                logging.info(f"    Länge: {geom.length:.2f} m")
        
        # Zeige Gesamtlänge der divergenten Segmente
        total_length = divergent_segments.geometry.length.sum()
        total_network_length = enriched_rvn.geometry.length.sum()
        logging.info(f"\n📏 LÄNGEN:")
        logging.info(f"  Divergente Segmente: {total_length/1000:.2f} km ({total_length/total_network_length*100:.2f}% des Netzes)")
        logging.info(f"  Gesamtnetz: {total_network_length/1000:.2f} km")
    
    logging.info("\n" + "="*70)
    
    return {
        'total': total_segments,
        'has_elem_nr': len(has_elem_nr),
        'divergent': len(divergent_segments),
        'identical': len(identical_segments)
    }


def apply_elem_nr_priority(enriched_rvn):
    """
    Übernimmt elem_nr als finale element_nr, falls elem_nr vorhanden ist.
    
    Diese Funktion implementiert die Prioritätsregel:
    - Falls elem_nr existiert UND kein virtueller Knotenpunkt vorhanden: element_nr = elem_nr
    - Falls elem_nr nicht existiert: element_nr bleibt unverändert (berechneter Wert)
    - Falls virtueller Knotenpunkt vorhanden: berechnete element_nr bleibt erhalten
    
    WICHTIG: Segmente mit virtuellen Knotenpunkten (erkennbar an "V" in beginnt_bei_vp
    oder endet_bei_vp) werden von der Prioritätsregel AUSGENOMMEN, da die elem_nr
    aus der Zeit vor dem Splitting stammt und virtuelle Knotenpunkte nicht berücksichtigt.
    
    Args:
        enriched_rvn (GeoDataFrame): Radvorrangsnetz mit berechneter element_nr und
                                     ursprünglicher elem_nr
                                     
    Returns:
        GeoDataFrame: Radvorrangsnetz mit finaler element_nr
    """
    logging.info("\n" + "="*70)
    logging.info("ANWENDUNG DER PRIORITÄTSREGEL: elem_nr → element_nr")
    logging.info("="*70)
    
    result_gdf = enriched_rvn.copy()
    
    # Identifiziere Segmente mit virtuellen Knotenpunkten
    has_virtual_start = result_gdf['beginnt_bei_vp'].notna() & result_gdf['beginnt_bei_vp'].astype(str).str.startswith('V')
    has_virtual_end = result_gdf['endet_bei_vp'].notna() & result_gdf['endet_bei_vp'].astype(str).str.startswith('V')
    has_virtual_node = has_virtual_start | has_virtual_end
    
    # Zähle Segmente
    virtual_count = has_virtual_node.sum()
    has_elem_nr = result_gdf['elem_nr'].notna()
    
    # Prioritätsregel gilt NUR für Segmente OHNE virtuelle Knotenpunkte
    eligible_for_priority = has_elem_nr & ~has_virtual_node
    excluded_virtual = has_elem_nr & has_virtual_node
    
    overwrite_count = eligible_for_priority.sum()
    excluded_count = excluded_virtual.sum()
    keep_calculated_count = (~has_elem_nr).sum()
    
    logging.info(f"\n📝 PRIORITÄTSREGEL:")
    logging.info(f"  elem_nr vorhanden UND kein V-Knoten → wird übernommen: {overwrite_count} Segmente")
    logging.info(f"  elem_nr vorhanden ABER V-Knoten → AUSGENOMMEN: {excluded_count} Segmente")
    logging.info(f"  elem_nr fehlt → berechnete element_nr behalten: {keep_calculated_count} Segmente")
    logging.info(f"\n  Gesamt mit virtuellen Knotenpunkten: {virtual_count} Segmente")
    
    # Übernehme elem_nr als element_nr NUR wo vorhanden UND keine virtuellen Knotenpunkte
    result_gdf.loc[eligible_for_priority, 'element_nr'] = result_gdf.loc[eligible_for_priority, 'elem_nr']
    
    logging.info(f"\n✅ Prioritätsregel angewendet (Segmente mit V-Knoten ausgenommen)!")
    logging.info("="*70)
    
    return result_gdf


def create_element_numbers_for_rvn():
    """
    Hauptfunktion zur Erstellung der Element-Nummern für das Radvorrangsnetz.
    """
    # Dateipfade definieren
    radvorrangsnetz_path = 'output/rvn/Berlin Radvorrangsnetz_mit_virtuellen-knotenpunkten.fgb'
    knotenpunkte_path = 'output/knotenpunkte/knotenpunkte_mit_id.gpkg'
    virtuelle_knotenpunkte_path = 'data/Virtuelle-Knotenpunkte.gpkg'
    output_path = 'output/rvn/Berlin Vorrangnetz_with_element_nr.fgb'
    
    # Stelle sicher, dass das Ausgabeverzeichnis existiert
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    try:
        # Lade Daten (inkl. virtuelle Knotenpunkte)
        rvn_gdf, combined_nodes_gdf = load_data(radvorrangsnetz_path, knotenpunkte_path, virtuelle_knotenpunkte_path)
        
        # Weise Element-Nummern zu (mit kombinierten Knotenpunkten)
        enriched_rvn = assign_element_numbers(rvn_gdf, combined_nodes_gdf)
        
        # Qualitätsanalyse durchführen
        quality_stats = analyze_element_nr_quality(enriched_rvn)
        
        # Prüfe Divergenzen zwischen elem_nr und berechneter element_nr
        divergence_stats = check_elem_nr_divergence(enriched_rvn)
        
        # Wende Prioritätsregel an: elem_nr überschreibt berechnete element_nr
        enriched_rvn = apply_elem_nr_priority(enriched_rvn)
        
        # Speichere Ergebnis
        logging.info(f"\nSpeichere anreichertes Radvorrangsnetz nach {output_path}")
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
        
        logging.info(f"\nVerarbeitung abgeschlossen:")
        logging.info(f"  Gesamt: {total_segments} Segmente")
        logging.info(f"  Mit beiden VPs: {segments_with_both_vp} Segmente")
        logging.info(f"  Mit einem VP: {segments_with_one_vp} Segmente")
        logging.info(f"  Ohne VP: {segments_without_vp} Segmente")
        
    except Exception as e:
        logging.error(f"Fehler bei der Verarbeitung: {e}")
        raise


if __name__ == '__main__':
    create_element_numbers_for_rvn()
