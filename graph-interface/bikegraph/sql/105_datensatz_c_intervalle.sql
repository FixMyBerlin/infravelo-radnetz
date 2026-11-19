-- Datensatz C aus Straßen (mit gefalteten Radwegen) und Wegen: Rohintervalle des Matchings (bikegraph.dc_iv_raw,
-- Eingang sql/104 auf matching.reference_edges) in Intervalle je TILDA-Objekt für map-matching assemble.
--   wege      das eigene TILDA-Objekt des Wegs auf seinem RVN-Abschnitt
--   strassen  jeder Kandidat der Straßenkante in der passenden Straßenrichtung, auf den gematchten RVN-Abschnitt
--             projiziert (Variante A: nur die Straße wird gematcht, die Kandidaten folgen ihr):
--               strasse       die Straße selbst, nur in Richtungen mit Radfreigabe (edges.fwd/bwd)
--               seitenobjekt  Radstreifen u. ä. der Straße (bl_faltung, durchgang definiert)
--               seitenweg     auf die Straße gefaltete separate Radwege (bl_faltung, Durchgang 1/2b/2e, auch gespiegelt)
--             Straßenrichtung aus der Lage der Straßenkante zur RVN-Kante: gleich gerichtet -> ri der Straße = ri des RVN,
--             sonst umgekehrt. Kandidaten über die ganze Straßenkante übernehmen die gematchten Abschnitte der Kante
--             unverändert (das HMM ordnet die Kante zu, auch über eine Ecke auf zwei RVN-Kanten); nur Teilstücke
--             (from_m..to_m auf der Straßenkante) werden über ihre Endpunkte aufs RVN projiziert und auf den gematchten
--             Abschnitt begrenzt (eine Straßenkante über eine Ecke verlöre sonst den Teil, dessen Ende geometrisch neben
--             der RVN-Kante liegt).
--             Güte: die des Straßen-Traces, dazu ein kleiner Abschlag nur zum Auflösen von Gleichständen (alle Kandidaten
--             einer Straße hätten sonst dieselbe Güte, und assemble entschiede innerhalb eines Tiers zufällig):
--             Seitenobjekt 0 (gehört per Definition zur Straße), gefalteter Radweg -1e-7..-1e-6 nach seiner Faltungsgüte,
--             Straße selbst -2e-6. Die Güten auf dem RVN streuen um Größenordnungen mehr (Median etwa -0,4).
-- Ausgang bikegraph.intervals_dc (Format bikegraph.intervals).
-- psql-Variablen: min_length_m (Standard 0.5)
\if :{?min_length_m}
\else
\set min_length_m 0.5
\endif
BEGIN;
DROP TABLE IF EXISTS bikegraph.intervals_dc;

CREATE TEMP TABLE inp ON COMMIT DROP AS SELECT input_ref, min(id) AS id FROM bikegraph.input_edges GROUP BY 1;
CREATE INDEX ON inp (input_ref);

CREATE TEMP TABLE raw ON COMMIT DROP AS
SELECT x.ref_id, x.ri::int AS ri, x.from_m, x.to_m, x.score, x.n_obs, x.mirrored, x.trace_id, d.trace_group, d.art, d.kante, d.input_ref
FROM bikegraph.dc_iv_raw x JOIN bikegraph.dc_input d ON d.id = x.input_id
WHERE x.to_m > x.from_m;
CREATE INDEX ON raw (kante);

-- Kandidaten je Straßenkante und Richtung (Lage in m entlang der Kantengeometrie)
CREATE TEMP TABLE kand ON COMMIT DROP AS
SELECT e.id AS kante, d.ri, 0::float8 AS von, e.len AS bis, e.routing_id AS input_ref, 'strasse'::text AS art, -2e-6::float8 AS abschlag
FROM bikegraph.edges e, (VALUES (0), (1)) d(ri)
WHERE e.id IN (SELECT kante FROM raw WHERE trace_group = 'strassen') AND CASE WHEN d.ri = 0 THEN e.fwd ELSE e.bwd END
UNION ALL
SELECT f.strassen_kante, f.ri, f.from_m, f.to_m, i.input_ref, CASE WHEN f.durchgang = 'definiert' THEN 'seitenobjekt' ELSE 'seitenweg' END,
       CASE WHEN f.durchgang = 'definiert' THEN 0
            ELSE -1e-7 * (1 + least(greatest(-coalesce(f.score, -9), 0), 9)) END
