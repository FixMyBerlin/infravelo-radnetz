-- Routing der RVN-Abschnitte, Teil 4 (abschnitte.sh, nach dem letzten Teil 3): Kandidaten neben dem besten Weg und Wahl
-- der Führungsform wie in der Kandidatenwahl von v7 (Stufen: Radinfrastruktur vor Mischverkehr vor Sonstigen Wegen vor
-- keiner Radinfrastruktur). Der beste Weg je Route liefert nur einen Kandidaten; hier bekommt jede ungenutzte parallele
-- Kante im Korridor die Kosten des billigsten Wegs, der sie benutzt (Via-Weg):
-- 1. Je Teilroute des besten Wegs (eine bei ganzen Routen; Teilrouten getrennt an ihrer virtuellen Zielkante) zwei Suchen
--    im Korridorgraphen mit den Kosten aus Teil 2:
--      hin:    virtueller Start -> jeder Knoten v der Teilroute mit den Kosten bis v; D_out(n) = billigster Weg "entlang
--              der Teilroute bis v, dort abbiegen, bis n"
--      zurück: im umgedrehten Graphen virtueller Start -> jeder Knoten w mit den Restkosten ab w; D_in(n) = billigster Weg
--              "von n zurück auf die Teilroute und weiter bis zu ihrem Ende"
--    Je Teilroute ist das ein kürzester Weg zwischen ihren Ankern, die Mehrkosten sind damit >= 0. Geglättete Routen
--    (Teil 2b) sind absichtlich nicht kürzest; dort werden negative Mehrkosten zu 0.
-- 2. Kandidatenkante: im Korridor, nicht im besten Weg, parallel zur Route (Fortschritt entlang der Routenlinie
--    >= kandidat_parallel x Länge), in Fahrtrichtung offen, Mitte <= kandidat_abstand_m von der Routenlinie.
--    Mehrkosten = D_out(Anfang) + Kosten + D_in(Ende) - Kosten der Teilroute (kleinster Wert über die Teilrouten).
-- 3. Zuordnung zur nächsten RVN-Kante (naechste_rvn), wenn die Route diese RVN-Kante belegt (rvn_stuecke, deren Richtung).
--    Je RVN-Kante, Richtung und Führungsform x50: die kleinsten Mehrkosten, bei denen die Form kandidat_abdeckung der
--    RVN-Kante abdeckt (Tabelle kandidat).
-- 4. Wahl: hat eine Form mit x50 <= kandidat_mehr eine bessere Stufe als das Ergebnis aus Teil 3, wird sie das Ergebnis
--    (die beste Stufe, bei gleicher die mit kleinstem x50). ergebnis.fuehr_weg behält die Form aus Teil 3, kandidat und
--    kandidat_mehr kennzeichnen den Wechsel. Mit vorrang (Standard true) gewinnt auch eine Form gleicher Stufe nach den
--    Regeln von v7 (rules.prefer in processing/map-matching/config/default.toml, wie die Abstimmung in Teil 3): geschützter
--    Radfahrstreifen vor Bussonderfahrstreifen, Bussonderfahrstreifen / Radfahrstreifen mit Linienverkehr vor einem Radweg
--    ohne Z237/240/241.
-- psql-Variablen: schema, kandidat_mehr (Standard 100; 0 = nur Kandidaten ohne Mehrkosten), kandidat_abstand_m (30),
-- kandidat_parallel (0.87, also <= 30 Grad), kandidat_abdeckung (0.5), vorrang (true)
\if :{?schema} \else \set schema routing_abschnitte \endif
\if :{?kandidat_mehr} \else \set kandidat_mehr 100 \endif
\if :{?kandidat_abstand_m} \else \set kandidat_abstand_m 30 \endif
\if :{?kandidat_parallel} \else \set kandidat_parallel 0.87 \endif
\if :{?kandidat_abdeckung} \else \set kandidat_abdeckung 0.5 \endif
\if :{?vorrang} \else \set vorrang true \endif
SET search_path TO :"schema", public;
DROP TABLE IF EXISTS via_knoten, via_teil, via_gesamt, via_out, via_in, kandidat;

