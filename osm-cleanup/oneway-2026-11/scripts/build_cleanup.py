"""Decide per way: fix automatically (osmChange) or review by hand (MAID task file).

Usage (from the project folder, after rules.py and history_check.py):
  uvx --from duckdb==1.4.1 --with pytz python -I scripts/build_cleanup.py <hw.opl> <berlin.osm.pbf> output

Inputs in output/: R1/R2/R3 CSVs (rules.py), history_check.csv + history/*.parquet (history_check.py).
Writes to output/:
  auto__tracks-explicit.osc  delete the wrong tag; on a track side set the side default explicitly
  auto__delete-only.osc     delete only (if tilda-geo reads tracks on the road side as one-way)
  maid__oneway-check.json  MAID task file for everything that needs a person
  decisions.csv           one row per way with the decision and the reason
  decisions.json          counts
See README.md for the rules.
"""

import csv
import json
import os
import subprocess
import sys
import tempfile

import duckdb

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from opl import is_fmc, read_ways  # noqa: E402
from rules import side_infra  # noqa: E402

# First `yes` set by an fmc account (history_check.py); older tags are reviewed by hand.
FMC_START = "2025-07-05 11:56:11+02"
RULE_FILES = ["R1_both_two_way", "R2_plain_two_way", "R3_left_right_yes_two_way"]
ONEWAY_KEYS = ["cycleway:oneway", "cycleway:both:oneway", "cycleway:left:oneway", "cycleway:right:oneway"]
# Risk reasons from rules.py that always go to a person. The R3 reason "right side not tagged yes" is not one of
# them: single-side tags are decided by who set them (see decide()).
SINGLE_SIDE_REASON = "right side not tagged yes (single-side left:oneway=yes)"


def decide(row, hist):
    """Return (decision, reason). decision: auto | maid | skip."""
    if hist is None:
        return "maid", "keine History gefunden"
    if hist["klasse"] == "schon_entfernt":
        return "skip", "Tag schon entfernt"
    if hist["version_now"] > int(row["version"]):
        return "skip", "seit dem Extrakt bearbeitet: mit frischem Extrakt neu erzeugen"
    risks = [r for r in row["exclusions"].split("; ") if r and r != SINGLE_SIDE_REASON]
    if risks:
        return "maid", "Risiko: " + ", ".join(risks)
    if hist["first_yes"] < FMC_START:
        return "maid", "Tag schon vor der FMC-Erfassung gesetzt"
    single_side = SINGLE_SIDE_REASON in row["exclusions"]
    set_by_fmc = is_fmc(hist["last_adder"])
    if single_side and not set_by_fmc:
        return "maid", "nur links getaggt, nicht von FMC gesetzt"
    if single_side:
        return "auto", "nur links getaggt, von FMC gesetzt"
    return "auto", "beide Seiten getaggt (both, cycleway:oneway oder left+right)" + ("" if set_by_fmc else ", nicht von FMC gesetzt")


def wrong_keys(tags):
    """The direction tags that go: `yes` on both/plain/left; `cycleway:right:oneway` only when it is `yes`
    (the default; `no` or `-1` on the right stay)."""
    return [k for k in ONEWAY_KEYS if tags.get(k) == "yes"]


def new_tags(tags, explicit_tracks):
    """Remove the wrong direction tags. Optionally keep the side default explicit on a track side."""
    gone = wrong_keys(tags)
    out = {k: v for k, v in tags.items() if k not in gone}
    covered = {
        "left": any(k in gone for k in ("cycleway:oneway", "cycleway:both:oneway", "cycleway:left:oneway")),
        "right": any(k in gone for k in ("cycleway:oneway", "cycleway:both:oneway", "cycleway:right:oneway")),
    }
    added = {}
    if explicit_tracks:
        for s, default in (("left", "-1"), ("right", "yes")):
            if covered[s] and side_infra(tags, s) == "track" and f"cycleway:{s}:oneway" not in out:
                out[f"cycleway:{s}:oneway"] = default
                added[f"cycleway:{s}:oneway"] = default
    return out, added


