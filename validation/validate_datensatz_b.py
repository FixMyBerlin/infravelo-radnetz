#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
validate_datensatz_b.py
--------------------------------------------------------------------
Überprüft Datensatz B (Radverkehrsanlagen) auf Fehler und Probleme.
Prüft auf NULL-Werte, TODO-Substring und weitere Auffälligkeiten in wichtigen Attributen.

INPUT:
- output/snapping_with_overrides.fgb (oder mit --clip: _neukoelln, _norden, _sueden)

OUTPUT:
- Konsolenausgabe mit Hinweisen und Warnungen zu gefundenen Problemen

USAGE:
- Gesamter Datensatz: python validate_datensatz_b.py
- Regionaler Zuschnitt: python validate_datensatz_b.py --clip neukoelln|norden|sueden
"""

import sys
import argparse
import logging
import geopandas as gpd
import pandas as pd
from pathlib import Path
from collections import Counter

# Import der Helper aus processing
sys.path.append(str(Path(__file__).parent.parent / 'processing'))
from helpers.globals import DEFAULT_CRS
from helpers.clipping import clip_to_region

# ANSI Farb-Codes
ORANGE = '\033[38;5;214m'
RED = '\033[91m'
RESET = '\033[0m'

# Logging konfigurieren
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ============================================================================
# KONFIGURATION: Zu validierende Attribute
# ============================================================================
# Diese Attribute werden auf NULL-Werte und "TODO"-Substring geprüft
ATTRIBUTES_TO_VALIDATE = [
    'fuehr',
    'verkehrsri',
    'protek',
    'trennstreifen',
    'nutz_beschr',
    'farbe',
    'breite',
    'pflicht',
    'strassenname',
    'Bezirksnummer',
    'Länge',
    'beginnt_bei_vp',
    'endet_bei_vp'
]

# Diese Attribute werden von der Validierung geprüft, führen aber NICHT zur 
# Aufnahme in die problematische Features Datei (--create-file)
# Nützlich für Attribute, die oft fehlen, aber nicht kritisch sind
ATTRIBUTES_EXCLUDED_FROM_FILE_CREATION = [
    'Bezirksnummer'
]


def load_converted_bikelanes(file_path):
    """
    Lade konvertierte Radverkehrsanlagen-Daten aus FlatGeobuf.
    
    Args:
        file_path: Pfad zur FlatGeobuf-Datei
        
    Returns:
        GeoDataFrame mit konvertierten Radverkehrsanlagen
    """
    logger.info(f"Lade Daten aus {file_path}")
    
    if not Path(file_path).exists():
        logger.error(f"{RED}❌ FEHLER: Datei nicht gefunden: {file_path}{RESET}")
        sys.exit(1)
    
    try:
        gdf = gpd.read_file(file_path)
        logger.info(f"Daten geladen: {len(gdf)} Features")
        return gdf
    except Exception as e:
        logger.error(f"{RED}❌ Fehler beim Laden der Daten: {e}{RESET}")
        sys.exit(1)


def validate_null_values(gdf, attributes):
    """
    Prüfe auf NULL-Werte in den angegebenen Attributen.
    
    Spezialbehandlung:
    - 'breite': Wird nur bei Führungsformen geprüft, die nicht "Mischverkehr mit motorisiertem Verkehr" sind.
    - 'Keine Radinfrastruktur vorhanden': Features mit dieser Führungsform werden komplett übersprungen,
      da hier NULL-Werte erwartet werden.
    
    Args:
        gdf: GeoDataFrame mit den Daten
        attributes: Liste der zu prüfenden Attributnamen
        
    Returns:
        True wenn keine NULL-Werte gefunden wurden, False sonst
    """
    logger.info("Prüfe auf NULL-Werte in den Attributen...")
    
    all_valid = True
    total_null_count = 0
    
    # Filtere Features ohne Radinfrastruktur aus (dort sind NULL-Werte erlaubt)
    if 'fuehr' in gdf.columns:
        keine_radinfra_mask = gdf['fuehr'] == 'Keine Radinfrastruktur vorhanden'
        gdf_to_validate = gdf[~keine_radinfra_mask]
        keine_radinfra_count = keine_radinfra_mask.sum()
        
        if keine_radinfra_count > 0:
            logger.info(f"→ {keine_radinfra_count} Features mit 'Keine Radinfrastruktur vorhanden' übersprungen (NULL-Werte erwartet)")
    else:
        gdf_to_validate = gdf
    
    for attr in attributes:
        # Prüfe, ob Attribut existiert
        if attr not in gdf_to_validate.columns:
            logger.warning(f"{ORANGE}⚠️ WARNUNG: Attribut '{attr}' nicht gefunden in den Daten!{RESET}")
            all_valid = False
            continue
        
        # Spezialbehandlung für 'breite': nur bei Nicht-Mischverkehr prüfen
        if attr == 'breite' and 'fuehr' in gdf_to_validate.columns:
            # Filtere nur Features, die nicht Mischverkehr sind
            nicht_mischverkehr_mask = gdf_to_validate['fuehr'] != 'Mischverkehr mit motorisiertem Verkehr'
            gdf_to_check = gdf_to_validate[nicht_mischverkehr_mask]
            
            null_mask = gdf_to_check[attr].isnull()
            null_count = null_mask.sum()
            
            if null_count > 0:
                all_valid = False
                total_null_count += null_count
                logger.warning(f"{ORANGE}⚠️ WARNUNG: Attribut '{attr}' hat {null_count} NULL-Werte (nur bei Nicht-Mischverkehr)!{RESET}")
                
                # Zeige erste Beispiele
                null_indices = gdf_to_check[null_mask].index[:5].tolist()
                logger.warning(f"  Beispiel-Indizes: {null_indices}")
                
                if null_count > 5:
                    logger.warning(f"  ... und {null_count - 5} weitere NULL-Werte")
            else:
                logger.info(f"✓ Attribut '{attr}': Keine NULL-Werte (bei {len(gdf_to_check)} Nicht-Mischverkehr-Features)")
            
            # Info über Mischverkehr-Features
            mischverkehr_count = (~nicht_mischverkehr_mask).sum()
            if mischverkehr_count > 0:
                logger.info(f"  → {mischverkehr_count} Mischverkehr-Features übersprungen")
        else:
            # Normale Prüfung für alle anderen Attribute
            null_mask = gdf_to_validate[attr].isnull()
            null_count = null_mask.sum()
            
            if null_count > 0:
                all_valid = False
                total_null_count += null_count
                logger.warning(f"{ORANGE}⚠️ WARNUNG: Attribut '{attr}' hat {null_count} NULL-Werte!{RESET}")
                
                # Zeige erste Beispiele
                null_indices = gdf_to_validate[null_mask].index[:5].tolist()
                logger.warning(f"  Beispiel-Indizes: {null_indices}")
                
                if null_count > 5:
                    logger.warning(f"  ... und {null_count - 5} weitere NULL-Werte")
            else:
                logger.info(f"✓ Attribut '{attr}': Keine NULL-Werte")
    
    if not all_valid:
        logger.warning("-" * 80)
        logger.warning(f"Gesamt: {total_null_count} NULL-Werte in {len([a for a in attributes if a in gdf_to_validate.columns])} Attributen gefunden")
    else:
        logger.info("✓ Keine NULL-Werte gefunden!")
    
    return all_valid


def validate_keine_radinfra_has_null_values(gdf):
    """
    Prüfe, ob Features mit 'Keine Radinfrastruktur vorhanden' erwartete NULL-Werte haben.
    
    Bei 'Keine Radinfrastruktur vorhanden' sollten folgende Attribute NULL sein:
    - verkehrsri, protek, trennstreifen, nutz_beschr, farbe, breite, pflicht
    
    Args:
        gdf: GeoDataFrame mit den Daten
        
    Returns:
        True wenn alle 'Keine Radinfrastruktur vorhanden' Features korrekte NULL-Werte haben, False sonst
    """
    logger.info("Prüfe ob 'Keine Radinfrastruktur vorhanden' korrekte NULL-Werte hat...")
    
    # Attribute die bei 'Keine Radinfrastruktur vorhanden' NULL sein sollten
    expected_null_attributes = [
        'verkehrsri',
        'protek',
        'trennstreifen',
        'nutz_beschr',
        'farbe',
        'breite',
        'pflicht'
    ]
    
    if 'fuehr' not in gdf.columns:
        logger.warning("{ORANGE}⚠️ WARNUNG: Attribut 'fuehr' nicht gefunden!{RESET}")
        return False
    
    # Filtere Features mit 'Keine Radinfrastruktur vorhanden'
    keine_radinfra_mask = gdf['fuehr'] == 'Keine Radinfrastruktur vorhanden'
    keine_radinfra_gdf = gdf[keine_radinfra_mask]
    
    if len(keine_radinfra_gdf) == 0:
        logger.info("✓ Keine Features mit 'Keine Radinfrastruktur vorhanden' gefunden - Validierung übersprungen")
        return True
    
    logger.info(f"  Analysiere {len(keine_radinfra_gdf)} Features mit 'Keine Radinfrastruktur vorhanden'...")
    
    all_valid = True
    total_non_null_count = 0
    
    for attr in expected_null_attributes:
        if attr not in keine_radinfra_gdf.columns:
            logger.warning(f"{ORANGE}⚠️ WARNUNG: Attribut '{attr}' nicht gefunden in den Daten!{RESET}")
            all_valid = False
            continue
        
        # Prüfe auf NICHT-NULL-Werte (diese sind problematisch)
        non_null_mask = keine_radinfra_gdf[attr].notnull()
        non_null_count = non_null_mask.sum()
        
        if non_null_count > 0:
            all_valid = False
            total_non_null_count += non_null_count
            logger.warning(f"{ORANGE}⚠️ WARNUNG: Attribut '{attr}' hat {non_null_count} NICHT-NULL-Werte bei 'Keine Radinfrastruktur vorhanden'!{RESET}")
            
            # Zeige erste Beispiele mit den Werten
            non_null_features = keine_radinfra_gdf[non_null_mask].head(5)
            for idx, row in non_null_features.iterrows():
                logger.warning(f"  Index {idx}: '{row[attr]}'")
            
            if non_null_count > 5:
                logger.warning(f"  ... und {non_null_count - 5} weitere Nicht-NULL-Werte")
        else:
            logger.info(f"✓ Attribut '{attr}': Alle Werte sind NULL (wie erwartet)")
    
    if not all_valid:
        logger.warning("-" * 80)
        logger.warning(f"Gesamt: {total_non_null_count} unerwartete Nicht-NULL-Werte bei 'Keine Radinfrastruktur vorhanden' gefunden")
    else:
        logger.info("✓ Alle 'Keine Radinfrastruktur vorhanden' Features haben korrekte NULL-Werte!")
    
    return all_valid


def validate_todo_values(gdf, attributes):
    """
    Prüfe auf "TODO"-Substring in den angegebenen Attributen.
    
    Überspringt Features mit 'Keine Radinfrastruktur vorhanden', da dort NULL-Werte erwartet werden.
    
    Args:
        gdf: GeoDataFrame mit den Daten
        attributes: Liste der zu prüfenden Attributnamen
        
    Returns:
        True wenn keine TODO-Werte gefunden wurden, False sonst
    """
    logger.info("Prüfe auf TODO-Substring in den Attributen...")
    
    # Filtere Features ohne Radinfrastruktur aus
    if 'fuehr' in gdf.columns:
        keine_radinfra_mask = gdf['fuehr'] == 'Keine Radinfrastruktur vorhanden'
        gdf_to_validate = gdf[~keine_radinfra_mask]
        keine_radinfra_count = keine_radinfra_mask.sum()
        
        if keine_radinfra_count > 0:
            logger.info(f"→ {keine_radinfra_count} Features mit 'Keine Radinfrastruktur vorhanden' übersprungen")
    else:
        gdf_to_validate = gdf
    all_valid = True
    total_todo_count = 0
    
    for attr in attributes:
        # Prüfe, ob Attribut existiert
        if attr not in gdf_to_validate.columns:
            # Bereits bei NULL-Prüfung gewarnt
            continue
        
        # Prüfe nur String-Spalten
        if gdf_to_validate[attr].dtype == 'object' or isinstance(gdf_to_validate[attr].iloc[0], str) if len(gdf_to_validate) > 0 else False:
            # Suche nach TODO (case-insensitive)
            todo_mask = gdf_to_validate[attr].astype(str).str.contains('TODO', case=False, na=False)
            todo_count = todo_mask.sum()
            
            if todo_count > 0:
                all_valid = False
                total_todo_count += todo_count
                logger.warning(f"{ORANGE}⚠️ WARNUNG: Attribut '{attr}' hat {todo_count} Einträge mit 'TODO'!{RESET}")
                
                # Zeige erste Beispiele mit den Werten
                todo_features = gdf_to_validate[todo_mask].head(5)
                for idx, row in todo_features.iterrows():
                    logger.warning(f"  Index {idx}: '{row[attr]}'")
                
                if todo_count > 5:
                    logger.warning(f"  ... und {todo_count - 5} weitere TODO-Einträge")
            else:
                logger.info(f"✓ Attribut '{attr}': Keine TODO-Werte")
        else:
            # Numerisches Attribut - überspringe TODO-Prüfung
            logger.info(f"✓ Attribut '{attr}': Numerisch (TODO-Prüfung übersprungen)")
    
    if not all_valid:
        logger.warning("-" * 80)
        logger.warning(f"Gesamt: {total_todo_count} TODO-Einträge gefunden")
    else:
        logger.info("✓ Keine TODO-Werte gefunden!")
    
    return all_valid


def validate_element_nr_unknown(gdf):
    """
    Prüfe, ob element_nr den Substring 'UNKNOWN' enthält.
    
    Args:
        gdf: GeoDataFrame mit den Daten
        
    Returns:
        True wenn keine UNKNOWN-Werte gefunden wurden, False sonst
    """
    logger.info("Prüfe auf UNKNOWN-Substring in element_nr...")
    
    if 'element_nr' not in gdf.columns:
        logger.warning("{ORANGE}⚠️ WARNUNG: Attribut 'element_nr' nicht gefunden!{RESET}")
        return False
    
    # Suche nach UNKNOWN (case-insensitive)
    unknown_mask = gdf['element_nr'].astype(str).str.contains('UNKNOWN', case=False, na=False)
    unknown_count = unknown_mask.sum()
    
    if unknown_count > 0:
        logger.warning(f"{ORANGE}⚠️ WARNUNG: element_nr hat {unknown_count} Einträge mit 'UNKNOWN'!{RESET}")
        
        # Zeige erste Beispiele mit den Werten
        unknown_features = gdf[unknown_mask].head(5)
        for idx, row in unknown_features.iterrows():
            logger.warning(f"  Index {idx}: '{row['element_nr']}'")
        
        if unknown_count > 5:
            logger.warning(f"  ... und {unknown_count - 5} weitere UNKNOWN-Einträge")
        
        return False
    
    logger.info("✓ Attribut 'element_nr': Keine UNKNOWN-Werte")
    return True


def validate_duplicate_tilda_id_for_opposite_directions(gdf):
    """
    Prüfe, ob bei Einrichtungsverkehr entgegengesetzte Kanten (ri=0 und ri=1) 
    die gleiche tilda_id haben. Das darf nicht sein, da jede Richtung eine 
    eigene TILDA-Quelle haben sollte.
    
    Beispiel-Problem: element_nr=53470054_53470052.02 mit verkehrsri="Einrichtungsverkehr"
    für ri=0 und ri=1, aber beide mit gleicher tilda_id.
    
    Args:
        gdf: GeoDataFrame mit den Daten
        
    Returns:
        True wenn keine Duplikate gefunden wurden, False sonst
    """
    logger.info("Prüfe auf doppelte tilda_id bei entgegengesetzten Einrichtungsverkehr-Kanten...")
    
    # Prüfe ob erforderliche Spalten existieren
    required_columns = ['element_nr', 'ri', 'verkehrsri', 'tilda_id']
    missing_columns = [col for col in required_columns if col not in gdf.columns]
    
    if missing_columns:
        logger.warning(f"{ORANGE}⚠️ WARNUNG: Fehlende Spalten für diese Validierung: {', '.join(missing_columns)}{RESET}")
        return True  # Keine Validierung möglich, aber kein Fehler
    
    # Filtere nur Einrichtungsverkehr-Features
    einrichtungsverkehr_mask = gdf['verkehrsri'] == 'Einrichtungsverkehr'
    einrichtungsverkehr_gdf = gdf[einrichtungsverkehr_mask].copy()
    
    if len(einrichtungsverkehr_gdf) == 0:
        logger.info("✓ Keine Einrichtungsverkehr-Features gefunden - Validierung übersprungen")
        return True
    
    logger.info(f"  Analysiere {len(einrichtungsverkehr_gdf)} Einrichtungsverkehr-Features...")
    
    # Gruppiere nach element_nr und sammle ri-Werte mit zugehörigen tilda_ids
    problematic_elements = []
    
    # Gruppiere nach element_nr
    grouped = einrichtungsverkehr_gdf.groupby('element_nr')
    
    for element_nr, group in grouped:
        # Prüfe ob beide Richtungen (ri=0 und ri=1) existieren
        ri_values = group['ri'].unique()
        
        if 0 in ri_values and 1 in ri_values:
            # Hole tilda_ids für beide Richtungen
            tilda_ids_ri0 = set(group[group['ri'] == 0]['tilda_id'].dropna().unique())
            tilda_ids_ri1 = set(group[group['ri'] == 1]['tilda_id'].dropna().unique())
            
            # Prüfe auf Überschneidung (gleiche tilda_id in beiden Richtungen)
            duplicate_tilda_ids = tilda_ids_ri0 & tilda_ids_ri1
            
            if duplicate_tilda_ids:
                problematic_elements.append({
                    'element_nr': element_nr,
                    'duplicate_tilda_ids': list(duplicate_tilda_ids),
                    'tilda_ids_ri0': list(tilda_ids_ri0),
                    'tilda_ids_ri1': list(tilda_ids_ri1)
                })
    
    if problematic_elements:
        logger.warning(f"{ORANGE}⚠️ WARNUNG: {len(problematic_elements)} element_nr mit doppelter tilda_id für entgegengesetzte Richtungen gefunden!{RESET}")
        
        # Zeige erste Beispiele
        for item in problematic_elements[:5]:
            logger.warning(f"  element_nr: {item['element_nr']}")
            logger.warning(f"    Doppelte tilda_id(s): {item['duplicate_tilda_ids']}")
            logger.warning(f"    tilda_ids für ri=0: {item['tilda_ids_ri0']}")
            logger.warning(f"    tilda_ids für ri=1: {item['tilda_ids_ri1']}")
        
        if len(problematic_elements) > 5:
            logger.warning(f"  ... und {len(problematic_elements) - 5} weitere problematische element_nr")
        
        return False
    
    logger.info("✓ Keine doppelten tilda_id bei entgegengesetzten Einrichtungsverkehr-Kanten gefunden")
    return True


def validate_missing_attributes(gdf, attributes):
    """
    Prüfe, ob alle erforderlichen Attribute vorhanden sind.
    
    Args:
        gdf: GeoDataFrame mit den Daten
        attributes: Liste der erforderlichen Attributnamen
        
    Returns:
        True wenn alle Attribute vorhanden sind, False sonst
    """
    logger.info("Prüfe auf fehlende Attribute...")
    
    missing_attributes = [attr for attr in attributes if attr not in gdf.columns]
    
    if missing_attributes:
        logger.warning("{ORANGE}⚠️ WARNUNG: Folgende erforderliche Attribute fehlen:{RESET}")
        for attr in missing_attributes:
            logger.warning(f"  - {attr}")
        return False
    
    logger.info("✓ Alle erforderlichen Attribute vorhanden")
    return True


def filter_problematic_features(gdf, attributes, excluded_attributes=None):
    """
    Filtere Features, die NULL-Werte oder TODO-Substring in den angegebenen Attributen haben.
    
    Überspringt Features mit 'Keine Radinfrastruktur vorhanden', da dort NULL-Werte erwartet werden.
    
    Args:
        gdf: GeoDataFrame mit den Daten
        attributes: Liste der zu prüfenden Attributnamen
        excluded_attributes: Liste der Attribute, die nicht zur Filterung führen sollen
        
    Returns:
        GeoDataFrame mit nur den problematischen Features
    """
    logger.info("Filtere problematische Features...")
    
    if excluded_attributes is None:
        excluded_attributes = []
    
    # Erstelle Liste der tatsächlich zu prüfenden Attribute
    attributes_for_filtering = [attr for attr in attributes if attr not in excluded_attributes]
    
    if excluded_attributes:
        logger.info(f"Ausgeschlossene Attribute (werden nicht für Filterung verwendet): {', '.join(excluded_attributes)}")
    
    # Filtere Features ohne Radinfrastruktur aus (dort sind NULL-Werte erlaubt)
    if 'fuehr' in gdf.columns:
        keine_radinfra_mask = gdf['fuehr'] == 'Keine Radinfrastruktur vorhanden'
        gdf_to_filter = gdf[~keine_radinfra_mask]
        keine_radinfra_count = keine_radinfra_mask.sum()
        
        if keine_radinfra_count > 0:
            logger.info(f"→ {keine_radinfra_count} Features mit 'Keine Radinfrastruktur vorhanden' übersprungen")
    else:
        gdf_to_filter = gdf
    
    # Erstelle eine Maske für alle problematischen Features
    problematic_mask = pd.Series(False, index=gdf_to_filter.index)
    
    for attr in attributes_for_filtering:
        if attr not in gdf_to_filter.columns:
            continue
        
        # Spezialbehandlung für 'breite': nur bei Nicht-Mischverkehr prüfen
        if attr == 'breite' and 'fuehr' in gdf_to_filter.columns:
            # Nur NULL-Werte bei Nicht-Mischverkehr-Features als problematisch markieren
            nicht_mischverkehr_mask = gdf_to_filter['fuehr'] != 'Mischverkehr mit motorisiertem Verkehr'
            null_mask = gdf_to_filter[attr].isnull() & nicht_mischverkehr_mask
            problematic_mask |= null_mask
        else:
            # NULL-Werte
            null_mask = gdf_to_filter[attr].isnull()
            problematic_mask |= null_mask
        
        # TODO-Substring (nur bei String-Spalten)
        if gdf_to_filter[attr].dtype == 'object':
            todo_mask = gdf_to_filter[attr].astype(str).str.contains('TODO', case=False, na=False)
            problematic_mask |= todo_mask
    
    problematic_gdf = gdf_to_filter[problematic_mask].copy()
    
    logger.info(f"Gefunden: {len(problematic_gdf)} von {len(gdf)} Features sind problematisch")
    
    return problematic_gdf


def save_problematic_features(gdf, attributes, excluded_attributes, clip_region=None):
    """
    Speichere problematische Features in eine Ausgabedatei.
    
    Args:
        gdf: GeoDataFrame mit allen Daten
        attributes: Liste der zu prüfenden Attributnamen
        excluded_attributes: Liste der Attribute, die nicht zur Filterung führen sollen
        clip_region: Optional, Name der Region für Dateinamen
    """
    # Erstelle Output-Verzeichnis
    output_dir = Path("validation/output")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Filtere problematische Features (ohne ausgeschlossene Attribute)
    problematic_gdf = filter_problematic_features(gdf, attributes, excluded_attributes)
    
    if len(problematic_gdf) == 0:
        logger.info("✓ Keine problematischen Features gefunden - keine Datei erstellt")
        return
    
    # Bestimme Ausgabedateinamen
    if clip_region:
        output_file = output_dir / f"problematic_features_{clip_region}.fgb"
    else:
        output_file = output_dir / "problematic_features.fgb"
    
    # Speichere als FlatGeobuf
    logger.info(f"Speichere {len(problematic_gdf)} problematische Features nach {output_file}")
    problematic_gdf.to_file(output_file, driver="FlatGeobuf")
    logger.info(f"✓ Datei erstellt: {output_file}")
    
    # Statistik über die Probleme
    logger.info("-" * 80)
    logger.info("Statistik der problematischen Features:")
    
    for attr in attributes:
        if attr not in problematic_gdf.columns:
            continue
        
        null_count = problematic_gdf[attr].isnull().sum()
        if null_count > 0:
            logger.info(f"  {attr}: {null_count} NULL-Werte")
        
        if problematic_gdf[attr].dtype == 'object':
            todo_count = problematic_gdf[attr].astype(str).str.contains('TODO', case=False, na=False).sum()
            if todo_count > 0:
                logger.info(f"  {attr}: {todo_count} TODO-Einträge")
    
    logger.info("-" * 80)


def main():
    """Hauptfunktion zur Validierung der konvertierten Radverkehrsanlagen."""
    # Argument-Parser
    parser = argparse.ArgumentParser(
        description="Validierung von konvertierten Radverkehrsanlagen-Daten (Datensatz B)"
    )
    parser.add_argument(
        '--clip',
        type=str,
        choices=['neukoelln', 'norden', 'sueden'],
        help="Regionaler Zuschnitt: 'neukoelln', 'norden' oder 'sueden'"
    )
    parser.add_argument(
        '--create-file',
        action='store_true',
        help="Erstelle eine Datei mit allen problematischen Features in validation/output/"
    )
    
    args = parser.parse_args()
    
    # Header
    logger.info("=" * 80)
    logger.info("PRÜFUNG: Datensatz B (Radverkehrsanlagen) auf Fehler und Probleme")
    logger.info("=" * 80)
    
    # Dateipfad basierend auf --clip Parameter bestimmen
    needs_clipping = False
    if args.clip:
        input_file = Path(f"output/snapping_with_overrides{args.clip}.fgb")
        logger.info(f"Modus: Regionaler Zuschnitt ({args.clip})")
        
        # Wenn geclippte Datei nicht existiert, lade Standard-Datei und clippe dynamisch
        if not input_file.exists():
            fallback_file = Path("output/snapping_with_overrides.fgb")
            logger.warning(f"{ORANGE}⚠️ Geclippte Datei nicht gefunden: {input_file}{RESET}")
            logger.info(f"→ Lade Standard-Datei und clippe auf Region '{args.clip}'")
            input_file = fallback_file
            needs_clipping = True
    else:
        input_file = Path("output/snapping_with_overrides.fgb")
        logger.info("Modus: Vollständiger Datensatz")
    
    # Lade Daten
    gdf = load_converted_bikelanes(input_file)
    
    # Führe Clipping durch, wenn nötig
    if needs_clipping:
        logger.info(f"Clippe {len(gdf)} Features auf Region '{args.clip}'...")
        gdf = clip_to_region(gdf, data_dir="./data", crs=f"EPSG:{DEFAULT_CRS}", region=args.clip)
        logger.info(f"Nach Clipping: {len(gdf)} Features")
    
    # Validierungen durchführen
    logger.info("-" * 80)
    logger.info(f"Zu prüfende Attribute: {', '.join(ATTRIBUTES_TO_VALIDATE)}")
    logger.info("-" * 80)
    
    validation_results = []
    
    validation_results.append(validate_missing_attributes(gdf, ATTRIBUTES_TO_VALIDATE))
    validation_results.append(validate_null_values(gdf, ATTRIBUTES_TO_VALIDATE))
    validation_results.append(validate_todo_values(gdf, ATTRIBUTES_TO_VALIDATE))
    validation_results.append(validate_keine_radinfra_has_null_values(gdf))
    validation_results.append(validate_element_nr_unknown(gdf))
    validation_results.append(validate_duplicate_tilda_id_for_opposite_directions(gdf))
    
    # Zusammenfassung
    logger.info("=" * 80)
    if all(validation_results):
        logger.info("✓ PRÜFUNG ABGESCHLOSSEN: Keine gravierenden Probleme gefunden!")
        logger.info(f"  {len(gdf)} Features geprüft")
        logger.info(f"  {len(ATTRIBUTES_TO_VALIDATE)} Attribute geprüft")
    else:
        logger.warning("{ORANGE}⚠️ PRÜFUNG ABGESCHLOSSEN: Es wurden Probleme gefunden!{RESET}")
        logger.warning("Bitte prüfen Sie die Hinweise und Warnungen oben und beheben Sie ggf. die Daten.")
    logger.info("=" * 80)
    
    # Erstelle Datei mit problematischen Features, wenn gewünscht
    if args.create_file:
        logger.info("")
        logger.info("=" * 80)
        logger.info("ERSTELLE DATEI MIT PROBLEMATISCHEN FEATURES")
        logger.info("=" * 80)
        save_problematic_features(
            gdf, 
            ATTRIBUTES_TO_VALIDATE, 
            ATTRIBUTES_EXCLUDED_FROM_FILE_CREATION,
            clip_region=args.clip
        )
    
    return 0 if all(validation_results) else 1


if __name__ == "__main__":
    sys.exit(main())
