#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
convert_to_geojson.py
---------------------
Konvertiert Geodateien (GeoPackage, FlatGeoBuf) in GeoJSON-Format.

Dieses Skript kann verschiedene Eingabeformate verarbeiten:
1. GeoPackage mit mehreren Layern: Lädt alle verfügbaren Layer und führt sie zusammen
2. FlatGeoBuf-Dateien: Lädt die Datei direkt und konvertiert sie
3. Automatische Konvertierung der drei Standarddateien

Das Ergebnis wird immer als GeoJSON in WGS84 (EPSG:4326) exportiert, um der 
GeoJSON-Spezifikation zu entsprechen.

AUTOMATISCHE KONVERTIERUNG:
Standardmäßig werden die drei Datensätze des gewählten Netzes (--netz rvn|ren) konvertiert:
- Datensatz A: output/map-matching/matched_tilda_ways.fgb (REN+: output/map-matching-ren/)
- Datensatz B: output/snapping_converted_bikelanes.fgb (REN+: …_ren.fgb)
- Datensatz C: output/aggregated_rvn_final.gpkg (REN+: …_ren.gpkg)
Die Ausgaben heißen wie die Eingaben, beim REN+ mit dem Zusatz _ren.

Beim REN+ bekommen Datensatz B und C die Netzklasse radverkehrsnetz je element_nr aus
output/ren/ren_netz_with_element_nr.fgb. tilda-pseudo-tags/build_csv.py braucht sie.

KONFIGURATION:
Das Skript kann über die globale Variable EXCLUDE_FIELD_PREFIXES konfiguriert werden,
um bestimmte Spalten basierend auf ihren Präfixen vom Export auszuschließen.
Standardmäßig werden Spalten die mit 'priority' oder 'angle' beginnen entfernt.

VERWENDUNG:
    # Automatische Konvertierung aller Standarddateien
    python scripts/convert_to_geojson.py
    python scripts/convert_to_geojson.py --netz ren
    
    # Spezifische Datei konvertieren
    python scripts/convert_to_geojson.py \
        --input ./output/aggregated_rvn_final.gpkg \
        --output ./output/aggregated_rvn_final.geojson
    
    # Mit automatischer Benennung der Ausgabedatei
    python scripts/convert_to_geojson.py \
        --input ./output/aggregated_rvn_final.gpkg

UNTERSTÜTZTE EINGABEFORMATE:
- GeoPackage (.gpkg): Lädt alle Layer und führt sie zusammen
- FlatGeoBuf (.fgb): Lädt die Datei direkt

