-- Martin-Ebenen der Beurteilung (aus martin.sql nach routing_rvn): je RVN-Kantenrichtung, deren Führungsform vom Routing
-- anders ist als v7, ein Urteil aus den Belegen vor Ort (wie sonderfaelle/werkzeug/beurteilung.sql): offene Kanten des
-- Routing-Graphen bis 30 m von der RVN-Kante, parallel (Fortschritt >= 0.87 x Länge), Mitte innerhalb der Kante projiziert,
-- in Fahrtrichtung offen; Länge und mittlerer Abstand je Form. Kreuzungsweg ohne Parallelbedingung.
--   routing_urteil_routing    Routing richtig
--   routing_urteil_v7         v7 richtig
--   routing_urteil_grenzfall  Grenzfall, TILDA-Daten ([TODO]) und ohne v7 (Spalte urteil)
CREATE TEMP TABLE bu_d AS
SELECT r.rvn_id, r.ri, r.element_nr, r.routing, r.v7, r.henri, r.rueckfall, r.unbequem, r.kandidat, r.abdeckung,
       e.geom, ST_Length(e.geom) AS len, e.strassenname AS strasse
FROM routing_martin.routing_rvn r JOIN matching.reference_edges e ON e.id = r.rvn_id WHERE r.routing IS DISTINCT FROM r.v7;
CREATE INDEX ON bu_d USING gist (geom);
CREATE TEMP TABLE bu_kk AS
SELECT d.rvn_id, d.ri, g.id, g.len, ST_Distance(ST_LineInterpolatePoint(g.geom, 0.5), d.geom) AS dist,
       (ST_LineLocatePoint(d.geom, ST_EndPoint(g.geom)) - ST_LineLocatePoint(d.geom, ST_StartPoint(g.geom))) * d.len AS fort,
       ST_LineLocatePoint(d.geom, ST_LineInterpolatePoint(g.geom, 0.5)) AS lage, g.fuehr0, g.fuehr1, g.faktor0, g.faktor1
FROM bu_d d JOIN routing_graph.g g ON ST_DWithin(g.geom, d.geom, 30);
CREATE TEMP TABLE bu_kante AS
SELECT rvn_id, ri, id, len, dist, fort,
       coalesce(CASE WHEN (fort > 0) = (ri = 0) THEN fuehr0 ELSE fuehr1 END, 'Keine Radinfrastruktur vorhanden') AS fuehr,
       CASE WHEN (fort > 0) = (ri = 0) THEN faktor0 ELSE faktor1 END AS faktor
FROM bu_kk WHERE lage > 0.001 AND lage < 0.999;
DELETE FROM bu_kante WHERE faktor IS NULL OR (abs(fort) < 0.87 * len AND fuehr <> 'Kreuzungsweg');
CREATE TEMP TABLE bu_beleg AS
SELECT rvn_id, ri, fuehr, sum(len) AS m, sum(len * dist) / sum(len) AS d FROM bu_kante GROUP BY 1, 2, 3;
CREATE INDEX ON bu_beleg (rvn_id, ri);
CREATE FUNCTION pg_temp.bu_stufe(f text) RETURNS int LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE WHEN f IN ('Radfahrstreifen', 'Radfahrstreifen mit Linienverkehr frei (Z237 mit Z1026-32)',
                         'Bussonderfahrstreifen mit Radverkehr frei (Z245 mit Z1022‐10)', 'Geschützter Radfahrstreifen', 'Schutzstreifen',
                         'Fahrradstraße /-zone (Z 244)', 'Radweg', 'Gemeinsamer Geh- und Radweg mit Z240',
                         'Gehweg mit Zusatzzeichen "Radverkehr frei" (Z239 mit Z1022-10)', 'Fußgängerzone "Radverkehr frei" (Z242 mit Z1022-10)',
                         'Kreuzungsweg') THEN 1
              WHEN f = 'Mischverkehr mit motorisiertem Verkehr' THEN 2
              WHEN f IS NULL OR f = 'Keine Radinfrastruktur vorhanden' THEN 4 ELSE 3 END $$;
