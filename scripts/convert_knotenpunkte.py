#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
convert_knotenpunkte.py
-----------------------
Konvertiert die Knotenpunkte-Datei von GeoPackage in GeoJSON-Format und 
fügt virtuelle Knotenpunkte hinzu.

Dieses Skript lädt die Datei `knotenpunkte_mit_id_und_bezirken.gpkg` aus dem 
data-raw-tilda Verzeichnis sowie die virtuellen Knotenpunkte aus 
`Virtuelle-Knotenpunkte.gpkg` aus dem data Verzeichnis. Beide werden 
zusammengeführt und in das GeoJSON-Format mit Standard-Projektion 
(WGS84, EPSG:4326) konvertiert.

INPUT:
- data-raw-tilda/knotenpunkte_mit_id_und_bezirken.gpkg
- data/Virtuelle-Knotenpunkte.gpkg

OUTPUT:
- output/knotenpunkte_mit_id_und_bezirken.geojson (in WGS84)

VERWENDUNG:
    python scripts/convert_knotenpunkte.py

Das Ergebnis wird immer als GeoJSON in WGS84 (EPSG:4326) exportiert, um der 
GeoJSON-Spezifikation zu entsprechen. Virtuelle Knotenpunkte werden mit dem 
Attribut `ist_virtuell=1` markiert.
"""

import logging
import sys
import os

import geopandas as gpd
import pandas as pd

# Konfiguration für Pfade
INPUT_FILE = "./data-raw-tilda/knotenpunkte_mit_id_und_bezirken.gpkg"
VIRTUAL_KNOTENPUNKTE_FILE = "./data/Virtuelle-Knotenpunkte.gpkg"
OUTPUT_DIR = "./output/"
OUTPUT_FILE = "knotenpunkte_mit_id_und_bezirken.geojson"


def setup_logging():
    """Konfiguriert das Logging für das Skript."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )


