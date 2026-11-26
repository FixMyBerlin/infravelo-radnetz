#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
prepare_tilda_routing.py
------------------------
Bereitet den routingfähigen TILDA-Datensatz (`routing`) für das Map-Matching vor.

Schritte:
1. Join: Jede Routing-Kante bekommt die Attribute ihres Quellobjekts
   (`source_table` + `source_id` -> `id` in bikelanes / roads / roadsPathClasses).
2. Topologie: Die Wege werden an jedem Stützpunkt geteilt, den sie mit einem anderen Weg
   teilen (OSM-Knoten an Kreuzungen liegen oft mitten im Weg). Danach endet jede Kante an
   einem Knoten. Es wird nichts geometrisch repariert.
3. Zusammenhang: Nur die größte zusammenhängende Komponente wird behalten. Bricht ab, wenn
   sie zu wenig Radinfrastruktur enthält. Ausgeschlossene Kanten landen im Report.
4. Zuschnitt auf den RVN-Puffer (entfällt mit `--netz ren` oder `--ohne-rvn-zuschnitt`)
   und Übersetzung der TILDA-Attribute in RVN-Attribute (`translate_tilda_attributes`,
   Mapping-Regeln im Abschnitt „Übersetzung TILDA -> RVN“ unten).

INPUT:
- data/TILDA Routing Berlin.gpkg           (Export `routing`)
- data-raw-tilda/bikelanes.fgb             (Export `bikelanes`, gleicher Verarbeitungsstand)
- data-raw-tilda/roads.fgb                 (Export `roads`, gleicher Verarbeitungsstand)
- data-raw-tilda/roadsPathClasses.fgb      (Export `roadsPathClasses`, gleicher Verarbeitungsstand)

OUTPUT (output/TILDA-routing/, mit --netz ren output/TILDA-routing-ren/):
- TILDA Routing {Bikelanes,Streets,Paths} Translated.fgb
- ausserhalb_hauptnetz.fgb                 (Kanten außerhalb der größten Komponente)
- report.json                              (Kennzahlen zu Join und Topologie)

Aufruf (aus processing/):
    python scripts/prepare_tilda_routing.py
    python scripts/prepare_tilda_routing.py --netz ren
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
import pyogrio
from shapely import LineString

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from helpers.construction_comments import collect_todo_attributes  # noqa: E402
from helpers.globals import DEFAULT_CRS, RVN_BUFFER_METERS  # noqa: E402
from helpers.netz import TILDA_ROUTING_DIR, add_netz_argument  # noqa: E402
from helpers.progressbar import print_progressbar  # noqa: E402
from helpers.traffic_signs import has_traffic_sign  # noqa: E402
from helpers.width_parser import parse_width  # noqa: E402

# source_table im Routing-Datensatz -> (Rohdatei, data_source im Map-Matching)
SOURCES = {
    "bikelanes": ("bikelanes.fgb", "bikelanes"),
    "roads": ("roads.fgb", "streets"),
    "roadsPathClasses": ("roadsPathClasses.fgb", "paths"),
}
# Stützpunkte gelten bis auf 1e-7 Grad (ca. 1 cm) als identisch (Gleitkomma-Rauschen).
COORD_DECIMALS = 7


# ==================================================== Übersetzung TILDA -> RVN ==
# Übersetzt die TILDA-Attribute jeder Kante in RVN-Attribute (verkehrsri, fuehr, pflicht, breite,
# ofm, farbe, protek, trennstreifen, nutz_beschr, Länge, Kommentar). Die ursprünglichen
# TILDA-Attribute bekommen das Präfix `tilda_`.

# Konstanten
# Liste der RVN-Attribute, die auf fehlende Werte geprüft werden sollen
# (für Baustellen/temporäre Infrastruktur Kommentare)
# HINWEIS: "Kommentar" und "Länge" sind hier NICHT enthalten, da diese keine Pflichtattribute sind
CONFIG_ATTRIBUTES_TODO_CHECK = ["pflicht", "breite", "ofm", "farbe", "protek", "trennstreifen", "nutz_beschr", "fuehr", "verkehrsri"]

# Liste der neuen RVN-Attribute, die nicht umbenannt werden sollen
CONFIG_ATTRIBUTES_NOT_RENAMING = ["pflicht", "breite", "ofm", "farbe", "protek", "trennstreifen", "nutz_beschr", "fuehr", "verkehrsri", "Länge", "Kommentar"]

# Radvorrangsnetz-Datei für Buffer-Clipping
INPUT_RVN_FILE = "Berlin Radvorrangsnetz.fgb"

# Mappings für Oberflächenmaterial (OFM)
MAPPING_OFM_SURFACE = {
    "asphalt": "Asphalt",
    "concrete": "Beton (Platte etc.)",
    "concrete:plates": "Beton (Platte etc.)",
    "concrete:lanes": "Beton (Platte etc.)",
    "paving_stones": "Gepflastert (Berliner Platte, Mosaik, Kleinstein...)",
    "mosaic_sett": "Gepflastert (Berliner Platte, Mosaik, Kleinstein...)",
    "small_sett": "Gepflastert (Berliner Platte, Mosaik, Kleinstein...)", 
    "large_sett": "Gepflastert (Berliner Platte, Mosaik, Kleinstein...)",
    "sett": "Kopfsteinpflaster / Großstein",
    "cobblestone": "Kopfsteinpflaster / Großstein",
    "bricks": "Kopfsteinpflaster / Großstein",
    "stone": "Kopfsteinpflaster / Großstein",
    "unpaved": "Ungebunden",
    "ground": "Ungebunden", 
    "grass": "Ungebunden",
    "sand": "Ungebunden",
    "compacted": "Ungebunden",
    "fine_gravel": "Ungebunden",
    "pebblestone": "Ungebunden",
    "gravel": "Ungebunden",
}

# Mappings für physische Protektion (PROTEK)
MAPPING_PROTEK_SEPARATION = {
    "bollard": "Poller (auf Sperrfläche)",
    "bump": "Schwellen (auf Sperrfläche)",
    "vertical_panel": "Leitboys (flexibel, auf Breitstrich, ohne Sperrfläche)",
    "flex_post": "Leitboys (flexibel, auf Breitstrich, ohne Sperrfläche)",

    "planter": "Sonstige (z.B. Pflanzkübel, Leitplanke)",
    "guard_rail": "Sonstige (z.B. Pflanzkübel, Leitplanke)",
    "fence": "Sonstige (z.B. Pflanzkübel, Leitplanke)",
    "jersey_barrier": "Sonstige (z.B. Pflanzkübel, Leitplanke)",
    
    "no": "Ohne"
}

