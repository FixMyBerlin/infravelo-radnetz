"""Rules for the FMC cycleway:*:oneway cleanup in Berlin.

Usage: python3 -I rules.py <ways.opl> <out_dir> [<bikelanes_diff_ids.txt>]

The optional diff id file ("<way_id>:<side>,...", from public.bikelanes_diff of the carriageway-side run,
worktree bikelane-fahrbahn-seite, f6aa5a26d) defines group G2: diff ways on a two-way road whose left side
is tagged `yes` (via cycleway:left|both|plain :oneway). Without it G2 falls back to a tag approximation.

Reads highway ways (osmium cat -f opl, with metadata), applies every rule, writes per rule
a CSV of matched ways and osmChange files for the variants b (last editor FMC) and b+c
(plus: last editor not FMC, timestamp inside the FMC campaign range), and prints a summary.

Wiki: https://wiki.openstreetmap.org/wiki/Key:cycleway:right:oneway
`cycleway:<side>:oneway` is relative to the drawing direction of the way. Defaults (not to be tagged):
two-way road: right `yes`, left `-1`; oneway road (incl. roundabouts): both sides follow the road.
"""

import csv
import json
import os
import re
import sys
from xml.sax.saxutils import quoteattr

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from opl import is_fmc, read_ways  # noqa: E402

ROADS = set(
    "motorway trunk primary secondary tertiary unclassified residential living_street service road busway "
    "motorway_link trunk_link primary_link secondary_link tertiary_link".split()
)
ON_ROAD_INFRA = {"lane", "track", "share_busway", "shared_lane", "crossing"}
YES = {"yes", "1", "true"}
ONEWAY_KEY_RE = re.compile(r"^cycleway(:left|:right|:both)?:oneway$")
SIDE_DETAIL_RE = re.compile(r"^cycleway:(left|both):(separation|traffic_mode|buffer|marking):(left|right)$")
NOTE_KEY_RE = re.compile(r"note|fixme|description", re.I)
NOTE_VALUE_RE = re.compile(r"oneway|richtung|einbahn|gegen|contraflow|links|linke|left", re.I)
CHECK_DATE_ONEWAY_RE = re.compile(r"^(cycleway(:\w+)?:check_date(:oneway)?|check_date:cycleway(:\w+)?:oneway)$")


def is_two_way(t):
    """No oneway regulation: oneway missing or `no`, and not a roundabout/circular junction (unless oneway=no)."""
    if t.get("oneway") == "no":
        return True
    return t.get("oneway") is None and t.get("junction") not in ("roundabout", "circular")


def is_oneway_forward(t):
    """Oneway road in drawing direction. `junction=circular` without oneway is left out (wiki: must be tagged)."""
    if t.get("oneway") in YES:
        return True
    return t.get("oneway") is None and t.get("junction") == "roundabout"


def side_infra(t, side):
    return t.get(f"cycleway:{side}") or t.get("cycleway:both") or t.get("cycleway")


def oneway_keys(t):
    return {k: v for k, v in t.items() if ONEWAY_KEY_RE.match(k)}


def common_exclusions(t):
    """Risk cases shared by all rules. Returns a list of reasons (empty = not excluded)."""
    reasons = []
    if any(k in t for k in ("oneway:bicycle", "oneway:conditional", "oneway:bicycle:conditional")):
        reasons.append("oneway:bicycle/conditional")
    if any(CHECK_DATE_ONEWAY_RE.match(k) for k in t):
        reasons.append("cycleway check_date")
    if any(NOTE_KEY_RE.search(k) and NOTE_VALUE_RE.search(v) for k, v in t.items()):
        reasons.append("note mentions direction")
    return reasons


# --- Second-order effect: `cycleway:<side>:(separation|traffic_mode|buffer|marking):(left|right)` -----------------
# The second left/right is relative to the riding direction (Key:separation, "Directions of left and right").
# Left side of a two-way road, wiki default (-1): carriageway on the rider's LEFT, kerb/sidewalk on the rider's RIGHT.
# With the wrong `yes` the rider turns around, so the same tags read swapped.
CARRIAGEWAY_SIDE_SEPARATION = {"bollard", "vertical_panel", "flex_post", "jersey_barrier", "bump", "solid_line", "dashed_line"}


