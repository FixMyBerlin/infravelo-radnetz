#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
unify_networks.py
--------------------------------------------------------------------
Führt Radergänzungsnetz, Hauptstraßennetz und Radschnellverbindungen zu einem
einheitlichen Netz für REN+ zusammen (Zustand vor dem Matching).

Das touristische Radnetz (Radfernwege) fehlt noch: Es hat weder element_nr noch
Netzknoten und braucht einen Vorverarbeitungsschritt. Das Attribut
'routen_fernradweg' wird deshalb leer angelegt.

Fehlende element_nr werden aus den Knotenpunkten an den Kantenenden berechnet
(processing/scripts/assign_element_nr_to_rvn.py): Liegt an einem Ende kein Knotenpunkt,
wird entlang verbundener Kanten derselben Quelle weitergesucht. Verbindet das
Detailnetz dieselben zwei Knotenpunkte, wird dessen element_nr übernommen,
sonst entsteht von_bis.01. Kanten, an deren Enden kein Knotenpunkt gefunden
wird, bleiben ohne element_nr einzeln erhalten.

Pro element_nr entsteht eine Kante.

Kanten, die 2025 schon bearbeitet wurden (Ergebnisdatensatz C des
Radvorrangnetzes), bekommen bearbeitet_2025 = ja. Das Kartierungs-Netz ist das
Gesamtnetz ohne diese Kanten.

Ergänzende Daten (Straßenname, Straßenklasse) kommen aus dem Detailnetz.

Autobahnen und ihre Zubringer gehören nicht zum Netz: Kanten des
Hauptstraßennetzes, die im Detailnetz als Autobahn geführt sind
(strassenklasse2 AUBA/AUTO), werden vor dem Zusammenführen entfernt. Gehört
dieselbe Kante auch zum Radverkehrsnetz oder zu einer Radschnellverbindung,
bleibt sie über diese Quelle erhalten.

Einzelne Kanten, die diese Regel nicht erfasst, stehen mit Begründung in
ren-network/ausschluss_element_nr.csv und werden aus allen Quellen entfernt.

INPUT:
- data/netzquellen/radverkehrsnetz.gpkg
- data/netzquellen/hauptstrassennetz.gpkg
- data/netzquellen/radschnellverbindungen.gpkg
- data/Berlin Straßenabschnitte Detailnetz.fgb
  (liegt ein neuerer Stand als "Berlin Straßenabschnitte Detailnetz <Datum>.fgb"
  daneben, wird der jüngste verwendet)
- data/Berlin Verbindungspunkte Detailnetz.fgb
- data/Berlin Bezirke.gpkg
- ren-network/ausschluss_element_nr.csv
- data/netzquellen/ergebnis_2025_datensatz_c.geojson.gz
  (aggregated_rvn_final aus tilda-static-data, infravelo-datensatz-c-fortlaufend)

