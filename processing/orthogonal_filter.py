import geopandas as gpd
from shapely.geometry import Point, LineString
from shapely.ops import linemerge
import os
import numpy as np


def process_and_filter_short_segments(vorrangnetz_gdf, osm_gdf, short_way_threshold=35, segment_length=5, projection_ratio_threshold=0.2):
    """
    Verbindet das Vorrangnetz, segmentiert es und filtert kurze, orthogonale OSM-Wege.
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

    # 5. Für jeden kurzen OSM-Weg: Finde das nächste Netzsegment und prüfe die Orientierung
    #    Die Projektion der Endpunkte des OSM-Wegs auf das Segment wird berechnet
    #    Nur wenn der projizierte Anteil groß genug ist (d.h. der Weg verläuft nicht orthogonal), wird er behalten
    print(f"Wende Orthogonalitätsfilter auf {len(short_osm_gdf)} kurze Wege an...")
    final_short_ids = set()
    if not short_osm_gdf.empty and not segments_gdf.empty:
        joined_gdf = gpd.sjoin_nearest(short_osm_gdf, segments_gdf, how='inner', rsuffix='seg')

        for _, row in joined_gdf.iterrows():
            osm_geom = row.geometry
            # Finde die ursprüngliche Segmentgeometrie basierend auf dem Index
            segment_geom = segments_gdf.loc[row['index_seg']].geometry

            if osm_geom.is_empty or segment_geom.is_empty or osm_geom.length == 0:
                continue

            try:
                start_p = Point(osm_geom.coords[0])
                end_p = Point(osm_geom.coords[-1])
                proj_start_dist = segment_geom.project(start_p)
                proj_end_dist = segment_geom.project(end_p)
                projection_len = abs(proj_end_dist - proj_start_dist)
                ratio = projection_len / osm_geom.length
                
                # Nur Wege behalten, die nicht zu orthogonal zum Segment verlaufen
                if ratio >= projection_ratio_threshold:
                    way_id = row.get('osm_id') or row.get('id')
                    if way_id is not None:
                        final_short_ids.add(way_id)
            except Exception:
                continue
    
    print(f"{len(final_short_ids)} kurze Wege herausgefiltert.")
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
