import geopandas as gpd
from shapely.geometry import LineString, MultiLineString
from shapely.ops import linemerge
import os
import numpy as np
import logging
from helpers.globals import DEFAULT_OUTPUT_DIR

COMPLEX_CASES_TRESHOL_DEGREE=60
COMPLEX_DIFFERENCE_ANGLE_BETWEEN_OSM_IV=20


def merge_vorrangnetz_lines(vorrangnetz_gdf, output_path=None):
    """
    Verbindet Kanten im Radvorrangsnetz zu einer einzigen Geometrie und speichert das Ergebnis.
    """
    if output_path is None:
        output_path = os.path.join(DEFAULT_OUTPUT_DIR, "vorrangnetz_connected.fgb")
    logging.info("Verbinde Kanten im Radvorrangsnetz...")
    merged_lines_geom = linemerge(vorrangnetz_gdf.geometry.unary_union)
    vorrangnetz_connected_gdf = gpd.GeoDataFrame(geometry=[merged_lines_geom], crs=vorrangnetz_gdf.crs)
    if os.path.exists(output_path):
        os.remove(output_path)
    vorrangnetz_connected_gdf.to_file(output_path, driver='FlatGeobuf')
    logging.info(f"Verbundenes Vorrangnetz gespeichert als {output_path}")
    return vorrangnetz_connected_gdf


def segment_lines(gdf, segment_length, output_path=None):
    """
    Teilt Linien in gleich lange Segmente und speichert sie.
    """
    import logging
    if output_path is None:
        output_path = os.path.join(DEFAULT_OUTPUT_DIR, "vorrangnetz_segments.fgb")
    logging.info(f"Teile verbundenes Netz in {segment_length}m lange Stücke auf...")
    all_segments = []
    for line in gdf.geometry:
        if line.geom_type == 'MultiLineString':
            lines_to_process = line.geoms
        else:
            lines_to_process = [line]
        for single_line in lines_to_process:
            length = single_line.length
            for dist in np.arange(0, length, segment_length):
                start_point = single_line.interpolate(dist)
                end_point = single_line.interpolate(dist + segment_length)
                if not start_point.equals(end_point):
                    all_segments.append(LineString([start_point, end_point]))
    segments_gdf = gpd.GeoDataFrame(geometry=all_segments, crs=gdf.crs)
    if os.path.exists(output_path):
        os.remove(output_path)
    segments_gdf.to_file(output_path, driver='FlatGeobuf')
    logging.info(f"Segmentierte Linien gespeichert als {output_path}")
    return segments_gdf


def filter_short_ways(ways_gdf, short_way_threshold, output_path=None):
    """
    Filtert OSM-Wege, die kürzer als der Schwellenwert sind, und speichert sie.
    """
    if output_path is None:
        output_path = os.path.join(DEFAULT_OUTPUT_DIR, "osm_short_ways.fgb")
    logging.info(f"Wähle OSM-Wege kürzer als {short_way_threshold}m aus...")
    short_ways_gdf = ways_gdf[ways_gdf.geometry.length < short_way_threshold].copy()
    short_ways_gdf = short_ways_gdf.loc[:, ~short_ways_gdf.columns.duplicated()]
    short_ways_gdf.to_file(output_path, driver="FlatGeobuf")
    return short_ways_gdf


def calculate_line_angle(line):
    """
    Berechnet den mittleren Winkel einer Linie in Grad. Funktioniert für LineString und MultiLineString.
    Für MultiLineString wird der Mittelwert der Winkel aller Teilstücke berechnet.
    """
    if line.is_empty or line.length == 0:
        return 0
    angles = []
    # Falls MultiLineString: alle Teilstücke berücksichtigen
    if isinstance(line, MultiLineString):
        for part in line.geoms:
            coords = list(part.coords)
            if len(coords) < 2:
                continue
            start_point, end_point = coords[0], coords[-1]
            angle = np.arctan2(end_point[1] - start_point[1], end_point[0] - start_point[0]) * 180 / np.pi
            angles.append(angle)
        if not angles:
            return 0
        return float(np.mean(angles))
    # LineString
    coords = list(line.coords)
    if len(coords) < 2:
        return 0
    start_point, end_point = coords[0], coords[-1]
    return np.arctan2(end_point[1] - start_point[1], end_point[0] - start_point[0]) * 180 / np.pi


