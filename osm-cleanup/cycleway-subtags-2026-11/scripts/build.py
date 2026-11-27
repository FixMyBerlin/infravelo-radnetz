"""Redundant sub-tags of lanes and tracks tagged on the road line: osmChange for an automated edit (Berlin, November 2026).

Usage (from the project root, right before the upload, with a fresh extract):
  .venv/bin/python -I osm-cleanup/cycleway-subtags-2026-11/scripts/build.py <berlin.osm.pbf> <ren_netz.gpkg> <output dir>

Roads (not separate paths) with `cycleway:<side>=lane|track` (also via `cycleway:both` and `cycleway`). A sub-tag
(`cycleway:<side>:<key>`, `cycleway:both:<key>`, `cycleway:<key>`) is removed when, on every side it applies to, it
only repeats the default or does not belong there. The rules are in README.md (`PRIMARY`, `SECONDARY`).

A way is in the edit for the primary rules. On these ways the edit also removes what other cleanups of November 2026
would remove there (secondary rules), so each way gets one new version.

Output: one osmChange per network (`1-rvn.osc`, `2-ren.osc`), `ways.csv` (every way with its changes),
and `summary.json`.

Network: RVN = ways in `osm-cleanup/oneway-2026-11/rvn_way_ids.txt`; REN = other ways with at least 70 % of their
length inside 25 m of `ren_netz.gpkg`; the rest is not in the edit.
"""

import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import geopandas as gpd
import osmium
from pyproj import Transformer
from shapely import STRtree
from shapely.geometry import LineString
from shapely.ops import transform

LIST_DATE = date.today().isoformat()
CLEANUP = Path(__file__).resolve().parents[2]
RVN_IDS = CLEANUP / "oneway-2026-11" / "rvn_way_ids.txt"
# oneway-2026-11 sends these ways to a human (the road might be a one-way street): the wrong `yes` stays here
ONEWAY_CHECK_LIST = CLEANUP / "oneway-2026-11" / "maid" / "berlin-fahrtrichtung-links-pruefen.json"
SEPARATE_HIGHWAYS = {"cycleway", "path", "footway", "bridleway", "pedestrian", "steps", "track", "corridor", "platform"}
# tilda-geo `cyclewayOnHighwayProtected` (+ values it maps to them); a list like `kerb;bollard` counts as well
PHYSICAL = {"bollard", "flex_post", "vertical_panel", "studs", "bump", "planter", "fence", "jersey_barrier",
            "guard_rail", "separation_kerb", "lane_separator"}
SUB_KEY = re.compile(r"^cycleway(?::(left|right|both))?:(.+)$")
ONEWAY_KEY = re.compile(r"^cycleway(?::(left|right|both))?:oneway$")
SIDED = r"(?::(left|right|both))?"
SIDES = ("left", "right")
NO_VALUES = {"no", "none"}
LANE_LINE = {"advisory": "dashed_line", "exclusive": "solid_line"}
LANE_SEPARATION_LINES = {"no", "none", "dashed_line", "solid_line", "double_solid_line"}
SIGN_237 = re.compile(r"(?<![0-9-])237(?![0-9])")

# the redundant tags this list is about: they put a way on the list
PRIMARY = ["lane_oneway_default", "lane_oneway_wrong", "lane_marking", "lane_separation",
           "lane_traffic_mode", "lane_segregated", "buffer_no", "track_marking_no"]
# what other cleanups remove: only on ways that are on the list anyway
SECONDARY = ["track_separation_no", "pbl_segregated"]


def side_type(tags, side):
    return tags.get(f"cycleway:{side}") or tags.get("cycleway:both") or tags.get("cycleway")


def side_value_key(tags, side, sub):
    for prefix in (f"cycleway:{side}:", "cycleway:both:", "cycleway:"):
        if prefix + sub in tags:
            return prefix + sub
    return None


def side_value(tags, side, sub):
    key = side_value_key(tags, side, sub)
    return tags[key] if key else None