FROM bikegraph.bl_faltung f JOIN bikegraph.bl_input i ON i.id = f.input_id
WHERE f.to_m > f.from_m;
CREATE INDEX ON kand (kante, ri);

-- Straßenintervalle: Richtung der Straße zum RVN
CREATE TEMP TABLE sv ON COMMIT DROP AS
SELECT x.*, e.geom AS kgeom, e.len AS klen, r.geom AS rgeom, ST_Length(r.geom) AS rlen,
       CASE WHEN ST_LineLocatePoint(r.geom, ST_EndPoint(e.geom)) >= ST_LineLocatePoint(r.geom, ST_StartPoint(e.geom))
            THEN x.ri ELSE 1 - x.ri END AS kri
FROM raw x JOIN bikegraph.edges e ON e.id = x.kante JOIN matching.reference_edges r ON r.id = x.ref_id
WHERE x.trace_group = 'strassen' AND e.len > 0;

CREATE TEMP TABLE teil ON COMMIT DROP AS
-- Wege: eigenes Objekt
SELECT x.ref_id, x.ri, x.from_m AS a, x.to_m AS b, x.input_ref, x.art, 'wege'::text AS phase, x.score, x.n_obs, x.mirrored, x.trace_id
FROM raw x WHERE x.trace_group = 'wege'
UNION ALL
-- Straßen: Kandidaten über die ganze Straßenkante (Straße selbst, Seitenobjekte, ganz gefaltete Radwege) übernehmen den
-- gematchten Abschnitt unverändert (Zuordnung des HMM, auch um Ecken auf mehrere RVN-Kanten); Teilstücke projiziert
-- und auf den gematchten Abschnitt begrenzt
SELECT s.ref_id, s.ri,
       CASE WHEN k.von <= 0.01 AND k.bis >= s.klen - 0.01 THEN s.from_m ELSE greatest(least(p.p1, p.p2), s.from_m) END,
       CASE WHEN k.von <= 0.01 AND k.bis >= s.klen - 0.01 THEN s.to_m ELSE least(greatest(p.p1, p.p2), s.to_m) END,
       k.input_ref, k.art, 'strassen',
       s.score + k.abschlag, s.n_obs, s.mirrored, s.trace_id
FROM sv s JOIN kand k ON k.kante = s.kante AND k.ri = s.kri,
LATERAL (SELECT ST_LineLocatePoint(s.rgeom, ST_LineInterpolatePoint(s.kgeom, greatest(least(k.von / s.klen, 1.0), 0.0)::float8)) * s.rlen AS p1,
                ST_LineLocatePoint(s.rgeom, ST_LineInterpolatePoint(s.kgeom, greatest(least(k.bis / s.klen, 1.0), 0.0)::float8)) * s.rlen AS p2) p;

CREATE TABLE bikegraph.intervals_dc AS
SELECT row_number() OVER (ORDER BY t.ref_id, t.ri, t.a, i.id)::bigint AS ord, t.ref_id, r.element_nr, t.ri::bigint AS ri,
       t.a AS from_m, t.b AS to_m, i.id AS input_id, ie.input_ref, ie.trace_group::varchar AS trace_group, t.trace_id, t.score, t.n_obs,
       t.mirrored::bigint AS mirrored, t.phase, t.art,
       ST_LineSubstring(r.geom, greatest(least(t.a / ST_Length(r.geom), 1), 0), greatest(least(t.b / ST_Length(r.geom), 1), 0))::geometry(LineString, 25833) AS geom
FROM teil t JOIN inp i ON i.input_ref = t.input_ref JOIN bikegraph.input_edges ie ON ie.id = i.id
JOIN matching.reference_edges r ON r.id = t.ref_id
WHERE t.b - t.a >= :min_length_m AND ST_Length(r.geom) > 0;
CREATE INDEX ON bikegraph.intervals_dc (ref_id, ri);
COMMIT;
ANALYZE bikegraph.intervals_dc;

\echo 'Intervalle je Herkunft und Kandidatenart'
SELECT phase, art, count(*) AS intervalle, count(DISTINCT input_id) AS objekte, round((sum(to_m - from_m) / 1000)::numeric, 1) AS km
FROM bikegraph.intervals_dc GROUP BY 1, 2 ORDER BY 1, 2;
