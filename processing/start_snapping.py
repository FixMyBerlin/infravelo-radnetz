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
import os, logging
import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import LineString, MultiLineString, Point
from helpers.progressbar import print_progressbar
from helpers.globals import DEFAULT_CRS


# -------------------------------------------------------------- Konstanten --
CONFIG_BUFFER_DEFAULT = 30.0     # Standard-Puffergröße in Metern für Matching
CONFIG_MAX_ANGLE_DIFFERENCE = 50.0 # Maximaler Winkelunterschied für Ausrichtung in Grad

# Feldnamen für das Netz
RVN_ATTRIBUT_ELEMENT_NR = "element_nr"           # Kanten-ID
RVN_ATTRIBUT_BEGINN_VP = "beginnt_bei_vp"       # Startknoten-ID
RVN_ATTRIBUT_ENDE_VP   = "endet_bei_vp"         # Endknoten-ID
RVN_ATTRIBUT_VERKEHRSRICHTUNG  = "verkehrsrichtung"     # Werte: R / G / B (Richtung)

FINAL_DATASET_SEGMENT_MERGE_ATTRIBUTES = ["osm_road", "ri", "verkehrsri", "pflicht", "breite"]

# Prioritäten für OSM-Weg-Auswahl (höhere Zahl = höhere Priorität)
TILDA_TRAFFIC_SIGN_PRIORITÄTEN = {
    "237": 3,  # Radweg
    "240": 3,  # Gemeinsamer Geh- und Radweg
    "241": 3,  # Getrennter Rad- und Gehweg
}