# Traffic Signs für Benutzungspflicht
TRAFFIC_SIGNS_PFLICHT = ["237", "240", "241"]

# Traffic Signs für Nutzungsbeschränkungen
TRAFFIC_SIGNS_NUTZ_BESCHR = ["Gehwegschäden", "Radwegschäden", "Geh- und Radwegschäden"]

# Liste der zu entfernenden Attribute (ohne tilda-Prefix)
# Enthält sowohl Attribute von Bikelanes, Roads und Paths
# (`maxspeed*` und `smoothness_source` bleiben, siehe add_maxspeed_attributes; die rohen
# `osm_maxspeed*`-Spalten gehen darin auf)
CONFIG_REMOVE_TILDA_ATTRIBUTES = [
    "lit", "description", "maxspeed_name_ref", "maxspeed_confidence", "mapillary_coverage",  "bridge", "tunnel", "todos", "updated_age", "updated_at", "surface_confidence", "surface_source", "smoothness_confidence", "length", "offset", "_parent_highway",
    "osm_maxspeed_forward", "osm_maxspeed_backward", "osm_maxspeed_conditional",
    "osm_maxspeed:forward", "osm_maxspeed:backward", "osm_maxspeed:conditional",
    "parent_maxspeed", "adjoining_maxspeed",
]

# RVN-Buffer Cache (wird einmal geladen und wiederverwendet)
_rvn_buffer_cache = None


def load_rvn_buffer(data_dir: str, crs: int, buffer_distance: float = RVN_BUFFER_METERS) -> gpd.GeoDataFrame:
    """
    Lädt das Radvorrangsnetz und erstellt einen Buffer um alle Linien.
    Das Ergebnis wird gecached um mehrfaches Laden zu vermeiden.
    
    Args:
        data_dir: Verzeichnis mit den Eingabedateien
        crs: Ziel-Koordinatensystem
        buffer_distance: Puffergröße in Metern (default: RVN_BUFFER_METERS)
    
    Returns:
        GeoDataFrame mit gepuffertem RVN als einzelnes Polygon
    """
    global _rvn_buffer_cache
    
    if _rvn_buffer_cache is not None:
        return _rvn_buffer_cache
    
    rvn_path = os.path.join(data_dir, INPUT_RVN_FILE)
    
    if not os.path.exists(rvn_path):
        logging.warning(f"RVN-Datei nicht gefunden: {rvn_path}. Kein Buffer-Clipping möglich.")
        return None
    
    logging.info(f"Lade RVN für Buffer-Berechnung: {rvn_path}")
    rvn_gdf = gpd.read_file(rvn_path).to_crs(crs)
    
    # Erstelle Buffer um alle RVN-Linien und vereinige zu einem Polygon
    logging.info(f"Erstelle {buffer_distance}m Buffer um RVN ({len(rvn_gdf)} Features)")
    rvn_buffered = rvn_gdf.geometry.buffer(buffer_distance)
    rvn_union = rvn_buffered.unary_union
    
    # Erstelle GeoDataFrame mit dem vereinigten Buffer
    _rvn_buffer_cache = gpd.GeoDataFrame(geometry=[rvn_union], crs=crs)
    
    return _rvn_buffer_cache


def clip_to_rvn_buffer(gdf: gpd.GeoDataFrame, data_dir: str, crs: int) -> gpd.GeoDataFrame:
    """
    Filtert alle Features, die den RVN-Buffer berühren (intersect).
    Behält vollständige Linien - kein geometrisches Zuschneiden.
    
    Args:
        gdf: GeoDataFrame mit TILDA-Daten
        data_dir: Verzeichnis mit den Eingabedateien
        crs: Ziel-Koordinatensystem
    
    Returns:
        GeoDataFrame nur mit Features die den RVN-Buffer berühren
    """
    rvn_buffer = load_rvn_buffer(data_dir, crs)
    
    if rvn_buffer is None:
        logging.warning("Kein RVN-Buffer verfügbar. Verwende alle Features.")
        return gdf
    
    original_count = len(gdf)
    
    # Spatial Index für effiziente Abfrage
    # Finde alle Features die den Buffer intersecten (berühren)
    buffer_geom = rvn_buffer.geometry.iloc[0]
    intersects_mask = gdf.geometry.intersects(buffer_geom)
    
    filtered_gdf = gdf[intersects_mask].copy()
    
    filtered_count = len(filtered_gdf)
    removed_count = original_count - filtered_count
    percentage = (filtered_count / original_count * 100) if original_count > 0 else 0
    
    logging.info(f"RVN-Buffer Clipping: {filtered_count} von {original_count} Features behalten ({percentage:.1f}%), {removed_count} entfernt")
    
    return filtered_gdf


