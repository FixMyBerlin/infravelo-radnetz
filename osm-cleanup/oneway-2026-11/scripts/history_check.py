"""Alex' history check via the ohsome API v2 (contributions with tags and user per edit).

Question per way: did `cycleway:<both|left|>:oneway=yes` exist BEFORE any fmc* account edited the way?
Usage (key from env OHSOME_API_KEY, never printed):
  uvx --from duckdb==1.4.1 --with pytz python history_check.py <out_dir>
Reads the pattern CSVs (R1, R2, R3) in <out_dir>, downloads the full history of those ways as parquet into
<out_dir>/history/, writes <out_dir>/history_check.csv and prints the class counts.
"""

import csv
import os
import sys
import time
import urllib.parse
import urllib.error
import urllib.request

import duckdb

API = "https://api.heigit.org/ohsome-api/v2/extraction/contributions.parquet"
BERLIN_BBOX = "13.08,52.33,13.77,52.68"
RULE_KEY = {
    "R1_both_two_way": "cycleway:both:oneway",
    "R2_plain_two_way": "cycleway:oneway",
    "R3_left_right_yes_two_way": "cycleway:left:oneway",
}


def fetch(ids, path, key):
    # GET: the v2 POST body is a JSON model we do not need; ~150 ids keep the URL short.
    query = urllib.parse.urlencode({
        "aoi": BERLIN_BBOX,
        "filter": "type:way and id:(" + ",".join(str(i) for i in ids) + ")",
        "time": "2007-10-08T00:00:00Z/" + time.strftime("%Y-%m-%dT00:00:00Z", time.gmtime()),
    })
    req = urllib.request.Request(f"{API}?{query}", headers={
        "Authorization": key, "User-Agent": "osm-cleanup-check/0.1",
    })
    for attempt in range(8):
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                data = r.read()
            break
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            wait = int(e.headers.get("Retry-After") or 30 * (attempt + 1))
            print(f"429, waiting {wait}s", flush=True)
            time.sleep(wait)
    else:
        raise RuntimeError("ohsome rate limit: gave up")
    with open(path, "wb") as f:
        f.write(data)


def main():
    out = sys.argv[1]
    key = os.environ["OHSOME_API_KEY"]
    hist = os.path.join(out, "history")
    os.makedirs(hist, exist_ok=True)

    targets = []  # (way_id, rule, key, pbf_group, pbf_safe)
    for rule, k in RULE_KEY.items():
        with open(os.path.join(out, f"{rule}.csv"), encoding="utf-8") as f:
            for r in csv.DictReader(f):
                targets.append((int(r["id"]), rule, k, r["group"], r["safe"] == "True"))
    ids = sorted({t[0] for t in targets})
    chunk = 150
    for n, i in enumerate(range(0, len(ids), chunk)):
        path = os.path.join(hist, f"part{n:02d}.parquet")
        if not os.path.exists(path):
            fetch(ids[i:i + chunk], path, key)
            time.sleep(5)

    con = duckdb.connect()
    con.execute("create table t(way_id bigint, rule varchar, k varchar, pbf_group varchar, pbf_safe boolean)")
    con.executemany("insert into t values (?,?,?,?,?)", targets)
    con.execute(f"create view h as select * from read_parquet('{hist}/*.parquet')")
    # One row per way: first fmc edit, first time the tag was yes, who set the current `yes` run, current state.
    con.execute("""
    create table r as
    with c as (
      select t.way_id, t.rule, t.k, t.pbf_group, t.pbf_safe, h.edit_timestamp ts, h.version, h.user_name u,
             h.changeset_id cs, h.changeset_tags['comment'] cmt,
             coalesce(h.tags[t.k] = 'yes', false) as yes_now, coalesce(h.tags_before[t.k], '') = 'yes' as yes_before,
             coalesce(lower(h.user_name) like 'fmc%', false) as fmc, h.contribution_type ct
      from t join h on h.osm_id = t.way_id
    ),
    agg as (
      select way_id, rule, k, pbf_group, pbf_safe,
        min(ts) filter (where fmc) first_fmc,
        min(ts) filter (where yes_now) first_yes,
        arg_max(u, ts) filter (where yes_now and not yes_before) last_adder,
        arg_max(cmt, ts) filter (where yes_now and not yes_before) last_adder_comment,
        arg_max(yes_now, ts) yes_today,
        arg_max(ct, ts) last_type
      from c group by all
    )
    select *,
      case
        when not coalesce(yes_today, false) or last_type = 'DELETION' then 'schon_entfernt'
        when first_fmc is null then 'nie_fmc'
        when first_yes < first_fmc then 'vor_fmc_vorhanden'
        when lower(last_adder) like 'fmc%' then 'von_fmc_gesetzt'
        else 'nach_fmc_von_anderen_gesetzt'
      end as klasse
    from agg
    """)
    con.execute(f"copy r to '{out}/history_check.csv' (header)")
    print(con.sql("select rule, klasse, count(*) n, count(*) filter (where pbf_safe) n_sicher from r group by all order by rule, n desc"))
    print(con.sql("select rule, last_adder, count(*) n from r where klasse='nach_fmc_von_anderen_gesetzt' group by all order by n desc limit 15"))
    print(con.sql("select max(ts) from (select edit_timestamp ts from h)"))


if __name__ == "__main__":
    main()
