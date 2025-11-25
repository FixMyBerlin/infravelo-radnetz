#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
override_edges.py
--------------------------------------------------------------------
Enthält Funktionen für das manuelle Überschreiben von Kanten-Richtungen.

Unterstützt vier Modi:
1. Remove-Modus: Entfernt ri=1 komplett
2. Gegenrichtung-Modus: Setzt ri=1 auf "Keine Radinfrastruktur vorhanden"
3. Hinrichtung-Modus: Setzt ri=0 auf "Keine Radinfrastruktur vorhanden"
4. Beide-Modus: Setzt ri=0 UND ri=1 auf "Keine Radinfrastruktur vorhanden"
"""

import logging
from pathlib import Path


def load_opposite_edge_overwrite_list(data_dir, filename="opposite_edge_overwrite_element_nr.txt"):
    """
    Lädt die Liste der element_nr, für die die Rückrichtung (ri=1) verarbeitet werden soll.
    
    Unterstützt vier Modi:
    1. element_nr alleine: Entfernt ri=1 komplett (alte Funktionalität)
    2. element_nr|Gegenrichtung: Setzt ri=1 auf "Keine Radinfrastruktur vorhanden"
    3. element_nr|Hinrichtung: Setzt ri=0 auf "Keine Radinfrastruktur vorhanden"
    4. element_nr|Beide: Setzt ri=0 UND ri=1 auf "Keine Radinfrastruktur vorhanden"
    
    Format:
    - 40450020_40450004.01                  # Entfernt ri=1
    - 40450020_40450004.01|Gegenrichtung    # Setzt ri=1 auf "Keine Radinfra"
    - 49510013_49510004.01|Hinrichtung      # Setzt ri=0 auf "Keine Radinfra"
    - 49510013_49510004.01|Beide            # Setzt ri=0 UND ri=1 auf "Keine Radinfra"
    
    Args:
        data_dir: Verzeichnis mit der Datei opposite_edge_overwrite_element_nr.txt
        filename: Name der Datei (Standard: opposite_edge_overwrite_element_nr.txt)
    
    Returns:
        dict: Dictionary mit vier Keys:
            - 'remove': set von element_nr (Strings), für die ri=1 entfernt werden soll
            - 'keine_infra_ri1': set von element_nr für ri=1 → "Keine Radinfra"
            - 'keine_infra_ri0': set von element_nr für ri=0 → "Keine Radinfra"
            - 'keine_infra_beide': set von element_nr für ri=0+ri=1 → "Keine Radinfra"
    """
    file_path = Path(data_dir) / filename
    
    if not file_path.exists():
        logging.info(f"Keine Opposite-Edge-Overwrite-Liste gefunden: {file_path}")
        return {'remove': set(), 'keine_infra_ri1': set(), 'keine_infra_ri0': set(), 'keine_infra_beide': set()}
    
    element_nrs_remove = set()
    element_nrs_keine_infra_ri1 = set()  # Gegenrichtung
    element_nrs_keine_infra_ri0 = set()  # Hinrichtung
    element_nrs_keine_infra_beide = set()  # Beide
    
    with open(file_path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            # Entferne Whitespace und Kommentare
            line = line.strip()
            
            # Überspringe leere Zeilen und Kommentare
            if not line or line.startswith('#'):
                continue
            
            # Parse neue Syntax: element_nr|Modus
            if '|' in line:
                parts = line.split('|', 1)
                if len(parts) == 2:
                    element_nr = parts[0].strip()
                    mode = parts[1].strip().lower()
                    
                    # Gegenrichtung (ri=1) - neue und alte Schreibweisen
                    if mode in ['gegenrichtung', 'gegen', 'ri1', 'true', 'keineradinfra', 'keine_radinfra', 'keineinfra']:
                        element_nrs_keine_infra_ri1.add(element_nr)
                        logging.debug(f"  Zeile {line_num}: '{element_nr}' → Gegenrichtung (ri=1) KeineRadinfra-Modus")
                    # Hinrichtung (ri=0)
                    elif mode in ['hinrichtung', 'hin', 'ri0']:
                        element_nrs_keine_infra_ri0.add(element_nr)
                        logging.debug(f"  Zeile {line_num}: '{element_nr}' → Hinrichtung (ri=0) KeineRadinfra-Modus")
                    # Beide (ri=0 + ri=1)
                    elif mode in ['beide', 'both', 'all', 'beiderichtungen']:
                        element_nrs_keine_infra_beide.add(element_nr)
                        logging.debug(f"  Zeile {line_num}: '{element_nr}' → Beide Richtungen KeineRadinfra-Modus")
                    else:
                        logging.warning(
                            f"Zeile {line_num}: Unbekannter Modus '{mode}' für element_nr={element_nr} - "
                            f"verwende Remove-Modus (gültig: Gegenrichtung, Hinrichtung, Beide)"
                        )
                        element_nrs_remove.add(element_nr)
                else:
                    # Ungültiges Format mit |, behandle als Remove
                    logging.warning(f"Zeile {line_num}: Ungültiges Format '{line}' - verwende Remove-Modus")
                    element_nrs_remove.add(line)
            else:
                # Alte Syntax: nur element_nr (Remove-Modus)
                element_nrs_remove.add(line)
                logging.debug(f"  Zeile {line_num}: '{line}' → Remove-Modus")
    
    total = len(element_nrs_remove) + len(element_nrs_keine_infra_ri1) + len(element_nrs_keine_infra_ri0) + len(element_nrs_keine_infra_beide)
    if total > 0:
        logging.info(
            f"✔  Opposite-Edge-Overwrite-Liste geladen: {total} element_nr(s) aus {file_path} "
            f"(Remove: {len(element_nrs_remove)}, Gegenrichtung: {len(element_nrs_keine_infra_ri1)}, "
            f"Hinrichtung: {len(element_nrs_keine_infra_ri0)}, Beide: {len(element_nrs_keine_infra_beide)})"
        )
    else:
        logging.info(f"Opposite-Edge-Overwrite-Liste ist leer: {file_path}")
    
    return {
        'remove': element_nrs_remove,
        'keine_infra_ri1': element_nrs_keine_infra_ri1,
        'keine_infra_ri0': element_nrs_keine_infra_ri0,
        'keine_infra_beide': element_nrs_keine_infra_beide
    }


def _set_keine_radinfra_for_direction(gdf, element_nrs, ri_value, merge_attributes, additional_attributes):
    """
    Hilfsfunktion: Setzt "Keine Radinfrastruktur vorhanden" für die angegebene Richtung.
    Entfernt doppelten Code aus den drei Modi (Gegenrichtung, Hinrichtung, Beide).
    
    Args:
        gdf: GeoDataFrame mit den Kanten
        element_nrs: Set von element_nr zum Verarbeiten
        ri_value: Richtungswert (0, 1 oder None für beide)
        merge_attributes: Liste der Merge-Attribute zum Zurücksetzen
        additional_attributes: Liste der zusätzlichen Attribute zum Zurücksetzen
    
    Returns:
        tuple: (count, not_found_count) - Anzahl verarbeiteter und nicht gefundener Kanten
    """
    count = 0
    not_found_count = 0
    
    mode_name = "beide Richtungen" if ri_value is None else f"ri={ri_value}"
    
    for element_nr in element_nrs:
        # Maske je nach ri_value
        if ri_value is None:
            mask = gdf['element_nr'] == element_nr
        else:
            mask = (gdf['element_nr'] == element_nr) & (gdf['ri'] == ri_value)
        
        matching_indices = gdf[mask].index
        
        if len(matching_indices) == 0:
            logging.warning(f"  element_nr={element_nr}: NICHT GEFUNDEN in Daten ({mode_name})")
            not_found_count += 1
            continue
        
        # Setze fuehr="Keine Radinfrastruktur vorhanden"
        gdf.loc[matching_indices, 'fuehr'] = 'Keine Radinfrastruktur vorhanden'
        
        # Setze alle anderen Merge-Attribute (außer ri, fuehr) auf None
        for attr in merge_attributes:
            if attr not in ['ri', 'fuehr']:
                if attr in gdf.columns:
                    gdf.loc[matching_indices, attr] = None
        
        # Setze auch zusätzliche Attribute auf None (für Konsistenz)
        for attr in additional_attributes:
            if attr in gdf.columns:
                gdf.loc[matching_indices, attr] = None
        
        logging.info(
            f"  element_nr={element_nr}: Setze {len(matching_indices)} Kante(n) ({mode_name}) auf "
            f"'Keine Radinfrastruktur vorhanden'"
        )
        count += len(matching_indices)
    
    return count, not_found_count


def apply_opposite_edge_overwrite(gdf, opposite_edge_config, merge_attributes, additional_attributes):
    """
    Verarbeitet Rückrichtung (ri=1) für die angegebenen element_nr.
    
    Unterstützt vier Modi:
    1. Remove-Modus: Entfernt ri=1 komplett
    2. Gegenrichtung-Modus: Setzt ri=1 auf "Keine Radinfrastruktur vorhanden"
    3. Hinrichtung-Modus: Setzt ri=0 auf "Keine Radinfrastruktur vorhanden"
    4. Beide-Modus: Setzt ri=0 UND ri=1 auf "Keine Radinfrastruktur vorhanden"
    
    Gibt Warnungen aus, wenn ri=0 verkehrsri="Zweirichtungsverkehr" hat.
    
    Args:
        gdf: GeoDataFrame mit den Kanten
        opposite_edge_config: Dictionary mit 'remove', 'keine_infra_ri1', 'keine_infra_ri0', 'keine_infra_beide' Sets
        merge_attributes: Liste der Merge-Attribute zum Zurücksetzen
        additional_attributes: Liste der zusätzlichen Attribute zum Zurücksetzen
    
    Returns:
        GeoDataFrame: Verarbeitetes GeoDataFrame
    """
    # Kompatibilität: Falls altes Format übergeben wird
    if isinstance(opposite_edge_config, set):
        opposite_edge_config = {'remove': opposite_edge_config, 'keine_infra_ri1': set(), 'keine_infra_ri0': set(), 'keine_infra_beide': set()}
    elif 'keine_infra' in opposite_edge_config:  # Alte Version mit nur 'keine_infra'
        opposite_edge_config = {
            'remove': opposite_edge_config.get('remove', set()),
            'keine_infra_ri1': opposite_edge_config.get('keine_infra', set()),
            'keine_infra_ri0': set(),
            'keine_infra_beide': set()
        }
    
    element_nrs_remove = opposite_edge_config.get('remove', set())
    element_nrs_keine_infra_ri1 = opposite_edge_config.get('keine_infra_ri1', set())
    element_nrs_keine_infra_ri0 = opposite_edge_config.get('keine_infra_ri0', set())
    element_nrs_keine_infra_beide = opposite_edge_config.get('keine_infra_beide', set())
    
    total = len(element_nrs_remove) + len(element_nrs_keine_infra_ri1) + len(element_nrs_keine_infra_ri0) + len(element_nrs_keine_infra_beide)
    
    if total == 0:
        logging.info("Keine Opposite-Edge-Overwrites zu verarbeiten")
        return gdf
    
    logging.info(
        f"Verarbeite Opposite-Edge-Overwrites für {total} element_nr(s) "
        f"(Remove: {len(element_nrs_remove)}, Gegenrichtung: {len(element_nrs_keine_infra_ri1)}, "
        f"Hinrichtung: {len(element_nrs_keine_infra_ri0)}, Beide: {len(element_nrs_keine_infra_beide)})..."
    )
    
    # Zähler für Statistiken
    removed_count = 0
    warning_count = 0
    not_found_count = 0
    
    # Verarbeite Remove-Modus
    for element_nr in element_nrs_remove:
        # Finde alle Kanten mit dieser element_nr
        matching_edges = gdf[gdf['element_nr'] == element_nr]
        
        if len(matching_edges) == 0:
            logging.warning(f"  element_nr={element_nr}: NICHT GEFUNDEN in Daten (Remove-Modus)")
            not_found_count += 1
            continue
        
        # Prüfe ri=0 Kante auf Zweirichtungsverkehr
        ri0_edges = matching_edges[matching_edges['ri'] == 0]
        if len(ri0_edges) > 0:
            for _, edge in ri0_edges.iterrows():
                verkehrsri = edge.get('verkehrsri', None)
                if verkehrsri == 'Zweirichtungsverkehr':
                    logging.warning(
                        f"  ⚠️  element_nr={element_nr} (ri=0): Verkehrsrichtung ist 'Zweirichtungsverkehr' "
                        f"- BITTE MANUELL PRÜFEN ob Rückrichtung wirklich entfernt werden soll!"
                    )
                    warning_count += 1
        
        # Entferne ri=1 Kanten
        ri1_edges = matching_edges[matching_edges['ri'] == 1]
        if len(ri1_edges) > 0:
            logging.info(f"  element_nr={element_nr}: Entferne {len(ri1_edges)} ri=1 Kante(n)")
            removed_count += len(ri1_edges)
    
    # Filtere das GeoDataFrame (Remove-Modus)
    original_count = len(gdf)
    mask = ~((gdf['element_nr'].isin(element_nrs_remove)) & (gdf['ri'] == 1))
    gdf = gdf[mask].copy()
    
    # Verarbeite die drei "Keine Radinfra"-Modi mit der Hilfsfunktion
    keine_infra_ri1_count, nf1 = _set_keine_radinfra_for_direction(
        gdf, element_nrs_keine_infra_ri1, 1, merge_attributes, additional_attributes
    )
    not_found_count += nf1
    
    keine_infra_ri0_count, nf0 = _set_keine_radinfra_for_direction(
        gdf, element_nrs_keine_infra_ri0, 0, merge_attributes, additional_attributes
    )
    not_found_count += nf0
    
    keine_infra_beide_count, nfb = _set_keine_radinfra_for_direction(
        gdf, element_nrs_keine_infra_beide, None, merge_attributes, additional_attributes
    )
    not_found_count += nfb
    
    logging.info(
        f"✔  Opposite-Edge-Overwrite abgeschlossen: "
        f"{removed_count} ri=1 Kante(n) entfernt, "
        f"{keine_infra_ri1_count} Gegenrichtung (ri=1), "
        f"{keine_infra_ri0_count} Hinrichtung (ri=0), "
        f"{keine_infra_beide_count} Beide Richtungen auf 'Keine Radinfra' gesetzt, "
        f"{warning_count} Warnung(en), "
        f"{not_found_count} nicht gefunden"
    )
    logging.info(f"   Kanten vorher: {original_count}, nachher: {len(gdf)}")
    
    return gdf
