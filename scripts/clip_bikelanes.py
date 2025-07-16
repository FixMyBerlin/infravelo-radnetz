#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
clip_bikelanes.py
-----------------
Schneidet eine Vektordatei mit Linien auf die Polygone einer anderen Vektordatei zu.

Dieses Skript verwendet geopandas, um die Linien in der Eingabedatei auf die Grenzen
der Polygone in der Bezirksdatei zuzuschneiden. Linien, die die Grenzen der Polygone
schneiden, werden geteilt.

Nutze den GeoPackage Export von TILDA als Input.

Aufrufbeispiel:
    python ./scripts/clip_bikelanes.py \\
        --input ./bikelanes.fgb \\
        --clip-features ./data/"Berlin Bezirke.gpkg" \\
        --output ./TILDA Radwege Berlin.fgb


Nutzen für TILDA roads Datensatz:
    python ./scripts/clip_bikelanes.py   \
        --input ./roads.fgb \
        --clip-features ./data/"Berlin Bezirke.gpkg" \
        --output ./roads_berlin.fgb

"""

import argparse
import logging
import sys

import geopandas as gpd

# Konfiguriere das Logging
logging.basicConfig(stream=sys.stdout, level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')


def clip_geodata(input_path: str, clip_features_path: str, output_path: str):
    """
    Schneidet die Geodaten aus der Eingabedatei auf die Grenzen der Features in der
    Clip-Datei zu und speichert das Ergebnis.

    :param input_path: Pfad zur Eingabedatei (z.B. bikelanes.fgb).
    :param clip_features_path: Pfad zur Datei mit den Polygonen für den Zuschnitt
                               (z.B. Berlin Bezirke.gpkg).
    :param output_path: Pfad zur Ausgabedatei (z.B. TILDA Radwege Berlin.fgb).
    """
    try:
        # Lade die Eingabedatei mit den Linien
        logging.info(f"Lade Eingabedatei: {input_path}")
        features_to_clip = gpd.read_file(input_path)

        # Lade die Polygone für den Zuschnitt
        logging.info(f"Lade Clip-Features: {clip_features_path}")
        clip_polygons = gpd.read_file(clip_features_path)

        # Überprüfe und vereinheitliche das Koordinatenreferenzsystem (KBS)
        if features_to_clip.crs != clip_polygons.crs:
            logging.warning(
                f"Die Koordinatensysteme der Eingabedateien sind unterschiedlich. "
                f"Transformiere das KBS von '{input_path}' zu dem von '{clip_features_path}'.")
            features_to_clip = features_to_clip.to_crs(clip_polygons.crs)

        # Fasse alle Polygone der Clip-Features zu einem einzigen Geometrieobjekt zusammen
        logging.info("Fasse die Clip-Polygone zu einer einzigen Geometrie zusammen.")
        clip_boundary = clip_polygons.unary_union

        # Führe den Zuschnitt durch
        logging.info("Führe den Zuschnitt der Linien auf die Clip-Geometrie durch.")
        clipped_features = features_to_clip.clip(clip_boundary)

        # Prüfe auf doppelte Spalten und entferne sie, um Fehler beim Speichern zu vermeiden
        duplicated_cols = clipped_features.columns[clipped_features.columns.duplicated()].tolist()
        if duplicated_cols:
            logging.warning(f"Folgende doppelte Spalten werden entfernt: {duplicated_cols}")
            clipped_features = clipped_features.loc[:, ~clipped_features.columns.duplicated()]

        # Speichere das Ergebnis
        logging.info(f"Speichere das Ergebnis in: {output_path}")
        clipped_features.to_file(output_path, driver="FlatGeobuf")

        logging.info(
            f"✔ Erfolgreich abgeschlossen. {len(clipped_features)} Objekte wurden in die "
            f"Ausgabedatei geschrieben.")

    except Exception as e:
        logging.error(f"Ein Fehler ist aufgetreten: {e}")
        sys.exit(1)


def main():
    """
    Hauptfunktion des Skripts.
    Parst die Kommandozeilenargumente und ruft die clip_geodata-Funktion auf.
    """
    parser = argparse.ArgumentParser(
        description="Schneidet Linien auf die Grenzen von Polygonen zu.")
    parser.add_argument("--input",
                        default="bikelanes.fgb",
                        help="Pfad zur Eingabedatei mit den Linien, die zugeschnitten werden sollen.")
    parser.add_argument("--clip-features",
                        default="data/Berlin Bezirke.gpkg",
                        help="Pfad zur Datei mit den Polygonen für den Zuschnitt.")
    parser.add_argument("--output",
                        default="TILDA Radwege Berlin.fgb",
                        help="Pfad zur Ausgabedatei.")
    args = parser.parse_args()

    clip_geodata(args.input, args.clip_features, args.output)


if __name__ == "__main__":
    main()
