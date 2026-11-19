"""Cells for quality assurance (QA) in TILDA: one area per network edge.

For each cell, QA in TILDA compares the meters of cycling infrastructure with a frozen state. To
count only ways along the network, each cell is the strip around one edge (`element_nr`, both
directions together), at most `--buffer` meters wide. Where the strips of two edges meet (at nodes,
at parallel edges), each point belongs to the nearest edge (Voronoi). So the cells of one network do
not overlap.

With `--district`, the cells are built for the QA view of one district delivery: the whole network
is always split, and only the edges of the district are kept. So the cells at the district border
have the same shape as in the whole network.

Output: `output/<table>.gpkg` for viewing and `output/<table>.sql` for tilda-geo `data-schema/`
(text primary key `id` = `element_nr`, `geom` MultiPolygon EPSG:4326, `name` = street name). With
`--data-schema`, the SQL file is also written to `../tilda-geo/data-schema/<table>/`. Next steps:
README.md.

  .venv/bin/python tilda-qa/build_qa_cells.py --network rvn --data-schema
  .venv/bin/python tilda-qa/build_qa_cells.py --network ren --district 7 --date 2026-12-01 --data-schema
"""

import argparse
import gzip
import os
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = Path(__file__).resolve().parent / "output"
METRIC_CRS = 25833
# Distance between the sample points for the Voronoi split. Smaller makes the borders between two
# edges smoother, but takes more time.
POINT_SPACING_M = 2.0
# Afterwards the borders are simplified together (neighbors keep identical borders).
SIMPLIFY_TOLERANCE_M = 1.0


def tilda_static_data_dir():
    # Like bearbeitungsstand/update.sh: sibling folder, otherwise set by environment variable.
    return Path(os.environ.get("TILDA_STATIC_DATA_DIR", ROOT.parent / "tilda-static-data"))


def tilda_geo_dir():
    return Path(os.environ.get("TILDA_GEO_DIR", ROOT.parent / "tilda-geo"))


# Per network: input, table in tilda-geo and source note for the spec.yaml.
NETWORKS = {
    "rvn": {
        "input": lambda: tilda_static_data_dir() / "geojson" / "region-infravelo"
        / "infravelo-datensatz-c-fortlaufend" / "aggregated_rvn_final.geojson.gz",
        "table": "infravelo_qa_2026_cells_rvn",
        "description": "Radvorrangnetz, result 2025 (dataset C, tilda-static-data "
        "region-infravelo/infravelo-datensatz-c-fortlaufend)",
    },
    "ren": {
        "input": lambda: ROOT / "ren-network" / "output" / "ren_netz.gpkg",
        "table": "infravelo_qa_2026_cells_ren",
        "description": "REN+ (ren-network/output/ren_netz.gpkg, after netzanpassungen/apply_app_result.py)",
    },
}


def table_name(network, district, date):
    if district is None:
        return NETWORKS[network]["table"]
    return f"infravelo_qa_{date.replace('-', '_')}_cells_{network}_bezirk{district:02d}"


def read_network(path):
    if path.suffix == ".gz":
        with gzip.open(path) as file:
            lines = gpd.read_file(file)
    else:
        lines = gpd.read_file(path)
    missing = {"element_nr", "geometry"} - set(lines.columns)
    if missing:
        sys.exit(f"{path}: missing columns: {sorted(missing)}")
    lines = lines.to_crs(METRIC_CRS)
    lines["element_nr"] = lines["element_nr"].astype(str)
    if "strassenname" not in lines.columns:
        lines["strassenname"] = None
    district_column = next((c for c in lines.columns if c.lower() == "bezirksnummer"), None)
    lines["district"] = pd.to_numeric(lines[district_column], errors="coerce") if district_column else np.nan

    # One row per edge: the directions (ri) mostly have the same geometry. If a few differ, the
    # union counts.
    edges = lines.groupby("element_nr").agg(
        geometry=("geometry", lambda parts: shapely.line_merge(shapely.union_all(list(parts)))),
        strassenname=("strassenname", lambda names: next((n for n in names if n), None)),
        district=("district", "first"),
    )
    return gpd.GeoDataFrame(edges, geometry="geometry", crs=METRIC_CRS).reset_index()