def write_osc(path, items):
    from xml.sax.saxutils import quoteattr
    with open(path, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<osmChange version="0.6" generator="infravelo-radnetz-osm-cleanup-oneway">\n<modify>\n')
        for w, tags in items:
            f.write(f'  <way id="{w["id"]}" version="{w["version"]}">\n')
            for n in w["nodes"]:
                f.write(f'    <nd ref="{n}"/>\n')
            for k in sorted(tags):
                f.write(f"    <tag k={quoteattr(k)} v={quoteattr(tags[k])}/>\n")
            f.write("  </way>\n")
        f.write("</modify>\n</osmChange>\n")


def geometries(pbf, ids):
    with tempfile.TemporaryDirectory() as tmp:
        idfile = os.path.join(tmp, "ids.txt")
        with open(idfile, "w") as f:
            f.write("\n".join(f"w{i}" for i in ids))
        sel = os.path.join(tmp, "sel.osm.pbf")
        seq = os.path.join(tmp, "sel.geojsonseq")
        subprocess.run(["osmium", "getid", "-r", pbf, "-i", idfile, "-o", sel, "--overwrite"], check=True, capture_output=True)
        subprocess.run(["osmium", "export", sel, "-f", "geojsonseq", "-a", "type,id", "--geometry-types=linestring", "-o", seq, "--overwrite"], check=True, capture_output=True)
        geoms = {}
        with open(seq, encoding="utf-8") as f:
            for line in f:
                feat = json.loads(line.lstrip("\x1e"))
                if feat["properties"].get("@type") == "way":
                    geoms[int(feat["properties"]["@id"])] = feat["geometry"]
        return geoms


def maid_task(row, w, reason, geom):
    tags = w["tags"]
    present = {k: tags[k] for k in ONEWAY_KEYS if k in tags}
    tag_lines = "\n".join(f"- `{k}={v}`" for k, v in present.items())
    infra = f"links `{side_infra(tags, 'left') or '–'}`, rechts `{side_infra(tags, 'right') or '–'}`"
    _, added_explicit = new_tags(tags, True)
    remove = wrong_keys(tags)
    options = [{
        "id": "default",
        "label": "Radweg links fährt gegen die Linienrichtung (Standard)",
        "description": "Die Richtungsangabe ist falsch. Sie wird entfernt; an einem track bleibt die Seitenrichtung ausdrücklich stehen.",
        **({"set": added_explicit} if added_explicit else {}),
        "remove": [k for k in remove if k not in added_explicit],
    }, {
        "id": "keep",
        "label": "Die Angabe stimmt (links in Linienrichtung)",
        "description": "Nichts ändern, Aufgabe als erledigt markieren. Gern ein Verkehrszeichen ergänzen.",
        "set": {"cycleway:left:check_date:oneway": "2026-11-18"},
    }]
    return {
        "type": "Feature",
        "geometry": geom,
        "properties": {
            "task_id": f"way-{w['id']}",
            "title": f"{tags.get('name') or tags.get('highway')}: Fahrtrichtung links prüfen",
            "description": (
                f"Straße ohne Einbahnregelung. Getaggt:\n\n{tag_lines}\n\nRadinfrastruktur: {infra}.\n\n"
                f"Grund für die Prüfung: {reason}.\n\n"
                "`oneway` bezieht sich auf die Linienrichtung. Links heißt `yes`: Der Radweg fährt gegen den Kfz-Verkehr daneben. "
                "Das ist fast immer falsch."
            ),
            "osm": [f"way/{w['id']}"],
            "links": ["https://wiki.openstreetmap.org/wiki/Key:cycleway:right:oneway"],
            "options": options,
        },
    }


def main():
    opl, pbf, out = sys.argv[1], sys.argv[2], sys.argv[3]
    ways = {w["id"]: w for w in read_ways(opl)}

    con = duckdb.connect()
    con.execute(f"create view h as select * from read_parquet('{out}/history/*.parquet')")
    version_now = dict(con.execute("select osm_id, max(version) from h group by 1").fetchall())
    hist = {}
    with open(os.path.join(out, "history_check.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            r["version_now"] = version_now.get(int(r["way_id"]), 0)
            hist[(int(r["way_id"]), r["rule"])] = r

    rows = []
    for rule in RULE_FILES:
        with open(os.path.join(out, f"{rule}.csv"), encoding="utf-8") as f:
            for r in csv.DictReader(f):
                r["rule"] = rule
                rows.append(r)

    decisions, osc_explicit, osc_delete, maid_rows = [], [], [], []
    for r in rows:
        w = ways[int(r["id"])]
        h = hist.get((w["id"], r["rule"]))
        decision, reason = decide(r, h)
        tags_explicit, added = new_tags(w["tags"], True)
        tags_delete, _ = new_tags(w["tags"], False)
        if decision == "auto":
            osc_explicit.append((w, tags_explicit))
            osc_delete.append((w, tags_delete))
        elif decision == "maid":
            maid_rows.append((r, w, reason))
        decisions.append({
            "id": w["id"], "rule": r["rule"], "decision": decision, "reason": reason,
            "set_by": (h or {}).get("last_adder", ""), "first_yes": (h or {}).get("first_yes", ""),
            "left_infra": side_infra(w["tags"], "left") or "", "right_infra": side_infra(w["tags"], "right") or "",
            "track_explicit": ";".join(f"{k}={v}" for k, v in added.items()) if decision == "auto" else "",
            "g2": r["g2"], "url": f"https://www.openstreetmap.org/way/{w['id']}",
        })

    write_osc(os.path.join(out, "auto__tracks-explicit.osc"), osc_explicit)
    write_osc(os.path.join(out, "auto__delete-only.osc"), osc_delete)

    geoms = geometries(pbf, sorted({w["id"] for _, w, _ in maid_rows}))
    maid = {
        "type": "FeatureCollection",
        "maid_tasks": {
            "version": 1,
            "list_id": "berlin-oneway-links-2026-11",
            "title": "Berlin: Fahrtrichtung links an Straßen ohne Einbahnregelung prüfen",
            "description": (
                "Ways mit `cycleway:both|left:oneway=yes` oder `cycleway:oneway=yes` an Straßen ohne Einbahnregelung, "
                "die nicht automatisch bereinigt werden: altes Tagging (vor Juli 2025), nicht von FMC gesetztes einseitiges Tagging "
                "oder ein Risiko (oneway:bicycle, Hinweis, Detail-Tags in wörtlicher Richtung)."
            ),
        },
        "features": [maid_task(r, w, reason, geoms[w["id"]]) for r, w, reason in maid_rows if w["id"] in geoms],
    }
    with open(os.path.join(out, "maid__oneway-check.json"), "w", encoding="utf-8") as f:
        json.dump(maid, f, ensure_ascii=False, indent=1)

    with open(os.path.join(out, "decisions.csv"), "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=list(decisions[0]))
        wr.writeheader()
        wr.writerows(decisions)

    con.execute("create table d as select * from read_csv(?)", [os.path.join(out, "decisions.csv")])
    summary = {
        "by_rule_decision": con.execute("select rule, decision, count(*) from d group by all order by all").fetchall(),
        "by_reason": con.execute("select decision, reason, count(*) from d group by all order by 1, 3 desc").fetchall(),
        "auto_track_explicit": con.execute(
            "select track_explicit, count(*) from d where decision='auto' group by 1 order by 2 desc").fetchall(),
        "auto_set_by_fmc": con.execute(
            "select lower(set_by) like 'fmc%', count(*) from d where decision='auto' group by 1").fetchall(),
        "g2": con.execute("select decision, count(*) from d where g2 group by 1").fetchall(),
        "maid_tasks": len(maid["features"]),
    }
    with open(os.path.join(out, "decisions.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1, default=str)
    print(json.dumps(summary, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