OUTPUT:
- GeoJSON-Datei (.geojson) in WGS84 (EPSG:4326)
- Spalten mit konfigurierten Präfixen werden automatisch ausgeschlossen
"""

import argparse
import logging
import sys
import os

import geopandas as gpd
import pandas as pd
import gzip
import shutil

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from helpers.netz import DEFAULT_NETZ, MATCHING_DIR, PFADE, add_netz_argument, datei_zusatz  # noqa: E402

# Globale Konfiguration: Felder die entfernt werden sollen
# Alle Spalten die mit diesen Präfixen beginnen werden aus dem Export ausgeschlossen
EXCLUDE_FIELD_PREFIXES = ['priority', 'angle']

# Reihenfolge der Netzklassen, falls eine element_nr im REN+ mehrfach vorkommt
# (wie NETZ_RANK in tilda-pseudo-tags/build_csv.py)
RADVERKEHRSNETZ_RANG = ['Radvorrangnetz', 'Radergänzungsnetz', 'Kein Radverkehrsnetz vorhanden']


def default_files(netz: str) -> list:
    """
    Standard-Dateien je Netz: Datensatz A, B und C.
    
    Returns:
        Liste von (Eingabedatei relativ zu processing/, Ausgabename ohne Endung)
    """
    zusatz = datei_zusatz(netz)
    return [
        (os.path.join(MATCHING_DIR[netz], 'matched_tilda_ways.fgb'), f'matched_tilda_ways{zusatz}'),
        (f'output/snapping_converted_bikelanes{zusatz}.fgb', f'snapping_converted_bikelanes{zusatz}'),
        (f'output/aggregated_rvn_final{zusatz}.gpkg', f'aggregated_rvn_final{zusatz}'),
    ]


def find_default_files(netz: str) -> list:
    """
    Findet die Standard-Dateien des Netzes.
    
    Args:
        netz: Zielnetz (rvn oder ren)
        
    Returns:
        Liste der gefundenen (Eingabedatei, Ausgabename)
    """
    found_files = []
    
    for file_path, output_name in default_files(netz):
        if os.path.exists(file_path):
            found_files.append((file_path, output_name))
            logging.info(f"Gefundene Standard-Datei: {file_path}")
        else:
            logging.warning(f"Standard-Datei nicht gefunden: {file_path}")
    
    return found_files


def convert_multiple_files(input_files: list, output_dir: str, netz: str = DEFAULT_NETZ):
    """
    Konvertiert mehrere Dateien zu GeoJSON.
    
    Args:
        input_files: Liste von (Eingabedatei, Ausgabename ohne Endung)
        output_dir: Verzeichnis für die Ausgabedateien
        netz: Zielnetz (rvn oder ren)
    """
    success_count = 0
    
    for input_file, output_name in input_files:
        try:
            output_file = os.path.join(output_dir, f"{output_name}.geojson")
            
            logging.info(f"\n{'='*60}")
            logging.info(f"Konvertiere: {input_file}")
            logging.info(f"Nach: {output_file}")
            logging.info(f"{'='*60}")
            
            convert_to_geojson(input_file, output_file, netz)
            success_count += 1
            
        except Exception as e:
            logging.error(f"Fehler bei der Konvertierung von {input_file}: {e}")
            continue
    
    logging.info(f"\n{'='*60}")
    logging.info(f"✔ Konvertierung abgeschlossen!")
    logging.info(f"  Erfolgreich konvertiert: {success_count}/{len(input_files)} Dateien")
    logging.info(f"{'='*60}")
    
    return success_count


def filter_columns(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Filtert Spalten aus dem GeoDataFrame basierend auf konfigurierten Präfixen.
    
    Args:
        gdf: Das zu filternde GeoDataFrame
        
    Returns:
        GeoDataFrame ohne die ausgeschlossenen Spalten
    """
    if not EXCLUDE_FIELD_PREFIXES:
        return gdf
    
    # Finde alle Spalten die mit den konfigurierten Präfixen beginnen
    columns_to_exclude = []
    for col in gdf.columns:
        for prefix in EXCLUDE_FIELD_PREFIXES:
            if col.lower().startswith(prefix.lower()):
                columns_to_exclude.append(col)
                break
    
    if columns_to_exclude:
        logging.info(f"Entferne {len(columns_to_exclude)} Spalten mit Präfixen {EXCLUDE_FIELD_PREFIXES}: {columns_to_exclude}")
        # Behalte nur Spalten die nicht in der Ausschlussliste stehen
        columns_to_keep = [col for col in gdf.columns if col not in columns_to_exclude]
        gdf = gdf[columns_to_keep]
    else:
        logging.info(f"Keine Spalten mit Präfixen {EXCLUDE_FIELD_PREFIXES} gefunden")
    
    return gdf


def detect_file_type(input_path: str) -> str:
    """
    Erkennt den Dateityp basierend auf der Dateierweiterung.
    
    Args:
        input_path: Pfad zur Eingabedatei
        
    Returns:
        Dateityp ('gpkg' oder 'fgb')
    """
    if input_path.lower().endswith('.gpkg'):
        return 'gpkg'
    elif input_path.lower().endswith('.fgb'):
        return 'fgb'
    else:
        raise ValueError(f"Nicht unterstütztes Dateiformat: {input_path}")


