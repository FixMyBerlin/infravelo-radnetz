-- Geometrischer Vergleich zweier Datensätze B oder C (diff_geo.sh), unabhängig von element_nr und Teilung der Kanten.
-- Eingang: :a und :b (Tabellen mit element_nr, ri, den acht Attributen, geom in EPSG:25833), geladen von diff_geo.sh.
-- Variablen: pre_* (Tabellennamen im Schema diff), sample_m (Stücklänge), tol_m (Abstand), max_winkel (Grad),
-- label_a / label_b (Namen der Seiten im Text), col_*_a / col_*_b (Spaltennamen der Werte, z. B. fuehr_2025).
-- Ausgang:
--   diff.<name>_stuecke  beide Datensätze in Stücke von sample_m Metern, je Stück Fahrtrichtung (ri 0 in Digitalisierungsrichtung,
--                 ri 1 umgekehrt)
--   diff.<name>_paare    je Stück das nächste Stück der anderen Seite: höchstens tol_m entfernt, Richtung höchstens max_winkel
--                 anders; ohne solches Stück gegen_id leer
--   diff.<name>_diff     zusammengefasste Abschnitte: art 'Attribute anders' (Werte beider Seiten, gleiche als 'identisch'),
--                 'nur in A' / 'nur in B' (Seite ohne Gegenstück, Werte der anderen als 'fehlt'); dazu simplestyle-Felder
--   diff.<name>_zusammenfassung  km je art und je Attribut
\set ON_ERROR_STOP on
CREATE OR REPLACE FUNCTION pg_temp.zahl_oder_text(t text) RETURNS text LANGUAGE sql IMMUTABLE AS
$$ SELECT CASE WHEN t ~ '^-?[0-9]+(\.[0-9]+)?$' THEN trim_scale(t::numeric)::text ELSE t END $$;

DROP TABLE IF EXISTS diff.:"pre_stuecke", diff.:"pre_paare", diff.:"pre_diff", diff.:"pre_zusammenfassung";

CREATE TABLE diff.:"pre_stuecke" AS
WITH l AS (
    SELECT 'a'::text AS seite, element_nr, ri, fuehr, pflicht, breite, ofm, farbe, protek, trennstreifen, nutz_beschr,
           (ST_Dump(ST_LineMerge(geom))).geom AS g FROM :a
    UNION ALL
    SELECT 'b', element_nr, ri, fuehr, pflicht, breite, ofm, farbe, protek, trennstreifen, nutz_beschr,
           (ST_Dump(ST_LineMerge(geom))).geom FROM :b)
SELECT row_number() OVER () AS id, l.seite, l.element_nr, l.ri, l.fuehr, l.pflicht, l.breite, l.ofm, l.farbe, l.protek,
       l.trennstreifen, l.nutz_beschr, s.g AS geom, ST_LineInterpolatePoint(s.g, 0.5) AS mitte, ST_Length(s.g) AS m,
       CASE WHEN l.ri = 1 THEN ST_Azimuth(ST_EndPoint(s.g), ST_StartPoint(s.g))
            ELSE ST_Azimuth(ST_StartPoint(s.g), ST_EndPoint(s.g)) END AS kurs
FROM l, LATERAL (
    SELECT ST_LineSubstring(l.g, (i * :sample_m) / ST_Length(l.g), LEAST(1, ((i + 1) * :sample_m) / ST_Length(l.g))) AS g
    FROM generate_series(0, GREATEST(ceil(ST_Length(l.g) / :sample_m)::int - 1, 0)) i) s
WHERE ST_GeometryType(l.g) = 'ST_LineString' AND ST_Length(l.g) > 0 AND ST_Length(s.g) > 0.05;
CREATE INDEX ON diff.:"pre_stuecke" USING gist (geom);
CREATE INDEX ON diff.:"pre_stuecke" (seite);
ANALYZE diff.:"pre_stuecke";

CREATE TABLE diff.:"pre_paare" AS
SELECT s.id, s.seite, o.id AS gegen_id
FROM diff.:"pre_stuecke" s
LEFT JOIN LATERAL (
    SELECT x.id FROM diff.:"pre_stuecke" x
    WHERE x.seite <> s.seite AND ST_DWithin(x.geom, s.mitte, :tol_m)
      AND abs(mod((s.kurs - x.kurs + 3 * pi())::numeric, (2 * pi())::numeric) - pi()::numeric) < radians(:max_winkel)::numeric
    ORDER BY x.geom <-> s.mitte LIMIT 1) o ON true;

