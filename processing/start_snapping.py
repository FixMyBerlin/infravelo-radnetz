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
– Verwendet übersetzte TILDA-Attribute: fuehr, ofm, protek, pflicht, breite, farbe
– Bei fehlenden TILDA-Daten wird fuehr="Keine Radinfrastruktur vorhanden" gesetzt
– Berechnet die Länge jedes Segments in Metern (gerundet, ohne Nachkommastellen)
– Enthält Datenaufbereitung: Spaltenordnung für finale Ausgabe

INPUT:
- output/rvn/vorrangnetz_details_combined_rvn.fgb (Straßennetz)
- output/matched/matched_tilda_ways.fgb (TILDA-übersetzte Daten)

OUTPUT:
- output/snapping_network_enriched.fgb (angereicherte Netzwerkdaten)
(Bei Neukölln-Clipping: snapping_network_enriched_neukoelln.fgb)
"""
import argparse, sys
from pathlib import Path
import os, logging
import time
import tempfile
import pickle
import multiprocessing as mp
import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import linemerge
from helpers.progressbar import print_progressbar
from helpers.globals import DEFAULT_CRS
from helpers.traffic_signs import has_traffic_sign
from helpers.clipping import clip_to_neukoelln

# -------------------------------------------------------------- Konstanten --
CONFIG_BUFFER_DEFAULT = 25     # Standard-Puffergröße in Metern zum Suchraum
CONFIG_MAX_ANGLE_DIFFERENCE = 50 # Maximaler Winkelunterschied für Ausrichtung in Grad
CONFIG_SEGMENT_LENGTH = 2.5    # Segmentlänge in Metern für die Netz-Aufteilung
CONFIG_PROGRESS_UPDATE_INTERVAL = 100  # Fortschritt alle N Segmente aktualisieren
CONFIG_BATCH_SIZE = 250        # Anzahl Segmente pro Batch für bessere Performance
CONFIG_CPU_CORES = mp.cpu_count() - 1  # Anzahl CPU-Kerne für Parallelisierung (alle minus 1)

# Neukölln Grenzendatei
INPUT_NEUKOELLN_BOUNDARY_FILE = "Bezirk Neukölln Grenze.fgb"

# Feldnamen für das Netz
RVN_ATTRIBUT_ELEMENT_NR = "element_nr"           # Kanten-ID
RVN_ATTRIBUT_BEGINN_VP = "beginnt_bei_vp"       # Startknoten-ID
RVN_ATTRIBUT_ENDE_VP   = "endet_bei_vp"         # Endknoten-ID

# Attribute an denen die Kanten getrennt werden bzw. verschmolzen werden
# Diese Attribute müssen in den übersetzten TILDA Daten vorhanden sein
FINAL_DATASET_SEGMENT_MERGE_ATTRIBUTES = ["fuehr", "ofm", "protek", "pflicht", "breite", "farbe", "ri", "verkehrsri", "trennstreifen", "nutz_beschr", "Kommentar"]
FINAL_DATASET_SEGMENT_ADDITIONAL_ATTRIBUTES=["data_source", "tilda_id", "tilda_name","tilda_oneway", "tilda_category", "tilda_traffic_sign", "tilda_mapillary", "tilda_mapillary_traffic_sign", "tilda_mapillary_backward", "tilda_mapillary_forward"]

# Gewünschte Spaltenreihenfolge für Datenaufbereitung (finale Ausgabe)
COLUMN_ORDER = [
    "sfid",                   # 1. Snapping FID
    "element_nr",             # 2. element_nr
    "beginnt_bei_vp",         # 3. beginnt_bei_vp
    "endet_bei_vp",           # 4. endet_bei_vp
    "Länge",                  # 5. Länge (gerundet, ohne Nachkommastellen)
    "ri",                     # 6. ri
    "verkehrsri",             # 7. verkehrsri
    "Bezirksnummer",          # 8. Bezirksnummer
    "strassenname",           # 9. Straßenname
    "fuehr",                  # 10. fuehr
    "pflicht",                # 11. pflicht
    "breite",                 # 12. breite
    "ofm",                    # 13. ofm
    "farbe",                  # 14. farbliche beschichtung
    "protek",                 # 15. protek
    "trennstreifen",          # 16. trennstreifen
    "nutz_beschr",            # 17. nutzungsbeschränkung
    "Kommentar",
    # TILDA-Spalten (geprefixte Spalten)
    "tilda_id",
    "tilda_name",
    "tilda_oneway",
    "tilda_category",
    "tilda_traffic_sign",
    "tilda_mapillary",
    "tilda_mapillary_traffic_sign",
    "tilda_mapillary_backward",
    "tilda_mapillary_forward",
    # Weitere Standardspalten
    "data_source",
    "edge_source",
    "geometry"                # Geometrie immer als letzte Spalte
]

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


def calculate_angles_vectorized(geometries):
    """
    Berechnet Winkel für alle Geometrien vektorisiert.
    Deutlich schneller als einzelne apply()-Aufrufe.
    """
    angles = np.zeros(len(geometries))
    
    for i, geom in enumerate(geometries):
        if isinstance(geom, MultiLineString):
            # Bei MultiLineString den ersten Punkt der ersten Linie und 
            # den letzten Punkt der letzten Linie verwenden
            first_line = geom.geoms[0]
            last_line = geom.geoms[-1]
            
            first_coords = list(first_line.coords)
            last_coords = list(last_line.coords)
            
            if len(first_coords) >= 1 and len(last_coords) >= 1:
                p1 = first_coords[0]  # Erster Punkt der ersten Linie
                p2 = last_coords[-1]  # Letzter Punkt der letzten Linie
            else:
                angles[i] = 0.0
                continue
        elif hasattr(geom, 'coords'):
            coords = list(geom.coords)
            if len(coords) >= 2:
                p1, p2 = coords[0], coords[-1]
            else:
                angles[i] = 0.0
                continue
        else:
            angles[i] = 0.0
            continue
            
        angle = np.degrees(np.arctan2(p2[1] - p1[1], p2[0] - p1[0]))
        angles[i] = angle if angle >= 0 else angle + 360
    
    return angles


def create_base_variant_optimized(seg_dict: dict, ri_value: int) -> dict:
    """
    Erstellt eine Basis-Variante ohne redundante Kopieroperationen.
    Optimiert für bessere Performance.
    """
    # Nur die notwendigen Felder kopieren statt seg_dict.copy()
    variant = {
        'geometry': seg_dict['geometry'],
        'ri': ri_value,
        'element_nr': seg_dict.get('element_nr'),
        'beginnt_bei_vp': seg_dict.get('beginnt_bei_vp'),
        'endet_bei_vp': seg_dict.get('endet_bei_vp'),
        'Länge': int(round(seg_dict['geometry'].length)),
        'Bezirksnummer': seg_dict.get('Bezirksnummer'),
        'strassenname': seg_dict.get('strassenname'),
        'data_source': seg_dict.get('data_source'),
        'edge_source': seg_dict.get('edge_source')
    }
    
    return variant


def process_segments_batch_parallel(batch_data):
    """
    Parallelisierte Version der Batch-Verarbeitung für multiprocessing.
    Jeder Worker-Prozess lädt die OSM-Daten aus einer temporären Pickle-Datei.
    
    Args:
        batch_data: Tuple mit (segments_batch, osm_temp_path, buffer, batch_start_idx)
    
    Returns:
        List[dict]: Liste der verarbeiteten Segment-Varianten
    """
    segments_batch, osm_temp_path, buffer, batch_start_idx = batch_data
    
    # Lade OSM-Daten aus temporärer Pickle-Datei
    with open(osm_temp_path, 'rb') as f:
        osm_gdf = pickle.load(f)
    osm_sidx = osm_gdf.sindex
    
    batch_results = []
    
    for local_idx, seg_dict in enumerate(segments_batch):
        global_idx = batch_start_idx + local_idx + 1
        g = seg_dict['geometry']
        
        # Buffer einmal berechnen und cachen
        buffer_geom = g.buffer(buffer, cap_style='flat')
        cand_idx = list(osm_sidx.intersection(buffer_geom.bounds))
        
        if not cand_idx:
            # Keine TILDA-Kandidaten gefunden
            variants = create_directional_segment_variants_optimized(seg_dict, None)
            batch_results.extend(variants)
            continue
            
        # Kopiere die TILDA-Kandidaten, die im räumlichen Buffer gefunden wurden
        cand = osm_gdf.iloc[cand_idx].copy()

        # Vektorisierte Entfernungsberechnung
        cand["d"] = cand.geometry.distance(g)
        cand = cand[cand["d"] <= buffer]
        
        if cand.empty:
            # Keine TILDA-Kandidaten im Buffer
            variants = create_directional_segment_variants_optimized(seg_dict, None)
            batch_results.extend(variants)
            continue

        # Berechne Winkel vektorisiert statt mit apply()
        seg_angle = calculate_line_angle(g)
        cand_angles = calculate_angles_vectorized(cand.geometry)
        cand["angle"] = cand_angles
        
        # Berechne Winkeldifferenzen vektorisiert
        angle_diffs = np.array([angle_difference(a, seg_angle) for a in cand_angles])
        cand["angle_diff"] = angle_diffs

        # Erzeuge Segment-Varianten basierend auf TILDA-Daten (optimiert)
        variants = create_directional_segment_variants_optimized(seg_dict, cand, cand)
        batch_results.extend(variants)
    
    return batch_results


def process_segments_batch(segments_batch, osm_gdf, osm_sidx, buffer, candidates_log=None, batch_start_idx=0):
    """
    Verarbeitet eine Batch von Segmenten gleichzeitig.
    Reduziert Overhead durch Batch-Operationen.
    """
    batch_results = []
    
    for local_idx, seg_dict in enumerate(segments_batch):
        global_idx = batch_start_idx + local_idx + 1
        g = seg_dict['geometry']
        
        # Buffer einmal berechnen und cachen
        buffer_geom = g.buffer(buffer, cap_style='flat')
        cand_idx = list(osm_sidx.intersection(buffer_geom.bounds))
        
        if not cand_idx:
            # Keine TILDA-Kandidaten gefunden
            variants = create_directional_segment_variants_optimized(seg_dict, None)
            batch_results.extend(variants)
            
            if candidates_log:
                candidates_log.write(f"  Segment #{global_idx}: KEINE KANDIDATEN GEFUNDEN\n")
            continue
            
        # Kopiere die TILDA-Kandidaten, die im räumlichen Buffer gefunden wurden
        cand = osm_gdf.iloc[cand_idx].copy()

        # Vektorisierte Entfernungsberechnung
        cand["d"] = cand.geometry.distance(g)
        cand = cand[cand["d"] <= buffer]
        
        if cand.empty:
            # Keine TILDA-Kandidaten im Buffer
            variants = create_directional_segment_variants_optimized(seg_dict, None)
            batch_results.extend(variants)
            
            if candidates_log:
                candidates_log.write(f"  Segment #{global_idx}: KEINE KANDIDATEN IM PUFFER\n")
            continue

        # Berechne Winkel vektorisiert statt mit apply()
        seg_angle = calculate_line_angle(g)
        cand_angles = calculate_angles_vectorized(cand.geometry)
        cand["angle"] = cand_angles
        
        # Berechne Winkeldifferenzen vektorisiert
        angle_diffs = np.array([angle_difference(a, seg_angle) for a in cand_angles])
        cand["angle_diff"] = angle_diffs

        # Kandidaten-Logging (falls aktiviert)
        if candidates_log:
            all_tilda_ids = [c.get('tilda_id', 'unknown') for _, c in cand.iterrows()]
            candidates_log.write(f"  Segment #{global_idx}:\n")
            
            for ri_value in [0, 1]:
                ri_name = "Hinrichtung" if ri_value == 0 else "Rückrichtung"
                best_candidate = find_best_candidate_for_direction(cand, seg_dict, ri_value, seg_angle)
                
                if best_candidate:
                    best_tilda_id = best_candidate.get('tilda_id', 'unknown')
                    distance = best_candidate.get('d', -1)
                    angle_diff = best_candidate.get('angle_diff', -1)
                    dir_compat = best_candidate.get('direction_compatibility', -1)
                    verkehrsri = best_candidate.get('verkehrsri', 'unknown')
                    
                    candidates_log.write(f"    ri={ri_value} ({ri_name}): {best_tilda_id}")
                    candidates_log.write(f" [dist={distance:.1f}m, angle_diff={angle_diff:.1f}°, dir_compat={dir_compat}, verkehrsri={verkehrsri}]")
                    
                    if len(all_tilda_ids) > 1:
                        candidates_log.write(f" verfügbare: {all_tilda_ids}")
                    candidates_log.write("\n")
                else:
                    candidates_log.write(f"    ri={ri_value} ({ri_name}): KEIN BESTER KANDIDAT")
                    if all_tilda_ids:
                        candidates_log.write(f" verfügbare: {all_tilda_ids}")
                    candidates_log.write("\n")

        # Erzeuge Segment-Varianten basierend auf TILDA-Daten (optimiert)
        variants = create_directional_segment_variants_optimized(seg_dict, cand, cand)
        batch_results.extend(variants)
        
        # Logge ausgewählte Kandidaten
        if candidates_log:
            candidates_log.write(f"    AUSGEWÄHLT für Segment #{global_idx}:\n")
            for variant in variants:
                ri = variant.get('ri', 'unknown')
                tilda_id = variant.get('tilda_id', 'None')
                ri_name = "Hinrichtung" if ri == 0 else "Rückrichtung" if ri == 1 else f"ri={ri}"
                candidates_log.write(f"      ri={ri} ({ri_name}): {tilda_id}\n")
    
    return batch_results


# --------------------------------------------------------- Hilfsfunktionen --
def calculate_segment_length(geometry):
    """
    Berechnet die Länge eines Segments in Metern.
    """
    return geometry.length


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
        int: 0 für Hinrichtung (gleiche Richtung), 1 für Rückrichtung (entgegengesetzte Richtung)
    """
    segment_angle = calculate_line_angle(segment_geom)
    osm_angle = calculate_line_angle(osm_geom)
    
    angle_diff = angle_difference(segment_angle, osm_angle)
    
    # Wenn der Winkelunterschied kleiner als 90° ist, haben beide die gleiche Richtung (ri=0)
    # Wenn größer als 90°, haben sie entgegengesetzte Richtungen (ri=1)
    return 0 if angle_diff < 90 else 1


