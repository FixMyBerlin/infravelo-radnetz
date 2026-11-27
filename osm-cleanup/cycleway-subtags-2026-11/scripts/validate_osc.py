"""Check the osmChange files against the extract they were built from.

Usage (from the project root):
  .venv/bin/python -I osm-cleanup/cycleway-subtags-2026-11/scripts/validate_osc.py <berlin.osm.pbf> <osc>...

Per way: same version and node list as in the extract, at least one change, only `cycleway:*` sub-keys removed,
nothing added or changed except the direction of a track side (`cycleway:<side>:oneway` with the side's value).
"""

import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter

import osmium

REMOVABLE = re.compile(r"^cycleway(:left|:right|:both)?:.+$")
TRACK_ONEWAY = re.compile(r"^cycleway:(left|right):oneway$")


class Reader(osmium.SimpleHandler):
    def __init__(self, ids):
        super().__init__()
        self.ids, self.ways = ids, {}

    def way(self, w):
        if w.id in self.ids:
            self.ways[w.id] = (w.version, [n.ref for n in w.nodes], {t.k: t.v for t in w.tags})


def main(pbf, paths):
    roots = {path: ET.parse(path).getroot() for path in paths}
    ids = [int(way.get("id")) for root in roots.values() for way in root.iter("way")]
    reader = Reader(set(ids))
    reader.apply_file(pbf)
    errors = [f"way {i} is in more than one place" for i, n in Counter(ids).items() if n > 1]
    for path, root in roots.items():
        removed, added = Counter(), Counter()
        for way in root.iter("way"):
            wid = int(way.get("id"))
            version, nodes, before = reader.ways[wid]
            after = {t.get("k"): t.get("v") for t in way.iter("tag")}
            gone = set(before) - set(after)
            changed = {k: v for k, v in after.items() if before.get(k) != v}
            problems = []
            if int(way.get("version")) != version:
                problems.append("version")
            if [int(n.get("ref")) for n in way.iter("nd")] != nodes:
                problems.append("nodes")
            if not gone and not changed:
                problems.append("no change")
            if any(not REMOVABLE.match(k) for k in gone):
                problems.append(f"removed {sorted(k for k in gone if not REMOVABLE.match(k))}")
            for k, v in changed.items():
                side = TRACK_ONEWAY.match(k)
                track = side and (before.get(f"cycleway:{side.group(1)}") or before.get("cycleway:both")
                                  or before.get("cycleway")) == "track"
                if not track or k in before:
                    problems.append(f"set {k}={v}")
            removed.update(f"{re.sub(r'^cycleway(:left|:right|:both)?:', '', k)}={before[k]}" for k in gone)
            added.update(f"{k}={v}" for k, v in changed.items())
            if problems:
                errors.append(f"{path}: way {wid}: {', '.join(problems)}")
        print(f"{path}: {sum(1 for _ in root.iter('way'))} ways")
        print("  removed:", ", ".join(f"{k} {n}" for k, n in removed.most_common(12)), "…")
        print("  set:", dict(added))
    print("\n".join(errors) or "OK")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
