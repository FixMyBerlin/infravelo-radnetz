# -*- coding: utf-8 -*-
import geopandas as gpd
from shapely.ops import substring
from shapely.geometry import Point
import pandas as pd
from helpers.progressbar import print_progressbar
from helpers.globals import DEFAULT_CRS

# --- Konfiguration ---
INPUT_OSM_WAYS = './output/matched_osm_ways.fgb'
INPUT_TARGET_NETWORK = './output/vorrangnetz_details_combined_rvn.fgb'
OUTPUT_SNAPPED_WAYS = './output/qa-snapping/snapped_osm_ways.fgb'
OUTPUT_UNSNAPPED_WAYS = './output/qa-snapping/unsnapped_osm_ways.fgb'
CRS_TARGET = DEFAULT_CRS
SNAP_DISTANCE_TOLERANCE = 35  # in Metern

def get_projected_substring(target_line, osm_line):
    """
    Projiziert eine OSM-Linie auf eine Ziellinie und gibt den entsprechenden Teilstring der Ziellinie zurück.
    Behandelt Fälle, in denen mehrere Ziellinien zurückgegeben werden.
    """
    start_point = Point(osm_line.coords[0])
    end_point = Point(osm_line.coords[-1])

    if isinstance(target_line, (gpd.GeoSeries, pd.Series)):
        # Wenn mehrere Ziellinien möglich sind, iterieren und die kürzeste gültige auswählen
        possible_lines = []
        for line in target_line:
            start_dist = line.project(start_point)
            end_dist = line.project(end_point)
            if start_dist > end_dist:
                start_dist, end_dist = end_dist, start_dist
            sub = substring(line, start_dist, end_dist)
            if sub and not sub.is_empty:
                possible_lines.append(sub)
        
        if not possible_lines:
            return None
        
        # Wählt die kürzeste der möglichen Linien
        return min(possible_lines, key=lambda x: x.length)

    # Projiziert Start- und Endpunkte der OSM-Linie auf die Ziellinie
    start_dist = target_line.project(start_point)
    end_dist = target_line.project(end_point)

    # Sicherstellen, dass start_dist < end_dist
    if start_dist > end_dist:
        start_dist, end_dist = end_dist, start_dist

    # Erstellt den Teilstring der Ziellinie
    sub = substring(target_line, start_dist, end_dist)
    return sub if sub and not sub.is_empty else None


def snap_and_cut(osm_gdf, target_network_gdf, snap_distance_tolerance):
    """
    Snapped OSM-Wege auf das Zielnetzwerk.
    """
    print("Beginne mit Snapping-Prozess...")
    
    # Listen für die Ergebnisse
    snapped_ways = []
    unsnapped_ways = []
    
    # Räumlicher Index für das Zielnetzwerk
    print("Erstelle räumlichen Index für das Zielnetzwerk...")
    target_sindex = target_network_gdf.sindex
    
    total_ways = len(osm_gdf)
    print(f"Verarbeite {total_ways} OSM-Wege...")
    
    for idx, (_, osm_row) in enumerate(osm_gdf.iterrows()):
        # Fortschrittsanzeige
        if idx % 500 == 0:
            print_progressbar(idx + 1, total_ways, prefix='Snapping: ', length=50)
        
        osm_geom = osm_row.geometry
        
        # Puffer um OSM-Weg erstellen
        buffer_geom = osm_geom.buffer(snap_distance_tolerance)
        
        # Potenzielle Matches im Zielnetzwerk finden
        possible_matches_idx = list(target_sindex.intersection(buffer_geom.bounds))
        
        if not possible_matches_idx:
            # Keine Matches gefunden
            unsnapped_ways.append(osm_row)
            continue
        
        # Prüfe Intersection mit potentiellen Matches
        possible_matches = target_network_gdf.iloc[possible_matches_idx]
        intersecting_lines = possible_matches[possible_matches.intersects(buffer_geom)]
        
        if intersecting_lines.empty:
            # Keine Intersections
            unsnapped_ways.append(osm_row)
            continue
        
        # Versuche Snapping
        snapped_geom = get_projected_substring(intersecting_lines.geometry, osm_geom)
        
        if snapped_geom is None:
            # Snapping fehlgeschlagen
            unsnapped_ways.append(osm_row)
            continue
        
        # Snapping erfolgreich - erstelle neues GeoDataFrame-Row
        snapped_row = osm_row.copy()
        snapped_row.geometry = snapped_geom
        snapped_ways.append(snapped_row)
    
    # Abschluss der Fortschrittsanzeige
    print_progressbar(total_ways, total_ways, prefix='Snapping: ', length=50)
    
    # Erstelle GeoDataFrames
    if snapped_ways:
        snapped_gdf = gpd.GeoDataFrame(snapped_ways, crs=osm_gdf.crs)
        print(f"Erfolgreich gesnapped: {len(snapped_gdf)} Wege")
    else:
        snapped_gdf = gpd.GeoDataFrame(columns=osm_gdf.columns, crs=osm_gdf.crs)
        print("Keine Wege erfolgreich gesnapped.")
    
    if unsnapped_ways:
        unsnapped_gdf = gpd.GeoDataFrame(unsnapped_ways, crs=osm_gdf.crs)
        print(f"Nicht gesnapped: {len(unsnapped_gdf)} Wege")
    else:
        unsnapped_gdf = gpd.GeoDataFrame(columns=osm_gdf.columns, crs=osm_gdf.crs)
        print("Alle Wege erfolgreich gesnapped.")
    
    return snapped_gdf, unsnapped_gdf


