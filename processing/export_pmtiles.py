import os
import subprocess
import glob
import geopandas as gpd

def export_all_pmtiles():
    OUTPUT_DIR = './output'
    TARGET_DIR = './inspector/public/data'
    LAYER_NAME = 'default'
    WGS84_EPSG = 4326

    os.makedirs(TARGET_DIR, exist_ok=True)

    fgb_files = glob.glob(os.path.join(OUTPUT_DIR, '*.fgb'))

    for fgb_file in fgb_files:
        gdf = gpd.read_file(fgb_file)
        gdf = gdf.to_crs(epsg=WGS84_EPSG)
        temp_fgb = fgb_file + '.wgs84.fgb'
        gdf.to_file(temp_fgb, driver='FlatGeobuf')
        input_file = temp_fgb
        base = os.path.splitext(os.path.basename(fgb_file))[0]
        pmtiles_file = os.path.join(TARGET_DIR, f'{base}.pmtiles')
        geojson_file = os.path.join(TARGET_DIR, f'{base}.geojson')
        print(f'Running tippecanoe for {input_file}...')
        subprocess.run([
            'tippecanoe', '--output', pmtiles_file, '--layer', LAYER_NAME, '--force', input_file
        ], check=True)
        print(f'Output: {pmtiles_file}')
        gdf.to_file(geojson_file, driver='GeoJSON')
        print(f'GeoJSON written: {geojson_file}')
        os.remove(input_file)

    print('All .fgb files processed.')

if __name__ == '__main__':
    export_all_pmtiles()
