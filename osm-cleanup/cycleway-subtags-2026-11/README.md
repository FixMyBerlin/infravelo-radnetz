# Redundant sub-tags of lanes and tracks on the road line (Berlin, November 2026)

An automated edit (osmChange upload, like [oneway-2026-11](../oneway-2026-11/README.md)): about 4,600 ways are too many to edit by hand in a task list.

Many roads with `cycleway:<side>=lane` or `=track` carry sub-tags that only repeat a default or do not belong there. They make the data hard to read and create edge cases in tilda-geo. Example: Anna-Louisa-Karsch-Straße, [way/156364570](https://www.openstreetmap.org/way/156364570):

| Tag | Keep? |
| --- | --- |
| `cycleway:both=lane` | yes |
| `cycleway:both:lane=advisory` | yes |
| `cycleway:both:surface=asphalt` | yes |
| `cycleway:both:traffic_sign=none` | yes (says: no sign) |
| `cycleway:both:width=1` | yes |
| `cycleway:both:oneway=yes` | no: right the default, left wrong on a two-way road |
| `cycleway:both:buffer:both=no` | no: default |
| `cycleway:both:marking:left=dashed_line` | no: follows from `lane=advisory` |
| `cycleway:both:marking:right=no` | no: says nothing |
| `cycleway:both:surface:colour=none` | yes, for now (see below) |

The edit removes the others in one new version of the way.

## Rules

Roads (not separate paths) with `cycleway:<side>=lane|track`, read through `cycleway:both` and `cycleway` as tilda-geo does. A key (`cycleway:<side>:<key>`, `cycleway:both:<key>`, `cycleway:<key>`) is removed only when the rule holds on every lane/track side that reads it. A side-specific key wins over `both` and the plain key.

**Primary rules** (they put a way into the edit):

| Rule | Sides | Removed | Why |
| --- | --- | --- | --- |
| `lane_oneway_default` | lane | `oneway` = the side's default: on one-way roads the road direction, else right `yes`, left `-1` | lanes run with the traffic next to them |
| `lane_oneway_wrong` | lane | `oneway=yes` on the left of a road without a one-way rule | wrong (against the traffic next to it); without the tag the default is right |
| `lane_marking` | lane, not protected | `marking:*=no\|none`, and the lane's own line towards the carriageway (`dashed_line` on `advisory`, `solid_line` on `exclusive`) | follows from `lane` |
| `lane_separation` | lane, not protected | `separation:*` = `no`, `none`, `dashed_line`, `solid_line`, `double_solid_line`, and `kerb` towards the footway | a lane on the carriageway is separated by its line only |
| `lane_traffic_mode` | lane | `traffic_mode:*=foot\|no\|none` | a lane has no foot traffic next to it; tilda-geo reads `foot` as a segregated foot and cycle path |
| `lane_segregated` | lane | `segregated` | describes a footway on the same way; tilda-geo then never shows a protected lane |
| `buffer_no` | lane, track, not protected | `buffer:*=no\|none\|0` | no buffer is the default (Radinfra FAQ, tilda-schemas `assumed: no`) |
| `track_marking_no` | track, not protected | `marking:*=no\|none` | default |

**Secondary rules** (only on ways that are in the edit anyway, so each way gets one new version; they add no ways):

| Rule | Removed | Same as |
| --- | --- | --- |
| `track_separation_no` | `separation:*=no\|none` on tracks | – (tilda-geo reads `no` like a missing tag, see below) |
| `pbl_segregated` | `segregated` on a track with DE:237 and a physical separation towards the carriageway | [segregated-237-2026-11](../segregated-237-2026-11/README.md) |

`lane_oneway_wrong` and `lane_traffic_mode` are the same changes as the oneway cleanup ([oneway-2026-11](../oneway-2026-11/README.md), osmChange and the lane-foot list) makes. Ways in its check list `berlin-fahrtrichtung-links-pruefen.json` (the road might be a one-way street) keep the wrong `yes` here: that needs a human decision there. Where a `oneway` key is also read by a track side (`cycleway:both:oneway` with a lane left and a track right), the key is removed and the track keeps its direction in its own key (`cycleway:right:oneway=yes`), as oneway-2026-11 decided for tracks.

The rules that read the riding direction (`marking`, `separation`) run after the `oneway` changes, so the example above loses `marking:left=dashed_line` too.

**Why `separation=no` is safe to remove.** tilda-geo reads `separation` in two places. A protected lane needs a physical value (`bollard`, `flex_post`, …) towards the carriageway; `no` is not one, so it counts like a missing tag. A foot and cycle path with `traffic_mode=foot` is "segregated" when `separation` there is missing or `no`: both read the same. So `no` never changes what TILDA shows.

What stays, on purpose:

- **Protected lanes** keep `separation`, `marking`, `buffer` and `traffic_mode=parking`: that is how a protected lane is mapped, and tilda-schemas asks for these keys there. "Protected" (conservative): any `separation:*` with a physical value (also in a list like `kerb;bollard`), `traffic_mode:*=motor_vehicle`, or `traffic_mode=parking` on the carriageway side. A lane with `separation=kerb` towards the carriageway keeps it: that would make it a track, a mistake for a human.
- **`oneway` on tracks** (set on purpose in oneway-2026-11), and on lanes `no` (two-way lane) and `-1` on the left of a one-way road (contraflow lane).
- **Other markings**: `barred_area`, `double_solid_line`, a dashed line on the parking side, and contradictions (`solid_line` on `advisory`).
- **Real buffer widths** (`0.5`, …), `width`, `surface`, `traffic_sign` (also `none`), `lane`.
- **`surface:colour=no|none`**, although it is the default. Removing it would lose the information that someone checked the colour; we would have to keep that in the key-value-db ("Geprüft" of the iD Radnetz fork). Not part of this edit, to keep the discussion short.

## Result (Geofabrik extract 2026-11-27)

Network: RVN = the OSM ways in `../oneway-2026-11/rvn_way_ids.txt` (Datensatz C); REN = other ways with at least 70 % of their length within 25 m of `ren-network/output/ren_netz.gpkg`; rest = neither (not in the edit).

| | RVN | REN | Both |
| --- | ---: | ---: | ---: |
| Roads with lane or track on the road line | 4,487 | 5,803 | 10,290 |
| **Ways in the edit** | **2,863** | **1,731** | **4,594** |
| Tag changes | 8,441 | 3,940 | 12,381 |

29 more ways lie outside both networks and are not in the edit. 22 ways also get a track direction (split `oneway` key).

| Rule | RVN | REN |
| --- | ---: | ---: |
| `lane_marking` | 2,993 | 1,197 |
| `lane_oneway_default` | 1,829 | 804 |
| `buffer_no` | 1,673 | 785 |
| `lane_separation` | 1,246 | 599 |
| `lane_oneway_wrong` | 638 | 408 |
| `lane_traffic_mode` | 13 | 69 |
| `lane_segregated` | 9 | 61 |
| `track_marking_no` | 1 | 0 |
| `track_separation_no` (secondary) | 23 | 10 |
| `pbl_segregated` (secondary) | 1 | 0 |

Values: `output/summary.json`; every way with its changes: `output/ways.csv`.

## Order with the oneway edit

All 1,046 wrong `oneway=yes` (`lane_oneway_wrong`) are in the pending oneway edit ([oneway-2026-11](../oneway-2026-11/README.md), FixMyBerlin/infravelo-radnetz#12), and 1,161 ways are in both edits. So: **upload the oneway edit first, then build this edit again from a fresh extract**. The wrong `yes` is then gone, 256 ways drop out (that was their only change), and the rules that read the riding direction (`marking`, `separation`) see the corrected direction. Expected after the oneway edit: about 2,805 ways in the RVN and 1,533 in the REN.

The other MAID lists (`segregated-237-2026-11`, the lane-foot list of oneway-2026-11) are not changed. Built again from a fresh extract after the upload, they no longer find these ways.

## Upload packages

| Package | Ways | |
| --- | ---: | --- |
| `output/1-rvn.osc` | 2,863 | first |
| `output/2-ren.osc` | 1,731 | after package 1 ran without feedback |

`scripts/validate_osc.py` checks each package against the extract: same version and node list, only `cycleway:*` sub-keys removed, nothing added except a track side's own direction. The packages are not in the repo: they hold way versions and go stale fast, so build them right before the upload.

## Run

```bash
PBF_DIR="${OSM_PBFS_DIR:-$HOME/Development/_osm-pbfs}"
O=osm-cleanup/cycleway-subtags-2026-11/output
.venv/bin/python -I osm-cleanup/cycleway-subtags-2026-11/scripts/build.py "$PBF_DIR/berlin-latest.osm.pbf" ren-network/output/ren_netz.gpkg $O
.venv/bin/python -I osm-cleanup/cycleway-subtags-2026-11/scripts/validate_osc.py "$PBF_DIR/berlin-latest.osm.pbf" $O/1-rvn.osc $O/2-ren.osc
```

Run from the project root. `output/` is not versioned (`ways.csv` lists every way with its rules and changes, `summary.json` the counts).
