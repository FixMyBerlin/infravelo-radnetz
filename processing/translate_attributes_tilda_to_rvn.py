#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
translate_attributes_tilda_to_rvn.py
-----------------------------------
Übersetzt TILDA-Attribute in RVN-Attribute basierend auf den Mapping-Regeln.
Verarbeitet TILDA Radwege Berlin.fgb, TILDA Straßen Berlin.fgb und TILDA Wege Berlin.fgb.
"""

import argparse
import logging
import os
import geopandas as gpd
from helpers.globals import DEFAULT_CRS
from helpers.progressbar import print_progressbar
from helpers.traffic_signs import has_traffic_sign
from helpers.width_parser import parse_width


# --------------------------------------------------------- Konstanten --
# Eingabedateien im data/ Ordner
INPUT_FILES = {
    "bikelanes": "TILDA Radwege Berlin.fgb",
    "streets": "TILDA Straßen Berlin.fgb", 
    "paths": "TILDA Wege Berlin.fgb"
}
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
    "gravel": "Ungebunden"
}

# Mappings für physische Protektion (PROTEK)
MAPPING_PROTEK_SEPARATION = {
    "bollard": "Poller (auf Sperrfläche)",
    "bump": "Schwellen (auf Sperrfläche)",
    "vertical_panel": "Leitboys (flexibel, auf Breitstrich, ohne Sperrfläche)",
    "planter": "Sonstige (z.B. Pflanzkübel, Leitplanke)",
    "guard_rail": "Sonstige (z.B. Pflanzkübel, Leitplanke)",
    "no": "Ohne"
}

# Traffic Signs für Benutzungspflicht
TRAFFIC_SIGNS_PFLICHT = ["237", "240", "241"]

# Traffic Signs für Nutzungsbeschränkungen
TRAFFIC_SIGNS_NUTZ_BESCHR = ["Gehwegschäden", "Radwegschäden", "Geh- und Radwegschäden"]

# Liste der zu entfernenden Attribute (ohne tilda-Prefix)
# Enthält sowohl Attribute von Bikelanes, Roads und Paths
CONFIG_REMOVE_TILDA_ATTRIBUTES = [
    "lit", "description", "maxspeed_name_ref", "maxspeed_confidence", "maxspeed_conditional", "maxspeed_source", "mapillary_coverage", "mapillary", "bridge", "tunnel", "mapillary_traffic_sign", "mapillary_backward", "mapillary_forward", "todos",
    "updated_age", "updated_at", "width_source", "surface_confidence", "surface_source", "smoothness_confidence", "smoothness_source", "length", "offset", "_parent_highway"
]


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
            return "[TODO] Vermutlich nein"
        elif oneway == "implicit_yes":
            return "[TODO] Vermutlich Einrichtungsverkehr"
        elif not oneway or oneway in ["None", "none"]:
            # Fehlende Werte
            return "[TODO] Fehlender Wert"
        else:
            logging.warning(f"Unbekannter oneway-Wert für bikelanes: {oneway}, osm_id={row.get('osm_id', 'unbekannt')}")
            return "[TODO] Fehlerhafter Wert"
    
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
            return "[TODO] Fehlerhafter Wert"
    
    # Fallback
    logging.warning(f"Unbekannter data_source für verkehrsri: {data_source}")
    return "[TODO] Fehlerhafter Wert"


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
        return "Radweg"
    elif category.startswith("footwayBicycleYes"):
        # Prüfe auf Zusatzzeichen "Radverkehr frei" (Z239 mit Z1022-10)
        if has_traffic_sign(traffic_sign, "239") and has_traffic_sign(traffic_sign, "1022-10"):
            return "Gehweg mit Zusatzzeichen \"Radverkehr frei\" (Z239 mit Z1022-10)"
        # Falls kein traffic_sign vorhanden, als Sonstige Wege klassifizieren
        elif traffic_sign.strip() in ["none", "nan"]:
            return "Sonstige Wege (Gehwege, Wege durch Grünflächen, Plätze)"
        else:
            return "[TODO] Gehweg ohne Verkehrszeichen"
    elif (category == "pedestrianAreaBicycleYes" and 
          (has_traffic_sign(traffic_sign, "242") or has_traffic_sign(traffic_sign, "242.1")) and
          has_traffic_sign(traffic_sign, "1022-10")):
        return "Fußgängerzone \"Radverkehr frei\" (Z242 mit Z1022-10)"
    elif category == "crossing":
        return "[TODO] Kreuzungs-Querung"
    elif category == "needsClarification":
        return "[TODO] Klärung notwendig"
    
    logging.warning(f"Keine Führung gefunden für category={category}, traffic_sign={traffic_sign}, osm_id={row.get('osm_id', 'unbekannt')}")
    return "[TODO] Führung fehlt"


def determine_pflicht(row, data_source: str) -> bool:
    """
    Bestimmt die Benutzungspflicht basierend auf Verkehrszeichen.
    
    Args:
        row: Datenzeile mit OSM-Attributen
        data_source: Art der Daten ("bikelanes", "streets", "paths")
    
    Returns:
        True wenn Benutzungspflicht vorliegt
    """
    if data_source in ["streets", "paths"]:
        return False  # Immer "Nein" für streets und paths
    
    traffic_sign = str(row.get("traffic_sign", ""))
    
    # Prüfe auf Benutzungspflicht-Zeichen (Z237, Z240, Z241)
    for sign in TRAFFIC_SIGNS_PFLICHT:
        if has_traffic_sign(traffic_sign, sign):
            return True
    
    return False


def determine_ofm(row) -> str:
    """
    Bestimmt das Oberflächenmaterial basierend auf surface-Attribut.
    
    Args:
        row: Datenzeile mit OSM-Attributen
    
    Returns:
        Oberflächenmaterial-Kategorie oder "NICHT-GEFUNDEN"
    """
    surface = str(row.get("surface", "")).strip().lower()
    
    if not surface or surface == "nan":
        return "NICHT-GEFUNDEN"
    
    # Prüfe Mappings
    if surface in MAPPING_OFM_SURFACE:
        return MAPPING_OFM_SURFACE[surface]
    elif surface=="grass_paver" or surface=="wood" or surface=="metal" or surface=="paved":
        return "[TODO] Nicht zuordenbar"
    elif surface=="none":
        return "[TODO] Oberfläche Fehlt"
    
    # Logge unbekannte surface-Werte
    logging.warning(f"Unbekannter surface-Wert: {surface}")
    return "NICHT-GEFUNDEN"


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
    return "[TODO] Protektionstyp fehlt"


def determine_trennstreifen(row) -> str:
    """
    Bestimmt das Vorhandensein eines Sicherheitstrennstreifens (nur rechte Seite relevant).

    Args:
        row: Datenzeile mit OSM-Attributen

    Returns:
        "ja", "nein" oder "entfällt"
    """
    category = str(row.get("category", "")).strip().lower()

    # Für Fahrradstraßen beide Seiten prüfen
    # TODO Überlegen - was ist mit dem Fall nur auf einer Seite parkende Autos?
    if category.startswith("bicycleroad"):
        for side in ["left", "right"]:
            traffic_mode = str(row.get(f"traffic_mode_{side}", "")).strip().lower()
            markings = str(row.get(f"marking_{side}", "")).strip().lower()
            is_parking = traffic_mode == "parking"
            if ("dashed_line" in markings or "solid_line" in markings) and is_parking:
                return "ja"
        # Falls kein Sicherheitstrennstreifen auf beiden Seiten
        if not (str(row.get("traffic_mode_left", "")).strip().lower() == "parking" or
                str(row.get("traffic_mode_right", "")).strip().lower() == "parking"):
            return "entfällt"
        return "nein"

    # TODO Dies sollte für Radfahrstreifen und Schutzstreifen gelten ???
    # Nur rechte Seite prüfen
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

    # Bei markings_right=dashed_line oder solid_line UND parking vorhanden UND buffer_right >= 0.6
    # TODO Markings should also be checked for "dashed_line" or "solid_line"
    if is_parking_right and buffer_right_val is not None and buffer_right_val >= 0.6:
        return "ja"

    return "nein"


def determine_nutz_beschr(row) -> str:
    """
    Bestimmt Nutzungsbeschränkungen aufgrund baulicher Mängel.
    
    Args:
        row: Datenzeile mit OSM-Attributen
    
    Returns:
        Nutzungsbeschränkung oder "keine"
    """
    traffic_sign = str(row.get("traffic_sign", ""))
    
    # Prüfe auf Schadensschilder
    for sign in TRAFFIC_SIGNS_NUTZ_BESCHR:
        if sign in traffic_sign:
            return "Schadensschild/StVO Zusatzeichen (Straßenschäden, Gehwegschäden, Radwegschäden)"
    
    # TODO: Physische Sperre (Absperrschranke Z600) - noch nicht implementiert
    
    return "keine"


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
    
    # Liste der neuen RVN-Attribute, die nicht umbenannt werden sollen
    rvn_attributes = ["pflicht", "breite", "ofm", "farbe", "protek", "trennstreifen", "nutz_beschr", 
                     "fuehr", "verkehrsri"]
    
    # Erstelle Mapping für Umbenennung
    rename_mapping = {}
    for col in gdf.columns:
        if col not in rvn_attributes and col != "geometry":
            rename_mapping[col] = f"tilda_{col}"
    
    return gdf.rename(columns=rename_mapping)


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
        
        # Nutzungsbeschränkung
        nutz_beschr = determine_nutz_beschr(row)
        result_gdf.loc[result_gdf.index[idx-1], "nutz_beschr"] = nutz_beschr
        
        # Fortschrittsanzeige
        print_progressbar(idx, total, prefix=f"Übersetze {data_source}: ")
    
    # Logge Statistiken über nicht-gefundene Zuordnungen
    for attr, count in not_found_counts.items():
        if count > 0:
            percentage = (count / total) * 100
            logging.warning(f"{count} von {total} Features ({percentage:.1f}%) haben keine Zuordnung für '{attr}'")
    
    # Füge tilda_ Prefix zu ursprünglichen Attributen hinzu
    result_gdf = assign_prefix_and_remove_unnecessary_attrs(result_gdf)
    
    logging.info(f"✔ Übersetzung für {data_source} abgeschlossen")
    
    return result_gdf


def process_file(input_file: str, data_source: str, output_dir: str, crs: str, clip_neukoelln: bool = False, data_dir: str = "./data") -> None:
    """
    Verarbeitet eine einzelne TILDA-Datei.
    
    Args:
        input_file: Pfad zur Eingabedatei
        data_source: Art der Daten ("bikelanes", "streets", "paths")
        output_dir: Ausgabeverzeichnis
        crs: Ziel-Koordinatensystem
        clip_neukoelln: Ob auf Neukölln zugeschnitten werden soll
        data_dir: Verzeichnis mit den Eingabedateien
    """
    logging.info(f"Verarbeite {input_file} als {data_source}")
    
    # Lade Daten
    gdf = gpd.read_file(input_file).to_crs(crs)
    logging.info(f"Geladen: {len(gdf)} Features")
    
    # Optional: Auf Neukölln zuschneiden
    if clip_neukoelln:
        gdf = clip_to_neukoelln(gdf, data_dir, crs)
    
    # Übersetze Attribute
    translated_gdf = translate_tilda_attributes(gdf, data_source)

    # Sortiere die Spalten alphabetisch, geometry ans Ende
    cols = [col for col in translated_gdf.columns if col != "geometry"]
    sorted_cols = sorted(cols) + ["geometry"]
    translated_gdf = translated_gdf[sorted_cols]

    # Speichere Ergebnis
    filename_suffix = " Neukoelln" if clip_neukoelln else ""
    output_file = os.path.join(output_dir, f"TILDA {data_source.title()}{filename_suffix} Translated.fgb")
    os.makedirs(output_dir, exist_ok=True)
    translated_gdf.to_file(output_file, driver="FlatGeobuf")
    
    logging.info(f"✔ Gespeichert: {output_file} ({len(translated_gdf)} Features)")


def clip_to_neukoelln(gdf: gpd.GeoDataFrame, data_dir: str, crs: str) -> gpd.GeoDataFrame:
    """
    Schneidet die Geodaten auf die Grenzen von Neukölln zu.
    Basierend auf clip_bikelanes.py.
    
    Args:
        gdf: GeoDataFrame mit den zu zuschneidenden Daten
        data_dir: Verzeichnis mit den Eingabedateien
        crs: Ziel-Koordinatensystem
    
    Returns:
        Zugeschnittenes GeoDataFrame
    """
    
    # Pfad zur Neukölln-Grenzendatei
    boundary_path = os.path.join(data_dir, INPUT_NEUKOELLN_BOUNDARY_FILE)
    
    if not os.path.exists(boundary_path):
        logging.warning(f"Neukölln-Grenzendatei nicht gefunden: {boundary_path}")
        logging.warning("Überspringe Clipping - verwende vollständige Daten")
        return gdf
    
    try:
        logging.info(f"Lade Neukölln-Grenzen: {boundary_path}")
        clip_polygons = gpd.read_file(boundary_path)
        
        # Koordinatensystem vereinheitlichen
        if gdf.crs != clip_polygons.crs:
            logging.info("Transformiere Koordinatensystem für Clipping")
            gdf = gdf.to_crs(clip_polygons.crs)
        
        # Fasse alle Polygone zu einer einzigen Geometrie zusammen
        logging.info("Schneide Daten auf Neukölln zu")
        clip_boundary = clip_polygons.unary_union
        
        # Führe den Zuschnitt durch
        clipped_gdf = gdf.clip(clip_boundary)
        
        # Zurück zum gewünschten CRS
        if clipped_gdf.crs != crs:
            clipped_gdf = clipped_gdf.to_crs(crs)
        
        logging.info(f"Clipping abgeschlossen: {len(gdf)} → {len(clipped_gdf)} Features")
        return clipped_gdf
        
    except Exception as e:
        logging.error(f"Fehler beim Clipping: {e}")
        logging.warning("Überspringe Clipping - verwende vollständige Daten")
        return gdf


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
    parser.add_argument("--clip-neukoelln", action="store_true",
                       help="Schneide Daten auf Neukölln zu (optional)")
    
    args = parser.parse_args()
    
    logging.info("Starte TILDA-zu-RVN Attributübersetzung")
    if args.clip_neukoelln:
        logging.info("Clipping auf Neukölln aktiviert")
    
    # Verarbeite alle Eingabedateien
    for data_source, filename in INPUT_FILES.items():
        input_path = os.path.join(args.data_dir, filename)
        
        if not os.path.exists(input_path):
            logging.warning(f"Datei nicht gefunden: {input_path}")
            continue
        
        try:
            process_file(input_path, data_source, args.output_dir, args.crs, args.clip_neukoelln, args.data_dir)
        except Exception as e:
            logging.error(f"Fehler beim Verarbeiten von {input_path}: {e}")
            continue
    
    logging.info("✔ TILDA-zu-RVN Attributübersetzung abgeschlossen")


if __name__ == "__main__":
    main()
