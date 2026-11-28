# Direction of separate cycle paths (Berlin, November 2026)

Separate bicycle ways (`highway=cycleway`, or path/footway/bridleway with `bicycle=designated|yes`) whose one-way direction (`oneway:bicycle`, else `oneway`) does not fit how the line is drawn. Road sides on the road line (`cycleway:left:oneway=-1`) are not read.

Two mistakes happen when mapping:

- The line is drawn against the riding direction and turned with `-1`. That is correct, but hard to read. tilda-geo reverses such lines when it processes them, so the result does not show it.
- The line is drawn against the riding direction and tagged `yes`. Bicycles then ride against the traffic on that side of the road.

## Method

No routing graph is needed. For each way, `scripts/build.py` puts a point every 5 m and looks for the nearest parallel road (within 25 m, angle below 30°). The side of the road and the direction of the road give the direction of the traffic next to the way: on a two-way road, with the road line on the right and against it on the left; on a one-way road, with it on the right, while the left is not judged. On a dual carriageway the left side is the median, so only the nearest carriageway counts. Points next to a roundabout are not judged (as in tilda-schemas). A road that says its cycle path on that side is mapped separately (`cycleway:<side>=separate`, then `sidewalk:<side>=separate`) wins over a nearer road without it. Otherwise a side road between the path and the carriageway (Nebenfahrbahn) or a parallel one-way street would decide. A way is judged when at least 3 points vote and 80 % of them agree.

Check: of the 9,431 ways with `yes`, 7,941 fit the traffic next to them, 36 run against it, 25 are mixed and 1,429 have no parallel road. The convention therefore holds.

## Result (Geofabrik extract 2026-11-28)

| Group | Ways 2026-11-24 | Ways 2026-11-27 | Ways 2026-11-28 | List |
| --- | ---: | ---: | ---: | --- |
| `yes_wrong`: `yes`, but runs against the traffic next to it | 36 | 19 | 19 | `maid/berlin-radweg-richtung-falsch.json` |
| `minus1_wrong`: `-1`, and that runs against the traffic next to it | 10 | 0 | 0 | `maid/berlin-radweg-richtung-falsch.json` |
| `reverse_ok`: `-1`, fits the traffic; reverse the way and set `yes` | 351 | 162 | 157 | `maid/berlin-radweg-umdrehen.json` |
| `reverse_unjudged`: `-1`, no parallel road found | 17 | 15 | 14 | `maid/berlin-radweg-umdrehen.json` |

Answers in Maid (task operations since Maid a94b157):

- `yes_wrong`: "Weg umdrehen" (reverse, `yes` stays), "Zweirichtungsradweg" (`no`), "Richtung stimmt" (no change).
- `minus1_wrong`: "`yes`: the line is the right way round", "Zweirichtungsradweg", "Richtung stimmt".
- Reverse list: "Weg umdrehen" (reverse, then `yes`), "So lassen".

"Weg umdrehen" also sets `<key>=yes` after the reverse. Since Maid 0b6921a the reverse itself turns `-1` into `yes` on the first key that gives a direction (`oneway`, then `oneway:bicycle`), also with `oneway=no` + `oneway:bicycle=-1`; the `set` is a safeguard and changes nothing there.

The 25 mixed ways (`output/ways.csv`, mixed `fits`/`against`) are not in the lists. Nearly all are shorter than 40 m, pieces at junctions: a few points match the cross street or the road behind the junction, the rest match the carriageway.

The MAID texts are German on purpose: they are read by mappers in Berlin.

## Run

```bash
PBF_DIR="${OSM_PBFS_DIR:-$HOME/Development/_osm-pbfs}"
curl -fL -o "$PBF_DIR/berlin-latest.osm.pbf" https://download.geofabrik.de/europe/germany/berlin-latest.osm.pbf
.venv/bin/python -I osm-cleanup/sidepath-direction-2026-11/scripts/build.py "$PBF_DIR/berlin-latest.osm.pbf" osm-cleanup/sidepath-direction-2026-11/output
```

Run from the project root. The PBF is the shared extract cache (skill `osm-pbfs`); the lists name the extract date. `output/` is not versioned; copy the two lists to `maid/` (checked in for MAID) after a new run: `cp osm-cleanup/sidepath-direction-2026-11/output/berlin-radweg-*.json osm-cleanup/sidepath-direction-2026-11/maid/`. Load them in Maid (account menu → "Load task list…"). Check them with `bun run tasks-check <file>` in the Maid repository. `list_id` and `task_id` stay the same across runs, so Maid keeps the progress when a regenerated list is loaded.