# --------------------------------------------------------- Hilfsfunktionen --
def determine_verkehrsri(row, data_source: str) -> str:
    """
    Bestimmt die Verkehrsrichtung (Radverkehr) basierend auf oneway-Attributen.
    
    Args:
        row: Datenzeile mit OSM-Attributen
        data_source: Art der Daten ("bikelanes", "streets", "paths")
    
    Returns:
        Verkehrsrichtung oder TODO-Hinweis
    """
    # TILDA schreibt fehlende Werte und oneway=no als null; pandas liest sie als NaN, str(NaN) wäre "nan".
    oneway = "" if pd.isna(row.get("oneway")) else str(row.get("oneway")).strip()
    oneway_bicycle = "" if pd.isna(row.get("oneway_bicycle")) else str(row.get("oneway_bicycle")).strip()
    
    if data_source == "bikelanes":
        # Spezifische Regeln für bikelanes
        if oneway == "yes":
            return "Einrichtungsverkehr"
        elif oneway == "no":
            return "Zweirichtungsverkehr"
        elif oneway == "car_not_bike":
            return "Zweirichtungsverkehr"
        elif oneway == "assumed_no":
            # Prüfen ob die Daten präzisiert werden müssen
            return "Zweirichtungsverkehr"
        elif oneway == "implicit_yes":
            # Prüfen ob die Daten präzisiert werden müssen
            return "Einrichtungsverkehr"
        elif not oneway or oneway in ["None", "none"]:
            # Fehlende Werte
            return f"[TODO] Fehlender Wert: oneway={oneway}"
        else:
            logging.warning(f"Unbekannter oneway-Wert für bikelanes: {oneway}, osm_id={row.get('osm_id', 'unbekannt')}")
            return f"[TODO] Fehlerhafter Wert: oneway={oneway}"
    
    elif data_source in ["streets", "paths"]:
        # Spezifische Regeln für streets und paths
        if not oneway or oneway in ["None", "none", "nil"]:
            # oneway=nil oder leere Werte
            return "Zweirichtungsverkehr"
        # Muss als zweites stehen
        elif oneway_bicycle == "no":
            return "Zweirichtungsverkehr"
        elif oneway == "yes":
            return "Einrichtungsverkehr"
        elif oneway == "yes_dual_carriageway":
            return "Einrichtungsverkehr"
        elif oneway == "no":
            return "Zweirichtungsverkehr"
        else:
            logging.warning(f"Unbekannter oneway-Wert für {data_source}: {oneway}, osm_id={row.get('osm_id', 'unbekannt')}")
            return f"[TODO] Fehlerhafter Wert: oneway={oneway}"
    
    # Fallback
    logging.warning(f"Unbekannter data_source für verkehrsri: {data_source}")
    return f"[TODO] Fehlerhafter Wert: data_source={data_source}"


def determine_fuehrung(row, data_source: str) -> str:
    """
    Bestimmt die Art der Radverkehrsführung basierend auf category und traffic_sign.
    
    Args:
        row: Datenzeile mit OSM-Attributen
        data_source: Art der Daten ("bikelanes", "streets", "paths")
    
    Returns:
        Radverkehrsführungstyp oder "[TODO] Führung fehlt"
    """
    if data_source == "streets":
        return "Mischverkehr mit motorisiertem Verkehr"
    elif data_source == "paths":
        return "Sonstige Wege (Gehwege, Wege durch Grünflächen, Plätze)"
    
    # Für bikelanes: basierend auf category
    category = str(row.get("category", "")).strip()
    traffic_sign = str(row.get("traffic_sign", "")).strip()
    
    if category == "cyclewayOnHighway_exclusive" or category == "cyclewayOnHighwayBetweenLanes":
        return "Radfahrstreifen"
    elif category == "sharedBusLaneBikeWithBus":
        return "Radfahrstreifen mit Linienverkehr frei (Z237 mit Z1026-32)"
    elif category == "sharedBusLaneBusWithBike":
        return "Bussonderfahrstreifen mit Radverkehr frei (Z245 mit Z1022‐10)"
    elif category == "cyclewayOnHighwayProtected":
        return "Geschützter Radfahrstreifen"
    elif category == "cyclewayOnHighway_advisory":
        return "Schutzstreifen"
    elif category in ["bicycleRoad", "bicycleRoad_vehicleDestination"]:
        return "Fahrradstraße /-zone (Z 244)"
    elif any(category.startswith(cat) for cat in ["footAndCyclewayShared", "footAndCyclewaySegregated", "cyclewaySeparated", "cycleway_adjoining"]):
        # Prüfe auf gemeinsamen Geh- und Radweg mit Z240
        if category.startswith("footAndCyclewayShared") and has_traffic_sign(traffic_sign, "240"):
            return "Gemeinsamer Geh- und Radweg mit Z240"
        # Falls kein traffic_sign vorhanden, als Sonstige Wege klassifizieren
        # elif traffic_sign.strip() in ["none", "nan", ""]:
        #     return "Sonstige Wege (Gehwege, Wege durch Grünflächen, Plätze)"
        return "Radweg"
    elif category == "cycleway_isolated":
        return "Radweg"
    elif category.startswith("footwayBicycleYes"):
        # Prüfe auf Zusatzzeichen "Radverkehr frei" (Z239 mit Z1022-10)
        if has_traffic_sign(traffic_sign, "239") and has_traffic_sign(traffic_sign, "1022-10"):
            return "Gehweg mit Zusatzzeichen \"Radverkehr frei\" (Z239 mit Z1022-10)"
        # Falls kein traffic_sign vorhanden, als Sonstige Wege klassifizieren
        elif traffic_sign.strip() in ["none", "nan"]:
            return "Sonstige Wege (Gehwege, Wege durch Grünflächen, Plätze)"
        else:
            return "Sonstige Wege (Gehwege, Wege durch Grünflächen, Plätze)"
    elif (category == "pedestrianAreaBicycleYes" and 
          (has_traffic_sign(traffic_sign, "242") or has_traffic_sign(traffic_sign, "242.1")) and
          has_traffic_sign(traffic_sign, "1022-10")):
        return "Fußgängerzone \"Radverkehr frei\" (Z242 mit Z1022-10)"
    elif category == "sharedMotorVehicleLane":
        return "Mischverkehr mit motorisiertem Verkehr"
    elif category == "pedestrianAreaBicycleYes":
        return "Sonstige Wege (Gehwege, Wege durch Grünflächen, Plätze)"
    elif category == "crossing":
        return "Kreuzungsweg"   
    elif category == "needsClarification":
        return "[TODO] Klärung notwendig"
    
    logging.warning(f"Keine Führung gefunden für category={category}, traffic_sign={traffic_sign}, osm_id={row.get('osm_id', 'unbekannt')}")
    return "[TODO] Führung fehlt"


def determine_pflicht(row, data_source: str) -> bool:
    """
    Bestimmt die Benutzungspflicht basierend auf Verkehrszeichen.
    Prüft traffic_sign, traffic_sign_forward und traffic_sign_backward.
    
    Args:
        row: Datenzeile mit OSM-Attributen
        data_source: Art der Daten ("bikelanes", "streets", "paths")
    
    Returns:
        True wenn Benutzungspflicht vorliegt
    """
    # TODO Evntuell anpassen path, wenn fahrradwege rausfallen
    if data_source in ["streets"]:
        return False  # Immer "Nein" für streets und paths
    
    # Sammle alle relevanten Verkehrszeichen-Attribute
    traffic_sign_fields = [
        str(row.get("traffic_sign", "")),
        str(row.get("traffic_sign_forward", "")),
        str(row.get("traffic_sign_backward", ""))
    ]
    
    # Prüfe auf Benutzungspflicht-Zeichen (Z237, Z240, Z241) in allen Feldern
    for traffic_sign in traffic_sign_fields:
        if traffic_sign and traffic_sign.strip():  # Nur nicht-leere Felder prüfen
            for sign in TRAFFIC_SIGNS_PFLICHT:
                if has_traffic_sign(traffic_sign, sign):
                    return True
    
    return False


