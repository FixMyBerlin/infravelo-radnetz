"""Check every .osc against the source extract: same version and node list, only `cycleway:*:oneway` keys removed,
and nothing added or changed except a side default on a track side (`cycleway:left:oneway=-1`, `cycleway:right:oneway=yes`). Usage: python3 -I validate_osc.py <ways.opl> <osc>..."""

import os
import re
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from opl import read_ways  # noqa: E402

ALLOWED = re.compile(r"^cycleway(:left|:right|:both)?:oneway$")
SIDE_DEFAULT = {"cycleway:left:oneway": "-1", "cycleway:right:oneway": "yes"}


def main():
    src = {w["id"]: w for w in read_ways(sys.argv[1])}
    ok = True
    for path in sys.argv[2:]:
        root = ET.parse(path).getroot()
        ids, removed, added = set(), {}, {}
        for way in root.iter("way"):
            wid = int(way.get("id"))
            if wid in ids:
                print(f"{path}: duplicate way {wid}")
                ok = False
            ids.add(wid)
            orig = src[wid]
            tags = {t.get("k"): t.get("v") for t in way.iter("tag")}
            nodes = [int(n.get("ref")) for n in way.iter("nd")]
            errs = []
            if int(way.get("version")) != orig["version"]:
                errs.append("version")
            if nodes != orig["nodes"]:
                errs.append("nodes")
            gone = set(orig["tags"]) - set(tags)
            changed = {k: v for k, v in tags.items() if orig["tags"].get(k) != v}
            if any(SIDE_DEFAULT.get(k) != v for k, v in changed.items()):
                errs.append(f"tag added/changed {changed}")
            for k, v in changed.items():
                added[f"{k}={v}"] = added.get(f"{k}={v}", 0) + 1
            if not (gone or changed) or any(not ALLOWED.match(k) for k in gone):
                errs.append(f"removed {sorted(gone)}")
            for k in gone:
                removed[f"{k}={orig['tags'][k]}"] = removed.get(f"{k}={orig['tags'][k]}", 0) + 1
            if errs:
                ok = False
                print(f"{path}: way {wid}: {', '.join(errs)}")
        print(f"{os.path.basename(path)}: {len(ids)} ways, removed {removed}, set {added}")
    print("OK" if ok else "FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
