-- Routing der RVN-Abschnitte, Teil 5 (abschnitte.sh, ganz am Ende): Nachbearbeitung der Geometrie. Kanten der Wege, die
-- über ein an der Straßenmittellinie kartiertes Seitenobjekt laufen (Radfahrstreifen, Schutzstreifen, Busspur u. ä.),
-- werden um dessen Versatz aus TILDA (halbe Straßenbreite, routing_graph.g versatz0/versatz1 aus public.routing
-- tags.offset, siehe graph.sql) auf seine Seite verschoben, damit die Routen dort liegen, wo der Radverkehr fährt.
-- Nur Darstellung: Kosten, Nähte, Projektion auf das RVN (rvn_stuecke) und Ergebnis bleiben auf der Mittellinie
-- (geom); die versetzte Linie steht daneben in geom_versetzt.
-- Vorgehen je Route (pfad, Kanten in Fahrtrichtung):
-- 1. Läufe: aufeinanderfolgende Kanten mit demselben Versatz (auf 1 cm) bilden einen Lauf; ein Lauf endet auch an einer
--    virtuellen Kante (edge < 0).
-- 2. Jeder Lauf mit Versatz wird als eine Linie versetzt (ST_OffsetCurve, Gehrung), damit an Knicken zwischen zwei
--    Kanten weder Lücken noch Überlappungen entstehen. Gibt der Versatz keine einfache Linie (z. B. enge Schleife) oder
--    schrumpft sie auf weniger als die Hälfte, bleibt der Lauf unversetzt.
-- 3. Zurück auf die Kanten: jede Kante bekommt das Stück der versetzten Linie nach ihrem Längenanteil im Lauf.
-- 4. Übergänge: endet die vorige Kante woanders, als die nächste beginnt (Wechsel von Seitenobjekt zu Mittellinie oder
--    separatem Weg, Seitenwechsel an Kreuzungen), werden beide Kanten um je uebergang_faktor x Sprung / 2 gekürzt
--    (höchstens 45 % der Kante) und mit einer S-Kurve (kubische Bézierkurve entlang der Richtung beider Linien)
--    verbunden: weicher Schwenk statt Sprung. Die versetzten Routen sind damit lückenlos.
-- Eingang: pfad (Teil 2, ggf. geglättet in Teil 2b), abschnitt_pfad, abschnitt_route, kreuzung_pfad, kreuzung_route
-- (letzter Teil 3), routing_graph.g
-- Ausgang (Schema :schema): pfad_versatz (rid, seq, kante, ri, versatz, geom versetzt); Spalte geom_versetzt in
-- abschnitt_pfad, abschnitt_route, kreuzung_pfad, kreuzung_route
-- psql-Variablen: schema (Standard routing_abschnitte), versatz_faktor (Standard 1; 0 = nicht versetzen),
-- uebergang_faktor (Länge eines Übergangs je m Sprung, Standard 4: 3 m Versatz -> 12 m Kurve; 1 entspricht im Mittel 45°)
\if :{?schema} \else \set schema routing_abschnitte \endif
\if :{?uebergang_faktor} \else \set uebergang_faktor 4 \endif
\if :{?versatz_faktor} \else \set versatz_faktor 1 \endif
SET search_path TO :"schema", public;
DROP TABLE IF EXISTS pfad_versatz;

-- 1. Kanten der Wege in Fahrtrichtung mit Versatz (+ links / - rechts) und Lauf
CREATE TEMP TABLE pk AS
SELECT p.rid, p.seq, p.edge AS kante, CASE WHEN p.node = g.source THEN 0 ELSE 1 END AS ri,
       coalesce(round((CASE WHEN p.node = g.source THEN g.versatz0 ELSE g.versatz1 END * :versatz_faktor)::numeric, 2), 0)::float8 AS versatz,
       CASE WHEN p.node = g.source THEN g.geom ELSE ST_Reverse(g.geom) END AS geom
FROM pfad p JOIN routing_graph.g g ON g.id = p.edge
WHERE p.edge >= 0;
CREATE TEMP TABLE pl AS
SELECT x.*, sum(x.neu) OVER (PARTITION BY x.rid ORDER BY x.seq) AS lauf
FROM (SELECT k.*, CASE WHEN lag(k.seq) OVER w = k.seq - 1 AND lag(k.versatz) OVER w = k.versatz THEN 0 ELSE 1 END AS neu,
             ST_Length(k.geom) AS len
      FROM pk k WINDOW w AS (PARTITION BY k.rid ORDER BY k.seq)) x;
CREATE INDEX ON pl (rid, lauf);
ANALYZE pl;

