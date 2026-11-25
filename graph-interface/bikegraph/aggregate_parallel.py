"""start_aggregation.py (processing/) mit paralleler Aggregation je Kante und Richtung.

Die Aggregation behandelt jede (element_nr, ri) unabhängig (start_aggregation.aggregate_edge_group). Dieses Skript
importiert start_aggregation aus PROCESSING, ersetzt nur die Schleife in aggregate_network durch eine parallele mit
derselben Reihenfolge und ruft dann start_aggregation.process mit den üblichen Argumenten auf. Ergebnis wie
start_aggregation.py; das Skript selbst bleibt unverändert.

Aufruf (aus processing/): ../.venv/bin/python <dieses Skript> --input … --output … [--jobs 8]
"""
import argparse
import logging
import os
import sys
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.getcwd())
import geopandas as gpd  # noqa: E402
import start_aggregation as sa  # noqa: E402

JOBS = 8


def _chunk(groups):
    return [sa.aggregate_edge_group(g) for g in groups]


def aggregate_network_parallel(gdf):
    keys = ["element_nr", "ri"] if "ri" in gdf.columns else "element_nr"
    groups = [g for _, g in gdf.groupby(keys)]
    n = max(1, len(groups) // (JOBS * 8))
    chunks = [groups[i:i + n] for i in range(0, len(groups), n)]
    with ProcessPoolExecutor(JOBS) as pool:
        edges = [e for part in pool.map(_chunk, chunks) for e in part]
    result = gpd.GeoDataFrame(edges, geometry="geometry", crs=gdf.crs)
    drop = [c for c in sa.COLUMNS_TO_DROP if c in result.columns]
    if drop:
        result = result.drop(columns=drop)
    logging.info(f"Aggregation abgeschlossen (parallel, {JOBS} Prozesse): {len(gdf)} Segmente → {len(result)} Richtungs-Kanten")
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--crs", type=int, default=sa.DEFAULT_CRS)
    ap.add_argument("--data-dir", default="./data")
    ap.add_argument("--jobs", type=int, default=8)
    args = ap.parse_args()
    JOBS = args.jobs
    sa.aggregate_network = aggregate_network_parallel
    sa.print_progressbar = lambda *a, **k: None
    sa.process(args.input, args.output, args.crs, None, args.data_dir, True)
