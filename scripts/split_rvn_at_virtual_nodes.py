#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
split_rvn_at_virtual_nodes.py
--------------------------------------------------------------------
Teilt das Berliner Radvorrangsnetz und das Detailnetz an virtuellen Knotenpunkten auf.
Virtuelle Knotenpunkte liegen nicht an Linienendpunkten, sondern mitten auf
Linien und erfordern daher eine Aufteilung der betroffenen Linien.

Die neuen element_nr werden im Skript assign_element_nr_to_rvn.py ausgeführt.

INPUT:
- data/Virtuelle-Knotenpunkte.gpkg (von assign_node_ids erstellt)
- data/Berlin Radvorrangsnetz.fgb
- data/Berlin Straßenabschnitte Detailnetz.fgb

OUTPUT:
- output/rvn/Berlin Radvorrangsnetz_mit_virtuellen-knotenpunkten.fgb
- output/rvn/Berlin Detailnetz_mit_virtuellen-knotenpunkten.fgb
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


def load_virtual_nodes(virtual_nodes_path):
    """
    Lädt die virtuellen Knotenpunkte.
    
    Args:
        virtual_nodes_path (str): Pfad zu den virtuellen Knotenpunkten
        
    Returns:
        GeoDataFrame: Virtuelle Knotenpunkte
    """
    logging.info(f"Lade virtuelle Knotenpunkte von {virtual_nodes_path}")
    virtual_nodes_gdf = gpd.read_file(virtual_nodes_path)
    
    target_crs = f'EPSG:{DEFAULT_CRS}'
    if virtual_nodes_gdf.crs != target_crs:
        logging.info(f"Projiziere virtuelle Knotenpunkte auf {target_crs}")
        virtual_nodes_gdf = virtual_nodes_gdf.to_crs(target_crs)
    
    logging.info(f"Virtuelle Knotenpunkte geladen: {len(virtual_nodes_gdf)} Punkte")
    
    return virtual_nodes_gdf


def load_geodataframe(path, name="Datensatz"):
    """
    Lädt ein GeoDataFrame und projiziert es auf das Ziel-CRS.
    
    Args:
        path (str): Pfad zur Datei
        name (str): Name des Datensatzes für Logging
        
    Returns:
        GeoDataFrame: Geladener Datensatz
    """
    logging.info(f"Lade {name} von {path}")
    gdf = gpd.read_file(path)
    
    target_crs = f'EPSG:{DEFAULT_CRS}'
    if gdf.crs != target_crs:
        logging.info(f"Projiziere {name} auf {target_crs}")
        gdf = gdf.to_crs(target_crs)
    
    logging.info(f"{name} geladen: {len(gdf)} Einträge")
    
    return gdf


