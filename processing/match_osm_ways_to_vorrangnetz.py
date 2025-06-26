import geopandas as gpd
from shapely.geometry import LineString, Point
import sys
import numpy as np
import argparse
import os

# Konfiguration
OSM_FGB = './data/bikelanes.fgb'  # Pfad zu OSM-Radwege
VORRANGNETZ_FGB = './data/Berlin Radvorrangsnetz.fgb'  # Pfad zum Vorrangnetz
BUFFER_METERS = 30  # Buffer-Radius in Metern
OUTPUT_FILE = './output/matched_osm_way_ids.txt'

def main():
    parser = argparse.ArgumentParser(description="Match OSM ways to Vorrangnetz with optional filters.")
    parser.add_argument('--orthogonal', action='store_true', help='Enable orthogonality filtering (second step)')
    args = parser.parse_args()

    print('Lade OSM-Radwege...')
    osm_gdf = gpd.read_file(OSM_FGB)
    print(f'OSM-Radwege geladen: {len(osm_gdf)} Features')

    print('Lade Vorrangnetz...')
    vorrangnetz_gdf = gpd.read_file(VORRANGNETZ_FGB)
    print(f'Vorrangnetz geladen: {len(vorrangnetz_gdf)} Features')

    # Prüfe CRS und transformiere auf metrisches CRS (z.B. EPSG:25833 für Berlin)
    target_crs = 'EPSG:25833'
    if osm_gdf.crs != target_crs:
        osm_gdf = osm_gdf.to_crs(target_crs)
    if vorrangnetz_gdf.crs != target_crs:
        vorrangnetz_gdf = vorrangnetz_gdf.to_crs(target_crs)

    # Erzeuge Buffer um Vorrangnetz-Kanten
    print(f'Erzeuge Buffer von {BUFFER_METERS}m um Vorrangnetz-Kanten...')
    vorrangnetz_buffer = vorrangnetz_gdf.buffer(BUFFER_METERS)

    # --- METHODISCHE KORREKTUR: Alle Buffer zu einer Geometrie vereinen ---
    print('Vereine alle Buffer zu einer einzigen Geometrie...')
    unified_buffer = vorrangnetz_buffer.unary_union
    unified_buffer_gdf = gpd.GeoDataFrame(geometry=[unified_buffer], crs=target_crs)

    # --- Finde alle OSM-Wege, die im vereinten Buffer liegen (räumlicher Join) ---
    print('Finde alle OSM-Wege, die den vereinten Buffer schneiden...')
    # Alternative 1: Prüfe, ob der Großteil der OSM-Linie im Buffer liegt (z.B. >70% der Länge)
    def line_in_buffer_fraction(line, buffer_geom):
        if line.is_empty or line.length == 0:
            return 0
        intersected = line.intersection(buffer_geom)
        return intersected.length / line.length if not intersected.is_empty else 0

    FRACTION_THRESHOLD = 0.7  # Mindestens 70% der Linie müssen im Buffer liegen

    mask = osm_gdf.geometry.apply(lambda geom: line_in_buffer_fraction(geom, unified_buffer) >= FRACTION_THRESHOLD)
    matched_gdf_step1 = osm_gdf[mask].copy()

    print(f'Gefundene OSM-Way-IDs nach erstem Filter: {len(matched_gdf_step1)}')

    # Entferne doppelte Spaltennamen, falls vorhanden (vor dem Speichern!)
    # Speichere das Ergebnis nach dem ersten Schritt als FlatGeoBuf
    buffering_path = './output/bikelanes_in_buffering.fgb'
    if os.path.exists(buffering_path):
        os.remove(buffering_path)
    matched_gdf_step1 = matched_gdf_step1.loc[:, ~matched_gdf_step1.columns.duplicated()]
    matched_gdf_step1.to_file(buffering_path, driver='FlatGeoBuf')
    print('Bikelanes im Buffer gespeichert als ./output/bikelanes_in_buffering.fgb')

    # Optional: Orthogonalitäts-Filter anwenden
    if args.orthogonal:
        print("Wende Orthogonalitäts-Filter an...")
        PROJECTION_RATIO_THRESHOLD = 0.3  # OSM-Weg muss zu 30% in Richtung Vorrangnetz verlaufen
        final_matched_ids = set()
        if not matched_gdf_step1.empty:
            joined_gdf = gpd.sjoin_nearest(matched_gdf_step1, vorrangnetz_gdf, how='inner', rsuffix='vrr')
            for _, row in joined_gdf.iterrows():
                osm_geom = row.geometry
                vorrang_index = row['index_vrr']
                vorrang_geom = vorrangnetz_gdf.loc[vorrang_index].geometry
                if osm_geom.is_empty or vorrang_geom.is_empty or osm_geom.length == 0:
                    continue
                try:
                    start_p = Point(osm_geom.coords[0])
                    end_p = Point(osm_geom.coords[-1])
                    proj_start_dist = vorrang_geom.project(start_p)
                    proj_end_dist = vorrang_geom.project(end_p)
                    projection_len = abs(proj_end_dist - proj_start_dist)
                    ratio = projection_len / osm_geom.length
                    if ratio >= PROJECTION_RATIO_THRESHOLD:
                        way_id = row.get('osm_id') or row.get('id')
                        if way_id is not None:
                            final_matched_ids.add(way_id)
                except Exception:
                    continue
        print(f'Gefundene OSM-Way-IDs nach Orthogonalitäts-Filter: {len(final_matched_ids)}')
        id_col = 'osm_id' if 'osm_id' in osm_gdf.columns else 'id'
        matched_gdf = osm_gdf[osm_gdf[id_col].isin(final_matched_ids)]
    else:
        print("Orthogonalitäts-Filter übersprungen.")
        id_col = 'osm_id' if 'osm_id' in matched_gdf_step1.columns else 'id'
        matched_gdf = matched_gdf_step1

    # Entferne doppelte Spaltennamen, die durch sjoin entstehen können
    if 'index_right' in matched_gdf.columns:
        matched_gdf = matched_gdf.drop(columns=['index_right'])
    matched_gdf = matched_gdf.loc[:,~matched_gdf.columns.duplicated()]

    # Schreibe GeoJSON
    geojson_file = './output/matched_osm_ways.geojson'
    matched_gdf.to_file(geojson_file, driver='GeoJSON')
    print(f'GeoJSON gespeichert in {geojson_file}')

    # Optional: Schreibe weiterhin die Textliste
    with open('./output/matched_osm_way_ids.txt', 'w') as f:
        for way_id in sorted(matched_gdf[id_col].unique()):
            f.write(f'{way_id}\n')
    print(f'Ergebnis gespeichert in ./output/matched_osm_way_ids.txt')

    # Speichere das gebufferte Vorrangnetz zur Kontrolle
    buffered_gdf = gpd.GeoDataFrame(geometry=[unified_buffer], crs=target_crs)
    buffered_gdf.to_file('./output/vorrangnetz_buffered.fgb', driver='FlatGeobuf')
    print('Gebuffertes Vorrangnetz gespeichert als ./output/vorrangnetz_buffered.fgb')


if __name__ == '__main__':
    main()
