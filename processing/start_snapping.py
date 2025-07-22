#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
start_snapping.py
--------------------------------------------------------------------
Überträgt TILDA-übersetzte Attribute auf ein topologisches Richtungs-Straßennetz
– MultiLineStrings werden korrekt behandelt
– feste Feldnamen:
      element_nr         = Edge-ID
      beginnt_bei_vp     = From-Node
      endet_bei_vp       = To-Node
      verkehrsrichtung   = R / G / B
– Verwendet übersetzte TILDA-Attribute: fuehr, ofm, protek, pflicht, breite, farbe

INPUT:
- output/vorrangnetz_details_combined_rvn.fgb (Straßennetz)
- output/matched/matched_tilda_ways.fgb (TILDA-übersetzte Daten)

OUTPUT:
- output/snapping_network_enriched.fgb (angereicherte Netzwerkdaten)
(Bei Neukölln-Clipping: snapping_network_enriched_neukoelln.fgb)
"""
import argparse, sys
from pathlib import Path
import os, logging
import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import LineString, MultiLineString, Point
from helpers.progressbar import print_progressbar
from helpers.globals import DEFAULT_CRS
from helpers.traffic_signs import has_traffic_sign
from helpers.clipping import clip_to_neukoelln


# -------------------------------------------------------------- Konstanten --
CONFIG_BUFFER_DEFAULT = 30.0     # Standard-Puffergröße in Metern für Matching
CONFIG_MAX_ANGLE_DIFFERENCE = 50.0 # Maximaler Winkelunterschied für Ausrichtung in Grad

# Neukölln Grenzendatei
INPUT_NEUKOELLN_BOUNDARY_FILE = "Bezirk Neukölln Grenze.fgb"

# Feldnamen für das Netz
RVN_ATTRIBUT_ELEMENT_NR = "element_nr"           # Kanten-ID
RVN_ATTRIBUT_BEGINN_VP = "beginnt_bei_vp"       # Startknoten-ID
RVN_ATTRIBUT_ENDE_VP   = "endet_bei_vp"         # Endknoten-ID
RVN_ATTRIBUT_VERKEHRSRICHTUNG  = "verkehrsrichtung"     # Werte: R / G / B (Richtung)

# Attribute an denen die Kanten getrennt werden bzw. verschmolzen werden
# Diese Attribute müssen in den übersetzten TILDA Daten vorhanden sein
FINAL_DATASET_SEGMENT_MERGE_ATTRIBUTES = ["fuehr", "ofm", "protek", "pflicht", "breite", "farbe", "ri", "verkehrsri", "trennstreifen", "nutz_beschr"]
FINAL_DATASET_SEGMENT_ADDITIONAL_ATTRIBUTES=["data_source", "tilda_id", "tilda_name","tilda_oneway", "tilda_category", "tilda_traffic_sign"]

# Prioritäten für OSM-Weg-Auswahl (höhere Zahl = höhere Priorität)
TILDA_TRAFFIC_SIGN_PRIORITIES = {
    "237": 3,  # Radweg
    "240": 3,  # Gemeinsamer Geh- und Radweg
    "241": 3,  # Getrennter Rad- und Gehweg
}

# Kategorie-Prioritäten
TILDA_CATEGORY_PRIORITIES = {
    "bicycleRoad*": 6,  # Fahrradstraße
    "cycleway*": 6,  # Radweg
    "footAndCycleway*": 5,  # Fußweg mit Radverkehr
    "footwayBicycle*": 4,  # Fußweg mit Radverkehr
    "sharedBusLaneBikeWithBus": 3,  # Gemeinsame Busspur mit Radverkehr
    "sharedBusLaneBusWithBike": 2,
    "pedestrianAreaBicycleYes": 2,  # Fußgängerzone mit Radverkehr
    "sharedMotorVehicleLane": 1,  # Niedrigste Priorität
}


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


# TODO Why is this not used anymore?
def is_left(line: LineString, p: Point) -> bool:
    """Prüft, ob ein Punkt links der Linie liegt (für Richtungsprüfung)."""
    a_x, a_y = line.coords[0]
    b_x, b_y = line.coords[-1]
    return ((b_x - a_x) * (p.y - a_y) - (b_y - a_y) * (p.x - a_x)) > 0

def calculate_line_angle(line: LineString | MultiLineString) -> float:
    """
    Berechnet den Winkel einer Linie (Anfangs- zu Endpunkt) in Grad.
    Der Winkel wird im Bereich [0, 360) zurückgegeben.
    Bei MultiLineStrings wird der Winkel vom ersten Punkt des ersten LineStrings 
    zum letzten Punkt des letzten LineStrings berechnet.
    """
    if isinstance(line, MultiLineString):
        # Bei MultiLineString den ersten Punkt der ersten Linie und 
        # den letzten Punkt der letzten Linie verwenden
        first_line = line.geoms[0]
        last_line = line.geoms[-1]
        
        first_coords = list(first_line.coords)
        last_coords = list(last_line.coords)
        
        if len(first_coords) < 1 or len(last_coords) < 1:
            return 0.0
            
        p1 = first_coords[0]  # Erster Punkt der ersten Linie
        p2 = last_coords[-1]  # Letzter Punkt der letzten Linie
    else:
        # Normaler LineString
        coords = list(line.coords)
        if len(coords) < 2:
            return 0.0
        p1 = coords[0]
        p2 = coords[-1]
    
    angle = np.degrees(np.arctan2(p2[1] - p1[1], p2[0] - p1[0]))
    return angle if angle >= 0 else angle + 360


def angle_difference(angle1: float, angle2: float) -> float:
    """
    Berechnet die kleinste Differenz zwischen zwei Winkeln (in Grad).
    Das Ergebnis liegt immer zwischen 0 und 180.
    """
    diff = abs(angle1 - angle2)
    return min(diff, 360 - diff)


def determine_segment_direction(segment_geom, osm_geom) -> int:
    """
    Bestimmt die Richtung (ri) eines Segments basierend auf der Ausrichtung
    zwischen dem Segment und dem passenden OSM-Weg.
    
    Args:
        segment_geom: Geometrie des Netzwerksegments
        osm_geom: Geometrie des OSM-Wegs
        
    Returns:
        int: 1 für Hinrichtung (gleiche Richtung), 0 für Rückrichtung (entgegengesetzte Richtung)
    """
    segment_angle = calculate_line_angle(segment_geom)
    osm_angle = calculate_line_angle(osm_geom)
    
    angle_diff = angle_difference(segment_angle, osm_angle)
    
    # Wenn der Winkelunterschied kleiner als 90° ist, haben beide die gleiche Richtung (ri=1)
    # Wenn größer als 90°, haben sie entgegengesetzte Richtungen (ri=0)
    return 1 if angle_diff < 90 else 0


def split_network_into_segments(net_gdf, crs, segment_length=1.0):
    """
    Teilt alle Linien im Netz in ca. 1-Meter-Abschnitte auf.
    Gibt ein neues GeoDataFrame mit Segmenten und okstra_id zurück.
    """
    segmente = []
    total = len(net_gdf)
    for idx, (_, row) in enumerate(net_gdf.iterrows(), 1):
        for geom in lines_from_geom(row.geometry):
            n_seg = max(1, int(np.ceil(geom.length / segment_length)))
            breakpoints = np.linspace(0, geom.length, n_seg + 1)
            for i in range(n_seg):
                seg = LineString([
                    geom.interpolate(breakpoints[i]),
                    geom.interpolate(breakpoints[i+1])
                ])
                seg_row = row.copy()
                seg_row["geometry"] = seg
                segmente.append(seg_row)
        print_progressbar(idx, total, prefix="Segmentiere: ")
    return gpd.GeoDataFrame(segmente, crs=crs)


def normalize_merge_attribute(value):
    """
    Normalisiert Attributwerte für das Merging.
    Behandelt None/NaN-Werte und Floating-Point-Präzision.
    """
    if pd.isna(value) or value is None:
        return "NULL"  # Einheitlicher Wert für fehlende Daten
    if isinstance(value, float):
        # Runde Float-Werte auf eine Dezimalstelle für konsistentes Grouping
        return round(value, 1)
    if isinstance(value, bool):
        return str(value)  # Boolean zu String für konsistentes Grouping
    return str(value).strip()  # String normalisieren


def merge_segments(gdf, id_field, osm_fields):
    """
    Verschmilzt benachbarte Segmente mit gleicher okstra_id und identischen OSM-Attributen.
    Behandelt None/NaN-Werte und Floating-Point-Präzision korrekt.
    Zeigt einen Fortschrittsbalken an.
    """
    from shapely.ops import linemerge
    import logging
    
    # Erstelle eine Kopie für die Bearbeitung
    gdf_work = gdf.copy()
    
    # Normalisiere die Merge-Attribute für konsistentes Grouping
    for field in osm_fields:
        if field in gdf_work.columns:
            gdf_work[f"{field}_normalized"] = gdf_work[field].apply(normalize_merge_attribute)
        else:
            logging.warning(f"Merge-Attribut '{field}' nicht in den Daten gefunden!")
            gdf_work[f"{field}_normalized"] = "NULL"
    
    # Verwende die normalisierten Felder für das Grouping
    normalized_fields = [f"{field}_normalized" for field in osm_fields]
    groupby_fields = [id_field] + normalized_fields
    
    # Debug-Output: Zeige die Anzahl einzigartiger Kombinationen
    unique_combinations = gdf_work[groupby_fields].drop_duplicates()
    logging.info(f"Anzahl einzigartiger Attributkombinationen: {len(unique_combinations)}")
    
    gruppen = []
    # Gruppiere die Segmente nach okstra_id und den normalisierten OSM-Attributen
    grouped = list(gdf_work.groupby(groupby_fields))
    total = len(grouped)
    
    logging.info(f"Anzahl Gruppen zum Verschmelzen: {total}")
    
    for idx, (group_key, gruppe) in enumerate(grouped, 1):
        # Extrahiere die Geometrien der aktuellen Gruppe
        geoms = list(gruppe.geometry)
        if not geoms:
            continue
        
        # Debug: Zeige Gruppengröße
        if len(geoms) > 1:
            logging.debug(f"Verschmelze {len(geoms)} Segmente in Gruppe {group_key}")
        
        # Verschmelze die Geometrien zu einer Linie (MultiLineStrings werden zusammengeführt)
        merged = linemerge(geoms)
        
        # Übernehme die Attribute der ersten Zeile der Gruppe für das verschmolzene Segment
        # Aber verwende die Original-Werte, nicht die normalisierten
        merged_row = gruppe.iloc[0].copy()
        merged_row["geometry"] = merged
        
        # Entferne die temporären normalisierten Felder
        for field in normalized_fields:
            if field in merged_row.index:
                merged_row = merged_row.drop(field)
        
        gruppen.append(merged_row)
        
        # Zeige Fortschritt für den Nutzer
        print_progressbar(idx, total, prefix="Verschmelze: ")
    
    if not gruppen:
        # Fehlerfall: Es wurden keine Gruppen gefunden
        raise ValueError("No segments to merge. Check input data and grouping fields.")
    
    # Erzeuge ein neues GeoDataFrame aus den verschmolzenen Segmenten
    result_gdf = gpd.GeoDataFrame(gruppen, geometry="geometry", crs=gdf.crs)
    
    logging.info(f"Verschmelzung abgeschlossen: {len(gdf)} → {len(result_gdf)} Segmente")
    
    return result_gdf


def debug_merge_attributes(gdf, id_field, osm_fields, sample_okstra_id=None):
    """
    Debug-Funktion: Analysiert die Attributwerte für das Merging.
    Zeigt potenzielle Probleme bei der Gruppierung auf.
    """
    import logging
    
    # Wähle eine okstra_id zum Debuggen (falls nicht angegeben, nimm die erste)
    if sample_okstra_id is None:
        sample_okstra_id = gdf[id_field].iloc[0]
    
    # Filtere Segmente mit der gewählten okstra_id
    sample_segments = gdf[gdf[id_field] == sample_okstra_id].copy()
    
    logging.info(f"\n=== DEBUG: Attributanalyse für okstra_id = {sample_okstra_id} ===")
    logging.info(f"Anzahl Segmente mit dieser okstra_id: {len(sample_segments)}")
    
    if len(sample_segments) <= 1:
        logging.info("Nur ein Segment - kein Merging möglich.")
        return
    
    # Analysiere jeden Merge-Attribut
    for field in osm_fields:
        if field not in sample_segments.columns:
            logging.warning(f"Feld '{field}' nicht in den Daten!")
            continue
            
        unique_values = sample_segments[field].value_counts(dropna=False)
        logging.info(f"\nAttribut '{field}':")
        logging.info(f"  Einzigartige Werte: {len(unique_values)}")
        
        for value, count in unique_values.items():
            logging.info(f"    {repr(value)}: {count} Segmente")
        
        # Zeige erste paar Werte im Detail
        first_few = sample_segments[field].head(5)
        logging.info(f"  Erste 5 Werte: {list(first_few)}")
        logging.info(f"  Datentypen: {[type(x) for x in first_few]}")
    
    # Zeige die Kombinationen der Merge-Attribute
    if len(osm_fields) > 1:
        combinations = sample_segments[osm_fields].drop_duplicates()
        logging.info(f"\nEinzigartige Attributkombinationen: {len(combinations)}")
        for idx, row in combinations.iterrows():
            logging.info(f"  Kombination {idx}: {dict(row)}")


def calculate_osm_priority(row) -> int:
    """
    Berechnet die Priorität eines OSM-Wegs basierend auf traffic_sign und category.
    Höhere Zahl = höhere Priorität.
    Unterstützt Wildcard-Matching: Kategorien mit '*' am Ende verwenden Präfix-Match.
    """
    priority = 0
    
    # Priorität basierend auf Verkehrszeichen (mit tilda_ Präfix)
    traffic_sign = row.get("tilda_traffic_sign", "")
    if traffic_sign:
        for sign, prio in TILDA_TRAFFIC_SIGN_PRIORITIES.items():
            if has_traffic_sign(traffic_sign, sign):
                priority = max(priority, prio)
    
    # Priorität basierend auf Kategorie (mit tilda_ Präfix)
    category = row.get("tilda_category", "")
    if category:
        category_str = str(category)
        for pattern, prio in TILDA_CATEGORY_PRIORITIES.items():
            # Prüfe ob Pattern mit * endet (Wildcard-Match)
            if pattern.endswith("*"):
                # Entferne das * und prüfe ob Kategorie mit dem Präfix beginnt
                prefix = pattern[:-1]
                if category_str.startswith(prefix):
                    priority = max(priority, prio)
            else:
                # Exakter Match
                if category_str == pattern:
                    priority = max(priority, prio)
    
    return priority


def create_directional_segment_variants_from_matched_tilda_ways(seg_dict: dict, target_candidates, original_candidates=None) -> list[dict]:
    """
    Erstellt für jedes Segment gerichtete Varianten basierend auf den TILDA-Attributen.
    Die Attribute werden basierend auf dem besten gematchten TILDA-Weg gesetzt.
    Führt die Bewertung und Priorisierung der Kandidaten durch.
    
    Sonderfall: Bei verkehrsri=Einrichtungsverkehr und fuehr=Mischverkehr mit motorisiertem Verkehr
    wird nur eine Kante erzeugt, wobei das ri basierend auf der Richtungsausrichtung zwischen
    Segment und OSM-Weg bestimmt wird.
    
    Standardfall: Es werden zwei Kanten erzeugt, eine für die Hin- (ri=1) und eine für die
    Rückrichtung (ri=0). Die Attribute des besten TILDA-Matches werden auf beide
    Varianten angewendet.

    Args:
        seg_dict (dict): Dictionary des ursprünglichen Straßensegments.
        target_candidates: GeoDataFrame mit TILDA-Kandidaten oder None/leere Liste.
        original_candidates: GeoDataFrame mit ursprünglichen TILDA-Kandidaten für DEBUG-Ausgabe.

    Returns:
        list[dict]: Eine Liste mit ein oder zwei Dictionaries, die die gerichteten
                    Segment-Varianten repräsentieren.
    """
    variants = []
    best_osm = None
    
    # Aussehen target_cand an dieser Stelle für zwei Kandidaten::
    # breite data_source  farbe               fuehr nutz_beschr             ofm pflicht  ...                   verkehrsri                 geometry                                       d        angle     angle_diff   priority dist_to_mid
    # 1    6.0     streets  False  Mischverkehr mit motorisiertem Verkehr       keine  Asphalt   False  ...  Zweirichtungsverkehr  LINESTRING (806124.414 5815161.861, 806129.323...  0.449660  277.330268   0.251108        0    0.453697
    # 2    6.0     streets  False  Mischverkehr mit motorisiertem Verkehr       keine  Asphalt   False  ...  Zweirichtungsverkehr  LINESTRING (806084.079 5815472.905, 806085.054...  3.922344  277.388707   0.192669        0    4.417926
    # [2 rows x 50 columns]
    
    # Bewertung und Auswahl des besten Kandidaten
    if target_candidates is not None and len(target_candidates) > 0:
        # Berechne Priorität für alle Kandidaten
        target_candidates = target_candidates.copy()
        target_candidates["priority"] = target_candidates.apply(calculate_osm_priority, axis=1)
        
        # Sortiere nach Priorität und Entfernung (höchste Priorität, geringste Entfernung)
        from shapely.geometry import Point
        g = seg_dict["geometry"]
        mid = g.interpolate(0.5, normalized=True)
        target_candidates["dist_to_mid"] = target_candidates.geometry.distance(mid)
        
        # Sortiere nach Priorität (absteigend) und dann nach Entfernung (aufsteigend)
        target_candidates = target_candidates.sort_values(["priority", "dist_to_mid"], ascending=[False, True])
        
        # Wähle den besten Kandidaten
        best_osm = target_candidates.iloc[0].to_dict()
        
        # DEBUG: Wenn es mehr als einen ursprünglichen Kandidaten gibt, logge das Objekt
        if original_candidates is not None and len(original_candidates) > 1:
            candidate_ids = original_candidates["tilda_id"].tolist() if "tilda_id" in original_candidates.columns else original_candidates.index.tolist()
            # Prüfe, ob mindestens eine tilda_id "cycleway" enthält
            if any("cycleway" in str(tid) for tid in candidate_ids):
                candidate_links = [f"https://osm.org/{tid}" for tid in candidate_ids]
                import logging
                logging.info(f"Seg:{seg_dict.get('element_nr', 'unknown')}: {len(original_candidates)} Kandidaten, tilda_id: {candidate_ids}/Links: {candidate_links}")
    
    # Erstelle Varianten basierend auf verkehrsri und fuehr
    if best_osm and best_osm.get('verkehrsri') == 'Einrichtungsverkehr' and best_osm.get('fuehr') == 'Mischverkehr mit motorisiertem Verkehr':
        # Sonderfall: Einrichtungsverkehr mit Mischverkehr - nur eine Kante erzeugen
        # ri wird basierend auf der Richtungsausrichtung zwischen Segment und OSM-Weg bestimmt
        variant = seg_dict.copy()
        variant["ri"] = determine_segment_direction(seg_dict["geometry"], best_osm["geometry"])
        
        # Übertrage alle relevanten Attribute vom besten OSM-Match
        for attr in FINAL_DATASET_SEGMENT_MERGE_ATTRIBUTES:
            # Das Attribut `ri` wurde bereits explizit gesetzt
            if attr == 'ri':
                continue
            if attr in best_osm:
                variant[attr] = best_osm.get(attr)

        # Zusätzliche OSM-Attribute für Debugging/Referenz
        for attr in FINAL_DATASET_SEGMENT_ADDITIONAL_ATTRIBUTES:
            variant[attr] = best_osm.get(attr)
            
        variants.append(variant)
    else:
        # Standardfall: Erstelle zwei Varianten, eine für jede Richtung
        for ri_value in [1, 0]:  # 1 = Hinrichtung, 0 = Rückrichtung
            # Erstelle eine Kopie des ursprünglichen Segments für die Gegenrichtung
            # TODO das muss am Ende passieren, abhängig davon, ob es eine Einbahnstraße ohne Radverkehrs frei oder nicht
            variant = seg_dict.copy()
            variant["ri"] = ri_value

            if best_osm:
                # Übertrage alle relevanten Attribute vom besten OSM-Match
                for attr in FINAL_DATASET_SEGMENT_MERGE_ATTRIBUTES:
                    # Das Attribut `ri` wird explizit durch die Schleife gesetzt
                    if attr == 'ri':
                        continue
                    if attr in best_osm:
                        variant[attr] = best_osm.get(attr)

                # Zusätzliche OSM-Attribute für Debugging/Referenz
                for attr in FINAL_DATASET_SEGMENT_ADDITIONAL_ATTRIBUTES:
                    variant[attr] = best_osm.get(attr)
            else:
                # Keine OSM-Daten: Standardwerte setzen
                for attr in FINAL_DATASET_SEGMENT_MERGE_ATTRIBUTES:
                    # Das Attribut `ri` wird explizit durch die Schleife gesetzt
                    if attr == 'ri':
                        continue
                    if attr not in variant: # Behalte existierende Spalten wie 'geometry' etc.
                        variant[attr] = None
            
            variants.append(variant)

    return variants


# ------------------------------------------------------------- Hauptablauf --
def process(net_path, osm_path, out_path, crs, buf, clip_neukoelln=False, data_dir="./data"):
    """
    Hauptfunktion: Segmentiert das Netz, führt das Snapping durch und verschmilzt die Segmente wieder.
    net_path: Pfad zum Netz (mit Layer)
    osm_path: Pfad zu TILDA-übersetzten Daten (mit Layer)
    out_path: Ausgabepfad (mit Layer)
    crs: Ziel-Koordinatensystem (EPSG)
    buf: Puffergröße für Matching
    clip_neukoelln: Ob auf Neukölln zugeschnitten werden soll
    data_dir: Verzeichnis mit den Eingabedateien
    """
    # ---------- Daten laden -------------------------------------------------
    # Logging konfigurieren mit detaillierteren Informationen
    logging.basicConfig(
        level=logging.INFO, 
        format='%(asctime)s - %(levelname)s: %(message)s',
        datefmt='%H:%M:%S'
    )
    
    def read(path):
        f, *layer = path.split(":")
        return gpd.read_file(f, layer=layer[0] if layer else None)

    logging.info("Lade Netzwerk- und TILDA-übersetzte Daten ...")
    net = read(net_path).to_crs(crs)
    osm = read(osm_path).to_crs(crs)
    
    logging.info(f"Netzwerk: {len(net)} Features geladen")
    logging.info(f"TILDA-übersetzte Daten: {len(osm)} Features geladen")
    
    # Optional: Auf Neukölln zuschneiden
    if clip_neukoelln:
        logging.info("Schneide Netzwerk auf Neukölln zu")
        net = clip_to_neukoelln(net, data_dir, crs)
        logging.info("Schneide TILDA-übersetzte Daten auf Neukölln zu")
        osm = clip_to_neukoelln(osm, data_dir, crs)

    # Prüfen, ob alle Pflichtfelder im Netz vorhanden sind
    for fld in (RVN_ATTRIBUT_ELEMENT_NR, RVN_ATTRIBUT_BEGINN_VP, RVN_ATTRIBUT_ENDE_VP, RVN_ATTRIBUT_VERKEHRSRICHTUNG, "okstra_id"):
        if fld not in net.columns:
            sys.exit(f"Pflichtfeld “{fld}” fehlt im Netz!")

    # ---------- Netz segmentieren und speichern -----------------------------
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    
    # Stelle sicher, dass das segmentierte Detailnetz und das Ausgabeverzeichnis existiert
    filename_suffix = "_neukoelln" if clip_neukoelln else ""
    seg_path = f"./output/qa-snapping/rvn-segmented{filename_suffix}.fgb"
    os.makedirs(os.path.dirname(seg_path), exist_ok=True)
    
    if os.path.exists(seg_path):
        logging.info(f"Lade bereits segmentiertes Netz aus {seg_path} ...")
        net_segmented = gpd.read_file(seg_path)
    else:
        logging.info("Segmentiere Netz in 1-Meter-Abschnitte ...")
        net_segmented = split_network_into_segments(net, crs, segment_length=1.0)
        net_segmented.to_file(seg_path, driver="FlatGeobuf")
        logging.info(f"✔  Segmentiertes Netz gespeichert als {seg_path}")

    # ---------- Snapping/Attributübernahme auf Segmente ---------------------
    seg_attr_path = f"./output/qa-snapping/rvn-segmented-attributed-osm{filename_suffix}.fgb"
    os.makedirs(os.path.dirname(seg_attr_path), exist_ok=True)
    
    if os.path.exists(seg_attr_path):
        logging.info(f"Lade bereits attributierte Segmente aus {seg_attr_path} ...")
        net_segmented = gpd.read_file(seg_attr_path)
    else:
        logging.info("Führe Snapping und TILDA-Attributübernahme durch ...")
        # Erzeuge einen räumlichen Index für die TILDA-Daten, um schnelle räumliche Abfragen zu ermöglichen
        osm_sidx = osm.sindex  # Räumlicher Index für TILDA-Daten

        # Verarbeite alle Segmente (nicht nur 10% für Tests)
        total = len(net_segmented)
        snapped_records = []
        # Starte die TILDA-Attributübernahme für jedes Segment
        # --------------------------------------------------
        # Für jedes Segment:
        # 1. Suche TILDA-Kandidaten im räumlichen Puffer
        # 2. Filtere nach Entfernung und Ausrichtung
        # 3. Berechne Priorität und wähle den besten TILDA-Weg
        # 4. Übertrage relevante TILDA-Attribute auf das Segment
        # 5. Erzeuge ggf. Varianten für beide Richtungen
        # 6. Fortschrittsanzeige für den Nutzer

        # Iteriere über alle Detailnetz Segmente des Netzwerks und führe das Snapping sowie die Attributübernahme durch
        # cand => Mögliche TILDA-Kandidaten
        # seg => Detailnetz Kantensegment
        # idx => Segment-Index für Fortschrittsanzeige
        for idx, seg in enumerate(net_segmented.itertuples(), 1):
            g = seg.geometry
            
            # Kandidaten im Buffer suchen (räumliche Suche)
            cand_idx = list(osm_sidx.intersection(g.buffer(buf, cap_style='flat').bounds))
            if not cand_idx:
                # Keine TILDA-Kandidaten gefunden - Standardvarianten erzeugen
                seg_dict = seg._asdict()
                variants = create_directional_segment_variants_from_matched_tilda_ways(seg_dict, None)
                snapped_records.extend(variants)
                # TODO logging.info(f"Keine TILDA-Kandidaten im Puffer für Segment {seg.element_nr} gefunden.")

                # Fortschrittsanzeige aktualisieren
                print_progressbar(idx, total, prefix="Snapping: ")
                continue
                
            # Kopiere die TILDA-Kandidaten, die im räumlichen Buffer gefunden wurden, für weitere Verarbeitung
            # TODO Sollte die hier erstellt werden, oder erst später?
            cand = osm.iloc[cand_idx].copy()

            # DEBUG: Logge die Kandidaten, wenn es mehr als einen gibt
            # if len(cand) > 1:
            #     logging.info(f"{len(cand)} TILDA-Kandidaten im Buffer für Segment {seg.element_nr}: IDs {[c for c in cand['tilda_id'] if 'tilda_id' in cand.columns] if 'tilda_id' in cand.columns else cand.index.tolist()}")
            
            # Filtere Kandidaten nach tatsächlicher Entfernung zum Segment
            cand["d"] = cand.geometry.distance(g)
            cand = cand[cand["d"] <= buf]
            if cand.empty:
                # Keine TILDA-Kandidaten im Buffer - Standardvarianten erzeugen
                seg_dict = seg._asdict()

                # TODO Erstmal keine Kante erzeugen, damit Lücke sichtbar?
                variants = create_directional_segment_variants_from_matched_tilda_ways(seg_dict, None)
                snapped_records.extend(variants)
                # DEBUG Loggen: logging.info(f"Keine TILDA-Kandidaten im Puffer für Segment {seg.element_nr} gefunden.")

                # Fortschrittsanzeige aktualisieren
                print_progressbar(idx, total, prefix="Snapping: ")
                continue

            # Berechne den Winkel des Netzsegments
            seg_angle = calculate_line_angle(g)

            # Berechne Winkel und Winkeldifferenz für alle TILDA-Kandidaten
            # Kopie erstellen um SettingWithCopyWarning zu vermeiden
            cand = cand.copy()
            cand["angle"] = cand.geometry.apply(calculate_line_angle)
            cand["angle_diff"] = cand["angle"].apply(lambda a: angle_difference(a, seg_angle))

            # Filtere Kandidaten mit passender Ausrichtung
            oriented_cand = cand[cand["angle_diff"] <= CONFIG_MAX_ANGLE_DIFFERENCE].copy()

            ### Wähle die besten Kandidaten für die Bewertung aus
            # Wenn es ausgerichtete Kandidaten gibt, diese verwenden, sonst alle
            target_cand = oriented_cand if not oriented_cand.empty else cand.copy()

            ### Erzeuge Segment-Varianten basierend auf TILDA-Daten (mit integrierter Bewertung)
            seg_dict = seg._asdict()
            variants = create_directional_segment_variants_from_matched_tilda_ways(seg_dict, target_cand, cand)
            snapped_records.extend(variants)
            
            # Aktualisiere den Fortschrittsbalken
            print_progressbar(idx, total, prefix="Snapping: ")

        # Erstelle GeoDataFrame aus allen bearbeiteten Segmenten
        net_segmented = gpd.GeoDataFrame(snapped_records, crs=crs)
        net_segmented.to_file(seg_attr_path, driver="FlatGeobuf")
        logging.info(f"✔  Attributierte Segmente gespeichert als {seg_attr_path}")

    # ---------- Segmente verschmelzen ---------------------------------------
    logging.info("Fasse Segmente mit gleicher okstra_id und TILDA-Attributen zusammen ...")
    
    # Debug: Analysiere Merge-Attribute vor dem Verschmelzen
    logging.info(f"Zu verwendende Merge-Attribute: {FINAL_DATASET_SEGMENT_MERGE_ATTRIBUTES}")
    debug_merge_attributes(net_segmented, "okstra_id", FINAL_DATASET_SEGMENT_MERGE_ATTRIBUTES)
    
    out_gdf = merge_segments(net_segmented, "okstra_id", FINAL_DATASET_SEGMENT_MERGE_ATTRIBUTES)

    # ---------- Ergebnis speichern ------------------------------------------
    p, *layer = out_path.split(":")
    layer = layer[0] if layer else "edges_enriched"
    
    # Stelle sicher, dass das Ausgabeverzeichnis existiert
    os.makedirs(os.path.dirname(p), exist_ok=True)
    
    # Füge Suffix für Neukölln-Dateien hinzu
    if clip_neukoelln:
        # Extrahiere Dateiname und Erweiterung
        p_parts = p.split('.')
        if len(p_parts) > 1:
            p_base = '.'.join(p_parts[:-1])
            p_ext = p_parts[-1]
            p = f"{p_base}_neukoelln.{p_ext}"
        else:
            p = f"{p}_neukoelln"
    
    # Lösche existierende Ausgabedatei NACH dem Suffix-Handling, um Write-Access-Fehler zu vermeiden
    Path(p).unlink(missing_ok=True)
    
    out_gdf.to_file(p, layer=layer, driver="FlatGeoBuf")
    print(f"✔  {len(out_gdf)} Kanten → {p}:{layer}")


# ------------------------------------------------------------- CLI Wrapper --
if __name__ == "__main__":
    # Kommandozeilenargumente parsen
    ap = argparse.ArgumentParser(description="Snapping von TILDA-übersetzten Attributen auf Straßennetz")
    ap.add_argument("--net", default="./output/vorrangnetz_details_combined_rvn.fgb", 
                    help="Netz-Layer (Pfad[:Layer]) - Default: ./output/vorrangnetz_details_combined_rvn.fgb")
    ap.add_argument("--osm", default="./output/matched/matched_tilda_ways.fgb", 
                    help="TILDA-übersetzte Daten (Pfad[:Layer]) - Default: ../output/matching/matched_tilda_ways.fgb")
    ap.add_argument("--out", default="./output/snapping_network_enriched.fgb", 
                    help="Ausgabe (Pfad[:Layer]) - Default: ./output/snapping_network_enriched.fgb")
    ap.add_argument("--crs",  type=int,   default=DEFAULT_CRS,
                    help=f"Ziel-EPSG (default {DEFAULT_CRS})")
    ap.add_argument("--buffer", type=float, default=CONFIG_BUFFER_DEFAULT,
                    help=f"Matching-Puffer in m (default {CONFIG_BUFFER_DEFAULT})")
    ap.add_argument("--clip-neukoelln", action="store_true",
                    help="Schneide Daten auf Neukölln zu (optional)")
    ap.add_argument("--data-dir", default="./data", 
                    help="Pfad zum Datenverzeichnis (default: ./data)")
    args = ap.parse_args()

    # Hauptfunktion aufrufen
    process(args.net, args.osm, args.out, args.crs, args.buffer, args.clip_neukoelln, args.data_dir)