def check_complex_cases(osm_geom, intersecting_segments, angle_osm):
    """
    Überprüft komplexe Fälle, bei denen Segmente im Buffer stark unterschiedliche Winkel haben.
    Ein Weg wird nicht entfernt, wenn er zu mindestens einem Segment fast parallel ist.
    """

    segment_angles = [calculate_line_angle(seg) for seg in intersecting_segments.geometry]
    
    # Normalisiere Winkelunterschiede für den Vergleich
    angle_diffs = []
    for seg_angle in segment_angles:
        diff = abs(angle_osm - seg_angle)
        if diff > 180:
            diff = 360 - diff
        if diff > 90:
            diff = 180 - diff
        angle_diffs.append(diff)

    # Prüfe, ob die maximale Abweichung der Segmente untereinander groß ist
    if not angle_diffs:
        return True # Sollte nicht passieren, aber zur Sicherheit

    max_segment_angle_diff = 0
    if len(segment_angles) > 1:
        # Berechne die maximale Winkeldifferenz zwischen den Segmenten
        # Dies ist eine Annäherung, die die Varianz der Winkel prüft
        min_angle, max_angle = min(segment_angles), max(segment_angles)
        diff = abs(min_angle - max_angle)
        if diff > 180:
            diff = 360 - diff
        max_segment_angle_diff = diff

    if max_segment_angle_diff > COMPLEX_CASES_TRESHOL_DEGREE:
        # Wenn es eine große Varianz gibt, prüfe, ob ein Segment fast parallel ist
        if any(diff < COMPLEX_DIFFERENCE_ANGLE_BETWEEN_OSM_IV for diff in angle_diffs):
            return False  # Nicht entfernen, da ein Segment fast parallel ist
    
    return True # Im Normalfall oder wenn kein Segment parallel ist, weiter prüfen


def filter_orthogonal_short_ways(short_ways_gdf, segments_gdf, angle_diff_threshold, buffer_meters):
    """
    Identifiziert kurze OSM-Wege, die orthogonal zum Vorrangnetz verlaufen.
    Gibt die IDs der zu entfernenden Wege zurück.
    """
    print(f"Wende Orthogonalitätsfilter auf {len(short_ways_gdf)} kurze Wege an...")
    final_short_ids = set()
    if not short_ways_gdf.empty and not segments_gdf.empty:
        # Erzeuge einen räumlichen Index für die Segmente des Vorrangnetzes
        segments_sindex = segments_gdf.sindex
        for _, row in short_ways_gdf.iterrows():
            osm_geom = row.geometry
            if osm_geom.is_empty or osm_geom.length == 0:
                continue
            # Schritt 1: Erzeuge einen Buffer um den OSM-Weg
            buffer_geom = osm_geom.buffer(buffer_meters)
            # Schritt 2: Finde alle Segmente des Vorrangnetzes, die im Buffer liegen
            possible_matches_index = list(segments_sindex.intersection(buffer_geom.bounds))
            possible_matches = segments_gdf.iloc[possible_matches_index]
            intersecting_segments = possible_matches[possible_matches.intersects(buffer_geom)]
            if intersecting_segments.empty:
                continue

            # Winkel der OSM-Linie berechnen
            angle_osm = calculate_line_angle(osm_geom)

            # Neue Überprüfung für komplexe Fälle
            if not check_complex_cases(osm_geom, intersecting_segments, angle_osm):
                continue

            # Schritt 3: Vereine die gefundenen Segmente zu einer Linie
            unioned_geom = intersecting_segments.geometry.unary_union
            merged_line = None
            if unioned_geom.geom_type == 'LineString':
                merged_line = unioned_geom
            elif unioned_geom.geom_type == 'MultiLineString':
                merged_line_candidate = linemerge(unioned_geom)
                if merged_line_candidate.geom_type == 'LineString':
                    merged_line = merged_line_candidate
                elif merged_line_candidate.geom_type == 'MultiLineString':
                    merged_line = max(merged_line_candidate.geoms, key=lambda line: line.length)
            if not merged_line or merged_line.is_empty or merged_line.geom_type != 'LineString':
                continue
            # Schritt 4: Berechne die Winkel der OSM-Linie und des Vorrangnetz-Segments
            angle_segment_network = calculate_line_angle(merged_line)
            angle_diff = abs(angle_osm - angle_segment_network)
            # Schritt 5: Normalisiere den Winkelunterschied auf den Bereich [0, 90]
            if angle_diff > 180:
                angle_diff = 360 - angle_diff
            if angle_diff > 90:
                angle_diff = 180 - angle_diff
            # Schritt 6: Wenn der Winkelunterschied größer als der Schwellwert ist, markiere den Weg als querend
            if angle_diff > angle_diff_threshold:
                way_id = row.get('osm_id') or row.get('id')
                if way_id is not None:
                    final_short_ids.add(way_id)
    print(f"{len(final_short_ids)} kurze Wege als querend identifiziert und zum Entfernen markiert.")
    return final_short_ids


