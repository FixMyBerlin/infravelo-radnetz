import geopandas as gpd
import osmnx as ox
from shapely.geometry import Point
from sklearn.cluster import DBSCAN
import numpy as np
import os

# Load traffic signals from OSM and consolidate them within a radius.

# 1. Alle Ampeln aus OpenStreetMap in Berlin herunterladen
print("Lade Ampeldaten aus OpenStreetMap für Berlin herunter...")
place_name = "Berlin, Germany"
tags = {"highway": "traffic_signals"}
gdf_signals = ox.features_from_place(place_name, tags)
print(f"{len(gdf_signals)} Ampeln gefunden.")

# Umwandeln in ein geeignetes CRS für die Pufferung in Metern (ETRS89 / UTM zone 33N)
gdf_signals = gdf_signals.to_crs("EPSG:25833")

# Nur Punkte behalten
gdf_signals = gdf_signals[gdf_signals.geometry.type == 'Point']
print(f"Nach Filterung auf Punkte: {len(gdf_signals)} Ampeln.")

# 2. Alle Ampeln im Umkreis konsolidieren
print("Konsolidiere Ampeln im Umkreis von 35 Metern...")
if not gdf_signals.empty:
    # Koordinaten für DBSCAN extrahieren
    coords = np.array(list(zip(gdf_signals.geometry.x, gdf_signals.geometry.y)))

    # DBSCAN-Clustering
    db = DBSCAN(eps=35, min_samples=1).fit(coords)
    gdf_signals['cluster'] = db.labels_

    # Zentroid für jeden Cluster berechnen
    consolidated_points = []
    for cluster_id in gdf_signals['cluster'].unique():
        if cluster_id != -1: # Rauschen ignorieren, falls vorhanden
            cluster_points = gdf_signals[gdf_signals['cluster'] == cluster_id]
            centroid = cluster_points.unary_union.centroid
            consolidated_points.append(centroid)

    gdf_consolidated = gpd.GeoDataFrame(geometry=consolidated_points, crs="EPSG:25833")
    print(f"{len(gdf_consolidated)} konsolidierte Ampel-Punkte erstellt.")
else:
    gdf_consolidated = gpd.GeoDataFrame(geometry=[], crs="EPSG:25833")
    print("Keine Ampeln zum Konsolidieren gefunden.")


# 3. Die konsolidierten Punkte auf dem Radvorrangsnetz verorten
print("Filtere Punkte, die sich auf dem Radvorrangsnetz befinden...")
buffer_path = os.path.join('output', 'vorrangnetz_buffered.fgb')
if os.path.exists(buffer_path):
    gdf_buffer = gpd.read_file(buffer_path)
    gdf_buffer = gdf_buffer.to_crs("EPSG:25833")

    # Räumlicher Join, um nur Punkte innerhalb des Puffers zu erhalten
    gdf_final = gpd.sjoin(gdf_consolidated, gdf_buffer, how="inner", predicate='within')

    # Attribute entfernen, nur Geometrie behalten und Duplikate entfernen
    gdf_final = gdf_final[['geometry']].drop_duplicates()

    print(f"{len(gdf_final)} Ampeln befinden sich im gepufferten Vorrangnetz.")

    # Ergebnis speichern
    output_path = os.path.join('output', 'consolidated_osm_traffic_signals.gpkg')
    gdf_final.to_file(output_path, driver='GPKG')
    print(f"Ergebnis gespeichert in {output_path}")
else:
    print(f"Fehler: Die Datei {buffer_path} wurde nicht gefunden.")

print("Skript abgeschlossen.")