def calculate_snapping_percentage(snapped_gdf, percentage):
    """
    Berechnet einen Teilbereich der gesnappten Wege basierend auf dem gegebenen Prozentsatz.
    """
    if percentage <= 0 or percentage > 100:
        raise ValueError("Percentage must be between 0 and 100")
    
    total_count = len(snapped_gdf)
    target_count = int(total_count * percentage / 100)
    
    print(f"Berechne {percentage}% der gesnappten Wege: {target_count} von {total_count}")
    
    # Nimm die ersten N Wege
    subset_gdf = snapped_gdf.head(target_count).copy()
    
    return subset_gdf


def main():
    """
    Hauptfunktion für das Snapping-Verfahren.
    """
    print("Lade OSM-Wege...")
    osm_gdf = gpd.read_file(INPUT_OSM_WAYS)
    print(f"Geladen: {len(osm_gdf)} OSM-Wege")
    
    print("Lade Zielnetzwerk...")
    target_network_gdf = gpd.read_file(INPUT_TARGET_NETWORK)
    print(f"Geladen: {len(target_network_gdf)} Zielnetzwerk-Segmente")
    
    # Koordinatensystem prüfen und anpassen
    if osm_gdf.crs != CRS_TARGET:
        osm_gdf = osm_gdf.to_crs(CRS_TARGET)
    if target_network_gdf.crs != CRS_TARGET:
        target_network_gdf = target_network_gdf.to_crs(CRS_TARGET)
    
    # Snapping durchführen
    snapped_gdf, unsnapped_gdf = snap_and_cut(osm_gdf, target_network_gdf, SNAP_DISTANCE_TOLERANCE)
    
    # Ergebnisse speichern
    print("Speichere Ergebnisse...")
    
    # Vollständige Ergebnisse
    if not snapped_gdf.empty:
        snapped_gdf.to_file(OUTPUT_SNAPPED_WAYS, driver='FlatGeobuf')
        print(f"Gesnappte Wege gespeichert: {OUTPUT_SNAPPED_WAYS}")
    
    if not unsnapped_gdf.empty:
        unsnapped_gdf.to_file(OUTPUT_UNSNAPPED_WAYS, driver='FlatGeobuf')
        print(f"Nicht gesnappte Wege gespeichert: {OUTPUT_UNSNAPPED_WAYS}")
    
    # 10% Teilbereich für QA
    if not snapped_gdf.empty:
        snapped_10pct = calculate_snapping_percentage(snapped_gdf, 10)
        output_10pct = './output/snapped_osm_ways_10pct.fgb'
        snapped_10pct.to_file(output_10pct, driver='FlatGeobuf')
        print(f"10% Teilbereich gespeichert: {output_10pct}")
    
    # Zusammenfassung
    print("\n--- Snapping-Zusammenfassung ---")
    print(f"Eingabe: {len(osm_gdf)} OSM-Wege")
    print(f"Erfolgreich gesnapped: {len(snapped_gdf)} ({len(snapped_gdf)/len(osm_gdf)*100:.1f}%)")
    print(f"Nicht gesnapped: {len(unsnapped_gdf)} ({len(unsnapped_gdf)/len(osm_gdf)*100:.1f}%)")


if __name__ == "__main__":
    main()