def load_flatgeobuf_data(input_path: str) -> gpd.GeoDataFrame:
    """
    Lädt eine FlatGeoBuf-Datei und gibt sie als GeoDataFrame zurück.
    
    Args:
        input_path: Pfad zur FGB-Datei
        
    Returns:
        GeoDataFrame mit den Daten
    """
    logging.info(f"Lade FlatGeoBuf-Datei: {input_path}")
    gdf = gpd.read_file(input_path)
    logging.info(f"FlatGeoBuf geladen: {len(gdf)} Features")
    return gdf


def load_geopackage_layers(input_path: str) -> gpd.GeoDataFrame:
    """
    Lädt die beiden bekannten Layer aus einem GeoPackage und führt sie zusammen.
    
    Args:
        input_path: Pfad zum GeoPackage
        
    Returns:
        Kombiniertes GeoDataFrame
    """
    # Lade beide Layer aus dem GeoPackage
    logging.info(f"Lade Layer 'hinrichtung' aus {input_path}")
    hinrichtung_gdf = gpd.read_file(input_path, layer="hinrichtung")
    
    logging.info(f"Lade Layer 'gegenrichtung' aus {input_path}")
    gegenrichtung_gdf = gpd.read_file(input_path, layer="gegenrichtung")
    
    # Überprüfe, ob beide Layer das gleiche Koordinatensystem haben
    if hinrichtung_gdf.crs != gegenrichtung_gdf.crs:
        logging.warning(
            f"Koordinatensysteme der Layer sind unterschiedlich. "
            f"Transformiere 'gegenrichtung' zu dem von 'hinrichtung'."
        )
        gegenrichtung_gdf = gegenrichtung_gdf.to_crs(hinrichtung_gdf.crs)
    
    # Überprüfe, ob beide Layer die gleichen Spalten haben
    hinrichtung_cols = set(hinrichtung_gdf.columns)
    gegenrichtung_cols = set(gegenrichtung_gdf.columns)
    
    if hinrichtung_cols != gegenrichtung_cols:
        logging.warning(
            f"Spalten der Layer sind nicht identisch. "
            f"Hinrichtung: {hinrichtung_cols - gegenrichtung_cols}, "
            f"Gegenrichtung: {gegenrichtung_cols - hinrichtung_cols}"
        )
        # Verwende die gemeinsamen Spalten
        common_cols = hinrichtung_cols.intersection(gegenrichtung_cols)
        hinrichtung_gdf = hinrichtung_gdf[list(common_cols)]
        gegenrichtung_gdf = gegenrichtung_gdf[list(common_cols)]
        logging.info(f"Verwende {len(common_cols)} gemeinsame Spalten")
    
    # Füge beide GeoDataFrames zusammen
    logging.info("Führe beide Layer zusammen...")
    combined_gdf = pd.concat([hinrichtung_gdf, gegenrichtung_gdf], 
                            ignore_index=True)
    
    # Stelle sicher, dass es ein GeoDataFrame bleibt
    combined_gdf = gpd.GeoDataFrame(combined_gdf, 
                                   geometry='geometry', 
                                   crs=hinrichtung_gdf.crs)
    
    # Sortiere nach element_nr und ri für bessere Übersicht
    if 'element_nr' in combined_gdf.columns and 'ri' in combined_gdf.columns:
        combined_gdf = combined_gdf.sort_values(['element_nr', 'ri'])
        logging.info("Daten nach element_nr und ri sortiert")
    
    # Statistiken für GeoPackage ausgeben
    logging.info(f"GeoPackage-Layer kombiniert:")
    logging.info(f"  Hinrichtung (ri=0): {len(hinrichtung_gdf)} Features")
    logging.info(f"  Gegenrichtung (ri=1): {len(gegenrichtung_gdf)} Features")
    logging.info(f"  Gesamt: {len(combined_gdf)} Features")
    
    return combined_gdf


