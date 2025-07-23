#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
start_matching.py
--------------------------------------------------------------------
Ordnet TILDA-übersetzte Attribute dem Berliner Radvorrangsnetz zu.
Führt räumliches Matching durch und erstellt bereinigte Datensätze.

INPUT:
- output/TILDA-translated/TILDA Bikelanes [Neukoelln] Translated.fgb
- output/TILDA-translated/TILDA Streets [Neukoelln] Translated.fgb
- output/TILDA-translated/TILDA Paths [Neukoelln] Translated.fgb
- data/Berlin Radvorrangsnetz.fgb
- data/include_ways.txt (manuelle Eingriffe)
- data/exclude_ways.txt (manuelle Eingriffe)

OUTPUT TMP FILES:
- output/matched/matched_tilda_bikelanes_ways.fgb
- output/matched/matched_tilda_streets_ways.fgb
- output/matched/matched_tilda_paths_ways.fgb
- output/matched/matched_tilda_streets_without_bikelanes.fgb
- output/matched/matched_tilda_paths_without_streets_and_bikelanes.fgb

OUTPUT:
- output/matched/matched_tilda_ways.fgb (kombinierte Datei)

VERWENDUNG:
- Standardmodus: python start_matching.py (verwendet ganz Berlin)
- Neukölln-Modus: python start_matching.py --clip-neukoelln (verwendet Neukölln-Dateien)
- Alle Straßen verwenden: python start_matching.py --use-all-streets-in-buffer (verwendet alle Straßen im Buffer anstatt nur die ohne Radwege)
"""

import geopandas as gpd
import pandas as pd
import logging
import argparse
import os
from matching.orthogonal_filter import process_and_filter_short_segments
from matching.manual_interventions import get_excluded_ways, get_included_ways
from matching.difference import get_or_create_difference_fgb
from helpers.progressbar import print_progressbar
from helpers.buffer_utils import create_unified_buffer
#from export_geojson import export_all_geojson

# Konfiguration
# Standard-Dateipfade (ohne Neukölln-Suffix)
INPUT_VORRANGNETZ_FGB = './data/Berlin Radvorrangsnetz.fgb'  # Pfad zum Vorrangnetz
BUFFER_BIKELANES_METERS = 25  # Buffer-Radius in Metern für Radwege
BUFFER_STREETS_METERS = 15    # Buffer-Radius in Metern für Straßen
BUFFER_PATHS_METERS = 15      # Buffer-Radius in Metern für Wege
TARGET_CRS = 'EPSG:25833'


def get_data_sources_config(use_neukoelln=False):
    """
    Erstellt die Datenquellen-Konfiguration basierend auf dem Neukölln-Parameter.
    
    Args:
        use_neukoelln: Ob die Neukölln-spezifischen Dateien verwendet werden sollen
        
    Returns:
        Dictionary mit Datenquellen-Konfiguration
    """
    suffix = " Neukoelln" if use_neukoelln else ""
    
    return {
        'bikelanes': {
            'file_path': f'./output/TILDA-translated/TILDA Bikelanes{suffix} Translated.fgb',
            'buffer_meters': BUFFER_BIKELANES_METERS,
            'description': 'TILDA Radwege'
        },
        'streets': {
            'file_path': f'./output/TILDA-translated/TILDA Streets{suffix} Translated.fgb',
            'buffer_meters': BUFFER_STREETS_METERS,
            'description': 'TILDA Straßen'
        },
        'paths': {
            'file_path': f'./output/TILDA-translated/TILDA Paths{suffix} Translated.fgb',
            'buffer_meters': BUFFER_PATHS_METERS,
            'description': 'TILDA Wege'
        }
    }

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


def find_osm_ways_in_buffer(osm_gdf, unified_buffer, cache_path, fraction_threshold=0.7):
    """
    Findet alle OSM-Wege, die zu mindestens fraction_threshold im Buffer liegen. Nutzt File Caching.
    Zeigt einen Fortschrittsbalken für den Geometrie-Check an.
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
        total = len(osm_gdf)
        mask = []
        for idx, geom in enumerate(osm_gdf.geometry):
            if line_in_buffer_fraction(geom, unified_buffer) >= fraction_threshold:
                mask.append(True)
            else:
                mask.append(False)
            print_progressbar(idx + 1, total, prefix="Buffer-Matching: ", length=40)
        matched_gdf = osm_gdf[mask].copy()
        matched_gdf = matched_gdf.loc[:, ~matched_gdf.columns.duplicated()]
        matched_gdf.to_file(cache_path, driver='FlatGeobuf')
        print(f'Zwischenergebnis gespeichert in {cache_path}')
    print(f'Gefundene TILDA Linien im Buffer: {len(matched_gdf)}')
    return matched_gdf


