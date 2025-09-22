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
Standardmäßig werden diese drei Dateien automatisch konvertiert:
- aggregated_rvn_final.gpkg
- snapping_network_enriched.fgb  
- matched/matched_tilda_ways.fgb

KONFIGURATION:
Das Skript kann über die globale Variable EXCLUDE_FIELD_PREFIXES konfiguriert werden,
um bestimmte Spalten basierend auf ihren Präfixen vom Export auszuschließen.
Standardmäßig werden Spalten die mit 'priority' oder 'angle' beginnen entfernt.

VERWENDUNG:
    # Automatische Konvertierung aller Standarddateien
    python scripts/convert_to_geojson.py
    
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

# Globale Konfiguration: Felder die entfernt werden sollen
# Alle Spalten die mit diesen Präfixen beginnen werden aus dem Export ausgeschlossen
EXCLUDE_FIELD_PREFIXES = ['priority', 'angle']

# Standard-Dateien die automatisch konvertiert werden sollen
DEFAULT_FILES = [
    'aggregated_rvn_final.gpkg',
    'snapping_converted_bikelanes.fgb',
    'matched/matched_tilda_ways.fgb'
]


def find_default_files(base_path: str) -> list:
    """
    Findet die Standard-Dateien im angegebenen Verzeichnis.
    
    Args:
        base_path: Basis-Pfad (normalerweise output-Verzeichnis)
        
    Returns:
        Liste der gefundenen Dateipfade
    """
    found_files = []
    
    for file_pattern in DEFAULT_FILES:
        file_path = os.path.join(base_path, file_pattern)
        if os.path.exists(file_path):
            found_files.append(file_path)
            logging.info(f"Gefundene Standard-Datei: {file_path}")
        else:
            logging.warning(f"Standard-Datei nicht gefunden: {file_path}")
    
    return found_files


def convert_multiple_files(input_files: list, output_dir: str):
    """
    Konvertiert mehrere Dateien zu GeoJSON.
    
    Args:
        input_files: Liste der Eingabedateien
        output_dir: Verzeichnis für die Ausgabedateien
    """
    success_count = 0
    
    for input_file in input_files:
        try:
            # Erstelle Ausgabedateiname basierend auf Eingabedatei
            filename = os.path.basename(input_file)
            name_without_ext = os.path.splitext(filename)[0]
            output_file = os.path.join(output_dir, f"{name_without_ext}.geojson")
            
            logging.info(f"\n{'='*60}")
            logging.info(f"Konvertiere: {input_file}")
            logging.info(f"Nach: {output_file}")
            logging.info(f"{'='*60}")
            
            convert_to_geojson(input_file, output_file)
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


def convert_to_geojson(input_path: str, output_path: str):
    """
    Konvertiert eine Geodatei (GeoPackage oder FlatGeoBuf) in GeoJSON-Format.
    
    Args:
        input_path: Pfad zur Eingabedatei
        output_path: Pfad für die Ausgabe-GeoJSON-Datei
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
        convert_to_geojson(args.input, args.output)
        
    else:
        # Automatische Konvertierung der Standard-Dateien
        logging.info("Keine spezifische Eingabedatei angegeben - konvertiere Standard-Dateien")
        
        # Finde Standard-Dateien
        default_files = find_default_files(args.output_dir)
        
        if not default_files:
            logging.error("Keine Standard-Dateien gefunden!")
            logging.info(f"Gesuchte Dateien in {args.output_dir}:")
            for file_pattern in DEFAULT_FILES:
                logging.info(f"  - {file_pattern}")
            sys.exit(1)
        
        # Konvertiere alle gefundenen Dateien
        success_count = convert_multiple_files(default_files, args.output_dir)
        
        if success_count == 0:
            logging.error("Keine Dateien erfolgreich konvertiert!")
            sys.exit(1)


if __name__ == "__main__":
    main()
