"""Cycle ways with a DE:237 sign (bicycles only) that also carry `segregated` (Berlin, November 2026).

Usage (from the project root):
  .venv/bin/python -I osm-cleanup/segregated-237-2026-11/scripts/build.py <berlin.osm.pbf> <output dir>

`segregated` says how bicycles share a way with pedestrians. On a protected bike lane (PBL) it does not fit: tilda-geo
reads `segregated` as "the way lies beside the road, next to a footway" and never shows the way as a PBL.

Ways in Berlin with a DE:237 sign (without DE:240/DE:241) and `segregated=yes|no`, in groups:
- `track_sidewalk_separate`: `cycleway:<side>=track` on the road line, the sidewalk of that side is `separate`.
- `track_other`: `cycleway:<side>=track` on the road line, sidewalk not mapped separately.
- `separate_cycleway`: a way of its own (`highway=cycleway|path`) without `foot=yes|designated`.
- `combined_foot`: a way of its own with `foot=yes|designated`: one line for the cycle way and the footway.

Most of them are raised cycle tracks next to a footway: a "Getrennter Rad- und Gehweg" in OSM, and `segregated=yes`
is right there. Only the PBLs get a task: a physical separation (PHYSICAL) towards the carriageway, read in the riding
direction as tilda-geo does. The task removes `segregated` of these sides.
"""

import json
import re
import sys
from collections import Counter
from datetime import date

import osmium

LIST_DATE = date.today().isoformat()
PHYSICAL = {"bollard", "flex_post", "vertical_panel", "studs", "bump", "planter", "fence", "jersey_barrier", "guard_rail", "separation_kerb", "lane_separator"}  # tilda-geo: exact value, the last two read as bump
SEPARATE_HIGHWAYS = {"cycleway", "path", "footway", "bridleway"}
CROSSING = {"crossing", "traffic_island", "link"}
SIGN_237 = re.compile(r"(?<![0-9-])237(?![0-9])")
ORDER = ["track_sidewalk_separate", "track_other", "separate_cycleway", "combined_foot"]


def bicycle_only_sign(sign):
    return bool(sign) and SIGN_237.search(sign) is not None and "240" not in sign and "241" not in sign


def side_value(tags, side, key):
    """(source key, value) of a `cycleway:<side>:<key>`, falling back to `cycleway:both:` and `cycleway:`."""
    for prefix in (f"cycleway:{side}:", "cycleway:both:", "cycleway:"):
        if prefix + key in tags:
            return prefix + key, tags[prefix + key]
    return None, None


def side_type(tags, side):
    return tags.get(f"cycleway:{side}") or tags.get("cycleway:both") or tags.get("cycleway")


def sidewalk(tags, side):
    value = tags.get(f"sidewalk:{side}") or tags.get("sidewalk:both")
    if value is None and tags.get("sidewalk") in ("separate", "no", "none"):
        value = tags["sidewalk"]
    return value


def carriageway_side(tags, side):
    """Side of the carriageway, seen in the riding direction of the track (as tilda-geo reads `separation:*`)."""
    _, oneway = side_value(tags, side, "oneway")
    if oneway is None:
        oneway = "yes" if side == "right" or tags.get("oneway") == "yes" else "-1"
    if side == "left" and oneway == "yes":
        return "right"
    if side == "right" and oneway == "-1":
        return "left" if tags.get("oneway") == "-1" else "right"
    return "left"


