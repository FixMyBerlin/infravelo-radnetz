#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
import_app_export.py
--------------------------------------------------------------------
Liest den Export „alle Einträge“ der App Netzanpassungen (Repo knotenpunkte, Ordner
netzanpassungen/) und bringt die Korrekturen ins REN+:

- edge_correction: Korrektur einer REN+-Kante (Geometrie, fahrbahn_typ, fahrbahn_gruppe,
  verkehrsrichtung, ausgeschlossen). Wird auf ren_netz_gesamt.gpkg abgespielt.
- virtual_node: virtueller Knoten, wird an data/Virtuelle-Knotenpunkte.gpkg angehängt.
- new_edge: gezeichnete Kante, wird an data/netzquellen/touristische_kanten.gpkg angehängt
  (je entry_id ersetzt, ein zweiter Lauf ändert nichts).
- Einträge mit geloescht = true werden übersprungen.

Eine Korrektur wird nur angewendet, wenn die Kante im Eingangsnetz liegt (Schlüssel
kante.ref wie in der App: element_nr, ab der zweiten Linie derselben Nummer `#2`, ...), ihre
original_coordinates höchstens 5 cm von der Geometrie dort abweichen (nach Umprojektion
EPSG:4326 -> EPSG:25833) und original_coordinates + aenderungen den gespeicherten Stand
ergeben. Sonst bleibt die Kante unverändert und steht in korrekturen_konflikte.csv.

Die Datei ren_netz_gesamt_korrigiert.gpkg enthält alle Kanten von ren_netz_gesamt.gpkg, mit
korrigierter Geometrie und den Spalten korrigiert, attribut_korrigiert, fahrbahn_typ,
fahrbahn_gruppe, verkehrsrichtung (nur wo erfasst), ausgeschlossen (ja/nein), anzahl_vorgaenge,
letzte_aenderung_am, letzte_aenderung_von, korrektur_kommentar. Ausgeschlossene Kanten bleiben
darin, sind aber markiert; processing/scripts/split_rvn_at_virtual_nodes.py und die
Kartierung lassen sie weg.

INPUT:
- Export der App (JSON: {gebiet, exported_at, entries})
- ren-network/output/ren_netz_gesamt.gpkg (unify_networks.py)
- data/Berlin Straßenabschnitte Detailnetz*.fgb (nur die element_nr, für die Nummern neuer Kanten)
- data/Virtuelle-Knotenpunkte.gpkg, data/netzquellen/touristische_kanten.gpkg (werden ergänzt)

OUTPUT:
- ren-network/output/ren_netz_gesamt_korrigiert.gpkg / .geojson
- ren-network/output/ren_netz_kartierung_korrigiert.gpkg / .geojson (ohne bearbeitet_2025 = ja
  und ohne ausgeschlossene Kanten)
- ren-network/output/korrekturen_konflikte.csv
- data/Virtuelle-Knotenpunkte.gpkg, data/netzquellen/touristische_kanten.gpkg (ergänzt)

Aufruf:
    python netzanpassungen/import_app_export.py netzanpassungen-alle-eintraege-berlin-2026-11-12.json
    python netzanpassungen/import_app_export.py export.json --ohne-anhaengen
