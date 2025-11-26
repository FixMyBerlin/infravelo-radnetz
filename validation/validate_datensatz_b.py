#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
validate_datensatz_b.py
--------------------------------------------------------------------
Validiert die konvertierten Radverkehrsanlagen-Daten (Datensatz B).
Prüft auf NULL-Werte und TODO-Substring in wichtigen Attributen.

INPUT:
- output/snapping_converted_bikelanes.fgb (oder mit --clip: _neukoelln, _norden, _sueden)

OUTPUT:
- Konsolenausgabe mit Warnungen bei gefundenen Problemen

USAGE:
- Vollständiger Datensatz: python validate_datensatz_b.py
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

# Logging konfigurieren
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ============================================================================
# KONFIGURATION: Zu validierende Attribute
# ============================================================================
# Diese Attribute werden auf NULL-Werte und "TODO"-Substring geprüft
ATTRIBUTES_TO_VALIDATE = [
    'fuehr',
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
        logger.error(f"FEHLER: Datei nicht gefunden: {file_path}")
        sys.exit(1)
    
    try:
        gdf = gpd.read_file(file_path)
        logger.info(f"Daten geladen: {len(gdf)} Features")
        logger.info(f"Verfügbare Spalten: {list(gdf.columns)}")
        return gdf
    except Exception as e:
        logger.error(f"Fehler beim Laden der Daten: {e}")
        sys.exit(1)


def validate_null_values(gdf, attributes):
    """
    Prüfe auf NULL-Werte in den angegebenen Attributen.
    
    Spezialbehandlung für 'breite': Wird nur bei Führungsformen geprüft, 
    die nicht "Mischverkehr mit motorisiertem Verkehr" sind.
    
    Args:
        gdf: GeoDataFrame mit den Daten
        attributes: Liste der zu prüfenden Attributnamen
        
    Returns:
        True wenn keine NULL-Werte gefunden wurden, False sonst
    """
    logger.info("Prüfe auf NULL-Werte in den Attributen...")
    
    all_valid = True
    total_null_count = 0
    
    for attr in attributes:
        # Prüfe, ob Attribut existiert
        if attr not in gdf.columns:
            logger.warning(f"⚠ WARNUNG: Attribut '{attr}' nicht gefunden in den Daten!")
            all_valid = False
            continue
        
        # Spezialbehandlung für 'breite': nur bei Nicht-Mischverkehr prüfen
        if attr == 'breite' and 'fuehr' in gdf.columns:
            # Filtere nur Features, die nicht Mischverkehr sind
            nicht_mischverkehr_mask = gdf['fuehr'] != 'Mischverkehr mit motorisiertem Verkehr'
            gdf_to_check = gdf[nicht_mischverkehr_mask]
            
            null_mask = gdf_to_check[attr].isnull()
            null_count = null_mask.sum()
            
            if null_count > 0:
                all_valid = False
                total_null_count += null_count
                logger.warning(f"⚠ WARNUNG: Attribut '{attr}' hat {null_count} NULL-Werte (nur bei Nicht-Mischverkehr)!")
                
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
            null_mask = gdf[attr].isnull()
            null_count = null_mask.sum()
            
            if null_count > 0:
                all_valid = False
                total_null_count += null_count
                logger.warning(f"⚠ WARNUNG: Attribut '{attr}' hat {null_count} NULL-Werte!")
                
                # Zeige erste Beispiele
                null_indices = gdf[null_mask].index[:5].tolist()
                logger.warning(f"  Beispiel-Indizes: {null_indices}")
                
                if null_count > 5:
                    logger.warning(f"  ... und {null_count - 5} weitere NULL-Werte")
            else:
                logger.info(f"✓ Attribut '{attr}': Keine NULL-Werte")
    
    if not all_valid:
        logger.warning("-" * 80)
        logger.warning(f"Gesamt: {total_null_count} NULL-Werte in {len([a for a in attributes if a in gdf.columns])} Attributen gefunden")
    else:
        logger.info("✓ Keine NULL-Werte gefunden!")
    
    return all_valid


def validate_todo_values(gdf, attributes):
    """
    Prüfe auf "TODO"-Substring in den angegebenen Attributen.
    
    Args:
        gdf: GeoDataFrame mit den Daten
        attributes: Liste der zu prüfenden Attributnamen
        
    Returns:
        True wenn keine TODO-Werte gefunden wurden, False sonst
    """
    logger.info("Prüfe auf TODO-Substring in den Attributen...")
    
    all_valid = True
    total_todo_count = 0
    
    for attr in attributes:
        # Prüfe, ob Attribut existiert
        if attr not in gdf.columns:
            # Bereits bei NULL-Prüfung gewarnt
            continue
        
        # Prüfe nur String-Spalten
        if gdf[attr].dtype == 'object' or isinstance(gdf[attr].iloc[0], str) if len(gdf) > 0 else False:
            # Suche nach TODO (case-insensitive)
            todo_mask = gdf[attr].astype(str).str.contains('TODO', case=False, na=False)
            todo_count = todo_mask.sum()
            
            if todo_count > 0:
                all_valid = False
                total_todo_count += todo_count
                logger.warning(f"⚠ WARNUNG: Attribut '{attr}' hat {todo_count} Einträge mit 'TODO'!")
                
                # Zeige erste Beispiele mit den Werten
                todo_features = gdf[todo_mask].head(5)
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
        logger.warning("⚠ WARNUNG: Attribut 'element_nr' nicht gefunden!")
        return False
    
    # Suche nach UNKNOWN (case-insensitive)
    unknown_mask = gdf['element_nr'].astype(str).str.contains('UNKNOWN', case=False, na=False)
    unknown_count = unknown_mask.sum()
    
    if unknown_count > 0:
        logger.warning(f"⚠ WARNUNG: element_nr hat {unknown_count} Einträge mit 'UNKNOWN'!")
        
        # Zeige erste Beispiele mit den Werten
        unknown_features = gdf[unknown_mask].head(5)
        for idx, row in unknown_features.iterrows():
            logger.warning(f"  Index {idx}: '{row['element_nr']}'")
        
        if unknown_count > 5:
            logger.warning(f"  ... und {unknown_count - 5} weitere UNKNOWN-Einträge")
        
        return False
    
    logger.info("✓ Attribut 'element_nr': Keine UNKNOWN-Werte")
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
        logger.warning("⚠ WARNUNG: Folgende erforderliche Attribute fehlen:")
        for attr in missing_attributes:
            logger.warning(f"  - {attr}")
        return False
    
    logger.info("✓ Alle erforderlichen Attribute vorhanden")
    return True


def filter_problematic_features(gdf, attributes, excluded_attributes=None):
    """
    Filtere Features, die NULL-Werte oder TODO-Substring in den angegebenen Attributen haben.
    
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
    
    # Erstelle eine Maske für alle problematischen Features
    problematic_mask = pd.Series(False, index=gdf.index)
    
    for attr in attributes_for_filtering:
        if attr not in gdf.columns:
            continue
        
        # Spezialbehandlung für 'breite': nur bei Nicht-Mischverkehr prüfen
        if attr == 'breite' and 'fuehr' in gdf.columns:
            # Nur NULL-Werte bei Nicht-Mischverkehr-Features als problematisch markieren
            nicht_mischverkehr_mask = gdf['fuehr'] != 'Mischverkehr mit motorisiertem Verkehr'
            null_mask = gdf[attr].isnull() & nicht_mischverkehr_mask
            problematic_mask |= null_mask
        else:
            # NULL-Werte
            null_mask = gdf[attr].isnull()
            problematic_mask |= null_mask
        
        # TODO-Substring (nur bei String-Spalten)
        if gdf[attr].dtype == 'object':
            todo_mask = gdf[attr].astype(str).str.contains('TODO', case=False, na=False)
            problematic_mask |= todo_mask
    
    problematic_gdf = gdf[problematic_mask].copy()
    
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
    logger.info("VALIDIERUNG: Konvertierte Radverkehrsanlagen (Datensatz B)")
    logger.info("=" * 80)
    
    # Dateipfad basierend auf --clip Parameter bestimmen
    needs_clipping = False
    if args.clip:
        input_file = Path(f"output/snapping_converted_bikelanes_{args.clip}.fgb")
        logger.info(f"Modus: Regionaler Zuschnitt ({args.clip})")
        
        # Wenn geclippte Datei nicht existiert, lade Standard-Datei und clippe dynamisch
        if not input_file.exists():
            fallback_file = Path("output/snapping_converted_bikelanes.fgb")
            logger.warning(f"⚠ Geclippte Datei nicht gefunden: {input_file}")
            logger.info(f"→ Lade Standard-Datei und clippe auf Region '{args.clip}'")
            input_file = fallback_file
            needs_clipping = True
    else:
        input_file = Path("output/snapping_converted_bikelanes.fgb")
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
    logger.info(f"Zu validierende Attribute: {', '.join(ATTRIBUTES_TO_VALIDATE)}")
    logger.info("-" * 80)
    
    validation_results = []
    
    validation_results.append(validate_missing_attributes(gdf, ATTRIBUTES_TO_VALIDATE))
    validation_results.append(validate_null_values(gdf, ATTRIBUTES_TO_VALIDATE))
    validation_results.append(validate_todo_values(gdf, ATTRIBUTES_TO_VALIDATE))
    validation_results.append(validate_element_nr_unknown(gdf))
    
    # Zusammenfassung
    logger.info("=" * 80)
    if all(validation_results):
        logger.info("✓ VALIDIERUNG ERFOLGREICH: Alle Prüfungen bestanden!")
        logger.info(f"  {len(gdf)} Features validiert")
        logger.info(f"  {len(ATTRIBUTES_TO_VALIDATE)} Attribute geprüft")
    else:
        logger.warning("⚠ VALIDIERUNG FEHLGESCHLAGEN: Es wurden Probleme gefunden!")
        logger.warning("Bitte überprüfen Sie die Warnungen oben und korrigieren Sie die Daten.")
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
