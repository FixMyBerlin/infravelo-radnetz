"""Upload package per automatic way, from the length of the tagged stretch it belongs to.

A correct `cycleway:left:oneway=yes` (or `:both:oneway=yes`) needs a one-way street. The candidates have no one-way
rule, so the tag can only be right where `oneway=yes` is missing on the road. One-way streets with cycling infra on
the left are short in Berlin: in the extract of 2026-11-21 all 20 such stretches that are not a dual carriageway are
below 190 m (median 47 m). A long tagged stretch is therefore a tagging error with high confidence.

Stretch: ways with the same name (unnamed: same `highway`) that share a node and are all candidates (auto or MAID).

Packages:
  1-sicher  stretch >= MIN_LENGTH_M
  2-kurz    shorter stretch, but nothing hints at a one-way street, or the way itself shows two-way traffic
  maid      shorter stretch that hints at a one-way street (whole street shorter than MIN_LENGTH_M, touches a one-way
            way of the same name, no name, or `*_link`) and the way shows no two-way traffic
            (no `*:backward` tag, no `oneway=no`, no `lanes>=2` without `lanes:forward`)
"""

import json
import math
import os
import subprocess
import tempfile
from collections import defaultdict

MIN_LENGTH_M = 200
ROADS = {"motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential", "service",
         "living_street", "busway", "trunk_link", "primary_link", "secondary_link", "tertiary_link"}


def _lengths(pbf):
    """Length in metres of every road way in the extract."""
    with tempfile.TemporaryDirectory() as tmp:
        roads = os.path.join(tmp, "roads.osm.pbf")
        seq = os.path.join(tmp, "roads.geojsonseq")
        subprocess.run(["osmium", "tags-filter", pbf, "w/highway=" + ",".join(sorted(ROADS)), "-o", roads, "--overwrite"],
                       check=True, capture_output=True)
        subprocess.run(["osmium", "export", roads, "-f", "geojsonseq", "-a", "type,id", "--geometry-types=linestring",
                        "-o", seq, "--overwrite"], check=True, capture_output=True)
        out = {}
        with open(seq, encoding="utf-8") as f:
            for line in f:
                ft = json.loads(line.lstrip("\x1e"))
                c = ft["geometry"]["coordinates"]
                out[int(ft["properties"]["@id"])] = sum(_haversine(a, b) for a, b in zip(c, c[1:]))
        return out


def _haversine(a, b):
    lon1, lat1, lon2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371008.8 * math.asin(math.sqrt(h))


def _key(tags):
    return tags.get("name") or "#" + tags.get("highway", "")


def _chains(ids, ways):
    parent = {i: i for i in ids}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    first = {}
    for i in ids:
        k = _key(ways[i]["tags"])
        for n in ways[i]["nodes"]:
            o = first.setdefault((k, n), i)
            if o != i:
                parent[find(i)] = find(o)
    res = defaultdict(list)
    for i in ids:
        res[find(i)].append(i)
    return list(res.values())


def two_way_evidence(tags):
    if any(":backward" in k or k.endswith("backward") for k in tags):
        return True
    if tags.get("oneway") == "no":
        return True
    try:
        return int(tags.get("lanes", "0")) >= 2 and "lanes:forward" not in tags
    except ValueError:
        return False


def packages(ways, candidates, auto, pbf):
    """Return {way id: (package, stretch length m, reason)} for the automatic ways.
    ways: all highway ways of the extract (opl), candidates: auto + MAID ids, auto: auto ids."""
    length = _lengths(pbf)
    roads = [i for i, w in ways.items() if w["tags"].get("highway") in ROADS and i in length]
    street_of = {}
    for c in _chains(roads, ways):
        m = sum(length[i] for i in c)
        for i in c:
            street_of[i] = m
    by_node = defaultdict(list)
    for i in roads:
        for n in ways[i]["nodes"]:
            by_node[n].append(i)

    out = {}
    for c in _chains([i for i in candidates if i in length], ways):
        cs = set(c)
        m = sum(length[i] for i in c)
        tags = ways[c[0]]["tags"]
        name = tags.get("name")
        touch = {o for i in c for n in ways[i]["nodes"] for o in by_node[n]} - cs
        hints = []
        if street_of[c[0]] < MIN_LENGTH_M:
            hints.append(f"ganze Straße kürzer als {MIN_LENGTH_M} m")
        if name and any(ways[o]["tags"].get("name") == name and ways[o]["tags"].get("oneway") in ("yes", "-1") for o in touch):
            hints.append("grenzt an ein Einbahnstück gleichen Namens")
        if not name:
            hints.append("ohne Namen")
        if tags.get("highway", "").endswith("_link"):
            hints.append("Zufahrt (*_link)")
        for i in c:
            if i not in auto:
                continue
            if m >= MIN_LENGTH_M:
                out[i] = ("1-sicher", round(m), "")
            elif hints and not two_way_evidence(ways[i]["tags"]):
                out[i] = ("maid", round(m), f"kurzer Abschnitt ({round(m)} m), " + ", ".join(hints)
                          + ", kein Hinweis auf Gegenverkehr am Weg")
            else:
                out[i] = ("2-kurz", round(m), "")
    return out
