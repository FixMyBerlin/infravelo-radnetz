-- Datensatz C aus Straßen (mit gefalteten Radwegen) und Wegen: Eingang für das Matching auf das RVN (datensatz_c.sh).
-- Voraussetzung: radweg_faltung.sh (bikegraph.bl_input, bl_faltung, bl_strassen1, radweg_faltung.radwege_abgelehnt).
-- Alle Straßen und Wege kommen aus dem TILDA-Routing-Export (public.routing); die OSM-Topologie liefert nur die
-- Knoten-IDs zum Verketten.
-- Ausgang bikegraph.dc_input (Format postgres.input_edges), zwei trace_groups:
--   strassen  je Kante des Faltungsnetzes (bl_strassen1) eine Zeile, in beide Richtungen befahrbar: welche Richtung
--             welche Kandidaten trägt, entscheidet sql/105 (Straße selbst nur mit Radfreigabe, Seitenobjekte und
--             gefaltete Radwege je Richtung). id = 100000000 + Kanten-ID. Ohne Kanten, die nichts tragen: weder
--             Radzugang (edges.fwd/bwd) noch eine Zeile in bl_faltung (Seitenobjekt oder gefalteter Radweg); sie bilden
--             keine Traces, damit keine Straße ohne Radverkehr die Verkettung bestimmt
--   wege      TILDA-Wege (routing roadsPathClasses) als Kanten des Graphen (id = Kanten-ID), ungefaltete separate
--             Radwege (radwege_abgelehnt, id = bl_input.id) und die ungefalteten Reste aller Radwege mit gefalteten
--             Stücken (unabhängig vom Status, auch "nicht gefaltet" mit kleinem gefaltetem Anteil) ab :rest_min_m
--             (id = 300000000 + n; Schnittpunkte bekommen eigene, negative Knoten-IDs)
-- Name (match_key, normalisiert wie im Matcher) aus routing.
-- psql-Variablen: rest_min_m (Standard 10)
\if :{?rest_min_m}
\else
\set rest_min_m 10
\endif
BEGIN;
DROP TABLE IF EXISTS bikegraph.dc_rest, bikegraph.dc_input;

-- Name je TILDA-Objekt aus routing, normalisiert (Kleinschreibung, "str." -> "straße", ohne Leerzeichen und "-")
CREATE TEMP TABLE rname ON COMMIT DROP AS
SELECT tags->>'source_id' AS routing_id,
       regexp_replace(replace(replace(lower(trim(max(tags->>'name'))), 'str.', 'straße'), 'strasse', 'straße'), '[[:space:]-]', '', 'g') AS name_norm
FROM public.routing GROUP BY 1;
CREATE INDEX ON rname (routing_id);

-- Gefaltete Anteile je Radweg mit gefalteten Stücken auf seiner eigenen Geometrie (0..1): Endpunkte des
-- Straßenstücks auf den Radweg projiziert. Jeder Status zählt: auch "nicht gefaltet" (<= 5 %) hat Faltungszeilen und
-- käme sonst weder über radwege_abgelehnt (nur ganz ohne Faltung) noch als Rest in den Eingang.
CREATE TEMP TABLE teil ON COMMIT DROP AS
SELECT f.input_id, least(p.a, p.b) AS lo, greatest(p.a, p.b) AS hi
FROM bikegraph.bl_faltung f
JOIN bikegraph.bl_input i ON i.id = f.input_id
JOIN bikegraph.edges e ON e.id = f.strassen_kante,
LATERAL (SELECT ST_LineSubstring(e.geom, greatest(f.from_m, 0) / e.len, least(f.to_m, e.len) / e.len) AS g) s,
LATERAL (SELECT ST_LineLocatePoint(i.geom, ST_StartPoint(s.g)) AS a, ST_LineLocatePoint(i.geom, ST_EndPoint(s.g)) AS b) p
WHERE f.gespiegelt = 0 AND e.len > 0 AND GeometryType(s.g) = 'LINESTRING' AND i.art IN ('separat', 'seitenobjekt_separat');

-- Ungefaltete Reste: [0,1] minus Vereinigung der gefalteten Anteile, ab :rest_min_m
CREATE TABLE bikegraph.dc_rest AS
SELECT row_number() OVER (ORDER BY x.input_id, lower(x.r))::bigint AS n, x.input_id, lower(x.r)::float8 AS lo, upper(x.r)::float8 AS hi
FROM (SELECT t.input_id, unnest(nummultirange(numrange(0, 1, '[]')) - range_agg(numrange(t.lo::numeric, t.hi::numeric, '[]'))) AS r
      FROM teil t GROUP BY t.input_id) x
