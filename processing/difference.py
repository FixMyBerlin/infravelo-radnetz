import geopandas as gpd
import os

BUFFER_METERS = 35  # Buffer-Radius in Metern für die Differenzbildung


def difference_streets_without_bikelanes(streets_gdf, bikelanes_gdf):
    """
    Gibt nur die Teile der Straßen zurück, die nicht im Buffer (BUFFER_METERS) um Radwege liegen.
    Ein Buffer wird um alle Radwege gelegt, und alle Straßen, die diesen Buffer schneiden, werden entfernt.
    """
    print(f"Erzeuge {BUFFER_METERS}m Buffer um Radwege ...")
    bikelanes_buffer = bikelanes_gdf.buffer(BUFFER_METERS)
    bikelanes_union = bikelanes_buffer.unary_union
    print("Berechne Differenz: entferne Straßen im Radwege-Buffer ...")
    diff_geoms = streets_gdf.geometry.apply(lambda geom: geom.difference(bikelanes_union) if not geom.is_empty else geom)
    result_gdf = streets_gdf.copy()
    result_gdf["geometry"] = diff_geoms
    result_gdf = result_gdf[~result_gdf.geometry.is_empty & result_gdf.geometry.notnull()]
    return result_gdf


def main():
    # Feste Pfade für diese Anwendung
    streets_path = './data/TILDA Straßen Berlin.fgb'
    bikelanes_path = './data/bikelanes.fgb'
    output_path = './output/streets_without_bikelanes_buffered.fgb'
    crs = 'EPSG:25833'

    print(f"Lade {streets_path} ...")
    streets_gdf = gpd.read_file(streets_path)
    print(f"Lade {bikelanes_path} ...")
    bikelanes_gdf = gpd.read_file(bikelanes_path)

    # CRS angleichen
    if streets_gdf.crs != crs:
        streets_gdf = streets_gdf.to_crs(crs)
    if bikelanes_gdf.crs != crs:
        bikelanes_gdf = bikelanes_gdf.to_crs(crs)

    # Berechne Differenz
    result_gdf = difference_streets_without_bikelanes(streets_gdf, bikelanes_gdf)

    # Speichere Ergebnis
    print(f"Speichere Ergebnis nach {output_path} ...")
    result_gdf.to_file(output_path, driver='FlatGeobuf')
    print(f"Differenz erfolgreich gespeichert. {len(result_gdf)} Features.")

