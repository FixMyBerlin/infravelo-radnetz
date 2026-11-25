# Cleanup of `cycleway:*:oneway=yes` (Berlin, November 2026)

In the 2025 project we often tagged `cycleway:both:oneway=yes`, `cycleway:left:oneway=yes` or `cycleway:oneway=yes` on streets without a one-way rule. `oneway` refers to the direction of the way's line ([Key:cycleway:right:oneway](https://wiki.openstreetmap.org/wiki/Key:cycleway:right:oneway)). On the left, `yes` therefore means: the cycleway runs against the motor traffic next to it. That is almost always wrong. Without a tag, the right side defaults to `yes` and the left side to `-1`.

This folder documents the rules and builds from them an osmChange file for the clear cases and a MAID task list for the rest. Agreed with the OSM community in Berlin; the upload is announced there only. The upload is done by hand (JOSM or similar), not from this folder.

Discussion and comments: [Claude Doc "FMC-Bereinigung cycleway:*:oneway in Berlin"](https://claude.ai/artifact/THKf7vJkzGgW1KcyHHhXBY).

## Result (extract 2026-11-21, history up to 2026-11-18)

| Decision | Ways | Of these last set by FMC |
| --- | ---: | ---: |
| clean up automatically, package 1 (`output/auto__1-sicher.osc`) | 1,644 | |
| clean up automatically, package 2 (`output/auto__2-kurz.osc`) | 591 | |
| automatic in all | 2,235 | 1,741 |
| check by hand (`output/maid__oneway-check.json`) | 160 | – |

The extract is newer than the history, so no way was skipped. 983 of the 2,235 have a track on an affected side (see "Tracks"). The packages are explained under "Quality check: length of the tagged stretch".

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

7. **Upload package** of the automatic ways (`scripts/confidence.py`), from the length of the tagged stretch (same name, or same `highway` without a name, connected, all candidates):
   - `1-sicher`: stretch of at least 200 m. Upload first.
   - `2-kurz`: shorter stretch without a hint at a one-way street, or the way itself shows two-way traffic. Upload second.
   - → MAID: shorter stretch that could be a one-way street with a missing `oneway=yes` (whole street shorter than 200 m, touches a one-way way of the same name, no name, or `*_link`) and the way shows no two-way traffic (no `*:backward` tag, no `oneway=no`, no `lanes` ≥ 2 without `lanes:forward`). The task gets an extra answer "the street is a one-way street" (`oneway=yes`).

Change: `yes` on `both`, `cycleway:oneway` and `left` is deleted, `cycleway:right:oneway` only when it is `yes`. `cycleway:right:oneway=no|-1` stays.

## Quality check: length of the tagged stretch

A correct `yes` on the left needs a one-way street. The candidates have no one-way rule, so the tag can only be right where `oneway=yes` is missing on the road. One-way streets with cycling infrastructure on the left (`oneway=yes`, `cycleway:left` or `:both` = `lane`/`track`) are short in Berlin (extract 2026-11-21): the 20 stretches that are not a dual carriageway are 1.2 km in all, median 47 m, 90 % below 155 m, the longest 188 m. 38 more stretches lie on dual carriageways, mostly short pieces at junctions. The sample is small, but it backs the threshold of 200 m.

Result (extract 2026-11-21):

| Package | Ways |
| --- | ---: |
| `auto__1-sicher.osc` | 1,644 |
| `auto__2-kurz.osc` | 591 |
| moved to MAID | 37 |

Most short stretches are short because the street is split (bridges, junction pieces, crossings) or only some pieces carry the tag; 295 of 343 short stretches belong to a street longer than 200 m. Two samples of the short stretches (30 ways) were all tagging errors on two-way streets.

Compared with the previous single file `auto__tracks-explicit.osc` (2,272 ways): the two packages hold the same change for 2,235 ways, the other 37 are now MAID tasks, the 123 earlier MAID tasks are unchanged, and `cycleway-oneway-corrections.csv` is unchanged (TILDA corrects MAID ways too).

## Tracks

tilda-geo reads a track on the road line without a direction (`derive_oneway.lua`, `road_track_is_one_way`) as one-way (`implicit_yes`) when the other side of the road has cycling infrastructure (lane, track, `separate`, a sidewalk open to bicycles, …). It reads it as "probably both directions" (`assumed_no`) when the track is the only cycle path of the road. A lane always counts as "one direction".

Deleting only would leave 985 ways with an untagged track side. In about 37 of them the other side has no cycling infrastructure, so tilda-geo would read a new two-way track. **Decided: on track sides we set the side direction explicitly** (`auto__1-sicher.osc`, `auto__2-kurz.osc`): `cycleway:left:oneway=-1` (959×), `cycleway:right:oneway=yes` (810×), on 985 ways. On lane sides the tag is only deleted.

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

`cycleway-oneway-corrections.csv` lists the ids of all ways of the automatic and MAID cases (2,395, extract 2026-11-21). tilda-geo downloads it from GitHub (`main`) on every processing run and corrects these ways before it derives the direction, the same change as the `auto__*` packages (`processing/pseudoTags/cyclewayOnewayCorrectionsSource/` in tilda-geo). So TILDA shows the right directions while the OSM edit is still running.

- Only the ids: tilda-geo derives the change itself.
- Ways last edited on or after 2026-11-22 count as corrected in OSM and are used as tagged, also false positives of the list. The script leaves them out of the CSV, tilda-geo checks the same date (`PSEUDO_TAG_CUTOFF` and `CUTOFF` in `apply_cycleway_oneway_correction.lua`).
- Regenerate about once a week with `scripts/run.sh` and commit the CSV. The list shrinks as the OSM edit goes on; the next TILDA run picks it up.

## Follow-up MAID lists (2026-11-22)

`scripts/build_maid_followups.py` writes two more MAID files from the same extract:

The two files in `maid/` are checked in for MAID; after a new run copy them there again. Both only cover the RVN: `rvn_way_ids.txt` lists the OSM ways matched to the Radvorrangnetz part of the REN+ (`radverkehrsnetz=Radvorrangnetz`) in Datensatz C, extract 2026-11-21.

- `maid/rvn-radweg-fahrtrichtung.json` (39 tasks, copy of `output/maid__track-direction.json`): tracks tagged on the road without a direction. tilda-geo guesses it from the other side of the road. Default answer: the side default (left `-1`, right `yes`); alternative: two-way per side.
- `maid/rvn-spur-mit-fussverkehr.json` (24 tasks, copy of `output/maid__lane-foot.json`): lanes on the road with `traffic_mode:<x>=foot` (no separation), which tilda-geo reads as a foot and cycle path next to the road. Answers: remove the foot tags (lane on the carriageway), make it a `track`, or keep.

## Files

| Path | Content |
| --- | --- |
| `output/auto__1-sicher.osc` | osmChange, stretch of at least 200 m, **upload first** |
| `output/auto__2-kurz.osc` | osmChange, shorter stretches, **upload second** |
| `output/auto__delete-only.osc` | comparison: delete only, do not upload |
| `maid/berlin-fahrtrichtung-links-pruefen.json` | checked-in copy of `output/maid__oneway-check.json` for MAID (160 tasks, extract 2026-11-21); copy again after a new run |
| `output/maid__oneway-check.json` | MAID tasks (options: restore the default / the tag is right; short stretches also: the street is a one-way street) |
| `output/decisions.csv`, `output/decisions.json` | decision and reason per way, counts |
| `output/history_check.csv` | history per way: first FMC edit, first `yes`, who set it |
| `output/R*.csv` | tag rules with risk reasons and detail tags |
| `cycleway-oneway-corrections.csv` | way ids TILDA corrects before the OSM edit, **checked in** |
| `g2_bikelanes_diff_ids.txt` | ways from the road-side diff (tilda-geo, `road_side_of_lane`), to count the coverage |
| `samples/results.md` | sample of 66 ways checked in the OSM history |
