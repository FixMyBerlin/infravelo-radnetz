#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apply_app_result.py  (Schritt 3 der Pipeline, bisher import_app_export.py)
--------------------------------------------------------------------
Liest den Export „alle Einträge“ der App Netzanpassungen (Repo knotenpunkte, Ordner
netzanpassungen/) und ren_netz_auto.gpkg (Schritt 2) und schreibt die Ergebnisnetze. Gelesen
wird nie aus data/ zurückgeschrieben: Alles, was von Hand entsteht, lebt in der App
(KV-Datenbank); die Dateien hier entstehen bei jedem Lauf neu.

Einträge des Exports (Einträge mit geloescht = true werden übersprungen):
- edge_correction: Korrektur einer REN+-Kante (Geometrie, fahrbahn_typ, fahrbahn_gruppe,
  verkehrsrichtung, ausgeschlossen). Wird auf ren_netz_auto.gpkg abgespielt.
- section_assignment: Entscheidung zu einem Abschnitt eines Radfernwegs (radfernweg_abschnitte.gpkg).
  zugeordnet: routen_fernradweg/routen_quelle (manuell) auf den gewählten Kanten; eine Detailnetzkante,
  die noch nicht im Netz ist, kommt mit quelle = detailnetz_manuell und grund_aufnahme =
  radfernweg_manuell dazu. Ersetzt die Entscheidung die automatische Zuordnung des Abschnitts
  (Umlegung), verliert die bisherige Kante diese Route (und fällt weg, wenn sie nur dafür aufgenommen
  wurde). keine_aktion: ändert nichts, steht nur in radfernweg_zuordnungen.csv. Unbekannter
  Abschnitt oder unbekannte Kante: Konflikt, der Eintrag gilt nicht.
- virtual_node: virtueller Knoten, kommt nach netzanpassungen/output/virtuelle_knoten.gpkg.
  Das ist die Datei, die die Pipeline (processing/, knotenpunkte/) als virtuelle Knoten liest.
- new_edge: gezeichnete Kante. Steht in beiden Ergebnisnetzen (quelle = neu_gezeichnet, routen_fernradweg aus dem
  Eintrag mit routen_quelle = manuell, element_nr `<von>_<bis>.<nn>` wie in der App) und weiterhin in
  netzanpassungen/output/touristische_kanten.gpkg.
- Virtuelle Knoten teilen ihre Trägerkante (REN+-Kante oder gezeichnete Kante) in beiden Ergebnisnetzen: Jede Teilkante
  bekommt eine neue element_nr und `ursprung_element_nr`, wie splitEdges in der App. Die Teilung an Detailnetz und
  Radvorrangsnetz bleibt Sache von processing/scripts/split_rvn_at_virtual_nodes.py; sie arbeitet nur geometrisch,
  nummeriert nicht und teilt an Knoten am Kantenende (unter 1 m) nicht noch einmal, kann also nicht wiederverwendet werden.

Eine Korrektur wird nur angewendet, wenn die Kante im Eingangsnetz liegt (Schlüssel
kante.ref wie in der App: element_nr, ab der zweiten Linie derselben Nummer `#2`, ...), ihre
original_coordinates höchstens 5 cm von der Geometrie dort abweichen (nach Umprojektion
EPSG:4326 -> EPSG:25833) und original_coordinates + aenderungen den gespeicherten Stand
ergeben. Sonst bleibt die Kante unverändert und steht in korrekturen_konflikte.csv.

Zwei Ergebnisnetze mit denselben Kanten und denselben Spalten; alles, was aus der App kommt, ist
markiert:
- ren_netz.gpkg (Kunde): Original-Lage. Mit Radfernwegen (auto und von Hand), aufgenommenen
  Detailnetzkanten, Richtung, Fahrbahn und Ausschluss, aber ohne Lagekorrekturen.
- ren_netz_korrigiert.gpkg (Matching, Mapping): dasselbe plus die Lagekorrekturen, mit lage_korrigiert
  und den Kennzahlen hausdorff_m, max_verschiebung_m, differenzflaeche_m2, laenge_alt_m, laenge_neu_m.
Spalten (beide): quelle (radnetz | detailnetz_radfernweg | detailnetz_manuell | neu_gezeichnet), ursprung_element_nr, grund_aufnahme,
routen_fernradweg, routen_quelle (auto | manuell | auto; manuell), verkehrsrichtung (aktuell),
verkehrsrichtung_original, verkehrsrichtung_korrigiert (ja/nein), fahrbahn_typ, fahrbahn_gruppe,
ausgeschlossen (ja/nein), ausschluss_grund, eintrag_ids, anzahl_vorgaenge, letzte_aenderung_am,
letzte_aenderung_von, korrektur_kommentar. Ausgeschlossene Kanten bleiben in beiden Netzen, sind aber
markiert; die Kartierung und processing/scripts/split_rvn_at_virtual_nodes.py lassen sie weg.

Zu beiden Netzen gibt es die Kartierung (ohne bearbeitet_2025 = ja und ohne ausgeschlossene Kanten).

INPUT:
- Export der App (JSON: {gebiet, exported_at, entries}); mit --ohne-export ohne Einträge
- netzanpassungen/output/ren_netz_auto.gpkg (match_cycle_routes.py)
- netzanpassungen/output/radfernweg_abschnitte.gpkg (nur für section_assignment)
- data/Berlin Straßenabschnitte Detailnetz*.fgb (element_nr für die Nummern neuer Kanten, Linien für
  von Hand zugeordnete Detailnetzkanten)

OUTPUT:
- ren-network/output/ren_netz.gpkg / .geojson, ren_netz_kartierung.gpkg / .geojson
- ren-network/output/ren_netz_korrigiert.gpkg / .geojson, ren_netz_kartierung_korrigiert.gpkg / .geojson
- ren-network/output/korrekturen_konflikte.csv, radfernweg_zuordnungen.csv
- netzanpassungen/output/virtuelle_knoten.gpkg (Layer Virtuelle-Knotenpunkte: Knotenpunkt-ID, ist_virtuell,
  traeger_netz, traeger_element_nr, station_m, kommentar, eintrag_id)
- netzanpassungen/output/touristische_kanten.gpkg (Layer touristische_kanten)

Aufruf:
    python netzanpassungen/apply_app_result.py netzanpassungen-alle-eintraege-berlin-2026-11-12.json
    python netzanpassungen/apply_app_result.py --ohne-export    # nur Schritt 2, keine Handarbeit; lässt
                                                                     # virtuelle_knoten.gpkg unangetastet
