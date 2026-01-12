#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
validate_virtuelle_knotenpunkte.py
--------------------------------------------------------------------
Validiert die Eindeutigkeit der Knotenpunkt-IDs in den virtuellen Knotenpunkten.
Prüft, ob jede Knotenpunkt-ID nur einmal vorkommt und gibt Warnungen bei Duplikaten aus.

INPUT:
- data/Virtuelle-Knotenpunkte.gpkg

OUTPUT:
- Konsolenausgabe mit Warnungen bei gefundenen Duplikaten
"""

import sys
import logging
import geopandas as gpd
import pandas as pd
from pathlib import Path
from collections import Counter

# Import der Helper aus processing
sys.path.append(str(Path(__file__).parent.parent / 'processing'))
from helpers.globals import DEFAULT_CRS

# ANSI Farb-Codes
ORANGE = '\033[38;5;214m'
RED = '\033[91m'
RESET = '\033[0m'

# Logging konfigurieren
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def load_virtuelle_knotenpunkte(file_path):
    """
    Lade Virtuelle Knotenpunkte-Daten aus GeoPackage.
    
    Args:
        file_path: Pfad zur GeoPackage-Datei
        
    Returns:
        GeoDataFrame mit virtuellen Knotenpunkten
    """
    logger.info(f"Lade virtuelle Knotenpunkte aus {file_path}")
    
    try:
        gdf = gpd.read_file(file_path)
        logger.info(f"Virtuelle Knotenpunkte geladen: {len(gdf)} Features")
        return gdf
    except Exception as e:
        logger.error(f"{RED}❌ FEHLER: Fehler beim Laden der Daten: {e}{RESET}")
        sys.exit(1)


def validate_knotenpunkt_id_uniqueness(gdf):
    """
    Prüfe, ob jede Knotenpunkt-ID eindeutig ist.
    
    Args:
        gdf: GeoDataFrame mit virtuellen Knotenpunkten
        
    Returns:
        True wenn alle Knotenpunkt-IDs eindeutig sind, False sonst
    """
    logger.info("Validiere Eindeutigkeit der Knotenpunkt-ID...")
    
    # Prüfe, ob Knotenpunkt-ID-Spalte existiert
    if 'Knotenpunkt-ID' not in gdf.columns:
        logger.error(f"{RED}❌ FEHLER: Spalte 'Knotenpunkt-ID' nicht gefunden!{RESET}")
        return False
    
    # Zähle Vorkommen jeder Knotenpunkt-ID
    knotenpunkt_id_counts = Counter(gdf['Knotenpunkt-ID'])
    
    # Finde Duplikate (IDs, die mehr als einmal vorkommen)
    duplicates = {knotenpunkt_id: count for knotenpunkt_id, count in knotenpunkt_id_counts.items() if count > 1}
    
    if not duplicates:
        logger.info("✓ Alle Knotenpunkt-IDs sind eindeutig!")
        return True
    
    # Ausgabe der Duplikate
    logger.warning(f"{ORANGE}⚠️ WARNUNG: {len(duplicates)} Knotenpunkt-ID(s) kommen mehrfach vor!{RESET}")
    logger.warning(f"{ORANGE}-" * 80 + f"{RESET}")
    
    for knotenpunkt_id, count in sorted(duplicates.items(), key=lambda x: x[1], reverse=True):
        logger.warning(f"{ORANGE}  Knotenpunkt-ID '{knotenpunkt_id}' kommt {count}x vor{RESET}")
        
        # Zeige Details zu den betroffenen Features
        duplicate_features = gdf[gdf['Knotenpunkt-ID'] == knotenpunkt_id]
        for idx, row in duplicate_features.iterrows():
            # Sichere Geometrie-Koordinaten-Extraktion
            if row.geometry is None or row.geometry.is_empty:
                coords = "keine Geometrie"
            else:
                try:
                    coords = f"({row.geometry.x:.2f}, {row.geometry.y:.2f})"
                except AttributeError:
                    coords = f"{row.geometry.geom_type}"
            
            logger.warning(f"{ORANGE}    - Index {idx}: Koordinaten {coords}{RESET}")
    
    logger.warning(f"{ORANGE}-" * 80 + f"{RESET}")
    logger.warning(f"{ORANGE}Gesamt: {sum(duplicates.values())} nicht-eindeutige Features gefunden{RESET}")
    
    return False


def validate_null_knotenpunkt_ids(gdf):
    """
    Prüfe, ob es Features ohne Knotenpunkt-ID gibt.
    
    Args:
        gdf: GeoDataFrame mit virtuellen Knotenpunkten
        
    Returns:
        True wenn alle Features eine Knotenpunkt-ID haben, False sonst
    """
    logger.info("Prüfe auf fehlende Knotenpunkt-IDs...")
    
    null_ids = gdf['Knotenpunkt-ID'].isnull() | (gdf['Knotenpunkt-ID'] == '')
    null_count = null_ids.sum()
    
    if null_count == 0:
        logger.info("✓ Alle Features haben eine Knotenpunkt-ID")
        return True
    
    logger.warning(f"{ORANGE}⚠️ WARNUNG: {null_count} Feature(s) haben keine Knotenpunkt-ID!{RESET}")
    
    # Zeige Details zu Features ohne Knotenpunkt-ID
    null_features = gdf[null_ids]
    for idx, row in null_features.head(10).iterrows():
        # Sichere Geometrie-Koordinaten-Extraktion
        if row.geometry is None or row.geometry.is_empty:
            coords = "keine Geometrie"
        else:
            try:
                coords = f"({row.geometry.x:.2f}, {row.geometry.y:.2f})"
            except AttributeError:
                coords = f"{row.geometry.geom_type}"
        
        logger.warning(f"{ORANGE}  - Index {idx}: Koordinaten {coords}{RESET}")
    
    if null_count > 10:
        logger.warning(f"{ORANGE}  ... und {null_count - 10} weitere Features{RESET}")
    
    return False


def main():
    """Hauptfunktion zur Validierung der virtuellen Knotenpunkte."""
    logger.info("=" * 80)
    logger.info("VALIDIERUNG: Virtuelle Knotenpunkte - Eindeutigkeit der Knotenpunkt-IDs")
    logger.info("=" * 80)
    
    # Dateipfad definieren
    input_file = Path("data/Virtuelle-Knotenpunkte.gpkg")
    
    if not input_file.exists():
        logger.error(f"{RED}❌ FEHLER: Datei nicht gefunden: {input_file}{RESET}")
        sys.exit(1)
    
    # Lade Daten
    gdf = load_virtuelle_knotenpunkte(input_file)
    
    # Validierungen durchführen
    validation_results = []
    
    validation_results.append(validate_null_knotenpunkt_ids(gdf))
    validation_results.append(validate_knotenpunkt_id_uniqueness(gdf))
    
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
