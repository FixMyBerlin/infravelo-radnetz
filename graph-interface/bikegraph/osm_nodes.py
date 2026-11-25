"""Knotenlisten aller highway-Wege aus einem OSM-Auszug nach PostGIS (Zwischenlösung, bis tilda-geo sie ausgibt).

Aufruf:
  python osm_nodes.py <auszug.osm.pbf> | psql "$MATCHING_PG" -v ON_ERROR_STOP=1 -q

Schreibt ein SQL-Skript mit COPY-Blöcken auf stdout:
  bikegraph.osm_ways       way_id, tags (nur die für Topologie und Zugang nötigen)
  bikegraph.osm_way_nodes  way_id, seq, node_id
  bikegraph.osm_nodes      node_id, lon, lat (nur Knoten dieser Wege)
Flächen (area=yes) und Wege mit weniger als zwei Knoten fallen weg.
"""
import sys

import osmium

KEYS = ("highway", "footway", "cycleway", "service", "access", "bicycle", "vehicle", "foot", "oneway", "oneway:bicycle",
        "junction", "area", "name", "construction", "sidewalk")


def esc(v):
    return v.replace("\\", "\\\\").replace("\t", " ").replace("\n", " ")


def jsonb(d):
    import json
    return esc(json.dumps(d, ensure_ascii=False))


class Ways(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.ways = []
        self.nodes = {}

    def way(self, w):
        if "highway" not in w.tags or w.tags.get("area") == "yes" or len(w.nodes) < 2:
            return
        refs = []
        for n in w.nodes:
            if not n.location.valid():
                return
            refs.append(n.ref)
            self.nodes[n.ref] = (n.location.lon, n.location.lat)
        self.ways.append((w.id, {k: w.tags[k] for k in KEYS if k in w.tags}, refs))


h = Ways()
h.apply_file(sys.argv[1], locations=True)
out = sys.stdout
out.write("""
CREATE SCHEMA IF NOT EXISTS bikegraph;
DROP TABLE IF EXISTS bikegraph.osm_ways, bikegraph.osm_way_nodes, bikegraph.osm_nodes;
CREATE TABLE bikegraph.osm_ways (way_id bigint PRIMARY KEY, tags jsonb);
CREATE TABLE bikegraph.osm_way_nodes (way_id bigint, seq int, node_id bigint, PRIMARY KEY (way_id, seq));
CREATE TABLE bikegraph.osm_nodes (node_id bigint PRIMARY KEY, lon double precision, lat double precision);
COPY bikegraph.osm_ways FROM stdin;
""")
for wid, tags, _ in h.ways:
    out.write(f"{wid}\t{jsonb(tags)}\n")
out.write("\\.\nCOPY bikegraph.osm_way_nodes FROM stdin;\n")
for wid, _, refs in h.ways:
    for i, r in enumerate(refs):
        out.write(f"{wid}\t{i}\t{r}\n")
out.write("\\.\nCOPY bikegraph.osm_nodes FROM stdin;\n")
for nid, (lon, lat) in h.nodes.items():
    out.write(f"{nid}\t{lon:.7f}\t{lat:.7f}\n")
out.write("\\.\nCREATE INDEX ON bikegraph.osm_way_nodes (node_id);\nANALYZE bikegraph.osm_ways, bikegraph.osm_way_nodes, bikegraph.osm_nodes;\n")
print(f"{len(h.ways)} Wege, {len(h.nodes)} Knoten", file=sys.stderr)
