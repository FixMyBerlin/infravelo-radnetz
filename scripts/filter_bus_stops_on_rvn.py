#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
filter_bus_stops_on_rvn.py
--------------------------------------------------------------------
Filtert Bushaltestellen aus data/Stop-Positions-Bus-OSM.fgb, die sich 
auf dem Radvorrangsnetz befinden (mit 15m Puffer).

INPUT:
- data/Stop-Positions-Bus-OSM.fgb (Bushaltestellen aus OSM)
- output/matching/vorrangnetz_buffered_15m_round.fgb (gepuffertes RVN)

OUTPUT:
- output/bus_stops_on_rvn.fgb (gefilterte Bushaltestellen auf RVN)
"""

import geopandas as gpd
import os
import logging
from pathlib import Path

# Logging konfigurieren
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def filter_bus_stops_on_rvn():
    """
    Hauptfunktion: Filtert Bushaltestellen, die sich auf dem Radvorrangsnetz befinden.
    """
    # Pfade definieren
    bus_stops_path = "data/Stop-Positions-Bus-OSM.fgb"
    rvn_buffered_path = "output/matching/vorrangnetz_buffered_15m_round.fgb"
    output_path = "output/bus_stops_on_rvn.fgb"
    
    # Überprüfen, ob Eingabedateien existieren
    if not os.path.exists(bus_stops_path):
        logging.error(f"Bushaltestellen-Datei nicht gefunden: {bus_stops_path}")
        return False
        
    if not os.path.exists(rvn_buffered_path):
        logging.error(f"Gepuffertes RVN nicht gefunden: {rvn_buffered_path}")
        logging.info("Hinweis: Führe zuerst das Matching/Processing aus, um das gepufferte RVN zu erstellen.")
        return False
    
    try:
        # 1. Bushaltestellen laden
        logging.info(f"Lade Bushaltestellen aus {bus_stops_path}")
        bus_stops_gdf = gpd.read_file(bus_stops_path)
        logging.info(f"Bushaltestellen geladen: {len(bus_stops_gdf)} Punkte")
        
        # Informationen über die geladenen Daten
        logging.info(f"CRS der Bushaltestellen: {bus_stops_gdf.crs}")
        if hasattr(bus_stops_gdf, 'columns'):
            logging.info(f"Verfügbare Spalten: {list(bus_stops_gdf.columns)}")
        
        # 2. Gepuffertes Radvorrangsnetz laden
        logging.info(f"Lade gepuffertes Radvorrangsnetz aus {rvn_buffered_path}")
        rvn_buffered_gdf = gpd.read_file(rvn_buffered_path)
        logging.info(f"Gepuffertes RVN geladen: {len(rvn_buffered_gdf)} Polygone")
        logging.info(f"CRS des gepufferten RVN: {rvn_buffered_gdf.crs}")
        
        # 3. CRS angleichen (beide auf EPSG:25833 - UTM Zone 33N für Berlin)
        target_crs = "EPSG:25833"
        
        if bus_stops_gdf.crs != target_crs:
            logging.info(f"Transformiere Bushaltestellen von {bus_stops_gdf.crs} nach {target_crs}")
            bus_stops_gdf = bus_stops_gdf.to_crs(target_crs)
            
        if rvn_buffered_gdf.crs != target_crs:
            logging.info(f"Transformiere gepuffertes RVN von {rvn_buffered_gdf.crs} nach {target_crs}")
            rvn_buffered_gdf = rvn_buffered_gdf.to_crs(target_crs)
        
        # 4. Nur Punkt-Geometrien behalten (falls andere Geometrietypen vorhanden)
        original_count = len(bus_stops_gdf)
        bus_stops_gdf = bus_stops_gdf[bus_stops_gdf.geometry.type == 'Point']
        if len(bus_stops_gdf) < original_count:
            logging.warning(f"Nicht-Punkt-Geometrien entfernt: {original_count - len(bus_stops_gdf)} Objekte")
            logging.info(f"Verbleibende Punkt-Geometrien: {len(bus_stops_gdf)}")
        
        # 5. Räumlicher Join: Finde Bushaltestellen, die innerhalb des gepufferten RVN liegen
        logging.info("Führe räumlichen Join durch...")
        bus_stops_on_rvn = gpd.sjoin(bus_stops_gdf, rvn_buffered_gdf, how="inner", predicate='within')
        
        # 6. Duplikate entfernen (falls eine Bushaltestelle mehrere RVN-Segmente trifft)
        # Behalte nur die originalen Bushaltestellen-Spalten
        original_columns = bus_stops_gdf.columns.tolist()
        if 'geometry' not in original_columns:
            original_columns.append('geometry')
            
        bus_stops_on_rvn = bus_stops_on_rvn[original_columns].drop_duplicates()
        
        logging.info(f"Bushaltestellen auf RVN gefunden: {len(bus_stops_on_rvn)} von {len(bus_stops_gdf)} ({len(bus_stops_on_rvn)/len(bus_stops_gdf)*100:.1f}%)")
        
        # 7. Ausgabeverzeichnis erstellen falls nötig
        output_dir = os.path.dirname(output_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        
        # 8. Ergebnis speichern
        logging.info(f"Speichere gefilterte Bushaltestellen nach {output_path}")
        bus_stops_on_rvn.to_file(output_path, driver='FlatGeobuf')
        
        # 9. Statistiken ausgeben
        logging.info("=" * 60)
        logging.info("ZUSAMMENFASSUNG:")
        logging.info(f"Eingabe Bushaltestellen: {len(bus_stops_gdf)}")
        logging.info(f"Bushaltestellen auf RVN (15m Puffer): {len(bus_stops_on_rvn)}")
        logging.info(f"Anteil auf RVN: {len(bus_stops_on_rvn)/len(bus_stops_gdf)*100:.1f}%")
        logging.info(f"Ausgabedatei: {output_path}")
        logging.info("=" * 60)
        
        return True
        
    except Exception as e:
        logging.error(f"Fehler beim Verarbeiten der Daten: {e}")
        return False

if __name__ == "__main__":
    success = filter_bus_stops_on_rvn()
    if success:
        logging.info("Skript erfolgreich abgeschlossen.")
    else:
        logging.error("Skript mit Fehlern beendet.")
        exit(1)
