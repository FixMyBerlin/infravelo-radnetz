import geopandas as gpd
from shapely.geometry import LineString, Point
import sys
import numpy as np
from scipy.spatial.distance import directed_hausdorff
import argparse

# Konfiguration
OSM_FGB = './data/bikelanes.fgb'  # Pfad zu OSM-Radwege
VORRANGNETZ_FGB = './data/Berlin Radvorrangsnetz.fgb'  # Pfad zum Vorrangnetz
BUFFER_METERS = 100  # Buffer-Radius in Metern
OUTPUT_FILE = './output/matched_osm_way_ids.txt'
HAUSDORFF_THRESHOLD = 1500  # Meter, sinnvoller Startwert für "ähnliche" Linien


def parse_args():
    parser = argparse.ArgumentParser(description='Match OSM-Ways zum Radvorrangsnetz')
    parser.add_argument('--hausdorff', action='store_true', help='Hausdorff-Distanz-Filter aktivieren')
    return parser.parse_args()


def main():
    args = parse_args()
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

    # Baue räumlichen Index für OSM-Radwege
    print('Baue räumlichen Index für OSM-Radwege...')
    osm_sindex = osm_gdf.sindex

    matched_ids = set()
    print('Starte Matching...')
    for i, buffer_geom in enumerate(vorrangnetz_buffer):
        if buffer_geom is None or buffer_geom.is_empty:
            continue
        # Finde OSM-Radwege, die den Buffer schneiden
        possible_matches_index = list(osm_sindex.intersection(buffer_geom.bounds))
        possible_matches = osm_gdf.iloc[possible_matches_index]
        precise_matches = possible_matches[possible_matches.intersects(buffer_geom)]
        vorrang_geom = vorrangnetz_gdf.iloc[i].geometry
        if vorrang_geom.geom_type == 'MultiLineString':
            vorrang_lines = list(vorrang_geom.geoms)
        else:
            vorrang_lines = [vorrang_geom]
        for _, row in precise_matches.iterrows():
            way_id = row.get('osm_id') or row.get('id')
            if way_id is None:
                continue
            candidate_geom = row.geometry
            if candidate_geom.geom_type == 'MultiLineString':
                candidate_lines = list(candidate_geom.geoms)
            else:
                candidate_lines = [candidate_geom]
            # Vergleiche alle Liniensegmente (bei MultiLineString)
            match_found = False
            for vg in vorrang_lines:
                for cg in candidate_lines:
                    if args.hausdorff:
                        try:
                            coords1 = np.array(vg.coords)
                            coords2 = np.array(cg.coords)
                            d1 = directed_hausdorff(coords1, coords2)[0]
                            d2 = directed_hausdorff(coords2, coords1)[0]
                            hausdorff_dist = max(d1, d2)
                        except Exception:
                            continue
                        if hausdorff_dist > HAUSDORFF_THRESHOLD:
                            continue
                    matched_ids.add(way_id)
                    match_found = True
                    break
                if match_found:
                    break
        if (i+1) % 100 == 0:
            print(f'...{i+1} Vorrangnetz-Kanten verarbeitet')

    print(f'Gefundene OSM-Way-IDs nach erstem Filter: {len(matched_ids)}')
    # Filtere OSM-GDF auf gematchte IDs
    id_col = 'osm_id' if 'osm_id' in osm_gdf.columns else 'id'
    matched_gdf_step1 = osm_gdf[osm_gdf[id_col].isin(matched_ids)]

    # --- ZWEITER SCHRITT: PROJEKTIONS-FILTER GEGEN ORTHOGONALE WEGE ---
    print('Starte zweiten Filter-Schritt (Projektionslänge)...')
    PROJECTION_RATIO_THRESHOLD = 0.3  # OSM-Weg muss zu 30% in Richtung Vorrangnetz verlaufen

    final_matched_ids = set()
    if not matched_gdf_step1.empty:
        # Finde für jeden gematchten Weg den nächsten Vorrangnetz-Weg
        joined_gdf = gpd.sjoin_nearest(matched_gdf_step1, vorrangnetz_gdf, how='inner', rsuffix='vrr')

        for _, row in joined_gdf.iterrows():
            osm_geom = row.geometry
            vorrang_index = row['index_vrr']
            vorrang_geom = vorrangnetz_gdf.loc[vorrang_index].geometry

            if osm_geom.is_empty or vorrang_geom.is_empty or osm_geom.length == 0:
                continue

            # Projiziere Start- und Endpunkt des OSM-Wegs auf den Vorrangnetz-Weg
            try:
                start_p = Point(osm_geom.coords[0])
                end_p = Point(osm_geom.coords[-1])
                
                proj_start_dist = vorrang_geom.project(start_p)
                proj_end_dist = vorrang_geom.project(end_p)
                
                projection_len = abs(proj_end_dist - proj_start_dist)
                ratio = projection_len / osm_geom.length
                
                # Behalte den Weg, wenn der Ratio über dem Schwellenwert liegt
                if ratio >= PROJECTION_RATIO_THRESHOLD:
                    way_id = row.get('osm_id') or row.get('id')
                    if way_id is not None:
                        final_matched_ids.add(way_id)
            except Exception:
                continue
    
    print(f'Gefundene OSM-Way-IDs nach zweitem Filter: {len(final_matched_ids)}')
    matched_gdf = osm_gdf[osm_gdf[id_col].isin(final_matched_ids)]

    # Entferne doppelte Spaltennamen, falls vorhanden
    matched_gdf = matched_gdf.loc[:,~matched_gdf.columns.duplicated()]
    # Schreibe GeoJSON
    geojson_file = './output/matched_osm_ways.geojson'
    matched_gdf.to_file(geojson_file, driver='GeoJSON')
    print(f'GeoJSON gespeichert in {geojson_file}')
    # Optional: Schreibe weiterhin die Textliste
    with open(OUTPUT_FILE, 'w') as f:
        for way_id in sorted(matched_ids):
            f.write(f'{way_id}\n')
    print(f'Ergebnis gespeichert in {OUTPUT_FILE}')

    # Gebuffertes Vorrangnetz als FlatGeoBuf speichern
    buffered_gdf = vorrangnetz_gdf.copy()
    buffered_gdf['geometry'] = vorrangnetz_buffer
    buffered_gdf.to_file('./output/vorrangnetz_buffered.flatgeobuf', driver='FlatGeobuf')
    print('Gebuffertes Vorrangnetz gespeichert als ./output/vorrangnetz_buffered.flatgeobuf')


if __name__ == '__main__':
    main()
