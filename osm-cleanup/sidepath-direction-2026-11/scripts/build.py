"""Separate bicycle ways whose riding direction does not fit their drawing direction (Berlin, November 2026).

Usage (from the project root):
  .venv/bin/python -I osm-cleanup/sidepath-direction-2026-11/scripts/build.py <berlin.osm.pbf> <output dir>

Reads every way of its own that bicycles ride on (`highway=cycleway`, or path/footway/bridleway with
`bicycle=designated|yes`) with a one-way direction (`oneway:bicycle`, else `oneway`: `yes` or `-1`). Road sides
(`cycleway:left:oneway=-1` on the road line) are not read.

For each such way the script looks for the road next to it: points every 5 m along the way, the nearest road within
MAX_DIST that runs parallel (angle below MAX_ANGLE). The side of the road and the road's direction give the direction
the traffic on that side runs in: on a two-way road with the line on the right, against it on the left; on a
one-way road with the road on the right, the left side is not judged (on a dual carriageway that is the
median: only the nearest carriageway counts). Points next to a roundabout are not judged. Each point votes "fits" or "against"; a way is
judged when at least MIN_VOTES points voted and SHARE of them agree.

Groups (one MAID task per way):
- `reverse_ok`: `-1`, and riding against the line fits the traffic next to it. The tag is right, the geometry is
  hard to read: reverse the way and tag `yes`.
- `reverse_unjudged`: `-1`, no road found next to it (or not parallel enough). Reverse the way and tag `yes`, after a
  look at the direction.
- `minus1_wrong`: `-1`, but riding against the line runs against the traffic next to it. Probably the line was drawn
  right and `-1` is wrong: tag `yes`.
- `yes_wrong`: `yes`, but riding with the line runs against the traffic next to it. Either the way was drawn the
  wrong way round (reverse it, keep `yes`) or it is a signed two-way cycle path (`no`).
"""

import json
import math
from datetime import date
import sys
from collections import Counter

import osmium
import shapely
from pyproj import Transformer
from shapely.geometry import LineString, Point
from shapely.strtree import STRtree

LIST_DATE = date.today().isoformat()
SAMPLE_STEP = 5.0  # m between points along a bicycle way
MAX_DIST = 25.0  # m from a point to the road line
MAX_ANGLE = 30.0  # degrees between the way and the road
MIN_VOTES = 3
SHARE = 0.8

ROADS = {
    "motorway_link", "trunk", "trunk_link", "primary", "primary_link", "secondary", "secondary_link",
    "tertiary", "tertiary_link", "unclassified", "residential", "living_street",
}
PATHS = {"path", "footway", "bridleway"}
SKIP_SUBTYPES = {"crossing", "traffic_island", "link"}

to_utm = Transformer.from_crs("EPSG:4326", "EPSG:25833", always_xy=True).transform


def bike_direction(tags):
    """(key, value) of the one-way direction for bicycles on a way of its own, or None."""
    for key in ("oneway:bicycle", "oneway"):
        value = tags.get(key)
        if value is not None:
            if value in ("yes", "1", "true"):
                return key, "yes"
            if value in ("-1", "reverse"):
                return key, "-1"
            return None  # no, alternating, …: not a one-way
    return None


def is_bike_way(tags):
    hw = tags.get("highway")
    if tags.get("area") == "yes":
        return False
    if hw == "cycleway":
        return tags.get("cycleway") not in SKIP_SUBTYPES
    if hw in PATHS:
        if tags.get("footway") in SKIP_SUBTYPES or tags.get("path") in SKIP_SUBTYPES:
            return False
        return tags.get("bicycle") in ("designated", "yes")
    return False


def road_direction(tags):
    """+1 one-way with the line, -1 one-way against it, 0 two-way."""
    oneway = tags.get("oneway")
    if oneway in ("yes", "1", "true"):
        return 1
    if oneway == "-1":
        return -1
    if oneway is None and tags.get("junction") in ("roundabout", "circular"):
        return 1
    if tags.get("highway") == "motorway_link" and oneway != "no":
        return 1
    return 0


