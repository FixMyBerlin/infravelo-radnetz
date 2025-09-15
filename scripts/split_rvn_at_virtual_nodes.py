#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
split_rvn_at_virtual_nodes.py
--------------------------------------------------------------------
Teilt das Berliner Radvorrangsnetz an virtuellen Knotenpunkten auf.
Virtuelle Knotenpunkte liegen nicht an Linienendpunkten, sondern mitten auf
Linien und erfordern daher eine Aufteilung der betroffenen Linien.

Das Script wird vor assign_element_nr_to_rvn.py ausgeführt, damit die
element_nr-Zuweisung korrekt auf die aufgeteilten Segmente angewendet wird.

INPUT:
- data/Virtuelle-Knotenpunkte.gpkg (von assign_node_ids erstellt)
- data/Berlin Radvorrangsnetz.fgb

OUTPUT:
- output/rvn/Berlin Radvorrangsnetz_mit_virtuellen-knotenpunkten.fgb
"""

import geopandas as gpd
import logging
import os
from shapely.geometry import LineString, MultiLineString
from shapely.ops import split

# Konfiguration
DEFAULT_CRS = 25833  # EPSG:25833 (ETRS89 / UTM zone 33N) - aus helpers.globals
VIRTUAL_NODE_TOLERANCE = 3.0  # Maximale Entfernung in Metern für virtuellen Knotenpunkt zur Linie

# Logging konfigurieren
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def load_data(rvn_path, virtual_nodes_path):
    """
    Lädt das Radvorrangsnetz und die virtuellen Knotenpunkte.
    
    Args:
        rvn_path (str): Pfad zum Radvorrangsnetz
        virtual_nodes_path (str): Pfad zu den virtuellen Knotenpunkten
        
    Returns:
        tuple: (rvn_gdf, virtual_nodes_gdf) GeoDataFrames
    """
    logging.info(f"Lade Radvorrangsnetz von {rvn_path}")
    rvn_gdf = gpd.read_file(rvn_path)
    
    logging.info(f"Lade virtuelle Knotenpunkte von {virtual_nodes_path}")
    virtual_nodes_gdf = gpd.read_file(virtual_nodes_path)
    
    # Sicherstellen, dass beide Datensätze das gleiche CRS haben
    target_crs = f'EPSG:{DEFAULT_CRS}'
    if rvn_gdf.crs != target_crs:
        logging.info(f"Projiziere Radvorrangsnetz auf {target_crs}")
        rvn_gdf = rvn_gdf.to_crs(target_crs)
        
    if virtual_nodes_gdf.crs != target_crs:
        logging.info(f"Projiziere virtuelle Knotenpunkte auf {target_crs}")
        virtual_nodes_gdf = virtual_nodes_gdf.to_crs(target_crs)
    
    logging.info(f"Radvorrangsnetz geladen: {len(rvn_gdf)} Linien")
    logging.info(f"Virtuelle Knotenpunkte geladen: {len(virtual_nodes_gdf)} Punkte")
    
    return rvn_gdf, virtual_nodes_gdf


def find_closest_line_segment(point, line_geom):
    """
    Findet das nächstgelegene Liniensegment zu einem Punkt bei MultiLineString.
    Bei einfachen LineStrings wird die Linie selbst zurückgegeben.
    
    Args:
        point (Point): Punkt für den das nächste Segment gesucht wird
        line_geom (LineString oder MultiLineString): Liniengeometrie
        
    Returns:
        tuple: (closest_segment, segment_index) oder (line_geom, 0) für LineString
    """
    if isinstance(line_geom, LineString):
        return line_geom, 0
    
    if isinstance(line_geom, MultiLineString):
        min_distance = float('inf')
        closest_segment = None
        closest_index = -1
        
        for idx, segment in enumerate(line_geom.geoms):
            distance = point.distance(segment)
            if distance < min_distance:
                min_distance = distance
                closest_segment = segment
                closest_index = idx
        
        return closest_segment, closest_index
    
    raise ValueError(f"Ununterstützte Geometrie: {type(line_geom)}")


def split_line_at_point(line_geom, point, tolerance=VIRTUAL_NODE_TOLERANCE):
    """
    Teilt eine Linie an der nächstgelegenen Position zu einem Punkt.
    
    Args:
        line_geom (LineString oder MultiLineString): Zu teilende Linie
        point (Point): Punkt an dem geteilt werden soll
        tolerance (float): Maximale Entfernung für gültigen Split
        
    Returns:
        list: Liste der resultierenden LineString-Geometrien, oder [line_geom] wenn nicht geteilt
    """
    # Finde nächstes Segment bei MultiLineString
    if isinstance(line_geom, MultiLineString):
        closest_segment, segment_idx = find_closest_line_segment(point, line_geom)
        distance = point.distance(closest_segment)
        
        if distance > tolerance:
            logging.warning(f"Virtueller Knotenpunkt ist {distance:.2f}m von nächster Linie entfernt (> {tolerance}m)")
            return [line_geom]
        
        # Teile nur das nächste Segment
        split_segments = split_line_at_point(closest_segment, point, tolerance)
        
        # Ersetze das ursprüngliche Segment durch die geteilten Segmente
        result_segments = []
        for idx, segment in enumerate(line_geom.geoms):
            if idx == segment_idx:
                result_segments.extend(split_segments)
            else:
                result_segments.append(segment)
        
        return result_segments
    
    # Für einfache LineString
    distance = point.distance(line_geom)
    if distance > tolerance:
        logging.warning(f"Virtueller Knotenpunkt ist {distance:.2f}m von Linie entfernt (> {tolerance}m)")
        return [line_geom]
    
    # Projiziere Punkt auf Linie
    projected_distance = line_geom.project(point)
    projected_point = line_geom.interpolate(projected_distance)
    
    # Erstelle einen kleinen Puffer um den projizierten Punkt für split
    split_buffer = projected_point.buffer(0.01)  # 1cm Buffer für numerische Stabilität
    
    try:
        # Teile Linie mit dem Buffer
        split_result = split(line_geom, split_buffer)
        
        if hasattr(split_result, 'geoms'):
            # Erfolgreiche Teilung - sammle alle LineString-Teile
            segments = []
            for geom in split_result.geoms:
                if isinstance(geom, LineString) and geom.length > 0.01:  # Mindestlänge 1cm
                    segments.append(geom)
            
            if len(segments) > 1:
                logging.debug(f"Linie erfolgreich in {len(segments)} Segmente geteilt")
                return segments
            else:
                logging.debug("Split ergab nur ein Segment - Rückgabe der ursprünglichen Linie")
                return [line_geom]
        else:
            # Keine Teilung erfolgt
            logging.debug("Keine Teilung möglich - Rückgabe der ursprünglichen Linie")
            return [line_geom]
            
    except Exception as e:
        logging.warning(f"Fehler beim Teilen der Linie: {e}")
        return [line_geom]


def split_rvn_at_virtual_nodes(rvn_gdf, virtual_nodes_gdf):
    """
    Teilt alle Linien des RVN an virtuellen Knotenpunkten.
    Verarbeitet virtuelle Knotenpunkte seriell pro Linie.
    
    Args:
        rvn_gdf (GeoDataFrame): Radvorrangsnetz
        virtual_nodes_gdf (GeoDataFrame): Virtuelle Knotenpunkte
        
    Returns:
        GeoDataFrame: RVN mit aufgeteilten Linien
    """
    logging.info("Starte Aufteilung der RVN-Linien an virtuellen Knotenpunkten...")
    
    result_segments = []
    splits_performed = 0
    lines_affected = 0
    
    for line_idx, line_row in rvn_gdf.iterrows():
        if line_idx % 100 == 0:
            logging.info(f"Verarbeite Linie {line_idx + 1} von {len(rvn_gdf)}")
        
        current_geometry = line_row.geometry
        line_was_split = False
        
        # Finde alle virtuellen Knotenpunkte in der Nähe dieser Linie
        line_buffer = current_geometry.buffer(VIRTUAL_NODE_TOLERANCE)
        nearby_virtual_nodes = virtual_nodes_gdf[virtual_nodes_gdf.geometry.within(line_buffer)]
        
        if len(nearby_virtual_nodes) == 0:
            # Keine virtuellen Knotenpunkte in der Nähe - Linie unverändert übernehmen
            result_segments.append(line_row.copy())
            continue
        
        # Sortiere virtuelle Knotenpunkte nach Position entlang der Linie für serielle Verarbeitung
        virtual_nodes_with_position = []
        for vn_idx, vn_row in nearby_virtual_nodes.iterrows():
            try:
                # Projiziere virtuellen Knotenpunkt auf die Linie
                if isinstance(current_geometry, MultiLineString):
                    # Bei MultiLineString: finde nächstes Segment und projiziere darauf
                    closest_segment, _ = find_closest_line_segment(vn_row.geometry, current_geometry)
                    position = closest_segment.project(vn_row.geometry)
                else:
                    position = current_geometry.project(vn_row.geometry)
                
                virtual_nodes_with_position.append((position, vn_row))
            except Exception as e:
                logging.warning(f"Fehler beim Projizieren von virtuellem Knotenpunkt {vn_idx}: {e}")
                continue
        
        # Sortiere nach Position entlang der Linie
        virtual_nodes_with_position.sort(key=lambda x: x[0])
        
        # Teile die Linie seriell an jedem virtuellen Knotenpunkt
        current_segments = [current_geometry]
        
        for position, vn_row in virtual_nodes_with_position:
            new_segments = []
            split_occurred = False
            
            for segment in current_segments:
                split_result = split_line_at_point(segment, vn_row.geometry, VIRTUAL_NODE_TOLERANCE)
                if len(split_result) > 1:
                    split_occurred = True
                    splits_performed += 1
                new_segments.extend(split_result)
            
            current_segments = new_segments
            if split_occurred:
                line_was_split = True
        
        # Erstelle Ergebniszeilen für alle Segmente dieser ursprünglichen Linie
        for segment_geom in current_segments:
            if isinstance(segment_geom, (LineString, MultiLineString)) and segment_geom.length > 0.01:
                segment_row = line_row.copy()
                segment_row.geometry = segment_geom
                result_segments.append(segment_row)
        
        if line_was_split:
            lines_affected += 1
    
    # Erstelle neues GeoDataFrame
    result_gdf = gpd.GeoDataFrame(result_segments, crs=rvn_gdf.crs)
    
    logging.info(f"Aufteilung abgeschlossen:")
    logging.info(f"  Ursprüngliche Linien: {len(rvn_gdf)}")
    logging.info(f"  Resultierende Segmente: {len(result_gdf)}")
    logging.info(f"  Betroffene Linien: {lines_affected}")
    logging.info(f"  Durchgeführte Splits: {splits_performed}")
    
    return result_gdf


def main():
    """
    Hauptfunktion zur Aufteilung des RVN an virtuellen Knotenpunkten.
    """
    # Dateipfade definieren
    rvn_path = 'data/Berlin Radvorrangsnetz.fgb'
    virtual_nodes_path = 'data/Virtuelle-Knotenpunkte.gpkg'
    output_path = 'output/rvn/Berlin Radvorrangsnetz_mit_virtuellen-knotenpunkten.fgb'
    
    # Stelle sicher, dass das Ausgabeverzeichnis existiert
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    try:
        # Lade Daten
        rvn_gdf, virtual_nodes_gdf = load_data(rvn_path, virtual_nodes_path)
        
        # Führe Aufteilung durch
        split_rvn = split_rvn_at_virtual_nodes(rvn_gdf, virtual_nodes_gdf)
        
        # Speichere Ergebnis
        logging.info(f"Speichere aufgeteiltes RVN nach {output_path}")
        split_rvn.to_file(output_path, driver='FlatGeobuf')
        
        logging.info("Verarbeitung erfolgreich abgeschlossen!")
        
    except Exception as e:
        logging.error(f"Fehler bei der Verarbeitung: {e}")
        raise


if __name__ == '__main__':
    main()