def load_data(rvn_path, virtual_nodes_path):
    """
    Lädt das Radvorrangsnetz und die virtuellen Knotenpunkte.
    
    Args:
        rvn_path (str): Pfad zum Radvorrangsnetz
        virtual_nodes_path (str): Pfad zu den virtuellen Knotenpunkten
        
    Returns:
        tuple: (rvn_gdf, virtual_nodes_gdf) GeoDataFrames
    """
    rvn_gdf = load_geodataframe(rvn_path, "Radvorrangsnetz")
    virtual_nodes_gdf = load_virtual_nodes(virtual_nodes_path)
    
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
    Wenn der Punkt nahe einem Endpunkt liegt, wird der virtuelle Knotenpunkt
    exakt auf den Endpunkt projiziert, um sehr kurze Segmente zu vermeiden.
    
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
    line_length = line_geom.length
    
    # VERBESSERUNG: Prüfe ob der projizierte Punkt sehr nah an einem Endpunkt liegt
    # Wenn ja, snap auf den exakten Endpunkt um sehr kurze Segmente zu vermeiden
    ENDPOINT_SNAP_TOLERANCE = 1.0  # 1 Meter
    
    if projected_distance < ENDPOINT_SNAP_TOLERANCE:
        # Nahe am Startpunkt - snap auf Start
        logging.debug(f"Virtueller Knotenpunkt liegt {projected_distance:.2f}m vom Startpunkt - snapping auf Startpunkt")
        return [line_geom]  # Keine Teilung notwendig
    elif (line_length - projected_distance) < ENDPOINT_SNAP_TOLERANCE:
        # Nahe am Endpunkt - snap auf Ende
        logging.debug(f"Virtueller Knotenpunkt liegt {line_length - projected_distance:.2f}m vom Endpunkt - snapping auf Endpunkt")
        return [line_geom]  # Keine Teilung notwendig
    
    # VERBESSERUNG: Erstelle exakte Koordinaten für den Split-Punkt
    projected_point = line_geom.interpolate(projected_distance)
    
    # Erstelle neue Linie durch Koordinaten-Extraktion und -Aufteilung
    coords = list(line_geom.coords)
    
    # Finde die Position wo der Split-Punkt eingefügt werden soll
    split_coord = (projected_point.x, projected_point.y)
    
    # Baue zwei neue LineStrings: vom Start bis zum Split-Punkt und vom Split-Punkt bis zum Ende
    accumulated_distance = 0.0
    split_index = None
    
    for i in range(len(coords) - 1):
        segment_start = coords[i]
        segment_end = coords[i + 1]
        segment_line = LineString([segment_start, segment_end])
        segment_length = segment_line.length
        
        if accumulated_distance <= projected_distance <= accumulated_distance + segment_length:
            split_index = i
            break
        accumulated_distance += segment_length
    
    if split_index is None:
        logging.warning("Konnte Split-Index nicht bestimmen - Rückgabe der ursprünglichen Linie")
        return [line_geom]
    
    try:
        # Erstelle erstes Segment: vom Start bis zum Split-Punkt
        first_coords = coords[:split_index + 1] + [split_coord]
        first_segment = LineString(first_coords)
        
        # Erstelle zweites Segment: vom Split-Punkt bis zum Ende
        second_coords = [split_coord] + coords[split_index + 1:]
        second_segment = LineString(second_coords)
        
        # Prüfe ob beide Segmente eine sinnvolle Länge haben (mindestens 0.1m)
        MIN_SEGMENT_LENGTH = 0.1
        segments = []
        
        if first_segment.length >= MIN_SEGMENT_LENGTH:
            segments.append(first_segment)
        else:
            logging.debug(f"Erstes Segment zu kurz ({first_segment.length:.3f}m) - wird übersprungen")
        
        if second_segment.length >= MIN_SEGMENT_LENGTH:
            segments.append(second_segment)
        else:
            logging.debug(f"Zweites Segment zu kurz ({second_segment.length:.3f}m) - wird übersprungen")
        
        if len(segments) == 2:
            logging.debug(f"Linie erfolgreich in 2 Segmente geteilt ({first_segment.length:.2f}m, {second_segment.length:.2f}m)")
            return segments
        elif len(segments) == 1:
            logging.debug("Split würde zu kurzes Segment erzeugen - ein Segment beibehalten")
            return segments
        else:
            logging.debug("Beide Segmente zu kurz - Rückgabe der ursprünglichen Linie")
            return [line_geom]
            
    except Exception as e:
        logging.warning(f"Fehler beim Teilen der Linie: {e}")
        return [line_geom]


