#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
validate_knotenpunkte.py
--------------------------------------------------------------------
Validiert die Knotenpunkte im TILDA-Datensatz.

INPUT:
- data-raw-tilda/knotenpunkte_mit_id_und_bezirken.gpkg

OUTPUT:
- Konsolenausgabe mit Warnungen bei gefundenen Problemen
"""

import sys
import logging
import geopandas as gpd
import pandas as pd
from pathlib import Path

# ANSI Farb-Codes
ORANGE = '\033[38;5;214m'
RED = '\033[91m'
RESET = '\033[0m'

# Logging konfigurieren
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ============================================================================
# KONFIGURATION: Pflichtfelder bei KP_Nichtbetrachten != 1
# ============================================================================
# Diese Felder müssen ausgefüllt sein, wenn KP_Nichtbetrachten NICHT 1 ist
PFLICHTFELDER_BEI_BETRACHTUNG = [
    'Knotenpunkt‐ID',  # Achtung: Bindestrich ist ein spezielles Unicode-Zeichen
    'Bezirksnummer',
    'KP_HVS',
    'LSA_KP',
    'Mar_RVF_KP',
    'Furt_rot',
    'Fl_Linksab',
    'vorgez_Fl',
    'RFS_Mitte'
]


def load_knotenpunkte(file_path):
    """
    Lade Knotenpunkte-Daten aus GeoPackage.
    
    Args:
        file_path: Pfad zur GeoPackage-Datei
        
    Returns:
        GeoDataFrame mit Knotenpunkten
    """
    logger.info(f"Lade Knotenpunkte aus {file_path}")
    
    try:
        gdf = gpd.read_file(file_path)
        logger.info(f"Knotenpunkte geladen: {len(gdf)} Features")
        logger.info(f"Verfügbare Spalten: {list(gdf.columns)}")
        return gdf
    except Exception as e:
        logger.error(f"{RED}❌ FEHLER: Fehler beim Laden der Daten: {e}{RESET}")
        sys.exit(1)


def validate_pflichtfelder_bei_betrachtung(gdf):
    """
    Prüfe, ob bei Knotenpunkten mit KP_Nichtbetrachten != 1 alle Pflichtfelder ausgefüllt sind.
    
    Args:
        gdf: GeoDataFrame mit Knotenpunkten
        
    Returns:
        True wenn alle Pflichtfelder bei zu betrachtenden Knotenpunkten ausgefüllt sind, False sonst
    """
    logger.info("Prüfe Pflichtfelder bei zu betrachtenden Knotenpunkten (KP_Nichtbetrachten != 1)...")
    
    # Prüfe, ob KP_Nichtbetrachten-Spalte existiert
    if 'KP_Nichtbetrachten' not in gdf.columns:
        logger.error(f"{RED}❌ FEHLER: Spalte 'KP_Nichtbetrachten' nicht gefunden!{RESET}")
        logger.error(f"{RED}Verfügbare Spalten: {list(gdf.columns)}{RESET}")
        return False
    
    # Filtere Knotenpunkte, die betrachtet werden sollen (KP_Nichtbetrachten == 0)
    zu_betrachten_mask = gdf['KP_Nichtbetrachten'] == 0
    gdf_zu_betrachten = gdf[zu_betrachten_mask]
    
    logger.info(f"Zu betrachtende Knotenpunkte (KP_Nichtbetrachten == 0): {len(gdf_zu_betrachten)} von {len(gdf)}")
    
    if len(gdf_zu_betrachten) == 0:
        logger.info("✓ Keine zu betrachtenden Knotenpunkte gefunden (KP_Nichtbetrachten == 0)")
        return True
    
    all_valid = True
    total_null_count = 0
    
    for feld in PFLICHTFELDER_BEI_BETRACHTUNG:
        # Prüfe, ob Feld existiert
        if feld not in gdf.columns:
            logger.warning(f"{ORANGE}⚠️ WARNUNG: Pflichtfeld '{feld}' nicht in den Daten gefunden!{RESET}")
            all_valid = False
            continue
        
        # Prüfe auf NULL-Werte
        null_mask = gdf_zu_betrachten[feld].isnull()
        null_count = null_mask.sum()
        
        if null_count > 0:
            all_valid = False
            total_null_count += null_count
            logger.warning(f"{ORANGE}⚠️ WARNUNG: Pflichtfeld '{feld}' hat {null_count} NULL-Werte bei zu betrachtenden Knotenpunkten!{RESET}")
            
            # Zeige erste Beispiele
            null_indices = gdf_zu_betrachten[null_mask].index[:5].tolist()
            logger.warning(f"{ORANGE}  Beispiel-Indizes: {null_indices}{RESET}")
            
            if null_count > 5:
                logger.warning(f"{ORANGE}  ... und {null_count - 5} weitere NULL-Werte{RESET}")
        else:
            logger.info(f"✓ Pflichtfeld '{feld}': Keine NULL-Werte")
    
    if not all_valid:
        logger.warning(f"{ORANGE}-" * 80 + f"{RESET}")
        logger.warning(f"{ORANGE}Gesamt: {total_null_count} NULL-Werte in Pflichtfeldern gefunden{RESET}")
    else:
        logger.info("✓ Alle Pflichtfelder sind bei zu betrachtenden Knotenpunkten ausgefüllt!")
    
    return all_valid


def main():
    """Hauptfunktion zur Validierung der Knotenpunkte."""
    logger.info("=" * 80)
    logger.info("VALIDIERUNG: Knotenpunkte - Pflichtfelder bei Betrachtung")
    logger.info("=" * 80)
    
    # Dateipfad definieren
    input_file = Path("output/knotenpunkte_mit_id_und_bezirken.geojson")
    
    if not input_file.exists():
        logger.error(f"{RED}❌ FEHLER: Datei nicht gefunden: {input_file}{RESET}")
        sys.exit(1)
    
    # Lade Daten
    gdf = load_knotenpunkte(input_file)
    
    # Validierungen durchführen
    validation_results = []
    
    validation_results.append(validate_pflichtfelder_bei_betrachtung(gdf))
    
    # Zusammenfassung
    logger.info("=" * 80)
    if all(validation_results):
        logger.info("✓ VALIDIERUNG ERFOLGREICH: Alle Prüfungen bestanden!")
    else:
        logger.warning(f"{ORANGE}⚠️ VALIDIERUNG FEHLGESCHLAGEN: Es wurden Probleme gefunden!{RESET}")
        logger.warning(f"{ORANGE}Bitte überprüfen Sie die Warnungen oben und korrigieren Sie die Daten.{RESET}")
    logger.info("=" * 80)
    
    return 0 if all(validation_results) else 1


if __name__ == "__main__":
    sys.exit(main())