-- 2. Läufe mit Versatz als eine Linie versetzen
CREATE TEMP TABLE lauf AS
SELECT rid, lauf, min(versatz) AS versatz, sum(len) AS len, ST_RemoveRepeatedPoints(ST_MakeLine(geom ORDER BY seq)) AS linie
FROM pl WHERE versatz <> 0 GROUP BY 1, 2;
ALTER TABLE lauf ADD COLUMN versetzt geometry(LineString, 25833);
WITH o AS (
    SELECT rid, lauf, linie, len, ST_LineMerge(ST_OffsetCurve(linie, versatz, 'quad_segs=4 join=mitre mitre_limit=2.0')) AS v
    FROM lauf
), einfach AS (
    -- ST_OffsetCurve dreht die Linie je nach PostGIS/GEOS-Version bei negativem Versatz um: wieder in Fahrtrichtung
    SELECT rid, lauf, CASE WHEN ST_Distance(ST_StartPoint(v), ST_StartPoint(linie)) > ST_Distance(ST_EndPoint(v), ST_StartPoint(linie))
                           THEN ST_Reverse(v) ELSE v END AS v
    FROM o WHERE GeometryType(v) = 'LINESTRING' AND ST_Length(v) >= 0.5 * len
)
UPDATE lauf l SET versetzt = e.v FROM einfach e WHERE e.rid = l.rid AND e.lauf = l.lauf;
CREATE INDEX ON lauf (rid, lauf);
ANALYZE lauf;

-- 3. Stück je Kante nach Längenanteil im Lauf
CREATE TEMP TABLE stueck AS
SELECT p.rid, p.seq, p.kante, p.ri, p.versatz, l.versetzt IS NOT NULL AS versetzt,
       CASE WHEN l.versetzt IS NOT NULL AND p.len > 0
            THEN ST_LineSubstring(l.versetzt, least(1.0, (p.vor) / l.len), least(1.0, (p.vor + p.len) / l.len))
            ELSE p.geom END AS geom
FROM (SELECT pl.*, sum(pl.len) OVER (PARTITION BY pl.rid, pl.lauf ORDER BY pl.seq) - pl.len AS vor FROM pl) p
LEFT JOIN lauf l ON l.rid = p.rid AND l.lauf = p.lauf;

-- 4. Übergänge: Sprung zwischen dem Ende der vorigen Kante und dem Anfang der nächsten als S-Kurve
-- Kürzung: die nächste Kante am Anfang, die vorige am Ende um je uebergang_faktor x Sprung / 2 (höchstens 45 % der Kante)
CREATE TEMP TABLE st AS
SELECT x.*, CASE WHEN x.vorige_seq = x.seq - 1 THEN ST_Distance(x.vorige_ende, ST_StartPoint(x.geom)) ELSE 0 END AS sprung
FROM (SELECT s.*, ST_Length(s.geom) AS glen, lag(s.seq) OVER w AS vorige_seq, lag(ST_EndPoint(s.geom)) OVER w AS vorige_ende
      FROM stueck s WHERE GeometryType(s.geom) = 'LINESTRING' AND ST_Length(s.geom) > 0
      WINDOW w AS (PARTITION BY s.rid ORDER BY s.seq)) x;
CREATE TEMP TABLE kurz AS
SELECT y.*, ST_LineSubstring(y.geom, y.ab / y.glen, 1 - y.bis / y.glen) AS kg
FROM (SELECT t.*,
             CASE WHEN t.sprung > 0.01 THEN least(:uebergang_faktor * t.sprung / 2, 0.45 * t.glen) ELSE 0 END AS ab,
             CASE WHEN lead(t.seq) OVER w = t.seq + 1 AND lead(t.sprung) OVER w > 0.01
                  THEN least(:uebergang_faktor * lead(t.sprung) OVER w / 2, 0.45 * t.glen) ELSE 0 END AS bis
      FROM st t WINDOW w AS (PARTITION BY t.rid ORDER BY t.seq)) y;
-- Kubische Bézierkurve p -> q mit den Kontrollpunkten c1, c2 (n Teilstücke)
CREATE FUNCTION pg_temp.bezier(p geometry, c1 geometry, c2 geometry, q geometry, n int) RETURNS geometry
LANGUAGE sql IMMUTABLE AS $$
    SELECT ST_SetSRID(ST_MakeLine(ST_MakePoint(
               (1 - t) ^ 3 * ST_X(p) + 3 * (1 - t) ^ 2 * t * ST_X(c1) + 3 * (1 - t) * t ^ 2 * ST_X(c2) + t ^ 3 * ST_X(q),
               (1 - t) ^ 3 * ST_Y(p) + 3 * (1 - t) ^ 2 * t * ST_Y(c1) + 3 * (1 - t) * t ^ 2 * ST_Y(c2) + t ^ 3 * ST_Y(q))
               ORDER BY i), ST_SRID(p))
    FROM (SELECT i, i::float8 / n AS t FROM generate_series(0, n) i) s