def road_direction(tags):
    """`yes`/`-1` on a one-way road (as tilda-geo normalises it), `two_way`, or None when unclear."""
    oneway = tags.get("oneway")
    if oneway in ("yes", "1", "true"):
        return "yes"
    if oneway == "-1":
        return "-1"
    if oneway in (None, "no", "false", "0"):
        if oneway is None and tags.get("junction") in ("roundabout", "circular"):
            return "yes"
        return "two_way"
    return None  # reversible, alternating, conditional values


def side_default(tags, side):
    """Default of `cycleway:<side>:oneway`: on one-way roads the road direction, else right `yes`, left `-1`."""
    direction = road_direction(tags)
    if direction is None:
        return None
    if direction != "two_way":
        return direction
    return "yes" if side == "right" else "-1"


def carriageway_side(tags, side):
    """Side of the carriageway, seen in the riding direction (as tilda-geo reads `separation:*`)."""
    oneway = side_value(tags, side, "oneway") or side_default(tags, side) or ("yes" if side == "right" else "-1")
    runs_with_way = oneway != "-1"
    if side == "left":
        return "right" if runs_with_way else "left"
    return "left" if runs_with_way else "right"


def physical(value):
    return bool(value) and bool(PHYSICAL & set(value.split(";")))


def protected(tags, side):
    """A protected bike lane or a lane between lanes: `marking`, `buffer`, `separation` are part of its schema."""
    if any(physical(side_value(tags, side, sub)) for sub in ("separation", "separation:left", "separation:right",
                                                              "separation:both")):
        return True
    modes = {sub: side_value(tags, side, f"traffic_mode:{sub}") for sub in SIDES}
    if "motor_vehicle" in modes.values():
        return True
    return modes[carriageway_side(tags, side)] == "parking"


def pbl_track(tags, side):
    """segregated-237-2026-11: a track signed DE:237 (bicycles only) with a physical separation to the carriageway."""
    sign = side_value(tags, side, "traffic_sign") or ""
    if not SIGN_237.search(sign) or "240" in sign or "241" in sign:
        return False
    return physical(side_value(tags, side, f"separation:{carriageway_side(tags, side)}"))


# ---------------------------------------------------------------- rules


def oneway_changes(tags, may_fix_wrong):
    """{key: rule}, {key: value} of the lanes' `oneway` (pass 1, before the rules that read the riding direction).

    A key that a track side reads too is only removed when it is right for the track; the track then gets its own
    key (`cycleway:<side>:oneway`), as oneway-2026-11 decided for tracks.
    """
    remove, set_ = {}, {}
    two_way = road_direction(tags) == "two_way" and not any(
        k in tags for k in ("oneway:bicycle", "oneway:conditional", "oneway:bicycle:conditional"))
    for key, value in tags.items():
        m = ONEWAY_KEY.match(key)
        if not m:
            continue
        sides = [m.group(1)] if m.group(1) in SIDES else list(SIDES)
        sides = [s for s in sides if side_value_key(tags, s, "oneway") == key]
        types = {s: side_type(tags, s) for s in sides}
        lanes = [s for s in sides if types[s] == "lane" and side_value(tags, s, "lane") in (None, "advisory", "exclusive")]
        tracks = [s for s in sides if types[s] == "track"]
        if not lanes or len(lanes) + len(tracks) < sum(t not in (None, "no", "none", "separate") for t in types.values()):
            continue
        rules = set()
        for s in lanes:
            if value == side_default(tags, s):
                rules.add("lane_oneway_default")
            elif value == "yes" and s == "left" and two_way and may_fix_wrong:
                rules.add("lane_oneway_wrong")
            else:
                rules.add(None)
        if None in rules or any(value != side_default(tags, s) for s in tracks):
            continue
        remove[key] = ("lane_oneway_wrong" if "lane_oneway_wrong" in rules else "lane_oneway_default", lanes)
        for s in tracks:
            set_[f"cycleway:{s}:oneway"] = value
    return remove, set_


