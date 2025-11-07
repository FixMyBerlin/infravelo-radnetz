#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
convert_knotenpunkte.py
-----------------------
Konvertiert die Knotenpunkte-Datei von GeoPackage in GeoJSON-Format.

Dieses Skript lädt die Datei `knotenpunkte_mit_id_und_bezirken.gpkg` aus dem 
data-raw-tilda Verzeichnis und konvertiert sie in das GeoJSON-Format mit 
Standard-Projektion (WGS84, EPSG:4326).

INPUT:
- data-raw-tilda/knotenpunkte_mit_id_und_bezirken.gpkg

OUTPUT:
- output/knotenpunkte_mit_id_und_bezirken.geojson (in WGS84)

VERWENDUNG:
    python scripts/convert_knotenpunkte.py

Das Ergebnis wird immer als GeoJSON in WGS84 (EPSG:4326) exportiert, um der 
GeoJSON-Spezifikation zu entsprechen.
"""

import logging
import sys
import os

import geopandas as gpd

# Konfiguration für Pfade
INPUT_FILE = "./data-raw-tilda/knotenpunkte_mit_id_und_bezirken.gpkg"
OUTPUT_DIR = "./output/"
OUTPUT_FILE = "knotenpunkte_mit_id_und_bezirken.geojson"


def setup_logging():
    """Konfiguriert das Logging für das Skript."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )


def convert_knotenpunkte_to_geojson():
    """
    Konvertiert die Knotenpunkte-Datei von GeoPackage zu GeoJSON.
    
    Returns:
        bool: True wenn erfolgreich, False bei Fehler
    """
    try:
        # Überprüfe ob Eingabedatei existiert
        if not os.path.exists(INPUT_FILE):
            logging.error(f"Eingabedatei nicht gefunden: {INPUT_FILE}")
            return False
        
        # Erstelle Output-Verzeichnis falls es nicht existiert
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        
        # Vollständiger Pfad zur Ausgabedatei
        output_path = os.path.join(OUTPUT_DIR, OUTPUT_FILE)
        
        logging.info(f"Lade Knotenpunkte-Datei: {INPUT_FILE}")
        
        # Lade die GeoPackage-Datei
        gdf = gpd.read_file(INPUT_FILE)
        
        logging.info(f"Anzahl Features geladen: {len(gdf)}")
        logging.info(f"Spalten: {list(gdf.columns)}")
        logging.info(f"Ursprüngliches CRS: {gdf.crs}")
        
        # Konvertiere zu WGS84 (EPSG:4326) für GeoJSON
        if gdf.crs is not None and gdf.crs.to_string() != 'EPSG:4326':
            logging.info("Konvertiere CRS zu WGS84 (EPSG:4326)")
            gdf = gdf.to_crs('EPSG:4326')
        elif gdf.crs is None:
            logging.warning("Kein CRS definiert - Annahme: bereits WGS84")
        
        # Exportiere als GeoJSON
        logging.info(f"Exportiere als GeoJSON: {output_path}")
        gdf.to_file(output_path, driver='GeoJSON')
        
        logging.info(f"✔ Konvertierung erfolgreich abgeschlossen!")
        logging.info(f"  Ausgabedatei: {output_path}")
        logging.info(f"  Features exportiert: {len(gdf)}")
        
        return True
        
    except Exception as e:
        logging.error(f"Fehler bei der Konvertierung: {e}")
        return False


def main():
    """Hauptfunktion des Skripts."""
    setup_logging()
    
    logging.info("=" * 60)
    logging.info("Starte Konvertierung der Knotenpunkte-Datei")
    logging.info("=" * 60)
    
    success = convert_knotenpunkte_to_geojson()
    
    if success:
        logging.info("=" * 60)
        logging.info("✔ Skript erfolgreich beendet")
        logging.info("=" * 60)
        sys.exit(0)
    else:
        logging.error("=" * 60)
        logging.error("✘ Skript mit Fehlern beendet")
        logging.error("=" * 60)
        sys.exit(1)


if __name__ == "__main__":
    main()