# Kategorie-Prioritäten
TILDA_CATEGORY_PRIORITIES = {
    "sharedBusLaneBusWithBike": 2,
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


def reverse_geom(g):
    """Dreht die Richtung einer Linie oder Multi-Linie um."""
    if isinstance(g, LineString):
        return LineString(list(g.coords)[::-1])
    if isinstance(g, MultiLineString):
        parts = [LineString(list(ls.coords)[::-1]) for ls in g.geoms]
        return MultiLineString(parts[::-1])
    raise TypeError


def iter_coords(g):
    """Iteriert über alle Stützpunkte einer Geometrie, egal ob LineString oder MultiLineString."""
    if isinstance(g, LineString):
        yield from g.coords
    elif isinstance(g, MultiLineString):
        for ls in g.geoms:
            yield from ls.coords
    else:
        raise TypeError


def is_left(line: LineString, p: Point) -> bool:
    """Prüft, ob ein Punkt links der Linie liegt (für Richtungsprüfung)."""
    a_x, a_y = line.coords[0]
    b_x, b_y = line.coords[-1]
    return ((b_x - a_x) * (p.y - a_y) - (b_y - a_y) * (p.x - a_x)) > 0

# TODO MultiLineString-Handling behandelt nur den ersten LineString
def calculate_line_angle(line: LineString | MultiLineString) -> float:
    """
    Berechnet den Winkel einer Linie (Anfangs- zu Endpunkt) in Grad.
    Der Winkel wird im Bereich [0, 360) zurückgegeben.
    Bei MultiLineStrings wird nur der erste LineString zur Berechnung verwendet.
    """
    if isinstance(line, MultiLineString):
        # Bei MultiLineString nur den ersten Teil für die Winkelberechnung verwenden
        line = line.geoms[0]

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


def is_bikelane(category: str) -> bool:
    """
    Prüft, ob ein OSM-Weg eine Bikelane ist.
    Eine Bikelane liegt vor, wenn category gesetzt ist und nicht 'sharedMotorVehicleLane'.
    """
    if not category or pd.isna(category):
        return False
    return str(category).strip() != "sharedMotorVehicleLane"


def has_traffic_sign(traffic_sign_value: str, target_sign: str) -> bool:
    """
    Prüft, ob ein bestimmtes Verkehrszeichen in einem traffic_sign Wert vorhanden ist.
    
    Args:
        traffic_sign_value: Der traffic_sign Wert aus OSM (z.B. "DE:240" oder "DE:1022,240")
        target_sign: Das gesuchte Verkehrszeichen (z.B. "240")
    
    Returns:
        True wenn das Verkehrszeichen mit DE: Präfix gefunden wird
    """
    if not traffic_sign_value or pd.isna(traffic_sign_value):
        return False
    
    traffic_sign_str = str(traffic_sign_value).strip()
    
    # Prüfe auf "DE:XXX" Format (direkter Match)
    if f"DE:{target_sign}" in traffic_sign_str:
        return True
    
    # Prüfe auf "DE:XXX,YYY" Format - teile bei Komma und prüfe jeden Teil
    parts = traffic_sign_str.split(",")
    for part in parts:
        part = part.strip()
        # Wenn der Teil mit "DE:" beginnt, extrahiere die Nummer
        if part.startswith("DE:"):
            sign_number = part[3:]  # Entferne "DE:" Präfix
            if sign_number == target_sign:
                return True
        # Wenn der Teil nur eine Nummer ist und wir bereits ein "DE:" am Anfang hatten
        elif part.isdigit() and "DE:" in traffic_sign_str:
            if part == target_sign:
                return True
    
    return False


def calculate_osm_priority(row) -> int:
    """
    Berechnet die Priorität eines OSM-Wegs basierend auf traffic_sign und category.
    Höhere Zahl = höhere Priorität.
    """
    priority = 0
    
    # Priorität basierend auf Verkehrszeichen
    traffic_sign = row.get("traffic_sign", "")
    if traffic_sign:
        for sign, prio in TILDA_TRAFFIC_SIGN_PRIORITÄTEN.items():
            if has_traffic_sign(traffic_sign, sign):
                priority = max(priority, prio)
    
    # Priorität basierend auf Kategorie
    category = row.get("category", "")
    if category and str(category) in TILDA_CATEGORY_PRIORITIES:
        priority = max(priority, TILDA_CATEGORY_PRIORITIES[str(category)])
    
    return priority


def parse_width(width_value) -> float:
    """
    Wandelt OSM-Breitenangaben in standardisierte Meter-Werte um.
    Rundet auf 0,10 m-Stellen und gibt das Ergebnis als Float zurück.
    
    Args:
        width_value: OSM width-Wert (kann String oder Number sein)
    
    Returns:
        Breite in Metern gerundet auf 0,10 m, oder None wenn nicht parsbar
    """
    if not width_value or pd.isna(width_value):
        return None
        
    try:
        # String zu Float konvertieren, falls nötig
        if isinstance(width_value, str):
            # Entferne Einheiten und andere Zeichen
            width_str = str(width_value).strip().lower()
            # Entferne "m", "meter", "metres" etc.
            width_str = width_str.replace("m", "").replace("eter", "").replace("tres", "")
            # Entferne Leerzeichen
            width_str = width_str.strip()
            # Falls mehrere Werte durch Semikolon getrennt sind, nehme den ersten
            if ";" in width_str:
                width_str = width_str.split(";")[0].strip()
            width_float = float(width_str)
        else:
            width_float = float(width_value)
        
        # Auf 0,10 m runden (d.h. auf eine Dezimalstelle)
        return round(width_float, 1)
        
    except (ValueError, TypeError):
        return None


def new_neg_id(counter):
    """Erzeugt eine neue negative ID für Zwischennoten (Splits)."""
    counter["val"] -= 1
    return counter["val"]


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


def merge_segments(gdf, id_field, osm_fields):
    """
    Verschmilzt benachbarte Segmente mit gleicher okstra_id und identischen OSM-Attributen.
    Zeigt einen Fortschrittsbalken an.
    """
    from shapely.ops import linemerge
    gruppen = []
    grouped = list(gdf.groupby([id_field] + osm_fields))
    total = len(grouped)
    for idx, (_, gruppe) in enumerate(grouped, 1):
        geoms = list(gruppe.geometry)
        if not geoms:
            continue
        merged = linemerge(geoms)
        merged_row = gruppe.iloc[0].copy()
        merged_row["geometry"] = merged
        gruppen.append(merged_row)
        print_progressbar(idx, total, prefix="Verschmelze: ")
    if not gruppen:
        raise ValueError("No segments to merge. Check input data and grouping fields.")
    return gpd.GeoDataFrame(gruppen, geometry="geometry", crs=gdf.crs)


def determine_direction_attributes(seg_verkehrsrichtung: str, osm_oneway: str, osm_oneway_bicycle: str, 
                                 osm_category: str) -> str:
    """
    Bestimmt die Richtungsattribute basierend auf Segment-Richtung und OSM-Daten.
    
    Returns:
        verkehrsri: "Einrichtungsverkehr" oder "Zweirichtungsverkehr"
    """
    # Standardwerte
    verkehrsri = "Zweirichtungsverkehr"
    
    # Prüfung auf Einrichtungsverkehr
    oneway_bicycle = str(osm_oneway_bicycle).lower() if osm_oneway_bicycle else ""
    oneway = str(osm_oneway).lower() if osm_oneway else ""
    
    if oneway_bicycle == "yes" or oneway_bicycle == "implicit_yes":
        verkehrsri = "Einrichtungsverkehr"
    elif not is_bikelane(osm_category) and oneway == "yes":
        verkehrsri = "Einrichtungsverkehr"
    elif oneway == "no" and oneway_bicycle == "no":
        verkehrsri = "Zweirichtungsverkehr"
    
    return verkehrsri


def create_segment_variants(seg_dict: dict, matched_osm_ways: list) -> list[dict]:
    """
    Erstellt Varianten eines Straßensegments basierend auf OSM-Wegen.
    Dupliziert das Segment für beide Richtungen und setzt entsprechende Attribute.
    
    Args:
        seg_dict: Dictionary des ursprünglichen Straßensegments
        matched_osm_ways: Liste der gematchten OSM-Wege mit Prioritäten
    
    Returns:
        Liste von Segment-Dictionaries (ein oder zwei, je nach Richtung)
    """
    variants = []
    verkehrsrichtung = seg_dict.get(RVN_ATTRIBUT_VERKEHRSRICHTUNG, "B")
    
    # Für jede Richtung prüfen, ob OSM-Daten vorhanden sind
    directions = []
    if verkehrsrichtung in ["R", "B"]:  # Richtung (gleiche Richtung wie Geometrie)
        directions.append(("R", 0))
    if verkehrsrichtung in ["G", "B"]:  # Gegenrichtung
        directions.append(("G", 1))
    
    for direction, ri_value in directions:
        # Besten OSM-Weg für diese Richtung finden
        best_osm = None
        if matched_osm_ways:
            # Für jetzt nehmen wir den ersten/besten OSM-Weg
            # TODO: Hier könnte weitere Richtungslogik implementiert werden
            best_osm = matched_osm_ways[0]
        
        # Neue Segment-Variante erstellen
        variant = seg_dict.copy()
        variant["ri"] = ri_value
        
        if best_osm is not None:
            # OSM-Attribute übertragen (ohne osm_ Präfix, da die Original-Feldnamen verwendet werden)
            for attr in ["osm_id", "category", "road", "name", "surface", 
                        "surface_color", "oneway", "traffic_sign", "width", "bikelane_self"]:
                original_attr = attr if attr == "osm_id" else attr  # osm_id bleibt, rest ohne Präfix
                variant[f"osm_{attr}"] = best_osm.get(original_attr, None)
            
            # Breite aus OSM-Width-Attribut parsen
            variant["breite"] = parse_width(best_osm.get("width", None))
            
            # Verkehrsrichtung bestimmen
            verkehrsri = determine_direction_attributes(
                verkehrsrichtung,
                best_osm.get("oneway", ""),
                best_osm.get("oneway_bicycle", ""),  # Prüfe ob dieses Feld existiert
                best_osm.get("category", "")
            )
            variant["verkehrsri"] = verkehrsri
            
            # Pflicht-Attribut setzen
            traffic_sign = best_osm.get("traffic_sign", "")
            variant["pflicht"] = any(has_traffic_sign(traffic_sign, sign) for sign in TILDA_TRAFFIC_SIGN_PRIORITÄTEN.keys())
        else:
            # Keine OSM-Daten gefunden - Standardwerte setzen
            variant["verkehrsri"] = "Zweirichtungsverkehr"
            variant["pflicht"] = False
            variant["breite"] = None
            for attr in ["osm_id", "category", "road", "name", "surface", 
                        "surface_color", "oneway", "traffic_sign", "width", "bikelane_self"]:
                variant[f"osm_{attr}"] = None
        
        variants.append(variant)
    
    return variants


# ------------------------------------------------------------- Hauptablauf --
def process(net_path, osm_path, out_path, crs, buf):
    """
    Hauptfunktion: Segmentiert das Netz, führt das Snapping durch und verschmilzt die Segmente wieder.
    net_path: Pfad zum Netz (mit Layer)
    osm_path: Pfad zu OSM-Ways (mit Layer)
    out_path: Ausgabepfad (mit Layer)
    crs: Ziel-Koordinatensystem (EPSG)
    buf: Puffergröße für Matching
    """
    # ---------- Daten laden -------------------------------------------------
    def read(path):
        f, *layer = path.split(":")
        return gpd.read_file(f, layer=layer[0] if layer else None)

    net = read(net_path).to_crs(crs)
    osm = read(osm_path).to_crs(crs)

    # Prüfen, ob alle Pflichtfelder im Netz vorhanden sind
    for fld in (RVN_ATTRIBUT_ELEMENT_NR, RVN_ATTRIBUT_BEGINN_VP, RVN_ATTRIBUT_ENDE_VP, RVN_ATTRIBUT_VERKEHRSRICHTUNG, "okstra_id"):
        if fld not in net.columns:
            sys.exit(f"Pflichtfeld “{fld}” fehlt im Netz!")

    # ---------- Netz segmentieren und speichern -----------------------------
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    
    # Stelle sicher, dass das Ausgabeverzeichnis existiert
    seg_path = "./output/qa-snapping/rvn-segmented.fgb"
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
    seg_attr_path = "./output/qa-snapping/rvn-segmented-attributed-osm.fgb"
    os.makedirs(os.path.dirname(seg_attr_path), exist_ok=True)
    
    if os.path.exists(seg_attr_path):
        logging.info(f"Lade bereits attributierte Segmente aus {seg_attr_path} ...")
        net_segmented = gpd.read_file(seg_attr_path)
    else:
        logging.info("Führe Snapping und OSM-Attributübernahme auf 10% der Segmente durch ...")
        # Erzeuge einen räumlichen Index für die OSM-Ways, um schnelle räumliche Abfragen zu ermöglichen
        osm_sidx = osm.sindex  # Räumlicher Index für OSM-Ways

        # Für Test: nur wenige Segmente bearbeiten 
        total = len(net_segmented)
        n_test = max(1, int(total * 0.10))
        snapped_records = []
        # Starte die OSM-Attributübernahme für jedes Segment
        # --------------------------------------------------
        # Für jedes Segment:
        # 1. Suche OSM-Kandidaten im räumlichen Puffer
        # 2. Filtere nach Entfernung und Ausrichtung
        # 3. Berechne Priorität und wähle den besten OSM-Weg
        # 4. Übertrage relevante OSM-Attribute auf das Segment
        # 5. Erzeuge ggf. Varianten für beide Richtungen
        # 6. Fortschrittsanzeige für den Nutzer
        for idx, seg in enumerate(net_segmented.itertuples(), 1):
            if idx > n_test:
                break
            g = seg.geometry
            
            # Kandidaten im Buffer suchen (räumliche Suche)
            cand_idx = list(osm_sidx.intersection(g.buffer(buf).bounds))
            if not cand_idx:
                # Keine OSM-Kandidaten gefunden - Standardvarianten erzeugen
                seg_dict = seg._asdict()
                variants = create_segment_variants(seg_dict, [])
                snapped_records.extend(variants)
                logging.info(f"Keine OSM-Kandidaten im Puffer für Segment {seg} gefunden.")
                print_progressbar(idx, n_test, prefix="Snapping (Test 10%): ")
                continue
                
            cand = osm.iloc[cand_idx].copy()
            # Filtere Kandidaten nach tatsächlicher Entfernung zum Segment
            cand["d"] = cand.geometry.distance(g)
            cand = cand[cand["d"] <= buf]
            if cand.empty:
                # Keine OSM-Kandidaten im Buffer - Standardvarianten erzeugen
                seg_dict = seg._asdict()
                variants = create_segment_variants(seg_dict, [])
                snapped_records.extend(variants)
                logging.info(f"Keine OSM-Kandidaten im Puffer für Segment {seg} gefunden.")
                print_progressbar(idx, n_test, prefix="Snapping (Test 10%): ")
                continue

            # Berechne den Winkel des Netzsegments
            seg_angle = calculate_line_angle(g)

            # Berechne Winkel und Winkeldifferenz für alle OSM-Kandidaten
            # Kopie erstellen um SettingWithCopyWarning zu vermeiden
            cand = cand.copy()
            cand["angle"] = cand.geometry.apply(calculate_line_angle)
            cand["angle_diff"] = cand["angle"].apply(lambda a: angle_difference(a, seg_angle))

            # Filtere Kandidaten mit passender Ausrichtung
            oriented_cand = cand[cand["angle_diff"] <= CONFIG_MAX_ANGLE_DIFFERENCE].copy()

            # Wenn es ausgerichtete Kandidaten gibt, diese verwenden, sonst alle
            target_cand = oriented_cand if not oriented_cand.empty else cand.copy()

            # Berechne Priorität für alle Kandidaten
            target_cand["priority"] = target_cand.apply(calculate_osm_priority, axis=1)
            
            # Sortiere nach Priorität und Entfernung (höchste Priorität, geringste Entfernung)
            mid = g.interpolate(0.5, normalized=True)
            target_cand["dist_to_mid"] = target_cand.geometry.distance(mid)
            target_cand = target_cand.sort_values(["priority", "dist_to_mid"], ascending=[False, True])

            # Wähle den besten OSM-Weg (höchste Priorität, nächste Entfernung)
            matched_osm_ways = []
            if not target_cand.empty:
                best_osm = target_cand.iloc[0].to_dict()
                matched_osm_ways.append(best_osm)

            # Erzeuge Segment-Varianten basierend auf OSM-Daten
            seg_dict = seg._asdict()
            variants = create_segment_variants(seg_dict, matched_osm_ways)
            snapped_records.extend(variants)
            print_progressbar(idx, n_test, prefix="Snapping (Test 10%): ")
        # Erstelle GeoDataFrame aus allen bearbeiteten Segmenten
        net_segmented = gpd.GeoDataFrame(snapped_records, crs=crs)
        net_segmented.to_file(seg_attr_path, driver="FlatGeobuf")
        logging.info(f"✔  Attributierte Test-Segmente gespeichert als {seg_attr_path}")

    # ---------- Segmente verschmelzen ---------------------------------------
    logging.info("Fasse Segmente mit gleicher okstra_id und OSM-Attributen zusammen ...")
    out_gdf = merge_segments(net_segmented, "okstra_id", FINAL_DATASET_SEGMENT_MERGE_ATTRIBUTES)

    # ---------- Ergebnis speichern ------------------------------------------
    p, *layer = out_path.split(":")
    layer = layer[0] if layer else "edges_enriched"
    
    # Stelle sicher, dass das Ausgabeverzeichnis existiert
    os.makedirs(os.path.dirname(p), exist_ok=True)
    Path(p).unlink(missing_ok=True)
    
    out_gdf.to_file(p, layer=layer, driver="FlatGeoBuf")
    print(f"✔  {len(out_gdf)} Kanten → {p}:{layer}")


# ------------------------------------------------------------- CLI Wrapper --
if __name__ == "__main__":
    # Kommandozeilenargumente parsen
    ap = argparse.ArgumentParser()
    ap.add_argument("--net", default="../output/vorrangnetz_details_combined_rvn.fgb", 
                    help="Netz-Layer (Pfad[:Layer]) - Default: ../output/vorrangnetz_details_combined_rvn.fgb")
    ap.add_argument("--osm", default="../output/matching/matched_osm_ways.fgb", 
                    help="OSM-Ways (Pfad[:Layer]) - Default: ../output/matching/matched_osm_ways.fgb")
    ap.add_argument("--out", default="../output/snapping_network_enriched.fgb", 
                    help="Ausgabe (Pfad[:Layer]) - Default: ../output/snapping_network_enriched.fgb")
    ap.add_argument("--crs",  type=int,   default=DEFAULT_CRS,
                    help=f"Ziel-EPSG (default {DEFAULT_CRS})")
    ap.add_argument("--buffer", type=float, default=CONFIG_BUFFER_DEFAULT,
                    help=f"Matching-Puffer in m (default {CONFIG_BUFFER_DEFAULT})")
    args = ap.parse_args()

    # Hauptfunktion aufrufen
    process(args.net, args.osm, args.out, args.crs, args.buffer)