def add_radverkehrsnetz(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Ergänzt beim REN+ die Netzklasse (radverkehrsnetz) je element_nr aus dem vorbereiteten
    Netz von process_radnetz.sh --netz ren. Das Matching-Netz führt die Spalte nicht mit.
    
    Args:
        gdf: Daten mit element_nr
        
    Returns:
        GeoDataFrame mit Spalte radverkehrsnetz
    """
    path = PFADE['ren']['mit_element_nr']
    if not os.path.exists(path):
        raise FileNotFoundError(f"{path} fehlt, zuerst ./process_radnetz.sh --netz ren ausführen")
    netz = gpd.read_file(path, columns=['element_nr', 'radverkehrsnetz'], ignore_geometry=True)
    netz['rang'] = netz['radverkehrsnetz'].map({name: i for i, name in enumerate(RADVERKEHRSNETZ_RANG)})
    klasse = netz.sort_values('rang').drop_duplicates('element_nr').set_index('element_nr')['radverkehrsnetz']
    
    gdf = gdf.copy()
    gdf['radverkehrsnetz'] = gdf['element_nr'].map(klasse)
    missing = gdf['radverkehrsnetz'].isna()
    if missing.any():
        logging.warning(f"{missing.sum()} Features ohne radverkehrsnetz (element_nr nicht in {path}), "
                        f"z. B. {sorted(gdf.loc[missing, 'element_nr'].dropna().unique())[:5]}")
    logging.info(f"radverkehrsnetz ergänzt: {gdf['radverkehrsnetz'].value_counts().to_dict()}")
    return gdf


def convert_to_geojson(input_path: str, output_path: str, netz: str = DEFAULT_NETZ):
    """
    Konvertiert eine Geodatei (GeoPackage oder FlatGeoBuf) in GeoJSON-Format.
    
    Args:
        input_path: Pfad zur Eingabedatei
        output_path: Pfad für die Ausgabe-GeoJSON-Datei
        netz: Zielnetz (rvn oder ren); beim REN+ wird radverkehrsnetz ergänzt
    """
    try:
        # Erkenne den Dateityp
        file_type = detect_file_type(input_path)
        logging.info(f"Erkannter Dateityp: {file_type.upper()}")
        
        # Lade die Daten basierend auf dem Dateityp
        if file_type == 'gpkg':
            combined_gdf = load_geopackage_layers(input_path)
        elif file_type == 'fgb':
            combined_gdf = load_flatgeobuf_data(input_path)
        else:
            raise ValueError(f"Nicht unterstützter Dateityp: {file_type}")
        
        # Filtere unerwünschte Spalten
        combined_gdf = filter_columns(combined_gdf)
        
        if netz == 'ren' and 'element_nr' in combined_gdf.columns and 'radverkehrsnetz' not in combined_gdf.columns:
            combined_gdf = add_radverkehrsnetz(combined_gdf)
        
        # Erstelle das Ausgabeverzeichnis falls es nicht existiert
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        # Konvertiere zu WGS84 (EPSG:4326) für GeoJSON-Spezifikation
        current_crs = combined_gdf.crs
        if current_crs != 'EPSG:4326':
            logging.info(f"Konvertiere CRS von {current_crs} zu WGS84 (EPSG:4326) für GeoJSON")
            combined_gdf = combined_gdf.to_crs('EPSG:4326')
        else:
            logging.info("CRS ist bereits WGS84 (EPSG:4326)")
        
        # Exportiere als GeoJSON
        logging.info(f"Exportiere {len(combined_gdf)} Features nach {output_path}")
        combined_gdf.to_file(output_path, driver="GeoJSON")
        # Komprimiere die GeoJSON-Datei zu .gz und entferne die unkomprimierte Datei
        compressed_path = f"{output_path}.gz"
        try:
            logging.info(f"Komprimiere {output_path} nach {compressed_path}")
            with open(output_path, 'rb') as f_in, gzip.open(compressed_path, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
            # Entferne die unkomprimierte GeoJSON-Datei
            os.remove(output_path)
            logging.info(f"Erzeugt komprimierte Datei: {compressed_path}")
            output_path_to_report = compressed_path
        except Exception as e:
            logging.error(f"Fehler beim Komprimieren der Datei {output_path}: {e}")
            # Falls Kompression fehlschlägt, berichte weiterhin den unkomprimierten Pfad
            output_path_to_report = output_path
        
        # Statistiken ausgeben
        logging.info(f"✔ Konvertierung erfolgreich abgeschlossen!")
        logging.info(f"  Eingabedatei: {input_path}")
        logging.info(f"  Ausgabedatei: {output_path_to_report}")
        logging.info(f"  Anzahl Features: {len(combined_gdf)}")

        # Zusätzliche Statistiken für GeoPackage
        if file_type == 'gpkg' and 'ri' in combined_gdf.columns:
            ri_counts = combined_gdf['ri'].value_counts().sort_index()
            logging.info(f"  Richtungsverteilung: {dict(ri_counts)}")

        print(f"✔ {len(combined_gdf)} Features erfolgreich von {file_type.upper()} nach GeoJSON exportiert (output: {output_path_to_report})")

    except Exception as e:
        logging.error(f"Fehler bei der Konvertierung: {e}")
        sys.exit(1)


def main():
    """
    Hauptfunktion des Skripts.
    Parst die Kommandozeilenargumente und ruft die Konvertierungsfunktion auf.
    """
    # Logging konfigurieren
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )
    
    # Kommandozeilenargumente parsen
    parser = argparse.ArgumentParser(
        description="Konvertiert Geodateien (GeoPackage, FlatGeoBuf) in GeoJSON-Format."
    )
    parser.add_argument(
        "--input",
        help="Pfad zur spezifischen Eingabedatei (.gpkg oder .fgb). Wenn nicht angegeben, werden die Standard-Dateien konvertiert."
    )
    parser.add_argument(
        "--output", 
        help="Pfad für die Ausgabe-GeoJSON-Datei (optional - wird automatisch aus Eingabedatei abgeleitet)"
    )
    parser.add_argument(
        "--output-dir",
        default="./output",
        help="Verzeichnis für Ausgabedateien bei automatischer Konvertierung (Standard: ./output)"
    )
    add_netz_argument(parser)
    
    args = parser.parse_args()
    
    # Überprüfe ob spezifische Eingabedatei angegeben wurde
    if args.input:
        # Einzelne Datei konvertieren (bisheriges Verhalten)
        if not os.path.exists(args.input):
            logging.error(f"Eingabedatei nicht gefunden: {args.input}")
            sys.exit(1)
        
        # Automatische Ausgabedatei-Benennung falls nicht angegeben
        if not args.output:
            input_path = os.path.splitext(args.input)[0]
            args.output = f"{input_path}.geojson"
            logging.info(f"Automatische Ausgabedatei: {args.output}")
        
        # Konvertierung durchführen
        convert_to_geojson(args.input, args.output, args.netz)
        
    else:
        # Automatische Konvertierung der Standard-Dateien
        logging.info("Keine spezifische Eingabedatei angegeben - konvertiere Standard-Dateien")
        
        # Finde Standard-Dateien
        found_files = find_default_files(args.netz)
        
        if not found_files:
            logging.error("Keine Standard-Dateien gefunden!")
            logging.info(f"Gesuchte Dateien (Netz {args.netz}):")
            for file_path, _ in default_files(args.netz):
                logging.info(f"  - {file_path}")
            sys.exit(1)
        
        # Konvertiere alle gefundenen Dateien
        success_count = convert_multiple_files(found_files, args.output_dir, args.netz)
        
        if success_count == 0:
            logging.error("Keine Dateien erfolgreich konvertiert!")
            sys.exit(1)


if __name__ == "__main__":
    main()
