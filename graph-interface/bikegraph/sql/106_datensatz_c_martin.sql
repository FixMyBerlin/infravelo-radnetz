-- Datensatz C der Baseline und des neuen Laufs sowie ihre Abweichungen für Martin (nach compare_c.sh).
-- Eingang: bikegraph.c_base (Baseline), bikegraph.c_cand (neuer Datensatz C), bikegraph.c_faelle (Urteile je
-- abweichender Kanten-Richtung), alle aus compare_c.sh.
-- Ausgang (Schema datensatz_c):
--   baseline_c  je RVN-Kante und Richtung die Führungsform der Baseline (Geometrie der RVN-Kante)
--   new_c       dasselbe für den neuen Datensatz C
--   diff_c      nur Kanten-Richtungen mit anderer Führungsform (oder nur in einem der beiden): beide Werte, Urteil und
--               Regel aus compare_c.sh, beteiligte TILDA-Objekte; nur Richtungen, die das RVN vorsieht (R- und G-Kanten
--               nur ri 0, wie sql/70)
--   baseline_wins  Teil von diff_c mit Urteil Baseline (Baseline besser)
--   neu_wins       Teil von diff_c mit Urteil Kandidat (neuer Datensatz besser)
CREATE SCHEMA IF NOT EXISTS datensatz_c;
BEGIN;
DROP TABLE IF EXISTS datensatz_c.baseline_c, datensatz_c.new_c, datensatz_c.diff_c, datensatz_c.baseline_wins, datensatz_c.neu_wins;

CREATE TABLE datensatz_c.baseline_c AS
SELECT row_number() OVER (ORDER BY element_nr, ri)::bigint AS id, element_nr, ri::int AS ri, strassenname, fuehr, pflicht, breite, ofm,
       protek, tilda_id, tilda_ids, tilda_category, hmm_regel, tilda_link, ST_Multi(geom)::geometry(MultiLineString, 25833) AS geom
FROM bikegraph.c_base;
CREATE TABLE datensatz_c.new_c AS
SELECT row_number() OVER (ORDER BY element_nr, ri)::bigint AS id, element_nr, ri::int AS ri, strassenname, fuehr, pflicht, breite, ofm,
       protek, tilda_id, tilda_ids, tilda_category, hmm_regel, tilda_link, ST_Multi(geom)::geometry(MultiLineString, 25833) AS geom
FROM bikegraph.c_cand;

CREATE TABLE datensatz_c.diff_c AS
SELECT row_number() OVER (ORDER BY coalesce(b.element_nr, c.element_nr), coalesce(b.ri, c.ri))::bigint AS id,
       coalesce(b.element_nr, c.element_nr) AS element_nr, coalesce(b.ri, c.ri)::int AS ri, coalesce(b.strassenname, c.strassenname) AS strassenname,
       b.fuehr AS fuehr_baseline, c.fuehr AS fuehr_neu, b.tilda_ids AS tilda_ids_baseline, c.tilda_ids AS tilda_ids_neu,
       coalesce(f.urteil, CASE WHEN b.element_nr IS NULL THEN 'nur neu' WHEN c.element_nr IS NULL THEN 'nur Baseline' END) AS urteil,
       f.regel, round(f.m, 1) AS laenge_m, coalesce(b.tilda_link, c.tilda_link) AS tilda_link,
       ST_Multi(coalesce(b.geom, c.geom))::geometry(MultiLineString, 25833) AS geom
FROM bikegraph.c_base b FULL JOIN bikegraph.c_cand c ON c.element_nr = b.element_nr AND c.ri = b.ri
LEFT JOIN bikegraph.c_faelle f ON f.element_nr = coalesce(b.element_nr, c.element_nr) AND f.ri = coalesce(b.ri, c.ri)
WHERE b.fuehr IS DISTINCT FROM c.fuehr
  AND NOT (coalesce(b.ri, c.ri) = 1 AND coalesce(b.element_nr, c.element_nr) IN
           (SELECT element_nr FROM matching.reference_edges WHERE verkehrsrichtung IN ('R', 'G')));

CREATE TABLE datensatz_c.baseline_wins AS SELECT * FROM datensatz_c.diff_c WHERE urteil = 'Baseline';
CREATE TABLE datensatz_c.neu_wins AS SELECT * FROM datensatz_c.diff_c WHERE urteil = 'Kandidat';

ALTER TABLE datensatz_c.baseline_c ADD PRIMARY KEY (id);
ALTER TABLE datensatz_c.new_c ADD PRIMARY KEY (id);
ALTER TABLE datensatz_c.diff_c ADD PRIMARY KEY (id);
ALTER TABLE datensatz_c.baseline_wins ADD PRIMARY KEY (id);
ALTER TABLE datensatz_c.neu_wins ADD PRIMARY KEY (id);
CREATE INDEX ON datensatz_c.baseline_c USING gist (geom);
CREATE INDEX ON datensatz_c.new_c USING gist (geom);
CREATE INDEX ON datensatz_c.diff_c USING gist (geom);
CREATE INDEX ON datensatz_c.baseline_wins USING gist (geom);
CREATE INDEX ON datensatz_c.neu_wins USING gist (geom);
COMMIT;
ANALYZE datensatz_c.baseline_c, datensatz_c.new_c, datensatz_c.diff_c, datensatz_c.baseline_wins, datensatz_c.neu_wins;

SELECT 'baseline_c' AS tabelle, count(*) FROM datensatz_c.baseline_c UNION ALL SELECT 'new_c', count(*) FROM datensatz_c.new_c
UNION ALL SELECT 'diff_c', count(*) FROM datensatz_c.diff_c UNION ALL SELECT 'baseline_wins', count(*) FROM datensatz_c.baseline_wins
UNION ALL SELECT 'neu_wins', count(*) FROM datensatz_c.neu_wins;
SELECT urteil, count(*) AS richtungen, round(sum(laenge_m) / 1000, 1) AS km FROM datensatz_c.diff_c GROUP BY 1 ORDER BY 2 DESC;
