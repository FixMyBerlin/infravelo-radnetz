#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_knotenpunkte.py
--------------------------------------------------------------------
Erstellt den Knotenpunkt-Datensatz für alle Netzknoten des REN+-Netzes
(Radverkehrsnetz, Radschnellverbindungen, Hauptstraßennetz).

Knoten sind die von_knoten / bis_knoten der REN+-Kanten, ergänzt um die
manuell gepflegten virtuellen Knoten. Die Lage kommt aus den
Verbindungspunkten des Detailnetzes.

Jeder Knoten wird mit der Knotenpunkt-Lieferung 2025 (Radvorrangnetz)
verglichen, zuerst über die ID, dann über die Lage: bearbeitet_2025 = ja
oder nein. Für gelieferte Knoten werden die Bewertungen von 2025
übernommen. Dabei werden KP_HVS und LSA_KP auf Hauptverkehrsstrasse und
LSA_vorhanden migriert.

Für alle anderen Knoten werden Hauptverkehrsstrasse (aus den anliegenden
REN+-Kanten) und LSA_vorhanden (Open Data und OSM) abgeleitet. Nur diese
Knoten gehen an die Knotenpunkt-App und die ML-Vorhersage.

INPUT:
- ren-network/output/ren_netz_gesamt.gpkg (Layer: ren_netz)
- data/Berlin Verbindungspunkte Detailnetz.fgb
- data/Berlin Straßenabschnitte Detailnetz.fgb (jüngster Stand)
- data/Virtuelle-Knotenpunkte.gpkg (manuell gepflegt)
- data/Berlin Bezirke.gpkg
- data/netzquellen/knotenpunkte_2025.geojson.gz
  (tilda-static-data: region-infravelo/infravelo-datensatz-knoten-fortlaufend)
- data/netzquellen/lsa.gpkg, data/netzquellen/osm_ampeln.gpkg (download_lsa.py)