def rule(tags, side, sub, value):
    """Rule that removes `sub=value` on this side (pass 2), or None."""
    kind = side_type(tags, side)
    buffer = re.fullmatch(f"buffer{SIDED}", sub)
    if kind == "lane":
        if side_value(tags, side, "lane") not in (None, "advisory", "exclusive"):
            return None  # `lane=crossing` and other edge cases
        if sub == "segregated":
            return "lane_segregated"
        if re.fullmatch(f"traffic_mode{SIDED}", sub) and value in NO_VALUES | {"foot"}:
            return "lane_traffic_mode"
        if protected(tags, side):
            return None
        if buffer and value in NO_VALUES | {"0"}:
            return "buffer_no"
        marking = re.fullmatch(f"marking{SIDED}", sub)
        if marking:
            if value in NO_VALUES:
                return "lane_marking"
            # the lane's own line towards the carriageway; other lines (barred_area, double_solid_line,
            # a dashed line towards parking) and contradictions stay
            line = LANE_LINE.get(side_value(tags, side, "lane"))
            if value == line and (marking.group(1) or "left") in ("both", carriageway_side(tags, side)):
                return "lane_marking"
        separation = re.fullmatch(f"separation{SIDED}", sub)
        if separation:
            if value in LANE_SEPARATION_LINES:
                return "lane_separation"
            # the kerb towards the footway; a kerb towards the carriageway would make it a track: stays
            if value == "kerb" and (separation.group(1) or "left") not in ("both", carriageway_side(tags, side)):
                return "lane_separation"
    if kind == "track":
        if sub == "segregated" and pbl_track(tags, side):
            return "pbl_segregated"
        if re.fullmatch(f"separation{SIDED}", sub) and value in NO_VALUES:
            return "track_separation_no"
        if protected(tags, side):
            return None
        if buffer and value in NO_VALUES | {"0"}:
            return "buffer_no"
        if re.fullmatch(f"marking{SIDED}", sub) and value in NO_VALUES:
            return "track_marking_no"
    return None


def other_removals(tags):
    """{key: (rule, sides)} of all sub-tags but `oneway` (pass 2)."""
    result = {}
    for key, value in tags.items():
        m = SUB_KEY.match(key)
        if not m or m.group(2) in ("left", "right", "both", "oneway"):
            continue
        prefix, sub = m.groups()
        sides = [prefix] if prefix in SIDES else list(SIDES)
        # a side-specific key wins over `both` and the plain key: only judge the sides that read this key
        sides = [s for s in sides if side_value_key(tags, s, sub) == key]
        types = {s: side_type(tags, s) for s in sides}
        infra = [s for s in sides if types[s] in ("lane", "track")]
        if not infra or any(types[s] not in ("lane", "track", None, "no", "none", "separate") for s in sides):
            continue
        rules = {rule(tags, s, sub, value) for s in infra}
        if len(rules) == 1 and None not in rules:
            result[key] = (rules.pop(), infra)
    return result


def cleanup(tags, may_fix_wrong):
    """{key: (rule, sides)} to remove and {key: value} to set, or None when no primary rule applies."""
    remove, set_ = oneway_changes(tags, may_fix_wrong)
    after = {k: v for k, v in tags.items() if k not in remove}
    after.update(set_)
    remove.update(other_removals(after))
    if not any(r in PRIMARY for r, _ in remove.values()):
        return None
    return remove, set_


# ---------------------------------------------------------------- input


