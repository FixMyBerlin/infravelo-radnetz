#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
convert_schutzstreifen_at_bus_stops.py
--------------------------------------------------------------------
Funktionen für die Konvertierung von Schutzstreifen zu Radfahrstreifen an Bushaltestellen.

Diese Funktionen konvertieren Schutzstreifen, die:
1. Im 20m Umkreis von Bushaltestellen liegen UND 
2. An Radfahrstreifen angrenzen UND
3. Die Bushaltestelle auf der RECHTEN Seite (Fahrtrichtung) haben

Berücksichtigt Rechtsverkehr in Deutschland: Bushaltestellen befinden sich
rechts der Fahrtrichtung. Konvertierung erfolgt nur auf der Seite mit Haltestelle.

Bei MultiLineString-Geometrien: Nur die Teile werden konvertiert, die tatsächlich
im Umkreis einer Haltestelle liegen (nicht das gesamte MultiLineString).

Neue Führungsform: "Radfahrstreifen (OSM:Schutzstreifen an Haltestelle)"
"""

import logging
import pandas as pd
import geopandas as gpd
import os
from shapely.geometry import LineString, MultiLineString
from .progressbar import print_progressbar
from .schutzstreifen_conversion_helper import (
    find_schutzstreifen_adjacent_to_radfahrstreifen
)
from .bus_stop_side_detection import filter_bus_stops_by_side

logger = logging.getLogger(__name__)


def check_which_parts_have_bus_stops(geometry, bus_stops_gdf, ri, buffer_distance=20.0):
    """
    Prüft welche Teile einer (Multi)LineString-Geometrie Bushaltestellen auf der rechten Seite haben.
    
    Verwendet die modularen Funktionen aus bus_stop_side_detection.py für konsistente Logik.
    
    Args:
        geometry: LineString oder MultiLineString
        bus_stops_gdf: GeoDataFrame mit Bushaltestellen
        ri: Richtung (0=HIN, 1=RÜCK)
        buffer_distance: Puffer-Distanz für Haltestellen-Suche
        
    Returns:
        list: Indizes der Teile die Haltestellen auf der rechten Seite haben
              Für LineString: [0] wenn Haltestelle vorhanden, [] sonst
              Für MultiLineString: Liste der Teil-Indizes mit Haltestellen
    """
    from .bus_stop_side_detection import has_bus_stop_on_right_side
    
    if isinstance(geometry, LineString):
        # Einzelne LineString: Prüfe ob Haltestellen auf rechter Seite
        if has_bus_stop_on_right_side(geometry, bus_stops_gdf, ri, buffer_distance):
            return [0]
        return []
    
    elif isinstance(geometry, MultiLineString):
        # MultiLineString: Prüfe jeden Teil einzeln
        parts_with_stops = []
        
        for i, part in enumerate(geometry.geoms):
            # Prüfe ob dieser Teil Haltestellen auf rechter Seite hat
            if has_bus_stop_on_right_side(part, bus_stops_gdf, ri, buffer_distance):
                parts_with_stops.append(i)
                logger.debug(f"  Teil {i+1}/{len(geometry.geoms)}: Hat Haltestelle auf rechter Seite (Länge: {part.length:.1f}m)")
            else:
                logger.debug(f"  Teil {i+1}/{len(geometry.geoms)}: Keine Haltestelle auf rechter Seite (Länge: {part.length:.1f}m)")
        
        return parts_with_stops
    
    return []


def load_bus_stops(path, return_gdf=True):
    """
    Lädt die Bus-Haltestellen-Daten.
    
    Args:
        path: Pfad zur Bus-Haltestellen-Datei (.fgb)
        return_gdf: Wenn True, gibt GeoDataFrame zurück, sonst Pfad
        
    Returns:
        GeoDataFrame oder str: Bus-Haltestellen-Daten oder Pfad
    """
    if not os.path.exists(path):
        logger.error(f"\033[91m❌ Bus-Haltestellen-Datei nicht gefunden: {path}\033[0m")
        return gpd.GeoDataFrame() if return_gdf else None
    
    if return_gdf:
        logger.info(f"Lade Bus-Haltestellen aus {path}")
        return gpd.read_file(path)
    else:
        return path

def identify_schutzstreifen_near_bus_stops(all_ways_gdf, bus_stops_gdf, buffer_distance=20):
    """
    Identifiziere Schutzstreifen im Umkreis von Bushaltestellen.
    
    Args:
        all_ways_gdf: GeoDataFrame mit allen Wegen
        bus_stops_gdf: GeoDataFrame mit Bushaltestellen
        buffer_distance: Pufferabstand in Metern
        
    Returns:
        GeoDataFrame: Schutzstreifen in der Nähe von Bushaltestellen
    """
    if bus_stops_gdf.empty:
        logger.warning("Keine Bus-Haltestellen verfügbar")
        return gpd.GeoDataFrame()
    
    logger.info(f"Identifiziere Schutzstreifen im {buffer_distance}m Umkreis von {len(bus_stops_gdf)} Bushaltestellen")
    
    # Filtere nur Schutzstreifen
    schutzstreifen_gdf = all_ways_gdf[all_ways_gdf['fuehr'] == 'Schutzstreifen'].copy()
    logger.info(f"Gesamt Schutzstreifen im Netzwerk: {len(schutzstreifen_gdf)}")
    
    if schutzstreifen_gdf.empty:
        logger.warning("Keine Schutzstreifen im Netzwerk gefunden")
        return gpd.GeoDataFrame()
    
    # Erstelle Puffer um Bushaltestellen
    bus_buffer = bus_stops_gdf.geometry.buffer(buffer_distance).unary_union
    
    # Finde Schutzstreifen die den Puffer schneiden
    schutzstreifen_near_stops = schutzstreifen_gdf[
        schutzstreifen_gdf.geometry.intersects(bus_buffer)
    ].copy()
    
    logger.info(f"Schutzstreifen im {buffer_distance}m Umkreis von Bushaltestellen: {len(schutzstreifen_near_stops)}")
    return schutzstreifen_near_stops

def find_schutzstreifen_adjacent_to_radfahrstreifen_local(schutzstreifen_near_stops, all_ways_gdf, tolerance=1.0):
    """
    Wrapper-Funktion für find_schutzstreifen_adjacent_to_radfahrstreifen.
    """
    def progress_callback(current, total, prefix=""):
        print_progressbar(current, total, prefix)
    
    return find_schutzstreifen_adjacent_to_radfahrstreifen(
        schutzstreifen_near_stops, 
        all_ways_gdf, 
        tolerance, 
        progress_callback
    )

def convert_schutzstreifen_at_bus_stops_with_gdf(all_ways_gdf, bus_stops_gdf, 
                                                buffer_distance=20, tolerance=1.0):
    """
    Konvertiere Schutzstreifen an Bushaltestellen mit direktem GeoDataFrame.
    
    Berücksichtigt die Fahrtrichtung und konvertiert nur Schutzstreifen,
    bei denen die Bushaltestelle auf der rechten Seite liegt (Rechtsverkehr).
    
    Args:
        all_ways_gdf: GeoDataFrame mit allen Wegen
        bus_stops_gdf: GeoDataFrame mit Bushaltestellen 
        buffer_distance: Pufferabstand für Haltestellen in Metern
        tolerance: Toleranz für Angrenzungscheck in Metern
        
    Returns:
        GeoDataFrame: Aktualisierte Wege-Daten
    """
    logger.info("=== Schutzstreifen-Konvertierung an Bushaltestellen (mit Seitenprüfung) ===")
    
    if bus_stops_gdf.empty:
        logger.warning("Keine Bus-Haltestellen verfügbar - keine Konvertierung möglich")
        return all_ways_gdf.copy()
    
    result_gdf = all_ways_gdf.copy()
    
    # 1. Identifiziere Schutzstreifen im Umkreis von Bushaltestellen
    schutzstreifen_near_stops = identify_schutzstreifen_near_bus_stops(
        result_gdf, bus_stops_gdf, buffer_distance
    )
    
    if schutzstreifen_near_stops.empty:
        logger.info("Keine Schutzstreifen in der Nähe von Bushaltestellen gefunden")
        return result_gdf
    
    # 2. Prüfe welche Schutzstreifen an Radfahrstreifen angrenzen
    logger.info("Prüfe Angrenzung an Radfahrstreifen (mit Richtungscheck)...")
    schutzstreifen_adjacent = find_schutzstreifen_adjacent_to_radfahrstreifen_local(
        schutzstreifen_near_stops, result_gdf, tolerance
    )
    
    if schutzstreifen_adjacent.empty:
        logger.info("Keine Schutzstreifen an Bushaltestellen grenzen an Radfahrstreifen an")
        return result_gdf
    
    logger.info(f"Schutzstreifen die an Radfahrstreifen angrenzen: {len(schutzstreifen_adjacent)}")
    
    # 3. NEU: Prüfe für jeden Schutzstreifen, ob Haltestelle auf der richtigen Seite ist
    #    Bei MultiLineString: Prüfe welche Teile Haltestellen haben
    logger.info("Prüfe Seitenpositionierung der Bushaltestellen (Rechtsverkehr)...")
    logger.info("Bei MultiLineString: Nur Teile mit Haltestellen werden konvertiert")
    
    schutzstreifen_to_convert = []  # Liste von (idx, parts_to_convert) Tupeln
    side_stats = {
        'ri_0_right': 0, 'ri_0_wrong': 0, 'ri_1_right': 0, 'ri_1_wrong': 0,
        'multiline_full': 0, 'multiline_partial': 0, 'multiline_skipped': 0
    }
    
    for idx, schutzstreifen in schutzstreifen_adjacent.iterrows():
        ri = schutzstreifen.get('ri', None)
        sfid = schutzstreifen.get('sfid', idx)
        geometry = schutzstreifen.geometry
        
        # Prüfe welche Teile Haltestellen auf der rechten Seite haben
        parts_with_stops = check_which_parts_have_bus_stops(
            geometry, bus_stops_gdf, ri, buffer_distance
        )
        
        if len(parts_with_stops) > 0:
            # Bei MultiLineString: Prüfe ob alle oder nur einige Teile betroffen sind
            if isinstance(geometry, MultiLineString):
                total_parts = len(geometry.geoms)
                if len(parts_with_stops) == total_parts:
                    side_stats['multiline_full'] += 1
                    logger.debug(f"✓ sfid={sfid} (ri={ri}): MultiLineString - ALLE {total_parts} Teile haben Haltestellen → vollständig konvertiert")
                else:
                    side_stats['multiline_partial'] += 1
                    logger.info(f"✓ sfid={sfid} (ri={ri}): MultiLineString - {len(parts_with_stops)}/{total_parts} Teile haben Haltestellen → teilweise konvertiert")
            else:
                logger.debug(f"✓ sfid={sfid} (ri={ri}): LineString hat Haltestelle auf rechter Seite → wird konvertiert")
            
            schutzstreifen_to_convert.append((idx, parts_with_stops))
            
            if ri == 0:
                side_stats['ri_0_right'] += 1
            elif ri == 1:
                side_stats['ri_1_right'] += 1
        else:
            if isinstance(geometry, MultiLineString):
                side_stats['multiline_skipped'] += 1
                logger.debug(f"✗ sfid={sfid} (ri={ri}): MultiLineString - KEIN Teil hat Haltestelle auf rechter Seite → wird NICHT konvertiert")
            else:
                logger.debug(f"✗ sfid={sfid} (ri={ri}): Keine Haltestelle auf rechter Seite → wird NICHT konvertiert")
            
            if ri == 0:
                side_stats['ri_0_wrong'] += 1
            elif ri == 1:
                side_stats['ri_1_wrong'] += 1
    
    # Statistiken loggen
    logger.info(f"Seitenprüfung abgeschlossen:")
    logger.info(f"  - ri=0 (HIN): {side_stats['ri_0_right']} auf rechter Seite, {side_stats['ri_0_wrong']} auf falscher Seite")
    logger.info(f"  - ri=1 (RÜCK): {side_stats['ri_1_right']} auf rechter Seite, {side_stats['ri_1_wrong']} auf falscher Seite")
    logger.info(f"  - MultiLineString vollständig: {side_stats['multiline_full']}")
    logger.info(f"  - MultiLineString teilweise: {side_stats['multiline_partial']}")
    logger.info(f"  - MultiLineString übersprungen: {side_stats['multiline_skipped']}")
    logger.info(f"  - Gesamt zur Konvertierung: {len(schutzstreifen_to_convert)}")
    
    if len(schutzstreifen_to_convert) == 0:
        logger.info("Keine Schutzstreifen mit Bushaltestellen auf der richtigen Seite gefunden")
        return result_gdf
    
    # 4. Konvertiere die identifizierten Schutzstreifen
    #    Bei MultiLineString mit partieller Konvertierung: Teile aufsplitten
    logger.info(f"Konvertiere {len(schutzstreifen_to_convert)} Schutzstreifen an Bushaltestellen...")
    
    rows_to_add = []  # Neue Rows für aufgeteilte MultiLineStrings
    indices_to_remove = []  # Indizes die entfernt werden müssen
    converted_count = 0
    split_count = 0
    
    for idx, parts_to_convert in schutzstreifen_to_convert:
        geometry = result_gdf.loc[idx, 'geometry']
        sfid = result_gdf.loc[idx, 'sfid'] if 'sfid' in result_gdf.columns else idx
        ri = result_gdf.loc[idx, 'ri'] if 'ri' in result_gdf.columns else '?'
        
        if isinstance(geometry, MultiLineString):
            total_parts = len(geometry.geoms)
            
            # Fall 1: Alle Teile konvertieren - einfach Führungsform ändern
            if len(parts_to_convert) == total_parts:
                old_fuehr = result_gdf.loc[idx, 'fuehr']
                result_gdf.loc[idx, 'fuehr'] = 'Radfahrstreifen (OSM:Schutzstreifen an Haltestelle)'
                converted_count += 1
                logger.debug(f"Konvertiert (vollständig): sfid={sfid} (ri={ri}), {total_parts} Teile")
            
            # Fall 2: Nur einige Teile konvertieren - aufsplitten
            else:
                logger.info(f"Splitte MultiLineString: sfid={sfid} (ri={ri}) in {total_parts} Teile")
                
                # Originales Feature wird entfernt
                indices_to_remove.append(idx)
                
                # Erstelle neue Features für jeden Teil
                for i, part_geom in enumerate(geometry.geoms):
                    # Kopiere alle Attribute vom Original
                    new_row = result_gdf.loc[idx].copy()
                    new_row['geometry'] = part_geom
                    
                    # Setze sfid für den Teil (mit Suffix)
                    new_row['sfid'] = f"{sfid}_part{i+1}"
                    
                    # Konvertiere nur wenn dieser Teil eine Haltestelle hat
                    if i in parts_to_convert:
                        new_row['fuehr'] = 'Radfahrstreifen (OSM:Schutzstreifen an Haltestelle)'
                        converted_count += 1
                        logger.debug(f"  Teil {i+1}/{total_parts}: Konvertiert (sfid={new_row['sfid']}, Länge: {part_geom.length:.1f}m)")
                    else:
                        # Bleibt Schutzstreifen
                        logger.debug(f"  Teil {i+1}/{total_parts}: Bleibt Schutzstreifen (sfid={new_row['sfid']}, Länge: {part_geom.length:.1f}m)")
                    
                    rows_to_add.append(new_row)
                
                split_count += 1
        
        else:
            # LineString: Einfach konvertieren
            old_fuehr = result_gdf.loc[idx, 'fuehr']
            result_gdf.loc[idx, 'fuehr'] = 'Radfahrstreifen (OSM:Schutzstreifen an Haltestelle)'
            converted_count += 1
            logger.debug(f"Konvertiert: sfid={sfid} (ri={ri}), {old_fuehr} → Radfahrstreifen")
    
    # Entferne Original-Features die gesplittet wurden
    if len(indices_to_remove) > 0:
        logger.info(f"Entferne {len(indices_to_remove)} Original-MultiLineStrings (wurden gesplittet)")
        result_gdf = result_gdf.drop(indices_to_remove)
    
    # Füge neue Features hinzu (aufgeteilte MultiLineStrings)
    if len(rows_to_add) > 0:
        logger.info(f"Füge {len(rows_to_add)} neue Teil-Features hinzu (aus gesplitteten MultiLineStrings)")
        new_features_gdf = gpd.GeoDataFrame(rows_to_add, crs=result_gdf.crs)
        result_gdf = pd.concat([result_gdf, new_features_gdf], ignore_index=True)
    
    logger.info(f"✅ {converted_count} Schutzstreifen-Teile an Bushaltestellen erfolgreich konvertiert")
    if split_count > 0:
        logger.info(f"   ({split_count} MultiLineStrings wurden in Teile aufgeteilt)")
    
    return result_gdf

def convert_schutzstreifen_at_bus_stops(all_ways_gdf, bus_stops_path, buffer_distance=20, tolerance=1.0):
    """
    Konvertiere Schutzstreifen an Bushaltestellen basierend auf einem Dateipfad.
    
    Args:
        all_ways_gdf: GeoDataFrame mit allen Wegen
        bus_stops_path: Pfad zu Bus-Haltestellen-Datei
        buffer_distance: Pufferabstand für Haltestellen in Metern
        tolerance: Toleranz für Angrenzungscheck in Metern
        
    Returns:
        GeoDataFrame: Aktualisierte Wege-Daten
    """
    bus_stops_gdf = load_bus_stops(bus_stops_path, return_gdf=True)
    return convert_schutzstreifen_at_bus_stops_with_gdf(
        all_ways_gdf, bus_stops_gdf, buffer_distance, tolerance
    )
