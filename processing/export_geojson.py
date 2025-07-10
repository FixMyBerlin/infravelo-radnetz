import os
import glob
import geopandas as gpd
from processing.helpers.globals import DEFAULT_CRS, DEFAULT_OUTPUT_DIR

def export_all_geojson():
    OUTPUT_DIR = DEFAULT_OUTPUT_DIR
    TARGET_DIR = './output-static-data-transfer'
    os.makedirs(TARGET_DIR, exist_ok=True)
    # Write .gitignore to ignore all .geojson files
    gitignore_path = os.path.join(TARGET_DIR, '.gitignore')
    with open(gitignore_path, 'w') as f:
        f.write('*.geojson\n')

    fgb_files = glob.glob(os.path.join(OUTPUT_DIR, '*.fgb'))

    for fgb_file in fgb_files:
        gdf = gpd.read_file(fgb_file)
        # Ensure CRS is WGS84 for GeoJSON
        if gdf.crs is not None and gdf.crs.to_string() != 'EPSG:4326':
            gdf = gdf.to_crs('EPSG:4326')
        base = os.path.splitext(os.path.basename(fgb_file))[0]
        geojson_file = os.path.join(TARGET_DIR, f'{base}.geojson')
        gdf.to_file(geojson_file, driver='GeoJSON')
        print(f'GeoJSON written: {geojson_file}')

    print('All .fgb files exported as .geojson.')

if __name__ == '__main__':
    export_all_geojson()
