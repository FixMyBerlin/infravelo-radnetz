# -*- coding: utf-8 -*-
"""
enrich_rvn_with_detailnetz.py
Anreicherung des Radvorrangnetzes mit Detailnetz-Informationen.

Dieses Skript kombiniert das Berliner Radvorrangnetz mit dem Straßendetailnetz,
um detaillierte Informationen wie Straßennamen und -klassen zu ergänzen.

INPUT:
- output/rvn/Berlin Vorrangnetz_with_element_nr.fgb
- data/Berlin Straßenabschnitte Detailnetz.fgb

OUTPUT:
- output/rvn/vorrangnetz_details_combined_rvn.fgb
"""

import geopandas as gpd
import pandas as pd
import logging
import sys
import os
from pathlib import Path

# Pfad zur processing-Verzeichnis hinzufügen
processing_path = Path(__file__).parent.parent / "processing"
sys.path.append(str(processing_path))

try:
    from helpers.globals import DEFAULT_CRS, DEFAULT_OUTPUT_DIR
except ImportError:
    DEFAULT_CRS = 25833
    DEFAULT_OUTPUT_DIR = "output/"

# Konfiguration: Auszuschließende element_nr
EXCLUDED_ELEMENT_NRS = [
    "48500463_49500011.01"
]

# Logging konfigurieren
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def load_input_data():
    """
    Lädt die Input-Dateien und überprüft deren Struktur.
    
    Returns:
        tuple: (vorrangnetz_gdf, detailnetz_gdf)
    """
    logger.info("Lade Input-Dateien...")
    
    # Vorrangnetz laden
    vorrangnetz_path = "output/rvn/Berlin Vorrangnetz_with_element_nr.fgb"
    if not os.path.exists(vorrangnetz_path):
        raise FileNotFoundError(f"Vorrangnetz-Datei nicht gefunden: {vorrangnetz_path}")
    
    vorrangnetz = gpd.read_file(vorrangnetz_path)
    logger.info(f"Vorrangnetz geladen: {len(vorrangnetz)} Kanten")
    
    # Detailnetz laden
    detailnetz_path = "data/Berlin Straßenabschnitte Detailnetz.fgb"
    if not os.path.exists(detailnetz_path):
        raise FileNotFoundError(f"Detailnetz-Datei nicht gefunden: {detailnetz_path}")
    
    detailnetz = gpd.read_file(detailnetz_path)
    logger.info(f"Detailnetz geladen: {len(detailnetz)} Kanten")
    
    # CRS überprüfen
    if vorrangnetz.crs != f"EPSG:{DEFAULT_CRS}":
        logger.warning(f"Vorrangnetz CRS: {vorrangnetz.crs}, transformiere zu EPSG:{DEFAULT_CRS}")
        vorrangnetz = vorrangnetz.to_crs(f"EPSG:{DEFAULT_CRS}")
    
    if detailnetz.crs != f"EPSG:{DEFAULT_CRS}":
        logger.warning(f"Detailnetz CRS: {detailnetz.crs}, transformiere zu EPSG:{DEFAULT_CRS}")
        detailnetz = detailnetz.to_crs(f"EPSG:{DEFAULT_CRS}")
    
    return vorrangnetz, detailnetz