CREATE FUNCTION pg_temp.stufe(f text) RETURNS int LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE WHEN f IN ('Radfahrstreifen', 'Radfahrstreifen mit Linienverkehr frei (Z237 mit Z1026-32)',
                         'Bussonderfahrstreifen mit Radverkehr frei (Z245 mit Z1022‐10)', 'Geschützter Radfahrstreifen', 'Schutzstreifen',
                         'Fahrradstraße /-zone (Z 244)', 'Radweg', 'Gemeinsamer Geh- und Radweg mit Z240',
                         'Gehweg mit Zusatzzeichen "Radverkehr frei" (Z239 mit Z1022-10)', 'Fußgängerzone "Radverkehr frei" (Z242 mit Z1022-10)',
                         'Kreuzungsweg', '[TODO] Klärung notwendig') THEN 1
              WHEN f = 'Mischverkehr mit motorisiertem Verkehr' THEN 2
              WHEN f IS NULL OR f = 'Keine Radinfrastruktur vorhanden' THEN 4 ELSE 3 END $$;

-- 1. Teilrouten des besten Wegs: neue Teilroute nach jeder virtuellen Zielkante einer Teilroute (Teil 2: Kennung
-- <= -10000000, Brücken <= -1000000000 gehören zu ihrer Teilroute); Kosten je Teilroute neu aufsummiert, virtuelle Kanten 0
CREATE TEMP TABLE pz AS
SELECT rid, seq, node, edge, cost,
       1 + coalesce(sum(CASE WHEN edge <= -10000000 AND edge > -1000000000 THEN 1 ELSE 0 END)
                    OVER (PARTITION BY rid ORDER BY seq ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0) AS teil
FROM pfad WHERE node >= 0;
CREATE TABLE via_knoten AS
SELECT rid, teil, node, min(agg) AS agg_min, max(agg) AS agg_max FROM (
    SELECT rid, teil, node, coalesce(sum(CASE WHEN edge > 0 THEN cost ELSE 0 END)
               OVER (PARTITION BY rid, teil ORDER BY seq ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0) AS agg
    FROM pz) x
GROUP BY 1, 2, 3;
CREATE INDEX ON via_knoten (rid, teil);
CREATE TABLE via_teil AS
SELECT rid, teil, sum(cost) FILTER (WHERE edge > 0) AS gesamt FROM pz GROUP BY 1, 2 HAVING count(*) FILTER (WHERE edge > 0) > 0;
ALTER TABLE via_teil ADD PRIMARY KEY (rid, teil);
CREATE TABLE via_out AS
SELECT t.rid, t.teil, d.node, d.agg_cost AS d FROM via_teil t, LATERAL pgr_drivingDistance(format($q$
    SELECT g.id, g.source, g.target,
           CASE WHEN g.faktor0 IS NULL THEN -1 ELSE g.len * (g.faktor0 + k.zusatz_je_m) + k.umweg END AS cost,
           CASE WHEN g.faktor1 IS NULL THEN -1 ELSE g.len * (g.faktor1 + k.zusatz_je_m) + k.umweg END AS reverse_cost
    FROM korridor_kanten k JOIN routing_graph.g g ON g.id = k.id WHERE k.rid = %1$s
    UNION ALL SELECT -(row_number() OVER ())::bigint, -7::bigint, node, agg_min, -1::float8
    FROM via_knoten WHERE rid = %1$s AND teil = %2$s$q$, t.rid, t.teil), -7::bigint, 1e9::float8, true) d
WHERE d.node <> -7;
CREATE TABLE via_in AS
SELECT t.rid, t.teil, d.node, d.agg_cost AS d FROM via_teil t, LATERAL pgr_drivingDistance(format($q$
    SELECT g.id, g.target AS source, g.source AS target,
           CASE WHEN g.faktor0 IS NULL THEN -1 ELSE g.len * (g.faktor0 + k.zusatz_je_m) + k.umweg END AS cost,
           CASE WHEN g.faktor1 IS NULL THEN -1 ELSE g.len * (g.faktor1 + k.zusatz_je_m) + k.umweg END AS reverse_cost
    FROM korridor_kanten k JOIN routing_graph.g g ON g.id = k.id WHERE k.rid = %1$s
    UNION ALL SELECT -(row_number() OVER ())::bigint, -7::bigint, v.node, %3$s - v.agg_max, -1::float8
    FROM via_knoten v WHERE v.rid = %1$s AND v.teil = %2$s$q$, t.rid, t.teil, t.gesamt), -7::bigint, 1e9::float8, true) d
WHERE d.node <> -7;
CREATE INDEX ON via_out (rid, node); CREATE INDEX ON via_in (rid, node);

-- 2. Kandidatenkanten mit Mehrkosten
CREATE TEMP TABLE benutzt AS SELECT DISTINCT rid, edge AS id FROM pfad WHERE edge > 0;
CREATE INDEX ON benutzt (rid, id);
CREATE TEMP TABLE lage AS
SELECT k.rid, g.id, g.len, ST_Distance(ST_LineInterpolatePoint(g.geom, 0.5), r.linie) AS d,
       (ST_LineLocatePoint(r.linie, ST_EndPoint(g.geom)) - ST_LineLocatePoint(r.linie, ST_StartPoint(g.geom))) * ST_Length(r.linie) AS fortschritt,
       k.zusatz_je_m, k.umweg
FROM korridor_kanten k JOIN (SELECT DISTINCT rid FROM via_teil) t ON t.rid = k.rid JOIN routing_graph.g g ON g.id = k.id
JOIN routen r ON r.rid = k.rid LEFT JOIN benutzt b ON b.rid = k.rid AND b.id = k.id
WHERE b.id IS NULL;
DELETE FROM lage WHERE abs(fortschritt) < :kandidat_parallel * len OR d > :kandidat_abstand_m;
CREATE TEMP TABLE kand AS
SELECT l.rid, l.id, l.len,
       coalesce(CASE WHEN l.fortschritt > 0 THEN g.fuehr0 ELSE g.fuehr1 END, 'Keine Radinfrastruktur vorhanden') AS fuehr,
       CASE WHEN l.fortschritt > 0 THEN g.source ELSE g.target END AS von,
       CASE WHEN l.fortschritt > 0 THEN g.target ELSE g.source END AS nach,
       g.len * ((CASE WHEN l.fortschritt > 0 THEN g.faktor0 ELSE g.faktor1 END) + l.zusatz_je_m) + l.umweg AS kosten
FROM lage l JOIN routing_graph.g g ON g.id = l.id
WHERE (CASE WHEN l.fortschritt > 0 THEN g.faktor0 ELSE g.faktor1 END) IS NOT NULL;
CREATE INDEX ON kand (rid, von);
CREATE TEMP TABLE kand_m AS
SELECT k.rid, k.id, min(k.len) AS len, min(k.fuehr) AS fuehr, greatest(min(o.d + k.kosten + i.d - t.gesamt), 0) AS mehr,
       min(o.d + k.kosten + i.d - t.gesamt) AS mehr_roh
FROM kand k JOIN via_out o ON o.rid = k.rid AND o.node = k.von
JOIN via_in i ON i.rid = k.rid AND i.teil = o.teil AND i.node = k.nach JOIN via_teil t ON t.rid = k.rid AND t.teil = o.teil
GROUP BY 1, 2;

-- 3. je RVN-Kante, Richtung und Führungsform: x50
CREATE TEMP TABLE route_rvn AS SELECT DISTINCT rid, rvn_id, ri FROM rvn_stuecke;
CREATE INDEX ON route_rvn (rid, rvn_id);
CREATE TEMP TABLE kand_rvn AS
SELECT rr.rvn_id, rr.ri, m.fuehr, m.id, min(m.mehr) AS mehr, min(m.len) AS len
FROM kand_m m JOIN naechste_rvn n ON n.id = m.id JOIN route_rvn rr ON rr.rid = m.rid AND rr.rvn_id = n.rvn_id
GROUP BY 1, 2, 3, 4;
CREATE TABLE kandidat AS
SELECT rvn_id, ri, fuehr, min(mehr) FILTER (WHERE kum >= :kandidat_abdeckung * rlen) AS x50, min(mehr) AS x_min, count(*) AS kanten
FROM (SELECT k.*, ST_Length(e.geom) AS rlen, sum(k.len) OVER (PARTITION BY k.rvn_id, k.ri, k.fuehr ORDER BY k.mehr, k.id) AS kum
      FROM kand_rvn k JOIN matching.reference_edges e ON e.id = k.rvn_id) x
GROUP BY 1, 2, 3;
CREATE INDEX ON kandidat (rvn_id, ri);

-- 4. Wahl
CREATE TEMP TABLE wahl AS
SELECT DISTINCT ON (e.rvn_id, e.ri) e.rvn_id, e.ri, k.fuehr, k.x50
FROM ergebnis e JOIN kandidat k ON k.rvn_id = e.rvn_id AND k.ri = e.ri
WHERE k.x50 <= :kandidat_mehr AND (pg_temp.stufe(k.fuehr) < pg_temp.stufe(e.fuehr_weg)
    OR :vorrang AND ((k.fuehr = 'Geschützter Radfahrstreifen' AND e.fuehr_weg LIKE 'Bussonderfahrstreifen%')
        OR (k.fuehr LIKE 'Bussonderfahrstreifen%' OR k.fuehr LIKE 'Radfahrstreifen mit Linienverkehr%') AND e.fuehr_weg = 'Radweg'
           AND NOT EXISTS (SELECT 1 FROM rvn_stuecke s JOIN bikegraph.input_edges i ON i.input_ref = s.objekt
                           WHERE s.rvn_id = e.rvn_id AND s.ri = e.ri AND s.fuehr = 'Radweg'
                             AND i.attrs->>'tilda_traffic_sign' ~ '(^|[^0-9])(237|240|241)')))
ORDER BY e.rvn_id, e.ri, pg_temp.stufe(k.fuehr), k.x50;
UPDATE ergebnis e SET fuehr = coalesce(w.fuehr, e.fuehr_weg), kandidat = w.rvn_id IS NOT NULL, kandidat_mehr = round(w.x50::numeric)
FROM ergebnis x LEFT JOIN wahl w ON w.rvn_id = x.rvn_id AND w.ri = x.ri
WHERE x.rvn_id = e.rvn_id AND x.ri = e.ri;

\echo 'Kandidaten: Teilrouten, Kandidatenkanten, davon mit negativen Mehrkosten (geglättet), davon auf Routen aus Teilrouten, RVN-Kantenrichtungen gewechselt'
SELECT (SELECT count(*) FROM via_teil) AS teilrouten, (SELECT count(*) FROM kand_m) AS kandidatenkanten,
       (SELECT count(*) FROM kand_m WHERE mehr_roh < -1) AS negativ,
       (SELECT count(*) FROM kand_m m WHERE m.mehr_roh < -1 AND m.rid IN (SELECT rid FROM teilroute)) AS negativ_teilrouten,
       (SELECT count(*) FROM ergebnis WHERE kandidat) AS gewechselt;
\echo 'Wechsel: Führungsform aus Teil 3 -> Kandidat'
SELECT fuehr_weg, fuehr, count(*) FROM ergebnis WHERE kandidat GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 10;
