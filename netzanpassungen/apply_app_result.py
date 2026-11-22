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
  Ein Schlüssel `<Kante>@<von>-<bis>` nennt nur ein Stück der Kante (ganze Meter ab dem Anfang): `detailnetz:…@a-b` nimmt nur
  das Stück als neue Zeile auf (eigene element_nr aus den Knoten an den Enden), `ren:…@a-b` und `neu:…@a-b` geben die Route den
  Teilkanten innerhalb von a-b, nachdem die Kante an den virtuellen Knoten geteilt ist (siehe apply_assignments).
- virtual_node: virtueller Knoten mit seiner Nummer (`nummer`, vergibt nur die App). Alle nummerierten
  Knoten (aktiv und gelöscht, die 53 von 2025 eingeschlossen) kommen nach
  netzanpassungen/output/virtuelle_knoten.gpkg (die 53 von 2025 sind Einträge der App mit herkunft = rvn_2025,
  ihre Zeilen kommen aus den Einträgen; ein Eintrag von ihnen als Kantenende löst auf seine Nummer auf); das ist die Datei, die processing/ und knotenpunkte/ über
  read_active() aus data/virtuelle_knotenpunkte.py lesen. Ein Knoten ohne Nummer zählt nicht (Konflikt).
  Übernommene Knotenvorschläge von Schritt 1 (herkunft = vorschlag, vorschlag_id = P<x>-<y>): die
  Vorschlags-Id wird in von_knoten/bis_knoten/knoten_anfang/knoten_ende/element_nr durch die Nummer
  ersetzt (element_nr der Eingabe in element_nr_eingabe). Nicht übernommene Vorschläge bleiben mit ihrer
  P-Id und stehen als „Knotenvorschlag noch nicht übernommen“ in korrekturen_konflikte.csv, außer Sackgassen
  (art dead_end: nie ein Knoten, keine Entscheidung nötig, nur im Log). Ein offener Vorschlag höchstens 0,1 m neben
  einem aktiven Knoten der App ohne vorschlag_id gilt als von diesem Knoten übernommen (keine erneute Teilung).
  Eine Korrektur, die auf dem Original steht (coordinates = original_coordinates, attribute leer, z. B. nach
  „zurückgesetzt“), ändert nichts und wird übersprungen.
- bridge_check: Prüfung „Brücken und Tunnel“ eines Knotens (Tag `bauwerk`). `ok` ändert nichts. `getrennt`: die Enden der
  REN+-Kanten in `unten` am Knoten bekommen den neuen Knoten `<Knoten>-unten` (gleiche Lage, steht in
  netzanpassungen/output/bauwerk_knoten.gpkg), alle Kanten am Knoten die Spalten bauwerk und bauwerk_lage (oben | unten). Wird als Letztes
  angewendet (apply_bridge_checks); eine fehlende Kante oder ein fehlender Knoten ist ein Konflikt.
- Nach dem Abspielen liegt jedes Kantenende, das einen Knoten nennt (virtuell oder Detailnetz) und höchstens 3 m
  daneben liegt, genau auf dem Knoten (beide Ergebnisnetze). Treffen sich alle Kanten eines Knotens weiter weg an
  einem Punkt, bleibt alles, und der Knoten steht in korrekturen_konflikte.csv (eine Person entscheidet).
- new_edge: gezeichnete Kante. Steht in beiden Ergebnisnetzen (quelle = neu_gezeichnet, routen_fernradweg aus dem
  Eintrag mit routen_quelle = manuell, verkehrsrichtung aus dem Eintrag, ohne Angabe B, element_nr `<von>_<bis>.<nn>`
  wie in der App) und weiterhin in
  netzanpassungen/output/touristische_kanten.gpkg.
- Virtuelle Knoten teilen ihre Trägerkante (REN+-Kante oder gezeichnete Kante) in beiden Ergebnisnetzen: Jede Teilkante
  bekommt eine neue element_nr und `ursprung_element_nr`, wie splitEdges in der App. REN+-Kanten teilt auch jedes
  REN+-Ende, das im Inneren einer anderen REN+-Kante liegt (T-Kreuzung der Quelle, 1,5 m, mehr als 2 m von den Enden), an seinem
  vorhandenen Knoten. Die Teilung an Detailnetz und
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
- Einträge der App: standardmäßig direkt aus ihrer KV-Datenbank (kv_entries.py, Gebiet --gebiet, Zugang aus .env),
  mit --export aus einer JSON-Datei des App-Exports „Alle Einträge“ ({gebiet, exported_at, entries});
  mit --ohne-export ohne Einträge
- netzanpassungen/output/ren_netz_auto.gpkg (match_cycle_routes.py)
- netzanpassungen/output/radfernweg_abschnitte.gpkg (nur für section_assignment)
- ren-network/output/virtuelle_knoten_vorschlaege.gpkg (die 53 von 2025 kommen aus den Einträgen der App)
- data/Berlin Straßenabschnitte Detailnetz*.fgb (element_nr für die Nummern neuer Kanten, Linien für
  von Hand zugeordnete Detailnetzkanten)

OUTPUT:
- ren-network/output/ren_netz.gpkg / .geojson, ren_netz_kartierung.gpkg / .geojson
- ren-network/output/ren_netz_korrigiert.gpkg / .geojson, ren_netz_kartierung_korrigiert.gpkg / .geojson
- ren-network/output/korrekturen_konflikte.csv, radfernweg_zuordnungen.csv
- netzanpassungen/output/virtuelle_knoten.gpkg (Layer Virtuelle-Knotenpunkte: die Spalten des Verzeichnisses
  plus herkunft, app_eintrag, vorschlag_id, traeger_netz, traeger_element_nr, station_m)
- netzanpassungen/output/touristische_kanten.gpkg (Layer touristische_kanten)
- netzanpassungen/output/bauwerk_knoten.gpkg (Layer bauwerk_knoten: die Knoten `<Knoten>-unten` der Prüfung Brücken und Tunnel)

Aufruf:
    python netzanpassungen/apply_app_result.py                       # Einträge aus der KV-Datenbank, Gebiet berlin
    python netzanpassungen/apply_app_result.py --export netzanpassungen-alle-eintraege-berlin-2026-11-12.json
    python netzanpassungen/apply_app_result.py --ohne-export    # nur Schritt 2, keine Handarbeit; ein
                                                                     # vorhandenes virtuelle_knoten.gpkg bleibt, fehlt es,
                                                                     # entsteht es nur mit den 53 von 2025
