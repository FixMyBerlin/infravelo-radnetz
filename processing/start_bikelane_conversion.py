#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
start_bikelane_conversion.py
--------------------------------------------------------------------
Konvertiert Schutzstreifen zu Radfahrstreifen basierend auf verschiedenen Kriterien:
1. Kurze Schutzstreifen (< 50m) werden zu Radfahrstreifen konvertiert
2. Schutzstreifen an Bushaltestellen werden zu Radfahrstreifen konvertiert

Dies ist ein eigenständiger Verarbeitungsschritt zwischen Snapping und finaler Aggregation.

INPUT:
- output/snapping_network_enriched.fgb (angereicherte Netzwerkdaten nach Snapping)
- output/bus_stops_on_rvn.fgb (Bushaltestellen auf dem Radvorrangsnetz)

OUTPUT:
- output/snapping_converted_bikelanes.fgb (nach Schutzstreifen-Konvertierung)
(Bei Neukölln-Clipping: snapping_converted_bikelanes_neukoelln.fgb)
"""
import argparse
import sys
from pathlib import Path
import os
import logging
import geopandas as gpd
from helpers.globals import DEFAULT_CRS
from helpers.clipping import clip_to_neukoelln, clip_to_view
from helpers.convert_schutzstreifen import convert_short_schutzstreifen_to_radfahrstreifen
from helpers.convert_schutzstreifen_at_bus_stops import (
    convert_schutzstreifen_at_bus_stops_with_gdf,
    load_bus_stops as load_bus_stops_from_path,
)


def read_input_file(file_path):
    """
    Lädt die Eingabedatei und konvertiert sie zum gewünschten CRS.
    """
    try:
        gdf = gpd.read_file(file_path)
        if gdf.crs != f"EPSG:{DEFAULT_CRS}":
            gdf = gdf.to_crs(DEFAULT_CRS)
        return gdf
    except Exception as e:
        logging.error(f"Fehler beim Laden der Datei {file_path}: {e}")
        sys.exit(1)


def process_bikelane_conversion(input_path, output_path, clip_neukoelln=False, data_dir="./data", view=None):
    """
    Hauptfunktion: Konvertiert Schutzstreifen zu Radfahrstreifen.
    
    Args:
        input_path: Pfad zur Eingabedatei (snapping_network_enriched.fgb)
        output_path: Pfad zur Ausgabedatei (snapping_converted_bikelanes.fgb)
        clip_neukoelln: Ob auf Neukölln zugeschnitten werden soll
        data_dir: Verzeichnis mit den Eingabedateien
        view: Viewport-Zuschnitt (z/lat/lon)
    """
    # Logging konfigurieren
    logging.basicConfig(
        level=logging.INFO, 
        format='%(asctime)s - %(levelname)s: %(message)s',
        datefmt='%H:%M:%S'
    )
    
    logging.info("Starte Schutzstreifen-Konvertierung...")
    
    # ---------- Eingabedaten laden ------------------------------------------
    logging.info(f"Lade angereicherte Netzwerkdaten von: {input_path}")
    gdf = read_input_file(input_path)
    
    if len(gdf) == 0:
        logging.error("Abbruch: Keine Daten in der Eingabedatei gefunden")
        sys.exit(1)
    
    logging.info(f"Eingabedaten geladen: {len(gdf)} Kanten")
    
    # Räumliche Filter anwenden (falls erforderlich)
    if clip_neukoelln:
        logging.info("Schneide Daten auf Neukölln zu...")
        neukoelln_boundary_path = f"{data_dir}/Bezirk Neukölln Grenze.fgb"
        gdf = clip_to_neukoelln(gdf, neukoelln_boundary_path)
        logging.info(f"Nach Neukölln-Zuschnitt: {len(gdf)} Kanten")
    elif view:
        logging.info(f"Schneide Daten auf Viewport zu: {view}")
        gdf = clip_to_view(gdf, view)
        logging.info(f"Nach Viewport-Zuschnitt: {len(gdf)} Kanten")
    
    # ---------- Schutzstreifen-Konvertierung 1: Kurze Schutzstreifen -------
    logging.info("Konvertiere kurze Schutzstreifen zu Radfahrstreifen...")
    
    # Zähle Schutzstreifen vor der Konvertierung
    schutzstreifen_before = len(gdf[gdf['fuehr'] == 'Schutzstreifen'])
    logging.info(f"Anzahl Schutzstreifen vor Konvertierung kurzer Segmente: {schutzstreifen_before}")
    
    gdf = convert_short_schutzstreifen_to_radfahrstreifen(
        gdf, 
        length_threshold=50.0, 
        tolerance=0.1
    )
    
    # Zähle Schutzstreifen nach der ersten Konvertierung
    schutzstreifen_after_short = len(gdf[gdf['fuehr'] == 'Schutzstreifen'])
    converted_short = schutzstreifen_before - schutzstreifen_after_short
    logging.info(f"Kurze Schutzstreifen konvertiert: {converted_short}")
    
    # ---------- Schutzstreifen-Konvertierung 2: An Bushaltestellen ---------
    logging.info("Konvertiere Schutzstreifen an Bushaltestellen zu Radfahrstreifen...")
    
    # Lade Bushaltestellen-Datei
    bus_stops_gdf = load_bus_stops_from_path("output/bus_stops_on_rvn.fgb")
    if bus_stops_gdf is None:
        logging.warning("Bushaltestellen-Datei 'output/bus_stops_on_rvn.fgb' nicht gefunden oder leer; fahre fort ohne Haltestellen-Konvertierung")
    else:
        logging.info(f"Bushaltestellen geladen: {len(bus_stops_gdf)} Haltestellen")
    
    gdf = convert_schutzstreifen_at_bus_stops_with_gdf(
        gdf,
        bus_stops_gdf,
        buffer_distance=20.0,
        tolerance=1.0,
    )
    
    # Zähle Schutzstreifen nach der zweiten Konvertierung
    schutzstreifen_final = len(gdf[gdf['fuehr'] == 'Schutzstreifen'])
    converted_bus_stops = schutzstreifen_after_short - schutzstreifen_final
    total_converted = schutzstreifen_before - schutzstreifen_final
    
    logging.info(f"Schutzstreifen an Bushaltestellen konvertiert: {converted_bus_stops}")
    logging.info(f"Gesamt konvertierte Schutzstreifen: {total_converted}")
    logging.info(f"Verbleibende Schutzstreifen: {schutzstreifen_final}")
    
    # ---------- Finale Datenbereinigung ------------------------------------
    # Entferne Breite-Attribut bei allen Kanten mit Mischverkehr mit motorisiertem Verkehr
    mischverkehr_mask = gdf['fuehr'] == 'Mischverkehr mit motorisiertem Verkehr'
    mischverkehr_count = mischverkehr_mask.sum()
    if mischverkehr_count > 0:
        logging.info(f"Entferne Breite-Attribut bei {mischverkehr_count} Kanten mit Mischverkehr")
        gdf.loc[mischverkehr_mask, 'breite'] = None
    
    # ---------- Ausgabe speichern -------------------------------------------
    # Stelle sicher, dass das Ausgabeverzeichnis existiert
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    # Lösche existierende Ausgabedatei
    Path(output_path).unlink(missing_ok=True)
    
    # Speichere Ergebnis
    gdf.to_file(output_path, driver="FlatGeoBuf")
    
    logging.info(f"✔  Schutzstreifen-Konvertierung abgeschlossen: {len(gdf)} Kanten → {output_path}")
    
    # Zusammenfassung der Konvertierung
    logging.info("=" * 60)
    logging.info("ZUSAMMENFASSUNG SCHUTZSTREIFEN-KONVERTIERUNG:")
    logging.info(f"  Schutzstreifen vor Konvertierung: {schutzstreifen_before}")
    logging.info(f"  Kurze Schutzstreifen konvertiert: {converted_short}")
    logging.info(f"  An Bushaltestellen konvertiert: {converted_bus_stops}")
    logging.info(f"  Gesamt konvertiert: {total_converted}")
    logging.info(f"  Verbleibende Schutzstreifen: {schutzstreifen_final}")
    logging.info("=" * 60)


if __name__ == "__main__":
    # Kommandozeilenargumente parsen
    ap = argparse.ArgumentParser(description="Konvertierung von Schutzstreifen zu Radfahrstreifen")
    ap.add_argument("--input", default="./output/snapping_network_enriched.fgb", 
                    help="Eingabedatei (Pfad) - Default: ./output/snapping_network_enriched.fgb")
    ap.add_argument("--output", default="./output/snapping_converted_bikelanes.fgb", 
                    help="Ausgabedatei (Pfad) - Default: ./output/snapping_converted_bikelanes.fgb")
    ap.add_argument("--clip-neukoelln", action="store_true",
                    help="Schneide Daten auf Neukölln zu (optional)")
    ap.add_argument("--data-dir", default="./data", 
                    help="Pfad zum Datenverzeichnis (default: ./data)")
    ap.add_argument("--view", type=str, 
                    help="Viewport Zuschnitt 'zoom/lat/lon' (WGS84, z.B. 18/52.488306/13.425140). Nicht zusammen mit --clip-neukoelln verwenden.")
    args = ap.parse_args()

    # Konfliktprüfung
    if args.clip_neukoelln and args.view:
        print("❌ --clip-neukoelln und --view dürfen nicht kombiniert werden")
        sys.exit(1)

    # Anpassung der Pfade für verschiedene Modi
    if args.clip_neukoelln:
        # Für Neukölln: Standardpfade mit _neukoelln Suffix anpassen
        if args.input == "./output/snapping_network_enriched.fgb":
            args.input = "./output/snapping_network_enriched_neukoelln.fgb"
        if args.output == "./output/snapping_converted_bikelanes.fgb":
            args.output = "./output/snapping_converted_bikelanes_neukoelln.fgb"
    elif args.view:
        # Für View: Pfade nach output-bbox umleiten
        if args.input == "./output/snapping_network_enriched.fgb":
            args.input = "./output-bbox/snapping_network_enriched_view.fgb"
        if args.output == "./output/snapping_converted_bikelanes.fgb":
            args.output = "./output-bbox/snapping_converted_bikelanes_view.fgb"

    # Hauptfunktion aufrufen
    process_bikelane_conversion(
        args.input, 
        args.output, 
        args.clip_neukoelln, 
        args.data_dir, 
        args.view
    )
