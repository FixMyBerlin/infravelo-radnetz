import argparse
import sys
from pathlib import Path

# Importiere die enrich-Funktion
from snapping.enrich_streetnet_with_osm import enrich_network_with_osm, BUFFER_DEFAULT

MAX_ANGLE_DEFAULT = 65.0  # Standard für maximalen Winkelunterschied

def main():
    parser = argparse.ArgumentParser(description='Starte die Anreicherung des Straßennetzes mit OSM-Attributen')
    parser.add_argument('network_path', help='Pfad zur Netzwerk-Datei')
    parser.add_argument('osm_path', help='Pfad zur OSM-Datei')
    parser.add_argument('output_path', help='Pfad für die Ausgabe-Datei')
    parser.add_argument('--buffer', type=float, default=BUFFER_DEFAULT, help=f'Puffergröße in Metern (Standard: {BUFFER_DEFAULT})')
    parser.add_argument('--max-angle', type=float, default=MAX_ANGLE_DEFAULT, help=f'Maximaler erlaubter Winkelunterschied in Grad (Standard: {MAX_ANGLE_DEFAULT})')
    args = parser.parse_args()

    # Prüfe Eingabedateien
    if not Path(args.network_path).exists():
        print(f"Fehler: Netzwerk-Datei nicht gefunden: {args.network_path}")
        sys.exit(1)
    if not Path(args.osm_path).exists():
        print(f"Fehler: OSM-Datei nicht gefunden: {args.osm_path}")
        sys.exit(1)

    # Starte die Anreicherung
    enrich_network_with_osm(
        args.network_path,
        args.osm_path,
        args.output_path,
        args.buffer,
        args.max_angle
    )

if __name__ == '__main__':
    main()