def prepare_datasets(vorrangnetz, detailnetz):
    """
    Bereitet die Datensätze vor und wählt relevante Spalten aus.
    Erstellt eindeutige IDs für jede Geometrie um Duplikate korrekt zu handhaben.
    
    Args:
        vorrangnetz (GeoDataFrame): Vorrangnetz
        detailnetz (GeoDataFrame): Detailnetz
        
    Returns:
        tuple: (vorrangnetz_prepared, detailnetz_prepared)
    """
    logger.info("Bereite Datensätze vor...")
    
    # Vorrangnetz: Relevante Spalten auswählen und eindeutige ID erstellen
    vorrangnetz_cols = ['element_nr', 'beginnt_bei_vp', 'endet_bei_vp', 'geometry']
    vorrangnetz_prepared = vorrangnetz[vorrangnetz_cols].copy()
    
    # Erstelle eindeutige ID basierend auf Index (da element_nr nicht eindeutig ist)
    vorrangnetz_prepared['unique_id'] = vorrangnetz_prepared.index.astype(str) + '_' + vorrangnetz_prepared['element_nr'].astype(str)
    
    # Detailnetz: Relevante Spalten auswählen und eindeutige ID erstellen
    detailnetz_cols = ['element_nr', 'strassenname', 'strassenklasse', 'beginnt_bei_vp', 'endet_bei_vp', 'geometry']
    detailnetz_prepared = detailnetz[detailnetz_cols].copy()
    
    # Erstelle eindeutige ID für Detailnetz
    detailnetz_prepared['unique_id'] = detailnetz_prepared.index.astype(str) + '_' + detailnetz_prepared['element_nr'].astype(str)
    
    # Leere oder None-Werte behandeln
    detailnetz_prepared['strassenname'] = detailnetz_prepared['strassenname'].fillna('')
    detailnetz_prepared['strassenklasse'] = detailnetz_prepared['strassenklasse'].fillna('')
    
    logger.info(f"Vorrangnetz vorbereitet: {len(vorrangnetz_prepared)} Kanten")
    logger.info(f"Detailnetz vorbereitet: {len(detailnetz_prepared)} Kanten")
    
    # Prüfe auf doppelte element_nr im Vorrangnetz
    duplicate_elements = vorrangnetz_prepared['element_nr'].value_counts()
    duplicates = duplicate_elements[duplicate_elements > 1]
    if len(duplicates) > 0:
        logger.info(f"Gefunden: {len(duplicates)} element_nr mit mehreren Geometrien (wird durch unique_id gelöst)")
    
    return vorrangnetz_prepared, detailnetz_prepared


def find_detailnetz_in_buffer(vorrangnetz, detailnetz, buffer_meters=5):
    """
    Findet alle Detailnetz-Kanten, die sich vollständig im Buffer des Vorrangnetzes befinden.
    
    Args:
        vorrangnetz (GeoDataFrame): Vorrangnetz
        detailnetz (GeoDataFrame): Detailnetz
        buffer_meters (int): Buffer-Radius in Metern
        
    Returns:
        GeoDataFrame: Detailnetz-Kanten im Buffer
    """
    logger.info(f"Erstelle {buffer_meters}m Buffer um Vorrangnetz...")
    
    # Buffer um Vorrangnetz erstellen
    vorrangnetz_buffered = vorrangnetz.copy()
    vorrangnetz_buffered['geometry'] = vorrangnetz_buffered.geometry.buffer(buffer_meters)
    
    # Vereinigten Buffer erstellen für effiziente Spatial Query
    try:
        unified_buffer = vorrangnetz_buffered.geometry.union_all()
    except AttributeError:
        # Fallback für ältere GeoPandas-Versionen
        unified_buffer = vorrangnetz_buffered.geometry.unary_union
    
    logger.info("Suche Detailnetz-Kanten im Buffer...")
    
    # Spatial Index für Performance
    detailnetz_sindex = detailnetz.sindex
    
    # Mögliche Kandidaten über Bounding Box finden
    possible_matches_index = list(detailnetz_sindex.intersection(unified_buffer.bounds))
    possible_matches = detailnetz.iloc[possible_matches_index]
    
    # Exakte Überprüfung: Detailnetz-Geometrie vollständig im Buffer?
    detailnetz_in_buffer = []
    
    for idx, detail_row in possible_matches.iterrows():
        detail_geom = detail_row.geometry
        
        # Prüfe ob Geometrie vollständig im Buffer liegt
        if unified_buffer.contains(detail_geom):
            detailnetz_in_buffer.append(idx)
    
    result = detailnetz.loc[detailnetz_in_buffer].copy()
    logger.info(f"Gefunden: {len(result)} Detailnetz-Kanten im {buffer_meters}m Buffer")
    
    return result