def apply_orthogonal_filter_if_requested(args, vorrangnetz_gdf, osm_gdf, matched_gdf_step1, output_prefix):
    """
    Wendet optional den Orthogonalitätsfilter an und gibt das finale GeoDataFrame zurück.
    """
    use_orthogonal_filter = (output_prefix == 'bikelanes' and not args.skip_orthogonalfilter_bikelanes) or \
                            (output_prefix == 'streets' and not args.skip_orthogonalfilter_streets) or \
                            (output_prefix == 'paths' and not args.skip_orthogonalfilter_paths)

    if use_orthogonal_filter:
        print(f"Wende Orthogonalitäts-Filter für kurze Segmente für {output_prefix} an...")
        id_col_step1 = 'tilda_osm_id' if 'tilda_osm_id' in matched_gdf_step1.columns else 'tilda_id'
        step1_ids = set(matched_gdf_step1[id_col_step1])
        # Zusätzliche kurze Wege durch Orthogonalitäts-Check finden
        short_way_ids = process_and_filter_short_segments(
            vorrangnetz_gdf=vorrangnetz_gdf,
            osm_gdf=osm_gdf,
            output_prefix=output_prefix
        )
        # Entferne die IDs der kurzen, orthogonalen Wege aus den bisher gematchten Wegen
        final_way_ids = step1_ids.difference(short_way_ids)
        id_col_osm = 'tilda_osm_id' if 'tilda_osm_id' in osm_gdf.columns else 'tilda_id'
        matched_gdf = osm_gdf[osm_gdf[id_col_osm].isin(final_way_ids)].copy()
        id_col = id_col_osm
        print(f"Gesamtzahl der gematchten Wege nach Herausfiltern: {len(matched_gdf)}")
    else:
        print(f"Orthogonalitäts-Filter für {output_prefix} übersprungen.")
        id_col = 'tilda_osm_id' if 'tilda_osm_id' in matched_gdf_step1.columns else 'tilda_id'
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
    id_col = 'tilda_osm_id' if 'tilda_osm_id' in osm_gdf.columns else 'tilda_id'

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
        output_path = f'./output/matching/osm_{output_prefix}_manual_interventions.fgb'
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
    fgb_file = f'./output/matched/matched_tilda_{output_prefix}_ways.fgb'
    matched_gdf.to_file(fgb_file, driver='FlatGeobuf')
    print(f'FlatGeobuf gespeichert in {fgb_file}')


def export_matched_way_ids(matched_gdf, output_prefix):
    """
    Exportiert alle OSM way IDs, die im Matching enthalten sind, als Textdatei.
    Jede Zeile enthält eine OSM way ID.
    """
    # Bestimme die ID-Spalte
    id_col = 'tilda_osm_id' if 'tilda_osm_id' in matched_gdf.columns else 'tilda_id'
    # Extrahiere eindeutige IDs als Liste
    matched_ids = matched_gdf[id_col].drop_duplicates().astype(str).tolist()
    # Schreibe die IDs in eine Textdatei
    output_path = f'./output/matched/matched_tilda_{output_prefix}_way_ids.txt'
    with open(output_path, 'w') as f:
        for way_id in matched_ids:
            f.write(f"{way_id}\n")
    logging.info(f"Exportierte {len(matched_ids)} OSM way IDs nach {output_path}")


def parse_arguments():
    """
    Parst die Kommandozeilenargumente.
    """
    parser = argparse.ArgumentParser(description="Match OSM ways to Vorrangnetz with optional filters.")
    # Orthogonal filter and manual interventions are now enabled by default, use --skip-* to disable
    parser.add_argument('--skip-orthogonalfilter-bikelanes', action='store_true', help='Skip orthogonality filtering for bikelanes')
    parser.add_argument('--skip-orthogonalfilter-streets', action='store_true', help='Skip orthogonality filtering for streets')
    parser.add_argument('--skip-orthogonalfilter-paths', action='store_true', help='Skip orthogonality filtering for paths')
    parser.add_argument('--skip-manual-interventions', action='store_true', help='Skip manual interventions from data/exclude_ways.txt and data/include_ways.txt')
    parser.add_argument('--skip-bikelanes', action='store_true', help='Skip processing of bikelanes dataset')
    parser.add_argument('--skip-streets', action='store_true', help='Skip processing of streets dataset')
    parser.add_argument('--skip-paths', action='store_true', help='Skip processing of paths dataset')
    parser.add_argument('--skip-difference-streets-bikelanes', action='store_true', help='Skip difference: only streets without bikelanes')
    parser.add_argument('--skip-difference-paths-streets-bikelanes', action='store_true', help='Skip difference: only paths without streets and bikelanes')
    parser.add_argument('--use-all-streets-in-buffer', action='store_true', help='Verwende alle Straßen im Buffer anstatt nur Straßen ohne Radwege für das finale Dataset')
    parser.add_argument('--clip-neukoelln', action='store_true', help='Verwende Neukölln-spezifische Eingabedateien')
    return parser.parse_args()


