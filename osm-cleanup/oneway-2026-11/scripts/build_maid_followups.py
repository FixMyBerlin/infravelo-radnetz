"""Two MAID task files found while checking the TILDA corrections against the Rust pipeline (2026-11-22).

Usage (from the project folder, after run.sh has built data/):
  python3 -I scripts/build_maid_followups.py data/hw.opl data/berlin-internal.osm.pbf output

1. maid__track-direction.json: tracks tagged on the road (`cycleway:<side>=track`) without a direction
   (`cycleway:<side>:oneway`, `:both:oneway`, `cycleway:oneway`). tilda-geo then guesses the direction from the
   other side of the road. Selection: the ways in `track_ids_datensatz_c.txt` (they change Datensatz C) and every
   such side in the infraVelo net (`../../tilda-pseudo-tags/infravelo-netz.csv`).
   Default answer: the side default (left `-1`, right `yes`), one click.
2. maid__lane-foot.json: lanes on the road (`cycleway:<side>=lane`) with `traffic_mode:<left|right>=foot` or
   `segregated`. tilda-geo reads them as a foot and cycle path next to the road (`footAndCyclewaySegregated_adjoining`),
   which a lane on the carriageway cannot be. Default answer for a Schutzstreifen (`lane=advisory`, always on the
   carriageway): remove the foot tags.
"""

import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_cleanup import geometries  # noqa: E402
from opl import read_ways  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHECK_DATE = "2026-11-22"
SIDE_DEFAULT = {"left": "-1", "right": "yes"}
SIDE_DE = {"left": "links", "right": "rechts"}


def infra(t, s):
    return t.get(f"cycleway:{s}") or t.get("cycleway:both") or t.get("cycleway")


def direction(t, s):
    return t.get(f"cycleway:{s}:oneway") or t.get("cycleway:both:oneway") or t.get("cycleway:oneway")


def osm_link(i):
    return f"https://www.openstreetmap.org/way/{i}"


def track_tasks(ways, ids, net):
    tasks = []
    for i, w in sorted(ways.items()):
        t = w["tags"]
        if t.get("oneway") in ("-1", "reversible") or t.get("junction") in ("roundabout", "circular"):
            continue
        sides = [s for s in ("left", "right") if infra(t, s) == "track" and not direction(t, s)]
        in_net = [s for s in sides if net.get((i, f"cycleway/{s}")) or net.get((i, ""))]
        if not sides or (i not in ids and not in_net):
            continue
        # On a one-way road the wiki default of both sides is the road direction; only the right side is unambiguous.
        if t.get("oneway") == "yes":
            sides = [s for s in sides if s == "right"]
            if not sides:
                continue
        default = {f"cycleway:{s}:oneway": SIDE_DEFAULT[s] for s in sides}
        options = [{
            "id": "one-way",
            "label": "Einrichtungsradweg in Fahrtrichtung der Fahrbahn daneben (Standard)",
            "description": "Links fährt man gegen die Linienrichtung (`-1`), rechts mit ihr (`yes`).",
            "set": default,
        }]
        for s in sides:
            options.append({
                "id": f"two-way-{s}",
                "label": f"Radweg {SIDE_DE[s]} ist ein Zweirichtungsradweg",
                "description": "Nur mit Verkehrszeichen (Z 237/240/241 mit Zusatz 1000-31/33) oder eindeutiger Markierung.",
                "set": {**default, f"cycleway:{s}:oneway": "no"},
            })
        side_text = " und ".join(SIDE_DE[s] for s in sides)
        tasks.append((i, {
            "task_id": f"way-{i}",
            "title": f"{t.get('name') or t.get('highway')}: Fahrtrichtung des Radwegs {side_text} angeben",
            "description": (
                f"Der Radweg {side_text} (`cycleway:<Seite>=track`) hat keine Fahrtrichtung. "
                "TILDA muss sie raten: einrichtig, wenn auf der anderen Seite ein Radweg oder eine Spur ist, sonst zweirichtig.\n\n"
                + ("Liegt im infraVelo-Radnetz (Radvorrangnetz).\n\n" if in_net else "")
                + "In Berlin sind Radwege fast immer Einrichtungsradwege (StVO § 2 Abs. 4). `oneway` bezieht sich auf die Linienrichtung."
            ),
            "osm": [f"way/{i}"],
            "links": ["https://wiki.openstreetmap.org/wiki/Key:cycleway:right:oneway", osm_link(i)],
            "options": options,
        }))
    return tasks


def foot_keys(t, s):
    """Keys that make tilda-geo read the lane of side `s` as a foot and cycle path: `traffic_mode:<x>=foot` without a
    separation on that side, or with `separation:<x>=no` (as `foot_next_to_it` in tilda-geo `bikelane_categories.lua`).
    `segregated` goes with them in the fix, but alone it does not trigger the reading."""
    keys = []
    for prefix in (f"cycleway:{s}", "cycleway:both"):
        for k, v in t.items():
            if k.startswith(prefix + ":traffic_mode:") and v == "foot":
                x = k.rsplit(":", 1)[1]
                sep = t.get(f"cycleway:{s}:separation:{x}") or t.get(f"cycleway:both:separation:{x}")
                if sep in (None, "no"):
                    keys.append(k)
    if keys:
        keys += [k for k in (f"cycleway:{s}:segregated", "cycleway:both:segregated") if k in t]
    return keys


