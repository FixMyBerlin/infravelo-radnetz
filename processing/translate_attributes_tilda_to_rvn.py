#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
translate_attributes_tilda_to_rvn.py
-----------------------------------
Übersetzt TILDA-Attribute in RVN-Attribute basierend auf den Mapping-Regeln.
Verarbeitet bikelanes.fgb, TILDA Straßen Berlin.fgb und TILDA Wege Berlin.fgb.
"""

import argparse
import logging
import os
import pandas as pd
import geopandas as gpd
from helpers.globals import DEFAULT_CRS
from helpers.progressbar import print_progressbar
from helpers.traffic_signs import has_traffic_sign


# --------------------------------------------------------- Konstanten --
# Eingabedateien im data/ Ordner
INPUT_FILES = {
    "bikelanes": "bikelanes.fgb",
    "streets": "TILDA Straßen Berlin.fgb", 
    "paths": "TILDA Wege Berlin.fgb"
}

# Ausgabeverzeichnis
OUTPUT_DIR = "./output/TILDA-translated"

# Mappings für Oberflächenmaterial (OFM)
OFM_SURFACE_MAPPING = {
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
    "gravel": "Ungebunden"
}

# Mappings für physische Protektion (PROTEK)
PROTEK_SEPARATION_MAPPING = {
    "bollard": "Poller (auf Sperrfläche)",
    "bump": "Schwellen (auf Sperrfläche)",
    "vertical_panel": "Leitboys (flexibel, auf Breitstrich, ohne Sperrfläche)",
    "planter": "Sonstige (z.B. Pflanzkübel, Leitplanke)",
    "guard_rail": "Sonstige (z.B. Pflanzkübel, Leitplanke)",
    "no": "Ohne"
}

# Traffic Signs für Benutzungspflicht
PFLICHT_TRAFFIC_SIGNS = ["237", "240", "241"]

# Traffic Signs für Nutzungsbeschränkungen
NUTZ_BESCHR_TRAFFIC_SIGNS = ["Gehwegschäden", "Radwegschäden", "Geh- und Radwegschäden"]


# --------------------------------------------------------- Hilfsfunktionen --
def parse_width(width_value) -> float:
    """
    Wandelt OSM-Breitenangaben in standardisierte Meter-Werte um.
    Rundet auf 0,10 m-Stellen und gibt das Ergebnis als Float zurück.
    Übernommen aus start_snapping.py
    
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


def determine_fuehrung(row, data_type: str) -> str:
    """
    Bestimmt die Art der Radverkehrsführung basierend auf category und traffic_sign.
    
    Args:
        row: Datenzeile mit OSM-Attributen
        data_type: Art der Daten ("bikelanes", "streets", "paths")
    
    Returns:
        Radverkehrsführungstyp oder "NICHT-GEFUNDEN"
    """
    if data_type == "streets":
        return "Mischverkehr mit motorisiertem Verkehr"
    elif data_type == "paths":
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
    elif category == "sharedBusLaneBusWithBike":
        return "Bussonderfahrstreifen mit Radverkehr frei (Z245 mit Z1022-10)"
    elif (category.startswith("footwayBicycleYes") and 
          has_traffic_sign(traffic_sign, "239") and 
          has_traffic_sign(traffic_sign, "1022-10")):
        return "Gehweg mit Zusatzzeichen \"Radverkehr frei\" (Z239 mit Z1022-10)"
    elif (category == "pedestrianAreaBicycleYes" and 
          has_traffic_sign(traffic_sign, "242") and 
          has_traffic_sign(traffic_sign, "1022-10")):
        return "Fußgängerzone \"Radverkehr frei\" (Z242 mit Z1022-10)"
    elif category == "crossing":
        return "[TODO] Kreuzungs-Querung"
    elif category == "needsClarification":
        return "[TODO]Klärung notwendig"
    
    logging.warning(f"Keine Führung gefunden für category={category}, traffic_sign={traffic_sign}")
    return "NICHT-GEFUNDEN"