def left_side_detail_class(t):
    """Classify explicit `cycleway:left:*:(left|right)` tags of a two-way road.

    default: values fit the wiki default direction (fix makes them correct)
    literal: values fit the literal `oneway=yes` direction (fix makes them read swapped -> manual review)
    mixed / unknown: evidence conflicts or no decisive value
    `cycleway:both:*:(left|right)` is not classified here: the same values hold for the right side, which
    rides with the way, so by symmetry they are correct for the left side in the default direction.
    """
    infra = side_infra(t, "left")
    votes = {"default": 0, "literal": 0}

    def vote(rider_side, kind):
        # kind: 'kerb' (belongs to the kerb side) or 'carriageway'
        default_side = "right" if kind == "kerb" else "left"
        votes["default" if rider_side == default_side else "literal"] += 1

    for rider_side in ("left", "right"):
        tm = t.get(f"cycleway:left:traffic_mode:{rider_side}")
        if tm:
            vals = set(tm.split(";"))
            if "foot" in vals:
                vote(rider_side, "kerb")
            if vals & {"motor_vehicle", "motorized"}:
                vote(rider_side, "carriageway")
            if "parking" in vals and infra in ("lane", "share_busway"):
                vote(rider_side, "kerb")  # parking lies outside a painted lane
        sep = t.get(f"cycleway:left:separation:{rider_side}")
        if sep:
            vals = set(re.split(r"[;,]", sep))
            if vals & CARRIAGEWAY_SIDE_SEPARATION:
                vote(rider_side, "carriageway")
            elif infra == "lane" and "kerb" in vals:
                vote(rider_side, "kerb")
    if votes["default"] and votes["literal"]:
        return "mixed"
    if votes["default"]:
        return "default"
    if votes["literal"]:
        return "literal"
    return "unknown"


def detail_tags(t):
    return sorted(k for k in t if SIDE_DETAIL_RE.match(k))


def g2_candidate(t):
    """Approximation of group G2 of the carriageway-side diff (worktree bikelane-fahrbahn-seite, f6aa5a26d):
    two-way road, left side rides with the way because of `yes`, painted lane, no explicit traffic_mode on the
    left side, parking on the left side -> the parking moves from traffic_mode_right to traffic_mode_left."""
    if not is_two_way(t):
        return False
    left_dir = t.get("cycleway:left:oneway") or t.get("cycleway:both:oneway") or t.get("cycleway:oneway")
    if left_dir not in YES:
        return False
    if side_infra(t, "left") != "lane":
        return False
    if any(re.match(r"^cycleway:(left|both)?:?traffic_mode", k) for k in t):
        return False
    parking = t.get("parking:left") or t.get("parking:both")
    return parking not in (None, "no", "separate")


# --- Rules -------------------------------------------------------------------------------------------------------
# Each rule: match(t) -> (matched_core: bool, change: dict|None, exclusions: list)
# matched_core = the tag pattern is present; change = keys to delete; exclusions = risk reasons (safe set = none).


def rule_both_two_way(t):
    if not (is_two_way(t) and t.get("cycleway:both:oneway") == "yes"):
        return False, None, []
    reasons = common_exclusions(t)
    ow = oneway_keys(t)
    if "cycleway:left:oneway" in ow or "cycleway:oneway" in ow or ow.get("cycleway:right:oneway", "yes") != "yes":
        reasons.append("conflicting side oneway tags")
    if left_side_detail_class(t) == "literal":
        reasons.append("left detail tags fit literal direction")
    delete = ["cycleway:both:oneway"] + (["cycleway:right:oneway"] if ow.get("cycleway:right:oneway") == "yes" else [])
    return True, {"delete": delete}, reasons


def rule_plain_two_way(t):
    if not (is_two_way(t) and t.get("cycleway:oneway") == "yes"):
        return False, None, []
    reasons = common_exclusions(t)
    ow = oneway_keys(t)
    others = {k: v for k, v in ow.items() if k != "cycleway:oneway"}
    if any(not (k == "cycleway:right:oneway" and v == "yes") for k, v in others.items()):
        reasons.append("conflicting side oneway tags")
    if left_side_detail_class(t) == "literal":
        reasons.append("left detail tags fit literal direction")
    delete = ["cycleway:oneway"] + (["cycleway:right:oneway"] if others.get("cycleway:right:oneway") == "yes" else [])
    return True, {"delete": delete}, reasons


def rule_left_right_yes_two_way(t):
    """`cycleway:left:oneway=yes` + `cycleway:right:oneway=yes` means the same as `cycleway:both:oneway=yes` (R1),
    tagged per side. A single `cycleway:left:oneway=yes` can be a real one-direction lane on the left of a two-way
    road (Linksradweg) and is not part of this rule."""
    if not (is_two_way(t) and t.get("cycleway:left:oneway") == "yes"):
        return False, None, []
    if "cycleway:both:oneway" in t or "cycleway:oneway" in t:
        return False, None, []  # handled by the rules above (as conflict)
    reasons = common_exclusions(t)
    if t.get("cycleway:right:oneway") != "yes":
        reasons.append("right side not tagged yes (single-side left:oneway=yes)")
    if left_side_detail_class(t) == "literal":
        reasons.append("left detail tags fit literal direction")
    return True, {"delete": ["cycleway:left:oneway", "cycleway:right:oneway"]}, reasons