def process_data_source(osm_fgb_path, output_prefix, vorrangnetz_gdf, unified_buffer, args):
    """
    Führt den kompletten Verarbeitungsprozess für eine Datenquelle durch.
    Gibt das finale GeoDataFrame zurück.
    """
    print(f"\n--- Starte Verarbeitung für: {output_prefix} ---")
    # Schritt 1: OSM-Daten laden
    osm_gdf = load_geodataframe(osm_fgb_path, f"OSM {output_prefix}", TARGET_CRS)
    # Schritt 2: OSM-Wege im Buffer finden
    cache_path = f'./output/matching/osm_{output_prefix}_in_buffering.fgb'
    matched_gdf_step1 = find_osm_ways_in_buffer(osm_gdf, unified_buffer, cache_path)
    # Schritt 3: Optional Orthogonalfilter anwenden
    use_orthogonal_filter = (output_prefix == 'bikelanes' and not args.skip_orthogonalfilter_bikelanes) or \
                            (output_prefix == 'streets' and not args.skip_orthogonalfilter_streets) or \
                            (output_prefix == 'paths' and not args.skip_orthogonalfilter_paths)

    if use_orthogonal_filter:
        matched_gdf, _ = apply_orthogonal_filter_if_requested(args, vorrangnetz_gdf, osm_gdf, matched_gdf_step1, output_prefix)
    else:
        print(f"Orthogonalitäts-Filter für {output_prefix} übersprungen.")
        id_col = 'tilda_osm_id' if 'tilda_osm_id' in matched_gdf_step1.columns else 'tilda_id'
        matched_gdf = matched_gdf_step1

    # Schritt 4: Manuelle Eingriffe anwenden
    matched_gdf = apply_manual_interventions(args, matched_gdf, osm_gdf, output_prefix)
    # Schritt 5: Ergebnisse schreiben
    write_outputs(matched_gdf, output_prefix)
    # Exportiere gematchte OSM way IDs als Textliste
    export_matched_way_ids(matched_gdf, output_prefix)
    print(f"--- Verarbeitung für {output_prefix} abgeschlossen ---")
    return matched_gdf


def combine_multiple_datasets(datasets, output_path):
    """
    Kombiniert mehrere Datensätze (Straßen, Fahrradwege, Wege) zu einem einzigen GeoDataFrame.
    Behandelt doppelte Spaltennamen und stellt sicher, dass keine Daten verloren gehen.
    """
    print("\n--- Kombiniere mehrere Datensätze ---")
    
    combined_gdfs = []
    
    # Füge Datenquellen-Attribut hinzu
    for source_name, gdf in datasets.items():
        if gdf is not None:
            gdf_copy = gdf.copy()
            gdf_copy['data_source'] = source_name
            combined_gdfs.append(gdf_copy)
    
    if not combined_gdfs:
        print("Keine Daten zum Kombinieren verfügbar.")
        return None
    
    # Ermittle alle vorhandenen Spalten
    all_columns = set()
    for gdf in combined_gdfs:
        all_columns.update(gdf.columns)
    
    # Sortiere die Spalten für eine konsistente Reihenfolge
    all_columns = sorted(all_columns)
    
    # Harmonisiere die Spalten für alle GeoDataFrames
    print("Harmonisiere Spalten...")
    harmonized_gdfs = []
    for i, gdf in enumerate(combined_gdfs):
        print_progressbar(i + 1, len(combined_gdfs), prefix="Harmonisiere: ", length=50)
        
        # Füge fehlende Spalten hinzu
        for col in all_columns:
            if col not in gdf.columns and col != 'geometry':
                gdf[col] = None
        
        # Stelle sicher, dass alle Spalten in der gleichen Reihenfolge sind
        gdf = gdf.reindex(columns=all_columns)
        harmonized_gdfs.append(gdf)
    
    # Kombiniere die GeoDataFrames
    print("\nKombiniere GeoDataFrames...")
    combined_gdf = pd.concat(harmonized_gdfs, ignore_index=True)
    
    # Entferne doppelte Spaltennamen (falls vorhanden)
    if combined_gdf.columns.duplicated().any():
        print("Entferne doppelte Spaltennamen...")
        combined_gdf = combined_gdf.loc[:, ~combined_gdf.columns.duplicated()]
    
    # Prüfe auf doppelte Geometrien/IDs
    id_col = 'tilda_id' if 'tilda_id' in combined_gdf.columns else 'tilda_osm_id'
    if id_col in combined_gdf.columns:
        initial_count = len(combined_gdf)
        combined_gdf = combined_gdf.drop_duplicates(subset=[id_col])
        if len(combined_gdf) < initial_count:
            print(f"Warnung: {initial_count - len(combined_gdf)} doppelte Einträge basierend auf {id_col} entfernt.")
    
    # Speichere das kombinierte GeoDataFrame
    print(f"Speichere kombinierte Daten als {output_path}...")
    combined_gdf.to_file(output_path, driver='FlatGeobuf')
    
    print(f"Kombinierte Daten erfolgreich gespeichert:")
    print(f"  - Gesamtanzahl Features: {len(combined_gdf)}")
    for source_name in datasets.keys():
        if datasets[source_name] is not None:
            source_count = len(combined_gdf[combined_gdf['data_source'] == source_name])
            print(f"  - {source_name.capitalize()}: {source_count}")
    
    return combined_gdf