def identify_gaps_in_coverage(vorrangnetz, detailnetz_in_buffer, buffer_meters=5):
    """
    Identifiziert Bereiche im Vorrangnetz, die nicht durch Detailnetz-Kanten abgedeckt sind.
    
    Args:
        vorrangnetz (GeoDataFrame): Vorrangnetz
        detailnetz_in_buffer (GeoDataFrame): Detailnetz-Kanten im Buffer
        buffer_meters (int): Buffer-Radius in Metern
        
    Returns:
        GeoDataFrame: Vorrangnetz-Kanten ohne Detailnetz-Abdeckung
    """
    logger.info("Identifiziere Lücken in der Detailnetz-Abdeckung...")
    
    if len(detailnetz_in_buffer) == 0:
        logger.warning("Keine Detailnetz-Kanten im Buffer gefunden - verwende gesamtes Vorrangnetz")
        return vorrangnetz.copy()
    
    # Buffer um Detailnetz-Kanten erstellen
    detailnetz_buffered = detailnetz_in_buffer.copy()
    detailnetz_buffered['geometry'] = detailnetz_buffered.geometry.buffer(buffer_meters)
    
    # Vereinigten Buffer der Detailnetz-Kanten erstellen
    try:
        detailnetz_coverage = detailnetz_buffered.geometry.union_all()
    except AttributeError:
        # Fallback für ältere GeoPandas-Versionen
        detailnetz_coverage = detailnetz_buffered.geometry.unary_union
    
    # Vorrangnetz-Kanten finden, die NICHT vollständig im Detailnetz-Buffer liegen
    vorrangnetz_gaps = []
    
    for idx, rvn_row in vorrangnetz.iterrows():
        rvn_geom = rvn_row.geometry
        
        # Wenn Vorrangnetz-Geometrie NICHT vollständig im Detailnetz-Coverage liegt
        if not detailnetz_coverage.contains(rvn_geom):
            vorrangnetz_gaps.append(idx)
    
    result = vorrangnetz.loc[vorrangnetz_gaps].copy()
    logger.info(f"Gefunden: {len(result)} Vorrangnetz-Kanten ohne Detailnetz-Abdeckung")
    
    return result


def combine_datasets(detailnetz_in_buffer, vorrangnetz_gaps):
    """
    Kombiniert Detailnetz-Kanten und Vorrangnetz-Lücken zu einem finalen Datensatz.
    
    Args:
        detailnetz_in_buffer (GeoDataFrame): Detailnetz-Kanten im Buffer
        vorrangnetz_gaps (GeoDataFrame): Vorrangnetz-Kanten ohne Abdeckung
        
    Returns:
        GeoDataFrame: Kombinierter finaler Datensatz
    """
    logger.info("Kombiniere Datensätze...")
    
    # Für Vorrangnetz-Kanten: Fehlende Spalten mit leeren Werten ergänzen
    if len(vorrangnetz_gaps) > 0:
        vorrangnetz_enhanced = vorrangnetz_gaps.copy()
        vorrangnetz_enhanced['strassenname'] = ''
        vorrangnetz_enhanced['strassenklasse'] = ''
        vorrangnetz_enhanced['edge_source'] = 'rvn'
        
        # Spalten in gleicher Reihenfolge wie Detailnetz
        target_columns = ['unique_id', 'element_nr', 'strassenname', 'strassenklasse', 'beginnt_bei_vp', 'endet_bei_vp', 'edge_source', 'geometry']
        vorrangnetz_enhanced = vorrangnetz_enhanced[target_columns]
    else:
        vorrangnetz_enhanced = gpd.GeoDataFrame(columns=['unique_id', 'element_nr', 'strassenname', 'strassenklasse', 'beginnt_bei_vp', 'endet_bei_vp', 'edge_source', 'geometry'])
    
    # Detailnetz-Kanten: Spalten in richtiger Reihenfolge und Quelle hinzufügen
    if len(detailnetz_in_buffer) > 0:
        detailnetz_selected = detailnetz_in_buffer.copy()
        detailnetz_selected['edge_source'] = 'detailnetz'
        target_columns = ['unique_id', 'element_nr', 'strassenname', 'strassenklasse', 'beginnt_bei_vp', 'endet_bei_vp', 'edge_source', 'geometry']
        detailnetz_selected = detailnetz_selected[target_columns]
    else:
        detailnetz_selected = gpd.GeoDataFrame(columns=['unique_id', 'element_nr', 'strassenname', 'strassenklasse', 'beginnt_bei_vp', 'endet_bei_vp', 'edge_source', 'geometry'])
    
    # Kombinieren
    combined = pd.concat([detailnetz_selected, vorrangnetz_enhanced], ignore_index=True)
    combined_gdf = gpd.GeoDataFrame(combined, crs=f"EPSG:{DEFAULT_CRS}")
    
    logger.info(f"Finaler Datensatz: {len(combined_gdf)} Kanten")
    logger.info(f"  - Detailnetz-Kanten: {len(detailnetz_selected)}")
    logger.info(f"  - Vorrangnetz-Lücken: {len(vorrangnetz_enhanced)}")
    
    return combined_gdf


