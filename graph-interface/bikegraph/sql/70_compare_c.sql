-- Fallweiser Vergleich zweier Ergebnisse (Datensatz C) je Kante und Richtung mit abweichender Führungsform.
-- Bewertet wird jede Seite an den OSM-Daten, unabhängig vom Verfahren:
--   Richtung  ein Einrichtungs-Gewinner (TILDA oneway = yes) muss in Fahrtrichtung der Kante zeigen
--   Lage      Anteil der RVN-Kante (Punkte alle 5 m), der höchstens lage_m neben einem Gewinner liegt
--   Rang      wie Stufe 7: Radinfrastruktur (1) vor Mischverkehr (2) vor sonstigen Wegen (3); "Keine Radinfrastruktur" 4
-- Urteil (erste zutreffende Regel):
--   1 Richtung  nur eine Seite hat einen Gewinner gegen die Fahrtrichtung -> die andere
--   2 Lage      eine Seite liegt zu höchstens 30 % neben der Kante, die andere zu mindestens 60 % -> die andere
--   3 Lücke     eine Seite hat "Keine Radinfrastruktur", die andere einen plausiblen Gewinner (Lage >= 60 %) -> die andere
--   4 Rang      beide plausibel (Richtung passt, Lage >= 50 %) -> die mit dem besseren Rang
--   sonst unklar
-- Verglichen werden nur Richtungen, die das RVN vorsieht (verkehrsrichtung in matching.reference_edges): B und leer
-- beide, R und G nur ri 0 (die Vorverarbeitung dreht G-Geometrien um, enrich_rvn_with_detailnetz.py).
-- psql-Variablen: base, cand (Tabellen mit element_nr, ri, fuehr, tilda_id, tilda_link, geom in EPSG:25833), out, lage_m
DROP TABLE IF EXISTS :out;
CREATE TEMP TABLE rvn_einrichtung AS
SELECT DISTINCT element_nr FROM matching.reference_edges WHERE verkehrsrichtung IN ('R', 'G');
CREATE INDEX ON rvn_einrichtung (element_nr);
CREATE TEMP TABLE d AS
SELECT b.element_nr, b.ri, ST_Length(b.geom) AS m, b.geom, b.fuehr AS fuehr_base, c.fuehr AS fuehr_cand,
       b.tilda_id AS ids_base, c.tilda_id AS ids_cand, COALESCE(c.tilda_link, b.tilda_link) AS tilda_link,
       -- Fahrtrichtung: ri 0 entlang der Geometrie, 1 dagegen
       CASE WHEN b.ri = 0 THEN ST_LineMerge(b.geom) ELSE ST_Reverse(ST_LineMerge(b.geom)) END AS travel
FROM :base b JOIN :cand c USING (element_nr, ri)
WHERE b.fuehr IS DISTINCT FROM c.fuehr
  AND NOT (b.ri = 1 AND b.element_nr IN (SELECT element_nr FROM rvn_einrichtung));

CREATE TEMP TABLE rank_of (fuehr text, rang int);
INSERT INTO rank_of VALUES
  ('Radfahrstreifen', 1), ('Radfahrstreifen mit Linienverkehr frei (Z237 mit Z1026-32)', 1),
  ('Bussonderfahrstreifen mit Radverkehr frei (Z245 mit Z1022‐10)', 1), ('Geschützter Radfahrstreifen', 1),
  ('Schutzstreifen', 1), ('Fahrradstraße /-zone (Z 244)', 1), ('Radweg', 1), ('Gemeinsamer Geh- und Radweg mit Z240', 1),
  ('Gehweg mit Zusatzzeichen "Radverkehr frei" (Z239 mit Z1022-10)', 1), ('Fußgängerzone "Radverkehr frei" (Z242 mit Z1022-10)', 1),
  ('Kreuzungsweg', 1), ('[TODO] Klärung notwendig', 1), ('Mischverkehr mit motorisiertem Verkehr', 2),
  ('Keine Radinfrastruktur vorhanden', 4);

-- Gewinner je Seite: Geometrie aus dem TILDA-Routing (Seitenobjekte auf der Mittellinie des Elternwegs, linke Seite
-- umgedreht, also in Fahrtrichtung des Streifens)
CREATE TEMP TABLE w AS
SELECT d.element_nr, d.ri, s.seite, x.id, ST_Transform(r.geom, 25833) AS g, r.tags->>'oneway' = 'yes' AS oneway
FROM d
CROSS JOIN LATERAL (VALUES ('base', d.ids_base), ('cand', d.ids_cand)) s(seite, ids)
CROSS JOIN LATERAL unnest(string_to_array(s.ids, ';')) x(id)
JOIN public.routing r ON r.id = x.id;
CREATE INDEX ON w (element_nr, ri, seite);

CREATE TEMP TABLE pts AS
SELECT d.element_nr, d.ri, (ST_DumpPoints(ST_LineInterpolatePoints(x.geom, least(1, 5 / greatest(ST_Length(x.geom), 5))))).geom AS p
FROM d CROSS JOIN LATERAL ST_Dump(d.travel) x WHERE ST_Length(x.geom) > 0;