def calculate_difference_datasets(base_gdf, subtract_gdf, output_path, base_name, subtract_name):
    """
    Berechnet die Differenz zwischen zwei Datensätzen (base_gdf - subtract_gdf).
    """
    if base_gdf is not None and subtract_gdf is not None:
        print(f"\n--- Berechne Differenz: {base_name} ohne {subtract_name} ---")
        difference_gdf = get_or_create_difference_fgb(
            base_gdf,
            subtract_gdf,
            output_path,
            target_crs=TARGET_CRS
        )
        print(f"Differenz-Datei gespeichert: {output_path}")
        return difference_gdf
    else:
        print(f"Warnung: Differenz {base_name}-{subtract_name} kann nicht berechnet werden, da eine der Eingabedateien fehlt.")
        return None


def calculate_multiple_difference_datasets(base_gdf, subtract_gdfs, output_path, base_name, subtract_names):
    """
    Berechnet die Differenz zwischen einem Datensatz und mehreren anderen Datensätzen.
    base_gdf - (subtract_gdf1 + subtract_gdf2 + ...)
    """
    if base_gdf is None:
        print(f"Warnung: Basis-Datensatz {base_name} ist nicht verfügbar.")
        return None
    
    # Filtere nur verfügbare Datensätze zum Subtrahieren
    available_subtract_gdfs = [gdf for gdf in subtract_gdfs if gdf is not None]
    available_subtract_names = [name for gdf, name in zip(subtract_gdfs, subtract_names) if gdf is not None]
    
    if not available_subtract_gdfs:
        print(f"Warnung: Keine Datensätze zum Subtrahieren von {base_name} verfügbar.")
        return None
    
    print(f"\n--- Berechne Differenz: {base_name} ohne {' und '.join(available_subtract_names)} ---")
    
    # Kombiniere alle zu subtrahierenden Datensätze
    print("Kombiniere Datensätze zum Subtrahieren...")
    combined_subtract_gdf = pd.concat(available_subtract_gdfs, ignore_index=True)
    
    # Entferne Duplikate basierend auf der ID-Spalte
    id_col = 'tilda_id' if 'tilda_id' in combined_subtract_gdf.columns else 'tilda_osm_id'
    if id_col in combined_subtract_gdf.columns:
        initial_count = len(combined_subtract_gdf)
        combined_subtract_gdf = combined_subtract_gdf.drop_duplicates(subset=[id_col])
        if len(combined_subtract_gdf) < initial_count:
            print(f"Entfernte {initial_count - len(combined_subtract_gdf)} Duplikate aus kombinierten Subtraktions-Datensatz.")
    
    # Führe die Differenz-Berechnung durch
    difference_gdf = get_or_create_difference_fgb(
        base_gdf,
        combined_subtract_gdf,
        output_path,
        target_crs=TARGET_CRS
    )
    print(f"Differenz-Datei gespeichert: {output_path}")
    return difference_gdf


