# -*- coding: utf-8 -*-
import geopandas as gpd
from shapely.ops import substring
from shapely.geometry import Point
import pandas as pd
from processing.helpers.progressbar import print_progressbar

# --- Konfiguration ---
INPUT_OSM_WAYS = './output/matched_osm_ways.fgb'
INPUT_TARGET_NETWORK = './output/vorrangnetz_details_combined_rvn.fgb'
OUTPUT_SNAPPED_WAYS = './output/qa-snapping/snapped_osm_ways.fgb'
OUTPUT_UNSNAPPED_WAYS = './output/qa-snapping/unsnapped_osm_ways.fgb'
CRS_TARGET = 'EPSG:25833'
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
    # Fügt einen kleinen Puffer hinzu, um Gleitkommaprobleme zu vermeiden
    snapped_line = substring(target_line, start_dist, end_dist)
    return snapped_line

def snap_and_cut_osm_ways():
    """
    Snappt und schneidet OSM-Wege auf ein Zielnetzwerk.
    """
    # --- 1. Daten laden ---
    print("Lade Daten...")
    osm_ways = gpd.read_file(INPUT_OSM_WAYS)
    target_network = gpd.read_file(INPUT_TARGET_NETWORK)

    # --- 2. KBS-Transformation ---
    print(f"Stelle sicher, dass das KBS {CRS_TARGET} ist...")
    osm_ways = osm_ways.to_crs(CRS_TARGET)
    target_network = target_network.to_crs(CRS_TARGET)

    # --- 3. Vorverarbeitung ---
    # MultiLineStrings zur einfacheren Verarbeitung in LineStrings auflösen
    osm_ways_exploded = osm_ways.explode(index_parts=True).reset_index(level=0, drop=True)
    print(f"{len(osm_ways_exploded)} OSM LineStrings verarbeitet.")
    target_network_exploded = target_network.explode(index_parts=True).reset_index(level=0, drop=True)
    print(f"{len(target_network_exploded)} Zielnetzwerk LineStrings verarbeitet.")

    # --- 4. Snapping und Schneiden ---
    print("Führe räumlichen Join durch, um die nächstgelegenen Netzwerksegmente zu finden...")
    # sjoin_nearest verwenden, um die nächstgelegene Netzwerlinie für jeden OSM-Weg zu finden
    snapped_join = gpd.sjoin_nearest(
        osm_ways_exploded,
        target_network_exploded,
        max_distance=SNAP_DISTANCE_TOLERANCE,
        how='left' # Alle OSM-Wege beibehalten, auch die ohne Übereinstimmung
    )

    # --- 5. Gesnappte und nicht gesnappte Wege trennen ---
    # Nicht gesnappte Wege sind diejenigen, bei denen 'index_right' NaN ist
    unsnapped_mask = snapped_join['index_right'].isna()
    unsnapped_ways = snapped_join[unsnapped_mask].copy()
    # Nur die ursprünglichen Spalten von osm_ways behalten
    unsnapped_ways = unsnapped_ways[osm_ways.columns]
    print(f"{len(unsnapped_ways)} nicht gesnappte OSM-Wege gefunden.")

    # Gesnappte Wege sind der Rest
    snapped_ways_raw = snapped_join[~unsnapped_mask].copy()
    print(f"{len(snapped_ways_raw)} potenziell gesnappte Segmente gefunden.")

    # --- 6. Gesnappte Geometrien erzeugen ---
    print("Erzeuge gesnappte Geometrien...")
    snapped_geometries = []
    total = len(snapped_ways_raw)
    for idx, (row_idx, row) in enumerate(snapped_ways_raw.iterrows()):
        osm_line = row.geometry
        # Die entsprechende Ziellinie aus dem Join-Index holen
        target_line = target_network_exploded.loc[row['index_right']].geometry
        
        snapped_line = get_projected_substring(target_line, osm_line)
        
        if snapped_line and not snapped_line.is_empty:
            snapped_geometries.append(snapped_line)
        else:
            # Wenn der Teilstring leer ist, None anhängen, um die Ausrichtung beizubehalten
            snapped_geometries.append(None)
        # Ladebalken anzeigen
        print_progressbar(idx + 1, total, prefix="Snapping: ", length=50)
        # Nach 10% abbrechen und Zwischenergebnis speichern
        if (idx + 1) == max(1, int(total * 0.1)):
            print("\n10% erreicht – Zwischenergebnis wird gespeichert und Verarbeitung abgebrochen.")
            snapped_ways_partial = snapped_ways_raw.iloc[:idx+1].copy()
            snapped_ways_partial['geometry'] = snapped_geometries
            snapped_ways_partial = snapped_ways_partial[snapped_ways_partial.geometry.notna()]
            snapped_ways_partial = snapped_ways_partial[~snapped_ways_partial.geometry.is_empty]
            snapped_ways_partial = snapped_ways_partial[osm_ways.columns]
            snapped_ways_partial.to_file(OUTPUT_SNAPPED_WAYS.replace('.fgb', '_10pct.fgb'), driver="FlatGeobuf")
            print(f"Zwischenergebnis gespeichert unter {OUTPUT_SNAPPED_WAYS.replace('.fgb', '_10pct.fgb')}")
            return  # Funktion beenden
    print()  # Neue Zeile nach Ladebalken

    snapped_ways_final = snapped_ways_raw.copy()
    snapped_ways_final['geometry'] = snapped_geometries

    # Zeilen löschen, in denen die Geometrie None oder leer ist
    snapped_ways_final = snapped_ways_final[snapped_ways_final.geometry.notna()]
    snapped_ways_final = snapped_ways_final[~snapped_ways_final.geometry.is_empty]
    
    # Spalten aus dem Join bereinigen
    snapped_ways_final = snapped_ways_final[osm_ways.columns]


    print(f"{len(snapped_ways_final)} gesnappte Wege erstellt.")

    # --- 7. Ausgaben speichern ---
    print("Speichere Ausgabedateien...")
    if not snapped_ways_final.empty:
        snapped_ways_final.to_file(OUTPUT_SNAPPED_WAYS, driver="FlatGeobuf")
        print(f"Gesnappte Wege gespeichert unter {OUTPUT_SNAPPED_WAYS}")
    else:
        print("Es wurden keine gesnappten Wege erzeugt.")

    if not unsnapped_ways.empty:
        unsnapped_ways.to_file(OUTPUT_UNSNAPPED_WAYS, driver="FlatGeobuf")
        print(f"Nicht gesnappte Wege gespeichert unter {OUTPUT_UNSNAPPED_WAYS}")
    else:
        print("Es wurden keine nicht gesnappten Wege gefunden.")

    print("Verarbeitung abgeschlossen.")

if __name__ == '__main__':
    snap_and_cut_osm_ways()
