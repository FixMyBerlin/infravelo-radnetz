#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
enrich_rvn_with_detailnetz.py
--------------------------------------------------------------------
Anreicherung des Radvorrangsnetzes mit detaillierten Straßenabschnitten.
Erstellt einen Buffer um das Radvorrangsnetz und identifiziert alle
Straßenabschnitte innerhalb dieses Buffers. Kombiniert diese mit
fehlenden Segmenten aus dem originalen Radvorrangsnetz.

INPUT:
- output/rvn/Berlin Vorrangnetz_with_element_nr.fgb
- data/Berlin Straßenabschnitte Detailnetz.fgb

OUTPUT:
- output/rvn/vorrangnetz_details.fgb
- output/rvn/vorrangnetz_details_combined_rvn.fgb
- output/rvn/cache/vorrangnetz_buffered_25m.fgb (temporärer Cache)

VERWENDUNG:
python enrich_rvn_with_detailnetz.py
"""

import geopandas as gpd
import os
import sys
import logging

# Füge das processing-Verzeichnis zum Python-Pfad hinzu für Helper-Imports
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'processing'))

from helpers.buffer_utils import create_unified_buffer

# Konfiguration
CONFIG_VORRANGNETZ_BUFFER = 10  # Buffer-Radius in Metern
TARGET_CRS = 'EPSG:25833'  # Berlin verwendet EPSG:25833

# Logging konfigurieren
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def extract_streets_in_buffer(radvorrangsnetz_path, streets_detail_path, output_path):
    """
    TL;DR Hole alle Kanten im RVN aus dem Detailnetz und deren Attribute.

    Diese Funktion führt einen räumlichen Join zwischen einem gepufferten Vorrangnetz
    und detaillierten Straßenabschnitten durch. Es werden alle Straßenabschnitte
    identifiziert, die innerhalb des gepufferten Netzwerks liegen.

    Args:
        radvorrangsnetz_path (str): Dateipfad zum Radvorrangsnetz (FlatGeobuf).
        streets_detail_path (str): Dateipfad zu den detaillierten Straßenabschnitten (FlatGeobuf).
        output_path (str): Dateipfad für die Ausgabedatei (FlatGeobuf).
    """
    # Eingabe: Radvorrangsnetz laden
    logging.info("Lese das Radvorrangsnetz ein ...")
    radvorrangsnetz = gpd.read_file(radvorrangsnetz_path)
    
    # Stelle sicher, dass das CRS korrekt ist
    if radvorrangsnetz.crs != TARGET_CRS:
        logging.info("Transformiere CRS des Radvorrangsnetzes...")
        radvorrangsnetz = radvorrangsnetz.to_crs(TARGET_CRS)
    
    # Erstelle Buffer um das Radvorrangsnetz
    logging.info(f"Erstelle {CONFIG_VORRANGNETZ_BUFFER}m Buffer um das Radvorrangsnetz...")
    unified_buffer, buffered_gdf = create_unified_buffer(
        radvorrangsnetz, 
        CONFIG_VORRANGNETZ_BUFFER, 
        TARGET_CRS,
        cache_dir=os.path.join(os.path.dirname(output_path), "cache"),
        cap_style='round'  # Verwende 'round' für einen runden Buffer
    )

    # Eingabe: Detailnetz der Straßenabschnitte laden
    logging.info("Lese die detaillierten Straßenabschnitte ein ...")
    streets_detail = gpd.read_file(streets_detail_path)
    
    # Stelle sicher, dass beide GeoDataFrames das gleiche CRS haben
    if streets_detail.crs != TARGET_CRS:
        logging.info("Transformiere CRS der Straßenabschnitte...")
        streets_detail = streets_detail.to_crs(TARGET_CRS)

    # Räumlicher Join: Finde alle Straßenabschnitte, die im Buffer liegen
    logging.info("Führe räumlichen Join durch (Straßen im Buffer ermitteln) ...")
    
    # Stelle sicher, dass der buffered_gdf das richtige CRS hat
    if buffered_gdf.crs != TARGET_CRS:
        logging.info("Transformiere CRS des gepufferten Netzes...")
        buffered_gdf = buffered_gdf.to_crs(TARGET_CRS)
    
    streets_in_buffer = gpd.sjoin(streets_detail, buffered_gdf, how="inner", predicate="within")

    # Überflüssige Spalte aus dem Join entfernen
    if 'index_right' in streets_in_buffer.columns:
        streets_in_buffer = streets_in_buffer.drop(columns=['index_right'])

    # Ergebnis speichern
    logging.info(f"Speichere {len(streets_in_buffer)} Straßenabschnitte nach {output_path} ...")
    streets_in_buffer.to_file(output_path, driver="FlatGeobuf")

    logging.info("Extraktion der Straßen im Buffer abgeschlossen.")


def add_missing_radvorrangsnetz_segments(vorrangnetz_details_path, radvorrangsnetz_path, output_path_combined):
    """
    TL;DR Identifiziert fehlende Segmente im Detailnetz und kombiniert sie mit denen aus dem RVN.
    Identifiziert fehlende Segmente im Radvorrangsnetz, die in den Detail-Straßenabschnitten
    nicht enthalten sind, und kombiniert sie.

    Args:
        vorrangnetz_details_path (str): Pfad zu den extrahierten Detail-Straßenabschnitten.
        radvorrangsnetz_path (str): Pfad zur Originaldatei des Radvorrangsnetzes.
        output_path_combined (str): Pfad für die kombinierte Ausgabedatei.
    """
    logging.info("Lade extrahierte Detail-Straßenabschnitte...")
    vorrangnetz_details = gpd.read_file(vorrangnetz_details_path)

    logging.info("Lade das originale Radvorrangsnetz...")
    radvorrangsnetz = gpd.read_file(radvorrangsnetz_path)

    # Stelle sicher, dass beide GeoDataFrames das gleiche CRS haben
    if vorrangnetz_details.crs != radvorrangsnetz.crs:
        logging.info("Transformiere CRS des Radvorrangsnetzes...")
        radvorrangsnetz = radvorrangsnetz.to_crs(vorrangnetz_details.crs)

    logging.info("Identifiziere fehlende Segmente...")
    # Finde Segmente im Radvorrangsnetz, die sich nicht mit den Detail-Straßenabschnitten überschneiden
    joined = gpd.sjoin(radvorrangsnetz, vorrangnetz_details, how='left', predicate='intersects')
    missing_segments = joined[joined['index_right'].isnull()]

    # Entferne die überflüssigen Spalten aus dem Join
    missing_segments = missing_segments.drop(columns=['index_right'])
    # Behalte nur die Spalten des ursprünglichen Radvorrangsnetzes
    missing_segments = missing_segments[radvorrangsnetz.columns]

    if not missing_segments.empty:
        logging.info(f"{len(missing_segments)} fehlende Segmente gefunden. Kombiniere Datensätze...")
        # Kombiniere die ursprünglichen Details mit den fehlenden Segmenten
        combined_gdf = gpd.pd.concat([vorrangnetz_details, missing_segments], ignore_index=True)

        logging.info(f"Speichere den kombinierten Datensatz nach {output_path_combined}...")
        combined_gdf.to_file(output_path_combined, driver="FlatGeobuf")
    else:
        logging.info("Keine fehlenden Segmente gefunden. Kopiere ursprünglichen Datensatz.")
        vorrangnetz_details.to_file(output_path_combined, driver="FlatGeobuf")

    logging.info("Kombination der Datensätze abgeschlossen.")


def main():
    """
    Hauptfunktion des Skripts. Definiert die Dateipfade und ruft die
    Verarbeitungsfunktionen auf.
    """
    # Basisverzeichnis bestimmen (ein Verzeichnis über dem Skript)
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    output_dir = os.path.join(base_dir, "output", "rvn")
    data_dir = os.path.join(base_dir, "data")

    # Ausgabeverzeichnis erstellen, falls es nicht existiert
    os.makedirs(output_dir, exist_ok=True)
    logging.info(f"Ausgabeverzeichnis erstellt/überprüft: {output_dir}")

    # Dateipfade für Eingabe- und Ausgabedateien definieren
    # radvorrangsnetz_path = os.path.join("output", "rvn", "Berlin Vorrangnetz_with_element_nr.fgb")
    radvorrangsnetz_path = os.path.join(data_dir, "Berlin Radvorrangsnetz.fgb")
    streets_detail_path = os.path.join(data_dir, "Berlin Straßenabschnitte Detailnetz.fgb")
    output_path = os.path.join(output_dir, "vorrangnetz_details.fgb")
    output_path_combined = os.path.join(output_dir, "vorrangnetz_details_combined_rvn.fgb")

    # Prüfe, ob Eingabedateien existieren
    if not os.path.exists(radvorrangsnetz_path):
        logging.error(f"Eingabedatei nicht gefunden: {radvorrangsnetz_path}")
        return
    
    if not os.path.exists(streets_detail_path):
        logging.error(f"Eingabedatei nicht gefunden: {streets_detail_path}")
        return

    logging.info("Starte Anreicherung des Radvorrangsnetzes mit Detailnetz...")
    
    # Führe die Verarbeitungsschritte durch
    extract_streets_in_buffer(radvorrangsnetz_path, streets_detail_path, output_path)
    add_missing_radvorrangsnetz_segments(output_path, radvorrangsnetz_path, output_path_combined)
    
    logging.info("Verarbeitung abgeschlossen.")


if __name__ == "__main__":
    main()