OUTPUT:
- knotenpunkte/output/knotenpunkte_gesamt.gpkg (Layer: knotenpunkte) / .geojson (WGS84)
- knotenpunkte/output/knotenpunkte_bewerten.geojson (WGS84, nur bearbeitet_2025 = nein)
- knotenpunkte/output/pruefliste.csv
"""

import gzip
import io
import logging
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT / "ren-network"))

import unify_networks as ren  # noqa: E402
from assign_node_ids import assign_node_ids_to_points  # noqa: E402

CRS = f"EPSG:{ren.DEFAULT_CRS}"
NODE_ID = ren.NODE_ID_COLUMN  # "Knotenpunkt‐ID" mit U+2010 wie in der Lieferung 2025

NETWORK_PATH = ren.OUTPUT_PATH
VIRTUAL_NODES_PATH = ROOT / "data" / "Virtuelle-Knotenpunkte.gpkg"
NODES_2025_PATH = ROOT / "data" / "netzquellen" / "knotenpunkte_2025.geojson.gz"
LSA_PATH = ROOT / "data" / "netzquellen" / "lsa.gpkg"
OSM_SIGNALS_PATH = ROOT / "data" / "netzquellen" / "osm_ampeln.gpkg"
OUTPUT_DIR = Path(__file__).resolve().parent / "output"
OUTPUT_PATH = OUTPUT_DIR / "knotenpunkte_gesamt.gpkg"
OUTPUT_LAYER = "knotenpunkte"
RATING_PATH = OUTPUT_DIR / "knotenpunkte_bewerten.geojson"
REPORT_PATH = OUTPUT_DIR / "pruefliste.csv"

# Virtuelle Knoten haben keine element_nr: anliegende Kanten über den Abstand
VIRTUAL_EDGE_TOLERANCE_M = 3.0
# Ampel gilt als am Knoten, wenn sie so nah ist. In infravelo-ml-knotenpunkte
# gegen LSA_KP der Lieferung 2025 kalibriert (5.001 Knoten, 20/25/30 m geprüft).
LSA_TOLERANCE_M = 25.0
# Knoten ohne ID-Treffer gelten als 2025 geliefert, wenn ein Knoten der
# Lieferung so nah liegt (geänderte IDs, virtuelle Knoten)
MATCH_2025_TOLERANCE_M = 5.0
# Liegt ein Knoten weiter von allen seinen REN+-Kanten entfernt, endet das Netz vor ihm
NETWORK_GAP_TOLERANCE_M = 5.0

LSA_CONFLICT_OSM = "nur_OSM"
LSA_CONFLICT_OPEN_DATA = "nur_OpenData"

# Bewertungen der Lieferung 2025, die unverändert übernommen werden
RATING_COLUMNS = ["Mar_RVF_KP", "Furt_rot", "Fl_Linksab", "vorgez_Fl", "RFS_Mitte",
                  "KP_Nichtbetrachten", "Mapillary-ID", "Kommentar"]
# Attribute der Lieferung 2025, die auf die neuen Attribute migriert werden
MIGRATED_COLUMNS = {"KP_HVS": "Hauptverkehrsstrasse", "LSA_KP": "LSA_vorhanden"}

FINAL_COLUMNS = [
    "lfd_nr",
    NODE_ID,
    "okstra_id",
    "Bezirksnummer",
    "ist_radvorrangnetz",
    "Hauptverkehrsstrasse",
    "LSA_vorhanden",
    "LSA_Konflikt",
    "Betrachtung",
    *RATING_COLUMNS,
    "ist_virtuell",
    "bearbeitet_2025",
    "knotenpunkt_id_2025",
    "netz_quellen",
    "anzahl_kanten",
    "geometry",
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s", force=True)

report_rows = []


def note(grund, node_id=None, node_id_2025=None, hinweis=None, geometry=None):
    report_rows.append({"grund": grund, "knotenpunkt_id": node_id, "knotenpunkt_id_2025": node_id_2025,
                        "hinweis": hinweis, "geometry": geometry})


def id_text(value):
    """IDs vereinheitlichen: 32580001, 32580001.0 und '32580001' -> '32580001'."""
    if value is None or (isinstance(value, float) and np.isnan(value)) or value is pd.NA:
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip() or None


def load_network():
    if not NETWORK_PATH.exists():
        raise SystemExit(f"Fehlt: {NETWORK_PATH}\nErst ren-network/unify_networks.py ausführen.")
    network = gpd.read_file(NETWORK_PATH, layer=ren.OUTPUT_LAYER).to_crs(CRS)
    logging.info(f"REN+: {len(network)} Kanten")
    return network


def edges_by_node(network):
    """Je Kante zwei Zeilen (von_knoten, bis_knoten) mit den Kantenattributen."""
    columns = ["radverkehrsnetz", "hauptverkehrsstrasse", "netz_quellen"]
    ends = pd.concat([
        network[["von_knoten", *columns]].rename(columns={"von_knoten": "node_id"}),
        network[["bis_knoten", *columns]].rename(columns={"bis_knoten": "node_id"}),
    ])
    ends["node_id"] = ends["node_id"].map(id_text)
    return ends[ends["node_id"].notna()]


def network_attributes(ends):
    """ist_radvorrangnetz, Hauptverkehrsstrasse, netz_quellen und anzahl_kanten je Knoten."""
    grouped = ends.groupby("node_id")

    def best_rvn(values):
        return ren._best_rvn(values) or ren.RVN_KEIN

    def sources(values):
        return ";".join(sorted({s for value in values.dropna() for s in value.split(";")}))

    return pd.DataFrame({
        "ist_radvorrangnetz": grouped["radverkehrsnetz"].agg(best_rvn),
        "Hauptverkehrsstrasse": grouped["hauptverkehrsstrasse"].agg(lambda v: bool((v == "ja").any())),
        "netz_quellen": grouped["netz_quellen"].agg(sources),
        "anzahl_kanten": grouped.size(),
    })


def load_connection_points(detail):
    """Verbindungspunkte des Detailnetzes mit Knotenpunkt-ID (wie ren.load_nodes, mit okstra_id)."""
    points = gpd.read_file(ren.VERBINDUNGSPUNKTE_PATH).to_crs(CRS)
    points = assign_node_ids_to_points(points, detail[["beginnt_bei_vp", "endet_bei_vp", "geometry"]])
    points["node_id"] = points[NODE_ID].map(id_text)
    points = points[points["node_id"].notna()]
    duplicated = points["node_id"].duplicated(keep="first")
    if duplicated.any():
        logging.warning(f"{duplicated.sum()} Verbindungspunkte mit bereits vergebener ID, erster Punkt gilt: "
                        f"{sorted(points.loc[duplicated, 'node_id'])[:10]}")
    return points[~duplicated].set_index("node_id")[["okstra_id", "geometry"]]


def detailnetz_end_points(detail):
    """Lage der Knoten laut Anfang und Ende der Detailnetz-Kanten (Rückfall ohne Verbindungspunkt)."""
    starts = gpd.GeoDataFrame({"node_id": detail["beginnt_bei_vp"].map(id_text)},
                              geometry=detail.geometry.apply(ren._as_multiline).apply(lambda g: g.geoms[0].boundary.geoms[0]),
                              crs=detail.crs)
    ends = gpd.GeoDataFrame({"node_id": detail["endet_bei_vp"].map(id_text)},
                            geometry=detail.geometry.apply(ren._as_multiline).apply(lambda g: g.geoms[-1].boundary.geoms[-1]),
                            crs=detail.crs)
    points = pd.concat([starts, ends])
    points = points[points["node_id"].notna()]
    return points.drop_duplicates("node_id").set_index("node_id")


def network_end_points(network, nodes):
    """Lage von Knoten ohne Detailnetz-Bezug aus den REN+-Kanten.

    Die Richtung der Geometrie folgt nicht immer der element_nr. Je Kante gilt
    deshalb das Ende, das weiter vom bereits verorteten Gegenknoten entfernt
    ist, sonst das Ende laut element_nr. Bei mehreren Kanten gewinnt die Lage,
    die die meisten Kanten teilen.
    """
    placed = nodes["geometry"].dropna()
    candidates = []
    for _, edge in network[network["element_nr"].notna()].iterrows():
        line = ren._as_multiline(edge.geometry)
        start, end = line.geoms[0].boundary.geoms[0], line.geoms[-1].boundary.geoms[-1]
        for node, other, own_end in [(edge["von_knoten"], edge["bis_knoten"], start),
                                     (edge["bis_knoten"], edge["von_knoten"], end)]:
            node, other = id_text(node), id_text(other)
            if node in placed.index:
                continue
            if other in placed.index:
                own_end = max([start, end], key=placed[other].distance)
            candidates.append((node, own_end))
    if not candidates:
        return gpd.GeoSeries(dtype="geometry")
    points = pd.DataFrame(candidates, columns=["node_id", "geometry"])
    points["key"] = points["geometry"].map(lambda p: (round(p.x), round(p.y)))
    counts = points.groupby(["node_id", "key"])["geometry"].agg(["first", "size"]).reset_index()
    best = counts.sort_values("size", ascending=False, kind="stable").drop_duplicates("node_id")
    return best.set_index("node_id")["first"]


def ren_nodes(network, detail):
    """Alle Netzknoten des REN+ mit Lage und Netzattributen."""
    attributes = network_attributes(edges_by_node(network))
    points = load_connection_points(detail)
    nodes = attributes.join(points, how="left")

    missing = nodes["geometry"].isna()
    if missing.any():
        fallback = detailnetz_end_points(detail)
        found = missing & nodes.index.isin(fallback.index)
        nodes.loc[found, "geometry"] = fallback.loc[nodes.index[found], "geometry"].values
        for node_id in nodes.index[found]:
            note("Kein Verbindungspunkt, Lage aus Kantenende im Detailnetz", node_id,
                 geometry=nodes.at[node_id, "geometry"])
        logging.info(f"{found.sum()} Knoten ohne Verbindungspunkt, Lage aus dem Detailnetz")

    missing = nodes["geometry"].isna()
    if missing.any():
        fallback = network_end_points(network, nodes)
        found = missing & nodes.index.isin(fallback.index)
        nodes.loc[found, "geometry"] = fallback.loc[nodes.index[found]].values
        for node_id in nodes.index[found]:
            note("Knoten nicht im Detailnetz, Lage aus Kantenende im REN+", node_id,
                 geometry=nodes.at[node_id, "geometry"])
        logging.info(f"{found.sum()} Knoten nicht im Detailnetz, Lage aus dem REN+")

    unplaced = nodes["geometry"].isna()
    if unplaced.any():
        for node_id in nodes.index[unplaced]:
            note("Knoten ohne Lage, nicht im Datensatz", node_id)
        logging.warning(f"{unplaced.sum()} Knoten ohne Lage, nicht im Datensatz: {sorted(nodes.index[unplaced])[:10]}")
        nodes = nodes[~unplaced]

    nodes = gpd.GeoDataFrame(nodes.rename_axis(NODE_ID).reset_index(), geometry="geometry", crs=CRS)
    nodes["ist_virtuell"] = 0
    logging.info(f"REN+-Knoten: {len(nodes)}")
    return nodes


def virtual_nodes(network):
    """Manuell gepflegte virtuelle Knoten; anliegende Kanten über den Abstand."""
    virtual = gpd.read_file(VIRTUAL_NODES_PATH).to_crs(CRS)
    # Die manuelle Datei schreibt die ID mit normalem Bindestrich
    virtual = virtual.rename(columns={"Knotenpunkt-ID": NODE_ID})
    virtual[NODE_ID] = virtual[NODE_ID].map(id_text)
    virtual = virtual[virtual[NODE_ID].notna()].reset_index(drop=True)

    buffers = gpd.GeoDataFrame({NODE_ID: virtual[NODE_ID]}, geometry=virtual.buffer(VIRTUAL_EDGE_TOLERANCE_M), crs=CRS)
    hits = gpd.sjoin(buffers, network[["radverkehrsnetz", "hauptverkehrsstrasse", "netz_quellen", "geometry"]],
                     predicate="intersects")
    attributes = network_attributes(hits.rename(columns={NODE_ID: "node_id"}))
    virtual = virtual.join(attributes, on=NODE_ID)

    off_network = virtual["anzahl_kanten"].isna()
    for _, row in virtual[off_network].iterrows():
        note(f"Virtueller Knoten ohne REN+-Kante im Umkreis von {VIRTUAL_EDGE_TOLERANCE_M:.0f} m",
             row[NODE_ID], geometry=row.geometry)
    virtual["ist_radvorrangnetz"] = virtual["ist_radvorrangnetz"].fillna(ren.RVN_KEIN)
    virtual["Hauptverkehrsstrasse"] = virtual["Hauptverkehrsstrasse"].fillna(False).astype(bool)
    virtual["netz_quellen"] = virtual["netz_quellen"].fillna("")
    virtual["anzahl_kanten"] = virtual["anzahl_kanten"].fillna(0).astype(int)
    virtual["okstra_id"] = None
    virtual["ist_virtuell"] = 1
    logging.info(f"Virtuelle Knoten: {len(virtual)}, davon {off_network.sum()} ohne REN+-Kante")
    return virtual


def add_district(nodes):
    """Bezirksnummer (01-12) aus gem wie assign_node_ids.assign_district_to_nodes;
    Punkte knapp außerhalb bekommen den nächsten Bezirk."""
    districts = gpd.read_file(ren.DISTRICTS_PATH).to_crs(CRS)[["gem", "geometry"]]
    inside = gpd.sjoin(nodes[["geometry"]], districts, how="left", predicate="within")
    gem = inside["gem"].groupby(level=0).first().reindex(nodes.index)
    outside = gem.isna()
    if outside.any():
        nearest = gpd.sjoin_nearest(nodes.loc[outside, ["geometry"]], districts)
        gem.loc[outside] = nearest["gem"].groupby(level=0).first()
    nodes["Bezirksnummer"] = gem.map(lambda value: None if pd.isna(value) else str(value)[-2:])
    return nodes


def nearest_distance(nodes, targets):
    hits = gpd.sjoin_nearest(nodes[["geometry"]], targets[["geometry"]], distance_col="distance")
    return hits["distance"].groupby(level=0).min().reindex(nodes.index, fill_value=np.inf)


def add_lsa(nodes):
    """LSA_vorhanden: ja, wenn Open Data UND OSM eine Ampel melden, nein, wenn keine
    Quelle eine meldet, sonst leer mit Grund in LSA_Konflikt."""
    for path in [LSA_PATH, OSM_SIGNALS_PATH]:
        if not path.exists():
            raise SystemExit(f"Fehlt: {path}\nErst knotenpunkte/download_lsa.py ausführen.")
    open_data = gpd.read_file(LSA_PATH).to_crs(CRS)
    osm = gpd.read_file(OSM_SIGNALS_PATH).to_crs(CRS)
    # Querungen, die ausdrücklich kein Signal haben, sind keine Ampel
    osm = osm[osm["crossing:signals"].fillna("") != "no"]

    at_open_data = nearest_distance(nodes, open_data) <= LSA_TOLERANCE_M
    at_osm = nearest_distance(nodes, osm) <= LSA_TOLERANCE_M
    nodes["LSA_vorhanden"] = pd.Series(pd.NA, index=nodes.index, dtype="boolean")
    nodes.loc[at_open_data & at_osm, "LSA_vorhanden"] = True
    nodes.loc[~at_open_data & ~at_osm, "LSA_vorhanden"] = False
    nodes["LSA_Konflikt"] = None
    nodes.loc[at_osm & ~at_open_data, "LSA_Konflikt"] = LSA_CONFLICT_OSM
    nodes.loc[at_open_data & ~at_osm, "LSA_Konflikt"] = LSA_CONFLICT_OPEN_DATA
    return nodes


def load_nodes_2025():
    with gzip.open(NODES_2025_PATH) as file:
        nodes_2025 = gpd.read_file(io.BytesIO(file.read())).to_crs(CRS)
    # MultiPoint mit einem Punkt
    nodes_2025["geometry"] = nodes_2025.geometry.representative_point()
    nodes_2025["node_id"] = nodes_2025[NODE_ID].map(id_text)
    for column in [*RATING_COLUMNS, *MIGRATED_COLUMNS]:
        values = nodes_2025[column]
        if values.dtype == object or pd.api.types.is_string_dtype(values):
            values = values.str.strip()
            values = values.where(~values.isin(["", "(NULL)"]))
        nodes_2025[column] = values
    logging.info(f"Lieferung 2025: {len(nodes_2025)} Knoten")

    # Doppelte IDs: Der vollständigste Eintrag gilt
    completeness = nodes_2025[[*RATING_COLUMNS, *MIGRATED_COLUMNS]].notna().sum(axis=1)
    order = completeness.sort_values(ascending=False, kind="stable").index
    duplicated = nodes_2025.loc[order, "node_id"].duplicated() & nodes_2025.loc[order, "node_id"].notna()
    for index in duplicated[duplicated].index:
        row = nodes_2025.loc[index]
        note("Doppelte ID in der Lieferung 2025, der vollständigere Eintrag gilt",
             node_id_2025=row["node_id"], geometry=row.geometry)
    if duplicated.any():
        logging.info(f"{duplicated.sum()} doppelte IDs in der Lieferung 2025 verworfen")
    return nodes_2025.drop(index=duplicated[duplicated].index)


def match_2025(nodes, nodes_2025):
    """Index in nodes_2025 je Knoten: über die ID, sonst über die Lage (jeder Knoten von 2025 höchstens einmal)."""
    index_by_id = pd.Series(nodes_2025.index, index=nodes_2025["node_id"])
    index_by_id = index_by_id[~index_by_id.index.duplicated()]
    match = nodes[NODE_ID].map(index_by_id)

    open_nodes = nodes[match.isna()]
    open_2025 = nodes_2025.drop(index=match.dropna().astype(int))
    hits = gpd.sjoin_nearest(open_nodes[["geometry"]], open_2025[["geometry"]],
                             max_distance=MATCH_2025_TOLERANCE_M, distance_col="distance")
    hits = hits.sort_values("distance")
    hits = hits[~hits.index.duplicated()]
    hits = hits[~hits["index_right"].duplicated()]
    match.loc[hits.index] = hits["index_right"]
    for index, row in hits.iterrows():
        note(f"Lieferung 2025 über die Lage zugeordnet ({row['distance']:.1f} m)", nodes.at[index, NODE_ID],
             nodes_2025.at[row["index_right"], "node_id"], geometry=nodes.at[index, "geometry"])
    logging.info(f"Lieferung 2025: {match.notna().sum() - len(hits)} Knoten über die ID, {len(hits)} über die Lage")

    unmatched = nodes_2025.drop(index=match.dropna().astype(int))
    for _, row in unmatched.iterrows():
        note("2025 geliefert, heute nicht im Netz", node_id_2025=row["node_id"], geometry=row.geometry)
    logging.info(f"{len(unmatched)} Knoten der Lieferung 2025 heute nicht im Netz")
    return match


def as_bool(value):
    return {"1": True, "0": False}.get(id_text(value))


def add_2025(nodes):
    """bearbeitet_2025, Bewertungen von 2025 und Migration von KP_HVS / LSA_KP."""
    nodes_2025 = load_nodes_2025()
    match = match_2025(nodes, nodes_2025)
    delivered = match.notna()
    source = nodes_2025.loc[match[delivered].astype(int)].set_index(nodes.index[delivered])

    nodes["bearbeitet_2025"] = np.where(delivered, "ja", "nein")
    nodes["knotenpunkt_id_2025"] = source["node_id"].reindex(nodes.index)
    for column in RATING_COLUMNS:
        nodes[column] = source[column].reindex(nodes.index)

    for old, new in MIGRATED_COLUMNS.items():
        values_2025 = source[old].map(as_bool).dropna().astype(bool)
        derived = nodes.loc[values_2025.index, new]
        differs = derived.notna() & (derived.astype(object) != values_2025)
        for index in values_2025.index[differs]:
            note(f"{new}: abgeleitet {derived[index]}, 2025 erhoben {values_2025[index]} (2025 gilt)",
                 nodes.at[index, NODE_ID], nodes.at[index, "knotenpunkt_id_2025"], geometry=nodes.at[index, "geometry"])
        logging.info(f"{old} -> {new}: {len(values_2025)} Werte von 2025, {differs.sum()} weichen von der Ableitung ab")
        nodes.loc[values_2025.index, new] = values_2025
        if new == "LSA_vorhanden":
            nodes.loc[values_2025.index, "LSA_Konflikt"] = None
    return nodes


def add_betrachtung(nodes):
    """Info: Hauptverkehrsstraße oder LSA. Ohne Hauptverkehrsstraße bei unklarer LSA leer."""
    lsa = nodes["LSA_vorhanden"]
    nodes["Betrachtung"] = pd.Series(pd.NA, index=nodes.index, dtype="boolean")
    nodes.loc[lsa.notna(), "Betrachtung"] = lsa[lsa.notna()].astype(bool)
    nodes.loc[nodes["Hauptverkehrsstrasse"], "Betrachtung"] = True
    return nodes


def note_nodes_off_network(nodes, network):
    """Knoten, die keine ihrer REN+-Kanten erreicht: Die Quelle deckt nur einen Teil des
    Detailnetz-Elements ab, die Verzweigung im Netz liegt dann mitten auf dem Element
    (Kandidat für einen virtuellen Knoten)."""
    ends = pd.concat([
        network[["von_knoten", "geometry"]].rename(columns={"von_knoten": "node_id"}),
        network[["bis_knoten", "geometry"]].rename(columns={"bis_knoten": "node_id"}),
    ])
    ends["node_id"] = ends["node_id"].map(id_text)
    ends = ends[ends["node_id"].notna()]
    points = nodes.loc[nodes["ist_virtuell"] == 0].set_index(NODE_ID).geometry
    ends = ends[ends["node_id"].isin(points.index)]
    distance = gpd.GeoSeries(ends.geometry.values, crs=CRS).distance(
        gpd.GeoSeries(points.loc[ends["node_id"]].values, crs=CRS))
    distance = pd.Series(distance.values, index=ends["node_id"].values).groupby(level=0).min()
    far = distance[distance > NETWORK_GAP_TOLERANCE_M]
    for node_id, gap in far.items():
        note(f"Netz erreicht den Knoten nicht ({gap:.0f} m), ggf. virtueller Knoten nötig", node_id,
             geometry=points[node_id])
    logging.info(f"{len(far)} Knoten mehr als {NETWORK_GAP_TOLERANCE_M:.0f} m von ihren REN+-Kanten entfernt")


def note_edges_without_nodes(network):
    """Kanten ohne element_nr: Hier fehlen noch Knoten (werden manuell ergänzt)."""
    edges = network[network["element_nr"].isna()]
    for _, row in edges.iterrows():
        note("Kante ohne element_nr, Knoten an den Enden fehlen",
             hinweis=f"lfd_nr {row['lfd_nr']}, {row['strassenname'] or 'ohne Straßenname'}, "
                     f"{row['netz_quellen']}, {row['laenge_m']:.0f} m",
             geometry=row.geometry.interpolate(0.5, normalized=True))
    logging.info(f"{len(edges)} Kanten ohne element_nr (fehlende Knoten in der Prüfliste)")


def finalize(nodes):
    nodes = nodes.sort_values(["ist_virtuell", NODE_ID], kind="stable").reset_index(drop=True)
    duplicated = nodes[NODE_ID].duplicated(keep=False)
    if duplicated.any():
        raise SystemExit(f"Doppelte {NODE_ID}: {sorted(set(nodes.loc[duplicated, NODE_ID]))[:20]}")
    nodes["lfd_nr"] = range(1, len(nodes) + 1)
    nodes["KP_Nichtbetrachten"] = pd.to_numeric(nodes["KP_Nichtbetrachten"]).astype("Int64")
    nodes["ist_virtuell"] = nodes["ist_virtuell"].astype("Int64")
    nodes["anzahl_kanten"] = nodes["anzahl_kanten"].astype("Int64")
    nodes["Hauptverkehrsstrasse"] = nodes["Hauptverkehrsstrasse"].astype("boolean")
    return gpd.GeoDataFrame(nodes[FINAL_COLUMNS], geometry="geometry", crs=CRS)


def write_outputs(nodes):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    nodes.to_file(OUTPUT_PATH, layer=OUTPUT_LAYER, driver="GPKG")
    logging.info(f"Geschrieben: {OUTPUT_PATH}")
    wgs84 = nodes.to_crs("EPSG:4326")
    geojson_path = OUTPUT_PATH.with_suffix(".geojson")
    wgs84.to_file(geojson_path, driver="GeoJSON", COORDINATE_PRECISION=7)
    logging.info(f"Geschrieben: {geojson_path}")

    # App und ML bewerten nur Knoten, die nicht 2025 geliefert wurden
    rating = wgs84[wgs84["bearbeitet_2025"] == "nein"]
    if (rating["bearbeitet_2025"] != "nein").any() or rating[NODE_ID].duplicated().any():
        raise SystemExit("knotenpunkte_bewerten enthält gelieferte oder doppelte Knoten")
    rating.to_file(RATING_PATH, driver="GeoJSON", COORDINATE_PRECISION=7)
    logging.info(f"Geschrieben: {RATING_PATH} ({len(rating)} Knoten)")

    report = gpd.GeoDataFrame(report_rows, geometry="geometry", crs=CRS).to_crs("EPSG:4326")
    report["lon"] = report.geometry.x.round(6)
    report["lat"] = report.geometry.y.round(6)
    report.drop(columns="geometry").to_csv(REPORT_PATH, index=False)
    logging.info(f"Prüfliste: {len(report)} Zeilen: {REPORT_PATH}")


def log_summary(nodes):
    logging.info(f"Knoten gesamt: {len(nodes)}")
    for column in ["bearbeitet_2025", "ist_radvorrangnetz", "Hauptverkehrsstrasse", "LSA_vorhanden", "LSA_Konflikt",
                   "Betrachtung", "ist_virtuell", "Bezirksnummer"]:
        logging.info(f"{column}: {nodes[column].value_counts(dropna=False).sort_index().to_dict()}")
    rating = nodes[nodes["bearbeitet_2025"] == "nein"]
    logging.info(f"Zu bewerten (bearbeitet_2025 = nein): {len(rating)}, "
                 f"davon Betrachtung = true: {(rating['Betrachtung'] == True).sum()}")  # noqa: E712


def main():
    network = load_network()
    detail = ren.load_detailnetz()
    nodes = pd.concat([ren_nodes(network, detail), virtual_nodes(network)], ignore_index=True)
    nodes = gpd.GeoDataFrame(nodes, geometry="geometry", crs=CRS)
    nodes = add_district(nodes)
    nodes = add_lsa(nodes)
    nodes = add_2025(nodes)
    nodes = add_betrachtung(nodes)
    note_nodes_off_network(nodes, network)
    note_edges_without_nodes(network)
    nodes = finalize(nodes)
    log_summary(nodes)
    write_outputs(nodes)


if __name__ == "__main__":
    main()
