#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
assign_node_ids.py
--------------------------------------------------------------------
Weist den Verbindungspunkten aus dem Detailnetz Knotenpunkt-IDs und
Bezirksnummern zu.

Die Knotenpunkt-IDs werden aus den beginnt_bei_vp und endet_bei_vp
Attributen der Straßenabschnitte extrahiert und den geometrischen
Verbindungspunkten zugeordnet. Anschließend wird jedem Knotenpunkt
eine zweistellige Bezirksnummer basierend auf seiner räumlichen Lage
zugewiesen.

Diese IDs werden später im Radvorrangsnetz verwendet, um Kanten mit
beginnt_bei_vp und endet_bei_vp zu versehen.

INPUT:
- data/Verbindungspunkte im RVN.gpkg
- data/Berlin Straßenabschnitte.gpkg
- data/Berlin Bezirke.gpkg

OUTPUT:
- output/knotenpunkte/knotenpunkte_mit_id.gpkg
- output/knotenpunkte/knotenpunkte_mit_id_und_bezirken.gpkg
"""

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point


def remove_duplicate_nodes(nodes_gdf):
    """
    Die Ausgangsdaten Verbindungspunkte im RVN.gpkg enthalten
    teilweise doppelte Knotenpunkte (mehrere Zeilen mit gleicher Geometrie).

    Diese Funktion entfernt vollständig identische Duplikate aus den Knotenpunkten.
    
    Zeilen mit gleicher Geometrie UND gleichen Attributen werden entfernt.
    Zeilen mit gleicher Geometrie aber unterschiedlichen Attributen werden
    beibehalten und geloggt (z.B. bei unterschiedlichen Verkehrsebenen).
    
    Args:
        nodes_gdf (GeoDataFrame): Knotenpunkte-GeoDataFrame
        
    Returns:
        GeoDataFrame: Bereinigte Knotenpunkte ohne vollständige Duplikate
    """
    original_count = len(nodes_gdf)
    nodes_gdf['geom_wkt'] = nodes_gdf.geometry.to_wkt()
    
    # Finde Zeilen mit gleicher Geometrie
    geom_duplicates = nodes_gdf[nodes_gdf.duplicated(subset=['geom_wkt'], keep=False)]
    
    if len(geom_duplicates) > 0:
        print(f"\nGefunden: {len(geom_duplicates)} Zeilen mit doppelter Geometrie")
        
        # Prüfe, welche davon vollständig identisch sind (alle Attribute gleich)
        attribute_cols = [col for col in nodes_gdf.columns if col not in ['geometry', 'geom_wkt']]
        
        # Finde partielle Duplikate (gleiche Geometrie, aber unterschiedliche Attribute)
        geom_groups = geom_duplicates.groupby('geom_wkt')
        partial_duplicates = []
        
        for geom_wkt, group in geom_groups:
            if len(group) > 1:
                # Prüfe ob Attribute unterschiedlich sind
                unique_attrs = group[attribute_cols].drop_duplicates()
                if len(unique_attrs) > 1:
                    partial_duplicates.extend(group.index.tolist())
        
        if partial_duplicates:
            print(f"\n⚠️  WARNUNG: {len(partial_duplicates)} Zeilen haben gleiche Geometrie aber unterschiedliche Attribute!")
            print("Diese werden NICHT entfernt und bleiben in den Daten.")
            print("\nBeispiele (erste 3 Gruppen):")
            
            shown = 0
            for geom_wkt, group in geom_groups:
                if len(group) > 1:
                    unique_attrs = group[attribute_cols].drop_duplicates()
                    if len(unique_attrs) > 1 and shown < 3:
                        print(f"\n  Geometrie-Gruppe mit {len(group)} Zeilen, {len(unique_attrs)} verschiedene Attribut-Kombinationen:")
                        for idx, row in group.iterrows():
                            print(f"    Index {idx}: dnkn__sdatenid={row.get('dnkn__sdatenid', 'N/A')}, "
                                  f"verkehrsebene={row.get('verkehrsebene', 'N/A')}, "
                                  f"ist_radvorrangnetz={row.get('ist_radvorrangnetz', 'N/A')}")
                        shown += 1
        
        # Entferne nur vollständig identische Duplikate (alle Spalten inkl. Geometrie gleich)
        nodes_gdf = nodes_gdf.drop_duplicates(subset=attribute_cols + ['geom_wkt'], keep='first')
        nodes_gdf = nodes_gdf.drop(columns=['geom_wkt'])
        
        fully_identical_removed = original_count - len(nodes_gdf)
        if fully_identical_removed > 0:
            print(f"\n✓ Entfernt: {fully_identical_removed} vollständig identische Duplikate")
            print(f"✓ Verbleibende Knotenpunkte: {len(nodes_gdf)}")
    else:
        print("Keine Geometrie-Duplikate gefunden")
        nodes_gdf = nodes_gdf.drop(columns=['geom_wkt'])
    
    return nodes_gdf


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
    
    Entfernt zunächst Duplikate aus den Eingangsdaten (mehrere Zeilen mit gleicher
    Geometrie), da diese zu doppelten Knotenpunkt-IDs führen würden.

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
    
    # Entferne vollständig identische Duplikate
    nodes_gdf = remove_duplicate_nodes(nodes_gdf)
    
    print(f"\nLade Straßenabschnitte von {segments_path}")
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