-- Abschnitte mit anderen Attributen (von A aus gesehen) und Stücke ohne Gegenstück (beide Seiten)
CREATE TABLE diff.:"pre_diff" AS
WITH p AS (
    SELECT a.element_nr AS element_nr_a, b.element_nr AS element_nr_b, a.ri, a.geom,
           a.fuehr fa, b.fuehr fb, a.pflicht pa, b.pflicht pb, a.breite ba, b.breite bb, a.ofm oa, b.ofm ob,
           a.farbe ca, b.farbe cb, a.protek xa, b.protek xb, a.trennstreifen ta, b.trennstreifen tb,
           a.nutz_beschr na, b.nutz_beschr nb
    FROM diff.:"pre_paare" g JOIN diff.:"pre_stuecke" a ON a.id = g.id JOIN diff.:"pre_stuecke" b ON b.id = g.gegen_id
    WHERE g.seite = 'a'),
d AS (
    SELECT *,
        fa IS DISTINCT FROM fb AS d_f, pg_temp.zahl_oder_text(ba) IS DISTINCT FROM pg_temp.zahl_oder_text(bb) AS d_b,
        pa IS DISTINCT FROM pb AS d_p, oa IS DISTINCT FROM ob AS d_o, ca IS DISTINCT FROM cb AS d_c,
        xa IS DISTINCT FROM xb AS d_x, ta IS DISTINCT FROM tb AS d_t, na IS DISTINCT FROM nb AS d_n
    FROM p),
anders AS (
    SELECT 'Attribute anders'::text AS art,
        concat_ws('; ',
            CASE WHEN d_f THEN format('Führungsform: %s → %s', coalesce(fa, 'leer'), coalesce(fb, 'leer')) END,
            CASE WHEN d_b THEN format('Breite: %s → %s', coalesce(ba, 'leer'), coalesce(bb, 'leer')) END,
            CASE WHEN d_p THEN format('Pflicht: %s → %s', coalesce(pa, 'leer'), coalesce(pb, 'leer')) END,
            CASE WHEN d_o THEN format('Oberfläche: %s → %s', coalesce(oa, 'leer'), coalesce(ob, 'leer')) END,
            CASE WHEN d_c THEN format('Farbe: %s → %s', coalesce(ca, 'leer'), coalesce(cb, 'leer')) END,
            CASE WHEN d_x THEN format('Protektion: %s → %s', coalesce(xa, 'leer'), coalesce(xb, 'leer')) END,
            CASE WHEN d_t THEN format('Trennstreifen: %s → %s', coalesce(ta, 'leer'), coalesce(tb, 'leer')) END,
            CASE WHEN d_n THEN format('Nutzungsbeschränkung: %s → %s', coalesce(na, 'leer'), coalesce(nb, 'leer')) END
        ) AS unterschied,
        element_nr_a, string_agg(DISTINCT element_nr_b, ' | ') AS element_nr_b, ri,
        round(sum(ST_Length(geom))::numeric) AS laenge_m,
        coalesce(fa, 'leer') f1, CASE WHEN d_f THEN coalesce(fb, 'leer') ELSE 'identisch' END f2,
        coalesce(ba, 'leer') b1, CASE WHEN d_b THEN coalesce(bb, 'leer') ELSE 'identisch' END b2,
        coalesce(pa, 'leer') p1, CASE WHEN d_p THEN coalesce(pb, 'leer') ELSE 'identisch' END p2,
        coalesce(oa, 'leer') o1, CASE WHEN d_o THEN coalesce(ob, 'leer') ELSE 'identisch' END o2,
        coalesce(ca, 'leer') c1, CASE WHEN d_c THEN coalesce(cb, 'leer') ELSE 'identisch' END c2,
        coalesce(xa, 'leer') x1, CASE WHEN d_x THEN coalesce(xb, 'leer') ELSE 'identisch' END x2,
        coalesce(ta, 'leer') t1, CASE WHEN d_t THEN coalesce(tb, 'leer') ELSE 'identisch' END t2,
        coalesce(na, 'leer') n1, CASE WHEN d_n THEN coalesce(nb, 'leer') ELSE 'identisch' END n2,
        ST_Multi(ST_LineMerge(ST_Union(geom))) AS geom
    FROM d
    WHERE d_f OR d_b OR d_p OR d_o OR d_c OR d_x OR d_t OR d_n
    GROUP BY element_nr_a, ri, d_f, d_b, d_p, d_o, d_c, d_x, d_t, d_n, fa, fb, ba, bb, pa, pb, oa, ob, ca, cb, xa, xb, ta, tb, na, nb),