def load_and_merge_virtual_knotenpunkte(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Lädt die virtuellen Knotenpunkte und fügt sie dem GeoDataFrame hinzu.
    
    Virtuelle Knotenpunkte werden mit dem Attribut `ist_virtuell=1` markiert.
    Die Spalte `Knotenpunkt-ID` aus der virtuellen Datei wird auf die Spalte
    `Knotenpunkt‐ID` der Hauptdatei gemappt (Bindestrich vs. Unicode-Hyphen).
    
    Args:
        gdf: GeoDataFrame mit den regulären Knotenpunkten
        
    Returns:
        GeoDataFrame mit regulären und virtuellen Knotenpunkten zusammengeführt
    """
    if not os.path.exists(VIRTUAL_KNOTENPUNKTE_FILE):
        logging.warning(f"Virtuelle Knotenpunkte-Datei nicht gefunden: {VIRTUAL_KNOTENPUNKTE_FILE}")
        logging.warning("Fahre ohne virtuelle Knotenpunkte fort.")
        return gdf
    
    logging.info(f"Lade virtuelle Knotenpunkte: {VIRTUAL_KNOTENPUNKTE_FILE}")
    
    # Lade virtuelle Knotenpunkte
    virtual_gdf = gpd.read_file(VIRTUAL_KNOTENPUNKTE_FILE)
    
    logging.info(f"Anzahl virtuelle Knotenpunkte geladen: {len(virtual_gdf)}")
    logging.info(f"Spalten virtuelle Knotenpunkte: {list(virtual_gdf.columns)}")
    
    # Markiere als virtuell
    virtual_gdf['ist_virtuell'] = 1
    
    # Mappe Spaltenname: "Knotenpunkt-ID" (normaler Bindestrich) -> "Knotenpunkt‐ID" (Unicode-Hyphen)
    # Die Hauptdatei verwendet einen Unicode-Hyphen (U+2010), die virtuelle Datei einen ASCII-Hyphen
    if 'Knotenpunkt-ID' in virtual_gdf.columns:
        # Finde den korrekten Spaltennamen in der Hauptdatei (mit Unicode-Hyphen)
        kp_id_col = [col for col in gdf.columns if 'Knotenpunkt' in col and 'ID' in col]
        if kp_id_col:
            virtual_gdf = virtual_gdf.rename(columns={'Knotenpunkt-ID': kp_id_col[0]})
            logging.info(f"Spalte 'Knotenpunkt-ID' umbenannt zu '{kp_id_col[0]}'")
    
    # Stelle sicher, dass beide GeoDataFrames das gleiche CRS haben
    if virtual_gdf.crs != gdf.crs:
        logging.info(f"Konvertiere virtuelle Knotenpunkte von {virtual_gdf.crs} zu {gdf.crs}")
        virtual_gdf = virtual_gdf.to_crs(gdf.crs)
    
    # Füge die virtuellen Knotenpunkte hinzu
    # pandas.concat fügt fehlende Spalten automatisch mit NaN-Werten hinzu
    combined_gdf = pd.concat([gdf, virtual_gdf], ignore_index=True)
    
    # Konvertiere zurück zu GeoDataFrame (concat kann den Typ verlieren)
    combined_gdf = gpd.GeoDataFrame(combined_gdf, geometry='geometry', crs=gdf.crs)
    
    logging.info(f"Zusammengeführte Knotenpunkte: {len(combined_gdf)} (davon {len(virtual_gdf)} virtuell)")
    
    return combined_gdf


def convert_knotenpunkte_to_geojson():
    """
    Konvertiert die Knotenpunkte-Datei von GeoPackage zu GeoJSON
    und fügt virtuelle Knotenpunkte hinzu.
    
    Returns:
        bool: True wenn erfolgreich, False bei Fehler
    """
    try:
        # Überprüfe ob Eingabedatei existiert
        if not os.path.exists(INPUT_FILE):
            logging.error(f"Eingabedatei nicht gefunden: {INPUT_FILE}")
            return False
        
        # Erstelle Output-Verzeichnis falls es nicht existiert
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        
        # Vollständiger Pfad zur Ausgabedatei
        output_path = os.path.join(OUTPUT_DIR, OUTPUT_FILE)
        
        logging.info(f"Lade Knotenpunkte-Datei: {INPUT_FILE}")
        
        # Lade die GeoPackage-Datei
        gdf = gpd.read_file(INPUT_FILE)
        
        logging.info(f"Anzahl Features geladen: {len(gdf)}")
        logging.info(f"Spalten: {list(gdf.columns)}")
        logging.info(f"Ursprüngliches CRS: {gdf.crs}")
        
        # Markiere alle regulären Knotenpunkte als nicht-virtuell
        gdf['ist_virtuell'] = 0
        
        # Lade und füge virtuelle Knotenpunkte hinzu
        gdf = load_and_merge_virtual_knotenpunkte(gdf)
        
        # Ersetze NULL-Werte und "(NULL)"-Strings durch "keine" für spezifische Attribute
        # Aber nur, wenn KP_Nichtbetrachten = 0 ist
        null_replacement_columns = ['Mar_RVF_KP', 'Furt_rot', 'Fl_Linksab', 'vorgez_Fl', 'RFS_Mitte']
        
        if 'KP_Nichtbetrachten' in gdf.columns:
            # Erstelle Maske für Zeilen mit KP_Nichtbetrachten = 0
            mask = gdf['KP_Nichtbetrachten'] == 0
            rows_to_process = mask.sum()
            logging.info(f"Anzahl Zeilen mit KP_Nichtbetrachten = 0: {rows_to_process}")
            
            for col in null_replacement_columns:
                if col in gdf.columns:
                    # Zähle echte NULL-Werte (NaN) bei KP_Nichtbetrachten = 0
                    null_count = (gdf.loc[mask, col].isna()).sum()
                    # Zähle "(NULL)"-String-Werte bei KP_Nichtbetrachten = 0
                    string_null_count = (gdf.loc[mask, col] == "(NULL)").sum()
                    
                    if null_count > 0:
                        # Ersetze echte NULL nur bei KP_Nichtbetrachten = 0
                        gdf.loc[mask, col] = gdf.loc[mask, col].fillna('keine')
                        logging.info(f"Ersetze {null_count} NULL-Werte in Spalte '{col}' durch 'keine' (nur bei KP_Nichtbetrachten = 0)")
                    
                    if string_null_count > 0:
                        # Ersetze "(NULL)"-Strings nur bei KP_Nichtbetrachten = 0
                        string_null_mask = mask & (gdf[col] == "(NULL)")
                        gdf.loc[string_null_mask, col] = 'keine'
                        logging.info(f"Ersetze {string_null_count} '(NULL)'-Strings in Spalte '{col}' durch 'keine' (nur bei KP_Nichtbetrachten = 0)")
                else:
                    logging.warning(f"Spalte '{col}' nicht in Datei gefunden")
        else:
            logging.warning("Spalte 'KP_Nichtbetrachten' nicht gefunden - keine NULL-Ersetzung durchgeführt")
        
        # Konvertiere zu WGS84 (EPSG:4326) für GeoJSON
        if gdf.crs is not None and gdf.crs.to_string() != 'EPSG:4326':
            logging.info("Konvertiere CRS zu WGS84 (EPSG:4326)")
            gdf = gdf.to_crs('EPSG:4326')
        elif gdf.crs is None:
            logging.warning("Kein CRS definiert - Annahme: bereits WGS84")
        
        # Exportiere als GeoJSON
        logging.info(f"Exportiere als GeoJSON: {output_path}")
        gdf.to_file(output_path, driver='GeoJSON')
        
        logging.info(f"✔ Konvertierung erfolgreich abgeschlossen!")
        logging.info(f"  Ausgabedatei: {output_path}")
        logging.info(f"  Features exportiert: {len(gdf)}")
        
        return True
        
    except Exception as e:
        logging.error(f"Fehler bei der Konvertierung: {e}")
        return False


def main():
    """Hauptfunktion des Skripts."""
    setup_logging()
    
    logging.info("=" * 60)
    logging.info("Starte Konvertierung der Knotenpunkte-Datei")
    logging.info("=" * 60)
    
    success = convert_knotenpunkte_to_geojson()
    
    if success:
        logging.info("=" * 60)
        logging.info("✔ Skript erfolgreich beendet")
        logging.info("=" * 60)
        sys.exit(0)
    else:
        logging.error("=" * 60)
        logging.error("✘ Skript mit Fehlern beendet")
        logging.error("=" * 60)
        sys.exit(1)


if __name__ == "__main__":
    main()