def split_geodataframe_at_virtual_nodes(gdf, virtual_nodes_gdf, dataset_name="Datensatz"):
    """
    Teilt alle Linien eines GeoDataFrames an virtuellen Knotenpunkten.
    Verarbeitet virtuelle Knotenpunkte seriell pro Linie.
    
    Args:
        gdf (GeoDataFrame): Zu splittendes GeoDataFrame mit Liniengeometrien
        virtual_nodes_gdf (GeoDataFrame): Virtuelle Knotenpunkte
        dataset_name (str): Name des Datensatzes für Logging
        
    Returns:
        GeoDataFrame: GeoDataFrame mit aufgeteilten Linien
    """
    logging.info(f"Starte Aufteilung der {dataset_name}-Linien an virtuellen Knotenpunkten...")
    
    result_segments = []
    splits_performed = 0
    lines_affected = 0
    total_lines = len(gdf)
    
    for line_idx, line_row in gdf.iterrows():
        if line_idx % 100 == 0:
            logging.info(f"Verarbeite Linie {line_idx + 1} von {total_lines}")
        
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
    result_gdf = gpd.GeoDataFrame(result_segments, crs=gdf.crs)
    
    logging.info(f"Aufteilung {dataset_name} abgeschlossen:")
    logging.info(f"  Ursprüngliche Linien: {total_lines}")
    logging.info(f"  Resultierende Segmente: {len(result_gdf)}")
    logging.info(f"  Betroffene Linien: {lines_affected}")
    logging.info(f"  Durchgeführte Splits: {splits_performed}")
    
    return result_gdf


def split_rvn_at_virtual_nodes(rvn_gdf, virtual_nodes_gdf):
    """
    Teilt alle Linien des RVN an virtuellen Knotenpunkten.
    Wrapper-Funktion für Abwärtskompatibilität.
    
    Args:
        rvn_gdf (GeoDataFrame): Radvorrangsnetz
        virtual_nodes_gdf (GeoDataFrame): Virtuelle Knotenpunkte
        
    Returns:
        GeoDataFrame: RVN mit aufgeteilten Linien
    """
    return split_geodataframe_at_virtual_nodes(rvn_gdf, virtual_nodes_gdf, "RVN")


def main():
    """
    Hauptfunktion zur Aufteilung des RVN und Detailnetzes an virtuellen Knotenpunkten.
    """
    # Dateipfade definieren
    virtual_nodes_path = 'data/Virtuelle-Knotenpunkte.gpkg'
    
    rvn_path = 'data/Berlin Radvorrangsnetz.fgb'
    rvn_output_path = 'output/rvn/Berlin Radvorrangsnetz_mit_virtuellen-knotenpunkten.fgb'
    
    detailnetz_path = 'data/Berlin Straßenabschnitte Detailnetz.fgb'
    detailnetz_output_path = 'output/rvn/Berlin Detailnetz_mit_virtuellen-knotenpunkten.fgb'
    
    # Stelle sicher, dass das Ausgabeverzeichnis existiert
    os.makedirs(os.path.dirname(rvn_output_path), exist_ok=True)
    
    try:
        # Lade virtuelle Knotenpunkte (einmal für beide Datensätze)
        virtual_nodes_gdf = load_virtual_nodes(virtual_nodes_path)
        
        # 1. RVN splitten
        logging.info("=" * 60)
        logging.info("SCHRITT 1: Radvorrangsnetz splitten")
        logging.info("=" * 60)
        rvn_gdf = load_geodataframe(rvn_path, "Radvorrangsnetz")
        split_rvn = split_geodataframe_at_virtual_nodes(rvn_gdf, virtual_nodes_gdf, "RVN")
        
        logging.info(f"Speichere aufgeteiltes RVN nach {rvn_output_path}")
        split_rvn.to_file(rvn_output_path, driver='FlatGeobuf')
        
        # 2. Detailnetz splitten
        logging.info("")
        logging.info("=" * 60)
        logging.info("SCHRITT 2: Detailnetz splitten")
        logging.info("=" * 60)
        detailnetz_gdf = load_geodataframe(detailnetz_path, "Detailnetz")
        split_detailnetz = split_geodataframe_at_virtual_nodes(detailnetz_gdf, virtual_nodes_gdf, "Detailnetz")
        
        logging.info(f"Speichere aufgeteiltes Detailnetz nach {detailnetz_output_path}")
        split_detailnetz.to_file(detailnetz_output_path, driver='FlatGeobuf')
        
        logging.info("")
        logging.info("=" * 60)
        logging.info("Verarbeitung erfolgreich abgeschlossen!")
        logging.info("=" * 60)
        
    except Exception as e:
        logging.error(f"Fehler bei der Verarbeitung: {e}")
        raise


if __name__ == '__main__':
    main()