#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyse_einrichtungsfahrbahnen.py
--------------------------------------------------------------------
Sucht ein Muster, an dem man RVN-Kanten erkennt, die nur in einer Richtung befahrbar sind
(Richtungsfahrbahnen, Einbahn-Ringe). Grundlage ist die alte manuelle Liste
`data/opposite_edge_overwrite_element_nr.txt` und die Referenz des Altverfahrens.

Merkmale je RVN-Kante:
- Detailnetz: verkehrsrichtung (nach data/rvn_korrekturen.csv), strassenklasse
- Topologie: parallele Detailnetz-Kante gleichen Namens in 3–60 m Abstand ("Zwilling"),
  alternativer Pfad gleichen Namens zwischen den Endknoten ("Ring")
- TILDA-Straßen entlang der Kante (Puffer 12 m, gleiche Ausrichtung): Längenanteil oneway,
  yes_dual_carriageway, oneway_bicycle=no
- Referenz: was die alte Referenz in ri=1 ausgibt (Gruppe A/B/C, siehe unten)

Gruppen (nur R/G-Kanten):
- A: ri=1 fehlt in der Referenz, ist "Keine Radinfrastruktur" oder die Kante steht in der Liste
- B: Referenz hat in ri=1 überwiegend einen Zweirichtungsweg
- C: Referenz hat in ri=1 einen Einrichtungsweg (Verdacht: Gegenfahrbahn gematcht)

Regel (Plan Stufe 1): ri=1 entfällt bei R/G ohne Freigabe in Gegenrichtung und ohne Zweirichtungsweg.
`pruefen` markiert die Kanten, bei denen Regel und Referenz sich widersprechen.

Ergebnisse und Einordnung: processing/map-matching/docs/einrichtungsfahrbahnen.md, Abschnitt 2.4

INPUT (relativ zu processing/):
- output/rvn/vorrangnetz_details_combined_rvn.fgb
- data/Berlin Straßenabschnitte Detailnetz 2025-11-17.fgb
- data/TILDA Straßen Berlin.fgb
- data/opposite_edge_overwrite_element_nr.txt
- output/reference-legacy/snapping_network_enriched.fgb
- output/map-matching/network_enriched_hmm.fgb (optional, zum Vergleich)

OUTPUT:
- output/analysis/einrichtungsfahrbahnen.fgb (RVN-Kanten mit Merkmalen, für QGIS)
- output/analysis/einrichtungsfahrbahnen.csv

Aufruf (aus processing/):
    ../.venv/bin/python validation/analyse_einrichtungsfahrbahnen.py