allein AS (
    SELECT CASE s.seite WHEN 'a' THEN 'nur in ' || :'label_a' ELSE 'nur in ' || :'label_b' END AS art,
        format('kein Stück in %s bis %s m mit gleicher Richtung', CASE s.seite WHEN 'a' THEN :'label_b' ELSE :'label_a' END, :tol_m) AS unterschied,
        CASE s.seite WHEN 'a' THEN s.element_nr END AS element_nr_a, CASE s.seite WHEN 'b' THEN s.element_nr END AS element_nr_b, s.ri,
        round(sum(s.m)::numeric) AS laenge_m,
        CASE s.seite WHEN 'a' THEN coalesce(s.fuehr, 'leer') ELSE 'fehlt' END f1, CASE s.seite WHEN 'b' THEN coalesce(s.fuehr, 'leer') ELSE 'fehlt' END f2,
        CASE s.seite WHEN 'a' THEN coalesce(s.breite, 'leer') ELSE 'fehlt' END b1, CASE s.seite WHEN 'b' THEN coalesce(s.breite, 'leer') ELSE 'fehlt' END b2,
        CASE s.seite WHEN 'a' THEN coalesce(s.pflicht, 'leer') ELSE 'fehlt' END p1, CASE s.seite WHEN 'b' THEN coalesce(s.pflicht, 'leer') ELSE 'fehlt' END p2,
        CASE s.seite WHEN 'a' THEN coalesce(s.ofm, 'leer') ELSE 'fehlt' END o1, CASE s.seite WHEN 'b' THEN coalesce(s.ofm, 'leer') ELSE 'fehlt' END o2,
        CASE s.seite WHEN 'a' THEN coalesce(s.farbe, 'leer') ELSE 'fehlt' END c1, CASE s.seite WHEN 'b' THEN coalesce(s.farbe, 'leer') ELSE 'fehlt' END c2,
        CASE s.seite WHEN 'a' THEN coalesce(s.protek, 'leer') ELSE 'fehlt' END x1, CASE s.seite WHEN 'b' THEN coalesce(s.protek, 'leer') ELSE 'fehlt' END x2,
        CASE s.seite WHEN 'a' THEN coalesce(s.trennstreifen, 'leer') ELSE 'fehlt' END t1, CASE s.seite WHEN 'b' THEN coalesce(s.trennstreifen, 'leer') ELSE 'fehlt' END t2,
        CASE s.seite WHEN 'a' THEN coalesce(s.nutz_beschr, 'leer') ELSE 'fehlt' END n1, CASE s.seite WHEN 'b' THEN coalesce(s.nutz_beschr, 'leer') ELSE 'fehlt' END n2,
        ST_Multi(ST_LineMerge(ST_Union(s.geom))) AS geom
    FROM diff.:"pre_paare" g JOIN diff.:"pre_stuecke" s USING (id)
    WHERE g.gegen_id IS NULL
    GROUP BY s.seite, s.element_nr, s.ri, s.fuehr, s.breite, s.pflicht, s.ofm, s.farbe, s.protek, s.trennstreifen, s.nutz_beschr)
SELECT row_number() OVER () AS id, art, unterschied, element_nr_a AS :"col_element_nr_a", element_nr_b AS :"col_element_nr_b", ri, laenge_m,
    f1 AS :"col_fuehr_a", f2 AS :"col_fuehr_b", b1 AS :"col_breite_a", b2 AS :"col_breite_b",
    p1 AS :"col_pflicht_a", p2 AS :"col_pflicht_b", o1 AS :"col_ofm_a", o2 AS :"col_ofm_b",
    c1 AS :"col_farbe_a", c2 AS :"col_farbe_b", x1 AS :"col_protek_a", x2 AS :"col_protek_b",
    t1 AS :"col_trennstreifen_a", t2 AS :"col_trennstreifen_b", n1 AS :"col_nutz_beschr_a", n2 AS :"col_nutz_beschr_b",
    CASE WHEN art = 'Attribute anders' THEN '#f97316' WHEN art LIKE 'nur in ' || :'label_a' THEN '#dc2626' ELSE '#2563eb' END AS stroke,
    1.0 AS "stroke-opacity",
    CASE WHEN art = 'Attribute anders' THEN 4 ELSE 6 END AS "stroke-width",
    CASE WHEN art = 'Attribute anders' THEN '#f97316' WHEN art LIKE 'nur in ' || :'label_a' THEN '#dc2626' ELSE '#2563eb' END AS fill,
    0.3 AS "fill-opacity",
    geom::geometry(MultiLineString, 25833) AS geom
FROM (SELECT * FROM anders UNION ALL SELECT * FROM allein) x;
CREATE INDEX ON diff.:"pre_diff" USING gist (geom);

CREATE TABLE diff.:"pre_zusammenfassung" AS
SELECT 'Länge A (km)'::text AS was, round((sum(m) FILTER (WHERE seite = 'a') / 1000)::numeric, 1) AS km FROM diff.:"pre_stuecke"
UNION ALL SELECT 'Länge B (km)', round((sum(m) FILTER (WHERE seite = 'b') / 1000)::numeric, 1) FROM diff.:"pre_stuecke"
UNION ALL SELECT art || ' (km)', round((sum(laenge_m) / 1000)::numeric, 1) FROM diff.:"pre_diff" GROUP BY art
UNION ALL SELECT '  ' || split_part(u, ':', 1) || ' anders (km)', round((sum(laenge_m) / 1000)::numeric, 1)
    FROM diff.:"pre_diff", unnest(string_to_array(unterschied, '; ')) u WHERE art = 'Attribute anders' GROUP BY 1;
