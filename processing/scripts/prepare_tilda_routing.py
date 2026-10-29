#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
prepare_tilda_routing.py
------------------------
Bereitet den routingfähigen TILDA-Datensatz (`routing`) für das Map-Matching vor.

Schritte:
1. Join: Jede Routing-Kante bekommt die Attribute ihres Quellobjekts
   (`source_table` + `source_id` -> `id` in bikelanes / roads / roadsPathClasses).
2. Topologie: Die Wege werden an jedem Stützpunkt geteilt, den sie mit einem anderen Weg
   teilen (OSM-Knoten an Kreuzungen liegen oft mitten im Weg). Danach endet jede Kante an
   einem Knoten. Es wird nichts geometrisch repariert.
3. Zusammenhang: Nur die größte zusammenhängende Komponente wird behalten. Bricht ab, wenn
   sie zu wenig Radinfrastruktur enthält. Ausgeschlossene Kanten landen im Report.
4. Zuschnitt auf den RVN-Puffer (entfällt mit `--netz ren` oder `--ohne-rvn-zuschnitt`)
   und Übersetzung in RVN-Attribute
   (wie `translate_attributes_tilda_to_rvn.py`).

INPUT:
- data/TILDA Routing Berlin.gpkg           (Export `routing`)
- data-raw-tilda/bikelanes.fgb             (Export `bikelanes`, gleicher Verarbeitungsstand)
- data-raw-tilda/roads.fgb                 (Export `roads`, gleicher Verarbeitungsstand)
- data-raw-tilda/roadsPathClasses.fgb      (Export `roadsPathClasses`, gleicher Verarbeitungsstand)

OUTPUT (output/TILDA-routing/, mit --netz ren output/TILDA-routing-ren/):
- TILDA Routing {Bikelanes,Streets,Paths} Translated.fgb
- ausserhalb_hauptnetz.fgb                 (Kanten außerhalb der größten Komponente)
- report.json                              (Kennzahlen zu Join und Topologie)

Aufruf (aus processing/):
    python scripts/prepare_tilda_routing.py
    python scripts/prepare_tilda_routing.py --netz ren
