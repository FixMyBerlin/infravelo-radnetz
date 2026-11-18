-- Radwege auf Straßen falten (radweg_faltung.sh), Ergebnis und Export für Martin.
-- bikegraph.bl_faltung: je gefaltetem Stück Straßenkante (bikegraph.edges.id), Richtung auf der Kante (ri), Lage in m
--   entlang der Kante, Radweg (bl_input.id) und Durchgang:
--   definiert  Seitenobjekte auf Kanten des Straßennetzes: ihre Straßenkante ganz, in ihrer Richtung (beidseitige in
--              beiden); Seitenobjekte außerhalb des Netzes (art seitenobjekt_separat) wie separate Radwege
--   1 / 2b / 2e  separate Radwege aus Durchgang 1, oder aus Durchgang 2 für die dort neu gematchten (< 50 % in
--                Durchgang 1): 2b zweirichtig auf Straßen in beide Richtungen, 2e einrichtig auf umgedrehten Einbahnen
-- Plausibilitätswerte je Stück (noch kein Filter):
--   strasse_m    Länge des Straßenstücks; rad_m: Länge des zugehörigen Radwegteils (Endpunkte des Straßenstücks auf den
--   Radweg projiziert); verhaeltnis = strasse_m / rad_m; breite_m = Schuhbandfläche (Straßenstück + Radwegteil) /
--   strasse_m; querung_m = Länge des Radwegteils, wenn der Radweg eine Querung ist
-- Je Radweg: anteil_gefaltet (Summe rad_m / Länge), status gefaltet (>= 80 %), teilweise (> 5 %), nicht gefaltet
-- Ausgang (Schema radweg_faltung): rvn, strassen, radwege, radweg_traces, strassen_mit_radwegen, stubs,
--   radwege_abgelehnt (separat behandelte Radwege ohne ein einziges gefaltetes Stück, für den späteren RVN-Schritt)
BEGIN;
DROP TABLE IF EXISTS bikegraph.bl_faltung;
CREATE TABLE bikegraph.bl_faltung AS
SELECT i.kante AS strassen_kante, d.ri, 0::float8 AS from_m, e.len AS to_m, i.id AS input_id, 'definiert'::text AS durchgang,
       0 AS gespiegelt, NULL::float8 AS score
FROM bikegraph.bl_input i JOIN bikegraph.edges e ON e.id = i.kante,
     LATERAL (VALUES (CASE WHEN i.umgedreht THEN 1 ELSE 0 END), (CASE WHEN i.reverse_cost >= 0 AND NOT i.umgedreht THEN 1 END)) d(ri)
WHERE i.art = 'seitenobjekt' AND d.ri IS NOT NULL
UNION ALL
SELECT x.ref_id, x.ri::int, x.from_m, x.to_m, x.input_id, '1', x.mirrored::int, x.score
FROM bikegraph.bl_iv1 x JOIN bikegraph.bl_input i ON i.id = x.input_id
WHERE i.art IN ('separat', 'seitenobjekt_separat') AND x.to_m > x.from_m AND NOT EXISTS (SELECT 1 FROM bikegraph.bl_input2 j WHERE j.id = x.input_id)
UNION ALL
SELECT x.ref_id, x.ri::int, x.from_m, x.to_m, x.input_id, x.variante, x.mirrored::int, x.score
FROM bikegraph.bl_iv2 x WHERE x.to_m > x.from_m;
CREATE INDEX ON bikegraph.bl_faltung (input_id);
CREATE INDEX ON bikegraph.bl_faltung (strassen_kante, ri);

-- Stücke mit Geometrie und Plausibilitätswerten
CREATE TEMP TABLE st ON COMMIT DROP AS
SELECT f.*, i.input_ref, i.art, i.kategorie, i.seite, i.geom AS rad_geom, ST_Length(i.geom) AS rad_len,
       CASE WHEN f.ri = 1 THEN ST_Reverse(s.g) ELSE s.g END AS strasse_geom
FROM bikegraph.bl_faltung f JOIN bikegraph.bl_input i ON i.id = f.input_id JOIN bikegraph.edges e ON e.id = f.strassen_kante,
     LATERAL (SELECT ST_LineSubstring(e.geom, greatest(f.from_m, 0) / e.len, least(f.to_m, e.len) / e.len) AS g) s
WHERE e.len > 0;
CREATE TEMP TABLE pl ON COMMIT DROP AS
SELECT st.*, ST_Length(strasse_geom) AS strasse_m,
       ST_LineLocatePoint(rad_geom, ST_StartPoint(strasse_geom)) AS a, ST_LineLocatePoint(rad_geom, ST_EndPoint(strasse_geom)) AS b
FROM st WHERE GeometryType(strasse_geom) = 'LINESTRING';
CREATE TEMP TABLE pl2 ON COMMIT DROP AS
SELECT pl.*, abs(b - a) * rad_len AS rad_m,
       CASE WHEN abs(b - a) * rad_len > 0.01 THEN
         CASE WHEN b >= a THEN ST_LineSubstring(rad_geom, a, b) ELSE ST_Reverse(ST_LineSubstring(rad_geom, b, a)) END END AS rad_teil