def process_and_filter_short_segments(
    vorrangnetz_gdf,
    osm_gdf,
    output_prefix, # z.B. 'bikelanes' oder 'streets'
    short_way_threshold=50, # Länge in Metern
    segment_length=5, # Länge eines Segments in Meter
    angle_diff_threshold=50, # in Grad
    buffer_meters=25 # Buffer in Metern
):
    """
    Orchestriert die Schritte: Mergen, Segmentieren, Filtern und Exportieren.
    """
    # 1. Vorrangnetz verbinden
    vorrangnetz_connected_gdf = merge_vorrangnetz_lines(vorrangnetz_gdf, './output/vorrangnetz_connected.fgb')
    # 2. Segmentieren
    segments_output_path = './output/vorrangnetz_segments.fgb'
    if os.path.exists(segments_output_path):
        print(f"Lade segmentierte Linien aus {segments_output_path}...")
        segments_gdf = gpd.read_file(segments_output_path)
    else:
        segments_gdf = segment_lines(vorrangnetz_connected_gdf, segment_length, segments_output_path)
    # 3. Kurze OSM-Wege filtern
    short_osm_output_path = f"./output/osm_{output_prefix}_orthogonal_all_ways.fgb"
    short_osm_gdf = filter_short_ways(osm_gdf, short_way_threshold, short_osm_output_path)
    # 4. Orthogonale kurze Wege identifizieren
    final_short_ids = filter_orthogonal_short_ways(short_osm_gdf, segments_gdf, angle_diff_threshold, buffer_meters)
    # 5. Exportiere herausgefilterte Wege
    removed_output_path = f"./output/osm_{output_prefix}_orthogonal_removed.fgb"
    export_filtered_ways(osm_gdf, final_short_ids, removed_output_path)
    return final_short_ids

def export_filtered_ways(osm_gdf, filtered_ids, output_path):
    """
    Exportiert alle OSM-Wege mit IDs in filtered_ids als FlatGeobuf.
    """
    id_col = 'osm_id' if 'osm_id' in osm_gdf.columns else 'id'
    filtered_gdf = osm_gdf[osm_gdf[id_col].isin(filtered_ids)].copy()
    filtered_gdf = filtered_gdf.loc[:, ~filtered_gdf.columns.duplicated()]
    filtered_gdf.to_file(output_path, driver="FlatGeobuf")
    print(f"Exportierte {len(filtered_gdf)} herausgefilterte Wege nach {output_path}")