"""

import argparse
import json
import logging
import sys
from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
import pyogrio
from shapely import LineString

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers.globals import DEFAULT_CRS  # noqa: E402
from helpers.netz import TILDA_ROUTING_DIR, add_netz_argument  # noqa: E402
from translate_attributes_tilda_to_rvn import clip_to_rvn_buffer, translate_tilda_attributes  # noqa: E402

# source_table im Routing-Datensatz -> (Rohdatei, data_source im Map-Matching)
SOURCES = {
    "bikelanes": ("bikelanes.fgb", "bikelanes"),
    "roads": ("roads.fgb", "streets"),
    "roadsPathClasses": ("roadsPathClasses.fgb", "paths"),
}
# Stützpunkte gelten bis auf 1e-7 Grad (ca. 1 cm) als identisch (Gleitkomma-Rauschen).
COORD_DECIMALS = 7


def join_source_attributes(routing: gpd.GeoDataFrame, raw_dir: Path, max_missing_share: float) -> tuple[gpd.GeoDataFrame, dict]:
    """Hängt an jede Routing-Kante die Attribute ihres Quellobjekts an.

    Routing-Attribute behalten das Präfix `routing_`. Fehlt das Quellobjekt, werden
    gleichnamige Routing-Attribute als Ersatz übernommen.
    """
    routing = routing.rename(columns={c: f"routing_{c}" for c in routing.columns if c != "geometry"})
    parts, stats = [], {}
    for source_table, (filename, _) in SOURCES.items():
        src = pyogrio.read_dataframe(raw_dir / filename, read_geometry=False)
        if src["id"].duplicated().any():
            raise ValueError(f"{filename}: `id` ist nicht eindeutig")
        sub = routing[routing["routing_source_table"] == source_table]
        joined = sub.merge(src, how="left", left_on="routing_source_id", right_on="id", indicator=True)
        missing = joined["_merge"] == "left_only"
        length = joined["routing_length"].astype(float)
        stats[source_table] = {
            "kanten": int(len(joined)),
            "ohne_quellobjekt": int(missing.sum()),
            "ohne_quellobjekt_km": round(float(length[missing].sum()) / 1000, 1),
            "beispiele": joined.loc[missing, "routing_source_id"].head(5).tolist(),
        }
        share = missing.mean() if len(joined) else 0.0
        if share > max_missing_share:
            raise ValueError(
                f"{source_table}: {share:.1%} der Kanten ohne Quellobjekt in {filename}. "
                "Stammen Routing- und Quelldaten aus demselben Verarbeitungslauf?"
            )
        if missing.any():
            logging.warning(f"{source_table}: {missing.sum()} Kanten ohne Quellobjekt, nutze Routing-Attribute als Ersatz")
            joined.loc[missing, "id"] = joined.loc[missing, "routing_source_id"]
            for col in src.columns:
                if f"routing_{col}" in joined.columns:
                    joined.loc[missing, col] = joined.loc[missing, f"routing_{col}"]
        # Wege/Straßen ohne `oneway`-Tag: Das Routing-`oneway` sagt, ob gegen die Linie gefahren werden darf.
        joined["oneway"] = joined["oneway"].fillna(joined["routing_oneway"]) if "oneway" in joined else joined["routing_oneway"]
        parts.append(joined.drop(columns="_merge"))
    out = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), geometry="geometry", crs=routing.crs)
    return out, stats


def split_at_shared_vertices(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Teilt jeden Weg an Stützpunkten, die Knoten sind (Endpunkt oder von mehreren Wegen genutzt)."""
    keyed = [[tuple(p) for p in np.round(np.asarray(g.coords), COORD_DECIMALS)] for g in gdf.geometry]
    usage: dict[tuple, int] = {}
    for coords in keyed:
        for p in set(coords):
            usage[p] = usage.get(p, 0) + 1
        for p in (coords[0], coords[-1]):
            usage[p] = usage.get(p, 0) + 1  # Endpunkte sind immer Knoten
    node_id: dict[tuple, int] = {}

    def node(p: tuple) -> int:
        return node_id.setdefault(p, len(node_id))

    rows, geoms = [], []
    for i, (coords, geom) in enumerate(zip(keyed, gdf.geometry)):
        raw = np.asarray(geom.coords)
        start, seg = 0, 0
        for j in range(1, len(coords)):
            if j == len(coords) - 1 or usage[coords[j]] > 1:
                if coords[start] != coords[j] or j - start > 1:
                    rows.append((i, seg, node(coords[start]), node(coords[j])))
                    geoms.append(LineString(raw[start : j + 1]))
                    seg += 1
                start = j
    idx, seg_idx, from_node, to_node = map(np.asarray, zip(*rows))
    out = gdf.iloc[idx].reset_index(drop=True)
    out["seg_idx"], out["from_node"], out["to_node"] = seg_idx, from_node, to_node
    return gpd.GeoDataFrame(out, geometry=geoms, crs=gdf.crs)


def main_component(segments: gpd.GeoDataFrame) -> np.ndarray:
    """Maske der Kanten in der größten zusammenhängenden Komponente (nach Länge)."""
    graph = nx.Graph()
    graph.add_edges_from(zip(segments["from_node"], segments["to_node"]))
    comp_of = {n: c for c, nodes in enumerate(nx.connected_components(graph)) for n in nodes}
    comp = segments["from_node"].map(comp_of)
    largest = segments["_len_m"].groupby(comp).sum().idxmax()
    return (comp == largest).to_numpy()


