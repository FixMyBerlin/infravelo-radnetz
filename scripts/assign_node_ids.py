import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

def assign_district_to_nodes(nodes_path, districts_path, output_path):
    """
    Weist den Verbindungspunkten den Bezirk basierend auf ihrem Standort zu.

    Args:
        nodes_path (str): Pfad zur Knotenpunkt-Datei.
        districts_path (str): Pfad zur Bezirks-Datei.
        output_path (str): Pfad zum Speichern der aktualisierten Knotenpunkt-Datei.
    """
    print(f"Lade Knotenpunkte von {nodes_path}")
    nodes_gdf = gpd.read_file(nodes_path)
    print(f"Lade Bezirke von {districts_path}")
    districts_gdf = gpd.read_file(districts_path)

    # Sicherstellen, dass die CRS übereinstimmen
    if nodes_gdf.crs != districts_gdf.crs:
        print("CRS stimmen nicht überein. Projiziere Bezirke auf das CRS der Knotenpunkte.")
        districts_gdf = districts_gdf.to_crs(nodes_gdf.crs)

    # Räumlicher Join, um den Bezirk für jeden Knotenpunkt zu finden
    joined_gdf = gpd.sjoin(nodes_gdf, districts_gdf[['gem', 'geometry']], how="left", predicate="within")

    # Erstellen der zweistelligen Bezirks-ID aus der 'gem'-Spalte
    # Füllt NaN-Werte, wendet die String-Operation an und behält NaNs bei
    joined_gdf['Bezirksnummer'] = joined_gdf['gem'].dropna().astype(str).str[-2:]

    # Duplikate entfernen, die durch den Join entstehen könnten, falls ein Punkt auf einer Grenze liegt
    joined_gdf = joined_gdf[~joined_gdf.index.duplicated(keep='first')]

    # Nur die ursprünglichen Spalten und die neue 'Bezirksnummer' behalten
    final_columns = list(nodes_gdf.columns) + ['Bezirksnummer']
    # Stellen Sie sicher, dass die Spalte 'Bezirksnummer' im DataFrame vorhanden ist, bevor Sie sie auswählen
    if 'Bezirksnummer' not in joined_gdf.columns:
        nodes_gdf['Bezirksnummer'] = None
    else:
        nodes_gdf['Bezirksnummer'] = joined_gdf['Bezirksnummer']

    print(f"Speichere aktualisierte Knotenpunkte nach {output_path}")
    nodes_gdf.to_file(output_path, driver='GPKG')
    print(f"{nodes_gdf['Bezirksnummer'].notna().sum()} Knotenpunkte haben eine Bezirks-ID erhalten.")


def assign_node_ids(nodes_path, segments_path, output_path):
    """
    Weist den Knotenpunkt-IDs basierend auf den verbundenen Straßenabschnitten zu.

    Args:
        nodes_path (str): Pfad zur Knotenpunkt-Datei.
        segments_path (str): Pfad zur Straßenabschnitts-Datei.
        output_path (str): Pfad zum Speichern der aktualisierten Knotenpunkt-Datei.
    """
    print("Starte Zuweisung der Knotenpunkt‐IDs basierend auf den Straßenabschnitten...")
    print("-----------------------------------------------------")
    # Laden der Geodaten
    print(f"Lade Knotenpunkte von {nodes_path}")
    nodes_gdf = gpd.read_file(nodes_path)
    print(f"Lade Straßenabschnitte von {segments_path}")
    segments_gdf = gpd.read_file(segments_path)

    # Sicherstellen, dass die CRS übereinstimmen
    if nodes_gdf.crs != segments_gdf.crs:
        print("CRS stimmen nicht überein. Projiziere Knotenpunkte auf das CRS der Segmente.")
        nodes_gdf = nodes_gdf.to_crs(segments_gdf.crs)

    # Extrahieren der Start- und Endpunkte der Segmente
    start_points = segments_gdf.copy()
    start_points['geometry'] = segments_gdf.geometry.apply(lambda line: Point(line.coords[0]))
    start_points['Knotenpunkt‐ID'] = start_points['beginnt_bei_vp']
    
    end_points = segments_gdf.copy()
    end_points['geometry'] = segments_gdf.geometry.apply(lambda line: Point(line.coords[-1]))
    end_points['Knotenpunkt‐ID'] = end_points['endet_bei_vp']

    # Kombinieren der Start- und Endpunkte
    segment_nodes = pd.concat([
        start_points[['geometry', 'Knotenpunkt‐ID']],
        end_points[['geometry', 'Knotenpunkt‐ID']]
    ], ignore_index=True)

    # Entfernen von Duplikaten, um die Leistung zu verbessern
    # segment_nodes = segment_nodes.drop_duplicates(subset=['geometry'])

    # Räumlicher Join, um die Knotenpunkt‐ID den Knotenpunkten zuzuordnen
    # Wir verwenden einen kleinen Puffer, um Ungenauigkeiten bei den Koordinaten zu berücksichtigen
    nodes_gdf_buffered = nodes_gdf.copy()
    nodes_gdf_buffered['geometry'] = nodes_gdf.geometry.buffer(0.1) # 10 cm Puffer, anpassbar

    joined_gdf = gpd.sjoin(nodes_gdf, segment_nodes, how="left", predicate="intersects")

    # Da ein Knotenpunkt mit mehreren Segment-Endpunkten verbunden sein kann,
    # gruppieren wir nach der ursprünglichen Knoten-ID und nehmen die erste gefundene Knotenpunkt‐ID.
    # Normalerweise sollten sie für einen gegebenen Knotenpunkt identisch sein.
    # Wir behalten den ersten Treffer für jeden ursprünglichen Knotenpunkt-Index
    joined_gdf = joined_gdf[~joined_gdf.index.duplicated(keep='first')]
    
    # Umbenennen der Spalte für die Ausgabe
    nodes_gdf['Knotenpunkt‐ID'] = joined_gdf['Knotenpunkt‐ID']


    # Speichern der Ergebnisse
    print(f"Speichere aktualisierte Knotenpunkte nach {output_path}")
    nodes_gdf.to_file(output_path, driver='GPKG')

    print("Skript erfolgreich abgeschlossen.")
    print(f"Zusammenfassung: {len(nodes_gdf)} Knotenpunkte verarbeitet.")
    print(f"{nodes_gdf['Knotenpunkt‐ID'].notna().sum()} Knotenpunkte haben eine Knotenpunkt‐ID erhalten.")
    print("-----------------------------------------------------")


if __name__ == '__main__':
    # Pfade zu den Eingabe- und Ausgabedateien
    nodes_input_path = 'data/Verbindungspunkte im RVN.gpkg'
    segments_input_path = 'data/Berlin Straßenabschnitte.gpkg'
    nodes_with_vp_id_path = 'output/knotenpunkte/knotenpunkte_mit_id.gpkg'

    # Aufruf der Funktion zur Zuweisung der Knotenpunkt‐ID
    assign_node_ids(nodes_input_path, segments_input_path, nodes_with_vp_id_path)

    # Pfade für die Bezirkszuweisung
    districts_input_path = 'data/Berlin Bezirke.gpkg'
    final_output_path = 'output/knotenpunkte/knotenpunkte_mit_id_und_bezirken.gpkg'

    # Aufruf der Funktion zur Zuweisung der Bezirks-ID
    assign_district_to_nodes(nodes_with_vp_id_path, districts_input_path, final_output_path)
