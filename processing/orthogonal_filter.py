import geopandas as gpd
from shapely.geometry import Point

def filter_orthogonal_bikelanes(matched_gdf_step1, vorrangnetz_gdf, projection_ratio_threshold=0.3):
    """
    Filtert OSM-Wege, die zu orthogonal zum Vorrangnetz verlaufen, basierend auf der Projektionslänge.
    Gibt ein gefiltertes GeoDataFrame zurück.
    """
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
                if ratio >= projection_ratio_threshold:
                    way_id = row.get('osm_id') or row.get('id')
                    if way_id is not None:
                        final_matched_ids.add(way_id)
            except Exception:
                continue
    return final_matched_ids
