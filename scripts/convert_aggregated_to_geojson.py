#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
convert_aggregated_to_geojson.py
---------------------------------
Konvertiert das aggregierte GeoPackage mit zwei Layern in eine einzige GeoJSON-Datei.

Dieses Skript lädt die beiden Layer 'hinrichtung' (ri=0) und 'gegenrichtung' (ri=1) 
aus dem aggregierten GeoPackage und fügt sie zu einem einzigen GeoDataFrame zusammen.
Das Ergebnis wird als GeoJSON exportiert.

Die beiden Layer enthalten dieselben Attribute und werden einfach vertikal 
zusammengeführt (concatenated), ohne objektbasierte Joins.

VERWENDUNG:
    python scripts/convert_aggregated_to_geojson.py
    
    # Mit benutzerdefinierten Pfaden:
    python scripts/convert_aggregated_to_geojson.py \
        --input output/aggregated_rvn_final.gpkg \
        --output output/aggregated_rvn_final.geojson

INPUT:
- output/aggregated_rvn_final.gpkg (GeoPackage mit zwei Layern)
  - Layer "hinrichtung": Kanten mit ri=0 (387 Features)
  - Layer "gegenrichtung": Kanten mit ri=1 (384 Features)

OUTPUT:
- output/aggregated_rvn_final.geojson (vereinigte GeoJSON-Datei mit 771 Features)
"""

import argparse
import logging
import sys
import os

import geopandas as gpd
import pandas as pd

# Füge den processing Pfad zum sys.path hinzu, um Helpers zu importieren
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'processing'))

try:
    from helpers.globals import DEFAULT_CRS, DEFAULT_OUTPUT_DIR
except ImportError:
    # Fallback-Werte falls Import fehlschlägt
    DEFAULT_CRS = 25833
    DEFAULT_OUTPUT_DIR = "output/"


def convert_geopackage_to_geojson(input_path: str, output_path: str):
    """
    Konvertiert ein GeoPackage mit zwei Layern in eine einzige GeoJSON-Datei.
    
    Args:
        input_path: Pfad zum GeoPackage mit den beiden Layern
        output_path: Pfad für die Ausgabe-GeoJSON-Datei
    """
    try:
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
        
        # Erstelle das Ausgabeverzeichnis falls es nicht existiert
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        # Exportiere als GeoJSON
        logging.info(f"Exportiere {len(combined_gdf)} Features nach {output_path}")
        combined_gdf.to_file(output_path, driver="GeoJSON")
        
        # Statistiken ausgeben
        logging.info(f"✔ Konvertierung erfolgreich abgeschlossen!")
        logging.info(f"  Hinrichtung (ri=0): {len(hinrichtung_gdf)} Features")
        logging.info(f"  Gegenrichtung (ri=1): {len(gegenrichtung_gdf)} Features")
        logging.info(f"  Gesamt: {len(combined_gdf)} Features")
        
        # Prüfe ri-Verteilung im kombinierten Datensatz
        if 'ri' in combined_gdf.columns:
            ri_counts = combined_gdf['ri'].value_counts().sort_index()
            logging.info(f"  Richtungsverteilung: {dict(ri_counts)}")
        
        print(f"✔ {len(combined_gdf)} Features erfolgreich nach {output_path} exportiert")
        
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
        description="Konvertiert aggregiertes GeoPackage mit zwei Layern in eine GeoJSON-Datei."
    )
    parser.add_argument(
        "--input",
        default=f"{DEFAULT_OUTPUT_DIR}/aggregated_rvn_final.gpkg",
        help="Pfad zum GeoPackage mit den beiden Layern (default: output/aggregated_rvn_final.gpkg)"
    )
    parser.add_argument(
        "--output", 
        default=f"{DEFAULT_OUTPUT_DIR}/aggregated_rvn_final.geojson",
        help="Pfad für die Ausgabe-GeoJSON-Datei (default: output/aggregated_rvn_final.geojson)"
    )
    
    args = parser.parse_args()
    
    # Überprüfe, ob die Eingabedatei existiert
    if not os.path.exists(args.input):
        logging.error(f"Eingabedatei nicht gefunden: {args.input}")
        sys.exit(1)
    
    # Konvertierung durchführen
    convert_geopackage_to_geojson(args.input, args.output)


if __name__ == "__main__":
    main()
