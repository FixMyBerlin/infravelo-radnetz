import geopandas as gpd
import pandas as pd
import argparse
import os
from orthogonal_filter import process_and_filter_short_segments
from manual_interventions import get_excluded_ways, get_included_ways

# Konfiguration
BIKELANES_FGB = './data/bikelanes.fgb'  # Pfad zu OSM-Radwegen
STREETS_FGB = './data/TILDA Straßen Berlin.fgb'  # Pfad zu OSM-Straßen
VORRANGNETZ_FGB = './data/Berlin Radvorrangsnetz.fgb'  # Pfad zum Vorrangnetz
BIKELANES_BUFFER_METERS = 30  # Buffer-Radius in Metern für Radwege
STREETS_BUFFER_METERS = 15    # Buffer-Radius in Metern für Straßen
TARGET_CRS = 'EPSG:25833'

def load_geodataframe(path, name, target_crs):
    """
    Lädt ein Geodaten-Set, transformiert es ins Ziel-CRS und gibt es zurück.
    """
    print(f'Lade {name}...')
    gdf = gpd.read_file(path)
    print(f'{name} geladen: {len(gdf)} Features')
    if gdf.crs != target_crs:
        gdf = gdf.to_crs(target_crs)
    return gdf


def create_unified_buffer(vorrangnetz_gdf, buffer_meters, target_crs):
    """
    Erzeugt einen vereinheitlichten Buffer um das Vorrangnetz.
    """
    print(f'Erzeuge Buffer von {buffer_meters}m um Vorrangnetz-Kanten...')
    vorrangnetz_buffer = vorrangnetz_gdf.buffer(buffer_meters)
    print('Vereine alle Buffer zu einer einzigen Geometrie...')
    unified_buffer = vorrangnetz_buffer.union_all()
    unified_buffer_gdf = gpd.GeoDataFrame(geometry=[unified_buffer], crs=target_crs)
    # Speichere das gebufferte Vorrangnetz zur Kontrolle
    buffered_gdf = gpd.GeoDataFrame(geometry=[unified_buffer], crs=target_crs)
    buffered_gdf.to_file('./output/vorrangnetz_buffered.fgb', driver='FlatGeobuf')
    print('Gebuffertes Vorrangnetz gespeichert als ./output/vorrangnetz_buffered.fgb')
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


def apply_orthogonal_filter_if_requested(args, vorrangnetz_gdf, osm_gdf, matched_gdf_step1, output_prefix):
    """
    Wendet optional den Orthogonalitätsfilter an und gibt das finale GeoDataFrame zurück.
    """
    use_orthogonal_filter = (output_prefix == 'bikelanes' and not args.skip_orthogonalfilter_bikelanes) or \
                            (output_prefix == 'streets' and not args.skip_orthogonalfilter_streets)

    if use_orthogonal_filter:
        print(f"Wende Orthogonalitäts-Filter für kurze Segmente für {output_prefix} an...")
        id_col_step1 = 'osm_id' if 'osm_id' in matched_gdf_step1.columns else 'id'
        step1_ids = set(matched_gdf_step1[id_col_step1])
        # Zusätzliche kurze Wege durch Orthogonalitäts-Check finden
        short_way_ids = process_and_filter_short_segments(
            vorrangnetz_gdf=vorrangnetz_gdf,
            osm_gdf=osm_gdf,
            output_prefix=output_prefix
        )
        # Entferne die IDs der kurzen, orthogonalen Wege aus den bisher gematchten Wegen
        final_way_ids = step1_ids.difference(short_way_ids)
        id_col_osm = 'osm_id' if 'osm_id' in osm_gdf.columns else 'id'
        matched_gdf = osm_gdf[osm_gdf[id_col_osm].isin(final_way_ids)].copy()
        id_col = id_col_osm
        print(f"Gesamtzahl der gematchten Wege nach Herausfiltern: {len(matched_gdf)}")
    else:
        print(f"Orthogonalitäts-Filter für {output_prefix} übersprungen.")
        id_col = 'osm_id' if 'osm_id' in matched_gdf_step1.columns else 'id'
        matched_gdf = matched_gdf_step1
    return matched_gdf, id_col