def determine_ofm(row) -> str:
    """
    Bestimmt das Oberflächenmaterial basierend auf surface-Attribut.
    Alle nicht zugeordneten Surface-Werte werden als "Sonstige" kategorisiert.
    
    Args:
        row: Datenzeile mit OSM-Attributen
    
    Returns:
        Oberflächenmaterial-Kategorie oder "NICHT-GEFUNDEN"
    """
    surface = str(row.get("surface", "")).strip().lower()
    
    if not surface or surface == "nan":
        return "NICHT-GEFUNDEN"
    
    # Prüfe auf "none" Wert
    if surface == "none":
        return "[TODO] Fehlt"
    
    # Prüfe Mappings
    if surface in MAPPING_OFM_SURFACE:
        return MAPPING_OFM_SURFACE[surface]
    
    # Alle anderen surface-Werte werden als "Sonstige" kategorisiert
    logging.info(f"Surface-Wert '{surface}' wird als 'Sonstige' kategorisiert")
    return "Sonstige"


def determine_farbe(row) -> bool:
    """
    Bestimmt ob eine durchgehende farbliche Beschichtung vorliegt.
    
    Args:
        row: Datenzeile mit OSM-Attributen
    
    Returns:
        True wenn rote oder grüne Färbung vorliegt
    """
    surface_color = str(row.get("surface_color", "")).strip().lower()
    
    return surface_color in ["red", "green"]


def determine_protek(row) -> str:
    """
    Bestimmt die Art der physischen Protektion.
    Nur relevant für geschützte Radfahrstreifen.
    
    Args:
        row: Datenzeile mit OSM-Attributen
    
    Returns:
        Protektionsart oder "NICHT-GEFUNDEN"
    """
    category = str(row.get("category", "")).strip()
    
    # Nur für geschützte Radfahrstreifen relevant
    if category != "cyclewayOnHighwayProtected":
        return "Ohne"
    
    # Prüfe verschiedene Separation-Attribute (left/right)
    for side in ["left", "right"]:
        separation = row.get(f"separation_{side}", "") or row.get("separation", "")
        traffic_mode = row.get(f"traffic_mode_{side}", "")
        markings = row.get(f"marking_{side}", "") or row.get("marking", "")
        
        separation_str = str(separation).strip().lower()
        
        # Ruhender Verkehr mit Sperrfläche
        if str(traffic_mode).strip().lower() == "parking" and "barred_area" in str(markings).lower():
            return "Ruhender Verkehr (mit Sperrfläche)"
        
        # Prüfe Separation-Mappings
        if separation_str in MAPPING_PROTEK_SEPARATION:
            return MAPPING_PROTEK_SEPARATION[separation_str]
        
        # Nur Sperrfläche
        if "barred_area" in str(markings).lower() and separation_str == "no":
            return "nur Sperrfläche"
    
    # TODO: Weitere komplexe Logik für Poller mit/ohne Sperrfläche
    logging.warning(f"Keine Protektion gefunden für Feature {row.get('osm_id', 'unbekannt')}")
    return "Protektionstyp nicht bekannt"


def determine_trennstreifen(row) -> str:
    """
    Bestimmt das Vorhandensein eines Sicherheitstrennstreifens.
    
    Für Fahrradstraßen: Prüft beide Seiten (left/right)
    - "ja" wenn auf mindestens einer Seite: Parking + (Buffer > 0 ODER Markierung vorhanden)
    - "nein" wenn Parking vorhanden, aber weder Buffer noch Markierung
    - "entfällt" wenn kein Parking auf beiden Seiten
    
    Für andere Infrastrukturtypen: Nur rechte Seite relevant (siehe unten)

    Args:
        row: Datenzeile mit OSM-Attributen

    Returns:
        "ja", "nein" oder "entfällt"
    """
    category = str(row.get("category", "")).strip().lower()

    if category.startswith("bicycleroad"):
        has_parking = False
        has_trennstreifen = False
        
        for side in ["left", "right"]:
            traffic_mode = str(row.get(f"traffic_mode_{side}", "")).strip().lower()
            markings = str(row.get(f"marking_{side}", "")).strip().lower()
            buffer_value = row.get(f"buffer_{side}", None)
            is_parking = traffic_mode == "parking"
            
            if is_parking:
                has_parking = True
                
                # Prüfe ob Buffer vorhanden ist
                try:
                    buffer_val = float(buffer_value) if buffer_value is not None and buffer_value != "" else None
                except (ValueError, TypeError):
                    buffer_val = None
                
                # Trennstreifen wenn Buffer vorhanden ODER Markierung vorhanden
                has_buffer = buffer_val is not None and buffer_val > 0
                has_marking = "dashed_line" in markings or "solid_line" in markings
                
                if has_buffer or has_marking:
                    has_trennstreifen = True
        
        # Wenn Trennstreifen auf mindestens einer Seite gefunden
        if has_trennstreifen:
            return "ja"
        # Wenn Parking vorhanden aber kein Trennstreifen (weder Buffer noch Markierung)
        elif has_parking:
            return "nein"
        # Kein Parking auf beiden Seiten
        else:
            return "entfällt"

    traffic_mode_right = str(row.get("traffic_mode_right", "")).strip().lower()
    markings_right = str(row.get("marking_right", "")).strip().lower()
    is_parking_right = traffic_mode_right == "parking"
    buffer_right = row.get("buffer_right", None)

    # Kein rechtsseitig ruhender Verkehr
    if not is_parking_right:
        return "entfällt"

    # Überprüfe, ob buffer_right vorhanden und mindestens 0.6 ist
    try:
        buffer_right_val = float(buffer_right) if buffer_right is not None and buffer_right != "" else None
    except (ValueError, TypeError):
        buffer_right_val = None

    if is_parking_right and buffer_right_val is not None and buffer_right_val >= 0.6:
        return "ja"

    return "nein"


