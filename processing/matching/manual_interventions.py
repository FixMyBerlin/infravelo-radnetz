"""
Dieses Modul behandelt manuelle Eingriffe in den Datenverarbeitungsprozess.
Es ermöglicht das Ausschließen und Einschließen von OSM-Wegen durch vordefinierte Listen.
Sowie das Überschreiben von Attributen durch Override-Konfiguration.
"""

import os
import json
import logging

def read_way_ids_from_file(file_path):
    """
    Liest OSM-Weg-IDs aus einer Textdatei.
    Jede Zeile der Datei sollte eine ID enthalten.
    Kommentare (beginnend mit #) und leere Zeilen werden ignoriert.

    Args:
        file_path (str): Der Pfad zur Textdatei.

    Returns:
        set: Ein Set von OSM-Weg-IDs.
    """
    if not os.path.exists(file_path):
        print(f"Warnung: Datei nicht gefunden: {file_path}")
        return set()

    with open(file_path, 'r') as f:
        lines = f.readlines()

    way_ids = set()
    for line in lines:
        line = line.strip()
        if line and not line.startswith('#'):
            try:
                way_ids.add(int(line))
            except ValueError:
                print(f"Warnung: Ungültige ID in {file_path}: {line}")
    return way_ids

def get_excluded_ways(exclude_file_path='./data/exclude_ways.txt'):
    """
    Ruft die IDs der Wege ab, die explizit ausgeschlossen werden sollen.

    Args:
        exclude_file_path (str): Pfad zur Datei mit den auszuschließenden IDs.

    Returns:
        set: Ein Set von auszuschließenden OSM-Weg-IDs.
    """
    print(f"Lese manuell ausgeschlossene Wege aus {exclude_file_path}...")
    excluded_ids = read_way_ids_from_file(exclude_file_path)
    print(f"{len(excluded_ids)} Wege zum manuellen Ausschluss geladen.")
    return excluded_ids

def get_included_ways(include_file_path='./data/include_ways.txt'):
    """
    Ruft die IDs der Wege ab, die explizit eingeschlossen werden sollen.

    Args:
        include_file_path (str): Pfad zur Datei mit den einzuschließenden IDs.

    Returns:
        set: Ein Set von einzuschließenden OSM-Weg-IDs.
    """
    print(f"Lese manuell eingeschlossene Wege aus {include_file_path}...")
    included_ids = read_way_ids_from_file(include_file_path)
    print(f"{len(included_ids)} Wege zum manuellen Einschluss geladen.")
    return included_ids


def parse_override_entry(line, line_num):
    """
    Parst eine einzelne Override-Zeile im Format:
    tilda_id|element_nr|ri|attributes_json
    
    Args:
        line (str): Die zu parsende Zeile
        line_num (int): Zeilennummer für Fehlerausgabe
    
    Returns:
        dict oder None: Dictionary mit Override-Informationen oder None bei Fehler
        {
            'tilda_id': str,          # z.B. "way/123456"
            'element_nr': str,        # Element-Nummer als String
            'ri': int,                # Richtung (0 oder 1)
            'force_match': bool,      # Ob Match erzwungen werden soll
            'attributes': dict        # Zu überschreibende Attribute
        }
    """
    try:
        parts = line.split('|')
        if len(parts) != 4:
            logging.warning(
                f"Zeile {line_num}: Ungültiges Format (erwartet 4 Teile durch | getrennt): {line}"
            )
            return None
        
        tilda_id, element_nr, ri_str, attributes_json = parts
        
        # Validiere tilda_id Format (sollte "way/123" oder "relation/456" sein)
        tilda_id = tilda_id.strip()
        if not tilda_id or '/' not in tilda_id:
            logging.warning(
                f"Zeile {line_num}: Ungültige tilda_id (erwartet Format 'way/123456'): {tilda_id}"
            )
            return None
        
        # Parse element_nr (als String belassen)
        element_nr = element_nr.strip()
        if not element_nr:
            logging.warning(f"Zeile {line_num}: Leere element_nr: {line}")
            return None
        
        # Parse ri (muss 0 oder 1 sein)
        try:
            ri = int(ri_str.strip())
            if ri not in [0, 1]:
                logging.warning(
                    f"Zeile {line_num}: ri muss 0 oder 1 sein, ist aber {ri}: {line}"
                )
                return None
        except ValueError:
            logging.warning(
                f"Zeile {line_num}: ri muss eine Zahl sein (0 oder 1): {ri_str}"
            )
            return None
        
        # Parse JSON-Attribute
        try:
            attributes = json.loads(attributes_json.strip())
            if not isinstance(attributes, dict):
                logging.warning(
                    f"Zeile {line_num}: attributes_json muss ein JSON-Objekt sein: {attributes_json}"
                )
                return None
        except json.JSONDecodeError as e:
            logging.warning(
                f"Zeile {line_num}: Ungültiges JSON: {attributes_json} (Fehler: {e})"
            )
            return None
        
        # Extrahiere force_match Flag
        force_match = attributes.pop('force_match', False)
        if not isinstance(force_match, bool):
            # Versuche String zu Boolean zu konvertieren
            if isinstance(force_match, str):
                force_match = force_match.lower() in ['true', '1', 'yes']
            else:
                force_match = bool(force_match)
        
        return {
            'tilda_id': tilda_id,
            'element_nr': element_nr,
            'ri': ri,
            'force_match': force_match,
            'attributes': attributes
        }
        
    except Exception as e:
        logging.warning(
            f"Zeile {line_num}: Unerwarteter Fehler beim Parsen: {e} - {line}"
        )
        return None