def rule_defaults_two_way(t):
    """Cosmetic: defaults tagged on a two-way road (`right=yes`, `left=-1`), with no wrong tag on the way."""
    if not is_two_way(t):
        return False, None, []
    ow = oneway_keys(t)
    if not ow:
        return False, None, []
    defaults = {"cycleway:right:oneway": "yes", "cycleway:left:oneway": "-1"}
    if not all(defaults.get(k) == v for k, v in ow.items()):
        return False, None, []
    return True, {"delete": sorted(ow)}, common_exclusions(t)


def rule_defaults_oneway(t):
    """Cosmetic: `yes` on any side of a oneway road in drawing direction (both sides follow the road)."""
    if not is_oneway_forward(t):
        return False, None, []
    ow = oneway_keys(t)
    if not ow or any(v != "yes" for v in ow.values()):
        return False, None, []
    reasons = []
    if t.get("oneway:bicycle") not in (None, "yes"):
        reasons.append("oneway:bicycle not yes (contraflow reading of left side differs DE/EN)")
    if any(k.endswith(":conditional") and k.startswith("oneway") for k in t):
        reasons.append("oneway:conditional")
    reasons += [r for r in common_exclusions(t) if r != "oneway:bicycle/conditional"]
    return True, {"delete": sorted(ow)}, reasons


RULES = [
    ("R1_both_two_way", "cycleway:both:oneway=yes on a two-way street", rule_both_two_way, False),
    ("R2_plain_two_way", "cycleway:oneway=yes on a two-way street", rule_plain_two_way, False),
    ("R3_left_right_yes_two_way", "cycleway:left:oneway=yes + cycleway:right:oneway=yes", rule_left_right_yes_two_way, False),
    ("R4_defaults_two_way", "default values on a two-way street (right=yes / left=-1)", rule_defaults_two_way, True),
    ("R5_defaults_oneway", "default value yes on a one-way street (oneway=yes / roundabout)", rule_defaults_oneway, True),
]


def percentile(sorted_vals, p):
    if not sorted_vals:
        return None
    i = min(len(sorted_vals) - 1, max(0, round(p / 100 * (len(sorted_vals) - 1))))
    return sorted_vals[i]


def write_osc(path, ways, generator="fmc-oneway-cleanup"):
    with open(path, "w", encoding="utf-8") as f:
        f.write(f'<?xml version="1.0" encoding="UTF-8"?>\n<osmChange version="0.6" generator="{generator}">\n<modify>\n')
        for w in ways:
            f.write(f'  <way id="{w["id"]}" version="{w["version"]}">\n')
            for n in w["nodes"]:
                f.write(f'    <nd ref="{n}"/>\n')
            for k in sorted(w["new_tags"]):
                f.write(f'    <tag k={quoteattr(k)} v={quoteattr(w["new_tags"][k])}/>\n')
            f.write("  </way>\n")
        f.write("</modify>\n</osmChange>\n")