OUTPUT:
- ren-network/output/ren_netz_vereinheitlicht.gpkg (Layer: ren_netz)
- ren-network/output/ren_netz_vereinheitlicht.geojson (WGS84, z.B. für play.placemark.io)
- ren-network/output/ren_netz_kartierung.gpkg / .geojson (ohne bearbeitet_2025 = ja)
- ren-network/output/element_nr_nicht_im_detailnetz.csv
- ren-network/output/bearbeitet_2025_abweichungen.csv
"""

import gzip
import io
import logging
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import shapely
from shapely.geometry import LineString, MultiLineString

ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT / "processing"))
sys.path.append(str(ROOT / "processing" / "scripts"))

from assign_element_nr_to_rvn import assign_element_numbers  # noqa: E402
from assign_node_ids import assign_node_ids_to_points  # noqa: E402
from helpers.district_assignment import assign_district_to_edges  # noqa: E402

try:
    from helpers.globals import DEFAULT_CRS
except ImportError:
    DEFAULT_CRS = 25833

SOURCES_DIR = ROOT / "data" / "netzquellen"
DETAILNETZ_PATH = ROOT / "data" / "Berlin Straßenabschnitte Detailnetz.fgb"
# Lokale, nicht versionierte Stände mit Datum im Namen haben Vorrang
DETAILNETZ_DATED_GLOB = "Berlin Straßenabschnitte Detailnetz *.fgb"
VERBINDUNGSPUNKTE_PATH = ROOT / "data" / "Berlin Verbindungspunkte Detailnetz.fgb"
# Spaltenname aus assign_node_ids / assign_element_nr_to_rvn (mit U+2010 als Bindestrich)
NODE_ID_COLUMN = "Knotenpunkt‐ID"
DISTRICTS_PATH = ROOT / "data" / "Berlin Bezirke.gpkg"
OUTPUT_DIR = ROOT / "ren-network" / "output"
OUTPUT_PATH = OUTPUT_DIR / "ren_netz_vereinheitlicht.gpkg"
OUTPUT_LAYER = "ren_netz"
EXCLUSIONS_PATH = Path(__file__).resolve().parent / "ausschluss_element_nr.csv"
MISSING_REPORT_PATH = OUTPUT_DIR / "element_nr_nicht_im_detailnetz.csv"
RESULT_2025_PATH = ROOT / "data" / "netzquellen" / "ergebnis_2025_datensatz_c.geojson.gz"
MAPPING_NETWORK_PATH = OUTPUT_DIR / "ren_netz_kartierung.gpkg"
RESULT_2025_REPORT_PATH = OUTPUT_DIR / "bearbeitet_2025_abweichungen.csv"

# Reihenfolge bestimmt, aus welcher Quelle die Geometrie übernommen wird
SOURCE_PRIORITY = ["radverkehrsnetz", "radschnellverbindungen", "hauptstrassennetz"]

# Deckt eine Quelle nur einen Teil der Kante ab (z.B. das Radverkehrsnetz, das
# vor dem Knotenpunkt abbiegt), gewinnt die Quelle mit der vollständigen
# Geometrie. Bis zu dieser Differenz gelten Geometrien als gleich lang.
GEOMETRY_LENGTH_TOLERANCE_M = 10

# Rang der Radverkehrsnetz-Ausprägungen (höher gewinnt bei Konflikten)
RVN_VORRANG = "Radvorrangnetz"
RVN_ERGAENZUNG = "Radergänzungsnetz"
RVN_KEIN = "Kein Radverkehrsnetz vorhanden"
RVN_RANK = {RVN_VORRANG: 2, RVN_ERGAENZUNG: 1}

# Straßenstufen I bis III sind Hauptverkehrsstraßen
HAUPTVERKEHRSSTRASSEN_KLASSEN = {"I", "II", "III"}

# strassenklasse2 im Detailnetz: Autobahn inkl. Zubringer und Anschlussstellen
AUTOBAHN_KLASSEN = {"AUBA", "AUTO"}

# Kanten ohne passende element_nr gelten als 2025 bearbeitet, wenn dieser Anteil
# ihrer Länge im Puffer um die Kanten des Ergebnisses 2025 liegt
RESULT_2025_BUFFER_M = 5
RESULT_2025_MIN_SHARE = 0.8

ELEMENT_NR_PATTERN = r"^(\d+)_(\d+)\.\d+$"

FINAL_COLUMNS = [
    "lfd_nr",
    "element_nr",
    "element_nr_berechnet",
    "von_knoten",
    "bis_knoten",
    "laenge_m",
    "bezirksnummer",
    "strassenname",
    "radverkehrsnetz",
    "routen_fernradweg",
    "hauptverkehrsstrasse",
    "strassenklasse",
    "netz_quellen",
    "netz_quellen_teilweise",
    "in_detailnetz",
    "bearbeitet_2025",
    "geometry",
]

MISSING_REPORT_COLUMNS = ["lfd_nr", "element_nr", "element_nr_berechnet", "netz_quellen", "bezirksnummer", "strassenname", "laenge_m"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def _read_source(name):
    gdf = gpd.read_file(SOURCES_DIR / f"{name}.gpkg")
    if gdf.crs is None or gdf.crs.to_epsg() != DEFAULT_CRS:
        gdf = gdf.to_crs(f"EPSG:{DEFAULT_CRS}")
    return gdf


def _blank_to_none(series):
    return series.where(series.notna() & (series.astype(str).str.strip() != ""), None)


def load_sources():
    """Lädt die drei Netze und bringt sie auf ein gemeinsames Spaltenschema."""
    frames = []

    radverkehr = _read_source("radverkehrsnetz")
    frames.append(gpd.GeoDataFrame({
        "element_nr": _blank_to_none(radverkehr["elem_nr"]),
        "radverkehrsnetz": radverkehr["ist_radvorrangnetz"].map(
            {"Radvorrangnetz": RVN_VORRANG, "Ergänzungsnetz": RVN_ERGAENZUNG}),
        "strassenname": None,
        "strassenklasse": None,
        "netz": "radverkehrsnetz",
    }, geometry=radverkehr.geometry, crs=radverkehr.crs))

    schnell = _read_source("radschnellverbindungen")
    frames.append(gpd.GeoDataFrame({
        "element_nr": _blank_to_none(schnell["element_nr"]),
        # 'Sonstiges' gehört nicht zum Radverkehrsnetz
        "radverkehrsnetz": schnell["RVN"].map(
            {"Vorrangnetz": RVN_VORRANG, "Ergänzungsnetz": RVN_ERGAENZUNG}),
        "strassenname": None,
        "strassenklasse": None,
        "netz": "radschnellverbindungen",
    }, geometry=schnell.geometry, crs=schnell.crs))

    haupt = _read_source("hauptstrassennetz")
    frames.append(gpd.GeoDataFrame({
        "element_nr": _blank_to_none(haupt["element_nr"]),
        "radverkehrsnetz": None,
        "strassenname": _blank_to_none(haupt["strassenname"]),
        "strassenklasse": _blank_to_none(haupt["strassenklasse1"]),
        "netz": "hauptstrassennetz",
    }, geometry=haupt.geometry, crs=haupt.crs))

    for frame in frames:
        logging.info(f"{frame['netz'].iloc[0]}: {len(frame)} Kanten, {frame['element_nr'].isna().sum()} ohne element_nr")

    return gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=f"EPSG:{DEFAULT_CRS}")


def load_detailnetz():
    dated = sorted(DETAILNETZ_PATH.parent.glob(DETAILNETZ_DATED_GLOB))
    path = dated[-1] if dated else DETAILNETZ_PATH
    logging.info(f"Detailnetz: {path.name}")
    detail = gpd.read_file(path, columns=[
        "element_nr", "strassenname", "strassenklasse1", "strassenklasse2", "beginnt_bei_vp", "endet_bei_vp"])
    if detail.crs is None or detail.crs.to_epsg() != DEFAULT_CRS:
        detail = detail.to_crs(f"EPSG:{DEFAULT_CRS}")
    return detail


def remove_motorways(sources, detail):
    """Entfernt Autobahnen und Zubringer aus dem Hauptstraßennetz."""
    motorway_element_nr = set(detail.loc[detail["strassenklasse2"].isin(AUTOBAHN_KLASSEN), "element_nr"])
    is_motorway = (sources["netz"] == "hauptstrassennetz") & sources["element_nr"].isin(motorway_element_nr)
    logging.info(f"hauptstrassennetz: {is_motorway.sum()} Autobahn-Kanten entfernt "
                 f"({sources.loc[is_motorway].geometry.length.sum() / 1000:.1f} km)")

    remaining = sources.loc[~is_motorway].reset_index(drop=True)
    kept_elsewhere = sorted(set(remaining["element_nr"].dropna()) & motorway_element_nr)
    if kept_elsewhere:
        logging.warning(f"{len(kept_elsewhere)} Autobahn-Kanten bleiben über Radverkehrsnetz oder "
                        f"Radschnellverbindungen im Netz: {kept_elsewhere}")
    return remaining


def load_nodes(detail):
    """Verbindungspunkte mit Knotenpunkt-ID aus beginnt_bei_vp / endet_bei_vp des Detailnetzes."""
    points = gpd.read_file(VERBINDUNGSPUNKTE_PATH)
    nodes = assign_node_ids_to_points(points, detail[["beginnt_bei_vp", "endet_bei_vp", "geometry"]])
    nodes = nodes.loc[nodes[NODE_ID_COLUMN].notna(), [NODE_ID_COLUMN, "geometry"]].reset_index(drop=True)
    nodes[NODE_ID_COLUMN] = nodes[NODE_ID_COLUMN].astype(str)
    logging.info(f"Verbindungspunkte mit Knotenpunkt-ID: {len(nodes)}/{len(points)}")
    return nodes


def remove_excluded(sources):
    """Entfernt die manuell gepflegten Kanten aus ausschluss_element_nr.csv."""
    exclusions = pd.read_csv(EXCLUSIONS_PATH, dtype=str)
    is_excluded = sources["element_nr"].isin(exclusions["element_nr"])
    logging.info(f"Ausschlussliste: {is_excluded.sum()} Quellkanten entfernt "
                 f"({sources.loc[is_excluded].geometry.length.sum() / 1000:.1f} km), "
                 f"Gründe: {exclusions['grund'].value_counts().to_dict()}")
    unknown = sorted(set(exclusions["element_nr"]) - set(sources["element_nr"].dropna()))
    if unknown:
        logging.warning(f"{len(unknown)} element_nr der Ausschlussliste kommen in keiner Quelle vor: {unknown}")
    return sources.loc[~is_excluded].reset_index(drop=True)


def _detailnetz_by_node_pair(detail):
    """Detailnetz-Abschnitte je ungeordnetem Knotenpaar."""
    pairs = {}
    for element_nr, von, bis, geom in zip(detail["element_nr"], detail["beginnt_bei_vp"],
                                          detail["endet_bei_vp"], detail.geometry):
        if pd.notna(element_nr) and pd.notna(von) and pd.notna(bis):
            pairs.setdefault(frozenset((str(von), str(bis))), []).append((element_nr, geom))
    return pairs


def _element_nr_for_nodes(von, bis, geom, detail_pairs):
    """element_nr des Detailnetzes zwischen beiden Knoten, unabhängig von der
    Digitalisierungsrichtung; bei mehreren Abschnitten der geometrisch nächste.
    Ohne passenden Abschnitt: von_bis.01"""
    candidates = detail_pairs.get(frozenset((von, bis)))
    if not candidates:
        return f"{von}_{bis}.01"
    return min(candidates, key=lambda c: geom.hausdorff_distance(c[1]))[0]


def assign_missing_element_nr(sources, detail, nodes):
    """Berechnet fehlende element_nr aus den Knotenpunkten an den Kantenenden."""
    sources = sources.copy()
    sources["element_nr_berechnet"] = False
    detail_pairs = _detailnetz_by_node_pair(detail)

    # Graph pro Quelle, da nur Kanten derselben Quelle gemeinsame Endpunkte haben
    for netz, group in sources[sources["element_nr"].isna()].groupby("netz", sort=False):
        computed = assign_element_numbers(group[["geometry"]], nodes)
        computed.index = group.index
        complete = computed[computed["beginnt_bei_vp"].notna() & computed["endet_bei_vp"].notna()]

        from_detail = 0
        # Alle Kanten einer Kette (gleiche vorläufige element_nr) werden gemeinsam zugeordnet
        for _, chain in complete.groupby("element_nr"):
            von, bis = chain["beginnt_bei_vp"].iloc[0], chain["endet_bei_vp"].iloc[0]
            element_nr = _element_nr_for_nodes(von, bis, shapely.unary_union(chain.geometry.values), detail_pairs)
            from_detail += frozenset((von, bis)) in detail_pairs
            sources.loc[chain.index, "element_nr"] = element_nr
            sources.loc[chain.index, "element_nr_berechnet"] = True

        logging.info(
            f"{netz}: element_nr für {len(complete)}/{len(group)} Kanten ohne element_nr berechnet "
            f"({complete['element_nr'].nunique()} Knotenpaare, davon {from_detail} im Detailnetz), "
            f"{len(group) - len(complete)} ohne Knotenpunkt an beiden Enden"
        )
    return sources


def _as_multiline(geom):
    if isinstance(geom, LineString):
        return MultiLineString([geom])
    return geom


def _merge_parts(geoms):
    """Fasst mehrere Teilgeometrien einer element_nr zu einer MultiLineString zusammen."""
    if len(geoms) == 1:
        return _as_multiline(geoms[0])
    merged = shapely.line_merge(shapely.unary_union(geoms))
    return _as_multiline(merged)


def _best_rvn(values):
    ranked = [v for v in values if v in RVN_RANK]
    return max(ranked, key=RVN_RANK.get) if ranked else None


def _first_valid(values):
    for value in values:
        if pd.notna(value):
            return value
    return None


def merge_by_element_nr(sources):
    """Eine Kante pro element_nr; Kanten ohne element_nr bleiben einzeln."""
    sources = sources.copy()
    sources["prio"] = sources["netz"].map({n: i for i, n in enumerate(SOURCE_PRIORITY)})

    keyed = sources[sources["element_nr"].notna()]
    unkeyed = sources[sources["element_nr"].isna()]

    rows = []
    multi_part_groups = 0
    partial_geometry_groups = 0
    for element_nr, group in keyed.groupby("element_nr", sort=False):
        # Geometrie aus der Quelle mit höchster Priorität, die die Kante vollständig abdeckt
        length_by_prio = group.geometry.length.groupby(group["prio"]).sum()
        complete = length_by_prio[length_by_prio >= length_by_prio.max() - GEOMETRY_LENGTH_TOLERANCE_M]
        best_prio = complete.index.min()
        if best_prio != group["prio"].min():
            partial_geometry_groups += 1
        # Quellen, die nur einen Teil der Kante abdecken
        partial_sources = sorted(set(group.loc[~group["prio"].isin(complete.index), "netz"]))
        parts = list(group.loc[group["prio"] == best_prio, "geometry"])
        if len(parts) > 1:
            multi_part_groups += 1
        ordered = group.sort_values("prio")
        rows.append({
            "element_nr": element_nr,
            "geometry": _merge_parts(parts),
            "radverkehrsnetz": _best_rvn(group["radverkehrsnetz"]),
            "strassenname": _first_valid(ordered["strassenname"].iloc[::-1]),
            "strassenklasse": _first_valid(ordered["strassenklasse"].iloc[::-1]),
            "netz_quellen": ";".join(sorted(set(group["netz"]))),
            "netz_quellen_teilweise": ";".join(partial_sources) or None,
            "element_nr_berechnet": "ja" if group["element_nr_berechnet"].any() else "nein",
        })

    for _, row in unkeyed.iterrows():
        rows.append({
            "element_nr": None,
            "element_nr_berechnet": None,
            "geometry": _as_multiline(row.geometry),
            "radverkehrsnetz": row["radverkehrsnetz"],
            "strassenname": row["strassenname"],
            "strassenklasse": row["strassenklasse"],
            "netz_quellen": row["netz"],
            "netz_quellen_teilweise": None,
        })

    merged = gpd.GeoDataFrame(rows, geometry="geometry", crs=f"EPSG:{DEFAULT_CRS}")
    logging.info(
        f"Zusammengeführt: {len(keyed)} + {len(unkeyed)} Quellkanten -> {len(merged)} Kanten "
        f"({merged['element_nr'].notna().sum()} mit element_nr, {len(unkeyed)} ohne). "
        f"element_nr mit mehreren Teilgeometrien in derselben Quelle: {multi_part_groups}. "
        f"Geometrie aus nachrangiger Quelle, weil die vorrangige nur einen Teil abdeckt: {partial_geometry_groups}"
    )
    return merged


def add_detailnetz_attributes(network, detail):
    """Ergänzt Straßenname und Straßenklasse aus dem Detailnetz über die element_nr."""
    detail = detail.drop_duplicates("element_nr").set_index("element_nr")

    network = network.copy()
    in_detail = network["element_nr"].isin(detail.index)
    logging.info(f"element_nr im Detailnetz gefunden: {in_detail.sum()}/{network['element_nr'].notna().sum()}")
    # Kanten ohne element_nr können nicht nachgeschlagen werden und bleiben leer
    network["in_detailnetz"] = in_detail.map({True: "ja", False: "nein"}).where(network["element_nr"].notna(), None)

    dn_name = network["element_nr"].map(detail["strassenname"])
    dn_klasse = _blank_to_none(network["element_nr"].map(detail["strassenklasse1"]))
    log_klassen_differences(network, dn_klasse)

    network["strassenname"] = network["strassenname"].fillna(_blank_to_none(dn_name))
    network["strassenklasse"] = network["strassenklasse"].fillna(dn_klasse)
    return network


def log_klassen_differences(network, dn_klasse):
    """Listet Kanten, bei denen Detailnetz und Hauptstraßennetz bei der Straßenklasse abweichen."""
    in_hsn = network["netz_quellen"].str.contains("hauptstrassennetz")
    hsn_klasse = network["strassenklasse"]

    abweichend = in_hsn & hsn_klasse.notna() & dn_klasse.notna() & (hsn_klasse != dn_klasse)
    if abweichend.any():
        details = [f"{e} (HSN {h}, DN {d})" for e, h, d in
                   zip(network.loc[abweichend, "element_nr"], hsn_klasse[abweichend], dn_klasse[abweichend])]
        logging.warning(f"{abweichend.sum()} Kanten mit abweichender Straßenklasse zwischen "
                        f"Hauptstraßennetz und Detailnetz: {details}")

    nicht_in_hsn = ~in_hsn & dn_klasse.isin(HAUPTVERKEHRSSTRASSEN_KLASSEN)
    if nicht_in_hsn.any():
        details = [f"{e} (DN {d})" for e, d in
                   zip(network.loc[nicht_in_hsn, "element_nr"], dn_klasse[nicht_in_hsn])]
        logging.warning(f"{nicht_in_hsn.sum()} Kanten sind laut Detailnetz Hauptverkehrsstraße (Klasse I-III), "
                        f"fehlen aber im Hauptstraßennetz: {details}")


def add_nodes(network):
    """von_knoten / bis_knoten als Zahl aus der element_nr (Format: von_bis.NN)."""
    parts = network["element_nr"].str.extract(ELEMENT_NR_PATTERN)
    invalid = network.loc[network["element_nr"].notna() & parts[0].isna(), "element_nr"]
    if len(invalid):
        logging.warning(
            f"{len(invalid)} element_nr entsprechen nicht dem Muster von_bis.NN, "
            f"von_knoten/bis_knoten bleiben leer: {sorted(invalid)}"
        )
    network["von_knoten"] = pd.to_numeric(parts[0]).astype("Int64")
    network["bis_knoten"] = pd.to_numeric(parts[1]).astype("Int64")
    return network


def add_district(network):
    """Bezirksnummer (01-12) nach größtem räumlichen Anteil, wie in der Aggregation."""
    network = assign_district_to_edges(network.copy(), str(DISTRICTS_PATH), f"EPSG:{DEFAULT_CRS}")
    network["bezirksnummer"] = pd.to_numeric(network["Bezirksnummer"]).astype("Int64")
    return network


def finalize(network):
    network = network.copy()
    network["radverkehrsnetz"] = network["radverkehrsnetz"].fillna(RVN_KEIN)
    network["laenge_m"] = network.geometry.length.round(1)
    # Nur Kanten aus dem Hauptstraßennetz können Hauptverkehrsstraßen sein
    in_hauptstrassennetz = network["netz_quellen"].str.contains("hauptstrassennetz")
    ist_hvs = network["strassenklasse"].isin(HAUPTVERKEHRSSTRASSEN_KLASSEN)
    network["hauptverkehrsstrasse"] = (in_hauptstrassennetz & ist_hvs).map({True: "ja", False: "nein"})
    # TODO: Radfernwege, sobald das touristische Netz vorverarbeitet ist
    network["routen_fernradweg"] = None

    network = network.sort_values("element_nr", na_position="last", kind="stable").reset_index(drop=True)
    network["lfd_nr"] = range(1, len(network) + 1)
    return network[FINAL_COLUMNS]


def add_bearbeitet_2025(network):
    """Markiert Kanten, die im Ergebnis 2025 stehen: über die element_nr, sonst über die Geometrie."""
    with gzip.open(RESULT_2025_PATH) as file:
        result = gpd.read_file(io.BytesIO(file.read())).to_crs(network.crs)
    element_nrs = set(result["element_nr"].dropna())
    by_element_nr = network["element_nr"].isin(element_nrs)

    buffers = result.geometry.buffer(RESULT_2025_BUFFER_M)
    share = pd.Series(0.0, index=network.index)
    for index, geom in network.geometry.items():
        nearby = buffers.iloc[buffers.sindex.query(geom, predicate="intersects")]
        if len(nearby):
            share[index] = geom.intersection(nearby.union_all()).length / geom.length
    by_geometry = ~by_element_nr & (share >= RESULT_2025_MIN_SHARE)

    network = network.copy()
    network["bearbeitet_2025"] = (by_element_nr | by_geometry).map({True: "ja", False: "nein"})
    logging.info(f"2025 bearbeitet: {by_element_nr.sum()} Kanten über element_nr, {by_geometry.sum()} über die Geometrie, "
                 f"{network.loc[by_element_nr | by_geometry].geometry.length.sum() / 1000:.1f} km")

    # Abweichungen zur Prüfung: gleiche element_nr an anderer Stelle, nur geometrisch
    # gefunden, heutiges Radvorrangnetz ohne Bearbeitung 2025
    grund = pd.Series(None, index=network.index, dtype=object)
    grund[(network["radverkehrsnetz"] == RVN_VORRANG) & ~(by_element_nr | by_geometry)] = "Radvorrangnetz, 2025 nicht bearbeitet"
    grund[by_geometry] = "nur über Geometrie gefunden"
    grund[by_element_nr & (share < 0.5)] = "element_nr 2025 an anderer Stelle"
    report = network.loc[grund.notna(), ["element_nr", "strassenname", "radverkehrsnetz", "netz_quellen"]].copy()
    report["laenge_m"] = network.geometry.length.round(1)
    report["anteil_im_ergebnis_2025"] = share.round(2)
    report["grund"] = grund
    missing = sorted(element_nrs - set(network["element_nr"].dropna()))
    report = pd.concat([report, pd.DataFrame({"element_nr": missing, "grund": "2025 bearbeitet, element_nr nicht mehr im Netz"})])
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report.to_csv(RESULT_2025_REPORT_PATH, index=False)
    logging.info(f"Abweichungen zum Ergebnis 2025: {report['grund'].value_counts().to_dict()}: {RESULT_2025_REPORT_PATH}")
    return network


def write_network(network, path):
    network.to_file(path, layer=OUTPUT_LAYER, driver="GPKG")
    logging.info(f"Geschrieben: {path}")
    geojson_path = path.with_suffix(".geojson")
    network.to_crs("EPSG:4326").to_file(geojson_path, driver="GeoJSON", COORDINATE_PRECISION=6)
    logging.info(f"Geschrieben: {geojson_path}")


def write_missing_report(network):
    """Schreibt alle Kanten, deren element_nr nicht im Detailnetz vorkommt, in eine CSV."""
    missing = network.loc[network["in_detailnetz"] == "nein", MISSING_REPORT_COLUMNS]
    missing.to_csv(MISSING_REPORT_PATH, index=False)
    logging.info(f"{len(missing)} Kanten mit element_nr nicht im Detailnetz: {MISSING_REPORT_PATH}")


def log_summary(network):
    logging.info(f"Kanten gesamt: {len(network)}, Länge {network['laenge_m'].sum() / 1000:.1f} km")
    for column in ["radverkehrsnetz", "hauptverkehrsstrasse", "netz_quellen", "netz_quellen_teilweise", "in_detailnetz",
                   "element_nr_berechnet", "bearbeitet_2025"]:
        logging.info(f"{column}: {network[column].value_counts(dropna=False).to_dict()}")
    for column in ["element_nr", "von_knoten", "bis_knoten", "bezirksnummer", "strassenname"]:
        logging.info(f"{column}: {network[column].isna().sum()} ohne Wert")
    duplicated = network["element_nr"].dropna().duplicated().sum()
    logging.info(f"Doppelte element_nr: {duplicated}")


def main():
    sources = load_sources()
    detail = load_detailnetz()
    sources = remove_motorways(sources, detail)
    sources = remove_excluded(sources)
    sources = assign_missing_element_nr(sources, detail, load_nodes(detail))
    network = merge_by_element_nr(sources)
    network = add_detailnetz_attributes(network, detail)
    network = add_nodes(network)
    network = add_district(network)
    network = add_bearbeitet_2025(network)
    network = finalize(network)
    log_summary(network)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_network(network, OUTPUT_PATH)
    mapping_network = network[network["bearbeitet_2025"] == "nein"]
    logging.info(f"Kartierungs-Netz: {len(mapping_network)} Kanten, {mapping_network['laenge_m'].sum() / 1000:.1f} km")
    write_network(mapping_network, MAPPING_NETWORK_PATH)
    write_missing_report(network)


if __name__ == "__main__":
    main()
