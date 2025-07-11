from helpers.globals import DEFAULT_CRS
import geopandas as gpd
import os

BUFFER_METERS = 35  # Buffer-Radius in Metern für die Differenzbildung


def difference_streets_without_bikelanes(streets_gdf, bikelanes_gdf, target_crs=None):
    """
    Gibt nur die Teile der Straßen zurück, die nicht im Buffer (BUFFER_METERS) um Radwege liegen.
    Ein Buffer wird um alle Radwege gelegt, und alle Straßen, die diesen Buffer schneiden, werden entfernt.
    target_crs: CRS string (e.g. 'EPSG:25833') to project to before buffering. If None, no reprojection.
    """
    # Ensure both are in projected CRS for correct buffering
    if target_crs is not None:
        if streets_gdf.crs != target_crs:
            streets_gdf = streets_gdf.to_crs(target_crs)
        if bikelanes_gdf.crs != target_crs:
            bikelanes_gdf = bikelanes_gdf.to_crs(target_crs)
    else:
        target_crs = f"EPSG:{DEFAULT_CRS}"
    print(f"Erzeuge {BUFFER_METERS}m Buffer um Radwege ...")
    bikelanes_buffer = bikelanes_gdf.buffer(BUFFER_METERS)
    bikelanes_union = bikelanes_buffer.unary_union
    print("Berechne Differenz: entferne Straßen im Radwege-Buffer ...")
    diff_geoms = streets_gdf.geometry.apply(lambda geom: geom.difference(bikelanes_union) if not geom.is_empty else geom)
    result_gdf = streets_gdf.copy()
    result_gdf["geometry"] = diff_geoms
    result_gdf = result_gdf[~result_gdf.geometry.is_empty & result_gdf.geometry.notnull()]
    return result_gdf


def get_or_create_difference_fgb(streets_gdf, bikelanes_gdf, output_path, target_crs=None):
    """
    Loads the difference result from output_path if it exists, otherwise computes and writes it.
    Returns the resulting GeoDataFrame.
    """
    if os.path.exists(output_path):
        print(f"Lade vorhandene Differenzdatei: {output_path}")
        return gpd.read_file(output_path)
    print("Berechne Differenz: nur Straßen ohne Radwege ...")
    diff_gdf = difference_streets_without_bikelanes(streets_gdf, bikelanes_gdf, target_crs=target_crs)
    diff_gdf.to_file(output_path, driver='FlatGeobuf')
    print(f'Differenz gespeichert als {output_path} ({len(diff_gdf)} Features)')
    return diff_gdf