def main():
    parser = argparse.ArgumentParser(description="Bereitet den TILDA-Routing-Datensatz für das Map-Matching vor")
    parser.add_argument("--routing", default="data/TILDA Routing Berlin.gpkg")
    parser.add_argument("--raw-dir", default="data-raw-tilda", help="Exporte bikelanes/roads/roadsPathClasses")
    parser.add_argument("--data-dir", default="data", help="enthält das RVN für den Puffer-Zuschnitt")
    parser.add_argument("--output-dir", help="Standard: output/TILDA-routing bzw. output/TILDA-routing-ren (--netz ren)")
    parser.add_argument("--max-missing-share", type=float, default=0.01, help="max. Anteil Kanten ohne Quellobjekt je Tabelle")
    parser.add_argument("--min-bikelane-share", type=float, default=0.95, help="min. Anteil Radinfrastruktur (km) im Hauptnetz")
    parser.add_argument("--ohne-rvn-zuschnitt", action="store_true", help="ganz Berlin behalten (bei --netz ren immer)")
    add_netz_argument(parser)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    out_dir = Path(args.output_dir or TILDA_ROUTING_DIR[args.netz])
    out_dir.mkdir(parents=True, exist_ok=True)

    routing = gpd.read_file(args.routing)
    logging.info(f"Routing: {len(routing)} Kanten aus {args.routing}")
    joined, join_stats = join_source_attributes(routing, Path(args.raw_dir), args.max_missing_share)

    segments = split_at_shared_vertices(joined)
    segments["_len_m"] = segments.to_crs(DEFAULT_CRS).length
    logging.info(f"Topologie: {len(joined)} Wege -> {len(segments)} Kanten zwischen Knoten")

    in_main = main_component(segments)
    km = segments.groupby(["routing_source_table", in_main])["_len_m"].sum() / 1000
    topo_stats = {
        st: {"hauptnetz_km": round(float(km.get((st, True), 0)), 1), "ausserhalb_km": round(float(km.get((st, False), 0)), 1)}
        for st in SOURCES
    }
    bike = topo_stats["bikelanes"]
    bike_share = bike["hauptnetz_km"] / max(bike["hauptnetz_km"] + bike["ausserhalb_km"], 1e-9)
    logging.info(f"Hauptnetz: {json.dumps(topo_stats)}; Radinfrastruktur im Hauptnetz: {bike_share:.1%}")
    outside = segments.loc[~in_main, ["routing_id", "routing_source_table", "category", "road", "seg_idx", "_len_m", "geometry"]]
    outside.to_file(out_dir / "ausserhalb_hauptnetz.fgb", driver="FlatGeobuf")
    if bike_share < args.min_bikelane_share:
        raise SystemExit(f"Nur {bike_share:.1%} der Radinfrastruktur im Hauptnetz (min. {args.min_bikelane_share:.0%}). Abbruch.")

    segments = segments[in_main].to_crs(DEFAULT_CRS)
    if args.netz == "rvn" and not args.ohne_rvn_zuschnitt:
        segments = clip_to_rvn_buffer(segments, args.data_dir, DEFAULT_CRS)
    segments = segments.drop(columns="_len_m")
    for source_table, (_, data_source) in SOURCES.items():
        part = segments[segments["routing_source_table"] == source_table].reset_index(drop=True)
        translated = translate_tilda_attributes(part, data_source)
        # Präfix-Doppelung aus der Übersetzung rückgängig machen (routing_* -> tilda_routing_*)
        translated = translated.rename(columns=lambda c: c.removeprefix("tilda_") if c.startswith("tilda_routing_") else c)
        translated = translated.rename(columns={"tilda_seg_idx": "seg_idx", "tilda_from_node": "from_node", "tilda_to_node": "to_node"})
        path = out_dir / f"TILDA Routing {data_source.title()} Translated.fgb"
        path.unlink(missing_ok=True)
        translated.to_file(path, driver="FlatGeobuf")
        logging.info(f"✔ {path} ({len(translated)} Kanten)")

    report = {"join": join_stats, "topologie": topo_stats, "radinfrastruktur_im_hauptnetz": round(bike_share, 4)}
    (out_dir / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
