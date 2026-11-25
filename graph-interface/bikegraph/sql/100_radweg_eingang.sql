-- Radwege auf Straßen falten (radweg_faltung.sh), Eingang und Netze.
-- Eingang bikegraph.bl_input (Format postgres.input_edges, eine trace_group 'bikelanes', damit Traces von
-- Seitenobjekten auf separate Radwege weiterlaufen):
--   separat       separate TILDA-Radwege als Kanten des OSM-Graphen (bikegraph.edges, herkunft separat,
--                 source_table bikelanes), Topologie über OSM-Knoten
--   seitenobjekt  Radstreifen u. ä. als Seite einer Straße (bikegraph.side_objects): die Kanten der Elternstraße mit der
--                 Richtung des Seitenobjekts; Teil der Traces, ihre Intervalle werden aber per Definition gesetzt (sql/101).
--                 Nur auf Kanten des Straßennetzes (bl_strassen1) "auf der Straße"; je Kante entschieden:
--   seitenobjekt_separat  dieselben Seitenobjekte auf Fahrbahnkanten außerhalb des Straßennetzes (service u. a.): wie
--                 separate Radwege gematcht (Durchgang 1/2), ungefaltet später für den RVN-Schritt
--   Einrichtungswege: Geometrie in erlaubter Richtung, reverse_cost = -1
-- Netze: Durchgang 1 = bikegraph.bl_strassen1 = alle Fahrbahnkanten mit einer Zeile im TILDA-Routing-Export
--        (public.routing über routing_id = source_id), ohne Tunnel (tunnel = yes dort); Richtungen way_fwd/way_bwd.
--        Kein weiterer Filter (highway, service): welche Straßen dazugehören, entscheidet routing (auch service-Straßen,
--        die TILDA behält). Die OSM-Topologie verbindet nur die Stücke und liefert keine eigenen Straßen. Dasselbe Netz
--        wird für Datensatz C auf das RVN gematcht (sql/104);
--        Durchgang 2e (Einrichtungs-Radwege) = bikegraph.bl_strassen2 (Einbahnen umgedreht, außer dual_carriageway
--        und Kreisverkehren, beides aus public.routing); Durchgang 2b (Zweirichtungs-Radwege) = bikegraph.bl_strassen_beide (alle Straßen in beide
--        Richtungen befahrbar: für einen Zweirichtungs-Radweg ist die Richtung der Straße egal, die gespiegelte Kopie
--        schreibt beide Richtungen)
BEGIN;
DROP TABLE IF EXISTS bikegraph.bl_input, bikegraph.bl_strassen1, bikegraph.bl_strassen2, bikegraph.bl_strassen_beide;

-- Straßennetz der Faltung: wie für das RVN-Matching, aber nur Straßen aus dem TILDA-Routing-Export und ohne Tunnel
CREATE TEMP TABLE routing_strasse ON COMMIT DROP AS
SELECT tags->>'source_id' AS routing_id, bool_or(coalesce(tags->>'tunnel', '') = 'yes') AS tunnel,
       bool_or(coalesce(tags->>'dual_carriageway', '') = 'yes') AS dual, bool_or(coalesce(tags->>'roundabout', '') = 'yes') AS kreis
FROM public.routing GROUP BY 1;
CREATE INDEX ON routing_strasse (routing_id);
CREATE TABLE bikegraph.bl_strassen1 AS
SELECT e.id, e.source, e.target,
       CASE WHEN e.way_fwd THEN e.len ELSE -1 END AS cost, CASE WHEN e.way_bwd THEN e.len ELSE -1 END AS reverse_cost,
       NULL::text AS match_key, e.geom, ('fahrbahn/' || e.id || '/1')::text AS element_nr, 1 AS part,
       NULL::varchar AS beginnt_bei_vp, NULL::varchar AS endet_bei_vp, NULL::varchar AS strassenname,
       NULL::varchar AS verkehrsrichtung, 'fahrbahn'::varchar AS edge_source, e.id AS edge_id
FROM bikegraph.edges e JOIN routing_strasse r ON r.routing_id = e.routing_id
WHERE e.herkunft = 'fahrbahn' AND e.len > 0 AND (e.way_fwd OR e.way_bwd) AND NOT r.tunnel;
ALTER TABLE bikegraph.bl_strassen1 ADD PRIMARY KEY (id);
CREATE INDEX ON bikegraph.bl_strassen1 (edge_id);
CREATE INDEX ON bikegraph.bl_strassen1 USING gist (geom);