def apply_manual_interventions(args, matched_gdf, osm_gdf, output_prefix):
    """
    Wendet manuelle Ausschlüsse und Einschlüsse von OSM Wege IDs an, falls gefordert.
    Erstellt eine Zwischen-Datei mit allen manuell hinzugefügten und entfernten Wegen und einem Attribut 'manual_action'.
    """
    if args.skip_manual_interventions:
        return matched_gdf

    print("Wende manuelle Eingriffe an...")
    id_col = 'osm_id' if 'osm_id' in osm_gdf.columns else 'id'

    # Manuelle Ausschlüsse
    excluded_ids = get_excluded_ways()
    removed_gdf = None
    if excluded_ids:
        removed_gdf = matched_gdf[matched_gdf[id_col].isin(excluded_ids)].copy()
        removed_gdf['manual_action'] = 'removed'
        initial_count = len(matched_gdf)
        matched_gdf = matched_gdf[~matched_gdf[id_col].isin(excluded_ids)]
        print(f"{initial_count - len(matched_gdf)} Wege manuell ausgeschlossen.")

    # Manuelle Einschlüsse
    included_ids = get_included_ways()
    added_gdf = None
    if included_ids:
        ways_to_add = osm_gdf[osm_gdf[id_col].isin(included_ids)]
        # Verhindere Duplikate
        ways_to_add = ways_to_add[~ways_to_add[id_col].isin(matched_gdf[id_col])]
        if not ways_to_add.empty:
            ways_to_add = ways_to_add.copy()
            ways_to_add['manual_action'] = 'added'
            added_gdf = ways_to_add
            matched_gdf = pd.concat([matched_gdf, ways_to_add], ignore_index=True)
            print(f"{len(ways_to_add)} Wege manuell hinzugefügt.")

    # Schreibe Zwischen-Datei mit nur den manuell hinzugefügten und entfernten Wegen
    if added_gdf is not None or removed_gdf is not None:
        manual_gdf = []
        if added_gdf is not None:
            manual_gdf.append(added_gdf)
        if removed_gdf is not None:
            manual_gdf.append(removed_gdf)
        manual_gdf = pd.concat(manual_gdf, ignore_index=True)
        manual_gdf = manual_gdf.loc[:,~manual_gdf.columns.duplicated()]
        output_path = f'./output/osm_{output_prefix}_manual_interventions.fgb'
        manual_gdf.to_file(output_path, driver='FlatGeobuf')
        print(f'Zwischen-Datei mit manuellen Eingriffen gespeichert als {output_path}')

    return matched_gdf


def write_outputs(matched_gdf, output_prefix):
    """
    Schreibt die Ergebnisse als FlatGeobuf.
    """
    # Entferne doppelte Spaltennamen, die durch sjoin entstehen können
    if 'index_right' in matched_gdf.columns:
        matched_gdf = matched_gdf.drop(columns=['index_right'])
    matched_gdf = matched_gdf.loc[:,~matched_gdf.columns.duplicated()]
    # Schreibe FlatGeobuf
    fgb_file = f'./output/matched_osm_{output_prefix}_ways.fgb'
    matched_gdf.to_file(fgb_file, driver='FlatGeobuf')
    print(f'FlatGeobuf gespeichert in {fgb_file}')


def parse_arguments():
    """
    Parst die Kommandozeilenargumente.
    """
    parser = argparse.ArgumentParser(description="Match OSM ways to Vorrangnetz with optional filters.")
    # Orthogonal filter and manual interventions are now enabled by default, use --skip-* to disable
    parser.add_argument('--skip-orthogonalfilter-bikelanes', action='store_true', help='Skip orthogonality filtering for bikelanes')
    parser.add_argument('--skip-orthogonalfilter-streets', action='store_true', help='Skip orthogonality filtering for streets')
    parser.add_argument('--skip-manual-interventions', action='store_true', help='Skip manual interventions from data/exclude_ways.txt and data/include_ways.txt')
    parser.add_argument('--skip-bikelanes', action='store_true', help='Skip processing of bikelanes dataset')
    parser.add_argument('--skip-streets', action='store_true', help='Skip processing of streets dataset')
    parser.add_argument('--skip-difference-streets-bikelanes', action='store_true', help='Skip difference: only streets without bikelanes')
    return parser.parse_args()


