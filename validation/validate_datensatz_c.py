#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
validate_datensatz_c.py
--------------------------------------------------------------------
Überprüft Datensatz C (Aggregierte RVN-Daten) auf Fehler und Probleme.
Prüft auf NULL-Werte, TODO-Substring und weitere Auffälligkeiten in wichtigen Attributen.

INPUT:
- output/aggregated_rvn_final.gpkg (oder mit --clip: _neukoelln, _norden, _sueden)
  Layer: hinrichtung, gegenrichtung

OUTPUT:
- Konsolenausgabe mit Hinweisen und Warnungen zu gefundenen Problemen

USAGE:
- Gesamter Datensatz: python validate_datensatz_c.py
- Regionaler Zuschnitt: python validate_datensatz_c.py --clip neukoelln|norden|sueden
"""

import sys
import argparse
import logging
import geopandas as gpd
import pandas as pd
from pathlib import Path

# Import der Helper aus processing
sys.path.append(str(Path(__file__).parent.parent / 'processing'))
from helpers.globals import DEFAULT_CRS

# Logging konfigurieren
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ============================================================================
# KONFIGURATION: Zu validierende Attribute
# ============================================================================
# Diese Attribute werden auf NULL-Werte und "TODO"-Substring geprüft
ATTRIBUTES_TO_VALIDATE = [
    'afid',
    'element_nr',
    'beginnt_bei_vp',
    'endet_bei_vp',
    'Länge',
    'ri',
    'verkehrsri',
    'Bezirksnummer',
    'strassenname',
    'fuehr',
    'pflicht',
    'breite',
    'ofm',
    'farbe',
    'protek',
    'trennstreifen',
    'nutz_beschr'
]

# Diese Attribute werden von der Validierung geprüft, führen aber NICHT zur 
# Aufnahme in die problematische Features Datei (--create-file)
ATTRIBUTES_EXCLUDED_FROM_FILE_CREATION = [
    'Bezirksnummer'
]


def load_aggregated_rvn(file_path, layer=None):
    """
    Lade aggregierte RVN-Daten aus GeoPackage.
    
    Args:
        file_path: Pfad zur GeoPackage-Datei
        layer: Optional, Layer-Name (hinrichtung oder gegenrichtung)
        
    Returns:
        GeoDataFrame mit aggregierten RVN-Daten
    """
    if layer:
        logger.info(f"Lade Daten aus {file_path} (Layer: {layer})")
    else:
        logger.info(f"Lade Daten aus {file_path}")
    
    if not Path(file_path).exists():
        logger.error(f"FEHLER: Datei nicht gefunden: {file_path}")
        sys.exit(1)
    
    try:
        if layer:
            gdf = gpd.read_file(file_path, layer=layer)
        else:
            gdf = gpd.read_file(file_path)
        logger.info(f"Daten geladen: {len(gdf)} Features")
        return gdf
    except Exception as e:
        logger.error(f"Fehler beim Laden der Daten: {e}")
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
            logger.warning(f"⚠ WARNUNG: Attribut '{attr}' nicht gefunden in den Daten!")
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
                logger.warning(f"⚠ WARNUNG: Attribut '{attr}' hat {null_count} NULL-Werte (nur bei Nicht-Mischverkehr)!")
                
                # Zeige erste Beispiele
                null_features = gdf_to_check[null_mask].head(5)
                for idx, row in null_features.iterrows():
                    logger.warning(f"  afid={row.get('afid', 'N/A')}, element_nr={row.get('element_nr', 'N/A')}")
                
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
                logger.warning(f"⚠ WARNUNG: Attribut '{attr}' hat {null_count} NULL-Werte!")
                
                # Zeige erste Beispiele
                null_features = gdf_to_validate[null_mask].head(5)
                for idx, row in null_features.iterrows():
                    logger.warning(f"  afid={row.get('afid', 'N/A')}, element_nr={row.get('element_nr', 'N/A')}")
                
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
        logger.warning("⚠ WARNUNG: Attribut 'fuehr' nicht gefunden!")
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
            logger.warning(f"⚠ WARNUNG: Attribut '{attr}' nicht gefunden in den Daten!")
            all_valid = False
            continue
        
        # Prüfe auf NICHT-NULL-Werte (diese sind problematisch)
        non_null_mask = keine_radinfra_gdf[attr].notnull()
        non_null_count = non_null_mask.sum()
        
        if non_null_count > 0:
            all_valid = False
            total_non_null_count += non_null_count
            logger.warning(f"⚠ WARNUNG: Attribut '{attr}' hat {non_null_count} NICHT-NULL-Werte bei 'Keine Radinfrastruktur vorhanden'!")
            
            # Zeige erste Beispiele mit den Werten
            non_null_features = keine_radinfra_gdf[non_null_mask].head(5)
            for idx, row in non_null_features.iterrows():
                logger.warning(f"  afid={row.get('afid', 'N/A')}, element_nr={row.get('element_nr', 'N/A')}: '{row[attr]}'")
            
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
                logger.warning(f"⚠ WARNUNG: Attribut '{attr}' hat {todo_count} Einträge mit 'TODO'!")
                
                # Zeige erste Beispiele mit den Werten
                todo_features = gdf_to_validate[todo_mask].head(5)
                for idx, row in todo_features.iterrows():
                    logger.warning(f"  afid={row.get('afid', 'N/A')}, element_nr={row.get('element_nr', 'N/A')}: '{row[attr]}'")
                
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
            logger.warning(f"  afid={row.get('afid', 'N/A')}, element_nr='{row['element_nr']}'")
        
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


def main():
    """Hauptfunktion zur Validierung der aggregierten RVN-Daten."""
    # Argument-Parser
    parser = argparse.ArgumentParser(
        description="Validierung von aggregierten RVN-Daten (Datensatz C)"
    )
    parser.add_argument(
        '--clip',
        type=str,
        choices=['neukoelln', 'norden', 'sueden'],
        help="Regionaler Zuschnitt: 'neukoelln', 'norden' oder 'sueden'"
    )
    
    args = parser.parse_args()
    
    # Header
    logger.info("=" * 80)
    logger.info("PRÜFUNG: Datensatz C (Aggregierte RVN-Daten) auf Fehler und Probleme")
    logger.info("=" * 80)
    
    # Dateipfad basierend auf --clip Parameter bestimmen
    if args.clip:
        input_file = Path(f"output/aggregated_rvn_final_{args.clip}.gpkg")
        logger.info(f"Modus: Regionaler Zuschnitt ({args.clip})")
    else:
        input_file = Path("output/aggregated_rvn_final.gpkg")
        logger.info("Modus: Vollständiger Datensatz")
    
    if not input_file.exists():
        logger.error(f"FEHLER: Datei nicht gefunden: {input_file}")
        logger.error("Hinweis: Führen Sie zuerst die Aggregation aus (execute_processing.sh)")
        sys.exit(1)
    
    # Lade und validiere beide Layer
    layers = ['hinrichtung', 'gegenrichtung']
    all_validation_results = []
    
    for layer in layers:
        logger.info("")
        logger.info("=" * 80)
        logger.info(f"Layer: {layer}")
        logger.info("=" * 80)
        
        # Lade Daten für diesen Layer
        try:
            gdf = load_aggregated_rvn(input_file, layer=layer)
        except Exception as e:
            logger.error(f"Fehler beim Laden des Layers '{layer}': {e}")
            all_validation_results.append(False)
            continue
        
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
        
        # Layer-Zusammenfassung
        logger.info("-" * 80)
        if all(validation_results):
            logger.info(f"✓ Layer '{layer}': Keine gravierenden Probleme gefunden!")
            logger.info(f"  {len(gdf)} Features geprüft")
        else:
            logger.warning(f"⚠ Layer '{layer}': Es wurden Probleme gefunden!")
        
        all_validation_results.extend(validation_results)
    
    # Gesamt-Zusammenfassung
    logger.info("")
    logger.info("=" * 80)
    logger.info("GESAMT-ZUSAMMENFASSUNG")
    logger.info("=" * 80)
    
    if all(all_validation_results):
        logger.info("✓ PRÜFUNG ABGESCHLOSSEN: Keine gravierenden Probleme gefunden!")
        logger.info(f"  {len(ATTRIBUTES_TO_VALIDATE)} Attribute geprüft")
        logger.info(f"  {len(layers)} Layer geprüft")
    else:
        logger.warning("⚠ PRÜFUNG ABGESCHLOSSEN: Es wurden Probleme gefunden!")
        logger.warning("Bitte prüfen Sie die Hinweise und Warnungen oben und beheben Sie ggf. die Daten.")
    logger.info("=" * 80)
    
    return 0 if all(all_validation_results) else 1


if __name__ == "__main__":
    sys.exit(main())