class Reader(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.ways = []

    def way(self, w):
        tags = {t.k: t.v for t in w.tags}
        highway = tags.get("highway")
        if not highway or highway in SEPARATE_HIGHWAYS:
            return
        if not any(side_type(tags, s) in ("lane", "track") for s in SIDES):
            return
        try:
            lonlat = [(round(n.lon, 7), round(n.lat, 7)) for n in w.nodes]
        except osmium.InvalidLocationError:
            return
        if len(lonlat) >= 2:
            self.ways.append({"id": w.id, "version": w.version, "nodes": [n.ref for n in w.nodes], "tags": tags,
                              "lonlat": lonlat})


def networks(ways, ren_path):
    rvn = {int(line) for line in open(RVN_IDS) if line.strip() and not line.startswith("#")}
    to_utm = Transformer.from_crs(4326, 25833, always_xy=True).transform
    ren = list(gpd.read_file(ren_path).to_crs(25833).geometry.buffer(25))
    tree = STRtree(ren)
    for way in ways:
        if way["id"] in rvn:
            way["net"] = "rvn"
            continue
        line = transform(to_utm, LineString(way["lonlat"]))
        hits = tree.query(line)
        inside = line.intersection(gpd.GeoSeries([ren[i] for i in hits]).union_all()).length if len(hits) else 0
        way["net"] = "ren" if line.length and inside / line.length >= 0.7 else "rest"


# ---------------------------------------------------------------- output

PACKAGES = {"rvn": "1-rvn.osc", "ren": "2-ren.osc"}


def write_osc(path, items):
    from xml.sax.saxutils import quoteattr
    with open(path, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n'
                '<osmChange version="0.6" generator="infravelo-radnetz-osm-cleanup-cycleway-subtags">\n<modify>\n')
        for way, tags in items:
            f.write(f'  <way id="{way["id"]}" version="{way["version"]}">\n')
            for ref in way["nodes"]:
                f.write(f'    <nd ref="{ref}"/>\n')
            for k in sorted(tags):
                f.write(f"    <tag k={quoteattr(k)} v={quoteattr(tags[k])}/>\n")
            f.write("  </way>\n")
        f.write("</modify>\n</osmChange>\n")


def main(pbf, ren_path, out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    header = osmium.io.Reader(pbf, osmium.osm.osm_entity_bits.NOTHING).header()
    extract = (header.get("osmosis_replication_timestamp") or header.get("timestamp") or "?")[:10]
    reader = Reader()
    reader.apply_file(pbf, locations=True, idx="flex_mem")
    ways = sorted(reader.ways, key=lambda w: w["id"])
    networks(ways, ren_path)
    oneway_check = {int(f["properties"]["task_id"].removeprefix("way-"))
                    for f in json.loads(ONEWAY_CHECK_LIST.read_text())["features"]}

    by_rule = defaultdict(Counter)
    packages = defaultdict(list)
    rows = []
    for way in ways:
        result = cleanup(way["tags"], may_fix_wrong=way["id"] not in oneway_check)
        if result is None:
            continue
        remove, set_ = result
        for key, (r, _) in remove.items():
            by_rule[r][(way["net"], f"{SUB_KEY.match(key).group(2)}={way['tags'][key]}")] += 1
        rows.append({"way": way["id"], "net": way["net"], "name": way["tags"].get("name", ""),
                     "lon": way["lonlat"][len(way["lonlat"]) // 2][0], "lat": way["lonlat"][len(way["lonlat"]) // 2][1],
                     "rules": ";".join(sorted({r for r, _ in remove.values()})),
                     "remove": ";".join(f"{k}={way['tags'][k]}" for k in sorted(remove)),
                     "set": ";".join(f"{k}={v}" for k, v in sorted(set_.items()))})
        if way["net"] in PACKAGES:
            new = {k: v for k, v in way["tags"].items() if k not in remove}
            new.update(set_)
            packages[way["net"]].append((way, new))

    for net, name in PACKAGES.items():
        write_osc(out / name, packages[net])
    with open(out / "ways.csv", "w") as f:
        keys = list(rows[0])
        f.write(",".join(keys) + "\n")
        for r in rows:
            f.write(",".join(json.dumps(r[k], ensure_ascii=False) if isinstance(r[k], str) else str(r[k]) for k in keys) + "\n")
    nets = ("rvn", "ren", "rest")
    summary = {
        "extract": extract,
        "candidate_ways": {n: sum(w["net"] == n for w in ways) for n in nets},
        "ways": {n: sum(r["net"] == n for r in rows) for n in nets},
        "tag_changes": {n: sum(r["remove"].count("=") + r["set"].count("=") for r in rows if r["net"] == n) for n in nets},
        "tags_by_rule": {
            r: {
                "total": {n: sum(v for (net, _), v in by_rule[r].items() if net == n) for n in nets},
                "values": {f"{net} {kv}": n for (net, kv), n in sorted(by_rule[r].items(), key=lambda x: -x[1])},
            }
            for r in PRIMARY + SECONDARY if r in by_rule
        },
    }
    with open(out / "summary.json", "w") as f:
        json.dump(summary, f, indent=1, ensure_ascii=False)
    print(json.dumps({k: v for k, v in summary.items() if k != "tags_by_rule"}, indent=1))
    for r, v in summary["tags_by_rule"].items():
        print(r, v["total"])


if __name__ == "__main__":
    main(*sys.argv[1:4])