CREATE TABLE bikegraph.bl_input AS
SELECT e.id,
       CASE WHEN e.bwd AND NOT e.fwd THEN e.target ELSE e.source END AS source,
       CASE WHEN e.bwd AND NOT e.fwd THEN e.source ELSE e.target END AS target,
       e.len AS cost, CASE WHEN e.fwd AND e.bwd THEN e.len ELSE -1 END AS reverse_cost,
       'bikelanes'::text AS trace_group, ''::text AS match_key, e.routing_id AS input_ref,
       (CASE WHEN e.bwd AND NOT e.fwd THEN ST_Reverse(e.geom) ELSE e.geom END)::geometry(LineString, 25833) AS geom,
       jsonb_build_object('tilda_category', t.tags->>'category') AS attrs,
       'separat'::text AS art, e.id AS kante, (e.bwd AND NOT e.fwd) AS umgedreht, NULL::text AS seite,
       coalesce(t.tags->>'category', '') AS kategorie
FROM bikegraph.edges e JOIN bikegraph.tilda t ON t.id = e.routing_id
WHERE e.herkunft = 'separat' AND t.source_table = 'bikelanes' AND e.len > 0 AND (e.fwd OR e.bwd)
UNION ALL
SELECT 20000000 + row_number() OVER (ORDER BY s.routing_id, r.id),
       CASE WHEN s.bwd AND NOT s.fwd THEN r.target ELSE r.source END,
       CASE WHEN s.bwd AND NOT s.fwd THEN r.source ELSE r.target END,
       r.len, CASE WHEN s.fwd AND s.bwd THEN r.len ELSE -1 END,
       'bikelanes', '', s.routing_id,
       (CASE WHEN s.bwd AND NOT s.fwd THEN ST_Reverse(r.geom) ELSE r.geom END)::geometry(LineString, 25833),
       jsonb_build_object('tilda_category', s.category),
       CASE WHEN n.edge_id IS NOT NULL THEN 'seitenobjekt' ELSE 'seitenobjekt_separat' END, r.id, (s.bwd AND NOT s.fwd), s.side,
       coalesce(s.category, '')
FROM bikegraph.side_objects s JOIN bikegraph.edges r ON r.way_id = s.way_id AND r.herkunft = 'fahrbahn'
LEFT JOIN bikegraph.bl_strassen1 n ON n.edge_id = r.id
WHERE r.len > 0 AND (s.fwd OR s.bwd);
ALTER TABLE bikegraph.bl_input ADD PRIMARY KEY (id);
CREATE INDEX ON bikegraph.bl_input (trace_group);
CREATE INDEX ON bikegraph.bl_input USING gist (geom);

CREATE TABLE bikegraph.bl_strassen2 AS
SELECT n.id, n.source, n.target,
       CASE WHEN (n.cost < 0) <> (n.reverse_cost < 0) AND NOT r.dual AND NOT r.kreis THEN n.reverse_cost ELSE n.cost END AS cost,
       CASE WHEN (n.cost < 0) <> (n.reverse_cost < 0) AND NOT r.dual AND NOT r.kreis THEN n.cost ELSE n.reverse_cost END AS reverse_cost,
       n.match_key, n.geom, n.element_nr, n.part, n.beginnt_bei_vp, n.endet_bei_vp, n.strassenname, n.verkehrsrichtung,
       n.edge_source, n.edge_id
FROM bikegraph.bl_strassen1 n JOIN bikegraph.edges e ON e.id = n.edge_id JOIN routing_strasse r ON r.routing_id = e.routing_id;
ALTER TABLE bikegraph.bl_strassen2 ADD PRIMARY KEY (id);
CREATE INDEX ON bikegraph.bl_strassen2 USING gist (geom);

CREATE TABLE bikegraph.bl_strassen_beide AS
SELECT id, source, target, ST_Length(geom) AS cost, ST_Length(geom) AS reverse_cost, match_key, geom, element_nr, part,
       beginnt_bei_vp, endet_bei_vp, strassenname, verkehrsrichtung, edge_source, edge_id
FROM bikegraph.bl_strassen1;
ALTER TABLE bikegraph.bl_strassen_beide ADD PRIMARY KEY (id);
CREATE INDEX ON bikegraph.bl_strassen_beide USING gist (geom);
COMMIT;
ANALYZE bikegraph.bl_input, bikegraph.bl_strassen1, bikegraph.bl_strassen2, bikegraph.bl_strassen_beide;
SELECT count(*) AS strassenkanten, round((sum(ST_Length(geom)) / 1000)::numeric) AS km FROM bikegraph.bl_strassen1;

SELECT art, count(*) AS wege, count(*) FILTER (WHERE reverse_cost < 0) AS einrichtung, round((sum(cost) / 1000)::numeric) AS km
FROM bikegraph.bl_input GROUP BY 1;
