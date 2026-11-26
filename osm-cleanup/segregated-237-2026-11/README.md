# `segregated` on protected bike lanes (Berlin, November 2026)

`segregated` says how a cycle way is separated from a footway on the same way. tilda-geo reads it as "the way lies beside the road, next to a footway" and never shows such a way as a protected bike lane (PBL), even with bollards or vertical panels towards the carriageway. Example: Tempelhofer Damm, [way/1067561743](https://www.openstreetmap.org/way/1067561743): `cycleway:right=track` + `…:segregated=yes` + `…:separation:left=vertical_panel` + `…:traffic_sign=DE:237` + `sidewalk:right=separate`.

A raised cycle track next to a footway with a DE:237 sign is a "Getrennter Rad- und Gehweg" in OSM, and `segregated=yes` is right there. Only on PBLs the tag is wrong. We clean the data instead of adding a rule in tilda-geo; a rule "DE:237 wins over `segregated`" exists only as a discussion branch (tilda-geo `segregated-traffic-sign`).

## Result (Geofabrik extract 2026-11-24)

Ways with a DE:237 sign (without DE:240/DE:241) and `segregated=yes|no`:

| Group | Ways | PBL (task) |
| --- | ---: | ---: |
| `track_sidewalk_separate`: `cycleway:<side>=track` on the road line, the sidewalk of that side is `separate` | 287 | 66 |
| `track_other`: `cycleway:<side>=track` on the road line, sidewalk not mapped separately | 21 | 0 |
| `separate_cycleway`: a way of its own without `foot=yes\|designated` | 44 | 3 |
| `combined_foot`: a way of its own with `foot=yes\|designated` (one line for cycle way and footway) | 343 | – |

PBL: the separation towards the carriageway, read in the riding direction as tilda-geo does, is exactly one of `bollard`, `flex_post`, `vertical_panel`, `studs`, `bump`, `planter`, `fence`, `jersey_barrier`, `guard_rail` (tilda-geo does not split values like `kerb;greenery;fence`). All 69 PBL ways have `segregated=yes`, on tracks always as `cycleway:<side>:segregated`.

## Maid

List: `maid/berlin-pbl-segregated.json` (69 tasks). One answer per task: "segregated entfernen" removes `cycleway:<side>:segregated` (tracks) or `segregated` (ways of their own). The MAID texts are German on purpose: they are read by mappers in Berlin.

## Run

```bash
PBF_DIR="${OSM_PBFS_DIR:-$HOME/Development/_osm-pbfs}"
.venv/bin/python -I osm-cleanup/segregated-237-2026-11/scripts/build.py "$PBF_DIR/berlin-latest.osm.pbf" osm-cleanup/segregated-237-2026-11/output
cp osm-cleanup/segregated-237-2026-11/output/berlin-pbl-segregated.json osm-cleanup/segregated-237-2026-11/maid/
```

Run from the project root. `output/` is not versioned (`ways.csv` lists every way of the four groups, `summary.json` the counts); the list goes to `maid/`. Check it with `bun run tasks-check <file>` in the Maid repository. `list_id` and `task_id` stay the same across runs, so Maid keeps the progress when a regenerated list is loaded.
