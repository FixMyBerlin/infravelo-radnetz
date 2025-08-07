#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extract_rvn_by_bezirk.py
-------------------------
Extrahiert Wege aus dem Berlin Radvorrangsnetz.fgb für jeden Berliner Bezirk
und speichert sie als separate GeoJSON-Dateien.

Input-Dateien:
- data/Berlin Bezirke.gpkg - Grenzen der Berliner Bezirke
- data/Berlin Radvorrangsnetz.fgb - Berlin Radvorrangsnetz

Output-Dateien:
- scripts/output/rvn_by_bezirk/{bezirk_name}.geojson - Radvorrangsnetz für jeden Bezirk
"""

import argparse
import logging
import os
import sys
from pathlib import Path

import geopandas as gpd

# Konstanten
DEFAULT_CRS = 25833  # EPSG-Code für Standard-Koordinatensystem


def setup_logging():
    """Konfiguriert das Logging."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )


def load_bezirke(data_dir: str) -> gpd.GeoDataFrame:
    """
    Lädt die Berliner Bezirksgrenzen.
    
    Args:
        data_dir: Pfad zum Datenverzeichnis
    
    Returns:
        GeoDataFrame mit den Bezirksgrenzen
    """
    bezirke_path = os.path.join(data_dir, "Berlin Bezirke.gpkg")
    
    if not os.path.exists(bezirke_path):
        raise FileNotFoundError(f"Bezirke-Datei nicht gefunden: {bezirke_path}")
    
    logging.info(f"Lade Bezirksgrenzen: {bezirke_path}")
    bezirke = gpd.read_file(bezirke_path)
    
    # Zur Standard-CRS transformieren
    if bezirke.crs != f"EPSG:{DEFAULT_CRS}":
        logging.info(f"Transformiere Bezirke zu CRS {DEFAULT_CRS}")
        bezirke = bezirke.to_crs(f"EPSG:{DEFAULT_CRS}")
    
    # Verwende explizit die Spalte 'namgem' als Bezirksname
    if 'namgem' in bezirke.columns:
        name_column = 'namgem'
        logging.info(f"Verwende Spalte 'namgem' als Bezirksname")
    else:
        # Prüfen ob Name-Spalte existiert
        name_columns = [col for col in bezirke.columns if 'name' in col.lower() or 'bezirk' in col.lower()]
        if not name_columns:
            # Fallback: erste String-Spalte verwenden
            string_columns = [col for col in bezirke.columns if bezirke[col].dtype == 'object' and col != 'geometry']
            if string_columns:
                name_column = string_columns[0]
                logging.info(f"Verwende Spalte '{name_column}' als Bezirksname")
            else:
                raise ValueError("Keine geeignete Spalte für Bezirksnamen gefunden")
        else:
            name_column = name_columns[0]
            logging.info(f"Verwende Spalte '{name_column}' als Bezirksname")
    bezirke['bezirk_name'] = bezirke[name_column]
    logging.info(f"Gefundene Bezirke: {', '.join(bezirke['bezirk_name'].tolist())}")
    
    return bezirke


def load_radvorrangsnetz(data_dir: str) -> gpd.GeoDataFrame:
    """
    Lädt das Berlin Radvorrangsnetz.
    
    Args:
        data_dir: Pfad zum Datenverzeichnis
    
    Returns:
        GeoDataFrame mit dem Radvorrangsnetz
    """
    rvn_path = os.path.join(data_dir, "Berlin Radvorrangsnetz.fgb")
    
    if not os.path.exists(rvn_path):
        raise FileNotFoundError(f"Radvorrangsnetz-Datei nicht gefunden: {rvn_path}")
    
    logging.info(f"Lade Radvorrangsnetz: {rvn_path}")
    rvn = gpd.read_file(rvn_path)
    
    # Zur Standard-CRS transformieren
    if rvn.crs != f"EPSG:{DEFAULT_CRS}":
        logging.info(f"Transformiere Radvorrangsnetz zu CRS {DEFAULT_CRS}")
        rvn = rvn.to_crs(f"EPSG:{DEFAULT_CRS}")
    
    logging.info(f"Radvorrangsnetz geladen: {len(rvn)} Wege")
    return rvn


