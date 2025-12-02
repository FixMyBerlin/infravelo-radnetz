#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
translate_attributes_tilda_to_rvn.py
-----------------------------------
Übersetzt TILDA-Attribute in RVN-Attribute basierend auf den Mapping-Regeln.
Berechnet zusätzlich die Länge jedes Segments in Metern (gerundet, ohne Nachkommastellen).

INPUT: 
- data/TILDA Radwege Berlin.fgb
- data/TILDA Straßen Berlin.fgb
- data/TILDA Wege Berlin.fgb

OUTPUT:
- output/TILDA-translated/TILDA Bikelanes Translated.fgb
- output/TILDA-translated/TILDA Streets Translated.fgb
- output/TILDA-translated/TILDA Paths Translated.fgb
(Bei Neukölln-Clipping: Dateien mit " Neukoelln" Suffix)
"""

import argparse
import logging
import os
from pathlib import Path
from datetime import datetime
import geopandas as gpd
from helpers.globals import DEFAULT_CRS
from start_snapping import CONFIG_BUFFER_DEFAULT
from helpers.progressbar import print_progressbar
from helpers.traffic_signs import has_traffic_sign
from helpers.width_parser import parse_width
from helpers.construction_comments import collect_todo_attributes

# --------------------------------------------------------- Konstanten --
# Liste der neuen RVN-Attribute, die nicht umbenannt werden sollen
CONFIG_ATTRIBUTES_NOT_RENAMING = ["pflicht", "breite", "ofm", "farbe", "protek", "trennstreifen", "nutz_beschr", "fuehr", "verkehrsri", "Länge", "Kommentar"]

# Eingabedateien im data/ Ordner
INPUT_FILES = {
    "bikelanes": "TILDA Radwege Berlin.fgb",
    "streets": "TILDA Straßen Berlin.fgb", 
    "paths": "TILDA Wege Berlin.fgb"
}
# Radvorrangsnetz-Datei für Buffer-Clipping
INPUT_RVN_FILE = "Berlin Radvorrangsnetz.fgb"
# Neukölln Grenzendatei
INPUT_NEUKOELLN_BOUNDARY_FILE = "Bezirk Neukölln Grenze.fgb"

# Ausgabeverzeichnis
OUTPUT_DIR = "./output/TILDA-translated"

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
CONFIG_REMOVE_TILDA_ATTRIBUTES = [
    "lit", "description", "maxspeed_name_ref", "maxspeed_confidence", "maxspeed_conditional", "maxspeed_source", "mapillary_coverage",  "bridge", "tunnel", "todos", "updated_age", "updated_at", "surface_confidence", "surface_source", "smoothness_confidence", "smoothness_source", "length", "offset", "_parent_highway"
]

# RVN-Buffer Cache (wird einmal geladen und wiederverwendet)
_rvn_buffer_cache = None


def load_rvn_buffer(data_dir: str, crs: int, buffer_distance: float = CONFIG_BUFFER_DEFAULT) -> gpd.GeoDataFrame:
    """
    Lädt das Radvorrangsnetz und erstellt einen Buffer um alle Linien.
    Das Ergebnis wird gecached um mehrfaches Laden zu vermeiden.
    
    Args:
        data_dir: Verzeichnis mit den Eingabedateien
        crs: Ziel-Koordinatensystem
        buffer_distance: Puffergröße in Metern (default: CONFIG_BUFFER_DEFAULT)
    
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
    oneway = str(row.get("oneway", "")).strip()
    oneway_bicycle = str(row.get("oneway_bicycle", "")).strip()
    
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


def determine_kommentar(row, translated_row=None) -> str:
    """
    Bestimmt den Kommentar basierend auf dem lifecycle-Attribut und fehlenden Attributen.
    
    Wenn lifecycle=construction:
    - Hauptkommentar: "Derzeit Baustelle (Stand ...)"
    - Zusatzkommentare: Für jedes Attribut mit [TODO] oder fehlendem Wert (None, NaN, "")
      wird hinzugefügt: "{Attributname} Attribut fehlt aufgrund von Baustelle"
    
    Wenn lifecycle=temporary:
    - Hauptkommentar: "Temporäre Markierungen zum Erhebungszeitpunkt"
    - Zusatzkommentare: Für jedes Attribut mit [TODO] oder fehlendem Wert (None, NaN, "")
      wird hinzugefügt: "{Attributname} Attribut fehlt aufgrund von temporärer Infrastruktur"
    
    Args:
        row: Datenzeile mit OSM-Attributen
        translated_row: Optional - Datenzeile mit übersetzten RVN-Attributen (nach Translation)
    
    Returns:
        Kommentar oder None (null)
    """
    # TODO Umbennung in lifecycle
    lifecycle = str(row.get("lifecycle", "")).strip().lower()
    
    comments = []
    
    if lifecycle == "construction":
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
            todo_attrs = collect_todo_attributes(translated_row, CONFIG_ATTRIBUTES_NOT_RENAMING, include_missing=True)
            for attr in todo_attrs:
                # Kapitalisiere ersten Buchstaben des Attributnamens
                attr_display = attr.capitalize()
                comments.append(f"{attr_display} Attribut fehlt aufgrund von Baustelle")
    
    elif lifecycle == "temporary":
        comments.append("Temporäre Markierungen zum Erhebungszeitpunkt")
        
        # Zusatzkommentare: Fehlende Attribute aufgrund temporärer Infrastruktur
        if translated_row is not None:
            todo_attrs = collect_todo_attributes(translated_row, CONFIG_ATTRIBUTES_NOT_RENAMING, include_missing=True)
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


