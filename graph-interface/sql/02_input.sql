-- Eingangsnetz (TILDA-Routing) als pgRouting-Kantentabelle.
--
-- Eingang: matching_staging.input_{bikelanes,streets,paths}
--          (ogr2ogr aus processing/output/TILDA-routing*/TILDA Routing * Translated.fgb)
-- Ausgang: matching.input_edges, matching.input_vertices
--
-- Topologie: from_node/to_node aus scripts/prepare_tilda_routing.py (geteilt an gemeinsamen
-- Stützpunkten, IDs über alle drei Quellen eindeutig). Werden diese später direkt in tilda-geo aus
-- den OSM-Knoten-IDs erzeugt, ändert sich nur diese Datei.
--
-- Richtung: Einrichtungswege (verkehrsri = 'Einrichtungsverkehr') nur in Digitalisierungsrichtung,
-- also reverse_cost = -1 (pgRouting-Konvention). trace_group = Datenquelle; Traces laufen nur
-- innerhalb einer Gruppe weiter. Alle übrigen Spalten stehen in attrs.

BEGIN;

DROP TABLE IF EXISTS matching.input_edges CASCADE;
DROP TABLE IF EXISTS matching.input_vertices CASCADE;

CREATE TEMP TABLE input_all ON COMMIT DROP AS
SELECT 'bikelanes'::text AS trace_group, 1 AS group_order, b.ogc_fid, to_jsonb(b) - 'geom' - 'ogc_fid' AS attrs, b.geom FROM matching_staging.input_bikelanes b
UNION ALL
SELECT 'streets', 2, s.ogc_fid, to_jsonb(s) - 'geom' - 'ogc_fid', s.geom FROM matching_staging.input_streets s
UNION ALL
SELECT 'paths', 3, p.ogc_fid, to_jsonb(p) - 'geom' - 'ogc_fid', p.geom FROM matching_staging.input_paths p;

CREATE TABLE matching.input_edges AS
-- id in Dateireihenfolge (bikelanes, streets, paths), damit das Matching dieselbe Reihenfolge sieht
SELECT row_number() OVER (ORDER BY group_order, ogc_fid) AS id,
       (attrs->>'from_node')::bigint AS source,
       (attrs->>'to_node')::bigint AS target,
       ST_Length(geom) AS cost,
       CASE WHEN attrs->>'verkehrsri' = 'Einrichtungsverkehr' THEN -1 ELSE ST_Length(geom) END AS reverse_cost,
       trace_group,
       matching.normalize_match_key(attrs->>'tilda_name') AS match_key,
       attrs->>'tilda_id' AS input_ref,
       geom::geometry(LineString, 25833) AS geom,
       attrs - 'from_node' - 'to_node' AS attrs
FROM input_all
WHERE ST_NPoints(geom) >= 2;

ALTER TABLE matching.input_edges ADD PRIMARY KEY (id);

-- Knoten: Lage aus dem ersten Kantenende, das den Knoten nennt
CREATE TABLE matching.input_vertices AS
SELECT DISTINCT ON (node) node AS id, pt::geometry(Point, 25833) AS geom
FROM (
    SELECT source AS node, ST_StartPoint(geom) AS pt, id, 0 AS o FROM matching.input_edges
    UNION ALL
    SELECT target, ST_EndPoint(geom), id, 1 FROM matching.input_edges
) e
ORDER BY node, id, o;
ALTER TABLE matching.input_vertices ADD PRIMARY KEY (id);

CREATE INDEX ON matching.input_edges (source);
CREATE INDEX ON matching.input_edges (target);
CREATE INDEX ON matching.input_edges (trace_group);
CREATE INDEX ON matching.input_edges (input_ref);
CREATE INDEX ON matching.input_edges USING gist (geom);
CREATE INDEX ON matching.input_vertices USING gist (geom);

COMMENT ON TABLE matching.input_edges IS
  'Eingangsnetz im pgRouting-Format (id, source, target, cost, reverse_cost; Meter, EPSG:25833). reverse_cost = -1: nur in Digitalisierungsrichtung. trace_group trennt Fahrbahn, Radinfrastruktur und Wege.';
COMMENT ON COLUMN matching.input_edges.match_key IS 'Normalisierter Straßenname, Vergleichsschlüssel für die Emission (optional).';
COMMENT ON COLUMN matching.input_edges.attrs IS 'Alle übrigen Attribute (TILDA, Routing, übersetzte RVN-Attribute wie fuehr, breite, protek) für die Regeln nach dem Matching.';

COMMIT;