def extract_rvn_for_bezirk(rvn: gpd.GeoDataFrame, bezirk_geometry, bezirk_name: str) -> gpd.GeoDataFrame:
    """
    Extrahiert Radvorrangsnetz-Wege für einen spezifischen Bezirk.
    
    Args:
        rvn: GeoDataFrame mit dem kompletten Radvorrangsnetz
        bezirk_geometry: Geometrie des Bezirks
        bezirk_name: Name des Bezirks
    
    Returns:
        GeoDataFrame mit den Wegen im Bezirk
    """
    logging.info(f"Extrahiere Wege für Bezirk: {bezirk_name}")
    
    # Spatial Join: Finde alle Wege die den Bezirk überschneiden
    rvn_in_bezirk = rvn[rvn.intersects(bezirk_geometry)]
    
    logging.info(f"Gefundene Wege in {bezirk_name}: {len(rvn_in_bezirk)}")
    
    return rvn_in_bezirk


def save_bezirk_geojson(rvn_bezirk: gpd.GeoDataFrame, bezirk_name: str, output_dir: str):
    """
    Speichert das Radvorrangsnetz eines Bezirks als GeoJSON.
    
    Args:
        rvn_bezirk: GeoDataFrame mit den Wegen des Bezirks
        bezirk_name: Name des Bezirks
        output_dir: Ausgabeverzeichnis
    """
    # Bereinige Bezirksnamen für Dateinamen
    clean_name = bezirk_name.replace(' ', '_').replace('/', '_').replace('\\', '_')
    output_path = os.path.join(output_dir, f"{clean_name}.geojson")
    
    if len(rvn_bezirk) == 0:
        logging.warning(f"Keine Wege für Bezirk {bezirk_name} gefunden - erstelle leere Datei")
        # Erstelle leere GeoJSON-Datei
        empty_gdf = gpd.GeoDataFrame(columns=rvn_bezirk.columns, crs=rvn_bezirk.crs)
        empty_gdf.to_file(output_path, driver='GeoJSON')
    else:
        logging.info(f"Speichere {len(rvn_bezirk)} Wege für {bezirk_name}: {output_path}")
        # Transformiere zu WGS84 für GeoJSON
        rvn_bezirk_wgs84 = rvn_bezirk.to_crs("EPSG:4326")
        rvn_bezirk_wgs84.to_file(output_path, driver='GeoJSON')


def main():
    """Hauptfunktion des Skripts."""
    # Argument-Parser konfigurieren
    parser = argparse.ArgumentParser(
        description="Extrahiert Radvorrangsnetz-Wege für jeden Berliner Bezirk"
    )
    parser.add_argument(
        '--data-dir',
        default='./data/',
        help='Verzeichnis mit den Eingabedateien (default: ./data/)'
    )
    parser.add_argument(
        '--output-dir',
        default='./scripts/output/rvn_by_bezirk/',
        help='Ausgabeverzeichnis für die Bezirks-GeoJSON-Dateien (default: ./scripts/output/rvn_by_bezirk/)'
    )
    parser.add_argument(
        '--bezirk',
        help='Nur einen spezifischen Bezirk verarbeiten (für Tests)'
    )
    
    args = parser.parse_args()
    
    # Logging konfigurieren
    setup_logging()
    
    try:
        # Ausgabeverzeichnis erstellen
        os.makedirs(args.output_dir, exist_ok=True)
        logging.info(f"Ausgabeverzeichnis: {args.output_dir}")
        
        # Daten laden
        bezirke = load_bezirke(args.data_dir)
        rvn = load_radvorrangsnetz(args.data_dir)
        
        # Filter für spezifischen Bezirk falls angegeben
        if args.bezirk:
            bezirke_filtered = bezirke[bezirke['bezirk_name'].str.contains(args.bezirk, case=False, na=False)]
            if len(bezirke_filtered) == 0:
                logging.error(f"Bezirk '{args.bezirk}' nicht gefunden")
                logging.info(f"Verfügbare Bezirke: {', '.join(bezirke['bezirk_name'].tolist())}")
                return 1
            bezirke = bezirke_filtered
            logging.info(f"Verarbeite nur Bezirk(e): {', '.join(bezirke['bezirk_name'].tolist())}")
        
        # Verarbeitung für jeden Bezirk
        for idx, bezirk_row in bezirke.iterrows():
            bezirk_name = bezirk_row['bezirk_name']
            bezirk_geometry = bezirk_row['geometry']
            
            # Radvorrangsnetz für Bezirk extrahieren
            rvn_bezirk = extract_rvn_for_bezirk(rvn, bezirk_geometry, bezirk_name)
            
            # Als GeoJSON speichern
            save_bezirk_geojson(rvn_bezirk, bezirk_name, args.output_dir)
        
        logging.info("Extraktion erfolgreich abgeschlossen!")
        return 0
        
    except Exception as e:
        logging.error(f"Fehler bei der Ausführung: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