def check_for_duplicates(combined_gdf):
    """
    Überprüft auf doppelte Kanten im finalen Datensatz.
    Verwendet unique_id für exakte Duplikat-Erkennung.
    
    Args:
        combined_gdf (GeoDataFrame): Kombinierter Datensatz
        
    Returns:
        GeoDataFrame: Datensatz ohne Duplikate
    """
    logger.info("Überprüfe auf Duplikate...")
    
    initial_count = len(combined_gdf)
    
    # Duplikate basierend auf unique_id entfernen (eindeutige Geometrie-basierte ID)
    combined_unique = combined_gdf.drop_duplicates(
        subset=['unique_id'], 
        keep='first'
    )
    
    duplicates_removed = initial_count - len(combined_unique)
    
    if duplicates_removed > 0:
        logger.warning(f"Entfernt: {duplicates_removed} doppelte Kanten basierend auf unique_id")
    else:
        logger.info("Keine Duplikate gefunden")
    
    # Entferne unique_id aus finaler Ausgabe (wird nur intern benötigt)
    if 'unique_id' in combined_unique.columns:
        combined_unique = combined_unique.drop(columns=['unique_id'])
    
    return combined_unique


def filter_excluded_elements(gdf):
    """
    Filtert ausgeschlossene element_nr aus dem GeoDataFrame.
    
    Args:
        gdf (GeoDataFrame): Eingabe-GeoDataFrame
        
    Returns:
        GeoDataFrame: Gefilterter GeoDataFrame ohne ausgeschlossene Elemente
    """
    if not EXCLUDED_ELEMENT_NRS:
        logger.info("Keine element_nr zum Ausschließen konfiguriert")
        return gdf
    
    initial_count = len(gdf)
    
    # Filtere Kanten mit ausgeschlossenen element_nr heraus
    filtered_gdf = gdf[~gdf['element_nr'].isin(EXCLUDED_ELEMENT_NRS)].copy()
    
    excluded_count = initial_count - len(filtered_gdf)
    
    if excluded_count > 0:
        logger.info(f"Ausgeschlossen: {excluded_count} Kanten mit element_nr in {EXCLUDED_ELEMENT_NRS}")
        # Zeige welche element_nr tatsächlich gefunden und ausgeschlossen wurden
        found_excluded = gdf[gdf['element_nr'].isin(EXCLUDED_ELEMENT_NRS)]['element_nr'].unique()
        if len(found_excluded) > 0:
            logger.info(f"  - Gefundene und ausgeschlossene element_nr: {list(found_excluded)}")
    else:
        logger.info(f"Keine der konfigurierten element_nr ({EXCLUDED_ELEMENT_NRS}) im Datensatz gefunden")
    
    return filtered_gdf


def save_result(combined_gdf, output_path):
    """
    Speichert den finalen Datensatz.
    
    Args:
        combined_gdf (GeoDataFrame): Finaler Datensatz
        output_path (str): Ausgabepfad
    """
    logger.info(f"Speichere Ergebnis nach: {output_path}")
    
    # Ausgabeverzeichnis erstellen falls nicht vorhanden
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    # Speichern
    combined_gdf.to_file(output_path, driver='FlatGeobuf')
    
    logger.info(f"Erfolgreich gespeichert: {len(combined_gdf)} Kanten")


def main():
    """
    Hauptfunktion des Skripts.
    """
    try:
        logger.info("=== Starte Anreicherung des Radvorrangnetzes ===")
        
        # 1. Input-Daten laden
        vorrangnetz, detailnetz = load_input_data()
        
        # 2. Datensätze vorbereiten
        vorrangnetz_prep, detailnetz_prep = prepare_datasets(vorrangnetz, detailnetz)
        
        # 3. Detailnetz-Kanten im Buffer finden
        detailnetz_in_buffer = find_detailnetz_in_buffer(vorrangnetz_prep, detailnetz_prep, buffer_meters=5)
        
        # 4. Lücken im Vorrangnetz identifizieren
        vorrangnetz_gaps = identify_gaps_in_coverage(vorrangnetz_prep, detailnetz_in_buffer, buffer_meters=5)
        
        # 5. Datensätze kombinieren
        combined_gdf = combine_datasets(detailnetz_in_buffer, vorrangnetz_gaps)
        
        # 6. Duplikate entfernen
        final_gdf = check_for_duplicates(combined_gdf)
        
        # 7. Ausgeschlossene element_nr entfernen
        final_gdf = filter_excluded_elements(final_gdf)
        
        # 8. Ergebnis speichern
        output_path = "output/rvn/vorrangnetz_details_combined_rvn.fgb"
        save_result(final_gdf, output_path)
        
        logger.info("=== Anreicherung erfolgreich abgeschlossen ===")
        
    except Exception as e:
        logger.error(f"Fehler beim Ausführen des Skripts: {str(e)}")
        raise


if __name__ == "__main__":
    main()
