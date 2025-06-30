import geopandas as gpd
import pandas as pd
import argparse
import os
from orthogonal_filter import  process_and_filter_short_segments
from manual_interventions import get_excluded_ways, get_included_ways

# Konfiguration
OSM_FGB = './data/bikelanes.fgb'  # Pfad zu OSM-Radwege
VORRANGNETZ_FGB = './data/Berlin Radvorrangsnetz.fgb'  # Pfad zum Vorrangnetz
BUFFER_METERS = 30  # Buffer-Radius in Metern
OUTPUT_FILE = './output/matched_osm_way_ids.txt'

def load_geodataframes(osm_path, vorrangnetz_path, target_crs):
    """
    Lädt OSM- und Vorrangnetz-Geodaten und transformiert sie ins Ziel-CRS.
    """
    print('Lade OSM-Radwege...')
    osm_gdf = gpd.read_file(osm_path)
    print(f'OSM-Radwege geladen: {len(osm_gdf)} Features')
    print('Lade Vorrangnetz...')
    vorrangnetz_gdf = gpd.read_file(vorrangnetz_path)
    print(f'Vorrangnetz geladen: {len(vorrangnetz_gdf)} Features')
    # Transformiere CRS falls nötig
    if osm_gdf.crs != target_crs:
        osm_gdf = osm_gdf.to_crs(target_crs)
    if vorrangnetz_gdf.crs != target_crs:
        vorrangnetz_gdf = vorrangnetz_gdf.to_crs(target_crs)
    return osm_gdf, vorrangnetz_gdf


def create_unified_buffer(vorrangnetz_gdf, buffer_meters, target_crs):
    """
    Erzeugt einen vereinheitlichten Buffer um das Vorrangnetz.
    """
    print(f'Erzeuge Buffer von {buffer_meters}m um Vorrangnetz-Kanten...')
    vorrangnetz_buffer = vorrangnetz_gdf.buffer(buffer_meters)
    print('Vereine alle Buffer zu einer einzigen Geometrie...')
    unified_buffer = vorrangnetz_buffer.union_all()
    unified_buffer_gdf = gpd.GeoDataFrame(geometry=[unified_buffer], crs=target_crs)
    return unified_buffer, unified_buffer_gdf


def find_osm_ways_in_buffer(osm_gdf, unified_buffer, cache_path, fraction_threshold=0.7):
    """
    Findet alle OSM-Wege, die zu mindestens fraction_threshold im Buffer liegen. Nutzt Caching.
    """
    if os.path.exists(cache_path):
        print(f'Lade zwischengespeichertes Ergebnis aus {cache_path}...')
        matched_gdf = gpd.read_file(cache_path)
    else:
        print('Finde alle OSM-Wege, die den vereinten Buffer schneiden (dies kann dauern)...')
        def line_in_buffer_fraction(line, buffer_geom):
            if line.is_empty or line.length == 0:
                return 0
            intersected = line.intersection(buffer_geom)
            return intersected.length / line.length if not intersected.is_empty else 0
        mask = osm_gdf.geometry.apply(lambda geom: line_in_buffer_fraction(geom, unified_buffer) >= fraction_threshold)
        matched_gdf = osm_gdf[mask].copy()
        matched_gdf = matched_gdf.loc[:, ~matched_gdf.columns.duplicated()]
        matched_gdf.to_file(cache_path, driver='FlatGeobuf')
        print(f'Zwischenergebnis gespeichert in {cache_path}')
    print(f'Gefundene OSM-Way-IDs nach erstem Filter: {len(matched_gdf)}')
    return matched_gdf


def apply_orthogonal_filter_if_requested(args, vorrangnetz_gdf, osm_gdf, matched_gdf_step1):
    """
    Wendet optional den Orthogonalitätsfilter an und gibt das finale GeoDataFrame zurück.
    """
    if args.orthogonalfilter:
        print("Wende Orthogonalitäts-Filter für kurze Segmente an...")
        id_col_step1 = 'osm_id' if 'osm_id' in matched_gdf_step1.columns else 'id'
        step1_ids = set(matched_gdf_step1[id_col_step1])
        # Zusätzliche kurze Wege durch Orthogonalitäts-Check finden
        short_way_ids = process_and_filter_short_segments(
            vorrangnetz_gdf=vorrangnetz_gdf,
            osm_gdf=osm_gdf
        )
        # Entferne die IDs der kurzen, orthogonalen Wege aus den bisher gematchten Wegen
        final_way_ids = step1_ids.difference(short_way_ids)
        id_col_osm = 'osm_id' if 'osm_id' in osm_gdf.columns else 'id'
        matched_gdf = osm_gdf[osm_gdf[id_col_osm].isin(final_way_ids)].copy()
        id_col = id_col_osm
        print(f"Gesamtzahl der gematchten Wege nach Herausfiltern: {len(matched_gdf)}")
    else:
        print("Orthogonalitäts-Filter übersprungen.")
        id_col = 'osm_id' if 'osm_id' in matched_gdf_step1.columns else 'id'
        matched_gdf = matched_gdf_step1
    return matched_gdf, id_col


