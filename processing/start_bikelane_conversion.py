#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
start_bikelane_conversion.py
--------------------------------------------------------------------
Konvertiert Schutzstreifen zu anderen Infrastrukturtypen basierend auf verschiedenen Kriterien:
1. Schutzstreifen an Bushaltestellen werden zu Radfahrstreifen konvertiert
2. Kurze Schutzstreifen (< 50m) an Radfahrstreifen werden zu Radfahrstreifen konvertiert
3. Kurze Schutzstreifen (< 50m) an Mischverkehr werden zu Mischverkehr konvertiert
4. Kurze Segmente an Knotenpunkten werden zu Kreuzungswegen konvertiert

Dies ist ein eigenständiger Verarbeitungsschritt zwischen Snapping und finaler Aggregation.

INPUT:
- output/snapping_network_enriched.fgb (angereicherte Netzwerkdaten nach Snapping)
- output/bus_stops_on_rvn.fgb (Bushaltestellen auf dem Radvorrangsnetz)
- data-raw-tilda/knotenpunkte_mit_id_und_bezirken.gpkg (Knotenpunkte)

OUTPUT:
- output/snapping_converted_bikelanes.fgb (nach allen Konvertierungen)
(Bei Neukölln-Clipping: snapping_converted_bikelanes_neukoelln.fgb)
"""
import argparse
import sys
from pathlib import Path
import os
import logging
import geopandas as gpd
from helpers.globals import DEFAULT_CRS
from helpers.clipping import clip_to_region, clip_to_view
from helpers.convert_schutzstreifen import convert_short_schutzstreifen_to_radfahrstreifen
from helpers.convert_schutzstreifen_at_bus_stops import (
    convert_schutzstreifen_at_bus_stops_with_gdf,
    load_bus_stops as load_bus_stops_from_path,
)
from helpers.convert_schutzstreifen_kreuzungen import convert_schutzstreifen_at_mixed_traffic
from helpers.convert_segments_near_intersections import convert_segments_near_intersections


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


def process_bikelane_conversion(input_path, output_path, clip_region=None, data_dir="./data", view=None):
    """
    Hauptfunktion: Konvertiert Schutzstreifen zu Radfahrstreifen.
    
    Args:
        input_path: Pfad zur Eingabedatei (snapping_network_enriched.fgb)
        output_path: Pfad zur Ausgabedatei (snapping_converted_bikelanes.fgb)
        clip_region: Regionaler Zuschnitt ('neukoelln', 'norden', 'sueden')
        data_dir: Verzeichnis mit den Eingabedateien
        view: Viewport-Zuschnitt (z/lat/lon)
    """
    # Logging konfigurieren
    log_level = logging.DEBUG if clip_region or view else logging.INFO
    logging.basicConfig(
        level=log_level, 
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
    if clip_region:
        logging.info(f"Schneide Daten auf Region {clip_region} zu...")
        gdf = clip_to_region(gdf, data_dir, f"EPSG:{DEFAULT_CRS}", clip_region)
        logging.info(f"Nach {clip_region}-Zuschnitt: {len(gdf)} Kanten")
    elif view:
        logging.info(f"Schneide Daten auf Viewport zu: {view}")
        gdf = clip_to_view(gdf, view)
        logging.info(f"Nach Viewport-Zuschnitt: {len(gdf)} Kanten")
    
    # Zähle Schutzstreifen vor allen Konvertierungen
    schutzstreifen_initial = len(gdf[gdf['fuehr'] == 'Schutzstreifen'])
    logging.info(f"Anzahl Schutzstreifen vor Konvertierung: {schutzstreifen_initial}")
    
    # ---------- Schutzstreifen-Konvertierung 1: An Bushaltestellen ---------
    logging.info("Konvertiere Schutzstreifen an Bushaltestellen zu Radfahrstreifen...")
    
    # Zähle Schutzstreifen vor der Radfahrstreifen-Konvertierung
    schutzstreifen_before = schutzstreifen_initial
    logging.info(f"Anzahl Schutzstreifen vor Radfahrstreifen-Konvertierung: {schutzstreifen_before}")
    
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
    
    # Zähle Schutzstreifen nach der ersten Konvertierung
    schutzstreifen_after_bus_stops = len(gdf[gdf['fuehr'] == 'Schutzstreifen'])
    converted_bus_stops = schutzstreifen_before - schutzstreifen_after_bus_stops
    logging.info(f"Schutzstreifen an Bushaltestellen konvertiert: {converted_bus_stops}")
    
    # ---------- Schutzstreifen-Konvertierung 2: Kurze Schutzstreifen -------
    logging.info("Konvertiere kurze Schutzstreifen zu Radfahrstreifen...")
    
    gdf = convert_short_schutzstreifen_to_radfahrstreifen(
        gdf, 
        length_threshold=50.0, 
        tolerance=0.1
    )
    
    # Zähle Schutzstreifen nach der zweiten Konvertierung
    schutzstreifen_after_short = len(gdf[gdf['fuehr'] == 'Schutzstreifen'])
    converted_short = schutzstreifen_after_bus_stops - schutzstreifen_after_short
    logging.info(f"Kurze Schutzstreifen zu Radfahrstreifen konvertiert: {converted_short}")
    
    # ---------- Schutzstreifen-Konvertierung 3: An Mischverkehr ------------
    logging.info("Konvertiere kurze Schutzstreifen an Mischverkehr zu Mischverkehr...")
    
    gdf = convert_schutzstreifen_at_mixed_traffic(
        gdf,
        length_threshold=50.0,
        tolerance=1.0
    )
    
    # Zähle Schutzstreifen nach der dritten Konvertierung
    schutzstreifen_after_mixed = len(gdf[gdf['fuehr'] == 'Schutzstreifen'])
    converted_mixed = schutzstreifen_after_short - schutzstreifen_after_mixed
    logging.info(f"Kurze Schutzstreifen zu Mischverkehr konvertiert: {converted_mixed}")
    
    # ---------- Führungsformen-Konvertierung 4: An Knotenpunkten -----------
    logging.info("Konvertiere kurze Segmente an Knotenpunkten zu Kreuzungswegen...")
    
    # Lade Knotenpunkte-Datei
    knotenpunkte_path = "data-raw-tilda/knotenpunkte_mit_id_und_bezirken.gpkg"
    try:
        knotenpunkte_gdf = gpd.read_file(knotenpunkte_path)
        logging.info(f"Knotenpunkte geladen: {len(knotenpunkte_gdf)} Knotenpunkte")
        
        # Zähle relevante Segmente vor Konvertierung
        segments_before = len(gdf)
        
        gdf = convert_segments_near_intersections(
            gdf=gdf,
            knotenpunkte_gdf=knotenpunkte_gdf
        )
        
        segments_after = len(gdf)
        if segments_before != segments_after:
            logging.warning(f"Anzahl Segmente hat sich geändert: {segments_before} → {segments_after}")
        
    except FileNotFoundError:
        logging.warning(f"Knotenpunkte-Datei '{knotenpunkte_path}' nicht gefunden; fahre fort ohne Knotenpunkt-Konvertierung")
    except Exception as e:
        logging.error(f"Fehler beim Laden der Knotenpunkte: {e}")
        logging.warning("Fahre fort ohne Knotenpunkt-Konvertierung")
    
    # ---------- Finale Statistik --------------------------------------------
    schutzstreifen_final = len(gdf[gdf['fuehr'] == 'Schutzstreifen'])
    total_converted = schutzstreifen_initial - schutzstreifen_final
    
    logging.info(f"Gesamt konvertierte Schutzstreifen: {total_converted}")
    logging.info(f"Verbleibende Schutzstreifen: {schutzstreifen_final}")
    
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
    logging.info("ZUSAMMENFASSUNG FÜHRUNGSFORM-KONVERTIERUNGEN:")
    logging.info(f"  Schutzstreifen initial: {schutzstreifen_initial}")
    logging.info(f"  → An Bushaltestellen zu Radfahrstreifen: {converted_bus_stops}")
    logging.info(f"  → Kurze Schutzstreifen zu Radfahrstreifen: {converted_short}")
    logging.info(f"  → (Kurze) Schutzstreifen an Kreuzungen zu Mischverkehr: {converted_mixed}")
    logging.info(f"  Gesamt konvertierte Schutzstreifen: {total_converted}")
    logging.info(f"  Verbleibende Schutzstreifen: {schutzstreifen_final}")
    logging.info(f"  + Weitere Konvertierungen an Knotenpunkten (siehe oben)")
    logging.info("=" * 60)


if __name__ == "__main__":
    # Kommandozeilenargumente parsen
    ap = argparse.ArgumentParser(description="Konvertierung von Schutzstreifen zu Radfahrstreifen")
    ap.add_argument("--input", default="./output/snapping_network_enriched.fgb", 
                    help="Eingabedatei (Pfad) - Default: ./output/snapping_network_enriched.fgb")
    ap.add_argument("--output", default="./output/snapping_converted_bikelanes.fgb", 
                    help="Ausgabedatei (Pfad) - Default: ./output/snapping_converted_bikelanes.fgb")
    ap.add_argument("--clip", type=str, choices=['neukoelln', 'norden', 'sueden'],
                    help="Regionaler Zuschnitt: 'neukoelln', 'norden' oder 'sueden'. Nicht mit --view kombinierbar.")
    ap.add_argument("--data-dir", default="./data", 
                    help="Pfad zum Datenverzeichnis (default: ./data)")
    ap.add_argument("--view", type=str, 
                    help="Viewport Zuschnitt 'zoom/lat/lon' (WGS84, z.B. 18/52.488306/13.425140). Nicht zusammen mit --clip verwenden.")
    args = ap.parse_args()

    # Konfliktprüfung
    if args.clip and args.view:
        print("❌ --clip und --view dürfen nicht kombiniert werden")
        sys.exit(1)

    # Anpassung der Pfade für verschiedene Modi
    if args.clip:
        # Für regionale Clipping: Standardpfade mit _{region} Suffix anpassen
        if args.input == "./output/snapping_network_enriched.fgb":
            args.input = f"./output/snapping_network_enriched_{args.clip}.fgb"
        if args.output == "./output/snapping_converted_bikelanes.fgb":
            args.output = f"./output/snapping_converted_bikelanes_{args.clip}.fgb"
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
        args.clip, 
        args.data_dir, 
        args.view
    )