FROM pl;

-- nur die eigenen Tabellen ersetzen; Auswertungstabellen im Schema (z. B. sql/102) bleiben erhalten
CREATE SCHEMA IF NOT EXISTS radweg_faltung;
DROP TABLE IF EXISTS radweg_faltung.strassen_mit_radwegen, radweg_faltung.radwege, radweg_faltung.rvn, radweg_faltung.strassen,
  radweg_faltung.radweg_traces, radweg_faltung.stubs, radweg_faltung.radwege_abgelehnt;

CREATE TABLE radweg_faltung.strassen_mit_radwegen AS
SELECT row_number() OVER (ORDER BY strassen_kante, ri, from_m)::bigint AS id, strassen_kante, ri, input_id AS radweg, input_ref, art,
       kategorie, seite, durchgang, gespiegelt, round(strasse_m::numeric, 1) AS strasse_m, round(rad_m::numeric, 1) AS rad_m,
       round((strasse_m / nullif(rad_m, 0))::numeric, 2) AS verhaeltnis,
       round((CASE WHEN art = 'seitenobjekt' THEN 0
                   WHEN rad_teil IS NOT NULL AND strasse_m > 0 THEN
                     ST_Area(ST_MakePolygon(ST_AddPoint(ST_MakeLine(strasse_geom, ST_Reverse(rad_teil)), ST_StartPoint(strasse_geom)))) / strasse_m
              END)::numeric, 1) AS breite_m,
       round((CASE WHEN kategorie = 'crossing' THEN rad_m ELSE 0 END)::numeric, 1) AS querung_m,
       round(score::numeric, 2) AS score,
       strasse_geom::geometry(LineString, 25833) AS geom
FROM pl2;

CREATE TEMP TABLE weg ON COMMIT DROP AS
SELECT input_id, sum(rad_m) FILTER (WHERE gespiegelt = 0) AS rad_gefaltet_m, min(durchgang) AS durchgang FROM pl2 GROUP BY 1;
CREATE INDEX ON weg (input_id);
CREATE TABLE radweg_faltung.radwege AS
SELECT i.id, i.input_ref, i.art, i.kategorie, i.seite, (i.reverse_cost < 0) AS einrichtung, round(i.cost::numeric, 1) AS laenge_m,
       CASE WHEN i.art = 'seitenobjekt' THEN 'definiert'
            ELSE coalesce(w.durchgang, CASE WHEN j.id IS NULL THEN '1' WHEN i.reverse_cost >= 0 THEN '2b' ELSE '2e' END) END AS durchgang,
       round(least(coalesce(w.rad_gefaltet_m, 0) / nullif(i.cost, 0), 1)::numeric, 2) AS anteil_gefaltet,
       CASE WHEN i.art = 'seitenobjekt' THEN 'definiert'
            WHEN coalesce(w.rad_gefaltet_m, 0) >= 0.8 * i.cost THEN 'gefaltet'
            WHEN coalesce(w.rad_gefaltet_m, 0) > 0.05 * i.cost THEN 'teilweise'
            ELSE 'nicht gefaltet' END AS status,
       i.geom
FROM bikegraph.bl_input i LEFT JOIN weg w ON w.input_id = i.id LEFT JOIN bikegraph.bl_input2 j ON j.id = i.id;

CREATE TABLE radweg_faltung.rvn AS
SELECT id, element_nr, strassenname, verkehrsrichtung, round(ST_Length(geom)::numeric, 1) AS laenge_m, geom::geometry(LineString, 25833) AS geom
FROM matching.reference_edges;

-- Straßennetz der Faltung mit Attributen aus dem TILDA-Routing-Export (Straßenklasse road, Name, dual_carriageway)
CREATE TEMP TABLE rs ON COMMIT DROP AS
SELECT tags->>'source_id' AS routing_id, max(tags->>'road') AS road, max(tags->>'name') AS name,
       max(tags->>'category') FILTER (WHERE tags->>'side' = 'self') AS category,
       bool_or(coalesce(tags->>'dual_carriageway', '') = 'yes') AS dual, bool_or(coalesce(tags->>'roundabout', '') = 'yes') AS kreis
FROM public.routing GROUP BY 1;
CREATE INDEX ON rs (routing_id);
CREATE TABLE radweg_faltung.strassen AS
SELECT e.id, e.routing_id AS osm_id, r.category, r.road, r.name,
       CASE WHEN n.cost >= 0 AND n.reverse_cost >= 0 THEN 'beide' WHEN n.cost >= 0 THEN 'vorwärts' ELSE 'rückwärts' END AS richtung,
       r.dual AS dual_carriageway, r.kreis AS kreisverkehr, round(e.len::numeric, 1) AS laenge_m, e.geom