def apply_manual_interventions(args, matched_gdf, osm_gdf):
    """
    Wendet manuelle Ausschlüsse und Einschlüsse von OSM Wege IDs an, falls gefordert.
    """
    if not args.manual_interventions:
        return matched_gdf

    print("Wende manuelle Eingriffe an...")
    id_col = 'osm_id' if 'osm_id' in osm_gdf.columns else 'id'

    # Manuelle Ausschlüsse
    excluded_ids = get_excluded_ways()
    if excluded_ids:
        initial_count = len(matched_gdf)
        matched_gdf = matched_gdf[~matched_gdf[id_col].isin(excluded_ids)]
        print(f"{initial_count - len(matched_gdf)} Wege manuell ausgeschlossen.")

    # Manuelle Einschlüsse
    included_ids = get_included_ways()
    if included_ids:
        ways_to_add = osm_gdf[osm_gdf[id_col].isin(included_ids)]
        # Verhindere Duplikate
        ways_to_add = ways_to_add[~ways_to_add[id_col].isin(matched_gdf[id_col])]
        
        if not ways_to_add.empty:
            matched_gdf = pd.concat([matched_gdf, ways_to_add], ignore_index=True)
            print(f"{len(ways_to_add)} Wege manuell hinzugefügt.")

    return matched_gdf


def write_outputs(matched_gdf, id_col, unified_buffer, target_crs):
    """
    Schreibt die Ergebnisse als FlatGeobuf und als Textliste. Speichert auch das gebufferte Vorrangnetz.
    """
    # Entferne doppelte Spaltennamen, die durch sjoin entstehen können
    if 'index_right' in matched_gdf.columns:
        matched_gdf = matched_gdf.drop(columns=['index_right'])
    matched_gdf = matched_gdf.loc[:,~matched_gdf.columns.duplicated()]
    # Schreibe FlatGeobuf
    fgb_file = './output/matched_osm_ways.fgb'
    matched_gdf.to_file(fgb_file, driver='FlatGeobuf')
    print(f'FlatGeobuf gespeichert in {fgb_file}')

    # Speichere das gebufferte Vorrangnetz zur Kontrolle
    buffered_gdf = gpd.GeoDataFrame(geometry=[unified_buffer], crs=target_crs)
    buffered_gdf.to_file('./output/vorrangnetz_buffered.fgb', driver='FlatGeobuf')
    print('Gebuffertes Vorrangnetz gespeichert als ./output/vorrangnetz_buffered.fgb')


def parse_arguments():
    """
    Parst die Kommandozeilenargumente.
    """
    parser = argparse.ArgumentParser(description="Match OSM ways to Vorrangnetz with optional filters.")
    parser.add_argument('--orthogonalfilter', action='store_true', help='Enable orthogonality filtering (second step)')
    parser.add_argument('--manual-interventions', action='store_true', help='Enable manual interventions from data/exclude_ways.txt and data/include_ways.txt')
    return parser.parse_args()


def main():
    """
    Orchestriert den gesamten Matching- und Filterprozess.
    """
    args = parse_arguments()
    # Schritt 1: Daten laden und CRS prüfen
    osm_gdf, vorrangnetz_gdf = load_geodataframes(OSM_FGB, VORRANGNETZ_FGB, 'EPSG:25833')
    # Schritt 2: Buffer erzeugen
    unified_buffer, _ = create_unified_buffer(vorrangnetz_gdf, BUFFER_METERS, 'EPSG:25833')
    # Schritt 3: OSM-Wege im Buffer finden
    matched_gdf_step1 = find_osm_ways_in_buffer(osm_gdf, unified_buffer, './output/bikelanes_in_buffering.fgb')
    # Schritt 4: Optional Orthogonalfilter anwenden
    matched_gdf, id_col = apply_orthogonal_filter_if_requested(args, vorrangnetz_gdf, osm_gdf, matched_gdf_step1)
    # Schritt 5: Manuelle Eingriffe anwenden
    matched_gdf = apply_manual_interventions(args, matched_gdf, osm_gdf)
    # Schritt 6: Ergebnisse schreiben
    write_outputs(matched_gdf, id_col, unified_buffer, 'EPSG:25833')


if __name__ == '__main__':
    main()
