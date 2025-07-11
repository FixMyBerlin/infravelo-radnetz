#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
enrich_streetnet_with_osm.py
--------------------------------------------------------------------
Überträgt OSM-Attribute auf ein topologisches Richtungs-Straßennetz
– MultiLineStrings werden korrekt behandelt
– feste Feldnamen:
      element_nr         = Edge-ID
      beginnt_bei_vp     = From-Node
      endet_bei_vp       = To-Node
      verkehrsrichtung   = R / G / B
--------------------------------------------------------------------
"""
import argparse, sys
from pathlib import Path

import numpy as np
import geopandas as gpd
from shapely.geometry import LineString, MultiLineString, Point, MultiPoint
from shapely.ops import split as shp_split, linemerge
from helpers.progressbar import print_progressbar
from helpers.globals import DEFAULT_CRS


# -------------------------------------------------------------- Konstanten --
BUFFER_DEFAULT = 20.0     # Standard-Puffergröße in Metern für Matching

# Feldnamen für das Netz
FLD_EDGE = "element_nr"           # Kanten-ID
FLD_FROM = "beginnt_bei_vp"       # Startknoten-ID
FLD_TO   = "endet_bei_vp"         # Endknoten-ID
FLD_DIR  = "verkehrsrichtung"     # Werte: R / G / B (Richtung)


# --------------------------------------------------------- Hilfsfunktionen --
def lines_from_geom(g):
    """
    Gibt alle Linien einer Geometrie als Liste von LineStrings zurück.
    Falls MultiLineString, werden alle Teile einzeln zurückgegeben.
    Falls LineString, wird eine Liste mit diesem einen Element zurückgegeben.
    """
    if isinstance(g, LineString):
        return [g]
    if isinstance(g, MultiLineString):
        return list(g.geoms)
    raise TypeError(f"Geometry {g.geom_type} nicht unterstützt")


def reverse_geom(g):
    """
    Kehrt die Richtung einer Geometrie um.
    """
    if isinstance(g, LineString):
        return LineString(reversed(g.coords))
    if isinstance(g, MultiLineString):
        return MultiLineString([reverse_geom(line) for line in g.geoms])
    raise TypeError(f"Geometry {g.geom_type} nicht unterstützt")


def direction_from_verkehrsrichtung(verkehrsrichtung):
    """
    Ermittelt die Richtung aus dem Verkehrsrichtungs-Attribut.
    R = Richtung der Geometrie, G = Gegenrichtung, B = Beide Richtungen
    """
    if verkehrsrichtung == 'R':
        return 'forward'
    elif verkehrsrichtung == 'G':
        return 'backward'
    elif verkehrsrichtung == 'B':
        return 'both'
    else:
        return 'unknown'


def build_spatial_index(gdf):
    """
    Erstellt einen räumlichen Index für ein GeoDataFrame.
    """
    return gdf.sindex


def find_matching_osm_features(network_geom, osm_gdf, osm_sindex, buffer_distance):
    """
    Findet OSM-Features, die mit einer Netzwerk-Geometrie übereinstimmen.
    """
    # Puffer um Netzwerk-Geometrie
    buffered_geom = network_geom.buffer(buffer_distance)
    
    # Räumliche Abfrage über Index
    possible_matches_idx = list(osm_sindex.intersection(buffered_geom.bounds))
    
    if not possible_matches_idx:
        return gpd.GeoDataFrame()
    
    # Prüfe tatsächliche Intersection
    possible_matches = osm_gdf.iloc[possible_matches_idx]
    intersecting_features = possible_matches[possible_matches.intersects(buffered_geom)]
    
    return intersecting_features


def transfer_osm_attributes(network_row, osm_matches):
    """
    Überträgt OSM-Attribute auf eine Netzwerk-Kante.
    """
    if osm_matches.empty:
        return network_row
    
    # Wähle das beste Match (das mit der größten Überschneidung)
    best_match = None
    best_intersection_length = 0
    
    network_geom = network_row.geometry
    
    for _, osm_row in osm_matches.iterrows():
        osm_geom = osm_row.geometry
        intersection = network_geom.intersection(osm_geom)
        
        if intersection.is_empty:
            continue
        
        # Berechne Überschneidungslänge
        if hasattr(intersection, 'length'):
            intersection_length = intersection.length
        else:
            intersection_length = 0
        
        if intersection_length > best_intersection_length:
            best_intersection_length = intersection_length
            best_match = osm_row
    
    # Übertrage Attribute vom besten Match
    if best_match is not None:
        enriched_row = network_row.copy()
        
        # Übertrage relevante OSM-Attribute
        osm_attributes = ['highway', 'name', 'maxspeed', 'lanes', 'surface', 'cycleway', 'cycleway:left', 'cycleway:right']
        
        for attr in osm_attributes:
            if attr in best_match.index:
                enriched_row[f'osm_{attr}'] = best_match[attr]
        
        return enriched_row
    
    return network_row


def process_network_edges(network_gdf, osm_gdf, buffer_distance=BUFFER_DEFAULT):
    """
    Verarbeitet alle Kanten des Netzwerks und reichert sie mit OSM-Attributen an.
    """
    print(f"Verarbeite {len(network_gdf)} Netzwerk-Kanten...")
    
    # Räumlicher Index für OSM-Daten
    osm_sindex = build_spatial_index(osm_gdf)
    
    enriched_rows = []
    
    for idx, (_, network_row) in enumerate(network_gdf.iterrows()):
        # Fortschrittsanzeige
        if idx % 100 == 0:
            print_progressbar(idx + 1, len(network_gdf), prefix='Anreicherung: ', length=50)
        
        # Finde passende OSM-Features
        osm_matches = find_matching_osm_features(
            network_row.geometry, 
            osm_gdf, 
            osm_sindex, 
            buffer_distance
        )
        
        # Übertrage Attribute
        enriched_row = transfer_osm_attributes(network_row, osm_matches)
        enriched_rows.append(enriched_row)
    
    # Abschluss der Fortschrittsanzeige
    print_progressbar(len(network_gdf), len(network_gdf), prefix='Anreicherung: ', length=50)
    
    # Erstelle angereichertes GeoDataFrame
    enriched_gdf = gpd.GeoDataFrame(enriched_rows, crs=network_gdf.crs)
    
    return enriched_gdf


def enrich_network_with_osm(network_path, osm_path, output_path, buffer_distance=BUFFER_DEFAULT):
    """
    Hauptfunktion zur Anreicherung des Straßennetzes mit OSM-Daten.
    """
    print(f"Lade Straßennetz aus: {network_path}")
    network_gdf = gpd.read_file(network_path)
    print(f"Geladen: {len(network_gdf)} Netzwerk-Kanten")
    
    print(f"Lade OSM-Daten aus: {osm_path}")
    osm_gdf = gpd.read_file(osm_path)
    print(f"Geladen: {len(osm_gdf)} OSM-Features")
    
    # Koordinatensystem prüfen
    target_crs = f"EPSG:{DEFAULT_CRS}"
    if network_gdf.crs != target_crs:
        network_gdf = network_gdf.to_crs(target_crs)
    if osm_gdf.crs != target_crs:
        osm_gdf = osm_gdf.to_crs(target_crs)
    
    # Anreicherung durchführen
    enriched_gdf = process_network_edges(network_gdf, osm_gdf, buffer_distance)
    
    # Ergebnis speichern
    print(f"Speichere angereichertes Netz: {output_path}")
    enriched_gdf.to_file(output_path, driver='FlatGeobuf')
    
    print("Anreicherung abgeschlossen.")
    return enriched_gdf


def main():
    """
    Hauptfunktion für die Kommandozeilenanwendung.
    """
    parser = argparse.ArgumentParser(description='Anreicherung des Straßennetzes mit OSM-Attributen')
    parser.add_argument('network_path', help='Pfad zur Netzwerk-Datei')
    parser.add_argument('osm_path', help='Pfad zur OSM-Datei')
    parser.add_argument('output_path', help='Pfad für die Ausgabe-Datei')
    parser.add_argument('--buffer', type=float, default=BUFFER_DEFAULT, 
                        help=f'Puffergröße in Metern (Standard: {BUFFER_DEFAULT})')
    
    args = parser.parse_args()
    
    # Prüfe Eingabedateien
    if not Path(args.network_path).exists():
        print(f"Fehler: Netzwerk-Datei nicht gefunden: {args.network_path}")
        sys.exit(1)
    
    if not Path(args.osm_path).exists():
        print(f"Fehler: OSM-Datei nicht gefunden: {args.osm_path}")
        sys.exit(1)
    
    # Führe Anreicherung durch
    enrich_network_with_osm(args.network_path, args.osm_path, args.output_path, args.buffer)


if __name__ == "__main__":
    main()