def determine_nutz_beschr(row, fuehr: str) -> str:
    """
    Bestimmt Nutzungsbeschränkungen aufgrund baulicher Mängel.
    Wende Nutzungsbeschränkungen nicht auf Wege mit Mischverkehr an.
    
    Args:
        row: Datenzeile mit OSM-Attributen
        fuehr: Art der Radverkehrsführung
    
    Returns:
        Nutzungsbeschränkung oder "keine"
    """
    # Keine Nutzungsbeschränkungen für Mischverkehr mit motorisiertem Verkehr
    if fuehr == "Mischverkehr mit motorisiertem Verkehr":
        return "keine"
    
    traffic_sign = str(row.get("traffic_sign", ""))
    
    # Prüfe auf Schadensschilder
    for sign in TRAFFIC_SIGNS_NUTZ_BESCHR:
        if sign in traffic_sign:
            return "Schadensschild/StVO Zusatzeichen (Straßenschäden, Gehwegschäden, Radwegschäden)"
    
    # Fall Physische Sperre (Absperrschranke Z600) - noch nicht implementiert
    # Wird durch Override und TILDA Hinweise abgebildet.
    
    return "keine"


# Fahrrad-Zugang aus TILDA-`routing` (`access_bicycle`), bei dem Radfahren nicht erlaubt ist.
ACCESS_BICYCLE_RESTRICTED = {"no", "destination", "private", "customers", "delivery", "permit", "agricultural_or_forestry"}


def cycling_restriction(row) -> str | None:
    """Hinweis, wenn Radfahren auf dem Weg nach OSM nicht erlaubt ist (TILDA `routing.access_bicycle`).

    Solche Wege bleiben im Ergebnis, damit sichtbar wird, wo ein Weg für den Radverkehr geöffnet werden könnte.
    """
    value = row.get("routing_access_bicycle")
    if isinstance(value, str) and value in ACCESS_BICYCLE_RESTRICTED:
        return f"Radverkehr nicht erlaubt (access_bicycle={value})"
    return None


def combine_nutz_beschr(*parts: str | None) -> str:
    """Mehrere Nutzungsbeschränkungen nebeneinander; "keine", wenn es keine gibt."""
    present = [p for p in parts if p and p != "keine"]
    return "; ".join(present) if present else "keine"


def determine_kommentar(row, translated_row=None) -> str:
    """
    Bestimmt den Kommentar basierend auf dem lifecycle-Attribut und fehlenden Attributen.
    
    Wenn lifecycle=construction oder lifecycle=construction_no_access:
    - Hauptkommentar: "Derzeit Baustelle (Stand ...)"
    - Zusatzkommentare: Für jedes Attribut aus CONFIG_ATTRIBUTES_TODO_CHECK mit [TODO] 
      oder fehlendem Wert wird hinzugefügt: "{Attributname} Attribut fehlt aufgrund von Baustelle"
    
    Wenn lifecycle=temporary:
    - Hauptkommentar: "Temporäre Markierungen zum Erhebungszeitpunkt"
    - Zusatzkommentare: Für jedes Attribut aus CONFIG_ATTRIBUTES_TODO_CHECK mit [TODO] 
      oder fehlendem Wert wird hinzugefügt: "{Attributname} Attribut fehlt aufgrund von temporärer Infrastruktur"
    
    Args:
        row: Datenzeile mit OSM-Attributen
        translated_row: Optional - Datenzeile mit übersetzten RVN-Attributen (nach Translation)
    
    Returns:
        Kommentar oder None (null)
    """
    lifecycle = str(row.get("lifecycle", "")).strip().lower()
    
    comments = []
    
    # Behandle beide construction-Varianten
    if lifecycle in ["construction", "construction_no_access"]:
        # Hauptkommentar: Baustelle
        updated_at = row.get("updated_at")
        try:
            if updated_at and str(updated_at).strip() and str(updated_at).strip() != "nan":
                # Konvertiere Unix-Timestamp zu lesbarem Datum
                timestamp = int(float(str(updated_at).strip()))
                date_str = datetime.fromtimestamp(timestamp).strftime("%d.%m.%Y")
                comments.append(f"Derzeit Baustelle (Stand {date_str})")
            else:
                comments.append("Derzeit Baustelle (Stand unbekannt)")
        except (ValueError, TypeError, OSError) as e:
            logging.warning(f"Fehler beim Formatieren des updated_at Datums: {updated_at}, Fehler: {e}")
            comments.append("Derzeit Baustelle (Stand unbekannt)")
        
        # Zusatzkommentare: Fehlende Attribute aufgrund Baustelle
        if translated_row is not None:
            todo_attrs = collect_todo_attributes(translated_row, CONFIG_ATTRIBUTES_TODO_CHECK, include_missing=True)
            for attr in todo_attrs:
                # Kapitalisiere ersten Buchstaben des Attributnamens
                attr_display = attr.capitalize()
                comments.append(f"{attr_display} Attribut fehlt aufgrund von Baustelle")
    
    elif lifecycle == "temporary":
        comments.append("Temporäre Markierungen zum Erhebungszeitpunkt")
        
        # Zusatzkommentare: Fehlende Attribute aufgrund temporärer Infrastruktur
        if translated_row is not None:
            todo_attrs = collect_todo_attributes(translated_row, CONFIG_ATTRIBUTES_TODO_CHECK, include_missing=True)
            for attr in todo_attrs:
                # Kapitalisiere ersten Buchstaben des Attributnamens
                attr_display = attr.capitalize()
                comments.append(f"{attr_display} Attribut fehlt aufgrund von temporärer Infrastruktur")
    
    # Verbinde alle Kommentare mit Semikolon
    if comments:
        return "; ".join(comments)
    
    return None