class Reader(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.hits = []

    def way(self, w):
        tags = {t.k: t.v for t in w.tags}
        hw = tags.get("highway")
        if hw is None:
            return
        hit = None
        if hw in SEPARATE_HIGHWAYS:
            if any(tags.get(k) in CROSSING for k in ("cycleway", "path", "footway")):
                return
            if tags.get("segregated") in ("yes", "no") and bicycle_only_sign(tags.get("traffic_sign")):
                group = "combined_foot" if tags.get("foot") in ("yes", "designated") else "separate_cycleway"
                hit = {"group": group, "sides": [{
                    "side": None, "segregated_key": "segregated", "segregated": tags["segregated"],
                    "sign_key": "traffic_sign", "sign": tags["traffic_sign"],
                }]}
        else:
            sides = []
            for side in ("left", "right"):
                if side_type(tags, side) != "track":
                    continue
                seg_key, seg = side_value(tags, side, "segregated")
                sign_key, sign = side_value(tags, side, "traffic_sign")
                if seg not in ("yes", "no") or not bicycle_only_sign(sign):
                    continue
                _, separation = side_value(tags, side, f"separation:{carriageway_side(tags, side)}")
                sides.append({
                    "side": side, "segregated_key": seg_key, "segregated": seg, "sign_key": sign_key, "sign": sign,
                    "sidewalk": sidewalk(tags, side), "pbl": separation in PHYSICAL,
                })
            if sides:
                separate = all(s["sidewalk"] == "separate" for s in sides)
                hit = {"group": "track_sidewalk_separate" if separate else "track_other", "sides": sides}
        if hit is None:
            return
        try:
            lonlat = [(round(n.lon, 7), round(n.lat, 7)) for n in w.nodes]
        except osmium.InvalidLocationError:
            return
        hit.update({"id": w.id, "tags": tags, "lonlat": lonlat})
        self.hits.append(hit)


SIDE_DE = {"left": "links", "right": "rechts"}


def separate_pbl(tags):
    """A way of its own with a physical separation towards the carriageway (left in the riding direction)."""
    side = "right" if tags.get("oneway") == "-1" else "left"
    separation = tags.get(f"separation:{side}") or tags.get("separation:both")
    if side == "left":
        separation = separation or tags.get("separation")
    return separation in PHYSICAL


def pbl_sides(hit):
    """The sides of a hit that would be a PBL without `segregated`."""
    if hit["group"] in ("track_sidewalk_separate", "track_other"):
        return [s for s in hit["sides"] if s["pbl"]]
    if hit["group"] == "separate_cycleway" and separate_pbl(hit["tags"]):
        return hit["sides"]
    return []


def task(hit, sides):
    tags = hit["tags"]
    keys = sorted({s["segregated_key"] for s in sides})
    removed = ", ".join(f"`{k}={tags[k]}`" for k in keys)
    if sides[0]["side"]:
        where = "Der Radweg " + " und ".join(SIDE_DE[s["side"]] for s in sides) + " auf der Straßenlinie"
    else:
        where = "Dieser separat gezeichnete Radweg"
    name = tags.get("name") or tags.get("is_sidepath:of:name") or f"way/{hit['id']}"
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": hit["lonlat"]},
        "properties": {
            "task_id": f"way-{hit['id']}",
            "title": f"{name}: segregated entfernen",
            "description": f"{where} ist mit **Z. 237** beschildert und hat zur Fahrbahn eine physische Trennung "
                           f"(Poller, Leitboys o. ä.): eine Protected Bike Lane. `segregated` beschreibt die Trennung "
                           f"von einem Gehweg auf demselben Weg und gehört hier nicht hin.\n\n"
                           f"Bitte {removed} entfernen.",
            "osm": [f"way/{hit['id']}"],
            "links": [
                "https://wiki.openstreetmap.org/wiki/DE:Key:segregated",
                f"https://www.openstreetmap.org/way/{hit['id']}",
            ],
            "options": [{"id": "remove-segregated", "label": "segregated entfernen", "remove": keys}],
            "group": hit["group"],
        },
    }


def main(pbf, out_dir):
    header = osmium.io.Reader(pbf, osmium.osm.osm_entity_bits.NOTHING).header()
    extract = (header.get("osmosis_replication_timestamp") or header.get("timestamp") or "?")[:10]
    reader = Reader()
    reader.apply_file(pbf, locations=True, idx="flex_mem")

    rows = []
    groups = Counter()
    pbl = Counter()
    features = []
    shared_source = 0
    for hit in sorted(reader.hits, key=lambda h: h["id"]):
        groups[hit["group"]] += 1
        sides = hit["sides"]
        if any(s["segregated_key"] in ("cycleway:both:segregated", "cycleway:segregated") for s in sides) and len(sides) == 1:
            shared_source += 1
        sides_pbl = pbl_sides(hit)
        if sides_pbl:
            features.append(task(hit, sides_pbl))
            pbl[hit["group"]] += len(sides_pbl)
        rows.append({
            "way": hit["id"], "group": hit["group"], "highway": hit["tags"]["highway"],
            "name": hit["tags"].get("name", ""), "sides": "|".join(s["side"] or "-" for s in sides),
            "segregated": "|".join(s["segregated"] for s in sides), "sign": "|".join(s["sign"] for s in sides),
            "pbl": bool(sides_pbl),
        })

    with open(f"{out_dir}/ways.csv", "w") as f:
        keys = list(rows[0])
        f.write(",".join(keys) + "\n")
        for r in rows:
            f.write(",".join(json.dumps(r[k], ensure_ascii=False) if isinstance(r[k], str) else str(r[k]) for k in keys) + "\n")

    doc = {
        "type": "FeatureCollection",
        "maid_tasks": {
            "version": 1,
            "list_id": f"berlin-pbl-segregated-{LIST_DATE[:7]}",
            "title": "Berlin: segregated an Protected Bike Lanes entfernen",
            "description": "Radwege mit **Z. 237** und physischer Trennung zur Fahrbahn (Protected Bike Lanes), die "
                           "`segregated` tragen. `segregated` beschreibt die Trennung von einem Gehweg auf demselben Weg; "
                           "TILDA erkennt diese Radwege deshalb nicht als Protected Bike Lane. Bitte `segregated` "
                           f"entfernen (Auszug {extract}, Liste {LIST_DATE}).",
        },
        "features": features,
    }
    with open(f"{out_dir}/berlin-pbl-segregated.json", "w") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    summary = {
        "extract": extract,
        "ways": {g: groups[g] for g in ORDER},
        "track_sides": sum(len(h["sides"]) for h in reader.hits if h["group"].startswith("track")),
        "pbl_sides": {g: pbl[g] for g in ORDER if g != "combined_foot"},
        "tasks": len(features),
        "single_side_with_shared_segregated_key": shared_source,
    }
    with open(f"{out_dir}/summary.json", "w") as f:
        json.dump(summary, f, indent=1)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