JOIN bikegraph.bl_input i ON i.id = x.input_id
WHERE (upper(x.r) - lower(x.r))::float8 * i.cost >= :rest_min_m;

CREATE TABLE bikegraph.dc_input AS
-- Straßen
SELECT 100000000 + e.id AS id, e.source, e.target, e.len AS cost, e.len AS reverse_cost, 'strassen'::text AS trace_group,
       coalesce(rn.name_norm, '') AS match_key, e.routing_id AS input_ref, e.geom::geometry(LineString, 25833) AS geom,
       '{}'::jsonb AS attrs, 'strasse'::text AS art, e.id AS kante
FROM bikegraph.bl_strassen1 n JOIN bikegraph.edges e ON e.id = n.edge_id LEFT JOIN rname rn ON rn.routing_id = e.routing_id
WHERE e.len > 0 AND (e.fwd OR e.bwd OR EXISTS (SELECT 1 FROM bikegraph.bl_faltung f WHERE f.strassen_kante = e.id))
UNION ALL
-- TILDA-Wege (routing roadsPathClasses), Geometrie in erlaubter Richtung
SELECT e.id, CASE WHEN e.bwd AND NOT e.fwd THEN e.target ELSE e.source END, CASE WHEN e.bwd AND NOT e.fwd THEN e.source ELSE e.target END,
       e.len, CASE WHEN e.fwd AND e.bwd THEN e.len ELSE -1 END, 'wege', coalesce(rn.name_norm, ''), e.routing_id,
       (CASE WHEN e.bwd AND NOT e.fwd THEN ST_Reverse(e.geom) ELSE e.geom END)::geometry(LineString, 25833), '{}'::jsonb, 'weg', e.id
FROM bikegraph.edges e JOIN bikegraph.tilda t ON t.id = e.routing_id LEFT JOIN rname rn ON rn.routing_id = e.routing_id
WHERE e.herkunft = 'separat' AND t.source_table = 'roadsPathClasses' AND e.len > 0 AND (e.fwd OR e.bwd)
UNION ALL
-- ungefaltete separate Radwege
SELECT i.id, i.source, i.target, i.cost, i.reverse_cost, 'wege', coalesce(rn.name_norm, ''), i.input_ref, i.geom, '{}'::jsonb,
       'radweg_ungefaltet', i.kante
FROM radweg_faltung.radwege_abgelehnt a JOIN bikegraph.bl_input i ON i.id = a.id
LEFT JOIN rname rn ON rn.routing_id = split_part(i.input_ref, '/', 1) || '/' || split_part(i.input_ref, '/', 2)
UNION ALL
-- ungefaltete Reste von Radwegen mit gefalteten Stücken
SELECT 300000000 + r.n, CASE WHEN r.lo <= 1e-6 THEN i.source ELSE -(2 * r.n) END, CASE WHEN r.hi >= 1 - 1e-6 THEN i.target ELSE -(2 * r.n + 1) END,
       (r.hi - r.lo) * i.cost, CASE WHEN i.reverse_cost >= 0 THEN (r.hi - r.lo) * i.cost ELSE -1 END, 'wege', coalesce(rn.name_norm, ''),
       i.input_ref, ST_LineSubstring(i.geom, r.lo, r.hi)::geometry(LineString, 25833), '{}'::jsonb, 'radweg_rest', i.kante
FROM bikegraph.dc_rest r JOIN bikegraph.bl_input i ON i.id = r.input_id
LEFT JOIN rname rn ON rn.routing_id = split_part(i.input_ref, '/', 1) || '/' || split_part(i.input_ref, '/', 2);
ALTER TABLE bikegraph.dc_input ADD PRIMARY KEY (id);
CREATE INDEX ON bikegraph.dc_input (trace_group);
CREATE INDEX ON bikegraph.dc_input USING gist (geom);
COMMIT;
ANALYZE bikegraph.dc_input;

SELECT trace_group, art, count(*) AS wege, count(*) FILTER (WHERE reverse_cost < 0) AS einrichtung,
       round((sum(cost) / 1000)::numeric, 1) AS km
FROM bikegraph.dc_input GROUP BY 1, 2 ORDER BY 1, 2;