CREATE TEMP TABLE bu_urteil AS
WITH b AS (
  SELECT d.*, br.m AS m_r, br.d AS d_r, bv.m AS m_v, bv.d AS d_v,
         least(coalesce(br.m, 0) / d.len, 1) AS c_r, least(coalesce(bv.m, 0) / d.len, 1) AS c_v,
         pg_temp.bu_stufe(d.routing) AS s_r, pg_temp.bu_stufe(d.v7) AS s_v,
         (SELECT string_agg(left(x.fuehr, 22) || ' ' || round(x.m) || ' m/' || round(x.d) || ' m', '; ' ORDER BY x.m DESC)
          FROM bu_beleg x WHERE x.rvn_id = d.rvn_id AND x.ri = d.ri) AS belege
  FROM bu_d d LEFT JOIN bu_beleg br ON br.rvn_id = d.rvn_id AND br.ri = d.ri AND br.fuehr = d.routing
  LEFT JOIN bu_beleg bv ON bv.rvn_id = d.rvn_id AND bv.ri = d.ri AND bv.fuehr = d.v7
), u AS (
  SELECT b.*, CASE
      WHEN v7 IS NULL THEN 'ohne v7|v7 hat kein Ergebnis'
      WHEN routing LIKE '[TODO]%' OR v7 LIKE '[TODO]%' THEN 'TILDA-Daten|Führungsform in TILDA ungeklärt ([TODO])'
      WHEN m_v IS NULL AND c_r >= 0.3 THEN 'Routing richtig|v7-Form liegt nicht an der Kante'
      WHEN m_r IS NULL AND c_v >= 0.3 THEN 'v7 richtig|Routing-Form liegt nicht an der Kante'
      WHEN m_v IS NULL OR m_r IS NULL THEN 'Grenzfall|schwache Belege (eine Form fehlt, die andere deckt unter 30 %)'
      WHEN s_r < s_v AND c_r >= 0.5 THEN 'Routing richtig|bessere Stufe, deckt mindestens die halbe Kante'
      WHEN s_v < s_r AND c_v >= 0.5 THEN 'v7 richtig|bessere Stufe, deckt mindestens die halbe Kante'
      WHEN s_r <> s_v THEN 'Grenzfall|bessere Stufe nur auf einem Teil der Kante'
      WHEN c_r >= 1.5 * c_v THEN 'Routing richtig|gleiche Stufe, Routing-Form deckt deutlich mehr der Kante'
      WHEN c_v >= 1.5 * c_r THEN 'v7 richtig|gleiche Stufe, v7-Form deckt deutlich mehr der Kante'
      WHEN d_r + 10 < d_v THEN 'Routing richtig|gleiche Stufe, Routing-Form deutlich näher an der RVN-Linie'
      WHEN d_v + 10 < d_r THEN 'v7 richtig|gleiche Stufe, v7-Form deutlich näher an der RVN-Linie'
      ELSE 'Grenzfall|gleiche Stufe, beide Formen ähnlich viel an der Kante' END AS u
  FROM b
)
SELECT row_number() OVER (ORDER BY rvn_id, ri)::int AS id, rvn_id, element_nr::text, ri, strasse::text, round(len::numeric) AS laenge_m,
       routing, v7, split_part(u, '|', 1) AS urteil, split_part(u, '|', 2) AS grund,
       round(m_r::numeric) AS m_routing, round(d_r::numeric) AS abstand_routing, round(m_v::numeric) AS m_v7, round(d_v::numeric) AS abstand_v7,
       belege, rueckfall, unbequem, kandidat,
       format('https://viewer.tilda-geo.de/?map=18/%s/%s', round(ST_Y(ST_Transform(ST_LineInterpolatePoint(geom, 0.5), 4326))::numeric, 5),
              round(ST_X(ST_Transform(ST_LineInterpolatePoint(geom, 0.5), 4326))::numeric, 5)) AS viewer,
       geom::geometry(LineString, 25833) AS geom
FROM u;
CREATE TABLE routing_martin.routing_urteil_routing AS SELECT * FROM bu_urteil WHERE urteil = 'Routing richtig';
CREATE TABLE routing_martin.routing_urteil_v7 AS SELECT * FROM bu_urteil WHERE urteil = 'v7 richtig';
CREATE TABLE routing_martin.routing_urteil_grenzfall AS SELECT * FROM bu_urteil WHERE urteil NOT IN ('Routing richtig', 'v7 richtig');