def determine_pflicht(row, data_type: str) -> bool:
    """
    Bestimmt die Benutzungspflicht basierend auf Verkehrszeichen.
    
    Args:
        row: Datenzeile mit OSM-Attributen
        data_type: Art der Daten ("bikelanes", "streets", "paths")
    
    Returns:
        True wenn Benutzungspflicht vorliegt
    """
    if data_type in ["streets", "paths"]:
        return False  # Immer "Nein" für streets und paths
    
    traffic_sign = str(row.get("traffic_sign", ""))
    
    # Prüfe auf Benutzungspflicht-Zeichen (Z237, Z240, Z241)
    for sign in PFLICHT_TRAFFIC_SIGNS:
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
    if surface in OFM_SURFACE_MAPPING:
        return OFM_SURFACE_MAPPING[surface]
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
        return "entfällt"
    
    # Prüfe verschiedene Separation-Attribute (left/right)
    for side in ["left", "right"]:
        separation = row.get(f"separation:{side}", "") or row.get("separation", "")
        traffic_mode = row.get(f"traffic_mode:{side}", "")
        markings = row.get(f"markings:{side}", "") or row.get("markings", "")
        buffer_val = row.get(f"buffer:{side}", "")
        
        separation_str = str(separation).strip().lower()
        
        # Ruhender Verkehr mit Sperrfläche
        if str(traffic_mode).strip().lower() == "parking" and "barred_area" in str(markings).lower():
            return "Ruhender Verkehr (mit Sperrfläche)"
        
        # Prüfe Separation-Mappings
        if separation_str in PROTEK_SEPARATION_MAPPING:
            return PROTEK_SEPARATION_MAPPING[separation_str]
        
        # Nur Sperrfläche
        if "barred_area" in str(markings).lower() and separation_str == "no":
            return "nur Sperrfläche"
    
    # TODO: Weitere komplexe Logik für Poller mit/ohne Sperrfläche
    logging.warning(f"Keine Protektion gefunden für Feature {row.get('osm_id', 'unbekannt')}")
    return "NICHT-GEFUNDEN"


def determine_trennstreifen(row) -> str:
    """
    Bestimmt das Vorhandensein eines Sicherheitstrennstreifens.
    
    Args:
        row: Datenzeile mit OSM-Attributen
    
    Returns:
        "ja", "nein" oder "entfällt"
    """
    # Prüfe für beide Seiten (left/right)
    for side in ["left", "right"]:
        traffic_mode = str(row.get(f"traffic_mode:{side}", "")).strip().lower()
        markings = str(row.get(f"markings:{side}", "")).strip().lower()
        buffer_val = row.get(f"buffer:{side}", "")
        cycleway_markings = str(row.get(f"cycleway:{side}:markings:{side}", "")).strip().lower()
        parking = str(row.get(f"parking:{side}", "")).strip().lower()
        
        # Kein rechtsseitig ruhender Verkehr
        if "no" in parking and side == "right":
            return "entfällt"
        
        # Bei cycleway:SIDE=lane: cycleway:SIDE:markings:right=dashed_line AND parking:right~=no
        if "dashed_line" in cycleway_markings and "no" not in parking:
            return "ja"
        
        # Bei bicycle_street=yes: markings:SIDE=dashed_line AND parking:SIDE~=no
        bicycle_street = str(row.get("bicycle_street", "")).strip().lower()
        if bicycle_street == "yes" and "dashed_line" in markings and "no" not in parking:
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
    for sign in NUTZ_BESCHR_TRAFFIC_SIGNS:
        if sign in traffic_sign:
            return "Schadensschild/StVO Zusatzeichen (Straßenschäden, Gehwegschäden, Radwegschäden)"
    
    # TODO: Physische Sperre (Absperrschranke Z600) - noch nicht implementiert
    
    return "keine"