"""

import argparse
import json
import logging
import re
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
from pyproj import Transformer
from shapely.geometry import LineString, MultiLineString, Point

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.append(str(ROOT / "ren-network"))
sys.path.append(str(HERE))

import unify_networks as ren  # noqa: E402
from export_app_daten import detailnetz_path, line_refs  # noqa: E402

CRS = f"EPSG:{ren.DEFAULT_CRS}"

# Weicht die Geometrie im Netz weiter von original_coordinates ab, wird die Korrektur nicht angewendet
CONFLICT_TOLERANCE_M = 0.05
# Der Wiederholungstest vergleicht Längen- und Breitengrade; die App rundet auf 7 Stellen (etwa 1 cm)
REPLAY_TOLERANCE_DEG = 1e-9
# Ein virtueller Knoten, der weiter von seiner (korrigierten) Trägerkante liegt, kommt auf die Prüfliste
NODE_ON_EDGE_TOLERANCE_M = 1.0
# Gleiche ID an (fast) gleicher Stelle: derselbe Knoten, schon angehängt
NODE_SAME_POSITION_M = 0.5

OUTPUT_DIR = ren.OUTPUT_DIR
GESAMT_ORIGINAL = ren.OUTPUT_PATH
GESAMT_KORRIGIERT = OUTPUT_DIR / "ren_netz_gesamt_korrigiert.gpkg"
KARTIERUNG_KORRIGIERT = OUTPUT_DIR / "ren_netz_kartierung_korrigiert.gpkg"
CONFLICTS_PATH = OUTPUT_DIR / "korrekturen_konflikte.csv"
VIRTUAL_NODES_PATH = ROOT / "data" / "Virtuelle-Knotenpunkte.gpkg"
VIRTUAL_NODES_LAYER = "Virtuelle-Knotenpunkte"
NEW_EDGES_PATH = ROOT / "data" / "netzquellen" / "touristische_kanten.gpkg"
NEW_EDGES_LAYER = "touristische_kanten"

CORRECTION_COLUMNS = ["korrigiert", "attribut_korrigiert", "fahrbahn_typ", "fahrbahn_gruppe", "verkehrsrichtung",
                      "ausgeschlossen", "anzahl_vorgaenge", "letzte_aenderung_am", "letzte_aenderung_von",
                      "korrektur_kommentar"]
CONFLICT_COLUMNS = ["grund", "art", "eintrag_id", "ref", "element_nr", "abweichung_m", "bearbeitet_von", "bearbeitet_am"]

ELEMENT_NR_PATTERN = re.compile(r"^(.+)_(.+)\.(\d+)$")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s", force=True)

_to_utm = Transformer.from_crs("EPSG:4326", CRS, always_xy=True)


def to_utm(coordinates):
    """[[lng, lat], ...] -> LineString in EPSG:25833."""
    return LineString([_to_utm.transform(lng, lat) for lng, lat in coordinates])


def deviation_m(a, b):
    """Größte Abweichung zweier Linien: Hausdorff, bei gleicher Stützpunktzahl auch Punkt für Punkt."""
    result = a.hausdorff_distance(b)
    if len(a.coords) == len(b.coords):
        result = max(result, max(Point(p).distance(Point(q)) for p, q in zip(a.coords, b.coords)))
    return result


def replay(original_coordinates, changes):
    """Spielt das Protokoll ab (wie replayCorrection in der App): (Koordinaten, Attribute).

    Unbekannte Zusatzfelder bleiben unbeachtet, z. B. `macht_rueckgaengig` (die vorgang_id, die eine
    Zeile zurücknimmt): Ein zurückgenommenes Einfügen steht als `zurueckgesetzt` mit folgenden
    „Wiederholt: …“-Zeilen im Protokoll, das Abspielen in Reihenfolge deckt das ab."""
    coordinates = [list(point) for point in original_coordinates]
    attribute = {}
    for change in changes:
        kind = change["art"]
        if kind == "verschoben":
            coordinates[change["index"]] = list(change["nach"])
        elif kind == "eingefuegt":
            coordinates.insert(change["index"], list(change["nach"]))
        elif kind == "attribut":
            attribute[change["feld"]] = change.get("nach_wert")
        elif kind == "ausgeschlossen":
            attribute["ausgeschlossen"] = change.get("nach_wert")
        elif kind == "zurueckgesetzt":
            coordinates = [list(point) for point in original_coordinates]
            attribute = {}
        else:
            raise ValueError(f"Unbekannte Änderungsart {kind!r}")
    return coordinates, attribute


def same_coordinates(a, b):
    return len(a) == len(b) and all(
        abs(p[0] - q[0]) <= REPLAY_TOLERANCE_DEG and abs(p[1] - q[1]) <= REPLAY_TOLERANCE_DEG for p, q in zip(a, b))


def significant_attributes(attribute):
    """Ohne leere Werte: ein fehlender Schlüssel bedeutet „nicht erfasst“."""
    return {key: value for key, value in attribute.items() if value not in (None, False)}


class Parts:
    """Die Linien des REN+ mit dem Schlüssel `ref` der App: eine MultiLineString kann mehrere haben."""

    def __init__(self, network):
        self.items = []
        element_nrs = []
        for row, geometry in enumerate(network.geometry):
            lines = list(geometry.geoms) if isinstance(geometry, MultiLineString) else [geometry]
            for number, line in enumerate(lines):
                if isinstance(line, LineString) and not line.is_empty:
                    self.items.append({"row": row, "part": number, "line": line})
                    element_nrs.append(network["element_nr"].iloc[row])
        for item, ref, element_nr in zip(self.items, line_refs(element_nrs), element_nrs):
            item["ref"] = ref
            item["element_nr"] = element_nr if isinstance(element_nr, str) else None
        self.by_ref = {item["ref"]: item for item in self.items}

    def same_number(self, element_nr):
        return [item for item in self.items if element_nr and item["element_nr"] == element_nr]


def blank_correction_columns(network):
    network = network.copy()
    network["korrigiert"] = "nein"
    network["attribut_korrigiert"] = "nein"
    network["fahrbahn_typ"] = None
    network["fahrbahn_gruppe"] = None
    network["verkehrsrichtung"] = None
    network["ausgeschlossen"] = "nein"
    network["anzahl_vorgaenge"] = pd.array([0] * len(network), dtype="Int64")
    network["letzte_aenderung_am"] = None
    network["letzte_aenderung_von"] = None
    network["korrektur_kommentar"] = None
    return network


def conflict(entry, data, reason, deviation=None):
    kante = data.get("kante") or {}
    return {
        "grund": reason,
        "art": data.get("kind"),
        "eintrag_id": entry.get("id"),
        "ref": kante.get("ref"),
        "element_nr": kante.get("element_nr"),
        "abweichung_m": None if deviation is None else round(deviation, 3),
        "bearbeitet_von": entry.get("updated_by"),
        "bearbeitet_am": entry.get("updated_at"),
    }


def apply_corrections(network, entries):
    """Spielt die edge_correction-Einträge auf das Netz ab. Gibt (korrigiertes Netz, Konflikte, Zähler) zurück."""
    network = blank_correction_columns(network)
    parts = Parts(network)
    lines = {}  # (row, part) -> neue Linie
    conflicts = []
    stats = {"edge_correction": 0, "angewendet": 0, "geometrie": 0, "attribute": 0, "konflikte": 0}
    seen = {}

    for entry in sorted(entries, key=lambda item: item.get("updated_at") or ""):
        data = entry["data"]
        if data.get("kind") != "edge_correction" or data.get("geloescht"):
            continue
        stats["edge_correction"] += 1
        kante = data["kante"]
        ref = kante["ref"]
        if ref in seen:
            conflicts.append(conflict(entry, data, f"Zweiter Eintrag zur selben Kante (erster: {seen[ref]}), der spätere gilt"))
        seen[ref] = entry.get("id")

        original = to_utm(data["original_coordinates"])
        item = parts.by_ref.get(ref)
        reason, distance = None, None
        if item is None or (kante.get("element_nr") and item["element_nr"] != kante["element_nr"]):
            # Die Nummerierung der Linien kann sich verschieben (z. B. Export nur eines Bezirks):
            # dann sucht die Geometrie unter den Linien derselben element_nr
            candidates = parts.same_number(kante.get("element_nr"))
            item = next((c for c in candidates if deviation_m(c["line"], original) <= CONFLICT_TOLERANCE_M), None)
            if item is None:
                reason = "Kante nicht im Eingangsnetz" if not candidates else \
                    "Kante mit dieser ref nicht im Eingangsnetz, Geometrie keiner Linie der element_nr gleich"
        if item is not None:
            distance = deviation_m(item["line"], original)
            if distance > CONFLICT_TOLERANCE_M:
                reason = f"original_coordinates weichen {distance * 100:.0f} cm von der Kante im Eingangsnetz ab (erlaubt {CONFLICT_TOLERANCE_M * 100:.0f} cm)"
        if reason is None:
            replayed, attribute = replay(data["original_coordinates"], data.get("aenderungen", []))
            if not same_coordinates(replayed, data["coordinates"]) or \
                    significant_attributes(attribute) != significant_attributes(data.get("attribute", {})):
                reason = "original_coordinates + aenderungen ergeben nicht den gespeicherten Stand"
        if reason is not None:
            conflicts.append(conflict(entry, data, reason, distance))
            stats["konflikte"] += 1
            continue

        row = item["row"]
        index = network.index[row]
        changed_geometry = not same_coordinates(data["original_coordinates"], data["coordinates"])
        if changed_geometry:
            lines[(row, item["part"])] = to_utm(data["coordinates"])
            network.at[index, "korrigiert"] = "ja"
            stats["geometrie"] += 1
        attribute = data.get("attribute", {})
        for field in ("fahrbahn_typ", "fahrbahn_gruppe", "verkehrsrichtung"):
            if attribute.get(field) is not None:
                network.at[index, field] = attribute[field]
        if attribute.get("ausgeschlossen"):
            network.at[index, "ausgeschlossen"] = "ja"
        if significant_attributes(attribute):
            network.at[index, "attribut_korrigiert"] = "ja"
            stats["attribute"] += 1
        changes = data.get("aenderungen", [])
        network.at[index, "anzahl_vorgaenge"] = int(network.at[index, "anzahl_vorgaenge"]) + len({c["vorgang_id"] for c in changes})
        if changes:
            last = max(changes, key=lambda c: c["am"])
            if network.at[index, "letzte_aenderung_am"] is None or last["am"] >= network.at[index, "letzte_aenderung_am"]:
                network.at[index, "letzte_aenderung_am"] = last["am"]
                network.at[index, "letzte_aenderung_von"] = last["von_nutzer"]
        if data.get("kommentar"):
            network.at[index, "korrektur_kommentar"] = data["kommentar"]
        stats["angewendet"] += 1

    # Geometrien der Zeilen mit korrigierten Linien neu bauen, die anderen Teile bleiben
    geometries = list(network.geometry)
    for row in sorted({row for row, _ in lines}):
        old = geometries[row]
        old_parts = list(old.geoms) if isinstance(old, MultiLineString) else [old]
        geometries[row] = MultiLineString([lines.get((row, number), part) for number, part in enumerate(old_parts)])
        if "laenge_m" in network.columns:
            network.at[network.index[row], "laenge_m"] = round(geometries[row].length, 1)
    network = network.set_geometry(gpd.GeoSeries(geometries, index=network.index, crs=network.crs))
    return network, conflicts, stats, parts


def active_entries(entries, kind):
    return [entry for entry in entries if entry["data"].get("kind") == kind]


def virtual_node_frame(entries):
    rows = []
    for entry in active_entries(entries, "virtual_node"):
        data = entry["data"]
        if data.get("geloescht"):
            continue
        x, y = _to_utm.transform(*data["lngLat"])
        rows.append({"Knotenpunkt-ID": data["name"], "eintrag_id": entry["id"], "geometry": Point(x, y)})
    return gpd.GeoDataFrame(rows, columns=["Knotenpunkt-ID", "eintrag_id", "geometry"], geometry="geometry", crs=CRS)


def check_nodes_on_edges(entries, network, parts):
    """Virtuelle Knoten auf einer REN+-Kante müssen auf der (korrigierten) Kante liegen."""
    found = []
    corrected = Parts(network)
    for entry in active_entries(entries, "virtual_node"):
        data = entry["data"]
        host = data.get("traeger", {})
        if data.get("geloescht") or host.get("art") != "ren":
            continue
        item = corrected.by_ref.get(host.get("ref"))
        if item is None:
            found.append({"grund": f"Virtueller Knoten {data['name']}: Trägerkante {host.get('ref')} nicht im Eingangsnetz",
                          "art": "virtual_node", "eintrag_id": entry["id"], "ref": host.get("ref"), "element_nr": None,
                          "abweichung_m": None, "bearbeitet_von": entry.get("updated_by"), "bearbeitet_am": entry.get("updated_at")})
            continue
        x, y = _to_utm.transform(*data["lngLat"])
        distance = item["line"].distance(Point(x, y))
        if distance > NODE_ON_EDGE_TOLERANCE_M:
            found.append({"grund": f"Virtueller Knoten {data['name']} liegt {distance:.2f} m neben seiner Trägerkante",
                          "art": "virtual_node", "eintrag_id": entry["id"], "ref": host.get("ref"),
                          "element_nr": item["element_nr"], "abweichung_m": round(distance, 3),
                          "bearbeitet_von": entry.get("updated_by"), "bearbeitet_am": entry.get("updated_at")})
    return found


def append_virtual_nodes(path, nodes):
    """Hängt neue virtuelle Knoten an. Gleiche ID an gleicher Stelle ist schon da. Gibt (neu, Konflikte) zurück."""
    existing = gpd.read_file(path).to_crs(CRS) if path.exists() else gpd.GeoDataFrame(
        {"Knotenpunkt-ID": []}, geometry=[], crs=CRS)
    known = {str(name): geometry for name, geometry in zip(existing["Knotenpunkt-ID"], existing.geometry)}
    added, conflicts = [], []
    for _, node in nodes.iterrows():
        name = node["Knotenpunkt-ID"]
        if name in known:
            distance = known[name].distance(node.geometry)
            if distance > NODE_SAME_POSITION_M:
                conflicts.append({"grund": f"Virtueller Knoten {name} steht schon in {path.name}, {distance:.2f} m entfernt; die Datei bleibt",
                                  "art": "virtual_node", "eintrag_id": node["eintrag_id"], "ref": None, "element_nr": None,
                                  "abweichung_m": round(distance, 3), "bearbeitet_von": None, "bearbeitet_am": None})
            continue
        known[name] = node.geometry
        added.append({"Knotenpunkt-ID": name, "geometry": node.geometry})
    if added:
        merged = pd.concat([existing[["Knotenpunkt-ID", "geometry"]], gpd.GeoDataFrame(added, crs=CRS)], ignore_index=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        gpd.GeoDataFrame(merged, crs=CRS).to_file(path, layer=VIRTUAL_NODES_LAYER, driver="GPKG")
    return len(added), conflicts


def pair_key(a, b):
    return tuple(sorted((a, b)))


def element_nr_counts(element_nrs):
    """Höchste laufende Nummer je Knotenpaar, wie baseCounts in der App (element-nr.ts)."""
    counts = {}
    for element_nr in element_nrs:
        match = ELEMENT_NR_PATTERN.match(element_nr) if isinstance(element_nr, str) else None
        if match:
            key = pair_key(match.group(1), match.group(2))
            counts[key] = max(counts.get(key, 0), int(match.group(3)))
    return counts


def node_name(key, virtual_names):
    if key.startswith("k:"):
        return key[2:]
    if key.startswith("v:"):
        return virtual_names.get(key[2:])
    return None


def new_edge_frame(entries, base_element_nrs):
    """Gezeichnete Kanten als Zeilen für touristische_kanten.gpkg. Die element_nr zählt wie in der App
    (Reihenfolge des Zeichnens); Teilungen an virtuellen Knoten macht split_rvn_at_virtual_nodes.py."""
    virtual_names = {entry["id"]: entry["data"]["name"] for entry in active_entries(entries, "virtual_node")
                     if not entry["data"].get("geloescht")}
    counts = element_nr_counts(base_element_nrs)
    rows, conflicts = [], []
    drawn = [entry for entry in active_entries(entries, "new_edge") if not entry["data"].get("geloescht")]
    for entry in sorted(drawn, key=lambda item: item.get("created_at") or ""):
        data = entry["data"]
        von, bis = node_name(data["von"], virtual_names), node_name(data["bis"], virtual_names)
        if not von or not bis:
            conflicts.append({"grund": f"Neue Kante: Knoten {data['von'] if not von else data['bis']} nicht auffindbar (gelöschter virtueller Knoten?)",
                              "art": "new_edge", "eintrag_id": entry["id"], "ref": None, "element_nr": None, "abweichung_m": None,
                              "bearbeitet_von": entry.get("updated_by"), "bearbeitet_am": entry.get("updated_at")})
            continue
        key = pair_key(von, bis)
        counts[key] = counts.get(key, 0) + 1
        rows.append({
            "entry_id": entry["id"],
            "element_nr": f"{von}_{bis}.{counts[key]:02d}",
            "von_knoten": von,
            "bis_knoten": bis,
            "quelle": data.get("quelle"),
            "strassenname": data.get("strassenname"),
            "routen_fernradweg": data.get("routen_fernradweg"),
            "kommentar": data.get("kommentar"),
            "geometry": to_utm(data["coordinates"]),
        })
    columns = ["entry_id", "element_nr", "von_knoten", "bis_knoten", "quelle", "strassenname", "routen_fernradweg",
               "kommentar", "geometry"]
    return gpd.GeoDataFrame(rows, columns=columns, geometry="geometry", crs=CRS), conflicts


def write_new_edges(path, frame, entries):
    """Ersetzt die Zeilen dieser Einträge (auch gelöschte) und lässt alle anderen stehen."""
    touched = {entry["id"] for entry in active_entries(entries, "new_edge")}
    existing = gpd.read_file(path, layer=NEW_EDGES_LAYER) if path.exists() else None
    if existing is not None:
        kept = existing[~existing["entry_id"].isin(touched)]
        frame = gpd.GeoDataFrame(pd.concat([kept, frame], ignore_index=True), crs=CRS) if len(kept) else frame
    elif frame.empty:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_file(path, layer=NEW_EDGES_LAYER, driver="GPKG")
    return len(frame)


def load_base_element_nrs(network, detail_path):
    element_nrs = list(network["element_nr"])
    if detail_path is not None and Path(detail_path).exists():
        element_nrs += list(gpd.read_file(detail_path, columns=["element_nr"])["element_nr"])
    return element_nrs


def run(export_path, ren_path=GESAMT_ORIGINAL, output_dir=OUTPUT_DIR, virtual_nodes_path=VIRTUAL_NODES_PATH,
        new_edges_path=NEW_EDGES_PATH, detail_path=None, append=True):
    """Der ganze Import. Gibt Zähler und Konflikte zurück (für Tests)."""
    export = json.loads(Path(export_path).read_text(encoding="utf-8"))
    entries = export["entries"]
    logging.info(f"Export {export.get('gebiet')} vom {export.get('exported_at')}: {len(entries)} Einträge")

    network = gpd.read_file(ren_path, layer=ren.OUTPUT_LAYER)
    if network.crs is None or network.crs.to_epsg() != ren.DEFAULT_CRS:
        network = network.to_crs(CRS)
    corrected, conflicts, stats, parts = apply_corrections(network, entries)
    logging.info(f"Korrekturen: {stats['angewendet']} von {stats['edge_correction']} angewendet "
                 f"({stats['geometrie']} mit Geometrie, {stats['attribute']} mit Attributen), {stats['konflikte']} Konflikte")

    conflicts += check_nodes_on_edges(entries, corrected, parts)

    nodes = virtual_node_frame(entries)
    new_edges, edge_conflicts = new_edge_frame(entries, load_base_element_nrs(network, detail_path))
    conflicts += edge_conflicts
    stats["virtuelle_knoten"] = len(nodes)
    stats["neue_kanten"] = len(new_edges)
    if append:
        added, node_conflicts = append_virtual_nodes(Path(virtual_nodes_path), nodes)
        conflicts += node_conflicts
        stats["virtuelle_knoten_neu"] = added
        write_new_edges(Path(new_edges_path), new_edges, entries)
        logging.info(f"Virtuelle Knoten: {len(nodes)} im Export, {added} neu angehängt. Neue Kanten: {len(new_edges)}")
    else:
        logging.info(f"Ohne Anhängen: {len(nodes)} virtuelle Knoten, {len(new_edges)} neue Kanten bleiben unberührt")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    ren.write_network(corrected, output_dir / GESAMT_KORRIGIERT.name)
    mapping = corrected[corrected["ausgeschlossen"] != "ja"]
    if "bearbeitet_2025" in mapping.columns:
        mapping = mapping[mapping["bearbeitet_2025"] != "ja"]
    ren.write_network(mapping, output_dir / KARTIERUNG_KORRIGIERT.name)
    logging.info(f"Kartierungs-Netz korrigiert: {len(mapping)} Kanten (ausgeschlossen: {(corrected['ausgeschlossen'] == 'ja').sum()})")

    report = pd.DataFrame(conflicts, columns=CONFLICT_COLUMNS)
    report.to_csv(output_dir / CONFLICTS_PATH.name, index=False)
    logging.info(f"Konflikte: {len(report)}: {output_dir / CONFLICTS_PATH.name}")
    stats["konflikte_gesamt"] = len(report)
    return stats, conflicts


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("export", type=Path, help="Export „alle Einträge“ der App (JSON)")
    parser.add_argument("--ren-netz", type=Path, default=GESAMT_ORIGINAL, help="Eingangsnetz (Standard: ren_netz_gesamt.gpkg)")
    parser.add_argument("--ohne-anhaengen", action="store_true",
                        help="Virtuelle Knoten und neue Kanten nicht in data/ schreiben")
    args = parser.parse_args()
    run(args.export, ren_path=args.ren_netz, detail_path=detailnetz_path(), append=not args.ohne_anhaengen)


if __name__ == "__main__":
    main()