def lane_tasks(ways):
    tasks = []
    for i, w in sorted(ways.items()):
        t = w["tags"]
        sides = [s for s in ("left", "right") if infra(t, s) == "lane" and foot_keys(t, s)]
        if not sides:
            continue
        keys = sorted({k for s in sides for k in foot_keys(t, s)})
        lanes = {t.get(f"cycleway:{s}:lane") or t.get("cycleway:both:lane") for s in sides}
        side_text = " und ".join(SIDE_DE[s] for s in sides)
        tag_lines = "\n".join(f"- `{k}={t[k]}`" for k in keys)
        options = [{
            "id": "lane",
            "label": "Spur auf der Fahrbahn, Gehweg dahinter (Bordstein)",
            "description": "Die Fuß-Angaben gehören nicht zur Spur. Sie werden entfernt; der Gehweg ist eigene Geometrie oder `sidewalk`.",
            "remove": keys,
        }]
        both_only = all(f"cycleway:{s}" not in t for s in sides) and t.get("cycleway:both") == "lane"
        per_side = all(t.get(f"cycleway:{s}") == "lane" for s in sides)
        if (both_only and set(sides) == {"left", "right"}) or per_side:
            track_set = {"cycleway:both": "track"} if both_only else {f"cycleway:{s}": "track" for s in sides}
            lane_keys = ["cycleway:both:lane"] if both_only else [f"cycleway:{s}:lane" for s in sides if f"cycleway:{s}:lane" in t]
            options.append({
                "id": "track",
                "label": "Radweg im Seitenraum neben dem Gehweg (getrennter Geh- und Radweg)",
                "description": "Dann ist es kein Schutz- oder Radfahrstreifen: `lane` wird zu `track`, die Fuß-Angaben bleiben.",
                "set": track_set,
                "remove": [k for k in lane_keys if k in t],
            })
        options.append({
            "id": "keep",
            "label": "Die Angaben stimmen so",
            "description": "Nichts ändern, Aufgabe als erledigt markieren. Gern einen Hinweis in `note` ergänzen.",
            "set": {f"cycleway:{sides[0]}:check_date": CHECK_DATE},
        })
        tasks.append((i, {
            "task_id": f"way-{i}",
            "title": f"{t.get('name') or t.get('highway')}: Spur {side_text} mit Fußverkehr prüfen",
            "description": (
                f"Getaggt ist eine Spur auf der Fahrbahn ({', '.join(sorted(x for x in lanes if x)) or 'lane'}) {side_text}, "
                f"zugleich mit Fußverkehr daneben:\n\n{tag_lines}\n\n"
                "Das passt nicht zusammen: Ein Schutz- oder Radfahrstreifen liegt auf der Fahrbahn, ein getrennter Geh- und Radweg im Seitenraum. "
                "TILDA liest es als Geh- und Radweg. Bitte im Luftbild oder in Mapillary prüfen, was es ist."
            ),
            "osm": [f"way/{i}"],
            "links": ["https://wiki.openstreetmap.org/wiki/Key:cycleway", osm_link(i)],
            "options": options,
        }))
    return tasks


def write(path, list_id, title, description, tasks, geoms):
    data = {
        "type": "FeatureCollection",
        "maid_tasks": {"version": 1, "list_id": list_id, "title": title, "description": description},
        "features": [{"type": "Feature", "geometry": geoms[i], "properties": p} for i, p in tasks if i in geoms],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    return len(data["features"])


def main():
    opl, pbf, out = sys.argv[1:4]
    ways = {w["id"]: w for w in read_ways(opl)}
    with open(os.path.join(HERE, "track_ids_datensatz_c.txt"), encoding="utf-8") as f:
        ids = {int(x) for x in f if x.strip() and not x.startswith("#")}
    net = {}
    with open(os.path.join(HERE, "..", "..", "tilda-pseudo-tags", "infravelo-netz.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            net[(int(r["osm_id"]), r["id_suffix"])] = r["infravelo_netz"]

    tracks = track_tasks(ways, ids, net)
    lanes = lane_tasks(ways)
    geoms = geometries(pbf, sorted({i for i, _ in tracks + lanes}))
    n1 = write(os.path.join(out, "maid__track-direction.json"), "berlin-track-direction-2026-11",
               "Berlin: Fahrtrichtung von Radwegen an der Straße angeben",
               "Radwege, die an der Straße getaggt sind (`cycleway:<Seite>=track`), ohne Fahrtrichtung. "
               "Sie ändern das Ergebnis des infraVelo-Netzabgleichs (Datensatz C) oder liegen im Radvorrangnetz.",
               tracks, geoms)
    n2 = write(os.path.join(out, "maid__lane-foot.json"), "berlin-lane-foot-2026-11",
               "Berlin: Schutz- und Radfahrstreifen mit Fußverkehr prüfen",
               "Spuren auf der Fahrbahn (`cycleway:<Seite>=lane`), die zugleich Fußverkehr daneben oder `segregated` haben. "
               "TILDA liest sie als getrennten Geh- und Radweg.",
               lanes, geoms)
    print(json.dumps({"track_tasks": n1, "lane_tasks": n2}))


if __name__ == "__main__":
    main()