FROM bikegraph.bl_strassen1 n JOIN bikegraph.edges e ON e.id = n.edge_id JOIN rs r ON r.routing_id = e.routing_id;

CREATE TABLE radweg_faltung.radweg_traces AS
SELECT row_number() OVER (ORDER BY durchgang, trace_id)::bigint AS id, durchgang, trace_id, count(*) AS n_wege,
       round(sum(ST_Length(geom))::numeric, 1) AS laenge_m, sum(n_obs) AS n_obs, sum(n_gematcht) AS n_gematcht,
       sum(n_brueche) AS n_brueche, count(*) FILTER (WHERE input_id >= 20000000) AS n_seitenobjekte,
       ST_Multi(ST_Collect(geom ORDER BY seq))::geometry(MultiLineString, 25833) AS geom
FROM (SELECT '1'::text AS durchgang, trace_id, seq, input_id, n_obs, n_gematcht, n_brueche, geom FROM bikegraph.bl_iv1_traces WHERE kontext = 0
      UNION ALL SELECT variante, trace_id, seq, input_id, n_obs, n_gematcht, n_brueche, geom FROM bikegraph.bl_iv2_traces WHERE kontext = 0) t
GROUP BY durchgang, trace_id;

CREATE TABLE radweg_faltung.stubs AS
SELECT row_number() OVER (ORDER BY durchgang, fid)::bigint AS id, durchgang, trace_id, ref_id AS strassen_kante, ri::int AS ri,
       round((to_m - from_m)::numeric, 1) AS laenge_m, input_von, input_nach, geom::geometry(LineString, 25833) AS geom
FROM (SELECT '1'::text AS durchgang, fid, trace_id, ref_id, ri, from_m, to_m, input_von, input_nach, geom FROM bikegraph.bl_iv1_stubs
      UNION ALL SELECT variante, fid, trace_id, ref_id, ri, from_m, to_m, input_von, input_nach, geom FROM bikegraph.bl_iv2_stubs) s;

-- separat behandelte Radwege, die auf keine Straße gefaltet wurden (auch nicht teilweise)
CREATE TABLE radweg_faltung.radwege_abgelehnt AS
SELECT r.id, r.input_ref, r.art, r.kategorie, r.seite, r.einrichtung, r.laenge_m, r.durchgang, r.geom
FROM radweg_faltung.radwege r
WHERE r.art IN ('separat', 'seitenobjekt_separat')
  AND NOT EXISTS (SELECT 1 FROM bikegraph.bl_faltung f WHERE f.input_id = r.id);

ALTER TABLE radweg_faltung.rvn ADD PRIMARY KEY (id);
ALTER TABLE radweg_faltung.strassen ADD PRIMARY KEY (id);
ALTER TABLE radweg_faltung.radwege ADD PRIMARY KEY (id);
ALTER TABLE radweg_faltung.radweg_traces ADD PRIMARY KEY (id);
ALTER TABLE radweg_faltung.strassen_mit_radwegen ADD PRIMARY KEY (id);
ALTER TABLE radweg_faltung.stubs ADD PRIMARY KEY (id);
ALTER TABLE radweg_faltung.radwege_abgelehnt ADD PRIMARY KEY (id);
CREATE INDEX ON radweg_faltung.radwege_abgelehnt USING gist (geom);
CREATE INDEX ON radweg_faltung.rvn USING gist (geom);
CREATE INDEX ON radweg_faltung.strassen USING gist (geom);
CREATE INDEX ON radweg_faltung.radwege USING gist (geom);
CREATE INDEX ON radweg_faltung.radweg_traces USING gist (geom);
CREATE INDEX ON radweg_faltung.strassen_mit_radwegen USING gist (geom);
CREATE INDEX ON radweg_faltung.stubs USING gist (geom);
COMMIT;
ANALYZE radweg_faltung.rvn, radweg_faltung.strassen, radweg_faltung.radwege, radweg_faltung.radweg_traces,
  radweg_faltung.strassen_mit_radwegen, radweg_faltung.stubs;

\echo 'Radwege nach Status (km)'
SELECT art, status, durchgang, count(*) AS wege, round(sum(laenge_m) / 1000) AS km FROM radweg_faltung.radwege GROUP BY 1, 2, 3 ORDER BY 1, 2, 3;
\echo 'gefaltete Stücke'
SELECT art, durchgang, count(*) AS stuecke, round(sum(strasse_m) / 1000) AS strasse_km,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY verhaeltnis)::numeric, 2) AS median_verhaeltnis,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY breite_m)::numeric, 1) AS median_breite_m
FROM radweg_faltung.strassen_mit_radwegen WHERE gespiegelt = 0 GROUP BY 1, 2 ORDER BY 1, 2;
SELECT 'traces' AS tabelle, count(*) FROM radweg_faltung.radweg_traces UNION ALL SELECT 'stubs', count(*) FROM radweg_faltung.stubs;