def split_network_into_segments(net_gdf, crs, segment_length=CONFIG_SEGMENT_LENGTH):
    """
    Teilt alle Linien im Netz in Segmente auf.
    Gibt ein neues GeoDataFrame mit Segmenten zurück.
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


def normalize_merge_attributes_batch(df, fields):
    """
    Normalisiert alle Merge-Attribute in einem Durchgang (vektorisiert).
    Behandelt None/NaN-Werte und Floating-Point-Präzision korrekt.
    Deutlich schneller als einzelne apply()-Operationen.
    """
    normalized = {}
    
    for field in fields:
        if field in df.columns:
            series = df[field].copy()
            result = pd.Series(index=series.index, dtype=object)
            
            # None/NaN behandeln
            null_mask = series.isna() | series.isnull()
            result.loc[null_mask] = "NULL"
            
            # Bearbeite nur nicht-null Werte
            non_null_series = series[~null_mask]
            
            if len(non_null_series) > 0:
                # Float-Werte identifizieren und behandeln
                float_mask = non_null_series.apply(lambda x: isinstance(x, (int, float)) and not isinstance(x, bool))
                
                if float_mask.any():
                    float_indices = non_null_series[float_mask].index
                    float_values = non_null_series[float_mask].apply(lambda x: str(round(float(x), 1)))
                    result.loc[float_indices] = float_values
                
                # Boolean zu String
                bool_mask = non_null_series.apply(lambda x: isinstance(x, bool))
                if bool_mask.any():
                    bool_indices = non_null_series[bool_mask].index
                    bool_values = non_null_series[bool_mask].astype(str)
                    result.loc[bool_indices] = bool_values
                
                # String normalisieren (alles was weder float noch bool ist)
                string_mask = ~float_mask & ~bool_mask
                if string_mask.any():
                    string_indices = non_null_series[string_mask].index
                    string_values = non_null_series[string_mask].astype(str).str.strip()
                    result.loc[string_indices] = string_values
            
            normalized[f"{field}_normalized"] = result
        else:
            logging.warning(f"Merge-Attribut '{field}' nicht in den Daten gefunden!")
            normalized[f"{field}_normalized"] = pd.Series(["NULL"] * len(df), index=df.index)
    
    return pd.DataFrame(normalized, index=df.index)


def normalize_merge_attribute(value):
    """
    Normalisiert einzelne Attributwerte für das Merging.
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
    Verschmilzt benachbarte Segmente mit gleicher element_nr und identischen OSM-Attributen.
    Behandelt None/NaN-Werte und Floating-Point-Präzision korrekt.
    Zeigt einen Fortschrittsbalken an.
    """
    
    # Erstelle eine Kopie für die Bearbeitung
    gdf_work = gdf.copy()
    
    # Normalisiere alle Merge-Attribute in einem Durchgang (vektorisiert - deutlich schneller)
    normalized_df = normalize_merge_attributes_batch(gdf_work, osm_fields)
    gdf_work = pd.concat([gdf_work, normalized_df], axis=1)
    
    # Verwende die normalisierten Felder für das Grouping
    normalized_fields = [f"{field}_normalized" for field in osm_fields]
    groupby_fields = [id_field] + normalized_fields
    
    # Debug-Output: Zeige die Anzahl einzigartiger Kombinationen
    unique_combinations = gdf_work[groupby_fields].drop_duplicates()
    logging.info(f"Anzahl einzigartiger Attributkombinationen: {len(unique_combinations)}")
    
    gruppen = []
    # Gruppiere die Segmente nach element_nr und den normalisierten OSM-Attributen (ohne Sortierung für bessere Performance)
    grouped = list(gdf_work.groupby(groupby_fields, sort=False))
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
        
        # Berechne die Länge für das verschmolzene Segment (gerundet, ohne Nachkommastellen)
        merged_row["Länge"] = int(round(calculate_segment_length(merged)))
        
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
    
    # Prüfe und logge die Längenberechnung
    if 'Länge' in result_gdf.columns:
        total_length = result_gdf['Länge'].sum()
        avg_length = result_gdf['Länge'].mean()
        logging.info(f"Längenstatistiken nach Verschmelzung: Gesamtlänge={total_length:.0f}m, Durchschnitt={avg_length:.0f}m")
    
    return result_gdf


def debug_merge_attributes(gdf, id_field, osm_fields, sample_element_nr=None):
    """
    Debug-Funktion: Analysiert die Attributwerte für das Merging.
    Zeigt potenzielle Probleme bei der Gruppierung auf.
    """
    
    # Wähle eine element_nr zum Debuggen (falls nicht angegeben, nimm die erste)
    if sample_element_nr is None:
        sample_element_nr = gdf[id_field].iloc[0]
    
    # Filtere Segmente mit der gewählten element_nr
    sample_segments = gdf[gdf[id_field] == sample_element_nr].copy()
    
    logging.info(f"\n=== DEBUG: Attributanalyse für element_nr = {sample_element_nr} ===")
    logging.info(f"Anzahl Segmente mit dieser element_nr: {len(sample_segments)}")
    
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


def find_best_candidate_for_direction(candidates, seg_dict, ri_value, segment_angle=None):
    """
    Findet den besten TILDA-Kandidaten für eine spezifische Richtung.
    Berücksichtigt verkehrsri und Richtungsausrichtung.
    
    Args:
        candidates: GeoDataFrame mit TILDA-Kandidaten
        seg_dict: Dictionary des Segments
        ri_value: Richtung (0=Hinrichtung, 1=Rückrichtung)
        
    Returns:
        dict oder None: Bester Kandidat für die gegebene Richtung
    """
    
    if candidates is None or len(candidates) == 0:
        logging.debug(f"Keine Kandidaten für ri={ri_value}")
        return None
    
    candidates = candidates.copy()
    segment_geom = seg_dict["geometry"]
    element_nr = seg_dict.get("element_nr", "unknown")
    
    logging.debug(f"Bewerte {len(candidates)} Kandidaten für ri={ri_value}, element_nr={element_nr}")
    
    # Berechne Priorität für alle Kandidaten
    candidates["priority"] = candidates.apply(calculate_osm_priority, axis=1)
    
    # Berechne Entfernung zum Segmentmittelpunkt
    mid = segment_geom.interpolate(0.5, normalized=True)
    candidates["dist_to_mid"] = candidates.geometry.distance(mid)
    
    # Berechne Richtungskompatibilität für jeden Kandidaten
    candidates["direction_compatibility"] = 0
    
    # Logge Segmentwinkel für Debugging - verwende übergebenen Winkel falls vorhanden
    if segment_angle is None:
        segment_angle = calculate_line_angle(segment_geom)
    logging.debug(f"Segment element_nr={element_nr}: Winkel={segment_angle:.1f}°")
    
    for idx, candidate in candidates.iterrows():
        candidate_verkehrsri = candidate.get('verkehrsri', '')
        candidate_tilda_id = candidate.get('tilda_id', f'idx_{idx}')
        # Verwende bereits berechneten Winkel falls vorhanden
        if 'angle' in candidate:
            candidate_angle = candidate['angle']
        else:
            candidate_angle = calculate_line_angle(candidate.geometry)
        
        if candidate_verkehrsri == 'Einrichtungsverkehr':
            # Bei Einrichtungsverkehr: Prüfe Richtungsausrichtung
            segment_direction = determine_segment_direction(segment_geom, candidate.geometry)
            
            logging.debug(f"  Kandidat {candidate_tilda_id}: Einrichtungsverkehr, "
                         f"Winkel={candidate_angle:.1f}°, segment_direction={segment_direction}, "
                         f"ri_value={ri_value}")
            
            if segment_direction == ri_value:
                # Richtung passt perfekt
                candidates.at[idx, "direction_compatibility"] = 10
                logging.debug(f"    → Richtung passt perfekt! direction_compatibility=10")
            else:
                # Richtung passt nicht - niedrigere Priorität
                candidates.at[idx, "direction_compatibility"] = 0
                logging.debug(f"    → Richtung passt NICHT! direction_compatibility=0")
        else:
            # Bei Zweirichtungsverkehr: Kann für beide Richtungen verwendet werden
            candidates.at[idx, "direction_compatibility"] = 1
            logging.debug(f"  Kandidat {candidate_tilda_id}: Zweirichtungsverkehr, "
                         f"Winkel={candidate_angle:.1f}°, direction_compatibility=1")
    
    # Sortiere nach Richtungskompatibilität, Priorität und Entfernung
    candidates = candidates.sort_values(
        ["direction_compatibility", "priority", "dist_to_mid"], 
        ascending=[False, False, True]
    )
    
    # Logge die Sortierreihenfolge
    if len(candidates) > 0:
        best_candidate = candidates.iloc[0]
        logging.debug(f"Bester Kandidat für ri={ri_value}: {best_candidate.get('tilda_id', 'unknown')} "
                     f"(dir_compat={best_candidate.get('direction_compatibility', -1)}, "
                     f"priority={best_candidate.get('priority', -1)}, "
                     f"dist={best_candidate.get('dist_to_mid', -1):.1f}m)")
        
        # Logge auch die anderen Kandidaten zur Nachvollziehbarkeit
        if len(candidates) > 1:
            logging.debug("Andere Kandidaten (in Sortierreihenfolge):")
            for i, (_, cand) in enumerate(candidates.iloc[1:].iterrows(), 1):
                logging.debug(f"  {i+1}. {cand.get('tilda_id', 'unknown')} "
                             f"(dir_compat={cand.get('direction_compatibility', -1)}, "
                             f"priority={cand.get('priority', -1)}, "
                             f"dist={cand.get('dist_to_mid', -1):.1f}m)")
    
    # Wähle den besten Kandidaten
    return candidates.iloc[0].to_dict() if len(candidates) > 0 else None


def create_directional_segment_variants_optimized(seg_dict: dict, target_candidates, original_candidates=None) -> list[dict]:
    """
    Memory-optimierte Version der Varianten-Erstellung.
    Reduziert Memory-Allokationen und redundante Operationen für bessere Performance.
    Verwendet create_base_variant_optimized() für effizientere Variant-Erstellung.
    """
    variants = []
    
    # Berechne Segmentwinkel nur einmal für alle Verwendungen
    segment_angle = calculate_line_angle(seg_dict["geometry"])
    
    # Prüfe auf Einrichtungsverkehr und Dual Carriageway Kandidaten
    einrichtung_candidates = []
    dual_carriageway_candidates = []
    
    if target_candidates is not None and len(target_candidates) > 0:
        einrichtung_candidates = target_candidates[
            target_candidates.get('verkehrsri', '') == 'Einrichtungsverkehr'
        ]
        dual_carriageway_candidates = target_candidates[
            target_candidates.get('tilda_oneway', '') == 'yes_dual_carriageway'
        ]
    
    # Sonderfall: Keine TILDA-Kandidaten gefunden
    if target_candidates is None or len(target_candidates) == 0:
        for ri_value in [0, 1]:
            variant = create_base_variant_optimized(seg_dict, ri_value)
            variant["fuehr"] = 'Keine Radinfrastruktur vorhanden'
            # Setze alle anderen Merge-Attribute auf None
            for attr in FINAL_DATASET_SEGMENT_MERGE_ATTRIBUTES:
                if attr not in ['ri', 'fuehr'] and attr not in variant:
                    variant[attr] = None
            for attr in FINAL_DATASET_SEGMENT_ADDITIONAL_ATTRIBUTES:
                variant[attr] = None
            variants.append(variant)
    
    # Sonderfall: Nur Einrichtungsverkehr-Kandidaten mit Mischverkehr
    elif (len(einrichtung_candidates) > 0 and 
        len(einrichtung_candidates) == len(target_candidates) and
        len(dual_carriageway_candidates) == 0 and
        all(cand.get('fuehr') == 'Mischverkehr mit motorisiertem Verkehr' 
            for _, cand in einrichtung_candidates.iterrows())):
        
        best_osm = find_best_candidate_for_direction(einrichtung_candidates, seg_dict, None, segment_angle)
        if best_osm:
            variant = create_base_variant_optimized(seg_dict, 
                determine_segment_direction(seg_dict["geometry"], best_osm["geometry"]))
            
            # Übertrage Attribute effizienter
            for attr in FINAL_DATASET_SEGMENT_MERGE_ATTRIBUTES:
                if attr != 'ri' and attr in best_osm:
                    variant[attr] = best_osm.get(attr)
            for attr in FINAL_DATASET_SEGMENT_ADDITIONAL_ATTRIBUTES:
                variant[attr] = best_osm.get(attr)
                
            variants.append(variant)
    else:
        # Standardfall: Erstelle zwei Varianten
        candidates_to_use = target_candidates
        
        # Dual Carriageway Behandlung
        if (len(dual_carriageway_candidates) > 0 and 
            len(dual_carriageway_candidates) == len(target_candidates) and
            all(cand.get('verkehrsri') == 'Einrichtungsverkehr' 
                for _, cand in dual_carriageway_candidates.iterrows())):
            candidates_to_use = dual_carriageway_candidates
        
        for ri_value in [0, 1]:
            variant = create_base_variant_optimized(seg_dict, ri_value)
            best_osm = find_best_candidate_for_direction(candidates_to_use, seg_dict, ri_value, segment_angle)

            if best_osm:
                # Übertrage Attribute ohne redundante Schleifen
                for attr in FINAL_DATASET_SEGMENT_MERGE_ATTRIBUTES:
                    if attr != 'ri' and attr in best_osm:
                        variant[attr] = best_osm.get(attr)
                for attr in FINAL_DATASET_SEGMENT_ADDITIONAL_ATTRIBUTES:
                    variant[attr] = best_osm.get(attr)
            else:
                # Setze fehlende Attribute auf None
                for attr in FINAL_DATASET_SEGMENT_MERGE_ATTRIBUTES:
                    if attr not in variant:
                        variant[attr] = None
                for attr in FINAL_DATASET_SEGMENT_ADDITIONAL_ATTRIBUTES:
                    variant[attr] = None

            variants.append(variant)
    
    return variants


def create_directional_segment_variants_from_matched_tilda_ways(seg_dict: dict, target_candidates, original_candidates=None) -> list[dict]:
    """
    Erstellt für jedes Segment gerichtete Varianten basierend auf den TILDA-Attributen.
    Die Attribute werden richtungsabhängig basierend auf den besten gematchten TILDA-Wegen gesetzt.
    Führt die Bewertung und Priorisierung der Kandidaten für jede Richtung durch.
    
    Keine Kandidaten: Wenn keine TILDA-Kandidaten gefunden werden, werden zwei Kanten
    erzeugt mit fuehr="Keine Radinfrastruktur vorhanden" (für geplante Infrastruktur).
    
    Sonderfall: Bei verkehrsri=Einrichtungsverkehr wird nur eine Kante erzeugt,
    wobei das ri basierend auf der Richtungsausrichtung zwischen Segment und OSM-Weg bestimmt wird.
    
    Standardfall: Es werden zwei Kanten erzeugt, eine für die Hin- (ri=0) und eine für die
    Rückrichtung (ri=1). Für jede Richtung wird der passendste TILDA-Weg gewählt.

    Args:
        seg_dict (dict): Dictionary des ursprünglichen Straßensegments.
        target_candidates: GeoDataFrame mit TILDA-Kandidaten oder None/leere Liste.
        original_candidates: GeoDataFrame mit ursprünglichen TILDA-Kandidaten für DEBUG-Ausgabe.

    Returns:
        list[dict]: Eine Liste mit ein oder zwei Dictionaries, die die gerichteten
                    Segment-Varianten repräsentieren.
    """
    variants = []
    
    # Berechne Segmentwinkel einmal für alle Verwendungen
    segment_angle = calculate_line_angle(seg_dict["geometry"])
    
    # DEBUG: Wenn es mehr als einen ursprünglichen Kandidaten gibt, logge das Objekt
    if original_candidates is not None and len(original_candidates) > 1:
        candidate_ids = original_candidates["tilda_id"].tolist() if "tilda_id" in original_candidates.columns else original_candidates.index.tolist()
        # Prüfe, ob mindestens eine tilda_id "cycleway" enthält
        if any("cycleway" in str(tid) for tid in candidate_ids):
            candidate_links = [f"https://osm.org/{tid}" for tid in candidate_ids]
            logging.debug(f"Seg:{seg_dict.get('element_nr', 'unknown')}: {len(original_candidates)} Kandidaten, tilda_id: {candidate_ids}/Links: {candidate_links}")
    
    # Prüfe, ob wir einen eindeutigen Einrichtungsverkehr-Kandidaten haben
    einrichtung_candidates = []
    if target_candidates is not None and len(target_candidates) > 0:
        einrichtung_candidates = target_candidates[
            target_candidates.get('verkehrsri', '') == 'Einrichtungsverkehr'
        ]
    
    # Prüfe auf Dual Carriageway Kandidaten
    dual_carriageway_candidates = []
    if target_candidates is not None and len(target_candidates) > 0:
        dual_carriageway_candidates = target_candidates[
            target_candidates.get('tilda_oneway', '') == 'yes_dual_carriageway'
        ]
    
    # Sonderfall: Keine TILDA-Kandidaten gefunden
    if target_candidates is None or len(target_candidates) == 0:
        # Erstelle zwei Varianten ohne OSM-Daten, aber mit speziellem fuehr-Attribut
        for ri_value in [0, 1]:  # 0 = Hinrichtung, 1 = Rückrichtung
            variant = seg_dict.copy()
            variant["ri"] = ri_value
            
            # Setze alle Merge-Attribute auf None, außer fuehr
            for attr in FINAL_DATASET_SEGMENT_MERGE_ATTRIBUTES:
                if attr == 'ri':  # ri wird explizit durch die Schleife gesetzt
                    continue
                elif attr == 'fuehr':
                    variant[attr] = 'Keine Radinfrastruktur vorhanden'
                elif attr not in variant:  # Behalte existierende Spalten wie 'geometry' etc.
                    variant[attr] = None
            
            # Zusätzliche OSM-Attribute für Debugging/Referenz auf None setzen
            for attr in FINAL_DATASET_SEGMENT_ADDITIONAL_ATTRIBUTES:
                variant[attr] = None
                
            variants.append(variant)
    
    # Sonderfall: Nur Einrichtungsverkehr-Kandidaten mit Mischverkehr (aber NICHT dual carriageway)
    elif (len(einrichtung_candidates) > 0 and 
        len(einrichtung_candidates) == len(target_candidates) and
        len(dual_carriageway_candidates) == 0 and  # KEINE dual carriageway Kandidaten
        all(cand.get('fuehr') == 'Mischverkehr mit motorisiertem Verkehr' 
            for _, cand in einrichtung_candidates.iterrows())):
        
        # Nur eine Kante erzeugen basierend auf dem besten Einrichtungsverkehr-Kandidaten
        best_osm = find_best_candidate_for_direction(einrichtung_candidates, seg_dict, None, segment_angle)
        if best_osm:
            variant = seg_dict.copy()
            variant["ri"] = determine_segment_direction(seg_dict["geometry"], best_osm["geometry"])
            
            # Übertrage alle relevanten Attribute vom besten OSM-Match
            for attr in FINAL_DATASET_SEGMENT_MERGE_ATTRIBUTES:
                if attr == 'ri':  # ri wurde bereits explizit gesetzt
                    continue
                if attr in best_osm:
                    variant[attr] = best_osm.get(attr)

            # Zusätzliche OSM-Attribute für Debugging/Referenz
            for attr in FINAL_DATASET_SEGMENT_ADDITIONAL_ATTRIBUTES:
                variant[attr] = best_osm.get(attr)
                
            variants.append(variant)
    else:
        # Bestimme welche Kandidaten verwendet werden sollen
        candidates_to_use = target_candidates
        
        # Sonderfall: Dual Carriageway mit Einrichtungsverkehr
        if (len(dual_carriageway_candidates) > 0 and 
            len(dual_carriageway_candidates) == len(target_candidates) and
            all(cand.get('verkehrsri') == 'Einrichtungsverkehr' 
                for _, cand in dual_carriageway_candidates.iterrows())):
            
            logging.debug(f"Dual carriageway erkannt für element_nr={seg_dict.get('element_nr', 'unknown')}: "
                         f"{len(dual_carriageway_candidates)} Kandidaten")
            candidates_to_use = dual_carriageway_candidates
        
        # Standardfall/Dual Carriageway: Erstelle zwei Varianten, eine für jede Richtung
        # Bei dual carriageway werden beide Richtungen erstellt, auch wenn OSM-Wege Einrichtungsverkehr sind
        # Dies repräsentiert die Tatsache, dass beide Fahrbahnen physisch vorhanden sind
        for ri_value in [0, 1]:  # 0 = Hinrichtung, 1 = Rückrichtung
            variant = seg_dict.copy()
            variant["ri"] = ri_value

            # Finde den besten Kandidaten für diese spezifische Richtung
            best_osm = find_best_candidate_for_direction(candidates_to_use, seg_dict, ri_value, segment_angle)

            if best_osm:
                # Übertrage alle relevanten Attribute vom besten OSM-Match
                for attr in FINAL_DATASET_SEGMENT_MERGE_ATTRIBUTES:
                    if attr == 'ri':  # ri wird explizit durch die Schleife gesetzt
                        continue
                    if attr in best_osm:
                        variant[attr] = best_osm.get(attr)

                # Zusätzliche OSM-Attribute für Debugging/Referenz
                for attr in FINAL_DATASET_SEGMENT_ADDITIONAL_ATTRIBUTES:
                    variant[attr] = best_osm.get(attr)
            else:
                # Keine OSM-Daten: Standardwerte setzen
                for attr in FINAL_DATASET_SEGMENT_MERGE_ATTRIBUTES:
                    if attr == 'ri':  # ri wird explizit durch die Schleife gesetzt
                        continue
                    if attr not in variant:  # Behalte existierende Spalten wie 'geometry' etc.
                        variant[attr] = None
                
                # Zusätzliche OSM-Attribute für Debugging/Referenz auf None setzen
                for attr in FINAL_DATASET_SEGMENT_ADDITIONAL_ATTRIBUTES:
                    variant[attr] = None

            variants.append(variant)
    
    # Berechne die Länge für alle Varianten einmalig am Ende (gerundet, ohne Nachkommastellen)
    for variant in variants:
        variant["Länge"] = int(round(calculate_segment_length(variant["geometry"])))
    
    return variants


# -------------------------------------------------- Datenaufbereitung --
def reorder_columns_for_output(gdf):
    """
    Ordnet die Spalten gemäß der definierten Reihenfolge für die finale Ausgabe.
    Diese Funktion ist Teil der Datenaufbereitung, nicht der Hauptverarbeitung.
    
    Args:
        gdf: GeoDataFrame mit den angereicherten Kanten
        
    Returns:
        GeoDataFrame mit geordneten Spalten
    """
    # Arbeite mit einer Kopie
    gdf = gdf.copy()
    
    # Bestimme verfügbare Spalten in der gewünschten Reihenfolge (ohne geometry)
    available_columns = []
    for col in COLUMN_ORDER:
        if col in gdf.columns and col != 'geometry':
            available_columns.append(col)
    
    # Füge alle anderen Spalten hinzu, die nicht in COLUMN_ORDER definiert sind (ohne geometry)
    for col in gdf.columns:
        if col not in available_columns and col != 'geometry':
            available_columns.append(col)
    
    # Erstelle neues GeoDataFrame mit geordneten Spalten
    # Behalte die originale geometry-Spalte bei
    ordered_data = {}
    for col in available_columns:
        ordered_data[col] = gdf[col]
    
    # Erstelle GeoDataFrame mit originaler geometry
    result_gdf = gpd.GeoDataFrame(ordered_data, geometry=gdf.geometry, crs=gdf.crs)
    
    logging.info(f"Spalten für Ausgabe geordnet: {len(available_columns) + 1} Spalten (inkl. geometry)")
    logging.debug(f"Spaltenreihenfolge: {available_columns + ['geometry']}")
    
    return result_gdf


# ------------------------------------------------------------- Hauptablauf --
def process(net_path, osm_path, out_path, crs, buffer, clip_neukoelln=False, data_dir="./data", log_candidates=False):
    """
    Hauptfunktion: Segmentiert das Netz, führt das Snapping durch und verschmilzt die Segmente wieder.
    net_path: Pfad zum Netz (mit Layer)
    osm_path: Pfad zu TILDA-übersetzten Daten (mit Layer)
    out_path: Ausgabepfad (mit Layer)
    crs: Ziel-Koordinatensystem (EPSG)
    buffer: Puffergröße für Matching
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
    for fld in (RVN_ATTRIBUT_ELEMENT_NR, RVN_ATTRIBUT_BEGINN_VP, RVN_ATTRIBUT_ENDE_VP):
        if fld not in net.columns:
            sys.exit(f"Pflichtfeld “{fld}” fehlt im Netz!")

    # ---------- Netz segmentieren und speichern -----------------------------
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    
    # Stelle sicher, dass das segmentierte Detailnetz und das Ausgabeverzeichnis existiert
    filename_suffix = "_neukoelln" if clip_neukoelln else ""
    seg_path = f"./output/snapping/rvn-segmented{filename_suffix}.fgb"
    os.makedirs(os.path.dirname(seg_path), exist_ok=True)
    
    if os.path.exists(seg_path):
        logging.info(f"Lade bereits segmentiertes Netz aus {seg_path} ...")
        net_segmented = gpd.read_file(seg_path)
        # Stelle sicher, dass das CRS korrekt ist
        if net_segmented.crs != crs:
            logging.info(f"Transformiere CRS von {net_segmented.crs} zu {crs}")
            net_segmented = net_segmented.to_crs(crs)
    else:
        logging.info("Segmentiere Netz in Segmente ...")
        net_segmented = split_network_into_segments(net, crs, segment_length=CONFIG_SEGMENT_LENGTH)
        net_segmented.to_file(seg_path, driver="FlatGeobuf")
        logging.info(f"✔  Segmentiertes Netz gespeichert als {seg_path}")

    # ---------- Snapping/Attributübernahme auf Segmente ---------------------
    seg_attr_path = f"./output/snapping/rvn-segmented-attributed-osm{filename_suffix}.fgb"
    os.makedirs(os.path.dirname(seg_attr_path), exist_ok=True)
    
    if os.path.exists(seg_attr_path):
        logging.info(f"Lade bereits attributierte Segmente aus {seg_attr_path} ...")
        net_segmented = gpd.read_file(seg_attr_path)
        # Stelle sicher, dass das CRS korrekt ist
        if net_segmented.crs != crs:
            logging.info(f"Transformiere CRS von {net_segmented.crs} zu {crs}")
            net_segmented = net_segmented.to_crs(crs)
    else:
        logging.info("Führe Snapping und TILDA-Attributübernahme durch ...")
        # Erzeuge einen räumlichen Index für die TILDA-Daten, um schnelle räumliche Abfragen zu ermöglichen
        osm_sidx = osm.sindex  # Räumlicher Index für TILDA-Daten

        # Optional: Öffne Kandidaten-Log-Datei für QA-Zwecke
        candidates_log = None
        if log_candidates:
            qa_dir = "./output/snapping"
            os.makedirs(qa_dir, exist_ok=True)
            candidates_log_file = os.path.join(qa_dir, f"osm_candidates_per_edge{filename_suffix}.txt")
            
            # Benenne alte Datei um falls sie existiert
            if os.path.exists(candidates_log_file):
                old_file = candidates_log_file.replace('.txt', '_OLD.txt')
                # Entferne eventuell vorhandene alte _OLD Datei
                if os.path.exists(old_file):
                    os.remove(old_file)
                os.rename(candidates_log_file, old_file)
                logging.info(f"Alte Kandidaten-Log-Datei umbenannt: {old_file}")
            
            candidates_log = open(candidates_log_file, 'w', encoding='utf-8')
            candidates_log.write("# TILDA-Kandidaten pro element_nr und Richtung\n")
            candidates_log.write("# Generiert von start_snapping.py\n")
            candidates_log.write(f"# Puffergröße: {buffer}m\n")
            candidates_log.write(f"# Max. Winkelunterschied: {CONFIG_MAX_ANGLE_DIFFERENCE}°\n")
            candidates_log.write("#\n")
            candidates_log.write("# Format: element_nr -> Segment #X -> ri=0/1: bester_kandidat [Details] verfügbare: [alle_kandidaten]\n")
            candidates_log.write("#\n\n")

        # Verarbeite alle Segmente
        total = len(net_segmented)
        snapped_records = []
        
        logging.info(f"Starte Snapping von {total} Segmenten mit CPU-Parallelisierung ({CONFIG_CPU_CORES} Kerne)...")
        start_time = time.time()
        
        # Konvertiere zu Liste für Batch-Verarbeitung
        segments_list = []
        for _, row in net_segmented.iterrows():
            seg_dict = row.to_dict()
            segments_list.append(seg_dict)
        
        # Entscheide zwischen paralleler und sequenzieller Verarbeitung
        if log_candidates or total < CONFIG_BATCH_SIZE * 2:
            # Sequenzielle Verarbeitung für Kandidaten-Logging oder kleine Datenmengen
            logging.info("Verwende sequenzielle Verarbeitung (Kandidaten-Logging aktiviert oder kleine Datenmenge)")
            for batch_start in range(0, total, CONFIG_BATCH_SIZE):
                batch_end = min(batch_start + CONFIG_BATCH_SIZE, total)
                segments_batch = segments_list[batch_start:batch_end]
                
                # Verarbeite aktuelle Batch
                batch_results = process_segments_batch(
                    segments_batch, osm, osm.sindex, buffer, 
                    candidates_log, batch_start
                )
                snapped_records.extend(batch_results)
                
                # Aktualisiere Fortschritt nur periodisch (deutlich schneller)
                if batch_end % CONFIG_PROGRESS_UPDATE_INTERVAL == 0 or batch_end == total:
                    elapsed = time.time() - start_time
                    rate = batch_end / elapsed if elapsed > 0 else 0
                    eta_minutes = (total - batch_end) / rate / 60 if rate > 0 else 0
                    
                    print_progressbar(batch_end, total, 
                        prefix=f"Snapping ({rate:.1f}/s, ETA: {eta_minutes:.1f}min): ")
        else:
            # Parallelisierte Verarbeitung für bessere Performance
            logging.info(f"Verwende parallelisierte Verarbeitung mit {CONFIG_CPU_CORES} Kernen")
            
            # Erstelle temporäre Pickle-Datei für OSM-Daten (für Worker-Prozesse)
            with tempfile.NamedTemporaryFile(suffix='.pkl', delete=False) as temp_file:
                osm_temp_path = temp_file.name
            
            # Speichere OSM-Daten als Pickle (unterstützt alle Python-Objekte)
            with open(osm_temp_path, 'wb') as f:
                pickle.dump(osm, f)
            
            try:
                # Bereite Batches für Parallelverarbeitung vor
                batch_data_list = []
                
                for batch_start in range(0, total, CONFIG_BATCH_SIZE):
                    batch_end = min(batch_start + CONFIG_BATCH_SIZE, total)
                    segments_batch = segments_list[batch_start:batch_end]
                    batch_data_list.append((segments_batch, osm_temp_path, buffer, batch_start))
                
                # Verwende multiprocessing Pool für parallele Verarbeitung mit Progress-Balken
                with mp.Pool(processes=CONFIG_CPU_CORES) as pool:
                    # Verwende imap für iterative Verarbeitung mit Progress-Updates
                    batch_count = len(batch_data_list)
                    processed_segments = 0
                    
                    # Starte parallele Verarbeitung mit imap (behält Reihenfolge bei)
                    for i, batch_results in enumerate(pool.imap(process_segments_batch_parallel, batch_data_list)):
                        snapped_records.extend(batch_results)
                        
                        # Zähle verarbeitete EINGABE-Segmente (nicht Ausgabe-Kanten)
                        # Jede Batch verarbeitet CONFIG_BATCH_SIZE Segmente (außer der letzten)
                        batch_size = len(batch_data_list[i][0])  # Anzahl Segmente in dieser Batch
                        processed_segments += batch_size
                        
                        # Aktualisiere Progress-Balken basierend auf verarbeiteten EINGABE-Segmenten
                        elapsed = time.time() - start_time
                        rate = processed_segments / elapsed if elapsed > 0 else 0
                        
                        print_progressbar(processed_segments, total, 
                            prefix=f"Snapping ({rate:.1f}/s, parallel): ")
                    
                    # Finale Statistiken
                    elapsed = time.time() - start_time
                    rate = total / elapsed if elapsed > 0 else 0
                    output_edges = len(snapped_records)
                    logging.info(f"Parallelverarbeitung abgeschlossen: {total} Segmente → {output_edges} Kanten in {elapsed:.1f}s ({rate:.1f} seg/s)")
                    
            finally:
                # Aufräumen: Lösche temporäre Datei
                if os.path.exists(osm_temp_path):
                    os.unlink(osm_temp_path)
        
        elapsed_total = time.time() - start_time
        final_rate = total / elapsed_total
        logging.info(f"Snapping abgeschlossen: {total} Segmente in {elapsed_total:.1f}s "
                    f"(Durchschnitt: {final_rate:.1f} Segmente/s)")
        # Schließe die Kandidaten-Log-Datei falls geöffnet
        if candidates_log:
            candidates_log.close()
            logging.info(f"✔  Kandidaten-Log erstellt: {candidates_log_file}")
        else:
            logging.info("Kandidaten-Logging deaktiviert (verwende --log-candidates zum Aktivieren)")

        # Erstelle GeoDataFrame aus allen bearbeiteten Segmenten
        net_segmented = gpd.GeoDataFrame(snapped_records, crs=crs)
        net_segmented.to_file(seg_attr_path, driver="FlatGeobuf")
        logging.info(f"✔  Attributierte Segmente gespeichert als {seg_attr_path}")

    # ---------- Segmente verschmelzen ---------------------------------------
    logging.info("Fasse Segmente mit gleicher element_nr und TILDA-Attributen zusammen ...")
    
    # Debug: Analysiere Merge-Attribute vor dem Verschmelzen
    logging.info(f"Zu verwendende Merge-Attribute: {FINAL_DATASET_SEGMENT_MERGE_ATTRIBUTES}")
    debug_merge_attributes(net_segmented, "element_nr", FINAL_DATASET_SEGMENT_MERGE_ATTRIBUTES)
    
    out_gdf = merge_segments(net_segmented, "element_nr", FINAL_DATASET_SEGMENT_MERGE_ATTRIBUTES)

    # ---------- Finale Datenbereinigung ------------------------------------
    # Entferne Breite-Attribut bei allen Kanten mit Mischverkehr mit motorisiertem Verkehr
    mischverkehr_mask = out_gdf['fuehr'] == 'Mischverkehr mit motorisiertem Verkehr'
    mischverkehr_count = mischverkehr_mask.sum()
    if mischverkehr_count > 0:
        logging.info(f"Entferne Breite-Attribut bei {mischverkehr_count} Kanten mit Mischverkehr")
        out_gdf.loc[mischverkehr_mask, 'breite'] = None

    # ---------- SFID hinzufügen ---------------------------------------------
    logging.info("Füge SFID-Spalte (Snapping FID) hinzu...")
    out_gdf['sfid'] = range(1, len(out_gdf) + 1)
    logging.info(f"SFID-Spalte hinzugefügt: {len(out_gdf)} Kanten nummeriert")
    
    # ---------- Datenaufbereitung: Spaltenordnung --------------------------
    logging.info("Bereite Daten für Ausgabe vor: Ordne Spalten...")
    out_gdf = reorder_columns_for_output(out_gdf)

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
    ap.add_argument("--net", default="./output/rvn/vorrangnetz_details_combined_rvn.fgb", 
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
    ap.add_argument("--log-candidates", action="store_true",
                    help="Erstelle detaillierte Kandidaten-Log-Datei für Debugging (optional)")
    ap.add_argument("--cpu-cores", type=int, default=CONFIG_CPU_CORES,
                    help=f"Anzahl CPU-Kerne für Parallelisierung (default: {CONFIG_CPU_CORES})")
    args = ap.parse_args()

    # CPU-Kerne-Konfiguration übernehmen (validiere Eingabe)
    cpu_cores = max(1, min(args.cpu_cores, mp.cpu_count()))
    if cpu_cores != CONFIG_CPU_CORES:
        logging.info(f"CPU-Kerne konfiguriert: {cpu_cores} (Standard: {CONFIG_CPU_CORES})")
    
    # Überschreibe globale Konfiguration
    CONFIG_CPU_CORES = cpu_cores
    
    # Hauptfunktion aufrufen
    process(args.net, args.osm, args.out, args.crs, args.buffer, args.clip_neukoelln, args.data_dir, args.log_candidates)