def process_data_source(osm_fgb_path, output_prefix, vorrangnetz_gdf, unified_buffer, args):
    """
    Führt den kompletten Verarbeitungsprozess für eine Datenquelle durch.
    """
    print(f"\n--- Starte Verarbeitung für: {output_prefix} ---")
    # Schritt 1: OSM-Daten laden
    osm_gdf = load_geodataframe(osm_fgb_path, f"OSM {output_prefix}", TARGET_CRS)
    # Schritt 2: OSM-Wege im Buffer finden
    cache_path = f'./output/osm_{output_prefix}_in_buffering.fgb'
    matched_gdf_step1 = find_osm_ways_in_buffer(osm_gdf, unified_buffer, cache_path)
    # Schritt 3: Optional Orthogonalfilter anwenden
    use_orthogonal_filter = (output_prefix == 'bikelanes' and not args.skip_orthogonalfilter_bikelanes) or \
                            (output_prefix == 'streets' and not args.skip_orthogonalfilter_streets)

    if use_orthogonal_filter:
        matched_gdf, _ = apply_orthogonal_filter_if_requested(args, vorrangnetz_gdf, osm_gdf, matched_gdf_step1, output_prefix)
    else:
        print(f"Orthogonalitäts-Filter für {output_prefix} übersprungen.")
        id_col = 'osm_id' if 'osm_id' in matched_gdf_step1.columns else 'id'
        matched_gdf = matched_gdf_step1

    # Schritt 4: Manuelle Eingriffe anwenden
    matched_gdf = apply_manual_interventions(args, matched_gdf, osm_gdf, output_prefix)
    # Schritt 5: Ergebnisse schreiben
    write_outputs(matched_gdf, output_prefix)
    print(f"--- Verarbeitung für {output_prefix} abgeschlossen ---")


def main():
    """
    Orchestriert den gesamten Matching- und Filterprozess.
    """
    args = parse_arguments()
    # Vorrangnetz und Buffer einmalig laden/erstellen
    vorrangnetz_gdf = load_geodataframe(VORRANGNETZ_FGB, "Vorrangnetz", TARGET_CRS)

    # Verarbeitung für Fahrradwege
    if not args.skip_bikelanes:
        bikelanes_buffer, _ = create_unified_buffer(vorrangnetz_gdf, BIKELANES_BUFFER_METERS, TARGET_CRS)
        process_data_source(BIKELANES_FGB, 'bikelanes', vorrangnetz_gdf, bikelanes_buffer, args)
    else:
        print("--- Überspringe Verarbeitung für bikelanes ---")

    # Verarbeitung für Straßen
    if not args.skip_streets:
        streets_buffer, _ = create_unified_buffer(vorrangnetz_gdf, STREETS_BUFFER_METERS, TARGET_CRS)
        process_data_source(STREETS_FGB, 'streets', vorrangnetz_gdf, streets_buffer, args)
    else:
        print("--- Überspringe Verarbeitung für streets ---")

    # Differenz Straßen - Radwege berechnen
    if not args.skip_difference_streets_bikelanes:
        print("Berechne Differenz: nur Straßen ohne Radwege ...")
        from processing.difference import difference_geodataframes
        import geopandas as gpd
        streets_gdf = gpd.read_file(STREETS_FGB)
        bikelanes_gdf = gpd.read_file(BIKELANES_FGB)
        # CRS angleichen
        if streets_gdf.crs != bikelanes_gdf.crs:
            bikelanes_gdf = bikelanes_gdf.to_crs(streets_gdf.crs)
        diff_gdf = difference_geodataframes(streets_gdf, bikelanes_gdf)
        output_path = './output/streets_without_bikelanes.fgb'
        diff_gdf.to_file(output_path, driver='FlatGeobuf')
        print(f'Differenz gespeichert als {output_path} ({len(diff_gdf)} Features)')
    else:
        print("--- Überspringe Differenz-Berechnung für Straßen ohne Radwege ---")

if __name__ == '__main__':
    main()