def assign_prefix_and_remove_unnecessary_attrs(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Fügt den Prefix 'tilda_' zu allen ursprünglichen Attributen hinzu und entfernt bestimmte unerwünschte Attribute.
    
    Args:
        gdf: GeoDataFrame mit TILDA-Attributen
    
    Returns:
        GeoDataFrame mit umbenannten Spalten
    """
    # Entferne diese Spalten, falls vorhanden
    gdf = gdf.drop(columns=[col for col in CONFIG_REMOVE_TILDA_ATTRIBUTES if col in gdf.columns], errors='ignore')
    
    # Erstelle Mapping für Umbenennung
    rename_mapping = {}
    for col in gdf.columns:
        if col not in CONFIG_ATTRIBUTES_NOT_RENAMING and col != "geometry":
            rename_mapping[col] = f"tilda_{col}"
    
    return gdf.rename(columns=rename_mapping)


def _text_or_none(series: pd.Series) -> pd.Series:
    """Werte als Text ohne Nachkommastelle bei ganzen Zahlen (30.0 -> "30"), leere Werte als None."""
    def convert(value):
        if pd.isna(value):
            return None
        if isinstance(value, (int, float)) and float(value).is_integer():
            return str(int(value))
        text = str(value).strip()
        return text or None
    return series.map(convert).astype(object)


def _first_column(gdf: gpd.GeoDataFrame, *names: str) -> pd.Series:
    """Erste vorhandene Spalte (Exporte nennen OSM-Tags mit `:` mal mit `_`), sonst leere Serie."""
    for name in names:
        if name in gdf.columns:
            return _text_or_none(gdf[name])
    return pd.Series([None] * len(gdf), index=gdf.index, dtype=object)


def add_maxspeed_attributes(gdf: gpd.GeoDataFrame, data_source: str) -> gpd.GeoDataFrame:
    """
    Bildet die Höchstgeschwindigkeit der Fahrbahn für das Map-Matching ab (danach `tilda_`-Präfix):
    - `maxspeed` / `maxspeed_source`: roads (Fahrbahn): TILDA `maxspeed` und `maxspeed_source`.
      bikelanes: `parent_maxspeed`, sonst `adjoining_maxspeed` (Quelle = Name der Spalte).
      Wege: `adjoining_maxspeed`.
    - `maxspeed_forward` / `maxspeed_backward`: OSM `maxspeed:forward|backward` (roads), gelten in bzw.
      gegen die Digitalisierungsrichtung des TILDA-Wegs. Das Map-Matching entscheidet je Teilsegment
      über die Fahrtrichtung, ob sie `maxspeed` ersetzen.
    - `maxspeed_conditional`: OSM `maxspeed:conditional`.
    """
    gdf = gdf.copy()
    n = len(gdf)
    empty = pd.Series([None] * n, index=gdf.index, dtype=object)
    if data_source == "streets":
        maxspeed = _first_column(gdf, "maxspeed")
        source = _first_column(gdf, "maxspeed_source")
    else:
        parent = _first_column(gdf, "parent_maxspeed") if data_source == "bikelanes" else empty
        adjoining = _first_column(gdf, "adjoining_maxspeed")
        maxspeed = parent.where(parent.notna(), adjoining)
        source = pd.Series(
            ["parent_maxspeed" if pd.notna(p) else "adjoining_maxspeed" if pd.notna(a) else None for p, a in zip(parent, adjoining)],
            index=gdf.index, dtype=object,
        )
    gdf["maxspeed"] = maxspeed
    gdf["maxspeed_source"] = source
    gdf["maxspeed_forward"] = _first_column(gdf, "osm_maxspeed_forward", "osm_maxspeed:forward")
    gdf["maxspeed_backward"] = _first_column(gdf, "osm_maxspeed_backward", "osm_maxspeed:backward")
    gdf["maxspeed_conditional"] = _first_column(gdf, "osm_maxspeed_conditional", "osm_maxspeed:conditional")
    return gdf


def calculate_segment_length(geometry):
    """
    Berechnet die Länge eines Segments in Metern.
    """
    return geometry.length


def lane_implicit_oneway_to_yes(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Schreibt `oneway=implicit_yes` an Spuren auf der Fahrbahn (Seitenlinien `…/cycleway/left|right`, keine
    Radwege oder Wege neben der Fahrbahn) als `yes`.

    An einer Spur ist die Fahrtrichtung der Seite der Standard (StVO, Wiki); TILDA schreibt dann `implicit_yes`,
    mit Tag `yes`. Im Ergebnis soll beides gleich aussehen. Radwege und Wege (`*_adjoining`, `*_isolated`) werden
    ausdrücklich gemappt, dort bleibt `implicit_yes` als Hinweis auf den fehlenden Tag.
    """
    if "oneway" not in gdf.columns or "id" not in gdf.columns or "category" not in gdf.columns:
        return gdf
    category = gdf["category"].fillna("").astype(str)
    is_lane = (
        gdf["id"].astype(str).str.contains("/cycleway/", regex=False)
        & ~category.str.contains("_adjoining|_isolated", regex=True)
    )
    mask = is_lane & (gdf["oneway"] == "implicit_yes")
    logging.info(f"{int(mask.sum())} Spuren mit oneway=implicit_yes als yes übernommen")
    gdf.loc[mask, "oneway"] = "yes"
    return gdf


def translate_tilda_attributes(gdf: gpd.GeoDataFrame, data_source: str) -> gpd.GeoDataFrame:
    """
    Übersetzt TILDA-Attribute in RVN-Attribute basierend auf den Mapping-Regeln.
    
    Args:
        gdf: GeoDataFrame mit TILDA-Daten
        data_source: Art der Daten ("bikelanes", "streets", "paths")
    
    Returns:
        GeoDataFrame mit RVN-Attributen
    """
    logging.info(f"Übersetze {len(gdf)} Features vom Typ '{data_source}'")

    result_gdf = gdf.copy()
    if data_source == "bikelanes":
        result_gdf = lane_implicit_oneway_to_yes(result_gdf)

    # Zähler für nicht-gefundene Zuordnungen
    not_found_counts = {
        "fuehr": 0,
        "ofm": 0,
        "protek": 0
    }
    
    total = len(result_gdf)
    show_progress = sys.stdout.isatty()

    for idx, (_, row) in enumerate(result_gdf.iterrows(), 1):
        # Verkehrsrichtung (Radverkehr)
        verkehrsri = determine_verkehrsri(row, data_source)
        result_gdf.loc[result_gdf.index[idx-1], "verkehrsri"] = verkehrsri
        
        # Art der Radverkehrsführung
        fuehr = determine_fuehrung(row, data_source)
        if fuehr == "NICHT-GEFUNDEN":
            not_found_counts["fuehr"] += 1
        result_gdf.loc[result_gdf.index[idx-1], "fuehr"] = fuehr
        
        # Benutzungspflicht
        pflicht = determine_pflicht(row, data_source)
        result_gdf.loc[result_gdf.index[idx-1], "pflicht"] = pflicht
        
        # Breite (width_effective falls vorhanden, sonst width)
        width_value = row.get("width_effective") if pd.notna(row.get("width_effective")) else row.get("width")
        breite = parse_width(width_value)
        result_gdf.loc[result_gdf.index[idx-1], "breite"] = breite
        
        # Oberflächenmaterial
        ofm = determine_ofm(row)
        if ofm == "NICHT-GEFUNDEN":
            not_found_counts["ofm"] += 1
        result_gdf.loc[result_gdf.index[idx-1], "ofm"] = ofm
        
        # Farbliche Beschichtung
        farbe = determine_farbe(row)
        result_gdf.loc[result_gdf.index[idx-1], "farbe"] = farbe
        
        # Physische Protektion
        protek = determine_protek(row)
        if protek == "NICHT-GEFUNDEN":
            not_found_counts["protek"] += 1
        result_gdf.loc[result_gdf.index[idx-1], "protek"] = protek
        
        # Sicherheitstrennstreifen
        trennstreifen = determine_trennstreifen(row)
        result_gdf.loc[result_gdf.index[idx-1], "trennstreifen"] = trennstreifen
        
        # Nutzungsbeschränkung (berücksichtigt die bereits bestimmte Führung)
        nutz_beschr = combine_nutz_beschr(determine_nutz_beschr(row, fuehr), cycling_restriction(row))
        result_gdf.loc[result_gdf.index[idx-1], "nutz_beschr"] = nutz_beschr
        
        # Länge berechnen (gerundet, ohne Nachkommastellen)
        length = int(round(calculate_segment_length(row.geometry)))
        result_gdf.loc[result_gdf.index[idx-1], "Länge"] = length
        
        # Kommentar (NACH allen anderen Attributen, um TODO-Attribute zu erkennen)
        # Erstelle eine temporäre Row mit allen übersetzten Attributen
        translated_row = result_gdf.loc[result_gdf.index[idx-1]]
        kommentar = determine_kommentar(row, translated_row)
        result_gdf.loc[result_gdf.index[idx-1], "Kommentar"] = kommentar
        
        # Fortschrittsanzeige nur im Terminal; in eine Log-Datei würde jede Zeile ein Balken
        if show_progress:
            print_progressbar(idx, total, prefix=f"Übersetze {data_source}: ")
    
    # Logge Statistiken über nicht-gefundene Zuordnungen
    for attr, count in not_found_counts.items():
        if count > 0:
            percentage = (count / total) * 100
            logging.warning(f"{count} von {total} Features ({percentage:.1f}%) haben keine Zuordnung für '{attr}'")
    
    # Prüfe und logge die Längenberechnung
    if 'Länge' in result_gdf.columns:
        total_length = result_gdf['Länge'].sum()
        avg_length = result_gdf['Länge'].mean()
        logging.info(f"Längenstatistiken für {data_source}: Gesamtlänge={total_length:.0f}m, Durchschnitt={avg_length:.0f}m")
    
    # Höchstgeschwindigkeit der Fahrbahn (surface/smoothness bleiben als Rohwerte stehen)
    result_gdf = add_maxspeed_attributes(result_gdf, data_source)
    
    # Füge tilda_ Prefix zu ursprünglichen Attributen hinzu
    result_gdf = assign_prefix_and_remove_unnecessary_attrs(result_gdf)
    
    logging.info(f"✔ Übersetzung für {data_source} abgeschlossen")
    
    return result_gdf


# ============================================================ Routing-Netz ==

def join_source_attributes(routing: gpd.GeoDataFrame, raw_dir: Path, max_missing_share: float) -> tuple[gpd.GeoDataFrame, dict]:
    """Hängt an jede Routing-Kante die Attribute ihres Quellobjekts an.

    Routing-Attribute behalten das Präfix `routing_`. Fehlt das Quellobjekt, werden
    gleichnamige Routing-Attribute als Ersatz übernommen.
    """
    routing = routing.rename(columns={c: f"routing_{c}" for c in routing.columns if c != "geometry"})
    parts, stats = [], {}
    for source_table, (filename, _) in SOURCES.items():
        src = pyogrio.read_dataframe(raw_dir / filename, read_geometry=False)
        if src["id"].duplicated().any():
            raise ValueError(f"{filename}: `id` ist nicht eindeutig")
        sub = routing[routing["routing_source_table"] == source_table]
        joined = sub.merge(src, how="left", left_on="routing_source_id", right_on="id", indicator=True)
        missing = joined["_merge"] == "left_only"
        length = joined["routing_length"].astype(float)
        stats[source_table] = {
            "kanten": int(len(joined)),
            "ohne_quellobjekt": int(missing.sum()),
            "ohne_quellobjekt_km": round(float(length[missing].sum()) / 1000, 1),
            "beispiele": joined.loc[missing, "routing_source_id"].head(5).tolist(),
        }
        share = missing.mean() if len(joined) else 0.0
        if share > max_missing_share:
            raise ValueError(
                f"{source_table}: {share:.1%} der Kanten ohne Quellobjekt in {filename}. "
                "Stammen Routing- und Quelldaten aus demselben Verarbeitungslauf?"
            )
        if missing.any():
            logging.warning(f"{source_table}: {missing.sum()} Kanten ohne Quellobjekt, nutze Routing-Attribute als Ersatz")
            joined.loc[missing, "id"] = joined.loc[missing, "routing_source_id"]
            for col in src.columns:
                if f"routing_{col}" in joined.columns:
                    joined.loc[missing, col] = joined.loc[missing, f"routing_{col}"]
        # Wege/Straßen ohne `oneway`-Tag: Das Routing-`oneway` sagt, ob gegen die Linie gefahren werden darf.
        joined["oneway"] = joined["oneway"].fillna(joined["routing_oneway"]) if "oneway" in joined else joined["routing_oneway"]
        parts.append(joined.drop(columns="_merge"))
    out = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), geometry="geometry", crs=routing.crs)
    return out, stats


