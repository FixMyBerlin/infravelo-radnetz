import geopandas as gpd
from shapely.geometry import LineString, Point
import sys
import numpy as np
import argparse
import os
from orthogonal_filter import  process_and_filter_short_segments
import pandas as pd

# Konfiguration
OSM_FGB = './data/bikelanes.fgb'  # Pfad zu OSM-Radwege
VORRANGNETZ_FGB = './data/Berlin Radvorrangsnetz.fgb'  # Pfad zum Vorrangnetz
BUFFER_METERS = 30  # Buffer-Radius in Metern
OUTPUT_FILE = './output/matched_osm_way_ids.txt'

def main():
    parser = argparse.ArgumentParser(description="Match OSM ways to Vorrangnetz with optional filters.")
    parser.add_argument('--orthogonalfilter', action='store_true', help='Enable orthogonality filtering (second step)')
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

    # --- Finde alle OSM-Wege, die im vereinten Buffer liegen (oder lade aus Cache) ---
    buffering_path = './output/bikelanes_in_buffering.fgb'

    if os.path.exists(buffering_path):
        print(f'Lade zwischengespeichertes Ergebnis aus {buffering_path}...')
        matched_gdf_step1 = gpd.read_file(buffering_path)
    else:
        print('Finde alle OSM-Wege, die den vereinten Buffer schneiden (dies kann dauern)...')
        
        def line_in_buffer_fraction(line, buffer_geom):
            if line.is_empty or line.length == 0:
                return 0
            intersected = line.intersection(buffer_geom)
            return intersected.length / line.length if not intersected.is_empty else 0

        FRACTION_THRESHOLD = 0.7  # Mindestens 70% der Linie müssen im Buffer liegen

        mask = osm_gdf.geometry.apply(lambda geom: line_in_buffer_fraction(geom, unified_buffer) >= FRACTION_THRESHOLD)
        matched_gdf_step1 = osm_gdf[mask].copy()

        # Entferne doppelte Spaltennamen vor dem Speichern
        matched_gdf_step1 = matched_gdf_step1.loc[:, ~matched_gdf_step1.columns.duplicated()]
        
        # Speichere das Ergebnis für die zukünftige Verwendung
        matched_gdf_step1.to_file(buffering_path, driver='FlatGeobuf')
        print(f'Zwischenergebnis gespeichert in {buffering_path}')

    print(f'Gefundene OSM-Way-IDs nach erstem Filter: {len(matched_gdf_step1)}')

    # Optional: Orthogonalitäts-Filter anwenden
    if args.orthogonalfilter:
        print("Wende Orthogonalitäts-Filter für kurze Segmente an...")
        
        # IDs aus dem ersten groben Filter (Buffer)
        id_col_step1 = 'osm_id' if 'osm_id' in matched_gdf_step1.columns else 'id'
        step1_ids = set(matched_gdf_step1[id_col_step1])

        # Zusätzliche kurze Wege durch Orthogonalitäts-Check finden
        # Diese Funktion arbeitet auf dem *gesamten* OSM-Datensatz, um kurze Wege zu finden,
        # die möglicherweise nicht im Buffer lagen, aber relevant sind.
        short_way_ids = process_and_filter_short_segments(
            vorrangnetz_gdf=vorrangnetz_gdf,
            osm_gdf=osm_gdf
        )

        # Kombiniere die IDs aus beiden Schritten
        final_way_ids = step1_ids.union(short_way_ids)
        
        # Erstelle das finale GeoDataFrame aus dem ursprünglichen OSM-Set
        id_col_osm = 'osm_id' if 'osm_id' in osm_gdf.columns else 'id'
        matched_gdf = osm_gdf[osm_gdf[id_col_osm].isin(final_way_ids)].copy()
        id_col = id_col_osm
        
        print(f"Gesamtzahl der gematchten Wege nach Kombination: {len(matched_gdf)}")

    else:
        print("Orthogonalitäts-Filter übersprungen.")
        id_col = 'osm_id' if 'osm_id' in matched_gdf_step1.columns else 'id'
        matched_gdf = matched_gdf_step1

    # Entferne doppelte Spaltennamen, die durch sjoin entstehen können
    if 'index_right' in matched_gdf.columns:
        matched_gdf = matched_gdf.drop(columns=['index_right'])
    matched_gdf = matched_gdf.loc[:,~matched_gdf.columns.duplicated()]

    # Schreibe FlatGeobuf
    fgb_file = './output/matched_osm_ways.fgb'
    matched_gdf.to_file(fgb_file, driver='FlatGeobuf')
    print(f'FlatGeobuf gespeichert in {fgb_file}')

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
