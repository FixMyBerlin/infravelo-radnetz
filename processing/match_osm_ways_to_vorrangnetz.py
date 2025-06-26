import geopandas as gpd
from shapely.geometry import LineString
import sys

# Konfiguration
OSM_FGB = './data/bikelanes.fgb'  # Pfad zu OSM-Radwege
VORRANGNETZ_FGB = './data/Berlin Radvorrangsnetz.fgb'  # Pfad zum Vorrangnetz
BUFFER_METERS = 20  # Buffer-Radius in Metern
OUTPUT_FILE = 'matched_osm_way_ids.txt'


def main():
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
        # Extrahiere OSM-Way-IDs (angenommen Attribut heißt 'osm_id' oder 'id')
        for _, row in precise_matches.iterrows():
            way_id = row.get('osm_id') or row.get('id')
            if way_id is not None:
                matched_ids.add(way_id)
        if (i+1) % 100 == 0:
            print(f'...{i+1} Vorrangnetz-Kanten verarbeitet')

    print(f'Gefundene OSM-Way-IDs: {len(matched_ids)}')
    # Filtere OSM-GDF auf gematchte IDs
    id_col = 'osm_id' if 'osm_id' in osm_gdf.columns else 'id'
    matched_gdf = osm_gdf[osm_gdf[id_col].isin(matched_ids)]
    # Entferne doppelte Spaltennamen, falls vorhanden
    matched_gdf = matched_gdf.loc[:,~matched_gdf.columns.duplicated()]
    # Schreibe GeoJSON
    geojson_file = 'matched_osm_ways.geojson'
    matched_gdf.to_file(geojson_file, driver='GeoJSON')
    print(f'GeoJSON gespeichert in {geojson_file}')
    # Optional: Schreibe weiterhin die Textliste
    with open(OUTPUT_FILE, 'w') as f:
        for way_id in sorted(matched_ids):
            f.write(f'{way_id}\n')
    print(f'Ergebnis gespeichert in {OUTPUT_FILE}')


if __name__ == '__main__':
    main()
