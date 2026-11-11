#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
map_back_to_original.py
--------------------------------------------------------------------
Bringt das Matching-Ergebnis vom korrigierten REN+ zurück aufs Original, das der Kunde bekommt.

Das Matching (processing/map-matching) rechnet mit dem korrigierten Netz
(ren_netz_korrigiert.gpkg). Die Teilsegmente seiner Ausgabe liegen auf den
korrigierten Linien. Hier werden sie auf die Originallinien (ren_netz.gpkg)
gelegt: Jedes Teilsegment wird auf seine korrigierte Kante projiziert, der Abschnitt dort
(von bis, als Anteil der Kantenlänge) gilt anteilig für die Originalkante. Kanten, die nicht
korrigiert wurden (gleiche Geometrie in beiden Netzen), bleiben unverändert.

Kanten, die an virtuellen Knoten geteilt wurden, tragen im Matching die Nummer der Teilkante
(`element_nr` mit V-Knoten). Ihre Ursprungskante steht in `elem_nr` von
processing/output/ren/ren_netz_with_element_nr.fgb; sie landet als `ursprung_element_nr` in
der Ausgabe, und die Anteile beziehen sich auf die Ursprungskante.

Felder der Eingabe (Ausgabe von processing/map-matching, src/pipeline.rs, `write_output`):
sfid, element_nr, beginnt_bei_vp, endet_bei_vp, Länge, ri, Bezirksnummer, strassenname,
die übernommenen Attribute (fuehr, pflicht, ...), tilda_ids, data_source, edge_source,
hmm_konfidenz, hmm_regel, hmm_kandidaten. `ri` = 0: Digitalisierungsrichtung der Linie im Matching.
Die Teilsegmente tragen keine Intervalle, nur die Geometrie; die Intervalle entstehen hier aus
der Projektion. Die Ausgabe hat dieselben Felder und zusätzlich:
- ursprung_element_nr: Nummer der Ursprungskante, falls die Kante geteilt wurde
- von_m, bis_m: Abschnitt auf der Originalkante in Metern (in Digitalisierungsrichtung des Originals)
- von_anteil, bis_anteil: derselbe Abschnitt als Anteil der Kantenlänge (0 bis 1)
- kante_korrigiert: ja, wenn die Kante in der App korrigiert wurde

Geometrie und `ri` behalten die Richtung der Eingabe (die Linie läuft in Fahrtrichtung `ri = 0`),
`Länge` wird neu berechnet. Teilsegmente, deren Kante nicht im Original liegt (in der App
gezeichnete Kanten), stehen nicht in der Ausgabe, sondern in <Ausgabe>_ohne_original.csv.

INPUT:
- processing/output/map-matching-ren/network_enriched_hmm.fgb (REN+; --eingabe)
- ren-network/output/ren_netz.gpkg (Original)
- ren-network/output/ren_netz_korrigiert.gpkg
- processing/output/ren/ren_netz_with_element_nr.fgb (Ursprungskanten geteilter Kanten)

OUTPUT:
- processing/output/map-matching-ren/network_enriched_hmm_original.fgb
- processing/output/map-matching-ren/network_enriched_hmm_original_ohne_original.csv

Aufruf:
    python ren-network/map_back_to_original.py
    python ren-network/map_back_to_original.py --eingabe processing/output/map-matching-ren/network_enriched_hmm.fgb
