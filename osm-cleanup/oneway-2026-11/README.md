# Cleanup of `cycleway:*:oneway=yes` (Berlin, November 2026)

In the 2025 project we often tagged `cycleway:both:oneway=yes`, `cycleway:left:oneway=yes` or `cycleway:oneway=yes` on streets without a one-way rule. `oneway` refers to the direction of the way's line ([Key:cycleway:right:oneway](https://wiki.openstreetmap.org/wiki/Key:cycleway:right:oneway)). On the left, `yes` therefore means: the cycleway runs against the motor traffic next to it. That is almost always wrong. Without a tag, the right side defaults to `yes` and the left side to `-1`.

This folder documents the rules and builds from them an osmChange file for the clear cases and a MAID task list for the rest. Agreed with the OSM community in Berlin; the upload is announced there only. The upload is done by hand (JOSM or similar), not from this folder.

Discussion and comments: [Claude Doc "FMC-Bereinigung cycleway:*:oneway in Berlin"](https://claude.ai/artifact/THKf7vJkzGgW1KcyHHhXBY).

## Result (extract 2026-11-08, history up to 2026-11-16)

| Decision | Ways | Of these last set by FMC |
| --- | ---: | ---: |
| clean up automatically (`output/auto__*.osc`) | 2,240 | 1,763 |
| check by hand (`output/maid__oneway-check.json`) | 117 | – |
| skipped: tag already removed | 75 | – |
| skipped: edited since the extract, rebuild with a fresh extract | 42 | – |

985 of the 2,240 have a track on an affected side (see "Tracks").

## Rules

Candidates: ways with `highway` = road (primary … residential, service, living_street, busway, `*_link`) **without a one-way rule** (no `oneway` or `oneway=no`, no `junction=roundabout|circular` without `oneway=no`) and at least one of these tags: `cycleway:both:oneway=yes`, `cycleway:oneway=yes`, `cycleway:left:oneway=yes`.

Per way, in this order (`scripts/build_cleanup.py`, `decide`):

1. **Already cleaned up** (current version without the tag) → skip.
2. **Edited since the extract** → skip, decide again in the next run with a fresh extract.
3. **Risk** → MAID:
   - `oneway:bicycle`, `oneway:conditional` or `oneway:bicycle:conditional` set
   - a check date for the direction (`cycleway:*:check_date(:oneway)`, `check_date:cycleway:*:oneway`)
   - `note`, `fixme` or `description` mentions a direction (oneway, Richtung, Einbahn, gegen, links, …)
   - contradicting side tags (e.g. `cycleway:both:oneway=yes` and `cycleway:left:oneway=-1`)
   - the detail tags of the left side (`cycleway:left:separation|traffic_mode:*`) match the literal direction `yes`: after deleting, they would read swapped.
4. **Tag set before 2025-07-05** (first `yes` in the history before the first tag of this kind set by FMC) → MAID. These are the cases where `yes` might be right.
5. **Both sides tagged** (`:both`, `cycleway:oneway`, or `left=yes` + `right=yes`) → automatic, whoever tagged it. Both sides in line direction do not exist on a two-way street.
6. **Only the left side tagged** (`cycleway:left:oneway=yes`, right not `yes`) → automatic if the tag was set by an `fmc*` account; otherwise MAID. A real left-hand cycleway is possible here.

"Set by FMC" means: the edit that set today's `yes` comes from an account starting with `fmc` (case-insensitive). The last editor of the way does not count; it says little about who set the tag (sample: `samples/results.md`).

Change: `yes` on `both`, `cycleway:oneway` and `left` is deleted, `cycleway:right:oneway` only when it is `yes`. `cycleway:right:oneway=no|-1` stays.

## Tracks

tilda-geo reads a track on the road line without a direction (`derive_oneway.lua`, `road_track_is_one_way`) as one-way (`implicit_yes`) when the other side of the road has cycling infrastructure (lane, track, `separate`, a sidewalk open to bicycles, …). It reads it as "probably both directions" (`assumed_no`) when the track is the only cycle path of the road. A lane always counts as "one direction".

Deleting only would leave 985 ways with an untagged track side. In about 37 of them the other side has no cycling infrastructure, so tilda-geo would read a new two-way track. **Decided: on track sides we set the side direction explicitly** (`auto__tracks-explicit.osc`): `cycleway:left:oneway=-1` (959×), `cycleway:right:oneway=yes` (810×), on 985 ways. On lane sides the tag is only deleted.

`auto__delete-only.osc` stays for comparison and is not uploaded.

The network validator in tilda-schemas (`cycleway_oneway_redundant`) does not check track sides (since tagging 0.4.0), so the explicit side defaults are not flagged. A test for this is in tilda-schemas commit 7adb7fb (local, not released).

## Run

```bash
OHSOME_API_KEY=… scripts/run.sh
```

1. Internal Geofabrik extract (with account names) from the Docker volume `tilda-geo_osmfiles`, read-only; Berlin via relation 62422.
2. `rules.py`: tag rules R1–R5 and risk exclusions, one CSV per rule. R4/R5 (default values only, cosmetic) are not used.
3. `history_check.py`: history of the candidates via the [ohsome API v2](https://docs.ohsome.org/ohsome-api/v2/) (`contributions.parquet`, per edit the account and the tags before/after). Key from [account.heigit.org](https://account.heigit.org/manage/key).
4. `build_cleanup.py`: decision per way, osmChange, MAID file, `decisions.csv`, and `cycleway-oneway-corrections.csv` for TILDA (see below).
5. `validate_osc.py`: same version and nodes as in the extract, only the named tags changed. Check the MAID file with `bun run tasks-check` in the Maid repo.

The MAID task texts are German on purpose: they are read by mappers in Berlin.

`data/` and `output/` are not versioned.

## Corrections in TILDA before the OSM edit

`cycleway-oneway-corrections.csv` lists the ids of all ways of the automatic and MAID cases (2,357, extract 2026-11-08). tilda-geo downloads it from GitHub (`main`) on every processing run and corrects these ways before it derives the direction, the same change as `auto__tracks-explicit.osc` (`processing/pseudoTags/cyclewayOnewayCorrectionsSource/` in tilda-geo). So TILDA shows the right directions while the OSM edit is still running.

- Only the ids: tilda-geo derives the change itself.
- Ways last edited on or after 2026-11-22 count as corrected in OSM and are used as tagged, also false positives of the list. The script leaves them out of the CSV, tilda-geo checks the same date (`PSEUDO_TAG_CUTOFF` and `CUTOFF` in `apply_cycleway_oneway_correction.lua`).
- Regenerate about once a week with `scripts/run.sh` and commit the CSV. The list shrinks as the OSM edit goes on; the next TILDA run picks it up.

## Files

| Path | Content |
| --- | --- |
| `output/auto__tracks-explicit.osc` | osmChange of the automatic cases, **upload this file** |
| `output/auto__delete-only.osc` | comparison: delete only, do not upload |
| `output/maid__oneway-check.json` | MAID tasks (options: restore the default / the tag is right) |
| `output/decisions.csv`, `output/decisions.json` | decision and reason per way, counts |
| `output/history_check.csv` | history per way: first FMC edit, first `yes`, who set it |
| `output/R*.csv` | tag rules with risk reasons and detail tags |
| `cycleway-oneway-corrections.csv` | way ids TILDA corrects before the OSM edit, **checked in** |
| `g2_bikelanes_diff_ids.txt` | ways from the road-side diff (tilda-geo, `road_side_of_lane`), to count the coverage |
| `samples/results.md` | sample of 66 ways checked in the OSM history |