def split_at_shared_vertices(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Teilt jeden Weg an Stützpunkten, die Knoten sind (Endpunkt oder von mehreren Wegen genutzt)."""
    keyed = [[tuple(p) for p in np.round(np.asarray(g.coords), COORD_DECIMALS)] for g in gdf.geometry]
    usage: dict[tuple, int] = {}
    for coords in keyed:
        for p in set(coords):
            usage[p] = usage.get(p, 0) + 1
        for p in (coords[0], coords[-1]):
            usage[p] = usage.get(p, 0) + 1  # Endpunkte sind immer Knoten
    node_id: dict[tuple, int] = {}

    def node(p: tuple) -> int:
        return node_id.setdefault(p, len(node_id))

    rows, geoms = [], []
    for i, (coords, geom) in enumerate(zip(keyed, gdf.geometry)):
        raw = np.asarray(geom.coords)
        start, seg = 0, 0
        for j in range(1, len(coords)):
            if j == len(coords) - 1 or usage[coords[j]] > 1:
                if coords[start] != coords[j] or j - start > 1:
                    rows.append((i, seg, node(coords[start]), node(coords[j])))
                    geoms.append(LineString(raw[start : j + 1]))
                    seg += 1
                start = j
    idx, seg_idx, from_node, to_node = map(np.asarray, zip(*rows))
    out = gdf.iloc[idx].reset_index(drop=True)
    out["seg_idx"], out["from_node"], out["to_node"] = seg_idx, from_node, to_node
    return gpd.GeoDataFrame(out, geometry=geoms, crs=gdf.crs)


def main_component(segments: gpd.GeoDataFrame) -> np.ndarray:
    """Maske der Kanten in der größten zusammenhängenden Komponente (nach Länge)."""
    graph = nx.Graph()
    graph.add_edges_from(zip(segments["from_node"], segments["to_node"]))
    comp_of = {n: c for c, nodes in enumerate(nx.connected_components(graph)) for n in nodes}
    comp = segments["from_node"].map(comp_of)
    largest = segments["_len_m"].groupby(comp).sum().idxmax()
    return (comp == largest).to_numpy()


def main():
    parser = argparse.ArgumentParser(description="Bereitet den TILDA-Routing-Datensatz für das Map-Matching vor")
    parser.add_argument("--routing", default="data/TILDA Routing Berlin.gpkg")
    parser.add_argument("--raw-dir", default="data-raw-tilda", help="Exporte bikelanes/roads/roadsPathClasses")
    parser.add_argument("--data-dir", default="data", help="enthält das RVN für den Puffer-Zuschnitt")
    parser.add_argument("--output-dir", help="Standard: output/TILDA-routing bzw. output/TILDA-routing-ren (--netz ren)")
    parser.add_argument("--max-missing-share", type=float, default=0.01, help="max. Anteil Kanten ohne Quellobjekt je Tabelle")
    parser.add_argument("--min-bikelane-share", type=float, default=0.95, help="min. Anteil Radinfrastruktur (km) im Hauptnetz")
    parser.add_argument("--ohne-rvn-zuschnitt", action="store_true", help="ganz Berlin behalten (bei --netz ren immer)")
    add_netz_argument(parser)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    out_dir = Path(args.output_dir or TILDA_ROUTING_DIR[args.netz])
    out_dir.mkdir(parents=True, exist_ok=True)

    routing = gpd.read_file(args.routing)
    logging.info(f"Routing: {len(routing)} Kanten aus {args.routing}")
    joined, join_stats = join_source_attributes(routing, Path(args.raw_dir), args.max_missing_share)

    segments = split_at_shared_vertices(joined)
    segments["_len_m"] = segments.to_crs(DEFAULT_CRS).length
    logging.info(f"Topologie: {len(joined)} Wege -> {len(segments)} Kanten zwischen Knoten")

    in_main = main_component(segments)
    km = segments.groupby(["routing_source_table", in_main])["_len_m"].sum() / 1000
    topo_stats = {
        st: {"hauptnetz_km": round(float(km.get((st, True), 0)), 1), "ausserhalb_km": round(float(km.get((st, False), 0)), 1)}
        for st in SOURCES
    }
    bike = topo_stats["bikelanes"]
    bike_share = bike["hauptnetz_km"] / max(bike["hauptnetz_km"] + bike["ausserhalb_km"], 1e-9)
    logging.info(f"Hauptnetz: {json.dumps(topo_stats)}; Radinfrastruktur im Hauptnetz: {bike_share:.1%}")
    outside = segments.loc[~in_main, ["routing_id", "routing_source_table", "category", "road", "seg_idx", "_len_m", "geometry"]]
    outside.to_file(out_dir / "ausserhalb_hauptnetz.fgb", driver="FlatGeobuf")
    if bike_share < args.min_bikelane_share:
        raise SystemExit(f"Nur {bike_share:.1%} der Radinfrastruktur im Hauptnetz (min. {args.min_bikelane_share:.0%}). Abbruch.")

    segments = segments[in_main].to_crs(DEFAULT_CRS)
    if args.netz == "rvn" and not args.ohne_rvn_zuschnitt:
        segments = clip_to_rvn_buffer(segments, args.data_dir, DEFAULT_CRS)
    segments = segments.drop(columns="_len_m")
    for source_table, (_, data_source) in SOURCES.items():
        part = segments[segments["routing_source_table"] == source_table].reset_index(drop=True)
        translated = translate_tilda_attributes(part, data_source)
        # Präfix-Doppelung aus der Übersetzung rückgängig machen (routing_* -> tilda_routing_*)
        translated = translated.rename(columns=lambda c: c.removeprefix("tilda_") if c.startswith("tilda_routing_") else c)
        translated = translated.rename(columns={"tilda_seg_idx": "seg_idx", "tilda_from_node": "from_node", "tilda_to_node": "to_node"})
        path = out_dir / f"TILDA Routing {data_source.title()} Translated.fgb"
        path.unlink(missing_ok=True)
        translated.to_file(path, driver="FlatGeobuf")
        logging.info(f"✔ {path} ({len(translated)} Kanten)")

    report = {"join": join_stats, "topologie": topo_stats, "radinfrastruktur_im_hauptnetz": round(bike_share, 4)}
    (out_dir / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
