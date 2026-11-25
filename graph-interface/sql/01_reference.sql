-- Referenznetz (RVN oder REN+) als pgRouting-Kantentabelle.
--
-- Eingang: matching_staging.reference_raw (ogr2ogr aus processing/output/<netz>/…_combined*.fgb)
-- Ausgang: matching.reference_edges, matching.reference_vertices
--
-- Knoten wie im Rust-Matching (src/network/mod.rs, cluster_points): Kantenenden, die transitiv
-- höchstens :node_tolerance_m auseinander liegen, sind ein Knoten. Nichts wird repariert.
-- Jeder Teil eines MultiLineStrings wird eine eigene Kante (wie im Matching).
-- Das Referenznetz ist für den Radverkehr in beiden Richtungen befahrbar: reverse_cost = cost.

BEGIN;

DROP TABLE IF EXISTS matching.reference_edges CASCADE;
DROP TABLE IF EXISTS matching.reference_vertices CASCADE;

CREATE TEMP TABLE ref_parts ON COMMIT DROP AS
SELECT row_number() OVER (ORDER BY r.ogc_fid, d.path) AS id,
       r.ogc_fid AS raw_fid,
       COALESCE(d.path[1], 1) AS part,
       d.geom::geometry(LineString, 25833) AS geom,
       r.element_nr, r.beginnt_bei_vp, r.endet_bei_vp, r.strassenname, r.verkehrsrichtung, r.edge_source
FROM matching_staging.reference_raw r
CROSS JOIN LATERAL ST_Dump(r.geom) d
WHERE r.element_nr IS NOT NULL
  AND ST_NPoints(d.geom) >= 2;

-- Kantenenden clustern (transitiv, wie Union-Find im Matching)
CREATE TEMP TABLE ref_ends ON COMMIT DROP AS
SELECT id AS edge_id, 'source' AS side, ST_StartPoint(geom) AS geom FROM ref_parts
UNION ALL
SELECT id, 'target', ST_EndPoint(geom) FROM ref_parts;

CREATE TEMP TABLE ref_clustered ON COMMIT DROP AS
SELECT edge_id, side, geom,
       ST_ClusterDBSCAN(geom, eps := :node_tolerance_m, minpoints := 1) OVER () AS cluster
FROM ref_ends;

-- Knoten-IDs stabil nach der kleinsten Kante im Cluster vergeben; Lage = erster Punkt (wie im Matching)
CREATE TABLE matching.reference_vertices AS
SELECT row_number() OVER (ORDER BY min_edge, min_side) AS id, cluster, geom
FROM (
    SELECT DISTINCT ON (cluster) cluster, edge_id AS min_edge, side AS min_side,
           geom::geometry(Point, 25833) AS geom
    FROM ref_clustered
    ORDER BY cluster, edge_id, side DESC  -- 'source' vor 'target'
) v;
ALTER TABLE matching.reference_vertices ADD PRIMARY KEY (id);

CREATE TABLE matching.reference_edges AS
SELECT p.id,
       s.id AS source,
       t.id AS target,
       ST_Length(p.geom) AS cost,
       ST_Length(p.geom) AS reverse_cost,
       matching.normalize_match_key(p.strassenname) AS match_key,
       p.geom,
       p.element_nr, p.part, p.beginnt_bei_vp, p.endet_bei_vp, p.strassenname, p.verkehrsrichtung, p.edge_source
FROM ref_parts p
JOIN ref_clustered cs ON cs.edge_id = p.id AND cs.side = 'source'
JOIN ref_clustered ct ON ct.edge_id = p.id AND ct.side = 'target'
JOIN matching.reference_vertices s ON s.cluster = cs.cluster
JOIN matching.reference_vertices t ON t.cluster = ct.cluster;

ALTER TABLE matching.reference_vertices DROP COLUMN cluster;
ALTER TABLE matching.reference_edges ADD PRIMARY KEY (id);
CREATE INDEX ON matching.reference_edges (source);
CREATE INDEX ON matching.reference_edges (target);
CREATE INDEX ON matching.reference_edges (element_nr);
CREATE INDEX ON matching.reference_edges USING gist (geom);
CREATE INDEX ON matching.reference_vertices USING gist (geom);

COMMENT ON TABLE matching.reference_edges IS
  'Referenznetz im pgRouting-Format (id, source, target, cost, reverse_cost; Meter, EPSG:25833). Ein Datensatz je Teil eines MultiLineStrings. Für den Radverkehr in beiden Richtungen: reverse_cost = cost.';
COMMENT ON COLUMN matching.reference_edges.match_key IS 'Normalisierter Straßenname, Vergleichsschlüssel für die Emission (optional).';

COMMIT;
