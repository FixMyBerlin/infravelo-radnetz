"""Reference values for a QA view in TILDA: the meters of cycling infrastructure per cell at the
state of a delivery.

Reads a TILDA export `bikelanes` (default: `processing/data-raw-tilda/bikelanes.fgb`, the state the
delivery was calculated from) into a local tilda-geo database and measures it per cell of the cell
table with the QA functions of tilda-geo (`processing/qa/qa_functions.sql`), exactly as the nightly
QA measures the current data. Result: `data.<target>` (area_id, indicator_key, value_key, amount)
and `output/<target>.sql` for tilda-geo `data-schema/`.

  .venv/bin/python tilda-qa/build_qa_reference.py --cells data.infravelo_qa_2026_cells_rvn \\
    --input <export>.fgb --geometry side --data-schema

Requires: a local tilda-geo database (`ENVIRONMENT=development` in tilda-geo `.env`) with the
measure and QA functions and the cell table (`bun run data-schema-load`), `ogr2ogr`, `psql`.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUTPUT_DIR = HERE / "output"
SCHEMA = "_tilda_qa_reference"
# More than any config uses today, so indicators can be added later without a new reference.
INDICATORS = "total,category,oneway,surface,smoothness,traffic_sign"


def tilda_geo_dir():
    return Path(os.environ.get("TILDA_GEO_DIR", ROOT.parent / "tilda-geo"))


def read_env(path):
    values = {}
    if path.exists():
        for line in path.read_text().splitlines():
            match = re.match(r"^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$", line)
            if match:
                values[match[1]] = match[2].strip().strip('"').strip("'")
    return values


def database_url():
    env = read_env(tilda_geo_dir() / ".env") | {k: v for k, v in os.environ.items() if k.startswith("DATABASE_")}
    if env.get("ENVIRONMENT", os.environ.get("ENVIRONMENT", "")).strip().lower() != "development":
        sys.exit("Abort: ENVIRONMENT in tilda-geo/.env must be development.")
    missing = [k for k in ("DATABASE_HOST", "DATABASE_USER", "DATABASE_PASSWORD", "DATABASE_NAME") if not env.get(k)]
    if missing:
        sys.exit(f"Missing in {tilda_geo_dir() / '.env'}: {', '.join(missing)} (or set TILDA_GEO_DIR)")
    port = env.get("DATABASE_PORT", "5432")
    return (f"postgresql://{quote(env['DATABASE_USER'])}:{quote(env['DATABASE_PASSWORD'])}"
            f"@{env['DATABASE_HOST']}:{port}/{env['DATABASE_NAME']}")


def run(args, capture=False):
    masked = [re.sub(r":[^:@/]+@", ":***@", a) for a in args]
    masked = [re.sub(r"password=\S+", "password=***", a) for a in masked]
    print("  $", " ".join(masked))
    result = subprocess.run(args, capture_output=capture, text=True)
    if result.returncode != 0:
        sys.exit(f"Failed: {args[0]}\n{result.stderr if capture else ''}")
    return result.stdout


def psql(url, sql):
    return run(["psql", url, "-X", "-A", "-t", "-F", "|", "-v", "ON_ERROR_STOP=1", "-c", sql], capture=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--cells", required=True, help="cell table, e.g. data.infravelo_qa_2026_cells_rvn")
    parser.add_argument("--input", type=Path, default=ROOT / "processing" / "data-raw-tilda" / "bikelanes.fgb",
                        help="TILDA export bikelanes (fgb/gpkg)")
    parser.add_argument("--geometry", required=True, choices=["centerline", "side"],
                        help="centerline: export on the road centerline with `offset` (TILDA since "
                             "August 2026), moved to the side like in the nightly QA; side: export "
                             "already moved to the side (until August 2026)")
    parser.add_argument("--target", help="name of the reference table (default: the cell table with _cells_ → _reference_)")
    parser.add_argument("--indicators", default=INDICATORS)
    parser.add_argument("--data-schema", action="store_true",
                        help="also write the SQL file to ../tilda-geo/data-schema/<target>/")
    parser.add_argument("--keep-schema", action="store_true",
                        help=f"keep schema {SCHEMA} with the loaded export for inspection")
    args = parser.parse_args()

    if not re.fullmatch(r"data\.[a-z0-9_]+", args.cells):
        sys.exit("--cells must be data.<table>")
    target = args.target or args.cells.removeprefix("data.").replace("_cells_", "_reference_")
    if target == args.cells.removeprefix("data.") or not re.fullmatch(r"[a-z0-9_]+", target):
        sys.exit("Target name unclear, please pass --target")
    if not args.input.exists():
        sys.exit(f"Export missing: {args.input}")
    url = database_url()
    indicators = json.dumps([{"key": key.strip()} for key in args.indicators.split(",")])

    ready = psql(url, f"""SELECT to_regprocedure('tilda_qa_measure()') IS NOT NULL
        AND to_regprocedure('tilda_qa_prepare_config(text, jsonb)') IS NOT NULL
        AND to_regprocedure('tilda_qa_side_lines(geometry, numeric)') IS NOT NULL
        AND to_regclass('{args.cells}') IS NOT NULL""").strip()
    if ready != "t":
        sys.exit(f"The database needs the measure and QA functions of tilda-geo (processing/measure, "
                 f"processing/qa, since 2026-11-18) and {args.cells}.")

    print("1. Load export")
    psql(url, f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE; CREATE SCHEMA {SCHEMA};")
    pg = re.match(r"postgresql://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)", url)
    from urllib.parse import unquote
    run(["ogr2ogr", "-f", "PostgreSQL",
         f"PG:host={pg[3]} port={pg[4]} dbname={pg[5]} user={unquote(pg[1])} password={unquote(pg[2])}",
         str(args.input), "-nln", f"{SCHEMA}.bikelanes", "-nlt", "GEOMETRY",
         "-lco", "GEOMETRY_NAME=geom", "-lco", "FID=ogc_fid"])

    print("2. Amount per cell, indicator and value")
    run(["psql", url, "-X", "-q", "-v", "ON_ERROR_STOP=1",
         "-v", f"features_file={HERE / 'sql' / 'bikelanes.sql'}",
         "-v", f"shift={'true' if args.geometry == 'centerline' else 'false'}",
         "-v", f"area_table={args.cells}", "-v", f"indicators={indicators}", "-v", f"target={target}",
         "-f", str(HERE / "sql" / "reference.sql")])

    print("3. Compare with the export")
    total = float(psql(url, f"SELECT sum(COALESCE(length::float, ST_Length(ST_Transform(geom, 5243)))) FROM {SCHEMA}.bikelanes"))
    rows = [line.split("|") for line in psql(url, f"""SELECT indicator_key, count(DISTINCT area_id), count(*), round(sum(amount))
        FROM data.{target} GROUP BY 1 ORDER BY 1""").splitlines() if line]
    cells = psql(url, f"SELECT count(*) FROM {args.cells}").strip()
    for key, with_data, count, amount in rows:
        print(f"  {key:14} {with_data:>6} cells with data  {count:>7} rows  {amount:>10} m")
    amounts = {amount for *_, amount in rows}
    inside = float(next(iter(amounts))) if rows else 0.0
    print(f"  Export {total:,.0f} m, of which in the {cells} cells {inside:,.0f} m ({inside / total:.0%})")
    if len(amounts) != 1:
        sys.exit("The indicators add up to different totals")

    print("4. Write SQL file for data-schema")
    OUTPUT_DIR.mkdir(exist_ok=True)
    data = psql(url, f"COPY (SELECT area_id, indicator_key, value_key, amount FROM data.{target} ORDER BY 1, 2, 3) TO STDOUT")
    sql_path = OUTPUT_DIR / f"{target}.sql"
    with sql_path.open("w") as file:
        file.write("-- QA reference for tilda-geo, created by infravelo-radnetz tilda-qa/build_qa_reference.py\n")
        file.write(f"-- cells {args.cells}, export {args.input.name}, geometry {args.geometry}\n")
        file.write(f'DROP TABLE IF EXISTS "data"."{target}";\n')
        file.write(f'CREATE TABLE "data"."{target}" (\n    "area_id" text NOT NULL,\n    "indicator_key" text NOT NULL,\n'
                   f'    "value_key" text NOT NULL,\n    "amount" numeric NOT NULL,\n'
                   f'    PRIMARY KEY ("area_id", "indicator_key", "value_key")\n);\n')
        file.write(f'COPY "data"."{target}" ("area_id", "indicator_key", "value_key", "amount") FROM stdin;\n')
        file.write(data)
        file.write("\\.\n")
    print(f"  {sql_path}")
    if args.data_schema:
        destination = tilda_geo_dir() / "data-schema" / target / f"{target}.sql"
        if not destination.parent.parent.exists():
            sys.exit(f"tilda-geo not found: {destination.parent.parent} (set TILDA_GEO_DIR)")
        destination.parent.mkdir(exist_ok=True)
        destination.write_bytes(sql_path.read_bytes())
        print(f"  {destination}")

    if not args.keep_schema:
        psql(url, f"DROP SCHEMA {SCHEMA} CASCADE")
    print(f"Done. data.{target} is loaded in this database.")


if __name__ == "__main__":
    main()
