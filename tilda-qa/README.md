# QA views in TILDA

Quality assurance (QA) in TILDA compares the meters of cycling infrastructure per cell with a frozen state and shows where something has changed since then. For infraVelo, every delivery gets its own QA view: cells along the delivered network and, as reference, the TILDA state the delivery was calculated from. Background in tilda-geo: [`docs/QA-Cells.md`](https://github.com/FixMyBerlin/tilda-geo/blob/develop/docs/QA-Cells.md), [`docs/QA-Freeze.md`](https://github.com/FixMyBerlin/tilda-geo/blob/develop/docs/QA-Freeze.md), [`docs/QA-Documentation.md`](https://github.com/FixMyBerlin/tilda-geo/blob/develop/docs/QA-Documentation.md). The parking QA of eUVM works the same way in [FMC/scripts `tilda-parkraum-euvm/tilda-qa/`](https://github.com/FixMyBerlin/scripts/tree/main/tilda-parkraum-euvm/tilda-qa).

A QA view needs two tables in tilda-geo and a QA config:

| Step | Script | Result |
| --- | --- | --- |
| 1. Cells | `build_qa_cells.py` | `data.infravelo_qa_<date>_cells_<network>[_bezirkNN]`: one area per network edge |
| 2. Reference | `build_qa_reference.py` | `data.infravelo_qa_<date>_reference_<network>[_bezirkNN]`: meters per cell, indicator and value at the state of the delivery |
| 3. tilda-geo | `bun run data-schema-*`, import, QA config | the QA view |

```bash
# whole Radvorrangnetz (2025), reference from the export of 2026-01-29
.venv/bin/python tilda-qa/build_qa_cells.py --network rvn --data-schema
.venv/bin/python tilda-qa/build_qa_reference.py --cells data.infravelo_qa_2026_cells_rvn \
  --input tilda-qa/input/bikelanes.fgb --geometry side --data-schema

# delivery of one district: cells of the district, reference from processing/data-raw-tilda/bikelanes.fgb
.venv/bin/python tilda-qa/build_qa_cells.py --network ren --district 7 --date 2026-12-01 --data-schema
.venv/bin/python tilda-qa/build_qa_reference.py --cells data.infravelo_qa_2026_12_01_cells_ren_bezirk07 \
  --geometry centerline --data-schema
```

`tilda-static-data` and `tilda-geo` are expected as sibling folders of this repo. Otherwise set `TILDA_STATIC_DATA_DIR` and `TILDA_GEO_DIR` (always in a worktree).

## Why here and not in tilda-geo

The networks and the TILDA exports of a delivery live in this repo, so cells and reference are built here too. tilda-geo only loads the result: With `--data-schema`, both scripts write their SQL file directly to `../tilda-geo/data-schema/<table>/` (like `processing/copy_to_tilda_static.sh` writes to tilda-static-data). A symlink would not help, because the folder `data-schema/<table>/` in tilda-geo is not versioned. The source is noted in the `spec.yaml` of the table instead, which is also stored on S3 and shown under `/admin/data-schema`.

The measuring still uses the code of tilda-geo: `build_qa_reference.py` calls the QA functions (`processing/qa/qa_functions.sql`) in a local tilda-geo database, so the reference and the nightly QA calculate the same way.

## 1. Cells: `build_qa_cells.py`

One area per network edge (`element_nr`, both directions together): the strip up to 25 m left and right of the edge. Where the strips of two edges meet (at nodes, at parallel edges), each point belongs to the nearest edge. So the cells of one network do not overlap, and only ways along the network count, not parallel ways away from it.

| `--network` | Input | Table (whole network) |
| --- | --- | --- |
| `rvn` | Result 2025, dataset C: `tilda-static-data/geojson/region-infravelo/infravelo-datensatz-c-fortlaufend/aggregated_rvn_final.geojson.gz` | `data.infravelo_qa_2026_cells_rvn` |
| `ren` | `ren-network/output/ren_netz.gpkg` (after `netzanpassungen/apply_app_result.py`) | `data.infravelo_qa_2026_cells_ren` |

- `--district N --date YYYY-MM-DD`: only the edges of one district (column `Bezirksnummer`), table name with district and delivery date. The whole network is always split, so the cells at the district border have the same shape as in the whole network.
- Each network is split on its own: Calculated together, REN edges would cut into the RVN cells. Cells of different networks may overlap, because each QA config reads only one table.
- The script aborts if an edge gets no cell, a cell is invalid, cells overlap, or less than 98 % of the edge length lies in its own cell.
- Output: `output/<table>.gpkg` for viewing, `output/<table>.sql` (text primary key `id` = `element_nr`, `name` = street name).

**Buffer 25 m.** Measured on the TILDA ways that were assigned to an edge in 2025 (`tilda_ids` in dataset C, export 2026-01-29, geometry moved to the street side): 91 % of their length lies within 20 m of their edge, 95 % within 25 m, and after that the share hardly grows (30 m: 95.7 %, 40 m: 96.4 %). The rest are ways that go beyond the end of their edge.

**Vertices.** The borders are simplified together by up to 1 m (`coverage_simplify`, neighbors keep identical borders), so the areas in the tiles are not too detailed.

Run 2026-11-18 (`rvn`): 5210 cells, 42.5 km², 99.9 % of the edge length in its own cell; 15.5 vertices per cell on average, 99 % with at most 65, 80 784 in total (the eUVM cells: 9.7 per cell, 336 701 in total).

**Open (REN+):** 32 edges with `.02` at the end of the `element_nr` lie exactly on their `.01` edge (e.g. `34610002_34610003.01` and `.02`) and get no cell of their own, so the script aborts. Clear this up before the first REN view: merge two edges into one cell or remove the duplication in the network.

## 2. Reference: `build_qa_reference.py`

Loads a TILDA export `bikelanes` into the local tilda-geo database (schema `_tilda_qa_reference`, dropped afterwards) and measures it per cell, like the nightly QA (`processing/topics/roads_bikelanes/5_qa_bikelanes.sql` in tilda-geo): A line that crosses a cell border counts proportionally in each cell, and what lies outside all cells is dropped.

- `--input`: default is `processing/data-raw-tilda/bikelanes.fgb`, the export the delivery was calculated from. This is the state the QA view later compares against.
- `--geometry centerline`: exports since August 2026 lie on the road centerline and carry `offset`. The lines are moved to the street side like in the nightly QA (`tilda_qa_side_lines`).
- `--geometry side`: older exports (until August 2026) already lie on their side, e.g. the export of 2026-01-29.
- Indicators: `total`, `category`, `oneway`, `surface`, `smoothness`, `traffic_sign` (more than any config uses today, so indicators can be added without a new reference).
- Checks that all indicators add up to the same total, and shows how much of the export lies in the cells.
- Requires: a local tilda-geo database (`ENVIRONMENT=development` in tilda-geo `.env`) with the functions from `processing/measure` and `processing/qa` (state since 2026-11-18) and the cell table (`bun run data-schema-load`), plus `ogr2ogr` and `psql`.

Run 2026-11-18 (`rvn`, export 2026-01-29): 934 493 m in 3654 of the 5210 cells, 36 556 rows. Identical to the published table.

`input/` (not versioned) holds the TILDA export of the infraVelo region of 2026-01-29 (`bikelanes.fgb`, 42 768 lines, 3797 km, geometry already moved to the side; plus `roads.fgb`, `roadsPathClasses.fgb`), the only state of this reference. It lives in the main folder of the repo, not in worktrees.

## 3. In tilda-geo

1. Put a `spec.yaml` next to the SQL file, then run `bun run data-schema-verify`, `data-schema-load`, `data-schema-publish` (skill `add-db-data-table`). Enter the call and the date in `source.documentation`.
2. Import on every environment (`/admin/data-schema` or MCP `data_schema_import`).
3. QA config of the region `infravelo`: dataset cycling infrastructure, the cell and the reference table, `areaFilter: all`, `referenceFrozenAt` = date of the export. It takes effect with the next processing run.