class Reader(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.bikes = []
        self.roads = []

    def way(self, w):
        tags = {t.k: t.v for t in w.tags}
        hw = tags.get("highway")
        if hw is None:
            return
        is_road = hw in ROADS
        direction = bike_direction(tags) if is_bike_way(tags) else None
        if not is_road and direction is None:
            return
        try:
            lonlat = [(n.lon, n.lat) for n in w.nodes]
        except osmium.InvalidLocationError:
            return
        if len(lonlat) < 2:
            return
        utm = LineString([to_utm(lon, lat) for lon, lat in lonlat])
        if utm.length == 0:
            return
        if is_road:
            self.roads.append({"id": w.id, "tags": tags, "geom": utm, "dir": road_direction(tags)})
        if direction is not None:
            self.bikes.append({
                "id": w.id, "tags": tags, "lonlat": lonlat, "geom": utm,
                "key": direction[0], "value": direction[1],
            })


def separate_rank(tags, side):
    """0: the road says its cycle path on this side is a way of its own, 1: its sidewalk, 2: neither."""
    if "separate" in (tags.get(f"cycleway:{side}"), tags.get("cycleway:both")):
        return 0
    for prefix in ("sidewalk", "sidewalk:bicycle"):
        if "separate" in (tags.get(f"{prefix}:{side}"), tags.get(f"{prefix}:both")):
            return 1
    return 1 if tags.get("sidewalk") == "separate" else 2


def heading(line, distance):
    """Unit vector of the line at the given distance along it."""
    a = line.interpolate(max(0.0, distance - 1.0))
    b = line.interpolate(min(line.length, distance + 1.0))
    dx, dy = b.x - a.x, b.y - a.y
    norm = math.hypot(dx, dy)
    return (dx / norm, dy / norm) if norm else (0.0, 0.0)


def judge(bike, roads, tree):
    """Votes of the points along the way: Counter of 'fits' / 'against' / 'none', and the road names it ran along."""
    line = bike["geom"]
    riding = 1 if bike["value"] == "yes" else -1
    votes = Counter()
    names = Counter()
    n = max(1, int(line.length // SAMPLE_STEP))
    for i in range(n + 1):
        d = min(line.length, (i + 0.5) * line.length / (n + 1))
        p = line.interpolate(d)
        bx, by = heading(line, d)
        best = None
        for idx in tree.query(p.buffer(MAX_DIST)):
            road = roads[idx]
            rd = road["geom"].project(p)
            q = road["geom"].interpolate(rd)
            dist = p.distance(q)
            if dist > MAX_DIST or dist < 0.5:
                continue  # 0.5 m: the bicycle way shares the road's node, not a sidepath
            rx, ry = heading(road["geom"], rd)
            cos = bx * rx + by * ry
            if abs(cos) < math.cos(math.radians(MAX_ANGLE)):
                continue
            # a road that says its cycle path (then: sidewalk) on this side is mapped separately wins over a nearer
            # one: a side road (Nebenfahrbahn, a parallel one-way street) is often nearer than the carriageway
            side = "left" if rx * (p.y - q.y) - ry * (p.x - q.x) > 0 else "right"
            rank = (separate_rank(road["tags"], side), dist)
            if best is None or rank < best[0]:
                best = (rank, road, rx, ry, q, cos)
        if best is None:
            votes["none"] += 1
            continue
        _, road, rx, ry, q, cos = best
        if road["tags"].get("junction") in ("roundabout", "circular"):
            votes["none"] += 1  # around a roundabout the paths often run both ways (as tilda-schemas)
            continue
        # side: cross product of the road direction and the vector road → point; > 0 is left
        cross = rx * (p.y - q.y) - ry * (p.x - q.x)
        side = "left" if cross > 0 else "right"
        if road["dir"] == 0:
            traffic = 1 if side == "right" else -1  # relative to the road line
        else:
            if side == "left":
                votes["none"] += 1  # left of a one-way road: either direction is possible
                continue
            traffic = road["dir"]
        bike_vs_road = 1 if cos > 0 else -1  # bicycle line with (+1) or against (-1) the road line
        ride_vs_road = bike_vs_road * riding
        votes["fits" if ride_vs_road == traffic else "against"] += 1
        if road["tags"].get("name"):
            names[road["tags"]["name"]] += 1
    return votes, names


def classify(bike, votes):
    judged = votes["fits"] + votes["against"]
    verdict = None
    if judged >= MIN_VOTES:
        if votes["fits"] >= SHARE * judged:
            verdict = "fits"
        elif votes["against"] >= SHARE * judged:
            verdict = "against"
    if bike["value"] == "-1":
        if verdict == "fits":
            return "reverse_ok"
        if verdict == "against":
            return "minus1_wrong"
        return "reverse_unjudged"
    if verdict == "against":
        return "yes_wrong"
    return None


KIND = {"cycleway": "Radweg", "path": "Weg", "footway": "Gehweg", "bridleway": "Reitweg"}

TEXTS = {
    "reverse_ok": {
        "title": "{label}: Weg umdrehen statt {key}=-1",
        "description": (
            "Dieser {kind} ist gegen die Fahrtrichtung gezeichnet und mit `{key}=-1` gedreht. Die Richtung passt zum "
            "Verkehr auf der Straßenseite daneben{road}.\n\n"
            "Fachlich ist das richtig, aber schwer zu lesen: Wer die Linie sieht, erwartet die Fahrt in "
            "Linienrichtung. TILDA dreht solche Wege bei der Verarbeitung schon um. Sauberer ist es, den Weg in OSM "
            "umzudrehen: Die Antwort „Weg umdrehen“ dreht die Linie und setzt `{key}=yes`, die Fahrtrichtung bleibt."
        ),
    },
    "reverse_unjudged": {
        "title": "{label}: Weg umdrehen statt {key}=-1",
        "description": (
            "Dieser {kind} ist gegen die Fahrtrichtung gezeichnet und mit `{key}=-1` gedreht. Eine parallele Straße "
            "daneben wurde nicht gefunden, die Richtung ist also nicht automatisch geprüft.\n\n"
            "Bitte erst prüfen, ob die Fahrt gegen die Linienrichtung stimmt (Schilder, Luftbild, Mapillary). Dann "
            "„Weg umdrehen“: Das dreht die Linie und setzt `{key}=yes`, die Fahrtrichtung bleibt."
        ),
    },
    "minus1_wrong": {
        "title": "{label}: {key}=-1 führt gegen den Verkehr daneben",
        "description": (
            "Dieser {kind} hat `{key}=-1`, man fährt also gegen die Linienrichtung. Damit fährt man aber gegen den "
            "Verkehr auf der Straßenseite daneben{road}.\n\n"
            "Wahrscheinlich ist die Linie schon richtig herum gezeichnet und `-1` ist falsch. Dann `{key}=yes`. "
            "Ist es ein Zweirichtungsradweg (Zeichen 237/240/241 mit Zusatz 1000-31/33 in beide Richtungen), `no`."
        ),
    },
    "yes_wrong": {
        "title": "{label}: Einbahn-Radweg läuft gegen den Verkehr daneben",
        "description": (
            "Dieser {kind} hat `{key}=yes`, man fährt also in Linienrichtung. Die Linie läuft aber gegen den Verkehr "
            "auf der Straßenseite daneben{road}. So fährt der Radverkehr nur gegen die Fahrtrichtung.\n\n"
            "Meist ist die Linie andersherum gezeichnet worden: dann „Weg umdrehen“, `yes` bleibt. Ist es ein "
            "Zweirichtungsradweg (Zeichen 237/240/241 mit Zusatz 1000-31/33 in beide Richtungen), `no`. Nur wenn "
            "wirklich ein Einbahn-Radweg gegen den Verkehr ausgeschildert ist, „Richtung stimmt“."
        ),
    },
}

ORDER = ["yes_wrong", "minus1_wrong", "reverse_ok", "reverse_unjudged"]


def options(group, bike):
    key = bike["key"]
    # Maid's reverse (since 0b6921a) turns `-1` into `yes` on the first key that gives a direction, `oneway` then
    # `oneway:bicycle`. The `set` after it is a safeguard for older Maid versions and other editors.
    reverse = {
        "id": "reverse",
        "label": "Weg umdrehen",
        "description": f"Dreht die Linie (wie Umkehren, Taste `V`). Danach `{key}=yes`.",
        "operations": [{"op": "reverse"}],
        "set": {key: "yes"},
    }
    two_way = {
        "id": "two-way",
        "label": "Zweirichtungsradweg (beide Richtungen)",
        "description": "Nur mit Verkehrszeichen für beide Richtungen.",
        "set": {key: "no"},
    }
    if group == "minus1_wrong":
        return [
            {"id": "yes", "label": f"{key}=yes: Linie ist richtig herum, -1 war falsch", "set": {key: "yes"}},
            two_way,
            {"id": "keep", "label": "Richtung stimmt (gegen die Linienrichtung)", "action": "none"},
        ]
    if group == "yes_wrong":
        return [
            reverse,
            two_way,
            {"id": "keep", "label": "Richtung stimmt (ausgeschildert gegen den Verkehr)", "action": "none"},
        ]
    return [reverse, {"id": "keep", "label": "So lassen", "action": "none"}]


def task(group, bike, names):
    tags = bike["tags"]
    road = names.most_common(1)[0][0] if names else None
    kind = KIND.get(tags["highway"], "Weg")
    label = tags.get("name") or (f"{kind} an {road}" if road else f"{kind} way/{bike['id']}")
    fmt = {
        "label": label, "kind": kind, "key": bike["key"],
        "road": f" ({road})" if road else "",
    }
    text = TEXTS[group]
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": [[round(x, 7), round(y, 7)] for x, y in bike["lonlat"]]},
        "properties": {
            "task_id": f"way-{bike['id']}",
            "title": text["title"].format(**fmt),
            "description": text["description"].format(**fmt),
            "osm": [f"way/{bike['id']}"],
            "links": [
                "https://wiki.openstreetmap.org/wiki/DE:Key:oneway",
                f"https://www.openstreetmap.org/way/{bike['id']}",
            ],
            "options": options(group, bike),
            "group": group,
        },
    }


def main(pbf, out_dir):
    reader = Reader()
    header = osmium.io.Reader(pbf, osmium.osm.osm_entity_bits.NOTHING).header()
    extract = (header.get("osmosis_replication_timestamp") or header.get("timestamp") or "?")[:10]
    reader.apply_file(pbf, locations=True, idx="flex_mem")
    roads = reader.roads
    tree = STRtree([r["geom"] for r in roads])
    print(f"{len(reader.bikes)} bicycle ways with a direction, {len(roads)} roads", file=sys.stderr)

    rows = []
    groups = Counter()
    features = {g: [] for g in ORDER}
    for bike in reader.bikes:
        votes, names = judge(bike, roads, tree)
        group = classify(bike, votes)
        rows.append({
            "way": bike["id"], "highway": bike["tags"]["highway"], "key": bike["key"], "value": bike["value"],
            "length_m": round(bike["geom"].length, 1), "fits": votes["fits"], "against": votes["against"],
            "none": votes["none"], "road": names.most_common(1)[0][0] if names else "", "group": group or "",
        })
        if group:
            groups[group] += 1
            features[group].append(task(group, bike, names))
    with open(f"{out_dir}/ways.csv", "w") as f:
        keys = list(rows[0])
        f.write(",".join(keys) + "\n")
        for r in rows:
            f.write(",".join(json.dumps(r[k]) if isinstance(r[k], str) else str(r[k]) for k in keys) + "\n")

    counts = {g: groups[g] for g in ORDER}
    lists = {
        "berlin-radweg-richtung-falsch": (
            ["yes_wrong", "minus1_wrong"],
            "Berlin: Einbahn-Radwege gegen den Verkehr daneben",
            "Separat gezeichnete Radwege im Seitenraum, auf denen man laut `oneway`/`oneway:bicycle` gegen den Verkehr "
            "auf der Straßenseite daneben fährt. Meist ist die Linie falsch herum gezeichnet oder das `-1` falsch. "
            f"Erkannt über die Geometrie: Seite und Richtung der parallelen Straße (Auszug {extract}, Liste {LIST_DATE}).",
        ),
        "berlin-radweg-umdrehen": (
            ["reverse_ok", "reverse_unjudged"],
            "Berlin: Radwege umdrehen statt oneway=-1",
            "Separat gezeichnete Radwege mit `oneway=-1` oder `oneway:bicycle=-1`. Die Richtung stimmt (oder ist nicht "
            "geprüft), aber die Linie läuft gegen die Fahrtrichtung. Umgedreht mit `yes` sind sie leichter zu "
            f"verstehen (Auszug {extract}, Liste {LIST_DATE}).",
        ),
    }
    for list_id, (grps, title, description) in lists.items():
        feats = [f for g in grps for f in features[g]]
        doc = {
            "type": "FeatureCollection",
            "maid_tasks": {"version": 1, "list_id": f"{list_id}-{LIST_DATE[:7]}", "title": title,
                           "description": description},
            "features": feats,
        }
        with open(f"{out_dir}/{list_id}.json", "w") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
    by_value = Counter((b["key"], b["value"]) for b in reader.bikes)
    summary = {"groups": counts, "bicycle_ways": {f"{k}={v}": n for (k, v), n in by_value.items()}}
    with open(f"{out_dir}/summary.json", "w") as f:
        json.dump(summary, f, indent=1)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