$$;
-- Kurve vom gekürzten Ende der vorigen Kante (p, Richtung ihres letzten Stücks) zum gekürzten Anfang der nächsten (q,
-- Richtung ihres ersten Stücks); die Kontrollpunkte liegen 0.4 x |pq| entlang dieser Richtungen. Auf gerader Straße ist
-- das ein sinusähnlicher Schwenk, an Abbiegungen eine runde Ecke. Die Kurve gehört zur nächsten Kante.
CREATE TEMP TABLE kurve AS
SELECT z.rid, z.seq,
       pg_temp.bezier(z.p, ST_Translate(z.p, z.k * sin(coalesce(z.az_p, z.az_pq)), z.k * cos(coalesce(z.az_p, z.az_pq))),
                      ST_Translate(z.q, -z.k * sin(coalesce(z.az_q, z.az_pq)), -z.k * cos(coalesce(z.az_q, z.az_pq))), z.q, 12) AS geom
FROM (SELECT a.rid, a.seq, ST_EndPoint(v.kg) AS p, ST_StartPoint(a.kg) AS q,
             0.4 * ST_Distance(ST_EndPoint(v.kg), ST_StartPoint(a.kg)) AS k,
             ST_Azimuth(ST_PointN(v.kg, ST_NPoints(v.kg) - 1), ST_EndPoint(v.kg)) AS az_p,
             ST_Azimuth(ST_StartPoint(a.kg), ST_PointN(a.kg, 2)) AS az_q,
             ST_Azimuth(ST_EndPoint(v.kg), ST_StartPoint(a.kg)) AS az_pq
      FROM kurz a JOIN kurz v ON v.rid = a.rid AND v.seq = a.seq - 1
      WHERE a.sprung > 0.01 AND GeometryType(a.kg) = 'LINESTRING' AND GeometryType(v.kg) = 'LINESTRING') z;
CREATE TABLE pfad_versatz AS
SELECT a.rid, a.seq, a.kante, a.ri, a.versatz, c.geom IS NOT NULL AS uebergang,
       (CASE WHEN c.geom IS NOT NULL THEN ST_RemoveRepeatedPoints(ST_MakeLine(c.geom, a.kg)) ELSE a.kg END)::geometry(LineString, 25833) AS geom
FROM kurz a LEFT JOIN kurve c ON c.rid = a.rid AND c.seq = a.seq
WHERE GeometryType(a.kg) = 'LINESTRING';
ALTER TABLE pfad_versatz ADD PRIMARY KEY (rid, seq);
ANALYZE pfad_versatz;

-- Ausgang: versetzte Linie neben geom
ALTER TABLE abschnitt_pfad ADD COLUMN IF NOT EXISTS geom_versetzt geometry(LineString, 25833);
UPDATE abschnitt_pfad a SET geom_versetzt = v.geom FROM pfad_versatz v WHERE v.rid = a.rid AND v.seq = a.seq;
UPDATE abschnitt_pfad SET geom_versetzt = geom WHERE geom_versetzt IS NULL;
ALTER TABLE kreuzung_pfad ADD COLUMN IF NOT EXISTS geom_versetzt geometry(LineString, 25833);
UPDATE kreuzung_pfad k SET geom_versetzt = v.geom FROM pfad_versatz v WHERE v.rid = k.rid AND v.seq = k.seq;
UPDATE kreuzung_pfad SET geom_versetzt = geom WHERE geom_versetzt IS NULL;
ALTER TABLE abschnitt_route ADD COLUMN IF NOT EXISTS geom_versetzt geometry(MultiLineString, 25833);
UPDATE abschnitt_route r SET geom_versetzt = p.geom
FROM (SELECT abschnitt, rid, rolle, ST_Multi(ST_LineMerge(ST_Collect(geom_versetzt ORDER BY seq)))::geometry(MultiLineString, 25833) AS geom
      FROM abschnitt_pfad GROUP BY 1, 2, 3) p
WHERE p.abschnitt = r.abschnitt AND p.rid = r.rid AND p.rolle = r.rolle;
ALTER TABLE kreuzung_route ADD COLUMN IF NOT EXISTS geom_versetzt geometry(MultiLineString, 25833);
UPDATE kreuzung_route r SET geom_versetzt = p.geom
FROM (SELECT rid, ST_Multi(ST_LineMerge(ST_Collect(geom_versetzt ORDER BY seq)))::geometry(MultiLineString, 25833) AS geom
      FROM kreuzung_pfad GROUP BY 1) p
WHERE p.rid = r.rid;

\echo 'Versatz der Routen: Kanten der Wege, davon versetzt, Läufe mit Versatz, davon unversetzt geblieben (keine einfache Linie), Übergänge'
SELECT (SELECT count(*) FROM pk) AS kanten, (SELECT count(*) FROM stueck WHERE versetzt) AS versetzt,
       (SELECT count(*) FROM lauf) AS laeufe, (SELECT count(*) FROM lauf WHERE versetzt IS NULL) AS laeufe_unversetzt,
       (SELECT count(*) FROM pfad_versatz WHERE uebergang) AS uebergaenge;
