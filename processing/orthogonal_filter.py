import geopandas as gpd
from shapely.geometry import Point, LineString
from shapely.ops import linemerge
import os
import numpy as np


def process_and_filter_short_segments(
    vorrangnetz_gdf,
    osm_gdf,
    short_way_threshold=35,
    segment_length=5,
    projection_ratio_threshold=0.2,
    angle_diff_threshold=50,
    buffer_meters=50
):
    """
    Verbindet das Vorrangnetz, segmentiert es und filtert kurze, orthogonale OSM-Wege.
    Die Parameter angle_diff_threshold (Grad) und buffer_meters (Meter) sind konfigurierbar.
    """
    # 1. Kanten im Radvorrangsnetz verbinden, um ein zusammenhängendes Netz zu erhalten
    print("Verbinde Kanten im Radvorrangsnetz...")
    merged_lines_geom = linemerge(vorrangnetz_gdf.geometry.unary_union)
    vorrangnetz_verbunden_gdf = gpd.GeoDataFrame(geometry=[merged_lines_geom], crs=vorrangnetz_gdf.crs)

        # Speichern des Zwischenergebnisses
    output_path = './output/_vorrangnetz_verbunden.fgb'
    if os.path.exists(output_path):
        os.remove(output_path)
    vorrangnetz_verbunden_gdf.to_file(output_path, driver='FlatGeobuf')
    print(f"Verbundenes Vorrangnetz gespeichert als {output_path}")

    # 2. Das verbundene Netz in gleich lange Segmente (z.B. 5m) aufteilen
    #    Dies ermöglicht eine feinere Analyse der Orientierung von kurzen OSM-Wege zu lokalen Netzabschnitten
    segments_output_path = './output/vorrangnetz_segments.fgb'
    if os.path.exists(segments_output_path):
        print(f"Lade segmentierte Linien aus {segments_output_path}...")
        segments_gdf = gpd.read_file(segments_output_path)
    else:
        print(f"Teile verbundenes Netz in {segment_length}m lange Stücke auf...")
        all_segments = []
        for line in vorrangnetz_verbunden_gdf.geometry:
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

        segments_gdf = gpd.GeoDataFrame(geometry=all_segments, crs=vorrangnetz_gdf.crs)
        # 3. Die erzeugten Segmente als FlatGeobuf speichern (optional, für Debugging/Analyse)
        if os.path.exists(segments_output_path):
            os.remove(segments_output_path)
        segments_gdf.to_file(segments_output_path, driver='FlatGeobuf')
        print(f"Segmentierte Linien gespeichert als {segments_output_path}")

    # 4. Auswahl aller OSM-Wege, die kürzer als der Schwellenwert sind
    #    Diese kurzen Wege sind oft Querungen oder kleine Verbindungen, die besonders geprüft werden sollen
    print(f"Wähle OSM-Wege kürzer als {short_way_threshold}m aus...")
    short_osm_gdf = osm_gdf[osm_gdf.geometry.length < short_way_threshold].copy()
    short_osm_gdf = short_osm_gdf.loc[:, ~short_osm_gdf.columns.duplicated()]
    short_osm_gdf.to_file("./output/short_osm_wege.fgb", driver="FlatGeobuf")

    # 5. Für jeden kurzen OSM-Weg: Prüfe die Ausrichtung im Vergleich zum lokalen Vorrangnetz
    print(f"Wende Orthogonalitätsfilter auf {len(short_osm_gdf)} kurze Wege an...")

    def calculate_line_angle(line):
        """Berechnet den Winkel einer Linie in Grad."""
        if line.is_empty or line.length == 0:
            return 0
        coords = list(line.coords)
        start_point, end_point = coords[0], coords[-1]
        return np.arctan2(end_point[1] - start_point[1], end_point[0] - start_point[0]) * 180 / np.pi

    # final_short_ids enthält die IDs der Wege, die aufgrund ihrer orthogonalen Ausrichtung entfernt werden.
    final_short_ids = set()

    if not short_osm_gdf.empty and not segments_gdf.empty:
        segments_sindex = segments_gdf.sindex

        for _, row in short_osm_gdf.iterrows():
            osm_geom = row.geometry
            if osm_geom.is_empty or osm_geom.length == 0:
                continue

            # 1. Puffer um den OSM-Weg
            buffer_geom = osm_geom.buffer(buffer_meters)

            # 2. Segmente des Radvorrangnetzes im Puffer selektieren
            possible_matches_index = list(segments_sindex.intersection(buffer_geom.bounds))
            possible_matches = segments_gdf.iloc[possible_matches_index]
            intersecting_segments = possible_matches[possible_matches.intersects(buffer_geom)]

            if intersecting_segments.empty:
                continue

            # 3. Vektor aus den selektierten Segmenten bilden
            unioned_geom = intersecting_segments.geometry.unary_union
            merged_line = None  # Initialisieren

            if unioned_geom.geom_type == 'LineString':
                merged_line = unioned_geom
            elif unioned_geom.geom_type == 'MultiLineString':
                # linemerge kann eine MultiLineString zurückgeben, wenn die Linien nicht zusammenhängend sind
                merged_line_candidate = linemerge(unioned_geom)
                if merged_line_candidate.geom_type == 'LineString':
                    merged_line = merged_line_candidate
                elif merged_line_candidate.geom_type == 'MultiLineString':
                    # Wenn es immer noch eine MultiLineString ist, nimm das längste Stück
                    merged_line = max(merged_line_candidate.geoms, key=lambda line: line.length)

            if not merged_line or merged_line.is_empty or merged_line.geom_type != 'LineString':
                continue

            # 4. Winkel berechnen und Differenz prüfen
            angle_osm = calculate_line_angle(osm_geom)
            angle_segment_network = calculate_line_angle(merged_line)

            angle_diff = abs(angle_osm - angle_segment_network)
            if angle_diff > 180:
                angle_diff = 360 - angle_diff
            if angle_diff > 90:
                angle_diff = 180 - angle_diff

            # 5. Wenn Winkel > angle_diff_threshold Grad, Segment zum Entfernen vormerken
            if angle_diff > angle_diff_threshold:
                way_id = row.get('osm_id') or row.get('id')
                if way_id is not None:
                    final_short_ids.add(way_id)
    
    print(f"{len(final_short_ids)} kurze Wege als querend identifiziert und zum Entfernen markiert.")
    # Exportiere herausgefilterte Wege als FlatGeobuf
    export_filtered_ways(osm_gdf, final_short_ids, "./output/short_osm_herausgefiltert.fgb")
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
