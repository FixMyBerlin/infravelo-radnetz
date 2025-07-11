"""
Dieses Modul behandelt manuelle Eingriffe in den Datenverarbeitungsprozess.
Es ermöglicht das Ausschließen und Einschließen von OSM-Wegen durch vordefinierte Listen.
"""

import os

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
