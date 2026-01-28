#!/usr/bin/env python3
"""
Validierungsskript: Überprüft, ob Wege sowohl in exclude_ways.txt als auch in include_ways.txt vorkommen.
Ein Weg darf nicht in beiden Dateien gleichzeitig sein.
"""

import sys
from pathlib import Path


def load_ways(file_path: Path) -> set[str]:
    """Lädt OSM-Way-IDs aus einer Textdatei (ignoriert Kommentare und Leerzeilen)."""
    ways = set()
    if not file_path.exists():
        print(f"Warnung: Datei {file_path} existiert nicht.")
        return ways
    
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            # Ignoriere Kommentare und Leerzeilen
            if line and not line.startswith('#'):
                ways.add(line)
    
    return ways


def main():
    # Pfade zu den Dateien
    base_dir = Path(__file__).parent.parent
    exclude_file = base_dir / 'data' / 'exclude_ways.txt'
    include_file = base_dir / 'data' / 'include_ways.txt'
    
    # Lade die Wege aus beiden Dateien
    exclude_ways = load_ways(exclude_file)
    include_ways = load_ways(include_file)
    
    # Finde Überschneidungen
    duplicates = exclude_ways & include_ways
    
    # Ausgabe
    print(f"Anzahl Wege in exclude_ways.txt: {len(exclude_ways)}")
    print(f"Anzahl Wege in include_ways.txt: {len(include_ways)}")
    print(f"Anzahl doppelter Wege: {len(duplicates)}")
    print()
    
    if duplicates:
        print("FEHLER: Die folgenden Wege sind in beiden Dateien vorhanden:")
        print("=" * 60)
        for way_id in sorted(duplicates):
            print(f"  - {way_id}")
        print("=" * 60)
        print()
        print("Diese Wege müssen aus einer der beiden Dateien entfernt werden!")
        sys.exit(1)
    else:
        print("✓ Validierung erfolgreich: Keine Überschneidungen gefunden.")
        sys.exit(0)


if __name__ == "__main__":
    main()