"""

import argparse
import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import substring

ROOT = Path(__file__).resolve().parent.parent
CRS = "EPSG:25833"
OUTPUT_LAYER = "ren_netz"

ORIGINAL_PATH = ROOT / "ren-network" / "output" / "ren_netz.gpkg"
CORRECTED_PATH = ROOT / "ren-network" / "output" / "ren_netz_korrigiert.gpkg"
INPUT_PATH = ROOT / "processing" / "output" / "map-matching-ren" / "network_enriched_hmm.fgb"
SPLIT_PATH = ROOT / "processing" / "output" / "ren" / "ren_netz_with_element_nr.fgb"

# Gleiche Geometrie in beiden Netzen: Abweichung bis hierhin gilt als unverändert (Meter)
UNCHANGED_TOLERANCE_M = 0.001
# Liegt ein Teilsegment weiter von seiner korrigierten Kante, wird das gemeldet (Meter)
FAR_FROM_EDGE_M = 10.0
# Kürzere Abschnitte auf dem Original entfallen (Meter)
MIN_LENGTH_M = 0.001

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s", force=True)


def line_parts(geometry):
    lines = list(geometry.geoms) if isinstance(geometry, MultiLineString) else [geometry]
    return [line for line in lines if isinstance(line, LineString) and not line.is_empty]


def parts_by_element_nr(network):
    """element_nr -> Linien (bei MultiLineString in der Reihenfolge der Teile, wie `#2`, `#3` in der App)."""
    result = {}
    for element_nr, geometry in zip(network["element_nr"], network.geometry):
        if isinstance(element_nr, str):
            result[element_nr] = line_parts(geometry)
    return result


def same_geometry(original_parts, corrected_parts):
    return len(original_parts) == len(corrected_parts) and all(
        o.hausdorff_distance(k) <= UNCHANGED_TOLERANCE_M for o, k in zip(original_parts, corrected_parts))


def interval_on_original(corrected_line, original_line, segment):
    """Abschnitt des Teilsegments auf der Originallinie.

    Gibt (von_m, bis_m, Geometrie, Abstand zur korrigierten Linie) zurück; die Geometrie ist None, wenn der
    Abschnitt kürzer als MIN_LENGTH_M ist oder die korrigierte Linie keine Länge hat. Der Abschnitt auf der
    korrigierten Linie wird anteilig auf die Originallänge übertragen. Die Geometrie läuft wie das
    Teilsegment (läuft es gegen die Linie, läuft sie gegen das Original)."""
    if corrected_line.length <= 0:
        return None, None, None, None
    start = corrected_line.project(Point(segment.coords[0]))
    end = corrected_line.project(Point(segment.coords[-1]))
    low, high = sorted((start, end))
    scale = original_line.length / corrected_line.length
    from_m, to_m = low * scale, high * scale
    if to_m - from_m < MIN_LENGTH_M:
        return from_m, to_m, None, corrected_line.distance(segment)
    piece = substring(original_line, from_m, to_m)
    if start > end:
        piece = LineString(list(piece.coords)[::-1])
    distance = corrected_line.distance(segment.interpolate(0.5, normalized=True))
    return from_m, to_m, piece, distance


def parent_element_nr(element_nr, corrected, split_parent):
    """Nummer der Kante im korrigierten Netz: die eigene, sonst die Ursprungskante einer Teilkante."""
    if element_nr in corrected:
        return element_nr
    return split_parent.get(element_nr)


def map_back(result, original, corrected, split_parent):
    """Legt die Teilsegmente aufs Original. Gibt (Ausgabe, Teilsegmente ohne Original) zurück."""
    rows, missing = [], []
    far = 0
    for _, segment in result.iterrows():
        element_nr = segment["element_nr"]
        parent = parent_element_nr(element_nr, corrected, split_parent)
        if parent is None or parent not in original:
            missing.append({"sfid": segment.get("sfid"), "element_nr": element_nr, "ursprung_element_nr": parent,
                            "grund": "Kante nicht im korrigierten Netz" if parent is None else "Kante nicht im Original"})
            continue
        row = segment.drop("geometry").to_dict()
        row["ursprung_element_nr"] = parent if parent != element_nr else None
        geometry = segment.geometry
        corrected_parts, original_parts = corrected[parent], original[parent]
        changed = not same_geometry(original_parts, corrected_parts)
        row["kante_korrigiert"] = "ja" if changed else "nein"

        def skip(reason):
            missing.append({"sfid": segment.get("sfid"), "element_nr": element_nr, "ursprung_element_nr": parent,
                            "grund": reason})

        if segment.geometry.length < MIN_LENGTH_M:
            skip(f"Teilsegment kürzer als {MIN_LENGTH_M * 1000:.0f} mm")
            continue
        if not changed:
            # Anteil trotzdem angeben, damit die Spalten überall gefüllt sind
            line = original_parts[0] if len(original_parts) == 1 else min(original_parts, key=lambda p: p.distance(geometry))
            from_m, to_m = sorted((line.project(Point(geometry.coords[0])), line.project(Point(geometry.coords[-1]))))
            length = line.length
        else:
            number = min(range(len(corrected_parts)), key=lambda i: corrected_parts[i].distance(geometry))
            if number >= len(original_parts):
                skip("Original hat weniger Linien als das korrigierte Netz")
                continue
            if corrected_parts[number].length <= 0:
                skip("Linie der korrigierten Kante hat die Länge 0")
                continue
            from_m, to_m, piece, distance = interval_on_original(corrected_parts[number], original_parts[number], geometry)
            length = original_parts[number].length
            if piece is None:
                skip(f"Abschnitt auf dem Original kürzer als {MIN_LENGTH_M * 1000:.0f} mm")
                continue
            geometry = piece
            far += distance > FAR_FROM_EDGE_M
        row.update({
            "geometry": geometry,
            "von_m": round(from_m, 2), "bis_m": round(to_m, 2),
            "von_anteil": round(from_m / length, 4) if length else None,
            "bis_anteil": round(to_m / length, 4) if length else None,
        })
        if "Länge" in row:
            row["Länge"] = int(round(geometry.length))
        rows.append(row)
    if far:
        logging.warning(f"{far} Teilsegmente liegen mehr als {FAR_FROM_EDGE_M:.0f} m neben ihrer korrigierten Kante")
    output = gpd.GeoDataFrame(rows, geometry="geometry", crs=result.crs)
    return output, pd.DataFrame(missing, columns=["sfid", "element_nr", "ursprung_element_nr", "grund"])


def load_split_parents(path):
    """Teilkante -> Ursprungskante (elem_nr) aus der Zwischendatei von assign_element_nr_to_rvn.py."""
    if not Path(path).exists():
        logging.warning(f"{path} fehlt: geteilte Kanten finden ihre Ursprungskante nicht")
        return {}
    split = gpd.read_file(path, columns=["element_nr", "elem_nr"])
    split = split[split["elem_nr"].notna() & (split["element_nr"] != split["elem_nr"])]
    return dict(zip(split["element_nr"], split["elem_nr"]))


def run(input_path=INPUT_PATH, output_path=None, original_path=ORIGINAL_PATH, corrected_path=CORRECTED_PATH,
        split_path=SPLIT_PATH):
    input_path = Path(input_path)
    output_path = Path(output_path) if output_path else input_path.with_name(input_path.stem + "_original.fgb")
    original = parts_by_element_nr(gpd.read_file(original_path, layer=OUTPUT_LAYER).to_crs(CRS))
    corrected = parts_by_element_nr(gpd.read_file(corrected_path, layer=OUTPUT_LAYER).to_crs(CRS))
    result = gpd.read_file(input_path)
    if result.crs is None or result.crs.to_epsg() != 25833:
        result = result.to_crs(CRS)
    logging.info(f"Matching-Ergebnis: {len(result)} Teilsegmente, korrigiertes Netz: {len(corrected)} Kanten")

    output, missing = map_back(result, original, corrected, load_split_parents(split_path))
    output.to_file(output_path, driver="FlatGeobuf")
    missing_path = output_path.with_name(output_path.stem + "_ohne_original.csv")
    missing.to_csv(missing_path, index=False)
    logging.info(f"Auf dem Original: {len(output)} Teilsegmente, davon auf korrigierten Kanten "
                 f"{(output['kante_korrigiert'] == 'ja').sum()}, geteilte Kanten {output['ursprung_element_nr'].notna().sum()}")
    logging.info(f"Ohne Original: {len(missing)} Teilsegmente ({missing['element_nr'].nunique()} Kanten): {missing_path}")
    logging.info(f"Geschrieben: {output_path}")
    return output, missing


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--eingabe", type=Path, default=INPUT_PATH, help="Matching-Ergebnis (network_enriched_hmm.fgb)")
    parser.add_argument("--ausgabe", type=Path, help="Standard: <Eingabe>_original.fgb")
    parser.add_argument("--original", type=Path, default=ORIGINAL_PATH)
    parser.add_argument("--korrigiert", type=Path, default=CORRECTED_PATH)
    parser.add_argument("--zwischenstand", type=Path, default=SPLIT_PATH,
                        help="ren_netz_with_element_nr.fgb, für die Ursprungskanten geteilter Kanten")
    args = parser.parse_args()
    run(args.eingabe, args.ausgabe, args.original, args.korrigiert, args.zwischenstand)


if __name__ == "__main__":
    main()