"""

import logging
from collections import defaultdict
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.ops import linemerge

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

PROCESSING = Path(__file__).resolve().parents[1]
RVN = PROCESSING / "output/rvn/vorrangnetz_details_combined_rvn.fgb"
DETAILNETZ = PROCESSING / "data/Berlin Straßenabschnitte Detailnetz 2025-11-17.fgb"
TILDA_STREETS = PROCESSING / "data/TILDA Straßen Berlin.fgb"
LIST = PROCESSING / "data/opposite_edge_overwrite_element_nr.txt"
REFERENCE = PROCESSING / "output/reference-legacy/snapping_network_enriched.fgb"
HMM = PROCESSING / "output/map-matching/network_enriched_hmm.fgb"
OUT_DIR = PROCESSING / "output/analysis"

NO_INFRA = "Keine Radinfrastruktur vorhanden"
NOT_CARRYING = {NO_INFRA, "Kreuzungsweg"}
MODES = {"true": "gegen", "ri1": "gegen", "gegen": "gegen", "gegenrichtung": "gegen",
         "hinrichtung": "hin", "ri0": "hin", "hin": "hin"}

# Schwellen
TWIN_MIN_M, TWIN_MAX_M = 3.0, 60.0
TILDA_BUFFER_M = 12.0
ONEWAY_SHARE = 0.8
CONTRAFLOW_SHARE = 0.3


def as_line(g):
    if g.geom_type == "MultiLineString":
        m = linemerge(g)
        g = m if m.geom_type == "LineString" else max(g.geoms, key=lambda x: x.length)
    return g


def unit_vector(g):
    g = as_line(g)
    v = np.array(g.coords[-1]) - np.array(g.coords[0])
    n = np.linalg.norm(v)
    return v / n if n > 0 else v


def load_list():
    entries = {}
    for line in LIST.read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        parts = line.split("|")
        mode = parts[1].strip().lower() if len(parts) > 1 else "remove"
        entries[parts[0].strip()] = MODES.get(mode, "beide" if mode.startswith(("beide", "both", "all")) else mode)
    return entries


class SameNameGraph:
    """Ungerichteter Detailnetz-Graph für alternative Pfade mit gleichem Straßennamen."""

    def __init__(self, det):
        self.det = det
        self.adj = defaultdict(list)
        for i, r in det.iterrows():
            self.adj[r.beginnt_bei_vp].append((r.endet_bei_vp, i))
            self.adj[r.endet_bei_vp].append((r.beginnt_bei_vp, i))

    def alt_path_length(self, src, dst, name, skip, max_len, max_depth=4):
        best = None
        stack = [(src, 0.0, 0, frozenset([skip]))]
        while stack:
            node, length, depth, used = stack.pop()
            if length > max_len or depth > max_depth:
                continue
            if node == dst and depth > 0:
                best = length if best is None else min(best, length)
                continue
            for nxt, ei in self.adj[node]:
                if ei in used or self.det.at[ei, "strassenname"] != name:
                    continue
                stack.append((nxt, length + self.det.at[ei, "geometry"].length, depth + 1, used | {ei}))
        return best


def topology_features(g, edge, det, det_by_el, graph):
    rec = {}
    pts = [g.interpolate(f, normalized=True) for f in np.linspace(0.1, 0.9, 9)]
    ev = unit_vector(g)
    twin = None
    for j in det.sindex.query(g.buffer(TWIN_MAX_M)):
        c = det.iloc[j]
        if c.element_nr == edge.element_nr or c.strassenname != edge.strassenname:
            continue
        if abs(np.dot(ev, unit_vector(c.geometry))) < 0.8:
            continue
        cl = c.geometry
        if np.mean([0 < cl.project(p) < cl.length for p in pts]) < 0.5:
            continue
        dist = float(np.median([cl.distance(p) for p in pts]))
        if TWIN_MIN_M <= dist <= TWIN_MAX_M and (twin is None or dist < twin[0]):
            twin = (dist, c.element_nr)
    if twin:
        rec.update(twin_dist=twin[0], twin_el=twin[1])
    if edge.element_nr in det_by_el:
        alt = graph.alt_path_length(edge.endet_bei_vp, edge.beginnt_bei_vp, edge.strassenname,
                                    det_by_el[edge.element_nr], 4 * g.length + 50)
        rec["ring_ratio"] = alt / g.length if alt else np.nan
    return rec


def tilda_features(g, tilda):
    ev = unit_vector(g)
    buf = g.buffer(TILDA_BUFFER_M)
    shares = defaultdict(float)
    for j in tilda.sindex.query(buf):
        t = tilda.iloc[j]
        part = t.geometry.intersection(buf)
        if part.length < 2 or abs(np.dot(ev, unit_vector(part))) < 0.7:
            continue
        if t.oneway in ("yes", "yes_dual_carriageway"):
            shares["tilda_oneway"] += part.length
        if t.oneway == "yes_dual_carriageway":
            shares["tilda_dual"] += part.length
        if t.oneway_bicycle == "no":
            shares["tilda_contraflow"] += part.length
    return {k: shares[k] / g.length for k in ("tilda_oneway", "tilda_dual", "tilda_contraflow")}


def reference_group(el, ref, listed):
    s1 = ref[(ref.element_nr == el) & (ref.ri == 1)]
    if listed in ("remove", "gegen") or len(s1) == 0:
        return "A"
    total = s1.L.sum()
    if s1[s1.fuehr.isin(NOT_CARRYING)].L.sum() / total > 0.8:
        return "A"
    two_way = s1[(s1.verkehrsri == "Zweirichtungsverkehr") & ~s1.fuehr.isin(NOT_CARRYING)].L.sum() / total
    return "B" if two_way > 0.5 else "C"


def main():
    logger.info("Lade Daten ...")
    rvn = gpd.read_file(RVN)
    rvn["geometry"] = rvn.geometry.apply(as_line)
    det = gpd.read_file(DETAILNETZ)
    det["geometry"] = det.geometry.apply(as_line)
    det_by_el = dict(zip(det.element_nr, det.index))
    tilda = gpd.read_file(TILDA_STREETS, columns=["oneway", "oneway_bicycle", "geometry"])
    tilda["geometry"] = tilda.geometry.apply(as_line)
    listed = load_list()
    ref = gpd.read_file(REFERENCE)
    ref["L"] = ref.geometry.length
    ref_dirs = ref.groupby("element_nr").ri.apply(lambda s: "".join(map(str, sorted(set(s)))))
    hmm_dirs = None
    if HMM.exists():
        hmm = gpd.read_file(HMM, columns=["element_nr", "ri"])
        hmm_dirs = hmm.groupby("element_nr").ri.apply(lambda s: "".join(map(str, sorted(set(s)))))

    graph = SameNameGraph(det)
    logger.info(f"Berechne Merkmale für {len(rvn)} RVN-Kanten ...")
    rows = []
    for _, edge in rvn.iterrows():
        g = edge.geometry
        rec = dict(element_nr=edge.element_nr, strassenname=edge.strassenname, verkehrsrichtung=edge.verkehrsrichtung,
                   edge_source=edge.edge_source, laenge=g.length, liste=listed.get(edge.element_nr, "-"),
                   ref_richtungen=ref_dirs.get(edge.element_nr, ""),
                   hmm_richtungen=hmm_dirs.get(edge.element_nr, "") if hmm_dirs is not None else "")
        rec.update(topology_features(g, edge, det, det_by_el, graph))
        rec.update(tilda_features(g, tilda))
        rows.append(rec)
    df = pd.DataFrame(rows)

    oneway_edge = df.verkehrsrichtung.isin(["R", "G"])
    contraflow = df.tilda_contraflow > CONTRAFLOW_SHARE
    df["gruppe"] = ""
    df.loc[oneway_edge, "gruppe"] = [reference_group(el, ref, l) for el, l in zip(df[oneway_edge].element_nr, df[oneway_edge].liste)]
    df["ri1_entfaellt"] = oneway_edge & ~contraflow & (df.gruppe != "B")
    df["pruefen"] = df.ri1_entfaellt & (df.gruppe == "C")

    # Kurzauswertung
    rg = df[oneway_edge]
    logger.info(f"R/G-Kanten: {len(rg)}, davon Liste 'remove': {(rg.liste == 'remove').sum()}")
    logger.info("Gruppen nach TILDA-Einbahn:\n" + pd.crosstab(
        np.where(rg.tilda_contraflow > CONTRAFLOW_SHARE, "Freigabe Gegenrichtung",
                 np.where(rg.tilda_oneway > ONEWAY_SHARE, "Einbahn", "kaum Einbahn")), rg.gruppe).to_string())
    logger.info(f"Regel: ri=1 entfällt bei {df.ri1_entfaellt.sum()} Kanten, davon {df.pruefen.sum()} im Widerspruch zur Referenz (pruefen)")
    b_listed = df[(df.verkehrsrichtung == "B") & (df.liste == "remove")]
    if len(b_listed):
        logger.warning(f"{len(b_listed)} B-Kanten mit Listeneintrag 'remove' – Kandidaten für data/rvn_korrekturen.csv: "
                       f"{', '.join(b_listed.element_nr)}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    gdf = gpd.GeoDataFrame(df, geometry=rvn.geometry.values, crs=rvn.crs)
    gdf.to_file(OUT_DIR / "einrichtungsfahrbahnen.fgb", driver="FlatGeobuf")
    df.to_csv(OUT_DIR / "einrichtungsfahrbahnen.csv", index=False)
    logger.info(f"Geschrieben: {OUT_DIR / 'einrichtungsfahrbahnen.fgb'} und .csv")


if __name__ == "__main__":
    main()