def main():
    opl_path, out_dir = sys.argv[1], sys.argv[2]
    os.makedirs(out_dir, exist_ok=True)
    ways = [w for w in read_ways(opl_path) if w["tags"].get("highway") in ROADS]

    # Reference sets for coverage numbers.
    ref_both = {w["id"] for w in ways if is_two_way(w["tags"]) and w["tags"].get("cycleway:both:oneway") == "yes"}
    ref_left = {w["id"] for w in ways if is_two_way(w["tags"]) and w["tags"].get("cycleway:left:oneway") == "yes"}
    def left_yes(t):
        return is_two_way(t) and (t.get("cycleway:left:oneway") or t.get("cycleway:both:oneway") or t.get("cycleway:oneway")) in YES

    if len(sys.argv) > 3:
        with open(sys.argv[3], encoding="utf-8") as f:
            diff_ids = {int(x.split(":")[0]) for x in f.read().strip().split(",") if x}
        in_g2 = lambda w: w["id"] in diff_ids and left_yes(w["tags"])  # noqa: E731
    else:
        in_g2 = lambda w: g2_candidate(w["tags"])  # noqa: E731
    ref_g2 = {w["id"]: ("both" if "cycleway:both:oneway" in w["tags"] else "left") for w in ways if in_g2(w)}

    summary = []
    for rule_id, label, fn, cosmetic in RULES:
        matched = []
        for w in ways:
            core, change, reasons = fn(w["tags"])
            if core:
                matched.append((w, change, reasons))
        safe = [(w, ch) for w, ch, r in matched if not r]
        fmc_ts = sorted(w["timestamp"] for w, _ in safe if is_fmc(w["user"]))
        lo, hi = percentile(fmc_ts, 5), percentile(fmc_ts, 95)

        def group(w):
            if is_fmc(w["user"]):
                return "b"
            if lo and lo <= w["timestamp"] <= hi:
                return "c"
            return "rest"

        rows, osc_b, osc_bc = [], [], []
        excl_counts = {}
        for w, change, reasons in matched:
            for r in reasons:
                excl_counts[r] = excl_counts.get(r, 0) + 1
            g = group(w)
            new_tags = {k: v for k, v in w["tags"].items() if k not in change["delete"]}
            rows.append({
                "id": w["id"], "version": w["version"], "user": w["user"], "timestamp": w["timestamp"],
                "group": g, "safe": not reasons, "exclusions": "; ".join(reasons),
                "delete": ";".join(k for k in change["delete"] if k in w["tags"]),
                "highway": w["tags"].get("highway"), "name": w["tags"].get("name", ""),
                "left_infra": side_infra(w["tags"], "left") or "", "right_infra": side_infra(w["tags"], "right") or "",
                "detail_tags": ";".join(detail_tags(w["tags"])), "left_detail_class": left_side_detail_class(w["tags"]),
                "g2": w["id"] in ref_g2, "url": f"https://www.openstreetmap.org/way/{w['id']}",
            })
            if not reasons and g in ("b", "c"):
                item = {"id": w["id"], "version": w["version"], "nodes": w["nodes"], "new_tags": new_tags}
                if g == "b":
                    osc_b.append(item)
                osc_bc.append(item)

        with open(os.path.join(out_dir, f"{rule_id}.csv"), "w", newline="", encoding="utf-8") as f:
            wr = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["id"])
            wr.writeheader()
            wr.writerows(rows)
        write_osc(os.path.join(out_dir, f"{rule_id}__b.osc"), osc_b)
        write_osc(os.path.join(out_dir, f"{rule_id}__b+c.osc"), osc_bc)

        safe_rows = [r for r in rows if r["safe"]]
        s = {
            "rule": rule_id, "label": label, "cosmetic": cosmetic,
            "pattern_total": len(rows), "excluded": len(rows) - len(safe_rows), "exclusion_reasons": excl_counts,
            "a": len(safe_rows),
            "b": sum(r["group"] == "b" for r in safe_rows),
            "c": sum(r["group"] == "c" for r in safe_rows),
            "rest": sum(r["group"] == "rest" for r in safe_rows),
            "fmc_range_p5_p95": [lo, hi],
            "fmc_range_min_max": [fmc_ts[0], fmc_ts[-1]] if fmc_ts else None,
            "safe_with_detail_tags": sum(bool(r["detail_tags"]) for r in safe_rows),
            "safe_left_detail_class": {k: sum(r["left_detail_class"] == k for r in safe_rows) for k in ("default", "literal", "mixed", "unknown")},
            "safe_with_both_detail_tags": sum("cycleway:both:" in r["detail_tags"] for r in safe_rows),
            "excluded_left_detail_literal": sum("literal direction" in r["exclusions"] for r in rows),
            "cover_2030_both": {g: sum(r["safe"] and r["id"] in ref_both and r["group"] in gs for r in rows) for g, gs in (("b", "b"), ("b+c", "bc"), ("a", ("b", "c", "rest")))},
            "cover_442_left": {g: sum(r["safe"] and r["id"] in ref_left and r["group"] in gs for r in rows) for g, gs in (("b", "b"), ("b+c", "bc"), ("a", ("b", "c", "rest")))},
            "cover_g2": {g: sum(r["safe"] and r["g2"] and r["group"] in gs for r in rows) for g, gs in (("b", "b"), ("b+c", "bc"), ("a", ("b", "c", "rest")))},
            "osc_b": len(osc_b), "osc_b+c": len(osc_bc),
        }
        summary.append(s)

    meta = {
        "ref_both_2way": len(ref_both), "ref_left_2way": len(ref_left),
        "ref_g2_approx": len(ref_g2), "ref_g2_approx_both": sum(v == "both" for v in ref_g2.values()),
        "ref_g2_approx_left": sum(v == "left" for v in ref_g2.values()),
    }
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "rules": summary}, f, indent=2, ensure_ascii=False)
    print(json.dumps(meta))
    for s in summary:
        print(json.dumps(s, ensure_ascii=False))


if __name__ == "__main__":
    main()
