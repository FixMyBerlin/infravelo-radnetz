#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
audit_double_edges.py
--------------------------------------------------------------------
Sucht im vereinheitlichten REN+-Netz Kanten, die denselben Weg doppelt
abbilden, und schreibt sie als Prüfliste. Es wird nichts entfernt: Was
wegfallen soll, kommt nach der Prüfung in ausschluss_element_nr.csv.

Zwei Fälle:
- ueberlappend: Zwei Kanten liegen aufeinander (mindestens OVERLAP_MIN_SHARE
  der kürzeren Kante im Abstand von OVERLAP_DISTANCE_M zur anderen),
  z.B. 52490051_53490038.01 und 52490051_53490038.02.
- parallel_zum_radverkehrsnetz: Eine Kante ohne Radverkehrsnetz verläuft
  neben Kanten des Radverkehrsnetzes (mindestens PARALLEL_MIN_SHARE ihrer
  Länge im Abstand von PARALLEL_DISTANCE_M), z.B. An der Wuhlheide
  53490017_54490002.01 neben den Kanten des Radergänzungsnetzes.

INPUT:
- ren-network/output/ren_netz_vereinheitlicht.gpkg

OUTPUT:
- ren-network/output/doppelte_kanten.csv      (eine Zeile je Fund)
- ren-network/output/doppelte_kanten.geojson  (Kandidaten und Partner, WGS84)
"""

import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

ROOT = Path(__file__).resolve().parent.parent
NETWORK_PATH = ROOT / "ren-network" / "output" / "ren_netz_vereinheitlicht.gpkg"
CSV_PATH = NETWORK_PATH.with_name("doppelte_kanten.csv")
GEOJSON_PATH = NETWORK_PATH.with_name("doppelte_kanten.geojson")

OVERLAP_DISTANCE_M = 3
OVERLAP_MIN_SHARE = 0.5
PARALLEL_DISTANCE_M = 20
PARALLEL_MIN_SHARE = 0.8

RVN_KEIN = "Kein Radverkehrsnetz vorhanden"
EDGE_COLUMNS = ["lfd_nr", "element_nr", "strassenname", "radverkehrsnetz", "netz_quellen", "in_detailnetz", "laenge_m"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def node_pair(element_nr):
    """Ungeordnetes Knotenpaar einer element_nr (von_bis.NN), sonst None."""
    if not isinstance(element_nr, str) or "_" not in element_nr:
        return None
    return frozenset(element_nr.split(".")[0].split("_"))


def shares_within(geometries, candidates, partners, distance):
    """Je (Kandidat, Partner): Länge des Kandidaten im Puffer des Partners."""
    buffers = shapely.buffer(geometries[partners], distance, cap_style="flat")
    i, j = shapely.STRtree(buffers).query(geometries[candidates], predicate="intersects")
    pairs = pd.DataFrame({"kandidat": candidates[i], "partner": partners[j], "buffer": j})
    pairs = pairs[pairs["kandidat"] != pairs["partner"]].reset_index(drop=True)
    pairs["laenge"] = shapely.length(shapely.intersection(
        geometries[pairs["kandidat"].values], buffers[pairs["buffer"].values]))
    return pairs, buffers


def find_overlapping(network):
    """Paare von Kanten, die aufeinander liegen."""
    geometries = network.geometry.values
    everything = np.arange(len(network))
    pairs, _ = shares_within(geometries, everything, everything, OVERLAP_DISTANCE_M)
    pairs["anteil"] = pairs["laenge"] / network.geometry.length.values[pairs["kandidat"].values]
    pairs = pairs[pairs["anteil"] >= OVERLAP_MIN_SHARE]

    # Jedes Paar nur einmal: Kandidat ist die Kante mit dem höheren Anteil
    pairs["key"] = [frozenset(pair) for pair in zip(pairs["kandidat"], pairs["partner"])]
    pairs = pairs.sort_values("anteil", ascending=False).drop_duplicates("key")
    return [("ueberlappend", row.kandidat, [row.partner], row.anteil) for row in pairs.itertuples()]


def find_parallel_to_bike_network(network):
    """Kanten ohne Radverkehrsnetz, die neben Kanten des Radverkehrsnetzes verlaufen."""
    geometries = network.geometry.values
    in_bike_network = (network["radverkehrsnetz"] != RVN_KEIN).values
    candidates = np.where(~in_bike_network)[0]
    partners = np.where(in_bike_network)[0]
    pairs, buffers = shares_within(geometries, candidates, partners, PARALLEL_DISTANCE_M)

    findings = []
    lengths = network.geometry.length.values
    for candidate, group in pairs.groupby("kandidat"):
        covered = shapely.intersection(geometries[candidate], shapely.union_all(buffers[group["buffer"].values]))
        share = shapely.length(covered) / lengths[candidate]
        if share >= PARALLEL_MIN_SHARE:
            ordered = group.sort_values("laenge", ascending=False)
            findings.append(("parallel_zum_radverkehrsnetz", candidate, list(ordered["partner"]), share))
    return findings


def build_report(network, findings):
    """CSV-Zeilen und GeoJSON-Features je Fund."""
    rows, features = [], []
    for number, (kind, candidate, partners, share) in enumerate(findings, start=1):
        edge = network.iloc[candidate]
        partner_edges = network.iloc[partners]
        same_nodes = node_pair(edge["element_nr"]) is not None and any(
            node_pair(nr) == node_pair(edge["element_nr"]) for nr in partner_edges["element_nr"])
        rows.append({
            "nr": number,
            "typ": kind,
            **{column: edge[column] for column in EDGE_COLUMNS},
            "anteil": round(share, 2),
            "gleiches_knotenpaar": "ja" if same_nodes else "nein",
            "partner_lfd_nr": ";".join(str(value) for value in partner_edges["lfd_nr"]),
            "partner_element_nr": ";".join(str(value) for value in partner_edges["element_nr"].fillna("-")),
            "partner_radverkehrsnetz": ";".join(sorted(set(partner_edges["radverkehrsnetz"]))),
            "partner_netz_quellen": ";".join(sorted(set(partner_edges["netz_quellen"]))),
            "partner_in_detailnetz": ";".join(sorted(set(partner_edges["in_detailnetz"].fillna("-")))),
        })
        for role, edges in (("kandidat", network.iloc[[candidate]]), ("partner", partner_edges)):
            features.append(edges[EDGE_COLUMNS + ["geometry"]].assign(nr=number, typ=kind, rolle=role))

    report = pd.DataFrame(rows).sort_values(["typ", "laenge_m"], ascending=[True, False])
    geojson = gpd.GeoDataFrame(pd.concat(features, ignore_index=True), crs=network.crs)
    return report, geojson


def main():
    network = gpd.read_file(NETWORK_PATH)
    overlapping = find_overlapping(network)
    # Kanten aus einem Überlappungs-Fund nicht ein zweites Mal als parallel melden
    reported = {index for _, candidate, partners, _ in overlapping for index in [candidate, *partners]}
    parallel = [finding for finding in find_parallel_to_bike_network(network) if finding[1] not in reported]
    findings = overlapping + parallel
    report, geojson = build_report(network, findings)

    report.to_csv(CSV_PATH, index=False)
    geojson.to_crs("EPSG:4326").to_file(GEOJSON_PATH, driver="GeoJSON", COORDINATE_PRECISION=6)

    for kind, group in report.groupby("typ"):
        logging.info(f"{kind}: {len(group)} Funde, {group['laenge_m'].sum() / 1000:.1f} km, "
                     f"davon gleiches Knotenpaar: {(group['gleiches_knotenpaar'] == 'ja').sum()}")
    logging.info(f"Geschrieben: {CSV_PATH}")
    logging.info(f"Geschrieben: {GEOJSON_PATH}")


if __name__ == "__main__":
    main()
