-- Schritt 0b: Eingangstabelle aus sql/04_input.sql (bikegraph.input_raw) im Format von matching.input_edges.
-- Ein TILDA-Objekt je Zeile (Weg oder Seitenobjekt), ungeteilt; Mehrteiliges wird in Teile zerlegt (gleiche input_ref).
-- Steht ein Weg in mehreren TILDA-Tabellen (z. B. Fahrradstraße in roads und bikelanes, Gehweg mit Radfreigabe in
-- bikelanes und roadsPathClasses), gilt die Radinfrastruktur: bikelanes vor roads vor roadsPathClasses (wie das TILDA-Routing).
-- Einrichtungswege (verkehrsri = 'Einrichtungsverkehr') nur in Digitalisierungsrichtung (reverse_cost = -1).
BEGIN;
DROP TABLE IF EXISTS bikegraph.input_edges;
CREATE OR REPLACE FUNCTION bikegraph.normalize_match_key(name text) RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT NULLIF(regexp_replace(replace(replace(lower(btrim(name)), 'str.', 'straße'), 'strasse', 'straße'), '[[:space:]-]', '', 'g'), '')
$$;
CREATE TABLE bikegraph.input_edges AS
SELECT row_number() OVER (ORDER BY r.n, d.path) AS id, NULL::bigint AS source, NULL::bigint AS target,
       ST_Length(d.geom) AS cost,
       CASE WHEN r.attrs->>'verkehrsri' = 'Einrichtungsverkehr' THEN -1 ELSE ST_Length(d.geom) END AS reverse_cost,
       r.trace_group, bikegraph.normalize_match_key(r.attrs->>'tilda_name') AS match_key, r.input_ref,
       d.geom::geometry(LineString, 25833) AS geom, r.attrs
FROM (SELECT DISTINCT ON (input_ref) * FROM bikegraph.input_raw
      ORDER BY input_ref, CASE trace_group WHEN 'bikelanes' THEN 1 WHEN 'streets' THEN 2 ELSE 3 END) r
CROSS JOIN LATERAL ST_Dump(ST_LineMerge(ST_SetSRID(ST_GeomFromWKB(decode(r.geom_hex, 'hex')), 25833))) d
WHERE GeometryType(d.geom) = 'LINESTRING' AND ST_NPoints(d.geom) >= 2 AND ST_Length(d.geom) > 0;
ALTER TABLE bikegraph.input_edges ADD PRIMARY KEY (id);
CREATE INDEX ON bikegraph.input_edges (input_ref);
CREATE INDEX ON bikegraph.input_edges (trace_group);
CREATE INDEX ON bikegraph.input_edges USING gist (geom);
COMMIT;
ANALYZE bikegraph.input_edges;
SELECT trace_group, count(*) AS zeilen, count(DISTINCT input_ref) AS tilda_objekte, round(sum(cost)::numeric / 1000) AS km
FROM bikegraph.input_edges GROUP BY 1 ORDER BY 1;
