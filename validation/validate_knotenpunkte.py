#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
validate_knotenpunkte.py
--------------------------------------------------------------------
Validiert die Eindeutigkeit der Knotenpunkte im TILDA-Datensatz.
Prüft, ob jede okstra_id nur einmal vorkommt und gibt Warnungen bei Duplikaten aus.

INPUT:
- data-raw-tilda/knotenpunkte_mit_id_und_bezirken.gpkg

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

# Logging konfigurieren
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


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
        logger.error(f"Fehler beim Laden der Daten: {e}")
        sys.exit(1)


def validate_okstra_id_uniqueness(gdf):
    """
    Prüfe, ob jede okstra_id eindeutig ist.
    
    Args:
        gdf: GeoDataFrame mit Knotenpunkten
        
    Returns:
        True wenn alle okstra_ids eindeutig sind, False sonst
    """
    logger.info("Validiere Eindeutigkeit der okstra_id...")
    
    # Prüfe, ob okstra_id-Spalte existiert
    if 'okstra_id' not in gdf.columns:
        logger.error("FEHLER: Spalte 'okstra_id' nicht gefunden!")
        logger.error(f"Verfügbare Spalten: {list(gdf.columns)}")
        return False
    
    # Zähle Vorkommen jeder okstra_id
    okstra_id_counts = Counter(gdf['okstra_id'])
    
    # Finde Duplikate (IDs, die mehr als einmal vorkommen)
    duplicates = {okstra_id: count for okstra_id, count in okstra_id_counts.items() if count > 1}
    
    if not duplicates:
        logger.info("✓ Alle okstra_ids sind eindeutig!")
        return True
    
    # Ausgabe der Duplikate
    logger.warning(f"⚠ WARNUNG: {len(duplicates)} okstra_id(s) kommen mehrfach vor!")
    logger.warning("-" * 80)
    
    for okstra_id, count in sorted(duplicates.items(), key=lambda x: x[1], reverse=True):
        logger.warning(f"  okstra_id '{okstra_id}' kommt {count}x vor")
        
        # Zeige Details zu den betroffenen Features
        duplicate_features = gdf[gdf['okstra_id'] == okstra_id]
        for idx, row in duplicate_features.iterrows():
            # Sichere Geometrie-Koordinaten-Extraktion
            if row.geometry is None or row.geometry.is_empty:
                coords = "keine Geometrie"
            else:
                try:
                    coords = f"({row.geometry.x:.2f}, {row.geometry.y:.2f})"
                except AttributeError:
                    coords = f"{row.geometry.geom_type}"
            
            logger.warning(f"    - Index {idx}: Koordinaten {coords}")
            
            # Zeige zusätzliche Attribute, falls vorhanden
            if 'Bezirksnummer' in row.index and pd.notna(row['Bezirksnummer']):
                logger.warning(f"      Bezirk: {row['Bezirksnummer']}")
    
    logger.warning("-" * 80)
    logger.warning(f"Gesamt: {sum(duplicates.values())} nicht-eindeutige Features gefunden")
    
    return False


def validate_null_okstra_ids(gdf):
    """
    Prüfe, ob es Features ohne okstra_id gibt.
    
    Args:
        gdf: GeoDataFrame mit Knotenpunkten
        
    Returns:
        True wenn alle Features eine okstra_id haben, False sonst
    """
    logger.info("Prüfe auf fehlende okstra_ids...")
    
    null_ids = gdf['okstra_id'].isnull()
    null_count = null_ids.sum()
    
    if null_count == 0:
        logger.info("✓ Alle Features haben eine okstra_id")
        return True
    
    logger.warning(f"⚠ WARNUNG: {null_count} Feature(s) haben keine okstra_id!")
    
    # Zeige Details zu Features ohne okstra_id
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
        
        logger.warning(f"  - Index {idx}: Koordinaten {coords}")
    
    if null_count > 10:
        logger.warning(f"  ... und {null_count - 10} weitere Features")
    
    return False


def main():
    """Hauptfunktion zur Validierung der Knotenpunkte."""
    logger.info("=" * 80)
    logger.info("VALIDIERUNG: Knotenpunkte-Eindeutigkeit")
    logger.info("=" * 80)
    
    # Dateipfad definieren
    input_file = Path("data-raw-tilda/knotenpunkte_mit_id_und_bezirken.gpkg")
    
    if not input_file.exists():
        logger.error(f"FEHLER: Datei nicht gefunden: {input_file}")
        sys.exit(1)
    
    # Lade Daten
    gdf = load_knotenpunkte(input_file)
    
    # Validierungen durchführen
    validation_results = []
    
    validation_results.append(validate_null_okstra_ids(gdf))
    validation_results.append(validate_okstra_id_uniqueness(gdf))
    
    # Zusammenfassung
    logger.info("=" * 80)
    if all(validation_results):
        logger.info("✓ VALIDIERUNG ERFOLGREICH: Alle Prüfungen bestanden!")
    else:
        logger.warning("⚠ VALIDIERUNG FEHLGESCHLAGEN: Es wurden Probleme gefunden!")
        logger.warning("Bitte überprüfen Sie die Warnungen oben und korrigieren Sie die Daten.")
    logger.info("=" * 80)
    
    return 0 if all(validation_results) else 1


if __name__ == "__main__":
    sys.exit(main())