def add_tilda_prefix(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Fügt den Prefix 'tilda_' zu allen ursprünglichen Attributen hinzu.
    
    Args:
        gdf: GeoDataFrame mit TILDA-Attributen
    
    Returns:
        GeoDataFrame mit umbenannten Spalten
    """
    # Liste der neuen RVN-Attribute, die nicht umbenannt werden sollen
    rvn_attributes = ["pflicht", "breite", "ofm", "farbe", "protek", "trennstreifen", "nutz_beschr", 
                     "fuehr", "bemerkung"]
    
    # Erstelle Mapping für Umbenennung
    rename_mapping = {}
    for col in gdf.columns:
        if col not in rvn_attributes and col != "geometry":
            rename_mapping[col] = f"tilda_{col}"
    
    return gdf.rename(columns=rename_mapping)


def translate_tilda_attributes(gdf: gpd.GeoDataFrame, data_type: str) -> gpd.GeoDataFrame:
    """
    Übersetzt TILDA-Attribute in RVN-Attribute basierend auf den Mapping-Regeln.
    
    Args:
        gdf: GeoDataFrame mit TILDA-Daten
        data_type: Art der Daten ("bikelanes", "streets", "paths")
    
    Returns:
        GeoDataFrame mit RVN-Attributen
    """
    logging.info(f"Übersetze {len(gdf)} Features vom Typ '{data_type}'")
    
    result_gdf = gdf.copy()
    
    # Zähler für nicht-gefundene Zuordnungen
    not_found_counts = {
        "fuehr": 0,
        "ofm": 0,
        "protek": 0
    }
    
    total = len(result_gdf)
    
    for idx, (_, row) in enumerate(result_gdf.iterrows(), 1):
        # Art der Radverkehrsführung
        fuehr = determine_fuehrung(row, data_type)
        if fuehr == "NICHT-GEFUNDEN":
            not_found_counts["fuehr"] += 1
        result_gdf.loc[result_gdf.index[idx-1], "fuehr"] = fuehr
        
        # Benutzungspflicht
        pflicht = determine_pflicht(row, data_type)
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
        
        # Bemerkung für temporäre Wege
        bemerkung = ""
        if str(row.get("temporary", "")).lower() == "yes":
            bemerkung = "Weg als temporärer Weg eingetragen; vermutlich Baustellen-Weg"
        result_gdf.loc[result_gdf.index[idx-1], "bemerkung"] = bemerkung
        
        # Fortschrittsanzeige
        print_progressbar(idx, total, prefix=f"Übersetze {data_type}: ")
    
    # Logge Statistiken über nicht-gefundene Zuordnungen
    for attr, count in not_found_counts.items():
        if count > 0:
            percentage = (count / total) * 100
            logging.warning(f"{count} von {total} Features ({percentage:.1f}%) haben keine Zuordnung für '{attr}'")
    
    # Füge tilda_ Prefix zu ursprünglichen Attributen hinzu
    result_gdf = add_tilda_prefix(result_gdf)
    
    logging.info(f"✔ Übersetzung für {data_type} abgeschlossen")
    
    return result_gdf


def process_file(input_file: str, data_type: str, output_dir: str, crs: str) -> None:
    """
    Verarbeitet eine einzelne TILDA-Datei.
    
    Args:
        input_file: Pfad zur Eingabedatei
        data_type: Art der Daten ("bikelanes", "streets", "paths")
        output_dir: Ausgabeverzeichnis
        crs: Ziel-Koordinatensystem
    """
    logging.info(f"Verarbeite {input_file} als {data_type}")
    
    # Lade Daten
    gdf = gpd.read_file(input_file).to_crs(crs)
    logging.info(f"Geladen: {len(gdf)} Features")
    
    # Übersetze Attribute
    translated_gdf = translate_tilda_attributes(gdf, data_type)
    
    # Speichere Ergebnis
    output_file = os.path.join(output_dir, f"TILDA {data_type.title()} Berlin.fgb")
    os.makedirs(output_dir, exist_ok=True)
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
                       help="Pfad zum Datenverzeichnis (default: ../data)")
    parser.add_argument("--output-dir", default=OUTPUT_DIR,
                       help=f"Ausgabeverzeichnis (default: {OUTPUT_DIR})")
    parser.add_argument("--crs", type=int, default=DEFAULT_CRS,
                       help=f"Ziel-EPSG (default: {DEFAULT_CRS})")
    
    args = parser.parse_args()
    
    logging.info("Starte TILDA-zu-RVN Attributübersetzung")
    
    # Verarbeite alle Eingabedateien
    for data_type, filename in INPUT_FILES.items():
        input_path = os.path.join(args.data_dir, filename)
        
        if not os.path.exists(input_path):
            logging.warning(f"Datei nicht gefunden: {input_path}")
            continue
        
        try:
            process_file(input_path, data_type, args.output_dir, args.crs)
        except Exception as e:
            logging.error(f"Fehler beim Verarbeiten von {input_path}: {e}")
            continue
    
    logging.info("✔ TILDA-zu-RVN Attributübersetzung abgeschlossen")


if __name__ == "__main__":
    main()