def sample_points(edges):
    """Sample points along each edge, without the end points: they lie on the nodes and belong to
    several edges."""
    coords, owner = [], []
    for index, line in enumerate(edges.geometry):
        for part in shapely.get_parts(line):
            length = part.length
            if length <= 0:
                continue
            steps = max(int(length // POINT_SPACING_M), 1)
            distances = (np.arange(steps) + 0.5) * (length / steps)
            coords.append(shapely.get_coordinates(shapely.line_interpolate_point(part, distances)))
            owner.append(np.full(len(distances), index))
    return np.vstack(coords), np.concatenate(owner)


def polygonal(geometries):
    """Only the polygon parts of each geometry, as MultiPolygon (empty if none remain)."""
    result = []
    for geometry in geometries:
        parts = shapely.get_parts(shapely.get_parts(geometry))
        parts = parts[(shapely.get_type_id(parts) == 3) & (shapely.area(parts) > 0)]
        result.append(shapely.multipolygons(parts))
    return np.array(result, dtype=object)


def build_cells(edges, buffer_m):
    coords, owner = sample_points(edges)
    # Identical sample points (edges that lie on each other) make the assignment ambiguous.
    _, first = np.unique(coords.round(2), axis=0, return_index=True)
    coords, owner = coords[first], owner[first]

    points = shapely.multipoints(coords)
    extent = shapely.buffer(shapely.envelope(points), buffer_m * 4)
    voronoi = shapely.get_parts(shapely.voronoi_polygons(points, extend_to=extent, ordered=True))
    if len(voronoi) != len(coords):
        sys.exit(f"Voronoi returned {len(voronoi)} areas for {len(coords)} points")

    owned = pd.Series(list(voronoi)).groupby(owner).agg(lambda parts: shapely.union_all(list(parts)))
    regions = np.array([owned.get(i) for i in range(len(edges))], dtype=object)
    strips = shapely.buffer(edges.geometry.values, buffer_m)
    cells = shapely.intersection(regions, strips)
    cells = polygonal(shapely.make_valid(cells))
    # Simplify shared borders together: neighbors stay gap-free and overlap-free.
    cells = polygonal(shapely.make_valid(shapely.coverage_simplify(cells, SIMPLIFY_TOLERANCE_M)))
    return gpd.GeoDataFrame(
        {"id": edges["element_nr"], "name": edges["strassenname"], "district": edges["district"]},
        geometry=cells, crs=METRIC_CRS,
    )


def check(cells, edges, buffer_m):
    empty = cells[cells.geometry.is_empty]
    if len(empty):
        sys.exit(f"{len(empty)} edges without a cell, e.g. {list(empty['id'][:5])}")
    invalid = int((~cells.geometry.is_valid).sum())
    if invalid:
        sys.exit(f"{invalid} invalid cells")
    if cells["id"].duplicated().any():
        sys.exit("element_nr is duplicated")
    area_sum = cells.geometry.area.sum()
    overlap = area_sum - shapely.union_all(cells.geometry.values).area
    if overlap > 1:
        sys.exit(f"Cells overlap by {overlap:.1f} m²")
    # Each edge lies almost entirely in its own cell (rest: sections that cover another edge, and
    # rounding at the nodes).
    inside = shapely.length(shapely.intersection(edges.geometry.values, cells.geometry.values))
    share = inside.sum() / edges.geometry.length.sum()
    print(f"  {len(cells)} cells, {area_sum / 1e6:.1f} km², overlap {overlap:.2f} m², "
          f"{share:.1%} of the edge length in its own cell, buffer {buffer_m} m")
    if share < 0.98:
        sys.exit("Less than 98 % of the edge length lies in its own cell")


def sql_text(value):
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "\\N"
    return str(value).replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")


def write_sql(cells, table, path, source_note):
    wgs84 = cells.to_crs(4326)
    wkb = shapely.to_wkb(shapely.set_srid(wgs84.geometry.values, 4326), hex=True, include_srid=True)
    with path.open("w") as file:
        file.write("-- QA cells for tilda-geo, created by infravelo-radnetz tilda-qa/build_qa_cells.py\n")
        file.write(f"-- from: {source_note}\n")
        file.write(f"DROP TABLE IF EXISTS data.{table};\n")
        file.write(f"CREATE TABLE data.{table} (id text PRIMARY KEY, geom public.geometry(MultiPolygon, 4326), name character varying);\n")
        file.write(f"COPY data.{table} (id, geom, name) FROM stdin;\n")
        for cell_id, geom, name in zip(wgs84["id"], wkb, wgs84["name"]):
            file.write(f"{sql_text(cell_id)}\t{geom}\t{sql_text(name)}\n")
        file.write("\\.\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--network", required=True, choices=sorted(NETWORKS))
    parser.add_argument("--input", type=Path, help="network file instead of the default of the network")
    parser.add_argument("--buffer", type=float, default=25.0, help="largest width per side in meters")
    parser.add_argument("--district", type=int, help="only the edges of this district (Bezirksnummer 1-12)")
    parser.add_argument("--date", help="delivery date YYYY-MM-DD, part of the table name (with --district)")
    parser.add_argument("--data-schema", action="store_true",
                        help="also write the SQL file to ../tilda-geo/data-schema/<table>/")
    args = parser.parse_args()

    network = NETWORKS[args.network]
    source = args.input or network["input"]()
    if args.district is not None and not (args.date and len(args.date) == 10):
        sys.exit("--district needs --date YYYY-MM-DD")
    table = table_name(args.network, args.district, args.date)
    source_note = f"{network['description']}: {source.name}" if not args.input else str(source)
    if args.district is not None:
        source_note += f", district {args.district:02d}, date {args.date}"
    if not source.exists():
        sys.exit(f"Input missing: {source}")

    print(f"1. Read network: {source}")
    edges = read_network(source)
    print(f"  {len(edges)} edges, {edges.geometry.length.sum() / 1000:.1f} km")

    print("2. Build cells")
    cells = build_cells(edges, args.buffer)
    check(cells, edges, args.buffer)
    if args.district is not None:
        cells = cells[cells["district"] == args.district]
        if cells.empty:
            sys.exit(f"No edges in district {args.district} (column Bezirksnummer)")
        print(f"  District {args.district:02d}: {len(cells)} cells")
    cells = cells.drop(columns="district")

    print("3. Write")
    OUTPUT_DIR.mkdir(exist_ok=True)
    cells.to_crs(4326).to_file(OUTPUT_DIR / f"{table}.gpkg", layer=table, driver="GPKG")
    sql_path = OUTPUT_DIR / f"{table}.sql"
    write_sql(cells, table, sql_path, source_note)
    print(f"  {OUTPUT_DIR / f'{table}.gpkg'}\n  {sql_path}")
    if args.data_schema:
        target = tilda_geo_dir() / "data-schema" / table / f"{table}.sql"
        if not target.parent.parent.exists():
            sys.exit(f"tilda-geo not found: {target.parent.parent} (set TILDA_GEO_DIR)")
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(sql_path.read_bytes())
        print(f"  {target}")


if __name__ == "__main__":
    main()