"""

import argparse
from collections import defaultdict
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
sys.path.append(str(ROOT / "data"))

import kv_entries  # noqa: E402
import merge_networks as ren  # noqa: E402
from auto_nodes import assert_unique, end_at, is_noop_correction, is_proposal  # noqa: E402
import virtuelle_knotenpunkte as vk  # noqa: E402
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
VIRTUAL_NODES_PATH = vk.OUTPUT_PATH  # netzanpassungen/output/virtuelle_knoten.gpkg, read by read_active()
VIRTUAL_NODES_LAYER = vk.LAYER
VIRTUAL_NODE_COLUMNS = vk.COLUMNS + vk.OUTPUT_EXTRA_COLUMNS + ["geometry"]
OPEN_PROPOSAL_REASON = "Knotenvorschlag noch nicht übernommen"
# An open proposal this close to an active node of the app without vorschlag_id is taken by that node
PROPOSAL_AT_NODE_M = 0.1
# An edge end naming a virtual node within this distance is moved exactly onto it; where all edges naming a node meet
# farther away (within NODE_MEETING_SPREAD_M of each other), a person decides (conflict)
NODE_END_SNAP_M = 3.0
NODE_MEETING_SPREAD_M = 1.0
NEW_EDGES_PATH = APP_OUTPUT_DIR / "touristische_kanten.gpkg"
NEW_EDGES_LAYER = "touristische_kanten"
# Brücken und Tunnel (bridge_check): the new node of the lower level is written to its own file, not to the registry of
# virtual nodes (its id `<Knoten>-unten` is no four-digit number)
BRIDGE_NODES_NAME = "bauwerk_knoten.gpkg"
BRIDGE_NODES_LAYER = "bauwerk_knoten"
LOWER_NODE_SUFFIX = "-unten"
NODE_COLUMNS = ("von_knoten", "bis_knoten", "knoten_anfang", "knoten_ende")

# Spalten, die beide Ergebnisnetze zusätzlich zum Netz aus Schritt 2 tragen (Reihenfolge der Datei)
MARK_COLUMNS = ["verkehrsrichtung_original", "verkehrsrichtung_korrigiert", "fahrbahn_typ", "fahrbahn_gruppe",
                "ausgeschlossen", "ausschluss_grund", "eintrag_ids", "anzahl_vorgaenge", "letzte_aenderung_am",
                "letzte_aenderung_von", "korrektur_kommentar", "aenderung", "element_nr_eingabe", "bauwerk", "bauwerk_lage"]
# Nur im korrigierten Netz
LAGE_COLUMNS = ["lage_korrigiert", "hausdorff_m", "max_verschiebung_m", "differenzflaeche_m2", "laenge_alt_m", "laenge_neu_m"]
CONFLICT_COLUMNS = ["grund", "art", "eintrag_id", "ref", "element_nr", "abweichung_m", "bearbeitet_von", "bearbeitet_am"]
ASSIGNMENT_COLUMNS = ["abschnitt_id", "radfernweg", "art", "kanten", "status", "hinweis", "kommentar", "eintrag_id",
                      "bearbeitet_von", "bearbeitet_am"]

# Virtuelle Knoten, die näher am Ende der Trägerkante liegen, teilen sie nicht (keine winzigen Teilkanten)
SPLIT_END_TOLERANCE_M = 0.5
# T-junctions of the source REN+ network: a REN+ edge that ends within REN_END_ON_EDGE_M of the interior of another REN+ edge
# (more than REN_CUT_MIN_M from its ends and from other cuts) splits it there, as the app cuts it into parts
# (parts.ts in the app: REN_END_ON_EDGE_M, MIN_PART_M)
REN_END_ON_EDGE_M = 1.5
REN_CUT_MIN_M = 2.0

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
    Index hinter dem Ende werden übersprungen, `entfernt` nimmt nur einen inneren Stützpunkt heraus, `attribut` gilt nur für die drei Felder,
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
        elif kind == "entfernt":
            # Nur innere Stützpunkte: die Enden gehören zu den Knoten
            if isinstance(index, int) and 0 < index < len(coordinates) - 1:
                del coordinates[index]
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
    network["aenderung"] = None
    network["aenderung_lage"] = None
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
    network["bauwerk"] = None
    network["bauwerk_lage"] = None
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


DIRECTION_TEXT = {"B": "in beide Richtungen (B)", "R": "nur in Pfeilrichtung (R)", "G": "nur gegen Pfeilrichtung (G)"}
FIELD_TEXT = {"verkehrsrichtung": "Verkehrsrichtung", "fahrbahn_typ": "Fahrbahntyp", "fahrbahn_gruppe": "Fahrbahngruppe"}
# Sentences about the position go to aenderung only in the working network; the customer network gets AENDERUNG_LAGE_HINT
AENDERUNG_LAGE_HINT = "Lage korrigiert (nur in ren_netz_korrigiert.gpkg)"


def add_change(network, index, sentence, column="aenderung"):
    """Appends one German sentence to the column `aenderung` of an edge (`; `-separated, no duplicates)."""
    if not sentence:
        return
    current = network.at[index, column] if column in network.columns else None
    sentences = current.split("; ") if isinstance(current, str) and current else []
    if sentence not in sentences:
        network.at[index, column] = "; ".join(sentences + [sentence])


def format_m(value):
    """4.2 -> '4,2 m'."""
    return f"{value:.1f} m".replace(".", ",") if isinstance(value, numbers.Number) else "?"


def change_sentence(change):
    """One sentence for one step of the correction log: its `beschreibung` from the app, else built from the step."""
    if has_text(change.get("beschreibung")):
        return change["beschreibung"]
    art = change.get("art")
    if art == "verschoben":
        return f"Stützpunkt {format_m(change.get('abstand_m'))} verschoben"
    if art == "eingefuegt":
        return "Stützpunkt eingefügt"
    if art == "entfernt":
        return "Stützpunkt entfernt"
    if art == "ausgeschlossen":
        return "Kante ausgeschlossen" if change.get("nach_wert") else "Ausschluss aufgehoben"
    if art == "attribut":
        field = change.get("feld")
        value = change.get("nach_wert")
        text = DIRECTION_TEXT.get(value, value) if field == "verkehrsrichtung" else value
        return f"{FIELD_TEXT.get(field, field)}: {text if text is not None else 'nicht erfasst'}"
    return f"Änderung {art}" if art else None


def is_position_change(change):
    return change.get("art") in ("verschoben", "eingefuegt", "entfernt")


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
        if data.get("kind") == "edge_correction" and not data.get("geloescht") and not is_noop_correction(data):
            ref_count[data["kante"]["ref"]] = ref_count.get(data["kante"]["ref"], 0) + 1

    noop = 0
    for entry in sorted(entries, key=lambda item: item.get("updated_at") or ""):
        data = entry["data"]
        if data.get("kind") != "edge_correction" or data.get("geloescht"):
            continue
        if is_noop_correction(data):
            noop += 1  # back to the original (e.g. zurueckgesetzt): changes nothing, nothing to check
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
        if "verkehrsrichtung" in attribute:
            # null is a value of its own: set to "nicht erfasst" in the app
            direction = attribute["verkehrsrichtung"]
            original = network.at[index, "verkehrsrichtung_original"]
            if direction != (original if has_text(original) else None):
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
        for change in changes:
            add_change(network, index, change_sentence(change), "aenderung_lage" if is_position_change(change) else "aenderung")
        if attribute.get("ausgeschlossen") and data.get("kommentar"):
            add_change(network, index, f"Ausschlussgrund: {data['kommentar']}")
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
    if noop:
        logging.info(f"Edge corrections back at the original (no change, not applied): {noop}")
    return network, conflicts, stats, parts


def active_entries(entries, kind):
    return [entry for entry in entries if entry["data"].get("kind") == kind]


def has_text(value):
    """True for a non-empty string (pandas gives NaN, a float, for a missing text)."""
    return isinstance(value, str) and value != ""


def short_id(entry_id):
    """The app refers to entries by the last part of their KV id: `berlin:vk:<uuid>` -> `<uuid>`."""
    return entry_id.rsplit(":", 1)[-1] if isinstance(entry_id, str) else entry_id


def entry_date(value):
    """'2026-11-19T10:00:00Z' -> '2026-11-19'."""
    return value[:10] if isinstance(value, str) and len(value) >= 10 else None


class AppNodes:
    """The virtual nodes of the app entries with their numbers (contract: every node has `nummer`).

    `by_entry`: entry id -> number of the active, numbered nodes; `accepted`: proposal id of step 1 ->
    number (nodes with herkunft = vorschlag); `rows`: every numbered node (active and deleted) for
    virtuelle_knoten.gpkg. A node without number, or with a number that is taken already, is a conflict and
    does not count."""

    def __init__(self, entries, registry, parts):
        self.old_to_number = dict(zip(registry["id_rvn_2025"].dropna(), registry.loc[registry["id_rvn_2025"].notna(), vk.ID_COLUMN]))
        taken = set(registry[vk.ID_COLUMN])
        self.by_entry, self.by_short, self.accepted, self.rows, self.conflicts = {}, {}, {}, [], []
        self.accepted_entry_ids = set()
        for entry in sorted(active_entries(entries, "virtual_node"), key=lambda item: item.get("created_at") or ""):
            data = entry["data"]
            number = vk.pad_id(data.get("nummer"))
            deleted = bool(data.get("geloescht"))
            if data.get("herkunft") == vk.HERKUNFT_2025:
                # A node of 2025: its row comes from the registry; the input is split there already. Edges
                # drawn to it in the app name its entry, so the entry resolves to its number.
                if not deleted and number:
                    self.by_entry[entry["id"]] = number
                    self.by_short[short_id(entry["id"])] = number
                    self.accepted_entry_ids.add(entry["id"])
                continue
            if number is None or not vk.ID_PATTERN.match(number):
                if not deleted:
                    self.conflict(entry, f"Virtueller Knoten {data.get('name')} hat noch keine Nummer "
                                         "(die App vergibt sie, wenn ein Admin das Gebiet öffnet): zählt nicht")
                continue
            if number in taken:
                self.conflict(entry, f"Virtueller Knoten {number} ist schon vergeben: der Eintrag zählt nicht")
                continue
            taken.add(number)
            x, y = _to_utm.transform(*data["lngLat"])
            host = data.get("traeger") or {}
            item = parts.by_ref.get(host.get("ref")) if host.get("art") == "ren" else None
            if item is not None:
                host_element_nr = item["element_nr"]
            elif host.get("art") == "detailnetz":
                host_element_nr = str(host.get("ref", "")).split("#")[0] or None
            else:
                host_element_nr = host.get("ref")
            herkunft = data.get("herkunft")
            proposal = data.get("vorschlag_id") if herkunft == "vorschlag" else None
            self.rows.append({
                vk.ID_COLUMN: number, "ist_virtuell": 1,
                "status": vk.STATUS_DELETED if deleted else vk.STATUS_ACTIVE,
                "angelegt_am": entry_date(entry.get("created_at")),
                "geloescht_am": (data.get("geloescht_am") or entry_date(entry.get("updated_at"))) if deleted else None,
                "grund": (data.get("grund") or "in der App gelöscht") if deleted else None,
                "id_rvn_2025": None, "quelle": "Netzanpassungen-App", "kommentar": data.get("kommentar"),
                "herkunft": herkunft, "app_eintrag": entry["id"], "vorschlag_id": proposal,
                "traeger_netz": host.get("art"), "traeger_element_nr": host_element_nr,
                "station_m": round(host["station_m"], 2) if host.get("station_m") is not None else None,
                "geometry": Point(x, y),
            })
            if deleted:
                continue
            self.by_entry[entry["id"]] = number
            self.by_short[short_id(entry["id"])] = number
            if proposal:
                self.accepted[proposal] = number
                self.accepted_entry_ids.add(entry["id"])

    def adopt_proposals(self, proposals, tolerance=PROPOSAL_AT_NODE_M):
        """An open proposal within `tolerance` of an active node of the app without vorschlag_id counts as accepted
        by that node (its id is replaced by the node's number; the node does not split its host again, step 1 split
        there already). Returns [(proposal id, number)]."""
        open_rows = [row for row in proposals.itertuples() if row.id not in self.accepted]
        if not open_rows:
            return []
        tree = shapely.STRtree([row.geometry for row in open_rows])
        adopted = []
        for node in self.rows:
            entry_id = node["app_eintrag"]
            if node["status"] != vk.STATUS_ACTIVE or node["vorschlag_id"] or entry_id in self.accepted_entry_ids:
                continue
            near = tree.query_nearest(node["geometry"], max_distance=tolerance, all_matches=False)
            if not len(near):
                continue
            proposal = open_rows[int(near[0])].id
            if proposal in self.accepted:
                continue
            self.accepted[proposal] = node[vk.ID_COLUMN]
            self.accepted_entry_ids.add(entry_id)
            node["vorschlag_id"] = proposal
            adopted.append((proposal, node[vk.ID_COLUMN]))
        return adopted

    def conflict(self, entry, reason):
        self.conflicts.append({"grund": reason, "art": "virtual_node", "eintrag_id": entry["id"], "ref": None,
                               "element_nr": None, "abweichung_m": None, "bearbeitet_von": entry.get("updated_by"),
                               "bearbeitet_am": entry.get("updated_at")})

    @property
    def splitting_ids(self):
        """Entries whose node splits its host edge: all active numbered nodes except accepted proposals (the input
        is already split there)."""
        return set(self.by_entry) - self.accepted_entry_ids

    def node_of_key(self, key, known_ids):
        """Node id of an edge end in the app (`k:<id>` input node, `v:<entry id>` app node), or None.
        `k:` with a 2025 id (V…) resolves to its number; other `k:` ids must be in `known_ids`."""
        if key.startswith("k:"):
            node = self.old_to_number.get(key[2:], key[2:])
            return node if node in known_ids else None
        if key.startswith("v:"):
            return self.by_entry.get(key[2:]) or self.by_short.get(key[2:])
        return None


def read_proposals(path=None):
    """Node proposals of step 1 (ren-network/output/virtuelle_knoten_vorschlaege.gpkg); empty without the file."""
    path = Path(path or ren.PROPOSALS_PATH)
    if not path.exists():
        logging.warning(f"Missing: {path} (step 1): open node proposals are not listed")
        return gpd.GeoDataFrame({"id": [], "art": [], "traeger_element_nr": []}, geometry=[], crs=CRS)
    proposals = gpd.read_file(path, layer=ren.PROPOSALS_LAYER)
    return proposals.to_crs(CRS) if proposals.crs is not None and proposals.crs.to_epsg() != ren.DEFAULT_CRS else proposals


def proposal_conflicts(proposals, app_nodes):
    """Open proposals (not accepted in the app) and accepted proposals that step 1 no longer has. A dead end is never
    a node and needs no decision: open dead ends are logged, not listed."""
    found = []
    dead_ends = sorted(row.id for row in proposals.itertuples() if row.art == "dead_end" and row.id not in app_nodes.accepted)
    if dead_ends:
        logging.info(f"Dead ends (technical end ids, no decision needed): {len(dead_ends)} {dead_ends}")
    for row in proposals.itertuples():
        if row.id not in app_nodes.accepted and row.art != "dead_end":
            found.append({"grund": OPEN_PROPOSAL_REASON + f" ({row.art})", "art": "vorschlag", "eintrag_id": None,
                          "ref": row.id, "element_nr": row.traeger_element_nr, "abweichung_m": None,
                          "bearbeitet_von": None, "bearbeitet_am": None})
    known = set(proposals["id"])
    for proposal, number in app_nodes.accepted.items():
        if proposal not in known:
            found.append({"grund": f"Übernommener Knotenvorschlag {proposal} (Knoten {number}) ist nicht mehr unter den "
                                   "Vorschlägen von Schritt 1: das Netz hat sich dort geändert",
                          "art": "vorschlag", "eintrag_id": None, "ref": proposal, "element_nr": None,
                          "abweichung_m": None, "bearbeitet_von": None, "bearbeitet_am": None})
    return found


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


def virtual_node_rows(registry, app_nodes):
    """The 53 of 2025 + every numbered node of the app (active and deleted), in the columns of the registry plus
    herkunft, app_eintrag, vorschlag_id and the host."""
    base = registry.copy()
    base["herkunft"] = "2025"
    frames = [base]
    if app_nodes.rows:
        frames.append(gpd.GeoDataFrame(app_nodes.rows, geometry="geometry", crs=CRS))
    nodes = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), geometry="geometry", crs=CRS)
    for column in VIRTUAL_NODE_COLUMNS:
        if column not in nodes.columns:
            nodes[column] = None
    nodes = nodes[VIRTUAL_NODE_COLUMNS]
    nodes["ist_virtuell"] = 1
    for column in vk.TEXT_COLUMNS + [vk.ID_COLUMN]:
        nodes[column] = nodes[column].astype("string")
    nodes["station_m"] = pd.to_numeric(nodes["station_m"])
    return nodes.sort_values(vk.ID_COLUMN).reset_index(drop=True)


def write_virtual_nodes(path, nodes):
    """Writes netzanpassungen/output/virtuelle_knoten.gpkg; the file is rebuilt on every run."""
    errors = vk.check(nodes)
    if errors:
        raise RuntimeError("virtuelle_knoten.gpkg would break the rules:\n- " + "\n- ".join(errors))
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
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


def new_edge_frame(entries, base_element_nrs, app_nodes, known_ids):
    """Gezeichnete Kanten als Zeilen für touristische_kanten.gpkg. Die element_nr zählt wie in der App
    (Reihenfolge des Zeichnens). Knoten: `k:<id>` aus der Eingabedatei (`known_ids`; 2025-Kennungen V… über
    id_rvn_2025), `v:<Eintrag>` mit der Nummer des App-Knotens."""
    counts = element_nr_counts(base_element_nrs)
    rows, conflicts = [], []
    drawn = [entry for entry in active_entries(entries, "new_edge") if not entry["data"].get("geloescht")]
    for entry in sorted(drawn, key=lambda item: item.get("created_at") or ""):
        data = entry["data"]
        von, bis = app_nodes.node_of_key(data["von"], known_ids), app_nodes.node_of_key(data["bis"], known_ids)
        if not von or not bis:
            conflicts.append({"grund": f"Neue Kante: Knoten {data['von'] if not von else data['bis']} nicht auffindbar "
                                       "(gelöschter oder nicht nummerierter virtueller Knoten, oder Knoten einer älteren Eingabedatei)",
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
            # Ohne Angabe gilt eine gezeichnete Kante in beide Richtungen (wie in der App)
            "verkehrsrichtung": data.get("verkehrsrichtung") or "B",
            "kommentar": data.get("kommentar"),
            "geometry": to_utm(data["coordinates"]),
        })
    columns = ["entry_id", "element_nr", "von_knoten", "bis_knoten", "quelle", "strassenname", "routen_fernradweg",
               "verkehrsrichtung", "kommentar", "geometry"]
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
    """Abschnitte der Radfernwege aus Schritt 2: id -> {radfernweg, kanten, zustand, mitte}. Ohne Datei None.

    `mitte` ist der Punkt in der Mitte des Abschnitts (in CRS); die App zählt einen Abschnitt als gezeichnet, wenn eine
    neue Kante höchstens SECTION_DRAWN_DISTANCE_M daran vorbeiführt."""
    if path is None or not Path(path).exists():
        return None
    frame = gpd.read_file(path, layer=SECTIONS_LAYER).to_crs(CRS)
    return {row.id: {"radfernweg": row.radfernweg, "kanten": [key for key in (row.kanten or "").split("|") if key],
                     "zustand": getattr(row, "zustand", None),
                     "mitte": row.geometry.interpolate(0.5, normalized=True) if row.geometry is not None else None}
            for row in frame.itertuples()}


# Wie in der App (sections.ts): eine neue Kante, die so nah an der Mitte eines Abschnitts vorbeiführt, trägt ihn
SECTION_DRAWN_DISTANCE_M = 10.0


def short_entry_id(entry_id):
    """Der letzte Teil einer KV-Id (`berlin:kante:<uuid>` -> `<uuid>`); so verweist die App auf ihre Einträge."""
    return str(entry_id).rsplit(":", 1)[-1]


def drawn_section_routes(sections, new_edges, assigned_ids):
    """Radfernwege, die eine gezeichnete Kante ohne Zuordnung trägt: Lücken-Abschnitte ohne Eintrag, an deren Mitte
    die Kante höchstens SECTION_DRAWN_DISTANCE_M vorbeiführt (wie `sectionStatus` „gezeichnet“ in der App). So
    bekommt eine Kante, auf der zwei Routen liegen, beide. Gibt kurze Eintrags-Id -> [(Route, Abschnitt-Id)] zurück."""
    found = {}
    if not sections or new_edges is None or len(new_edges) == 0:
        return found
    for sid, section in sections.items():
        middle = section.get("mitte")
        if sid in assigned_ids or section.get("zustand") != "luecke" or middle is None:
            continue
        for entry_id, geometry in zip(new_edges["entry_id"], new_edges.geometry):
            if geometry is not None and geometry.distance(middle) <= SECTION_DRAWN_DISTANCE_M:
                found.setdefault(short_entry_id(entry_id), []).append((section["radfernweg"], sid))
    return found


# Teil einer Kante: `<Kantenschlüssel>@<von>-<bis>`, ganze Meter ab dem Anfang der Kante entlang ihrer Linie. Die App
# teilt eine Kante an virtuellen Knoten und, bei einer Detailnetzkante, dort, wo eine REN+-Kante auf ihr endet.
PART_KEY_PATTERN = re.compile(r"^(.+)@(\d+)-(\d+)$")
# Die App misst geodätisch auf WGS84, hier gilt EPSG:25833: eine Station nahe an einem Knoten liegt an ihm
PART_SNAP_M = 2.0


def split_part_key(key):
    """'detailnetz:X@265-390' -> ('detailnetz:X', 265, 390); ein Schlüssel ohne Teil -> (key, None, None)."""
    match = PART_KEY_PATTERN.match(key) if isinstance(key, str) else None
    if not match:
        return key, None, None
    return match.group(1), int(match.group(2)), int(match.group(3))


def detail_end_nodes(edge):
    """(Knoten am Anfang der Linie, Knoten am Ende) einer Detailnetzkante: beginnt_bei_vp/endet_bei_vp, sonst aus der element_nr."""
    start, end = (str(value) if has_text(value) else None
                  for value in (getattr(edge, "beginnt_bei_vp", None), getattr(edge, "endet_bei_vp", None)))
    match = ELEMENT_NR_PATTERN.match(edge.element_nr) if isinstance(edge.element_nr, str) else None
    if match:
        start, end = start or match.group(1), end or match.group(2)
    return start, end


def detail_cuts(ref, line, end_nodes, network, entries, app_nodes):
    """Wo eine Detailnetzkante Teile hat: [(Station in m, Knoten)] aus beiden Enden der Kante, den REN+-Kanten, die auf ihr
    enden (Knoten des Endes), und den virtuellen Knoten der App auf ihr (ihre Nummer). `app_nodes`: AppNodes, sonst gilt
    `nummer` des Eintrags."""
    cuts = [(0.0, end_nodes[0]), (line.length, end_nodes[1])]
    for position in network.sindex.query(line.buffer(PART_SNAP_M), predicate="intersects"):
        row = network.iloc[position]
        geometry = row.geometry
        lines = list(geometry.geoms) if isinstance(geometry, MultiLineString) else [geometry]
        if len(lines) != 1 or not isinstance(lines[0], LineString) or lines[0].is_empty:
            continue
        start_node = row.get("knoten_anfang") if has_text(row.get("knoten_anfang")) else node_text(row.get("von_knoten"))
        end_node = row.get("knoten_ende") if has_text(row.get("knoten_ende")) else node_text(row.get("bis_knoten"))
        for coordinate, node in ((lines[0].coords[0], start_node), (lines[0].coords[-1], end_node)):
            point = Point(coordinate)
            if node and line.distance(point) <= PART_SNAP_M:
                cuts.append((line.project(point), node))
    for entry in active_entries(entries, "virtual_node"):
        data = entry["data"]
        host = data.get("traeger") or {}
        if data.get("geloescht") or host.get("art") != "detailnetz" or host.get("ref") != ref:
            continue
        number = app_nodes.by_entry.get(entry["id"]) if app_nodes is not None else vk.pad_id(data.get("nummer"))
        if not number:
            continue
        station = host.get("station_m")
        if not isinstance(station, numbers.Number):
            station = line.project(Point(*_to_utm.transform(*data["lngLat"])))
        cuts.append((min(max(float(station), 0.0), line.length), number))
    return cuts


def detail_part(ref, von, bis, edge, network, entries, app_nodes):
    """Das Stück `von`-`bis` m einer Detailnetzkante, an Knoten eingerastet: ({ref, von_m, bis_m, von_knoten, bis_knoten}, None)
    oder (None, Grund). Die Grenzen werden auf die Länge der Linie begrenzt; eine Station rastet am nächsten Knoten
    innerhalb von PART_SNAP_M ein (REN+-Ende, virtueller Knoten, Kantenende)."""
    line = edge.geometry
    if isinstance(line, MultiLineString) and len(line.geoms) == 1:
        line = line.geoms[0]
    length = line.length
    low, high = max(0.0, min(float(von), length)), max(0.0, min(float(bis), length))
    if high <= low:
        return None, f"Bereich {von}–{bis} m ist leer (die Kante ist {length:.0f} m lang)"
    cuts = detail_cuts(ref, line, detail_end_nodes(edge), network, entries, app_nodes)
    snapped = []
    for station in (low, high):
        near = min(((abs(cut[0] - station), cut[0], cut[1]) for cut in cuts if cut[1]), default=None)
        if near is None or near[0] > PART_SNAP_M:
            return None, (f"bei {station:.0f} m liegt kein Knoten auf der Kante (weder REN+-Ende noch virtueller Knoten "
                          "mit Nummer): der Teil hat dort keine Grenze")
        snapped.append((near[1], near[2]))
    (low, start_node), (high, end_node) = snapped
    if high - low < SPLIT_END_TOLERANCE_M:
        return None, f"Bereich {von}–{bis} m ist nach dem Einrasten an die Knoten leer"
    return {"ref": ref, "von_m": low, "bis_m": high, "von_knoten": start_node, "bis_knoten": end_node, "line": line}, None


def apply_assignments(network, parts, entries, sections, detail_lines, app_nodes=None):
    """Spielt die section_assignment-Einträge auf das Netz ab (nach den Korrekturen).

    `parts`: Linien des Eingangsnetzes mit ihrem Schlüssel `ref` (Parts), `sections`: id -> Abschnitt aus
    Schritt 2 (oder None), `detail_lines`: Linien des Detailnetzes mit Spalte `ref` (oder None), `app_nodes`: AppNodes
    (für die Nummern der virtuellen Knoten auf Detailnetzkanten).
    Kanten `neu:<Eintrag>` (in der App gezeichnet) sammelt die Funktion in `drawn_routes` (kurze Eintrags-Id ->
    [(Route, Abschnitt-Id, Eintrags-Id der Zuordnung)]); add_drawn_edges trägt sie ein.

    Teile (`<Kante>@<von>-<bis>`):
    - `detailnetz:<ref>@a-b` nimmt nur das Stück der Detailnetzlinie als neue Zeile ins Netz (quelle detailnetz_manuell), mit der
      Route und mit eigener element_nr aus den Knoten an den Enden des Stücks (REN+-Ende, Nummer des virtuellen Knotens, Ende der
      Kante). REN+-Zeilen mit derselben element_nr bekommen die Route nicht. Dasselbe Stück aus mehreren Zuordnungen kommt einmal
      ins Netz, mit allen Routen.
    - `ren:<ref>@a-b` und `neu:<Eintrag>@a-b` gelten erst nach der Teilung an den virtuellen Knoten (die Kante wird noch geteilt):
      die Funktion gibt sie in `part_routes` zurück, apply_part_routes trägt die Route in die Teilkanten innerhalb von a-b ein.
    - Für die Umlegung nennt ein Teil seine ganze Kante: die automatische Route der Kante bleibt.
    Gibt (Netz, Konflikte, Zeilen für radfernweg_zuordnungen.csv, Zähler, drawn_routes, part_routes) zurück."""
    items = [entry for entry in active_entries(entries, "section_assignment") if not entry["data"].get("geloescht")]
    conflicts, report = [], []
    stats = {"abschnitte": len(items), "zugeordnet": 0, "keine_aktion": 0, "konflikte": 0, "aufgenommen": 0, "aufgenommene_teile": 0,
             "umgelegt": 0}
    drawn_routes = {}
    part_routes = []
    if not items:
        return network, conflicts, report, stats, drawn_routes, part_routes

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
            base, von, bis = split_part_key(key)
            kind, _, ref = base.partition(":")
            if von is not None:
                # Teil einer Kante: eine fehlende Kante oder ein leerer Bereich ist ein Konflikt, der Eintrag gilt nicht
                if kind == "ren" and ref in parts.by_ref:
                    item = parts.by_ref[ref]
                    label = network.index[item["row"]]
                    geometry = network.geometry.loc[label]
                    lines = list(geometry.geoms) if isinstance(geometry, MultiLineString) else [geometry]
                    length = lines[item["part"]].length
                    if min(float(bis), length) <= float(von):
                        problem = f"Teil {key}: Bereich {von}–{bis} m ist leer (die Kante ist {length:.0f} m lang)"
                        break
                    targets.append(("rowpart", {"label": label, "part": item["part"], "von": von, "bis": bis}, key))
                elif kind == "neu" and ref:
                    if bis <= von:
                        problem = f"Teil {key}: Bereich {von}–{bis} m ist leer"
                        break
                    targets.append(("drawnpart", {"ref": short_entry_id(ref), "von": von, "bis": bis}, key))
                elif kind == "detailnetz" and ref in detail_by_ref:
                    spec, reason = detail_part(ref, von, bis, detail_by_ref[ref], network, entries, app_nodes)
                    if spec is None:
                        problem = f"Teil {key}: {reason}"
                        break
                    targets.append(("detailpart", spec, key))
                else:
                    problem = f"Teil {key}: Kante {base} nicht im Netz"
                    break
            elif kind == "ren" and ref in parts.by_ref:
                targets.append(("row", network.index[parts.by_ref[ref]["row"]], key))
            elif kind == "neu" and ref:
                targets.append(("drawn", short_entry_id(ref), key))
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
        # Ein Teil nennt seine ganze Kante: wer `<Kante>@a-b` wählt, legt die Route nicht von `<Kante>` weg
        named = {split_part_key(key)[0] for key in data["kanten"]}
        for key in sections[data["abschnitt"]["id"]]["kanten"]:
            if key in named or (route, key) in still_used:
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
                    add_change(network, index, f"Radfernweg {route} entfernt: in der App auf andere Kanten umgelegt "
                                               f"(Abschnitt {data['abschnitt']['id']})")

    # Zuordnen
    new_edges = {}  # detailnetz-ref -> (routen, Einträge)
    new_pieces = {}  # (ref, von_m, bis_m) -> {spec, routes, ids}
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
                add_change(network, target, f"Radfernweg {route} von Hand zugeordnet (Abschnitt {data['abschnitt']['id']})")
                dropped.discard(target)
            elif kind == "drawn":
                drawn_routes.setdefault(target, []).append((route, data["abschnitt"]["id"], entry["id"]))
                notes.append(f"{key} (neu gezeichnete Kante)")
            elif kind in ("rowpart", "drawnpart"):
                part_routes.append({"kind": "ren" if kind == "rowpart" else "neu", **target, "route": route, "key": key,
                                    "abschnitt": data["abschnitt"]["id"], "eintrag_id": entry["id"]})
                notes.append(f"{key} (Teil der Kante, nach der Teilung an virtuellen Knoten)")
            elif kind == "detailpart":
                piece = new_pieces.setdefault((target["ref"], round(target["von_m"], 2), round(target["bis_m"], 2)),
                                              {"spec": target, "routes": set(), "ids": []})
                piece["routes"].add(route)
                piece["ids"].append(entry["id"])
                notes.append(f"{key} ins Netz aufgenommen")
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
        for index in sorted(dropped):
            if int(network.at[index, "anzahl_vorgaenge"]) > 0:
                # The edge carried a correction from the app: it goes with the route, but not silently
                conflicts.append({"grund": "Kante fällt durch die Umlegung weg (nur für den Radfernweg aufgenommen); "
                                           "ihre Korrektur entfällt mit ihr",
                                  "art": "edge_correction", "eintrag_id": network.at[index, "eintrag_ids"], "ref": None,
                                  "element_nr": network.at[index, "element_nr"], "abweichung_m": None,
                                  "bearbeitet_von": network.at[index, "letzte_aenderung_von"],
                                  "bearbeitet_am": network.at[index, "letzte_aenderung_am"]})
                stats["konflikte"] += 1
        network = network.drop(index=sorted(dropped))
    if new_edges or new_pieces:
        refs = sorted(new_edges)
        piece_keys = sorted(new_pieces)
        records = [detail_by_ref[ref]._asdict() for ref in refs]
        routes = [routes_text(new_edges[ref][0]) for ref in refs]
        counts = element_nr_counts(list(network["element_nr"]) + (list(detail_lines["element_nr"]) if detail_lines is not None else []))
        piece_numbers = []
        for key in piece_keys:
            spec = new_pieces[key]["spec"]
            # Die element_nr des Stücks aus den Knoten an seinen Enden, wie bei anderen Kanten `<von>_<bis>.<nn>`
            pair = pair_key(spec["von_knoten"], spec["bis_knoten"])
            counts[pair] = counts.get(pair, 0) + 1
            element_nr = f"{spec['von_knoten']}_{spec['bis_knoten']}.{counts[pair]:02d}"
            piece_numbers.append(element_nr)
            record = detail_by_ref[spec["ref"]]._asdict()
            record.update({"element_nr": element_nr, "geometry": shapely.ops.substring(spec["line"], spec["von_m"], spec["bis_m"])})
            records.append(record)
            routes.append(routes_text(new_pieces[key]["routes"]))
        edges = gpd.GeoDataFrame(pd.DataFrame(records), geometry="geometry", crs=CRS)
        first_new = len(network)
        network = append_detail_rows(network, edges, "detailnetz_manuell", "radfernweg_manuell", routes, "manuell")
        if "aenderung" not in network.columns:
            network["aenderung"] = None
        if "ursprung_element_nr" not in network.columns:
            network["ursprung_element_nr"] = None
        for offset, ref in enumerate(refs):
            for entry_id in new_edges[ref][1]:
                add_entry_id(network, network.index[first_new + offset], entry_id)
            add_change(network, network.index[first_new + offset],
                       f"Detailnetzkante für Radfernweg {routes_text(new_edges[ref][0])} von Hand ins Netz aufgenommen")
        for offset, key in enumerate(piece_keys):
            index = network.index[first_new + len(refs) + offset]
            spec = new_pieces[key]["spec"]
            for entry_id in dict.fromkeys(new_pieces[key]["ids"]):
                add_entry_id(network, index, entry_id)
            parent = detail_by_ref[spec["ref"]].element_nr
            network.at[index, "ursprung_element_nr"] = parent
            add_change(network, index, f"Stück {spec['von_m']:.0f}–{spec['bis_m']:.0f} m der Detailnetzkante {parent}, für Radfernweg "
                                       f"{routes_text(new_pieces[key]['routes'])} von Hand ins Netz aufgenommen")
        stats["aufgenommen"] = len(refs)
        stats["aufgenommene_teile"] = len(piece_keys)
    return network, conflicts, report, stats, drawn_routes, part_routes


def apply_part_routes(network, part_routes, pieces, drawn_labels):
    """Trägt die Routen der Teile `ren:<ref>@a-b` und `neu:<Eintrag>@a-b` ein (nach der Teilung an den virtuellen Knoten).

    `pieces`: Indexmarke der geteilten Kante -> [(Indexmarke der Teilkante, von_m, bis_m)] (split_at_virtual_nodes), eine
    ungeteilte Kante ist ein Teil von 0 bis zu ihrer Länge. `drawn_labels`: Indexmarke je gezeichneter Kante (add_drawn_edges).
    Die Route bekommen die Teilkanten, die ganz in a-b liegen (Spielraum PART_SNAP_M, mindestens 1 % der Länge: die App misst
    geodätisch, auf einer korrigierten Linie verschieben sich die Stationen); gibt es keine, ist das ein Konflikt.
    Gibt (Netz, Konflikte) zurück."""
    conflicts = []
    by_short = {short_entry_id(entry_id): label for entry_id, label in drawn_labels.items()}
    for item in part_routes:
        label = by_short.get(item["ref"]) if item["kind"] == "neu" else item["label"]
        problem = None
        if label is None or (label not in pieces and label not in network.index):
            problem = f"Teil {item['key']}: die Kante gibt es nicht (mehr)"
        else:
            children = pieces.get(label)
            if children is None:
                geometry = network.geometry.loc[label]
                lines = list(geometry.geoms) if isinstance(geometry, MultiLineString) else [geometry]
                children = [(label, 0.0, lines[min(item.get("part", 0), len(lines) - 1)].length)]
            length = max(high for _, _, high in children)
            tolerance = max(PART_SNAP_M, 0.01 * length)
            targets = [child for child, low, high in children
                       if low >= item["von"] - tolerance and high <= item["bis"] + tolerance]
            if not targets:
                problem = (f"Teil {item['key']}: keine Teilkante liegt ganz zwischen {item['von']} und {item['bis']} m "
                           "(die Kante ist dort nicht an einem virtuellen Knoten geteilt)")
        if problem:
            conflicts.append({"grund": problem, "art": "section_assignment", "eintrag_id": item["eintrag_id"],
                              "ref": item["abschnitt"], "element_nr": None, "abweichung_m": None,
                              "bearbeitet_von": None, "bearbeitet_am": None})
            continue
        for target in targets:
            names = split_routes(network.at[target, "routen_fernradweg"])
            if item["route"] not in names:
                previous = network.at[target, "routen_quelle"]
                network.at[target, "routen_fernradweg"] = routes_text(names + [item["route"]])
                network.at[target, "routen_quelle"] = {None: "manuell", "auto": "auto; manuell"}.get(
                    previous if isinstance(previous, str) else None, previous)
            add_entry_id(network, target, item["eintrag_id"])
            add_change(network, target, f"Radfernweg {item['route']} von Hand zugeordnet (Abschnitt {item['abschnitt']}, "
                                        f"Teil {item['von']}–{item['bis']} m der Kante)")
    return network, conflicts


def node_text(value):
    """Knoten-IDs als Text: virtuelle IDs beginnen mit V, die übrigen sind Zahlen (von_knoten ist im Netz Integer)."""
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    return str(int(value)) if isinstance(value, numbers.Number) else str(value)


def add_drawn_edges(network, original_geometry, new_edges, entries, extra_routes=None, auto_routes=None):
    """Hängt die in der App gezeichneten Kanten (new_edges aus new_edge_frame) als Zeilen an das Netz.

    quelle = neu_gezeichnet, routen_fernradweg aus dem Eintrag (routen_quelle = manuell), element_nr wie in der
    App. Dazu kommen Routen aus Zuordnungen in der App (`extra_routes`, siehe apply_assignments) und Routen von
    Lücken-Abschnitten, an deren Mitte die Kante vorbeiführt (`auto_routes`, siehe drawn_section_routes), z. B. eine
    zweite Route auf derselben Kante. Gibt (Netz, Originallage, Indexmarke je entry_id) zurück; die Lage ist die
    gezeichnete, in beiden Netzen."""
    if len(new_edges) == 0:
        return network, original_geometry, {}
    data_by_id = {entry["id"]: entry["data"] for entry in entries}
    rows = []
    for edge in new_edges.itertuples():
        data = data_by_id[edge.entry_id]
        short = short_entry_id(edge.entry_id)
        names = split_routes(data.get("routen_fernradweg"))
        changes = [f"In der App neu gezeichnet ({'für den Radfernweg ' + routes_text(names) if names else data.get('quelle') or 'gezeichnet'})"]
        entry_ids = [edge.entry_id]
        for route, sid, assignment_id in (extra_routes or {}).get(short, []):
            if route not in names:
                names.append(route)
            changes.append(f"Radfernweg {route} von Hand zugeordnet (Abschnitt {sid})")
            entry_ids.append(assignment_id)
        for route, sid in (auto_routes or {}).get(short, []):
            if route not in names:
                names.append(route)
                changes.append(f"Radfernweg {route} liegt auch auf dieser Kante (Abschnitt {sid})")
        routes = routes_text(names) if names else None
        rows.append({
            "element_nr": edge.element_nr, "element_nr_berechnet": "nein", "von_knoten": edge.von_knoten,
            "bis_knoten": edge.bis_knoten, "strassenname": edge.strassenname, "radverkehrsnetz": ren.RVN_KEIN,
            "hauptverkehrsstrasse": "nein", "netz_quellen": "netzanpassungen", "in_detailnetz": "nein",
            "bearbeitet_2025": "nein", "anteil_2025": 0.0, "quelle": "neu_gezeichnet",
            "grund_aufnahme": "radfernweg_manuell" if data.get("quelle") == "radfernweg" else None,
            "routen_fernradweg": routes, "routen_quelle": "manuell" if routes else None,
            "verkehrsrichtung": edge.verkehrsrichtung, "verkehrsrichtung_original": edge.verkehrsrichtung,
            "eintrag_ids": "; ".join(dict.fromkeys(entry_ids)),
            "aenderung": "; ".join(changes),
            "geometry": MultiLineString([edge.geometry]),
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


def bridge_conflict(entry, reason, ref=None, element_nr=None):
    return {"grund": reason, "art": "bridge_check", "eintrag_id": entry.get("id"), "ref": ref, "element_nr": element_nr,
            "abweichung_m": None, "bearbeitet_von": entry.get("updated_by"), "bearbeitet_am": entry.get("updated_at")}


def apply_bridge_checks(network, entries, parts, labels_of_ref, app_nodes, node_positions, known_ids):
    """Prüfung „Brücken und Tunnel“ (bridge_check): `getrennt` gibt den Kantenenden der unteren Ebene einen eigenen Knoten.

    Jede REN+-Kante in `unten` (`ren:<ref>`), deren Ende am Knoten liegt, bekommt dort den Knoten `<Knoten>-unten` (an
    derselben Stelle; von_knoten, bis_knoten, knoten_anfang, knoten_ende, wo sie den Knoten nennen; die element_nr bleibt).
    Alle Kanten am Knoten bekommen `bauwerk` (Name) und `bauwerk_lage` (`oben` | `unten`). `ok` ändert nichts, ein gelöschter
    Eintrag zählt nicht. Eine Kante, die es nicht mehr gibt oder die nicht mehr am Knoten endet, und ein Knoten, den es nicht
    gibt, sind Konflikte; die Kante wird dann übersprungen. Das Netz ist am Ende von Schritt 3 (nach Teilung und
    Übernahme der Vorschläge): eine geteilte Kante findet man über `ursprung_element_nr`.
    `node_positions`: Knoten-ID -> Punkt (Detailnetz, virtuelle Knoten, Vorschläge). Gibt (Netz, neue Knoten, Konflikte,
    Zähler) zurück; neue Knoten: Zeilen mit id, ursprung_knoten, bauwerk, art, eintrag_id und geometry."""
    network = network.copy()
    new_nodes, conflicts = [], []
    stats = {"ok": 0, "getrennt": 0, "getrennte_kanten": 0, "konflikte": 0}
    checks = [entry for entry in active_entries(entries, "bridge_check") if not entry["data"].get("geloescht")]
    if not checks:
        return network, new_nodes, conflicts, stats
    columns = [column for column in NODE_COLUMNS if column in network.columns]
    by_node = defaultdict(set)  # node -> labels of the edges that name it at one of their ends
    for label, values in zip(network.index, zip(*(network[column].map(node_text) for column in columns))):
        for value in values:
            if has_text(value):
                by_node[value].add(label)
    for entry in sorted(checks, key=lambda item: item.get("created_at") or ""):
        data = entry["data"]
        if data.get("ergebnis") != "getrennt":
            stats["ok"] += 1
            continue
        stats["getrennt"] += 1
        structure = data.get("bauwerk") or {}
        name = structure.get("name") or ""
        found = []

        def report(reason, ref=None, element_nr=None):
            found.append(bridge_conflict(entry, reason, ref, element_nr))

        node = app_nodes.node_of_key(data.get("knoten") or "", known_ids)
        node = app_nodes.accepted.get(node, node)
        point = node_positions.get(node) if node else None
        if point is None:
            report(f"Brücken und Tunnel: Knoten {data.get('knoten')} gibt es nicht (mehr), die Ebenen sind dort nicht getrennt "
                   f"({name})", ref=data.get("knoten"))
            conflicts += found
            continue
        at_node = sorted(by_node.get(node, ()))
        lower = {}  # label -> the keys of `unten` that name it
        for key in data.get("unten") or []:
            kind, _, ref = key.partition(":")
            if kind != "ren":
                continue  # Detailnetz edges are no REN+ edges: nothing to change
            item = parts.by_ref.get(ref)
            if item is None:
                report(f"Brücken und Tunnel: Kante {key} unten am Knoten {node} gibt es nicht mehr ({name})", ref=ref)
                continue
            label = labels_of_ref[ref]
            candidates = [label] if label in network.index else [
                other for other in network.index if network.at[other, "ursprung_element_nr"] == item["element_nr"]]
            ending = [other for other in candidates if other in at_node]
            if not ending:
                report(f"Brücken und Tunnel: Kante {key} unten endet nicht mehr am Knoten {node} ({name})",
                       ref=ref, element_nr=item["element_nr"])
                continue
            for other in ending:
                lower.setdefault(other, []).append(key)
        conflicts += found
        stats["konflikte"] += len(found)
        if not lower:
            continue
        new_node = f"{node}{LOWER_NODE_SUFFIX}"
        for label in at_node:
            network.at[label, "bauwerk"] = name
            network.at[label, "bauwerk_lage"] = "unten" if label in lower else "oben"
            add_entry_id(network, label, entry["id"])
        for label in lower:
            for column in columns:
                if node_text(network.at[label, column]) == node:
                    network.at[label, column] = new_node
            by_node[node].discard(label)
            by_node[new_node].add(label)
            add_change(network, label, f"Am Bauwerk {name} ({structure.get('art')}) vom Knoten {node} getrennt: "
                                       f"Ende an der unteren Ebene, neuer Knoten {new_node}")
            stats["getrennte_kanten"] += 1
        for label in at_node:
            if label not in lower:
                add_change(network, label, f"Am Bauwerk {name} ({structure.get('art')}): obere Ebene am Knoten {node}, "
                                           f"untere Ebene getrennt (Knoten {new_node})")
        new_nodes.append({"id": new_node, "ursprung_knoten": node, "bauwerk": name, "art": structure.get("art"),
                          "eintrag_id": entry["id"], "geometry": point})
    return network, new_nodes, conflicts, stats


def write_bridge_nodes(path, new_nodes):
    """bauwerk_knoten.gpkg: the new nodes of the lower level; without any, an old file is removed."""
    path = Path(path)
    if not new_nodes:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = gpd.GeoDataFrame(new_nodes, geometry="geometry", crs=CRS)
    path.unlink(missing_ok=True)
    frame.to_file(path, layer=BRIDGE_NODES_LAYER, driver="GPKG")


def ren_end_cuts(network, excluded_labels):
    """T-junctions inside the REN+ network: {Indexmarke der durchgehenden Kante: [(Station, Knoten-ID, Punkt)]}.

    Die App teilt eine REN+-Kante dort in Teile, wo das Ende einer anderen REN+-Kante auf ihr liegt (näher als
    REN_END_ON_EDGE_M an ihrem Inneren, weiter als REN_CUT_MIN_M von ihren Enden): die Quelle hat solche T-Kreuzungen, an denen
    die durchgehende Kante nicht geteilt ist. Enden zählen mit ihrem Knoten (knoten_anfang/knoten_ende, sonst von_knoten/
    bis_knoten); ein Ende ohne Knoten oder von einer Kante mit mehreren Linien zählt nicht. `excluded_labels`: gezeichnete
    und von Hand aufgenommene Kanten, die in der App keine REN+-Kanten sind. Mehrere Enden am selben Punkt ergeben einen Schnitt
    (die späteren liegen innerhalb von REN_CUT_MIN_M)."""
    rows = [(label, row) for label, row in network.iterrows() if label not in excluded_labels
            and row.geometry is not None and len(row.geometry.geoms) == 1]
    ends = []  # (Punkt, Knoten-ID)
    for label, row in rows:
        coordinates = list(row.geometry.geoms[0].coords)
        for point, column, fallback in ((coordinates[0], "knoten_anfang", "von_knoten"),
                                        (coordinates[-1], "knoten_ende", "bis_knoten")):
            node = node_text(row.get(column)) if has_text(row.get(column)) else node_text(row.get(fallback))
            if has_text(node):
                ends.append((Point(point), node))
    if not ends:
        return {}
    tree = shapely.STRtree([point for point, _ in ends])
    cuts = {}
    for label, row in rows:
        line = row.geometry.geoms[0]
        if line.length <= 2 * REN_CUT_MIN_M:
            continue
        for position in tree.query(line, predicate="dwithin", distance=REN_END_ON_EDGE_M):
            point, node = ends[position]
            station = line.project(point)
            if REN_CUT_MIN_M < station < line.length - REN_CUT_MIN_M:
                cuts.setdefault(label, []).append((station, node, point))
    return cuts


def split_at_virtual_nodes(network, original_geometry, labels_of_ref, drawn_labels, entries, base_element_nrs,
                           accepted_ids=None, numbers=None):
    """Teilt REN+-Kanten und gezeichnete Kanten an den virtuellen Knoten des Exports (wie splitEdges in der App,
    netzanpassungen/src/network/element-nr.ts im Repo knotenpunkte).

    Jede Teilkante bekommt eine neue element_nr `<von>_<bis>.<nn>` (nn zählt je Knotenpaar nach den vorhandenen
    Kanten, zuerst die Teile gezeichneter Kanten) und `ursprung_element_nr`; die Ursprungszeile entfällt. Die
    Station kommt aus der Lage des Knotens (Projektion auf die Trägerkante, bei Lagekorrekturen auf die korrigierte
    Linie, wo die App den Knoten mitgeführt hat); ein Knoten mehr als 1 m neben der Kante teilt sie nicht. Im Kundennetz (Originallage) liegt die
    Teilung an der Projektion des Knotens auf die Originallinie (beim selben Anteil der Kantenlänge, wenn die Projektionen nicht in Reihenfolge liegen). Der freie Endknoten einer gezeichneten Kante teilt sie nicht.
    Dazu teilt ein REN+-Ende, das im Inneren einer anderen REN+-Kante liegt (T-Kreuzung der Quelle, ren_end_cuts), diese Kante
    an seinem vorhandenen Knoten, ohne neuen Knoten; Schnitte näher als 2 m an einem Kantenende oder an einem anderen Schnitt entfallen.
    Nicht geteilt wird eine Trägerkante ohne Knotennamen oder mit mehreren Linien (steht in den Konflikten).
    `labels_of_ref`: Indexmarke und Linie je Schlüssel `ref` des Eingangsnetzes.
    Gibt (Netz, Originallage, Konflikte, Zähler, Teile) zurück; `Teile`: Indexmarke der geteilten Kante ->
    [(Indexmarke der Teilkante, von_m, bis_m)] mit den Stationen auf der (korrigierten) Linie, für apply_part_routes."""
    nodes = [entry for entry in active_entries(entries, "virtual_node") if not entry["data"].get("geloescht")
             and (accepted_ids is None or entry["id"] in accepted_ids)]
    drawn_data = {entry["id"]: entry["data"] for entry in active_entries(entries, "new_edge")}
    drawn_data.update({short_id(entry_id): data for entry_id, data in list(drawn_data.items())})
    drawn_labels = {**drawn_labels, **{short_id(entry_id): label for entry_id, label in drawn_labels.items()}}
    conflicts, stats = [], {"geteilte_kanten": 0, "teilkanten": 0, "traeger_ohne_netz": 0, "knoten_neben_traeger": 0,
                            "schnitte_an_ren_enden": 0}
    hosts = {}  # Indexmarke -> [(Knoteneintrag)], in der Reihenfolge des Exports
    for entry in nodes:
        data = entry["data"]
        host = data.get("traeger") or {}
        if host.get("art") == "ren" and host.get("ref") in labels_of_ref and labels_of_ref[host["ref"]][0] in network.index:
            label = labels_of_ref[host["ref"]][0]
        elif host.get("art") == "neu" and host.get("ref") in drawn_labels:
            label = drawn_labels[host["ref"]]
            edge = drawn_data[host["ref"]]
            if {f"v:{entry['id']}", f"v:{short_id(entry['id'])}"} & {edge["von"], edge["bis"]}:
                continue  # freier Endknoten der gezeichneten Kante: teilt sie nicht
        else:
            stats["traeger_ohne_netz"] += 1
            continue
        hosts.setdefault(label, []).append(entry)

    drawn_label_set = set(drawn_labels.values())
    # T-junctions of the REN+ network: a REN+ edge that ends on the interior of another one cuts it at that node
    manual = set(network.index[network["quelle"] == "detailnetz_manuell"]) if "quelle" in network.columns else set()
    t_cuts = ren_end_cuts(network, drawn_label_set | manual)
    # Zuerst die gezeichneten Kanten, damit ihre Teile wie die Kanten selbst nummeriert werden
    order = sorted(set(hosts) | set(t_cuts), key=lambda label: label not in drawn_label_set)
    counts = element_nr_counts(list(base_element_nrs) + [network.at[label, "element_nr"] for label in drawn_label_set])
    network = network.copy()
    network["von_knoten"] = network["von_knoten"].map(node_text)
    network["bis_knoten"] = network["bis_knoten"].map(node_text)
    names = {entry["id"]: (numbers or {}).get(entry["id"]) or entry["data"].get("nummer") or entry["data"]["name"]
             for entry in nodes}
    next_label = int(network.index.max()) + 1
    next_lfd = int(network["lfd_nr"].max()) + 1
    pieces, piece_geometry, dropped = [], [], []
    ranges = {}
    for label in order:
        row = network.loc[label]
        line_parts = list(row.geometry.geoms)
        old_parts = list(original_geometry.loc[label].geoms)
        if len(line_parts) != 1:
            conflicts.append({"grund": f"Trägerkante {row['element_nr']} hat {len(line_parts)} Linien: nicht an virtuellen Knoten geteilt",
                              "art": "virtual_node", "eintrag_id": hosts[label][0]["id"], "ref": None, "element_nr": row["element_nr"],
                              "abweichung_m": None, "bearbeitet_von": None, "bearbeitet_am": None})
            continue
        # The nodes at the geometric ends: knoten_anfang/knoten_ende where step 1 set them (the app saw these as from/to),
        # otherwise von_knoten/bis_knoten
        start_node = row.get("knoten_anfang") if has_text(row.get("knoten_anfang")) else row["von_knoten"]
        end_node = row.get("knoten_ende") if has_text(row.get("knoten_ende")) else row["bis_knoten"]
        if not has_text(start_node) or not has_text(end_node):
            if label not in hosts:
                continue
            conflicts.append({"grund": f"Trägerkante {row['element_nr']} ohne Knoten: nicht an virtuellen Knoten geteilt",
                              "art": "virtual_node", "eintrag_id": hosts[label][0]["id"], "ref": None, "element_nr": row["element_nr"],
                              "abweichung_m": None, "bearbeitet_von": None, "bearbeitet_am": None})
            continue
        line, old_line = line_parts[0], old_parts[0]
        stops = []
        for entry in hosts.get(label, []):
            data = entry["data"]
            point = Point(*_to_utm.transform(*data["lngLat"]))
            if line.distance(point) > NODE_ON_EDGE_TOLERANCE_M:
                stats["knoten_neben_traeger"] += 1  # steht schon als Hinweis in den Konflikten (check_nodes_on_edges)
                continue
            station = line.project(point)
            if SPLIT_END_TOLERANCE_M < station < line.length - SPLIT_END_TOLERANCE_M:
                stops.append((station, entry))
        stops.sort(key=lambda item: item[0])
        # Two nodes closer than SPLIT_END_TOLERANCE_M on one edge would leave a near-zero piece: the first one splits,
        # the later one is reported
        spaced = stops[:1]
        for station, entry in stops[1:]:
            if station - spaced[-1][0] < SPLIT_END_TOLERANCE_M:
                conflicts.append({"grund": f"Virtueller Knoten {names[entry['id']]} liegt weniger als {SPLIT_END_TOLERANCE_M} m von "
                                           f"{names[spaced[-1][1]['id']]} auf {row['element_nr']}: teilt die Kante nicht",
                                  "art": "virtual_node", "eintrag_id": entry["id"], "ref": None, "element_nr": row["element_nr"],
                                  "abweichung_m": None, "bearbeitet_von": entry.get("updated_by"), "bearbeitet_am": entry.get("updated_at")})
            else:
                spaced.append((station, entry))
        # A REN+ end on the interior of the edge cuts it at its existing node. It is dropped within REN_CUT_MIN_M of an end
        # (done in ren_end_cuts), of a virtual node or of an earlier end (the app drops the later cut as well)
        ren_stops = []
        for station, node, point in sorted(t_cuts.get(label, []), key=lambda item: item[0]):
            taken = [item[0] for item in spaced] + [item[0] for item in ren_stops]
            if all(abs(station - other) > REN_CUT_MIN_M for other in taken):
                ren_stops.append((station, {"id": None, "ren_node": node, "point": point}))
        stops = sorted(spaced + ren_stops, key=lambda item: item[0])
        if not stops:
            continue
        stats["schnitte_an_ren_enden"] += len(ren_stops)
        node_name = lambda e: e["ren_node"] if e["id"] is None else names[e["id"]]
        node_point = lambda e: e["point"] if e["id"] is None else Point(*_to_utm.transform(*e["data"]["lngLat"]))
        scale = old_line.length / line.length if line.length else 1.0
        chain = [(0.0, start_node, None)] + [(st, node_name(e), e) for st, e in stops] + [(line.length, end_node, None)]
        # Where the nodes lie on the original line (customer network): their projection onto it, so a corrected
        # edge is cut at the same spot in both networks. Falls back to the same length share when the projections
        # are not in order (a heavily changed line).
        old_chain = [0.0] + [old_line.project(node_point(e)) for _, e in stops] + \
            [old_line.length]
        if not all(a < b for a, b in zip(old_chain, old_chain[1:])):
            old_chain = [station * scale for station, _, _ in chain]
        dropped.append(label)
        stats["geteilte_kanten"] += 1
        first_piece = len(pieces)
        ranges[label] = []
        for (low, start, start_entry), (high, end, end_entry), old_low, old_high in zip(
                chain[:-1], chain[1:], old_chain[:-1], old_chain[1:]):
            key = pair_key(start, end)
            counts[key] = counts.get(key, 0) + 1
            element_nr = f"{start}_{end}.{counts[key]:02d}"
            piece = row.drop(labels=["geometry"]).to_dict()
            piece.update({"element_nr": element_nr, "von_knoten": start, "bis_knoten": end, "knoten_anfang": None, "knoten_ende": None,
                          "ursprung_element_nr": row["element_nr"], "lfd_nr": next_lfd, "eintrag_ids": row["eintrag_ids"]})
            next_lfd += 1
            for entry in (start_entry, end_entry):
                if entry is not None and entry["id"] is not None:
                    ids = piece["eintrag_ids"].split("; ") if isinstance(piece["eintrag_ids"], str) and piece["eintrag_ids"] else []
                    if entry["id"] not in ids:
                        piece["eintrag_ids"] = "; ".join(ids + [entry["id"]])
            split_at = [name for name, entry in ((start, start_entry), (end, end_entry)) if entry is not None and entry["id"] is not None]
            split_at_ren = [name for name, entry in ((start, start_entry), (end, end_entry)) if entry is not None and entry["id"] is None]
            sentences = piece["aenderung"].split("; ") if isinstance(piece.get("aenderung"), str) and piece["aenderung"] else []
            where = [f"am virtuellen Knoten {' und '.join(split_at)}"] if split_at else []
            if split_at_ren:
                where.append(f"am Knoten {' und '.join(split_at_ren)}, an dem eine andere REN+-Kante endet")
            sentence = (f"Kante {row['element_nr']} {' und '.join(where)} geteilt "
                        f"(Teil {len(pieces) + 1 - first_piece} von {len(chain) - 1})")
            piece["aenderung"] = "; ".join(sentences + [sentence])
            pieces.append((next_label, piece))
            ranges[label].append((next_label, low, high))
            piece_geometry.append((next_label, MultiLineString([shapely.ops.substring(line, low, high)]),
                                   MultiLineString([shapely.ops.substring(old_line, old_low, old_high)])))
            next_label += 1
            stats["teilkanten"] += 1

    if not pieces:
        return network, original_geometry, conflicts, stats, ranges
    added = gpd.GeoDataFrame([piece for _, piece in pieces], index=[label for label, _ in pieces],
                             geometry=[geometry for _, geometry, _ in piece_geometry], crs=CRS)
    added["laenge_m"] = added.geometry.length.round(1)
    network = gpd.GeoDataFrame(pd.concat([network.drop(index=dropped), added[list(network.columns)]]), geometry="geometry", crs=CRS)
    old_added = gpd.GeoSeries([old for _, _, old in piece_geometry], index=[label for label, _, _ in piece_geometry], crs=CRS)
    original_geometry = pd.concat([original_geometry.drop(index=dropped), old_added])
    return network, original_geometry, conflicts, stats, ranges


def apply_accepted_proposals(network, accepted, base_element_nrs):
    """Replaces the proposal ids of step 1 that the app accepted by their numbers in von_knoten, bis_knoten,
    knoten_anfang, knoten_ende and element_nr. Where the element_nr changes, the one of the input stays in
    element_nr_eingabe. A renamed element_nr that is taken already gets the next free nn of its node pair."""
    network = network.copy()
    if "element_nr_eingabe" not in network.columns:
        network["element_nr_eingabe"] = None
    if not accepted:
        return network, 0
    for column in ("von_knoten", "bis_knoten", "knoten_anfang", "knoten_ende"):
        if column in network.columns:
            network[column] = network[column].map(lambda value: accepted.get(value, value) if isinstance(value, str) else value)
    used = set(network["element_nr"].dropna()) | {nr for nr in base_element_nrs if isinstance(nr, str)}
    counts = element_nr_counts(used)
    changed = 0
    for label in network.index:
        element_nr = network.at[label, "element_nr"]
        match = ELEMENT_NR_PATTERN.match(element_nr) if isinstance(element_nr, str) else None
        if not match or (match.group(1) not in accepted and match.group(2) not in accepted):
            continue
        von, bis = accepted.get(match.group(1), match.group(1)), accepted.get(match.group(2), match.group(2))
        new = f"{von}_{bis}.{match.group(3)}"
        if new in used:
            key = pair_key(von, bis)
            counts[key] = counts.get(key, 0) + 1
            new = f"{von}_{bis}.{counts[key]:02d}"
        else:
            key = pair_key(von, bis)
            counts[key] = max(counts.get(key, 0), int(match.group(3)))
        used.add(new)
        network.at[label, "element_nr_eingabe"] = element_nr
        network.at[label, "element_nr"] = new
        if "aenderung" in network.columns:
            renamed = [f"{proposal} als {accepted[proposal]}" for proposal in (match.group(1), match.group(2)) if proposal in accepted]
            add_change(network, label, f"Knotenvorschlag {' und '.join(renamed)} in der App übernommen "
                                       f"(element_nr bisher {element_nr})")
        changed += 1
    return network, changed


def _line_parts(geometry):
    return list(geometry.geoms) if geometry.geom_type == "MultiLineString" else [geometry]


def _end_nodes(row, geometry):
    """(start node, end node) an edge names at its geometric ends: knoten_anfang/knoten_ende where set, else
    von_knoten/bis_knoten (in the order that fits the geometry better is decided by the caller)."""
    start = node_text(row.get("knoten_anfang")) if has_text(node_text(row.get("knoten_anfang"))) else node_text(row.get("von_knoten"))
    end = node_text(row.get("knoten_ende")) if has_text(node_text(row.get("knoten_ende"))) else node_text(row.get("bis_knoten"))
    return start, end


def _move_end(geometry, side, point):
    parts = _line_parts(geometry)
    index = 0 if side == 0 else len(parts) - 1
    parts[index] = end_at(parts[index], side, point, max_cut_m=NODE_END_SNAP_M)
    return MultiLineString(parts) if geometry.geom_type == "MultiLineString" else parts[0]


def snap_ends_to_virtual_nodes(network, original_geometry, node_points):
    """Every edge end that names a virtual node (`node_points`: id -> Point) and lies at most NODE_END_SNAP_M from it is
    moved exactly onto it, in the corrected and in the original geometry. Where all edge ends naming a node lie farther
    away but together (within NODE_MEETING_SPREAD_M), the node may be in the wrong place: nothing moves, a conflict.
    Official nodes in `node_points` count the same. Returns (network, original_geometry, number of ends moved,
    conflicts)."""
    network = network.copy()
    original_geometry = original_geometry.copy()
    moved, far = 0, defaultdict(list)  # node -> [(label, end point)]
    naming = defaultdict(list)
    for label, row in network.iterrows():
        nodes = _end_nodes(row, row.geometry)
        for series, record in ((network.geometry, True), (original_geometry, False)):
            geometry = series.loc[label]
            if geometry is None or geometry.is_empty:
                continue
            parts = _line_parts(geometry)
            ends = (Point(parts[0].coords[0]), Point(parts[-1].coords[-1]))
            a, b = nodes
            pa, pb = node_points.get(a), node_points.get(b)
            if pa is None and pb is None:
                continue
            straight = (ends[0].distance(pa) if pa else 0) + (ends[1].distance(pb) if pb else 0)
            swapped = (ends[1].distance(pa) if pa else 0) + (ends[0].distance(pb) if pb else 0)
            pairs = ((0, a), (1, b)) if straight <= swapped else ((1, a), (0, b))
            for side, node in pairs:
                point = node_points.get(node)
                if point is None:
                    continue
                distance = ends[side].distance(point)
                if record:
                    naming[node].append(distance)
                if distance == 0:
                    continue
                if distance <= NODE_END_SNAP_M:
                    geometry = _move_end(geometry, side, point)
                    moved += record
                elif record:
                    far[node].append((label, ends[side]))
            if record:
                network.at[label, "geometry"] = geometry
            else:
                original_geometry.loc[label] = geometry
    conflicts = []
    for node, items in sorted(far.items()):
        if len(items) != len(naming[node]):
            continue  # other edges reach the node: only these ends are off
        points = [point for _, point in items]
        centre = shapely.centroid(shapely.MultiPoint(points))
        if max(point.distance(centre) for point in points) > NODE_MEETING_SPREAD_M:
            continue
        distance = centre.distance(node_points[node])
        element_nrs = "; ".join(sorted(str(network.at[label, "element_nr"]) for label, _ in items))
        kind = "virtuellen Knoten" if vk.ID_PATTERN.match(node) else "Knoten"
        conflicts.append({"grund": f"Alle {len(items)} Kanten am {kind} {node} treffen sich {distance:.1f} m "
                                   "neben dem Knoten: nicht verschoben, bitte prüfen (Knoten verschieben oder Kanten "
                                   "anpassen)",
                          "art": "virtual_node" if vk.ID_PATTERN.match(node) else "knoten", "eintrag_id": None,
                          "ref": node, "element_nr": element_nrs,
                          "abweichung_m": round(distance, 2), "bearbeitet_von": None, "bearbeitet_am": None})
    return network, original_geometry, moved, conflicts


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
    # aenderung: the working network names the position changes, the customer network only says where they are
    working["aenderung"] = [join_sentences(a, b) for a, b in zip(working["aenderung"], working["aenderung_lage"])]
    customer["aenderung"] = [join_sentences(a, AENDERUNG_LAGE_HINT if has_text(b) else None)
                             for a, b in zip(customer["aenderung"], customer["aenderung_lage"])]
    return customer.drop(columns=["aenderung_lage"]), working.drop(columns=["aenderung_lage"])


def join_sentences(*texts):
    sentences = [sentence for text in texts if has_text(text) for sentence in text.split("; ")]
    return "; ".join(dict.fromkeys(sentences)) or None


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


def load_entries(export_path=None, gebiet=None):
    """App entries: from the KV database of the app (`gebiet`, default), from a JSON file of the app export
    „Alle Einträge“ (`export_path`), or none (both None)."""
    if export_path is not None:
        return json.loads(Path(export_path).read_text(encoding="utf-8"))
    if gebiet is not None:
        return kv_entries.fetch_entries(gebiet)
    return {"gebiet": None, "exported_at": None, "entries": []}


def run(export_path, ren_path=AUTO_PATH, output_dir=OUTPUT_DIR, virtual_nodes_path=VIRTUAL_NODES_PATH,
        new_edges_path=NEW_EDGES_PATH, detail_path=None, sections_path=SECTIONS_PATH, registry_path=None,
        proposals_path=None, official_nodes=None, bridge_nodes_path=None):
    """Der ganze Schritt 3. `export_path`: JSON-Datei wie der App-Export oder schon gelesene Einträge
    ({gebiet, exported_at, entries}); None: ohne App-Einträge. `official_nodes`: Detailnetzknoten (Knotenpunkt-ID,
    geometry); Kantenenden, die sie nennen, rücken wie bei virtuellen Knoten auf sie. Gibt Zähler und Konflikte zurück
    (für Tests). `bridge_nodes_path`: bauwerk_knoten.gpkg (Standard: neben `new_edges_path`)."""
    export = export_path if isinstance(export_path, dict) else load_entries(export_path)
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

    # The 53 of 2025 are app entries; a file only in tests
    registry = vk.read_registry(registry_path) if registry_path else vk.read_registry(entries=entries)
    proposals = read_proposals(proposals_path)
    app_nodes = AppNodes(entries, registry, parts)
    adopted = app_nodes.adopt_proposals(proposals)
    logging.info(f"Open proposals taken by an app node on them (within {PROPOSAL_AT_NODE_M:g} m, without vorschlag_id): "
                 f"{len(adopted)} {adopted}")
    accepted_ids = app_nodes.splitting_ids
    conflicts += check_nodes_on_edges(entries, corrected, parts, accepted_ids)

    # Zuordnungen: Detailnetzlinien nur laden, wenn es Zuordnungen gibt
    assignments = [entry for entry in active_entries(entries, "section_assignment") if not entry["data"].get("geloescht")]
    detail_lines = None
    if assignments:
        detail_lines, _ = load_detailnetz(path=detail_path, extra_columns=("strassenklasse1", "strassenklasse2"))
        detail_lines["ref"] = line_refs(detail_lines["element_nr"])
    sections = read_sections(sections_path)
    corrected, assignment_conflicts, assignment_report, assignment_stats, drawn_routes, part_routes = apply_assignments(
        corrected, parts, entries, sections, detail_lines, app_nodes)
    conflicts += assignment_conflicts
    original_geometry = original_geometry.reindex(corrected.index)
    for index in corrected.index[original_geometry.isna()]:  # von Hand aufgenommene Kanten: Lage = Lage im Netz
        original_geometry.loc[index] = corrected.geometry.loc[index]
    stats.update({f"zuordnung_{key}": value for key, value in assignment_stats.items()})

    base_element_nrs = load_base_element_nrs(network, detail_path)
    # Von Hand aufgenommene Stücke von Detailnetzkanten haben eine neue element_nr: sie zählt für neue und geteilte Kanten mit
    known_nrs = {nr for nr in base_element_nrs if isinstance(nr, str)}
    base_element_nrs += [nr for nr in corrected["element_nr"] if isinstance(nr, str) and nr not in known_nrs]
    known_ids = set(registry[vk.ID_COLUMN]) | set(proposals["id"])
    for column in ("von_knoten", "bis_knoten", "knoten_anfang", "knoten_ende"):
        if column in network.columns:
            known_ids |= {value for value in network[column].map(node_text) if has_text(value)}
    for element_nr in base_element_nrs:
        match = ELEMENT_NR_PATTERN.match(element_nr) if isinstance(element_nr, str) else None
        if match:
            known_ids |= {match.group(1), match.group(2)}
    new_edges, edge_conflicts = new_edge_frame(entries, base_element_nrs, app_nodes, known_ids)
    conflicts += app_nodes.conflicts + edge_conflicts + proposal_conflicts(proposals, app_nodes)
    stats["virtuelle_knoten_app"] = len(app_nodes.by_entry)
    stats["vorschlaege"] = len(proposals)
    stats["vorschlaege_uebernommen"] = len(app_nodes.accepted)
    stats["vorschlaege_offen"] = int((~proposals["id"].isin(list(app_nodes.accepted))).sum())
    stats["neue_kanten"] = len(new_edges)

    # Gezeichnete Kanten in die Ergebnisnetze, dann REN+-Kanten und gezeichnete Kanten an den virtuellen Knoten teilen
    assigned_section_ids = {(entry["data"].get("abschnitt") or {}).get("id") for entry in assignments}
    auto_routes = drawn_section_routes(sections, new_edges, assigned_section_ids)
    stats["neue_kanten_mit_weiterer_route"] = sum(1 for items in auto_routes.values() if items)
    corrected, original_geometry, drawn_labels = add_drawn_edges(
        corrected, original_geometry, new_edges, entries, drawn_routes, auto_routes)
    drawn_ids = {short_entry_id(entry_id) for entry_id in new_edges["entry_id"]} if len(new_edges) else set()
    for short, items in drawn_routes.items():
        if short in drawn_ids:
            continue
        for route, sid, assignment_id in items:
            conflicts.append({"grund": f"Radfernweg {route} (Abschnitt {sid}) ist einer gezeichneten Kante zugeordnet, "
                                       f"die es nicht (mehr) gibt: neu:{short}",
                              "art": "section_assignment", "eintrag_id": assignment_id, "ref": sid, "element_nr": None,
                              "abweichung_m": None, "bearbeitet_von": None, "bearbeitet_am": None})
    corrected, original_geometry, split_conflicts, split_stats, split_ranges = split_at_virtual_nodes(
        corrected, original_geometry, {item["ref"]: (labels[item["row"]], item["part"]) for item in parts.items},
        drawn_labels, entries, base_element_nrs, accepted_ids, app_nodes.by_entry)
    conflicts += split_conflicts
    stats.update(split_stats)
    corrected, part_conflicts = apply_part_routes(corrected, part_routes, split_ranges, drawn_labels)
    conflicts += part_conflicts
    stats["konflikte_teile"] = len(part_conflicts)
    corrected["von_knoten"] = corrected["von_knoten"].map(node_text)
    corrected["bis_knoten"] = corrected["bis_knoten"].map(node_text)
    corrected, stats["element_nr_umbenannt"] = apply_accepted_proposals(corrected, app_nodes.accepted, base_element_nrs)
    if app_nodes.accepted and len(new_edges):
        rename = lambda value: app_nodes.accepted.get(value, value)
        new_edges["von_knoten"] = new_edges["von_knoten"].map(rename)
        new_edges["bis_knoten"] = new_edges["bis_knoten"].map(rename)
        by_entry = {}
        for ids, element_nr in zip(corrected["eintrag_ids"], corrected["element_nr"]):
            for entry_id in (ids.split("; ") if isinstance(ids, str) else []):
                by_entry.setdefault(entry_id, element_nr)
        new_edges["element_nr"] = [by_entry.get(entry_id, element_nr)
                                   for entry_id, element_nr in zip(new_edges["entry_id"], new_edges["element_nr"])]
    all_nodes = virtual_node_rows(registry, app_nodes)
    stats["virtuelle_knoten_datei"] = len(all_nodes)
    active_nodes = all_nodes[all_nodes["status"] == vk.STATUS_ACTIVE]
    node_points = {}
    if official_nodes is not None:
        node_points.update(zip(official_nodes[ren.NODE_ID_COLUMN].astype(str), official_nodes.geometry))
    node_points.update(zip(active_nodes[vk.ID_COLUMN].astype(str), active_nodes.geometry))
    # Brücken und Tunnel: runs last of the edits, so the edges and their ends are final; the node of the lower level lies
    # where the node is, so the snapping below keeps both together
    node_positions = dict(node_points)
    node_positions.update(zip(proposals["id"].astype(str), proposals.geometry))
    corrected, bridge_nodes, bridge_conflicts, bridge_stats = apply_bridge_checks(
        corrected, entries, parts, {item["ref"]: labels[item["row"]] for item in parts.items}, app_nodes, node_positions,
        known_ids | set(node_positions))
    conflicts += bridge_conflicts
    stats.update({f"bauwerk_{key}": value for key, value in bridge_stats.items()})
    node_points.update({node["id"]: node["geometry"] for node in bridge_nodes})
    logging.info(f"Brücken und Tunnel: {bridge_stats['ok']} OK, {bridge_stats['getrennt']} getrennt "
                 f"({bridge_stats['getrennte_kanten']} Kantenenden auf den Knoten der unteren Ebene, "
                 f"{bridge_stats['konflikte']} Konflikte)")
    corrected, original_geometry, stats["enden_auf_knoten_gelegt"], node_conflicts = snap_ends_to_virtual_nodes(
        corrected, original_geometry, node_points)
    conflicts += node_conflicts
    logging.info(f"Edge ends moved exactly onto their virtual node: {stats['enden_auf_knoten_gelegt']}; nodes where all "
                 f"edges meet farther than {NODE_END_SNAP_M:g} m away (conflict): {[c['ref'] for c in node_conflicts]}")
    logging.info(f"Gezeichnete Kanten im Netz: {len(drawn_labels)}, geteilt an virtuellen Knoten: "
                 f"{split_stats['geteilte_kanten']} Kanten in {split_stats['teilkanten']} Teilkanten")
    if export_path is None:
        # Without an export the file would not know the nodes drawn in the app: keep the last state, if there is one
        logging.info("Without export: nodes drawn in the app and drawn edges stay as they are")
        if not Path(virtual_nodes_path).exists():
            write_virtual_nodes(Path(virtual_nodes_path), all_nodes)
    else:
        write_virtual_nodes(Path(virtual_nodes_path), all_nodes)
        write_new_edges(Path(new_edges_path), new_edges)
        write_bridge_nodes(Path(bridge_nodes_path) if bridge_nodes_path else Path(new_edges_path).parent / BRIDGE_NODES_NAME,
                           bridge_nodes)
        logging.info(f"Virtual nodes: {len(all_nodes)} ({all_nodes['herkunft'].value_counts(dropna=False).to_dict()}, "
                     f"{all_nodes['status'].value_counts().to_dict()}) to {virtual_nodes_path}; proposals: "
                     f"{stats['vorschlaege_uebernommen']} accepted, {stats['vorschlaege_offen']} open; "
                     f"drawn edges: {len(new_edges)} to {new_edges_path}")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    customer, working = customer_and_working_network(corrected, original_geometry)
    assert_unique(customer)
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
    parser.add_argument("--gebiet", default="berlin",
                        help="Gebiet der App, dessen Einträge aus der KV-Datenbank gelesen werden (Standard: berlin)")
    parser.add_argument("--export", type=Path,
                        help="Statt der KV-Datenbank: Export „Alle Einträge“ der App (JSON, Rückfall)")
    parser.add_argument("--ohne-export", action="store_true",
                        help="Ohne App-Einträge: nur die Ergebnisnetze aus Schritt 2 (Handarbeit fehlt dann); "
                             "virtuelle Knoten und gezeichnete Kanten werden nicht neu geschrieben")
    parser.add_argument("--ren-netz", type=Path, default=AUTO_PATH, help="Eingangsnetz (Standard: ren_netz_auto.gpkg)")
    args = parser.parse_args()
    if args.export and args.ohne_export:
        parser.error("Entweder --export oder --ohne-export")
    export = None if args.ohne_export else load_entries(args.export, args.gebiet)
    detail = gpd.read_file(detailnetz_path(), columns=["beginnt_bei_vp", "endet_bei_vp"])
    if detail.crs is None or detail.crs.to_epsg() != ren.DEFAULT_CRS:
        detail = detail.to_crs(CRS)
    run(export, ren_path=args.ren_netz, detail_path=detailnetz_path(), official_nodes=ren.load_nodes(detail))


if __name__ == "__main__":
    main()