"""

import argparse
import json
import logging
import numbers
import re
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import shapely
import shapely.ops
from pyproj import Transformer
from shapely.geometry import LineString, MultiLineString, Point

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.append(str(ROOT / "ren-network"))
sys.path.append(str(HERE))

import merge_networks as ren  # noqa: E402
from auto_nodes import NODE_COLUMNS  # noqa: E402
from write_app_input import (  # noqa: E402
    AUTO_PATH, SECTIONS_LAYER, SECTIONS_PATH, detailnetz_path, line_refs, load_detailnetz)
from match_cycle_routes import append_detail_rows, routes_text  # noqa: E402

CRS = f"EPSG:{ren.DEFAULT_CRS}"

# Weicht die Geometrie im Netz weiter von original_coordinates ab, wird die Korrektur nicht angewendet
CONFLICT_TOLERANCE_M = 0.05
# Der Wiederholungstest vergleicht Längen- und Breitengrade; die App rundet auf 7 Stellen (etwa 1 cm)
REPLAY_TOLERANCE_DEG = 1e-9
# Raster der Koordinaten in der Eingabedatei der App (write_app_input.py, COORDINATE_GRID)
COORDINATE_GRID = 1e-7
# Ein virtueller Knoten, der weiter von seiner (korrigierten) Trägerkante liegt, kommt auf die Prüfliste
NODE_ON_EDGE_TOLERANCE_M = 1.0

OUTPUT_DIR = ren.OUTPUT_DIR
NETZ_PATH = OUTPUT_DIR / "ren_netz.gpkg"
NETZ_KORRIGIERT_PATH = OUTPUT_DIR / "ren_netz_korrigiert.gpkg"
KARTIERUNG_PATH = OUTPUT_DIR / "ren_netz_kartierung.gpkg"
KARTIERUNG_KORRIGIERT_PATH = OUTPUT_DIR / "ren_netz_kartierung_korrigiert.gpkg"
CONFLICTS_PATH = OUTPUT_DIR / "korrekturen_konflikte.csv"
ASSIGNMENTS_PATH = OUTPUT_DIR / "radfernweg_zuordnungen.csv"
APP_OUTPUT_DIR = HERE / "output"
VIRTUAL_NODES_PATH = APP_OUTPUT_DIR / "virtuelle_knoten.gpkg"  # wie processing/helpers/virtuelle_knoten.py
VIRTUAL_NODES_LAYER = "Virtuelle-Knotenpunkte"
NEW_EDGES_PATH = APP_OUTPUT_DIR / "touristische_kanten.gpkg"
NEW_EDGES_LAYER = "touristische_kanten"

# Spalten, die beide Ergebnisnetze zusätzlich zum Netz aus Schritt 2 tragen (Reihenfolge der Datei)
MARK_COLUMNS = ["verkehrsrichtung_original", "verkehrsrichtung_korrigiert", "fahrbahn_typ", "fahrbahn_gruppe",
                "ausgeschlossen", "ausschluss_grund", "eintrag_ids", "anzahl_vorgaenge", "letzte_aenderung_am",
                "letzte_aenderung_von", "korrektur_kommentar"]
# Nur im korrigierten Netz
LAGE_COLUMNS = ["lage_korrigiert", "hausdorff_m", "max_verschiebung_m", "differenzflaeche_m2", "laenge_alt_m", "laenge_neu_m"]
CONFLICT_COLUMNS = ["grund", "art", "eintrag_id", "ref", "element_nr", "abweichung_m", "bearbeitet_von", "bearbeitet_am"]
ASSIGNMENT_COLUMNS = ["abschnitt_id", "radfernweg", "art", "kanten", "status", "hinweis", "kommentar", "eintrag_id",
                      "bearbeitet_von", "bearbeitet_am"]

# Virtuelle Knoten, die näher am Ende der Trägerkante liegen, teilen sie nicht (keine winzigen Teilkanten)
SPLIT_END_TOLERANCE_M = 0.5

ATTRIBUTE_FIELDS = ("fahrbahn_typ", "fahrbahn_gruppe", "verkehrsrichtung")
ELEMENT_NR_PATTERN = re.compile(r"^(.+)_(.+)\.(\d+)$")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s", force=True)

_to_utm = Transformer.from_crs("EPSG:4326", CRS, always_xy=True)
_to_wgs = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True)


def to_utm(coordinates):
    """[[lng, lat], ...] -> LineString in EPSG:25833."""
    return LineString([_to_utm.transform(lng, lat) for lng, lat in coordinates])


def as_exported(line):
    """Die Linie so, wie sie in der Eingabedatei der App steht: WGS84, 7 Nachkommastellen (der Export
    rundet mit set_precision, dabei können eng beieinander liegende Stützpunkte zusammenfallen)."""
    wgs = shapely.ops.transform(lambda x, y, z=None: _to_wgs.transform(x, y), line)
    rounded = shapely.set_precision(wgs, COORDINATE_GRID)
    if not isinstance(rounded, LineString) or rounded.is_empty:
        return line
    return to_utm(list(rounded.coords))


def deviation_m(a, b):
    """Größte Abweichung zweier Linien: Hausdorff und Punkt für Punkt. Eine andere Stützpunktzahl gilt
    als Abweichung (unendlich), wie beim Prüfen gegen das Eingabenetz in der App."""
    if len(a.coords) != len(b.coords):
        return float("inf")
    return max(a.hausdorff_distance(b), max(Point(p).distance(Point(q)) for p, q in zip(a.coords, b.coords)))


def replay(original_coordinates, changes):
    """Spielt das Protokoll ab (wie replayCorrection in der App): (Koordinaten, Attribute).

    Unbekannte Zusatzfelder bleiben unbeachtet, z. B. `macht_rueckgaengig` (die vorgang_id, die eine
    Zeile zurücknimmt): Ein zurückgenommenes Einfügen steht als `zurueckgesetzt` mit folgenden
    „Wiederholt: …“-Zeilen im Protokoll, das Abspielen in Reihenfolge deckt das ab.

    Wie replayCorrection in der App: `verschoben` mit Index außerhalb der Linie und `eingefuegt` mit
    Index hinter dem Ende werden übersprungen, `attribut` gilt nur für die drei Felder,
    `ausgeschlossen` setzt `nach_wert is True`, eine unbekannte Art wird mit Warnung ignoriert."""
    coordinates = [list(point) for point in original_coordinates]
    attribute = {}
    for change in changes:
        kind = change["art"]
        index = change.get("index")
        if kind == "verschoben":
            if isinstance(index, int) and 0 <= index < len(coordinates) and change.get("nach"):
                coordinates[index] = list(change["nach"])
        elif kind == "eingefuegt":
            if isinstance(index, int) and 0 <= index <= len(coordinates) and change.get("nach"):
                coordinates.insert(index, list(change["nach"]))
        elif kind == "attribut":
            if change.get("feld") in ATTRIBUTE_FIELDS:
                attribute[change["feld"]] = change.get("nach_wert")
        elif kind == "ausgeschlossen":
            attribute["ausgeschlossen"] = change.get("nach_wert") is True
        elif kind == "zurueckgesetzt":
            coordinates = [list(point) for point in original_coordinates]
            attribute = {}
        else:
            logging.warning(f"Unbekannte Änderungsart {kind!r} im Protokoll ignoriert")
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
    """Markierungsspalten: leer, wo nichts aus der App kommt. `verkehrsrichtung` (aus dem Detailnetz) bleibt
    der aktuelle Wert, `verkehrsrichtung_original` hält den Wert vor der Korrektur."""
    network = network.copy()
    if "verkehrsrichtung" not in network.columns:
        network["verkehrsrichtung"] = None
    network["verkehrsrichtung_original"] = network["verkehrsrichtung"]
    network["verkehrsrichtung_korrigiert"] = "nein"
    network["lage_korrigiert"] = "nein"
    network["fahrbahn_typ"] = None
    network["fahrbahn_gruppe"] = None
    network["ausgeschlossen"] = "nein"
    network["ausschluss_grund"] = None
    network["eintrag_ids"] = None
    if "ursprung_element_nr" not in network.columns:  # step 1 fills it where it renumbered an edge
        network["ursprung_element_nr"] = None
    network["anzahl_vorgaenge"] = pd.array([0] * len(network), dtype="Int64")
    network["letzte_aenderung_am"] = None
    network["letzte_aenderung_von"] = None
    network["korrektur_kommentar"] = None
    for column in ("quelle", "grund_aufnahme", "routen_fernradweg", "routen_quelle"):
        if column not in network.columns:
            network[column] = "radnetz" if column == "quelle" else None
    return network


def add_entry_id(network, index, entry_id):
    """Trägt die KV-Id eines Eintrags in eintrag_ids der Kante ein (ohne Doppelte)."""
    current = network.at[index, "eintrag_ids"]
    ids = current.split("; ") if isinstance(current, str) and current else []
    if entry_id not in ids:
        network.at[index, "eintrag_ids"] = "; ".join(ids + [entry_id])


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
    ref_count = {}
    for entry in entries:
        data = entry["data"]
        if data.get("kind") == "edge_correction" and not data.get("geloescht"):
            ref_count[data["kante"]["ref"]] = ref_count.get(data["kante"]["ref"], 0) + 1

    for entry in sorted(entries, key=lambda item: item.get("updated_at") or ""):
        data = entry["data"]
        if data.get("kind") != "edge_correction" or data.get("geloescht"):
            continue
        stats["edge_correction"] += 1
        kante = data["kante"]
        ref = kante["ref"]
        if ref_count[ref] > 1:
            conflicts.append(conflict(entry, data, f"Mehrere Einträge zur selben Kante ({ref_count[ref]}): keiner wird angewendet"))
            stats["konflikte"] += 1
            continue

        original = to_utm(data["original_coordinates"])
        item = parts.by_ref.get(ref)
        reason, distance = None, None
        if item is None:
            reason = "Kante fehlt im Eingangsnetz (ref nicht vorhanden)"
        elif kante.get("element_nr") and item["element_nr"] != kante["element_nr"]:
            # Die ref gibt es, die Nummerierung der Linien hat sich aber verschoben (z. B. Export nur eines
            # Bezirks): dann sucht die Geometrie unter den Linien derselben element_nr
            candidates = parts.same_number(kante["element_nr"])
            item = next((c for c in candidates if deviation_m(as_exported(c["line"]), original) <= CONFLICT_TOLERANCE_M), None)
            if item is None:
                reason = "ref gehört im Eingangsnetz zu einer anderen element_nr, Geometrie keiner Linie der element_nr gleich"
        if item is not None:
            distance = deviation_m(as_exported(item["line"]), original)
            if distance == float("inf"):
                distance = None
                reason = "original_coordinates haben eine andere Stützpunktzahl als die Kante im Eingangsnetz"
            elif distance > CONFLICT_TOLERANCE_M:
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
            network.at[index, "lage_korrigiert"] = "ja"
            stats["geometrie"] += 1
        attribute = data.get("attribute", {})
        for field in ("fahrbahn_typ", "fahrbahn_gruppe"):
            if attribute.get(field) is not None:
                network.at[index, field] = attribute[field]
        direction = attribute.get("verkehrsrichtung")
        if direction is not None:
            if direction != network.at[index, "verkehrsrichtung_original"]:
                network.at[index, "verkehrsrichtung_korrigiert"] = "ja"
            network.at[index, "verkehrsrichtung"] = direction
        if attribute.get("ausgeschlossen"):
            network.at[index, "ausgeschlossen"] = "ja"
            network.at[index, "ausschluss_grund"] = data.get("kommentar")
        if significant_attributes(attribute):
            stats["attribute"] += 1
        add_entry_id(network, index, entry["id"])
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


def has_text(value):
    """True for a non-empty string (pandas gives NaN, a float, for a missing text)."""
    return isinstance(value, str) and value != ""


def virtual_node_frame(entries, parts, taken_names=()):
    """All virtual nodes drawn in the app (export, not deleted) in the fields of virtuelle_knoten.gpkg.
    `taken_names`: names of the nodes from step 1 (2025 and automatic). Returns (nodes, conflicts); a name used
    twice stays once (the earlier entry, or the node from step 1)."""
    rows, conflicts, names = [], [], {}
    for entry in active_entries(entries, "virtual_node"):
        data = entry["data"]
        if data.get("geloescht"):
            continue
        name = data["name"]
        if name in taken_names or name in names:
            origin = "a node from step 1 (2025 or automatic)" if name in taken_names else f"entry {names[name]}"
            conflicts.append({"grund": f"Virtueller Knoten {name} kommt schon vor ({origin}); der erste gilt",
                              "art": "virtual_node", "eintrag_id": entry["id"], "ref": None, "element_nr": None, "abweichung_m": None,
                              "bearbeitet_von": entry.get("updated_by"), "bearbeitet_am": entry.get("updated_at")})
            continue
        names[name] = entry["id"]
        x, y = _to_utm.transform(*data["lngLat"])
        host = data.get("traeger") or {}
        item = parts.by_ref.get(host.get("ref")) if host.get("art") == "ren" else None
        if item is not None:
            host_element_nr = item["element_nr"]
        elif host.get("art") == "detailnetz":
            host_element_nr = str(host.get("ref", "")).split("#")[0] or None
        else:
            host_element_nr = None
        rows.append({
            "Knotenpunkt-ID": name,
            "ist_virtuell": 1,
            "quelle": "app",
            "art": None,
            "traeger_netz": host.get("art"),
            "traeger_element_nr": host_element_nr,
            "station_m": round(host["station_m"], 2) if host.get("station_m") is not None else None,
            "kommentar": data.get("kommentar"),
            "eintrag_id": entry["id"],
            "geometry": Point(x, y),
        })
    return gpd.GeoDataFrame(rows, columns=NODE_COLUMNS, geometry="geometry", crs=CRS), conflicts


def read_step1_nodes(path=None):
    """Virtual nodes of step 1 (2025 and automatic): ren-network/output/virtuelle_knoten_roh.gpkg."""
    path = Path(path or ren.VIRTUAL_NODES_PATH)
    if not path.exists():
        raise SystemExit(f"Missing: {path}\nRun ren-network/merge_networks.py first (step 1).")
    nodes = gpd.read_file(path, layer=ren.VIRTUAL_NODES_LAYER)
    if nodes.crs is None or nodes.crs.to_epsg() != ren.DEFAULT_CRS:
        nodes = nodes.to_crs(CRS)
    return nodes[[column for column in NODE_COLUMNS if column in nodes.columns]]


def check_nodes_on_edges(entries, network, parts, accepted_ids=None):
    """Virtuelle Knoten auf einer REN+-Kante müssen auf der (korrigierten) Kante liegen.
    `accepted_ids`: nur diese Einträge (die virtual_node_frame übernommen hat); None = alle."""
    found = []
    corrected = Parts(network)
    for entry in active_entries(entries, "virtual_node"):
        data = entry["data"]
        host = data.get("traeger", {})
        if data.get("geloescht") or host.get("art") != "ren":
            continue
        if accepted_ids is not None and entry["id"] not in accepted_ids:
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


def write_virtual_nodes(path, step1_nodes, app_nodes):
    """Writes all virtual nodes: 2025 + automatic (step 1) + drawn in the app. The file is rebuilt on every run."""
    path.parent.mkdir(parents=True, exist_ok=True)
    nodes = gpd.GeoDataFrame(pd.concat([step1_nodes, app_nodes], ignore_index=True), geometry="geometry", crs=CRS)
    nodes.to_file(path, layer=VIRTUAL_NODES_LAYER, driver="GPKG")
    return nodes


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


def write_new_edges(path, frame):
    """Schreibt die gezeichneten Kanten des Exports; die Datei entsteht bei jedem Lauf neu."""
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_file(path, layer=NEW_EDGES_LAYER, driver="GPKG")


def load_base_element_nrs(network, detail_path):
    element_nrs = list(network["element_nr"])
    if detail_path is not None and Path(detail_path).exists():
        element_nrs += list(gpd.read_file(detail_path, columns=["element_nr"])["element_nr"])
    return element_nrs


def split_routes(text):
    return [name for name in (text or "").split("; ") if name] if isinstance(text, str) else []


def entry_conflict(entry, data, reason, ref=None, element_nr=None):
    return {"grund": reason, "art": data.get("kind"), "eintrag_id": entry.get("id"), "ref": ref, "element_nr": element_nr,
            "abweichung_m": None, "bearbeitet_von": entry.get("updated_by"), "bearbeitet_am": entry.get("updated_at")}


def read_sections(path):
    """Abschnitte der Radfernwege aus Schritt 2: id -> {radfernweg, kanten}. Ohne Datei None."""
    if path is None or not Path(path).exists():
        return None
    frame = gpd.read_file(path, layer=SECTIONS_LAYER)
    return {row.id: {"radfernweg": row.radfernweg, "kanten": [key for key in (row.kanten or "").split("|") if key]}
            for row in frame.itertuples()}


def apply_assignments(network, parts, entries, sections, detail_lines):
    """Spielt die section_assignment-Einträge auf das Netz ab (nach den Korrekturen).

    `parts`: Linien des Eingangsnetzes mit ihrem Schlüssel `ref` (Parts), `sections`: id -> Abschnitt aus
    Schritt 2 (oder None), `detail_lines`: Linien des Detailnetzes mit Spalte `ref` (oder None).
    Gibt (Netz, Konflikte, Zeilen für radfernweg_zuordnungen.csv, Zähler) zurück."""
    items = [entry for entry in active_entries(entries, "section_assignment") if not entry["data"].get("geloescht")]
    conflicts, report = [], []
    stats = {"abschnitte": len(items), "zugeordnet": 0, "keine_aktion": 0, "konflikte": 0, "aufgenommen": 0, "umgelegt": 0}
    if not items:
        return network, conflicts, report, stats

    def row_of(entry, data, art, status, hinweis=""):
        abschnitt = data.get("abschnitt") or {}
        report.append({"abschnitt_id": abschnitt.get("id"), "radfernweg": abschnitt.get("radfernweg"), "art": art,
                       "kanten": "|".join(data.get("kanten") or []), "status": status, "hinweis": hinweis,
                       "kommentar": data.get("kommentar"), "eintrag_id": entry.get("id"),
                       "bearbeitet_von": entry.get("updated_by"), "bearbeitet_am": entry.get("updated_at")}) 

    def reject(entry, data, reason):
        conflicts.append(entry_conflict(entry, data, reason, ref=(data.get("abschnitt") or {}).get("id")))
        stats["konflikte"] += 1
        row_of(entry, data, data.get("art"), "konflikt", reason)

    detail_by_ref = {}
    if detail_lines is not None:
        detail_by_ref = {ref: row for ref, row in zip(detail_lines["ref"], detail_lines.itertuples())}
    rows_by_element_nr = {}
    for index, element_nr in zip(network.index, network["element_nr"]):
        if isinstance(element_nr, str):
            rows_by_element_nr.setdefault(element_nr, []).append(index)

    # Ein Eintrag je Abschnitt: bei mehreren gilt der jüngste, die anderen sind Konflikte
    newest = {}
    for entry in sorted(items, key=lambda item: item.get("updated_at") or ""):
        newest[(entry["data"].get("abschnitt") or {}).get("id")] = entry
    valid = []
    for entry in items:
        data = entry["data"]
        abschnitt = data.get("abschnitt") or {}
        sid = abschnitt.get("id")
        if newest.get(sid) is not entry:
            reject(entry, data, f"Mehrere Einträge zum Abschnitt {sid}: der jüngste gilt")
        elif sections is None:
            reject(entry, data, "radfernweg_abschnitte.gpkg fehlt: Abschnitt nicht prüfbar (Schritt 2 laufen lassen)")
        elif sid not in sections:
            reject(entry, data, f"Abschnitt {sid} nicht in radfernweg_abschnitte.gpkg")
        elif sections[sid]["radfernweg"] != abschnitt.get("radfernweg"):
            reject(entry, data, f"Abschnitt {sid} gehört zu {sections[sid]['radfernweg']}, nicht zu {abschnitt.get('radfernweg')}")
        elif data.get("art") == "keine_aktion":
            stats["keine_aktion"] += 1
            row_of(entry, data, "keine_aktion", "angewendet", "keine Änderung am Netz")
        elif data.get("art") != "zugeordnet" or not data.get("kanten"):
            reject(entry, data, f"Art {data.get('art')!r} mit {len(data.get('kanten') or [])} Kanten nicht auswertbar")
        else:
            valid.append(entry)

    # Kanten-Schlüssel auf Zeilen des Netzes abbilden; unbekannte Kante: der ganze Eintrag gilt nicht
    resolved = {}
    for entry in valid:
        data = entry["data"]
        targets, problem = [], None
        for key in data["kanten"]:
            kind, _, ref = key.partition(":")
            if kind == "ren" and ref in parts.by_ref:
                targets.append(("row", network.index[parts.by_ref[ref]["row"]], key))
            elif kind == "detailnetz" and ref in detail_by_ref:
                edge = detail_by_ref[ref]
                if edge.element_nr in rows_by_element_nr:
                    targets.extend(("row", index, key) for index in rows_by_element_nr[edge.element_nr])
                else:
                    targets.append(("detail", ref, key))
            else:
                problem = f"Kante {key} nicht im Netz"
                break
        if problem:
            reject(entry, data, problem)
        else:
            resolved[entry["id"]] = targets

    # Umlegung: Kanten, die der Abschnitt automatisch trug und die der Eintrag nicht mehr nennt, verlieren die Route.
    # Behalten wird sie, wo eine andere, nicht ersetzte Zuordnung derselben Route die Kante noch trägt.
    replaced = {(entry["data"]["abschnitt"]["id"]) for entry in valid if entry["id"] in resolved}
    still_used = {(sections[sid]["radfernweg"], key) for sid in sections if sid not in replaced for key in sections[sid]["kanten"]}
    dropped = set()
    removed_from = {}
    for entry in valid:
        if entry["id"] not in resolved:
            continue
        data = entry["data"]
        route = data["abschnitt"]["radfernweg"]
        for key in sections[data["abschnitt"]["id"]]["kanten"]:
            if key in data["kanten"] or (route, key) in still_used:
                continue
            kind, _, ref = key.partition(":")
            if kind == "ren" and ref in parts.by_ref:
                indexes = [network.index[parts.by_ref[ref]["row"]]]
            elif kind == "detailnetz" and ref in detail_by_ref:
                indexes = rows_by_element_nr.get(detail_by_ref[ref].element_nr, [])
            else:
                continue
            for index in indexes:
                names = split_routes(network.at[index, "routen_fernradweg"])
                if route in names and network.at[index, "routen_quelle"] in ("auto", "auto; manuell"):
                    names.remove(route)
                    network.at[index, "routen_fernradweg"] = routes_text(names)
                    if not names:
                        network.at[index, "routen_quelle"] = None
                        if network.at[index, "quelle"] in ("detailnetz_radfernweg", "detailnetz_manuell"):
                            dropped.add(index)
                    elif network.at[index, "routen_quelle"] == "auto; manuell":
                        network.at[index, "routen_quelle"] = "manuell"
                    removed_from.setdefault(data["abschnitt"]["id"], []).append(key)
                    add_entry_id(network, index, entry["id"])

    # Zuordnen
    new_edges = {}  # detailnetz-ref -> (routen, Einträge)
    for entry in valid:
        if entry["id"] not in resolved:
            continue
        data = entry["data"]
        route = data["abschnitt"]["radfernweg"]
        notes = []
        for kind, target, key in resolved[entry["id"]]:
            if kind == "row":
                names = split_routes(network.at[target, "routen_fernradweg"])
                if route not in names:
                    previous = network.at[target, "routen_quelle"]
                    network.at[target, "routen_fernradweg"] = routes_text(names + [route])
                    network.at[target, "routen_quelle"] = {None: "manuell", "auto": "auto; manuell"}.get(
                        previous if isinstance(previous, str) else None, previous)
                add_entry_id(network, target, entry["id"])
                dropped.discard(target)
            else:
                routes, ids = new_edges.setdefault(target, (set(), []))
                routes.add(route)
                ids.append(entry["id"])
                notes.append(f"{key} ins Netz aufgenommen")
        if removed_from.get(data["abschnitt"]["id"]):
            stats["umgelegt"] += 1
            notes.append(f"löst {len(set(removed_from[data['abschnitt']['id']]))} automatisch zugeordnete Kanten ab")
        stats["zugeordnet"] += 1
        row_of(entry, data, "zugeordnet", "angewendet", "; ".join(notes))

    if dropped:
        network = network.drop(index=sorted(dropped))
    if new_edges:
        refs = sorted(new_edges)
        edges = pd.DataFrame([detail_by_ref[ref]._asdict() for ref in refs])
        edges = gpd.GeoDataFrame(edges, geometry="geometry", crs=CRS)
        first_new = len(network)
        network = append_detail_rows(network, edges, "detailnetz_manuell", "radfernweg_manuell",
                                     [routes_text(new_edges[ref][0]) for ref in refs], "manuell")
        for offset, ref in enumerate(refs):
            for entry_id in new_edges[ref][1]:
                add_entry_id(network, network.index[first_new + offset], entry_id)
        stats["aufgenommen"] = len(refs)
    return network, conflicts, report, stats


def node_text(value):
    """Knoten-IDs als Text: virtuelle IDs beginnen mit V, die übrigen sind Zahlen (von_knoten ist im Netz Integer)."""
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    return str(int(value)) if isinstance(value, numbers.Number) else str(value)


def add_drawn_edges(network, original_geometry, new_edges, entries):
    """Hängt die in der App gezeichneten Kanten (new_edges aus new_edge_frame) als Zeilen an das Netz.

    quelle = neu_gezeichnet, routen_fernradweg aus dem Eintrag (routen_quelle = manuell), element_nr wie in der
    App. Gibt (Netz, Originallage, Indexmarke je entry_id) zurück; die Lage ist die gezeichnete, in beiden Netzen."""
    if len(new_edges) == 0:
        return network, original_geometry, {}
    data_by_id = {entry["id"]: entry["data"] for entry in entries}
    rows = []
    for edge in new_edges.itertuples():
        data = data_by_id[edge.entry_id]
        routes = data.get("routen_fernradweg") or None
        rows.append({
            "element_nr": edge.element_nr, "element_nr_berechnet": "nein", "von_knoten": edge.von_knoten,
            "bis_knoten": edge.bis_knoten, "strassenname": edge.strassenname, "radverkehrsnetz": ren.RVN_KEIN,
            "hauptverkehrsstrasse": "nein", "netz_quellen": "netzanpassungen", "in_detailnetz": "nein",
            "bearbeitet_2025": "nein", "anteil_2025": 0.0, "quelle": "neu_gezeichnet",
            "grund_aufnahme": "radfernweg_manuell" if data.get("quelle") == "radfernweg" else None,
            "routen_fernradweg": routes, "routen_quelle": "manuell" if routes else None,
            "eintrag_ids": edge.entry_id, "geometry": MultiLineString([edge.geometry]),
        })
    added = gpd.GeoDataFrame(rows, geometry="geometry", crs=CRS)
    added = ren.add_district(added)
    added["laenge_m"] = added.geometry.length.round(1)
    for column, value in (("verkehrsrichtung_korrigiert", "nein"), ("lage_korrigiert", "nein"), ("ausgeschlossen", "nein"),
                          ("anzahl_vorgaenge", 0)):
        added[column] = value
    first = int(network["lfd_nr"].max()) + 1 if len(network) else 1
    added["lfd_nr"] = range(first, first + len(added))
    start = int(network.index.max()) + 1 if len(network) else 0
    added.index = range(start, start + len(added))
    labels = dict(zip(new_edges["entry_id"], added.index))
    added = added[[column for column in added.columns if column in network.columns]]
    network = gpd.GeoDataFrame(pd.concat([network, added]), geometry="geometry", crs=CRS)
    network["anzahl_vorgaenge"] = network["anzahl_vorgaenge"].astype("Int64")
    original_geometry = pd.concat([original_geometry, added.geometry])
    return network, original_geometry, labels


def split_at_virtual_nodes(network, original_geometry, labels_of_ref, drawn_labels, entries, base_element_nrs,
                           accepted_ids=None):
    """Teilt REN+-Kanten und gezeichnete Kanten an den virtuellen Knoten des Exports (wie splitEdges in der App,
    netzanpassungen/src/network/element-nr.ts im Repo knotenpunkte).

    Jede Teilkante bekommt eine neue element_nr `<von>_<bis>.<nn>` (nn zählt je Knotenpaar nach den vorhandenen
    Kanten, zuerst die Teile gezeichneter Kanten) und `ursprung_element_nr`; die Ursprungszeile entfällt. Die
    Station kommt aus der Lage des Knotens (Projektion auf die Trägerkante, bei Lagekorrekturen auf die korrigierte
    Linie, wo die App den Knoten mitgeführt hat); ein Knoten mehr als 1 m neben der Kante teilt sie nicht. Im Kundennetz (Originallage) liegt die
    Teilung bei demselben Anteil der Kantenlänge. Der freie Endknoten einer gezeichneten Kante teilt sie nicht.
    Nicht geteilt wird eine Trägerkante ohne Knotennamen oder mit mehreren Linien (steht in den Konflikten).
    `labels_of_ref`: Indexmarke und Linie je Schlüssel `ref` des Eingangsnetzes.
    Gibt (Netz, Originallage, Konflikte, Zähler) zurück."""
    nodes = [entry for entry in active_entries(entries, "virtual_node") if not entry["data"].get("geloescht")
             and (accepted_ids is None or entry["id"] in accepted_ids)]
    drawn_data = {entry["id"]: entry["data"] for entry in active_entries(entries, "new_edge")}
    conflicts, stats = [], {"geteilte_kanten": 0, "teilkanten": 0, "traeger_ohne_netz": 0, "knoten_neben_traeger": 0}
    hosts = {}  # Indexmarke -> [(Knoteneintrag)], in der Reihenfolge des Exports
    for entry in nodes:
        data = entry["data"]
        host = data.get("traeger") or {}
        if host.get("art") == "ren" and host.get("ref") in labels_of_ref and labels_of_ref[host["ref"]][0] in network.index:
            label = labels_of_ref[host["ref"]][0]
        elif host.get("art") == "neu" and host.get("ref") in drawn_labels:
            label = drawn_labels[host["ref"]]
            edge = drawn_data[host["ref"]]
            if f"v:{entry['id']}" in (edge["von"], edge["bis"]):
                continue  # freier Endknoten der gezeichneten Kante: teilt sie nicht
        else:
            stats["traeger_ohne_netz"] += 1
            continue
        hosts.setdefault(label, []).append(entry)

    drawn_label_set = set(drawn_labels.values())
    # Zuerst die gezeichneten Kanten, damit ihre Teile wie die Kanten selbst nummeriert werden
    order = sorted(hosts, key=lambda label: label not in drawn_label_set)
    counts = element_nr_counts(list(base_element_nrs) + [network.at[label, "element_nr"] for label in drawn_label_set])
    network = network.copy()
    network["von_knoten"] = network["von_knoten"].map(node_text)
    network["bis_knoten"] = network["bis_knoten"].map(node_text)
    names = {entry["id"]: entry["data"]["name"] for entry in nodes}
    next_label = int(network.index.max()) + 1
    next_lfd = int(network["lfd_nr"].max()) + 1
    pieces, piece_geometry, dropped = [], [], []
    for label in order:
        row = network.loc[label]
        line_parts = list(row.geometry.geoms)
        old_parts = list(original_geometry.loc[label].geoms)
        if len(line_parts) != 1:
            conflicts.append({"grund": f"Trägerkante {row['element_nr']} hat {len(line_parts)} Linien: nicht an virtuellen Knoten geteilt",
                              "art": "virtual_node", "eintrag_id": hosts[label][0]["id"], "ref": None, "element_nr": row["element_nr"],
                              "abweichung_m": None, "bearbeitet_von": None, "bearbeitet_am": None})
            continue
        if not has_text(row["von_knoten"]) or not has_text(row["bis_knoten"]):
            conflicts.append({"grund": f"Trägerkante {row['element_nr']} ohne Knoten: nicht an virtuellen Knoten geteilt",
                              "art": "virtual_node", "eintrag_id": hosts[label][0]["id"], "ref": None, "element_nr": row["element_nr"],
                              "abweichung_m": None, "bearbeitet_von": None, "bearbeitet_am": None})
            continue
        line, old_line = line_parts[0], old_parts[0]
        stops = []
        for entry in hosts[label]:
            data = entry["data"]
            point = Point(*_to_utm.transform(*data["lngLat"]))
            if line.distance(point) > NODE_ON_EDGE_TOLERANCE_M:
                stats["knoten_neben_traeger"] += 1  # steht schon als Hinweis in den Konflikten (check_nodes_on_edges)
                continue
            station = line.project(point)
            if SPLIT_END_TOLERANCE_M < station < line.length - SPLIT_END_TOLERANCE_M:
                stops.append((station, entry))
        if not stops:
            continue
        stops.sort(key=lambda item: item[0])
        scale = old_line.length / line.length if line.length else 1.0
        chain = [(0.0, row["von_knoten"], None)] + [(st, names[e["id"]], e) for st, e in stops] + [(line.length, row["bis_knoten"], None)]
        dropped.append(label)
        stats["geteilte_kanten"] += 1
        for (low, start, start_entry), (high, end, end_entry) in zip(chain[:-1], chain[1:]):
            key = pair_key(start, end)
            counts[key] = counts.get(key, 0) + 1
            element_nr = f"{start}_{end}.{counts[key]:02d}"
            piece = row.drop(labels=["geometry"]).to_dict()
            piece.update({"element_nr": element_nr, "von_knoten": start, "bis_knoten": end, "knoten_anfang": None, "knoten_ende": None,
                          "ursprung_element_nr": row["element_nr"], "lfd_nr": next_lfd, "eintrag_ids": row["eintrag_ids"]})
            next_lfd += 1
            for entry in (start_entry, end_entry):
                if entry is not None:
                    ids = piece["eintrag_ids"].split("; ") if isinstance(piece["eintrag_ids"], str) and piece["eintrag_ids"] else []
                    if entry["id"] not in ids:
                        piece["eintrag_ids"] = "; ".join(ids + [entry["id"]])
            pieces.append((next_label, piece))
            piece_geometry.append((next_label, MultiLineString([shapely.ops.substring(line, low, high)]),
                                   MultiLineString([shapely.ops.substring(old_line, low * scale, high * scale)])))
            next_label += 1
            stats["teilkanten"] += 1

    if not pieces:
        return network, original_geometry, conflicts, stats
    added = gpd.GeoDataFrame([piece for _, piece in pieces], index=[label for label, _ in pieces],
                             geometry=[geometry for _, geometry, _ in piece_geometry], crs=CRS)
    added["laenge_m"] = added.geometry.length.round(1)
    network = gpd.GeoDataFrame(pd.concat([network.drop(index=dropped), added[list(network.columns)]]), geometry="geometry", crs=CRS)
    old_added = gpd.GeoSeries([old for _, _, old in piece_geometry], index=[label for label, _, _ in piece_geometry], crs=CRS)
    original_geometry = pd.concat([original_geometry.drop(index=dropped), old_added])
    return network, original_geometry, conflicts, stats


def lage_metrics(old, new):
    """Kennzahlen zwischen alter und neuer Geometrie einer Kante (Meter, Quadratmeter)."""
    old_parts = list(old.geoms) if isinstance(old, MultiLineString) else [old]
    new_parts = list(new.geoms) if isinstance(new, MultiLineString) else [new]
    hausdorff = shift = area = 0.0
    for a, b in zip(old_parts, new_parts):
        if a.equals(b):
            continue
        hausdorff = max(hausdorff, a.hausdorff_distance(b))
        if len(a.coords) == len(b.coords):
            shift = max(shift, max(Point(p).distance(Point(q)) for p, q in zip(a.coords, b.coords)))
        else:
            shift = max(shift, a.hausdorff_distance(b))
        ring = list(a.coords) + list(b.coords)[::-1]
        if len(ring) >= 4:
            polygon = shapely.make_valid(shapely.Polygon(ring))
            area += sum(part.area for part in getattr(polygon, "geoms", [polygon]) if part.geom_type == "Polygon")
    return {"hausdorff_m": round(hausdorff, 3), "max_verschiebung_m": round(shift, 3), "differenzflaeche_m2": round(area, 2),
            "laenge_alt_m": round(old.length, 1), "laenge_neu_m": round(new.length, 1)}


def customer_and_working_network(corrected, original_geometry):
    """(Kundennetz, Arbeitsnetz): gleiche Kanten und Markierungen; das Kundennetz behält die Originallage und
    kennt weder lage_korrigiert noch die Kennzahlen."""
    working = corrected.copy()
    working["laenge_m"] = working.geometry.length.round(1)
    for column in LAGE_COLUMNS[1:]:
        working[column] = None
    for index in working.index[working["lage_korrigiert"] == "ja"]:
        for column, value in lage_metrics(original_geometry.loc[index], working.geometry.loc[index]).items():
            working.at[index, column] = value
    for column in LAGE_COLUMNS[1:]:
        working[column] = pd.to_numeric(working[column])
    customer = corrected.set_geometry(original_geometry.reindex(corrected.index)).drop(
        columns=[column for column in LAGE_COLUMNS if column in corrected.columns])
    customer["laenge_m"] = customer.geometry.length.round(1)
    return customer, working


def order_columns(network):
    first = [column for column in network.columns if column not in MARK_COLUMNS + LAGE_COLUMNS + ["geometry"]]
    rest = [column for column in MARK_COLUMNS + LAGE_COLUMNS if column in network.columns]
    return network[first + rest + ["geometry"]]


def mapping_network(network):
    """Kartierung: ohne bearbeitet_2025 = ja und ohne ausgeschlossene Kanten."""
    result = network[network["ausgeschlossen"] != "ja"]
    if "bearbeitet_2025" in result.columns:
        result = result[result["bearbeitet_2025"] != "ja"]
    return result


def run(export_path, ren_path=AUTO_PATH, output_dir=OUTPUT_DIR, virtual_nodes_path=VIRTUAL_NODES_PATH,
        new_edges_path=NEW_EDGES_PATH, detail_path=None, sections_path=SECTIONS_PATH, step1_nodes_path=None):
    """Der ganze Schritt 3. `export_path` None: ohne App-Einträge. Gibt Zähler und Konflikte zurück (für Tests)."""
    if export_path is None:
        export = {"gebiet": None, "exported_at": None, "entries": []}
    else:
        export = json.loads(Path(export_path).read_text(encoding="utf-8"))
    entries = export["entries"]
    logging.info(f"Export {export.get('gebiet')} vom {export.get('exported_at')}: {len(entries)} Einträge")

    network = gpd.read_file(ren_path, layer=ren.OUTPUT_LAYER)
    if network.crs is None or network.crs.to_epsg() != ren.DEFAULT_CRS:
        network = network.to_crs(CRS)
    original_geometry = network.geometry.copy()
    corrected, conflicts, stats, parts = apply_corrections(network, entries)
    labels = list(corrected.index)  # Indexmarke je Zeile des Eingangsnetzes (Parts.items[...]["row"] ist die Position)
    logging.info(f"Korrekturen: {stats['angewendet']} von {stats['edge_correction']} angewendet "
                 f"({stats['geometrie']} mit Geometrie, {stats['attribute']} mit Attributen), {stats['konflikte']} Konflikte")

    step1_nodes = read_step1_nodes(step1_nodes_path)
    nodes, node_conflicts = virtual_node_frame(entries, parts, set(step1_nodes["Knotenpunkt-ID"]))
    accepted_ids = set(nodes["eintrag_id"])
    conflicts += check_nodes_on_edges(entries, corrected, parts, accepted_ids)

    # Zuordnungen: Detailnetzlinien nur laden, wenn es Zuordnungen gibt
    assignments = [entry for entry in active_entries(entries, "section_assignment") if not entry["data"].get("geloescht")]
    detail_lines = None
    if assignments:
        detail_lines, _ = load_detailnetz(path=detail_path, extra_columns=("strassenklasse1", "strassenklasse2"))
        detail_lines["ref"] = line_refs(detail_lines["element_nr"])
    corrected, assignment_conflicts, assignment_report, assignment_stats = apply_assignments(
        corrected, parts, entries, read_sections(sections_path), detail_lines)
    conflicts += assignment_conflicts
    original_geometry = original_geometry.reindex(corrected.index)
    for index in corrected.index[original_geometry.isna()]:  # von Hand aufgenommene Kanten: Lage = Lage im Netz
        original_geometry.loc[index] = corrected.geometry.loc[index]
    stats.update({f"zuordnung_{key}": value for key, value in assignment_stats.items()})

    base_element_nrs = load_base_element_nrs(network, detail_path)
    new_edges, edge_conflicts = new_edge_frame(entries, base_element_nrs)
    conflicts += node_conflicts + edge_conflicts
    stats["virtuelle_knoten"] = len(nodes)
    stats["virtuelle_knoten_schritt1"] = len(step1_nodes)
    stats["neue_kanten"] = len(new_edges)

    # Gezeichnete Kanten in die Ergebnisnetze, dann REN+-Kanten und gezeichnete Kanten an den virtuellen Knoten teilen
    corrected, original_geometry, drawn_labels = add_drawn_edges(corrected, original_geometry, new_edges, entries)
    corrected, original_geometry, split_conflicts, split_stats = split_at_virtual_nodes(
        corrected, original_geometry, {item["ref"]: (labels[item["row"]], item["part"]) for item in parts.items},
        drawn_labels, entries, base_element_nrs, accepted_ids)
    conflicts += split_conflicts
    stats.update(split_stats)
    corrected["von_knoten"] = corrected["von_knoten"].map(node_text)
    corrected["bis_knoten"] = corrected["bis_knoten"].map(node_text)
    logging.info(f"Gezeichnete Kanten im Netz: {len(drawn_labels)}, geteilt an virtuellen Knoten: "
                 f"{split_stats['geteilte_kanten']} Kanten in {split_stats['teilkanten']} Teilkanten")
    if export_path is None:
        # Without an export the file would not know the nodes drawn in the app: keep the last state, if there is one
        logging.info("Without export: nodes drawn in the app and drawn edges stay as they are")
        if not Path(virtual_nodes_path).exists():
            write_virtual_nodes(Path(virtual_nodes_path), step1_nodes, nodes)
    else:
        all_nodes = write_virtual_nodes(Path(virtual_nodes_path), step1_nodes, nodes)
        write_new_edges(Path(new_edges_path), new_edges)
        logging.info(f"Virtual nodes: {len(all_nodes)} ({all_nodes['quelle'].value_counts().to_dict()}) to {virtual_nodes_path}, "
                     f"drawn edges: {len(new_edges)} to {new_edges_path}")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    customer, working = customer_and_working_network(corrected, original_geometry)
    for network_frame, path, mapping_path in ((order_columns(customer), NETZ_PATH, KARTIERUNG_PATH),
                                              (order_columns(working), NETZ_KORRIGIERT_PATH, KARTIERUNG_KORRIGIERT_PATH)):
        ren.write_network(network_frame, output_dir / path.name)
        mapping = mapping_network(network_frame)
        ren.write_network(mapping, output_dir / mapping_path.name)
        logging.info(f"{path.name}: {len(network_frame)} Kanten, Kartierung {len(mapping)} Kanten "
                     f"(ausgeschlossen: {(network_frame['ausgeschlossen'] == 'ja').sum()})")

    report = pd.DataFrame(conflicts, columns=CONFLICT_COLUMNS)
    report.to_csv(output_dir / CONFLICTS_PATH.name, index=False)
    logging.info(f"Konflikte: {len(report)}: {output_dir / CONFLICTS_PATH.name}")
    pd.DataFrame(assignment_report, columns=ASSIGNMENT_COLUMNS).to_csv(output_dir / ASSIGNMENTS_PATH.name, index=False)
    logging.info(f"Zuordnungen zu Abschnitten: {assignment_stats}: {output_dir / ASSIGNMENTS_PATH.name}")
    stats["konflikte_gesamt"] = len(report)
    return stats, conflicts


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("export", type=Path, nargs="?", help="Export „alle Einträge“ der App (JSON)")
    parser.add_argument("--ohne-export", action="store_true",
                        help="Ohne App-Einträge: nur die Ergebnisnetze aus Schritt 2 (Handarbeit fehlt dann); "
                             "virtuelle Knoten und gezeichnete Kanten werden nicht neu geschrieben")
    parser.add_argument("--ren-netz", type=Path, default=AUTO_PATH, help="Eingangsnetz (Standard: ren_netz_auto.gpkg)")
    args = parser.parse_args()
    if bool(args.export) == args.ohne_export:
        parser.error("Entweder den Export der App angeben oder --ohne-export")
    run(args.export, ren_path=args.ren_netz, detail_path=detailnetz_path())


if __name__ == "__main__":
    main()