def calculate_segment_length(geometry):
    """
    Berechnet die Länge eines Segments in Metern.
    """
    return geometry.length


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
    
    # Zähler für nicht-gefundene Zuordnungen
    not_found_counts = {
        "fuehr": 0,
        "ofm": 0,
        "protek": 0
    }
    
    total = len(result_gdf)
    
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
        
        # Breite (direkt aus width übernommen)
        breite = parse_width(row.get("width"))
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
        nutz_beschr = determine_nutz_beschr(row, fuehr)
        result_gdf.loc[result_gdf.index[idx-1], "nutz_beschr"] = nutz_beschr
        
        # Länge berechnen (gerundet, ohne Nachkommastellen)
        length = int(round(calculate_segment_length(row.geometry)))
        result_gdf.loc[result_gdf.index[idx-1], "Länge"] = length
        
        # Kommentar (NACH allen anderen Attributen, um TODO-Attribute zu erkennen)
        # Erstelle eine temporäre Row mit allen übersetzten Attributen
        translated_row = result_gdf.loc[result_gdf.index[idx-1]]
        kommentar = determine_kommentar(row, translated_row)
        result_gdf.loc[result_gdf.index[idx-1], "Kommentar"] = kommentar
        
        # Fortschrittsanzeige
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
    
    # Füge tilda_ Prefix zu ursprünglichen Attributen hinzu
    result_gdf = assign_prefix_and_remove_unnecessary_attrs(result_gdf)
    
    logging.info(f"✔ Übersetzung für {data_source} abgeschlossen")
    
    return result_gdf


def process_file(input_file: str, data_source: str, output_dir: str, crs: str, clip_region: str = None, data_dir: str = "./data") -> None:
    """
    Verarbeitet eine einzelne TILDA-Datei.
    
    Args:
        input_file: Pfad zur Eingabedatei
        data_source: Art der Daten ("bikelanes", "streets", "paths")
        output_dir: Ausgabeverzeichnis
        crs: Ziel-Koordinatensystem
        clip_region: Regionale Beschränkung ('neukoelln', 'norden', 'sueden')
        data_dir: Verzeichnis mit den Eingabedateien
    """
    logging.info(f"Verarbeite {input_file} als {data_source}")
    
    # Lade Daten
    gdf = gpd.read_file(input_file).to_crs(crs)
    logging.info(f"Geladen: {len(gdf)} Features")
    
    # Standardmäßig: Auf RVN-Buffer zuschneiden (behält vollständige Linien die den Buffer berühren)
    gdf = clip_to_rvn_buffer(gdf, data_dir, crs)
    
    # Optional: Zusätzlich auf Region zuschneiden
    if clip_region:
        from helpers.clipping import clip_to_region
        gdf = clip_to_region(gdf, data_dir, crs, clip_region)
    
    # Übersetze Attribute
    translated_gdf = translate_tilda_attributes(gdf, data_source)

    # Sortiere die Spalten alphabetisch, geometry ans Ende
    cols = [col for col in translated_gdf.columns if col != "geometry"]
    sorted_cols = sorted(cols) + ["geometry"]
    translated_gdf = translated_gdf[sorted_cols]

    # Speichere Ergebnis
    filename_suffix = f" {clip_region.capitalize()}" if clip_region else ""
    output_file = os.path.join(output_dir, f"TILDA {data_source.title()}{filename_suffix} Translated.fgb")
    os.makedirs(output_dir, exist_ok=True)
    
    # Lösche existierende Ausgabedatei, um Write-Access-Fehler zu vermeiden
    Path(output_file).unlink(missing_ok=True)
    
    translated_gdf.to_file(output_file, driver="FlatGeobuf")
    
    logging.info(f"✔ Gespeichert: {output_file} ({len(translated_gdf)} Features)")


def main():
    """Hauptfunktion für die Kommandozeilenausführung."""
    # Logging konfigurieren
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s: %(message)s',
        datefmt='%H:%M:%S'
    )
    
    # Kommandozeilenargumente parsen
    parser = argparse.ArgumentParser(description="Übersetzt TILDA-Attribute in RVN-Attribute")
    parser.add_argument("--data-dir", default="./data", 
                       help="Pfad zum Datenverzeichnis (default: ./data)")
    parser.add_argument("--output-dir", default=OUTPUT_DIR,
                       help=f"Ausgabeverzeichnis (default: {OUTPUT_DIR})")
    parser.add_argument("--crs", type=int, default=DEFAULT_CRS,
                       help=f"Ziel-EPSG (default: {DEFAULT_CRS})")
    parser.add_argument("--clip", type=str, choices=['neukoelln', 'norden', 'sueden'],
                       help="Regionaler Zuschnitt: 'neukoelln', 'norden' oder 'sueden'")
    
    args = parser.parse_args()
    
    logging.info("Starte TILDA-zu-RVN Attributübersetzung")
    if args.clip:
        logging.info(f"Clipping auf {args.clip} aktiviert")
    
    # Verarbeite alle Eingabedateien
    for data_source, filename in INPUT_FILES.items():
        input_path = os.path.join(args.data_dir, filename)
        
        if not os.path.exists(input_path):
            logging.warning(f"Datei nicht gefunden: {input_path}")
            continue
        
        try:
            process_file(input_path, data_source, args.output_dir, args.crs, args.clip, args.data_dir)
        except Exception as e:
            logging.error(f"Fehler beim Verarbeiten von {input_path}: {e}")
            continue
    
    logging.info("✔ TILDA-zu-RVN Attributübersetzung abgeschlossen")


if __name__ == "__main__":
    main()