def main():
    """
    Orchestriert den gesamten Matching- und Filterprozess.
    """
    args = parse_arguments()
    
    # Konfiguriere Datenquellen basierend auf Neukölln-Parameter
    DATA_SOURCES = get_data_sources_config(use_neukoelln=args.clip_neukoelln)
    
    if args.clip_neukoelln:
        print("--- Verwende Neukölln-spezifische Eingabedateien ---")
    else:
        print("--- Verwende Standard-Eingabedateien (ganz Berlin) ---")
    
    # Vorrangnetz einmalig laden
    vorrangnetz_gdf = load_geodataframe(INPUT_VORRANGNETZ_FGB, "Vorrangnetz", TARGET_CRS)

    # Dictionary zum Sammeln aller verarbeiteten Datensätze
    processed_datasets = {}

    # Verarbeitung für alle konfigurierten Datenquellen
    for source_name, source_config in DATA_SOURCES.items():
        # Prüfe, ob diese Datenquelle übersprungen werden soll
        skip_arg = f"skip_{source_name}"
        if hasattr(args, skip_arg) and getattr(args, skip_arg):
            print(f"--- Überspringe Verarbeitung für {source_name} ---")
            processed_datasets[source_name] = None
            continue

        # Erstelle Buffer für diese Datenquelle
        buffer_size = source_config['buffer_meters']
        unified_buffer, _ = create_unified_buffer(vorrangnetz_gdf, buffer_size, TARGET_CRS)
        
        # Verarbeite die Datenquelle
        processed_gdf = process_data_source(
            source_config['file_path'], 
            source_name, 
            vorrangnetz_gdf, 
            unified_buffer, 
            args
        )
        processed_datasets[source_name] = processed_gdf

    # Differenz-Berechnungen
    # Straßen ohne Radwege
    streets_without_bikelanes = None
    if not args.skip_difference_streets_bikelanes:
        output_path = './output/matched/matched_tilda_streets_without_bikelanes.fgb'
        streets_without_bikelanes = calculate_difference_datasets(
            processed_datasets.get('streets'),
            processed_datasets.get('bikelanes'),
            output_path,
            'streets',
            'bikelanes'
        )

    # Wege ohne Straßen UND Radwege
    paths_without_streets_and_bikelanes = None
    if not args.skip_difference_paths_streets_bikelanes:
        output_path = './output/matched/matched_tilda_paths_without_streets_and_bikelanes.fgb'
        paths_without_streets_and_bikelanes = calculate_multiple_difference_datasets(
            processed_datasets.get('paths'),
            [processed_datasets.get('streets'), processed_datasets.get('bikelanes')],
            output_path,
            'paths',
            ['streets', 'bikelanes']
        )

    # Kombiniere alle verfügbaren Datensätze (ohne Überschneidungen)
    datasets_for_combination = {}
    # Verwende alle Radwege
    if processed_datasets.get('bikelanes') is not None:
        datasets_for_combination['bikelanes'] = processed_datasets['bikelanes']
    
    # Entscheide, ob alle Straßen oder nur Straßen ohne Radwege verwendet werden sollen
    if args.use_all_streets_in_buffer:
        # Verwende alle Straßen im Buffer
        if processed_datasets.get('streets') is not None:
            datasets_for_combination['streets'] = processed_datasets['streets']
            print("Hinweis: Verwende alle Straßen im Buffer für das finale Dataset.")
    else:
        # Verwende nur Straßen ohne Radwege (um Überschneidungen zu vermeiden)
        if streets_without_bikelanes is not None:
            datasets_for_combination['streets'] = streets_without_bikelanes
    
    # Verwende die gefilterten Wege (ohne Streets und Bikelanes) anstatt der ursprünglichen Wege
    if paths_without_streets_and_bikelanes is not None:
        datasets_for_combination['paths'] = paths_without_streets_and_bikelanes

    if datasets_for_combination:
        combined_path = './output/matched/matched_tilda_ways.fgb'
        combined_gdf = combine_multiple_datasets(datasets_for_combination, combined_path)
        if combined_gdf is not None:
            print(f"Kombinierte Daten gespeichert: {combined_path}")
            if args.use_all_streets_in_buffer:
                print(f"Hinweis: Alle Straßen im Buffer wurden verwendet. Wege wurden von Straßen und Radwegen subtrahiert.")
            else:
                print(f"Hinweis: Wege wurden von Straßen und Radwegen subtrahiert, um Überschneidungen zu vermeiden.")
    else:
        print("Warnung: Keine Daten zum Kombinieren verfügbar.")

    # TODO Disabled export geojson for now
    # PMTiles-Export am Ende
    # print('Exportiere alle .fgb als .geojson ...')
    # export_all_geojson()

if __name__ == '__main__':
    main()