CREATE TEMP TABLE side_ev AS
SELECT d.element_nr, d.ri, s.seite,
       -- Lage: Anteil der Punkte nahe einem Gewinner
       (SELECT avg((EXISTS (SELECT 1 FROM w WHERE w.element_nr = d.element_nr AND w.ri = d.ri AND w.seite = s.seite
                            AND ST_DWithin(w.g, p.p, :lage_m)))::int)
        FROM pts p WHERE p.element_nr = d.element_nr AND p.ri = d.ri) AS lage,
       -- Richtung: ein Einrichtungs-Gewinner, der in seinem nahen Abschnitt gegen die Fahrtrichtung läuft
       EXISTS (SELECT 1 FROM w
               CROSS JOIN LATERAL (SELECT ST_LineLocatePoint(w.g, ST_StartPoint(ST_Intersection(d.travel, ST_Buffer(w.g, :lage_m)))) AS f1,
                                          ST_LineLocatePoint(w.g, ST_EndPoint(ST_LineMerge(ST_Intersection(d.travel, ST_Buffer(w.g, :lage_m))))) AS f2) f
               WHERE w.element_nr = d.element_nr AND w.ri = d.ri AND w.seite = s.seite AND w.oneway
                 AND ST_Intersects(d.travel, ST_Buffer(w.g, :lage_m)) AND f.f2 < f.f1 - 0.02) AS gegen_richtung
FROM d CROSS JOIN (VALUES ('base'), ('cand')) s(seite);

CREATE TABLE :out AS
SELECT d.element_nr, d.ri, round(d.m::numeric) AS m, d.fuehr_base, d.fuehr_cand, d.ids_base, d.ids_cand,
       round(b.lage::numeric, 2) AS lage_base, round(c.lage::numeric, 2) AS lage_cand,
       b.gegen_richtung AS gegen_base, c.gegen_richtung AS gegen_cand,
       COALESCE(rb.rang, 3) AS rang_base, COALESCE(rc.rang, 3) AS rang_cand,
       v.urteil, v.regel, d.tilda_link,
       ST_Y(ST_Transform(ST_PointOnSurface(d.geom), 4326)) AS lat,
       ST_X(ST_Transform(ST_PointOnSurface(d.geom), 4326)) AS lon
FROM d
JOIN side_ev b ON b.element_nr = d.element_nr AND b.ri = d.ri AND b.seite = 'base'
JOIN side_ev c ON c.element_nr = d.element_nr AND c.ri = d.ri AND c.seite = 'cand'
LEFT JOIN rank_of rb ON rb.fuehr = d.fuehr_base
LEFT JOIN rank_of rc ON rc.fuehr = d.fuehr_cand
CROSS JOIN LATERAL (SELECT
    CASE
        WHEN b.gegen_richtung AND NOT c.gegen_richtung THEN 'Kandidat'
        WHEN c.gegen_richtung AND NOT b.gegen_richtung THEN 'Baseline'
        WHEN COALESCE(b.lage, 0) <= 0.3 AND COALESCE(c.lage, 0) >= 0.6 AND COALESCE(rb.rang, 3) <> 4 THEN 'Kandidat'
        WHEN COALESCE(c.lage, 0) <= 0.3 AND COALESCE(b.lage, 0) >= 0.6 AND COALESCE(rc.rang, 3) <> 4 THEN 'Baseline'
        WHEN rb.rang = 4 AND c.lage >= 0.6 THEN 'Kandidat'
        WHEN rc.rang = 4 AND b.lage >= 0.6 THEN 'Baseline'
        WHEN b.lage >= 0.5 AND c.lage >= 0.5 AND COALESCE(rb.rang, 3) < COALESCE(rc.rang, 3) THEN 'Baseline'
        WHEN b.lage >= 0.5 AND c.lage >= 0.5 AND COALESCE(rc.rang, 3) < COALESCE(rb.rang, 3) THEN 'Kandidat'
        ELSE 'unklar' END AS urteil,
    CASE
        WHEN b.gegen_richtung <> c.gegen_richtung THEN '1 Richtung'
        WHEN (COALESCE(b.lage, 0) <= 0.3 AND COALESCE(c.lage, 0) >= 0.6 AND COALESCE(rb.rang, 3) <> 4)
          OR (COALESCE(c.lage, 0) <= 0.3 AND COALESCE(b.lage, 0) >= 0.6 AND COALESCE(rc.rang, 3) <> 4) THEN '2 Lage'
        WHEN (rb.rang = 4 AND c.lage >= 0.6) OR (rc.rang = 4 AND b.lage >= 0.6) THEN '3 Lücke'
        WHEN b.lage >= 0.5 AND c.lage >= 0.5 AND COALESCE(rb.rang, 3) <> COALESCE(rc.rang, 3) THEN '4 Rang'
        ELSE '-' END AS regel) v;

\echo 'Urteil je abweichender Kanten-Richtung (Führungsform)'
SELECT urteil, count(*) AS kanten_richtungen, round(sum(m) / 1000, 1) AS km FROM :out GROUP BY 1 ORDER BY 1;
\echo 'nach Regel'
SELECT regel, urteil, count(*) AS kanten_richtungen, round(sum(m) / 1000, 1) AS km FROM :out GROUP BY 1, 2 ORDER BY 1, 2;
\echo 'nach Änderung (km)'
SELECT fuehr_base || '  ->  ' || fuehr_cand AS aenderung,
       round(sum(m) FILTER (WHERE urteil = 'Kandidat') / 1000, 1) AS kandidat,
       round(sum(m) FILTER (WHERE urteil = 'Baseline') / 1000, 1) AS baseline,
       round(sum(m) FILTER (WHERE urteil = 'unklar') / 1000, 1) AS unklar
FROM :out GROUP BY 1 ORDER BY sum(m) DESC LIMIT 15;
